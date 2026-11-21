# -*- coding: utf-8 -*-
"""Dialogue « Sauvegardes » : lister et RESTAURER les sauvegardes d'un projet.

Tous les outils qui écrivent dans un projet (ChopChop, Propagation, Wireframe)
copient d'abord les fichiers touchés dans un dossier horodaté, sous le dossier
parent `_backupsPBIdouille\\`. Ce dialogue les présente ensemble, la plus
récente d'abord, et remet celle qu'on choisit en place — en sauvegardant
d'abord l'état courant, pour qu'une restauration soit elle-même annulable.

Chaque outil ne garde que ses `br.MAX_SESSIONS` sauvegardes les plus récentes :
la liste ne gonfle pas, et il n'y a pas de ménage à faire à la main.

Le détail de chaque sauvegarde (quel fichier venait d'où) se déplie sous sa
ligne. Les vieilles sauvegardes, écrites avant le manifeste, sont marquées :
leur cible est reconstituée par correspondance de nom (cf. backup_restore).
"""

from __future__ import annotations

import os
from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtGui import QBrush, QColor, QFont
from qtpy.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

import backup_restore as br

try:
    from core import theme as _theme
except ImportError:  # copie isolée
    _theme = None

COL_QUOI, COL_QUAND, COL_DETAIL = range(3)


