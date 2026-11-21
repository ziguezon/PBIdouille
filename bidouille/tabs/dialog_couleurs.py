# -*- coding: utf-8 -*-
"""Aperçu & édition des couleurs KPI (fond/texte) de TD_Indicateurs.xlsx.

L'Excel reste la source de vérité : le dialogue lit les colonnes configurées
dans l'onglet Rapport (clé/fond/texte), montre chaque KPI avec ses pastilles et
un aperçu rendu, permet d'éditer au QColorDialog, puis réécrit UNIQUEMENT les
cellules de couleur — en CRÉANT les colonnes d'en-tête manquantes au besoin
(ex. l'Excel maison n'a qu'une colonne « couleur » : la première sauvegarde
ajoute « couleur_fill »/« couleur_text » sans toucher au reste)."""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtGui import QBrush, QColor, QFont
from qtpy.QtWidgets import (
    QColorDialog,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import backup_restore as br
import xlsx_lecture as xl
from core.theme import ACCENT, TEXT_DIM, SURFACE_ALT

COL_KPI, COL_FILL, COL_TEXT, COL_PREVIEW = range(4)


def _norm_hex(v) -> str:
    v = str(v or "").strip()
    if not v:
        return ""
    if not v.startswith("#"):
        v = "#" + v
    return v.upper()


class CouleursDialog(QDialog):
    """Édite les couleurs par KPI directement dans l'Excel TD."""

    def __init__(self, xlsx, key_col: str, fill_col: str, text_col: str,
                 model_kpis=None, parent=None, project_root=None):
        super().__init__(parent)
        self.setWindowTitle("Couleurs des KPI · " + Path(xlsx).name)
        self.resize(720, 460)
        self.xlsx = Path(xlsx)
        self.project_root = Path(project_root) if project_root else self.xlsx.parent
        self.initial = {}
        self.key_col = key_col
        self.fill_col = fill_col
        self.text_col = text_col
        self.model_kpis = list(model_kpis or [])
        # état : clé -> {"fill": hex|"", "text": hex|"", "row": n° Excel|None}
        self.state: dict = {}

        lay = QVBoxLayout(self)
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        lay.addWidget(self.lbl_info)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["KPI (mesure)", "Fond", "Texte", "Aperçu"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_KPI, QHeaderView.Stretch)
        for c in (COL_FILL, COL_TEXT, COL_PREVIEW):
            header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.cellClicked.connect(self._on_cell_clicked)
        lay.addWidget(self.table, 1)

        tip = QLabel("Cliquer sur une pastille Fond/Texte pour choisir la couleur, "
                     "clic droit conceptuel : bouton « Effacer » sur la cellule sélectionnée.")
        tip.setStyleSheet(f"color:{TEXT_DIM};")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        buttons = QHBoxLayout()
        btn_clear = QPushButton("Effacer la couleur de la cellule cliquée")
        btn_clear.clicked.connect(self._clear_current)
        buttons.addWidget(btn_clear)
        buttons.addStretch()
        self.btn_save = QPushButton("Enregistrer dans l'Excel")
        self.btn_save.clicked.connect(self._save)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.reject)
        buttons.addWidget(self.btn_save)
        buttons.addWidget(btn_close)
        lay.addLayout(buttons)

        self._last_cell = None
        self._load()

    # ---- lecture -------------------------------------------------------------

    def _load(self):
        try:
            import openpyxl
        except ImportError:
            self.lbl_info.setText("openpyxl introuvable (py -m pip install openpyxl).")
            self.btn_save.setEnabled(False)
            return
        if not self.xlsx.exists():
            self.lbl_info.setText(f"Excel introuvable : {self.xlsx}")
            self.btn_save.setEnabled(False)
            return

        # PAS data_only : on préserve les formules du classeur à la sauvegarde
        wb = openpyxl.load_workbook(self.xlsx)
        ws = wb.worksheets[0]
        headers = {}
        for c in range(1, ws.max_column + 1):
            h = ws.cell(row=1, column=c).value
            if h is not None:
                headers[str(h).strip().lower()] = c
        wb.close()

        key_c = headers.get(self.key_col.lower())
        if key_c is None:
            self.lbl_info.setText(
                f"Colonne clé « {self.key_col} » absente de {self.xlsx.name}, "
                f"colonnes trouvées : {', '.join(headers)}.")
            self.btn_save.setEnabled(False)
            return
        fill_c = headers.get(self.fill_col.lower())
        text_c = headers.get(self.text_col.lower())

        wb = openpyxl.load_workbook(self.xlsx)
        ws = wb.worksheets[0]
        for r in range(2, ws.max_row + 1):
            key = ws.cell(row=r, column=key_c).value
            if key is None or str(key).strip() == "":
                continue
            key = str(key).strip()
            self.state[key] = {
                "fill": _norm_hex(ws.cell(row=r, column=fill_c).value) if fill_c else "",
                "text": _norm_hex(ws.cell(row=r, column=text_c).value) if text_c else "",
                "row": r,
            }
            self.initial[key] = self.state[key].copy()
        wb.close()

        # KPI du modèle absents de l'Excel : montrés grisés (à ajouter dans l'Excel)
        for k in self.model_kpis:
            if k not in self.state:
                self.state[k] = {"fill": "", "text": "", "row": None}

        missing_cols = [c for c, name in ((fill_c, self.fill_col), (text_c, self.text_col)) if c is None]
        info = f"{sum(1 for s in self.state.values() if s['row'])} KPI dans l'Excel."
        if missing_cols:
            info += (f"  Colonnes « {self.fill_col} »/« {self.text_col} » absentes : elles seront "
                     "CRÉÉES à la sauvegarde (la colonne « couleur » existante n'est pas touchée).")
        self.lbl_info.setText(info)
        self._fill_table()

    # ---- table ---------------------------------------------------------------

    def _fill_table(self):
        keys = sorted(self.state, key=str.lower)
        self.table.setRowCount(len(keys))
        for i, k in enumerate(keys):
            s = self.state[k]
            name = QTableWidgetItem(k + ("" if s["row"] else "   (absent de l'Excel)"))
            name.setFlags(Qt.ItemIsEnabled)
            if not s["row"]:
                name.setForeground(QBrush(QColor(TEXT_DIM)))
                name.setToolTip("Ajouter une ligne avec cette mesure dans l'Excel "
                                "pour pouvoir lui donner des couleurs.")
            self.table.setItem(i, COL_KPI, name)
            self._set_swatch(i, COL_FILL, s["fill"], editable=bool(s["row"]))
            self._set_swatch(i, COL_TEXT, s["text"], editable=bool(s["row"]))
            self._set_preview(i, k)

    def _set_swatch(self, row: int, col: int, hexv: str, editable: bool):
        item = QTableWidgetItem(hexv if hexv else "·")
        item.setFlags(Qt.ItemIsEnabled)
        item.setTextAlignment(Qt.AlignCenter)
        if hexv:
            item.setBackground(QBrush(QColor(hexv)))
            # texte lisible sur la pastille : noir ou blanc selon la luminance
            qc = QColor(hexv)
            lum = 0.299 * qc.red() + 0.587 * qc.green() + 0.114 * qc.blue()
            item.setForeground(QBrush(QColor("#000000" if lum > 140 else "#FFFFFF")))
        else:
            item.setBackground(QBrush(QColor(SURFACE_ALT)))
            item.setForeground(QBrush(QColor(TEXT_DIM)))
        if not editable:
            item.setToolTip("Ligne absente de l'Excel, l'ajouter d'abord.")
        self.table.setItem(row, col, item)

    def _set_preview(self, row: int, key: str):
        s = self.state[key]
        item = QTableWidgetItem("  123,4  ")
        item.setFlags(Qt.ItemIsEnabled)
        item.setTextAlignment(Qt.AlignCenter)
        f = QFont()
        f.setBold(True)
        item.setFont(f)
        if s["fill"]:
            item.setBackground(QBrush(QColor(s["fill"])))
        if s["text"]:
            item.setForeground(QBrush(QColor(s["text"])))
        elif s["fill"]:
            item.setForeground(QBrush(QColor("#FFFFFF")))
        self.table.setItem(row, COL_PREVIEW, item)

    def _key_at(self, row: int) -> str:
        return sorted(self.state, key=str.lower)[row]

    def _on_cell_clicked(self, row: int, col: int):
        if col not in (COL_FILL, COL_TEXT):
            return
        self._last_cell = (row, col)
        key = self._key_at(row)
        s = self.state[key]
        if not s["row"]:
            return  # absent de l'Excel : rien à éditer
        which = "fill" if col == COL_FILL else "text"
        start = QColor(s[which]) if s[which] else QColor(ACCENT)
        chosen = QColorDialog.getColor(start, self, f"Couleur {which} · {key}")
        if not chosen.isValid():
            return
        s[which] = chosen.name().upper()
        self._set_swatch(row, col, s[which], editable=True)
        self._set_preview(row, key)

    def _clear_current(self):
        if not self._last_cell:
            return
        row, col = self._last_cell
        key = self._key_at(row)
        s = self.state[key]
        if not s["row"]:
            return
        s["fill" if col == COL_FILL else "text"] = ""
        self._set_swatch(row, col, "", editable=True)
        self._set_preview(row, key)

    # ---- écriture --------------------------------------------------------------

    def _save(self):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(self.xlsx)
        except OSError as e:
            QMessageBox.critical(self, "Excel", str(e))
            return
        ws = wb.worksheets[0]

        headers = {}
        for c in range(1, ws.max_column + 1):
            h = ws.cell(row=1, column=c).value
            if h is not None:
                headers[str(h).strip().lower()] = c

        def ensure(name: str) -> int:
            c = headers.get(name.lower())
            if c is None:                      # création de la colonne manquante
                c = ws.max_column + 1
                ws.cell(row=1, column=c, value=name)
                headers[name.lower()] = c
            return c

        colonnes_manquantes = any(n.lower() not in headers for n in (self.fill_col, self.text_col))
        fill_c = ensure(self.fill_col)
        text_c = ensure(self.text_col)

        changements = {key: [col for col in ("fill", "text") if s[col] != self.initial[key][col]]
                       for key, s in self.state.items() if key in self.initial}
        changements = {k: cols for k, cols in changements.items() if cols}
        cle = headers.get(self.key_col.lower())
        lignes = {}
        if cle:
            for r in range(2, ws.max_row + 1):
                valeur = ws.cell(r, cle).value
                if valeur is not None:
                    lignes.setdefault(str(valeur).strip(), []).append(r)
        for key, cols in changements.items():
            if len(lignes.get(key, [])) != 1:
                wb.close()
                QMessageBox.critical(self, "Excel", f"Clé « {key} » absente ou en double. Rien écrit.")
                return
            for col in cols:
                cellule = ws.cell(lignes[key][0], fill_c if col == "fill" else text_c)
                cellule.value = self.state[key][col] or None

        if not changements and not colonnes_manquantes:
            wb.close()
            return
        n = len(changements)
        session = br.BackupSession(br.backup_root(self.project_root, "_indicateurs_backups"),
                                   "Excel des indicateurs", self.project_root)
        try:
            xl._substituer(wb, self.xlsx, session.save)
        except PermissionError:
            br.abandonner(session)
            QMessageBox.critical(
                self, "Excel verrouillé",
                f"{self.xlsx.name} est ouvert dans Excel, le fermer et réessayer.")
            return
        except OSError as e:
            br.abandonner(session)
            QMessageBox.critical(self, "Erreur d'écriture", str(e))
            return
        finally:
            wb.close()

        session.close(f"{n} KPI modifiés")
        for key in changements:
            self.initial[key] = self.state[key].copy()
        QMessageBox.information(
            self, "Enregistré",
            f"{n} KPI écrits dans {self.xlsx.name} "
            f"(colonnes « {self.fill_col} » / « {self.text_col} »).\n"
            "Lancer « Colorer » pour appliquer au rapport.")