class BackupsDialog(QDialog):
    """Liste des sauvegardes du projet + bouton Restaurer."""

    def __init__(self, project_root, parent=None, on_restored=None):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.on_restored = on_restored          # rappel après restauration
        self.setWindowTitle("Sauvegardes et restauration")
        self.resize(940, 560)

        layout = QVBoxLayout(self)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Opération", "Quand", "Contenu"])
        header = self.tree.header()
        header.setSectionResizeMode(COL_QUOI, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_QUAND, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_DETAIL, QHeaderView.Stretch)
        self.tree.currentItemChanged.connect(lambda *_: self._update_button())
        layout.addWidget(self.tree, stretch=1)

        buttons = QHBoxLayout()
        btn_refresh = QPushButton("Rafraîchir")
        btn_refresh.clicked.connect(self.reload)
        btn_open = QPushButton("Ouvrir le dossier")
        btn_open.clicked.connect(self._open_folder)
        self.btn_restore = QPushButton("Restaurer cette sauvegarde")
        self.btn_restore.clicked.connect(self._restore)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        buttons.addWidget(btn_refresh)
        buttons.addWidget(btn_open)
        buttons.addStretch()
        buttons.addWidget(self.btn_restore)
        buttons.addWidget(btn_close)
        layout.addLayout(buttons)

        self.reload()

    # ---- liste ---------------------------------------------------------------

    def reload(self):
        self.tree.clear()
        self.sessions = br.list_sessions(self.project_root)
        if not self.sessions:
            self.info.setText(
                f"Aucune sauvegarde sous <b>{self.project_root}\\{br.PARENT}</b>. "
                "Les outils en créent une à chaque écriture.")
            self._update_button()
            return

        self.info.setText(
            f"<b>{len(self.sessions)} sauvegarde(s)</b> dans "
            f"<b>{br.PARENT}\\</b>, la plus récente en haut. Restaurer "
            "réécrit les fichiers listés ; l'état courant est sauvegardé "
            "avant, donc l'opération reste annulable. Chaque outil ne garde "
            f"que ses <b>{br.MAX_SESSIONS}</b> plus récentes : au-delà, la "
            "plus vieille s'efface toute seule.")

        muted = QBrush(QColor(_theme.TEXT_MUTED)) if _theme else QBrush(QColor(150, 150, 150))
        for s in self.sessions:
            orphans = s["n_orphelins"]
            detail = f"{s['n_fichiers']} fichier(s)"
            if s["resume"]:
                detail += " · " + s["resume"]
            item = QTreeWidgetItem([s["outil"], s["date"], detail])
            item.setData(COL_QUOI, Qt.UserRole, s["dossier"])
            font = item.font(COL_QUOI)
            font.setBold(True)
            item.setFont(COL_QUOI, font)
            if not s["manifeste"]:
                item.setToolTip(
                    COL_QUOI,
                    "Sauvegarde antérieure au manifeste : la destination de "
                    "chaque fichier est reconstituée par correspondance de nom.")
                item.setText(COL_QUOI, s["outil"] + "   [ancienne]")
            if orphans:
                item.setText(COL_DETAIL, detail + f"  ⚠ {orphans} sans cible")

            for e in s["fichiers"]:
                cible = e.get("cible") or "cible inconnue, ne sera pas restauré"
                marque = ""
                if e.get("action") == br.DELETED:
                    marque = "  (fichier supprimé → recréé)"
                elif e.get("action") == br.ABSENT:
                    marque = "  (n'existait pas → sera EFFACÉ)"
                elif e.get("devine"):
                    marque = "  (destination déduite)"
                child = QTreeWidgetItem([e["sauvegarde"] or "·", "", cible + marque])
                if e.get("cible"):
                    child.setToolTip(COL_DETAIL, str(self.project_root / cible))
                child.setFlags(Qt.ItemIsEnabled)
                child.setForeground(COL_QUOI, muted)
                child.setForeground(COL_DETAIL, muted)
                item.addChild(child)
            self.tree.addTopLevelItem(item)

        self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._update_button()

    def _selected(self):
        """La session sélectionnée (un enfant sélectionne sa session)."""
        item = self.tree.currentItem()
        if item is None:
            return None
        if item.parent() is not None:
            item = item.parent()
        folder = item.data(COL_QUOI, Qt.UserRole)
        return next((s for s in self.sessions if s["dossier"] == folder), None)

    def _update_button(self):
        s = self._selected()
        self.btn_restore.setEnabled(bool(s) and s["n_fichiers"] > s["n_orphelins"])

    def _open_folder(self):
        s = self._selected()
        if s:
            os.startfile(s["dossier"])          # Windows : explorateur

    # ---- restauration --------------------------------------------------------

    def _restore(self):
        s = self._selected()
        if not s:
            return
        efface = sum(1 for e in s["fichiers"] if e.get("action") == br.ABSENT)
        n = s["n_fichiers"] - s["n_orphelins"] - efface
        msg = [f"Restaurer la sauvegarde « {s['outil']} » du {s['date']} ?", ""]
        msg.append(f"Projet sélectionné : {self.project_root}")
        msg.append(f"• {n} fichier(s) seront réécrits")
        recrees = sum(1 for e in s["fichiers"] if e.get("action") == br.DELETED)
        if recrees:
            msg.append(f"• dont {recrees} fichier(s) supprimé(s) à recréer")
        if efface:
            msg.append(f"• {efface} fichier(s) seront EFFACÉS "
                       "(ils n'existaient pas à ce moment-là)")
        externes = [e["cible"] for e in s["fichiers"]
                    if e.get("cible") and Path(e["cible"]).is_absolute()]
        if externes:
            msg.extend(["", "Fichiers hors projet concernés :"] + externes)
        if s["n_orphelins"]:
            msg.append(f"• {s['n_orphelins']} sans cible connue : ignoré(s)")
        msg += ["",
                "L'état ACTUEL est sauvegardé avant : cette restauration "
                "pourra elle-même être annulée."]

        if QMessageBox.question(
            self, "Confirmer la restauration", "\n".join(msg),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        ) != QMessageBox.Yes:
            return

        try:
            rep = br.restore_session(s["dossier"], self.project_root)
        except OSError as e:
            QMessageBox.critical(self, "Erreur d'écriture", str(e))
            return

        detail = [f"{len(rep['restaurés'])} fichier(s) restauré(s)."]
        if rep.get("supprimés"):
            detail.append(f"{len(rep['supprimés'])} fichier(s) effacé(s).")
        if rep["sauvegarde_avant"]:
            detail.append("État précédent sauvegardé sous "
                          + Path(rep["sauvegarde_avant"]).name + ".")
        if rep["ignorés"]:
            detail.append(f"{len(rep['ignorés'])} ignoré(s) (cible inconnue).")
        detail.append("Rouvrir le .pbip dans Power BI Desktop.")
        QMessageBox.information(self, "Restauration terminée", "\n".join(detail))

        if self.on_restored:
            self.on_restored(rep)
        self.reload()
