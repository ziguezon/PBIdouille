# -*- coding: utf-8 -*-
"""
ChopChopRapport 🔪 — UI (qtpy) au-dessus de unused_measures.py : arbre des
mesures groupées par statut, avec suppression directe dans les fichiers TMDL
du projet PBIP choisi.

  🟥 Inutilisées — aucune référence     (fond rouge sombre)
  🟨 Inutilisées — used by unused       (fond ambre sombre)
  ⬜ Utilisées                          (repliées par défaut, non supprimables)

- « Changer de rapport… » ouvre un sélecteur de fichier .pbip ; le dernier
  choix est mémorisé (QSettings) d'une session à l'autre ;
- cocher un GROUPE coche tous ses enfants (case tristate) ;
- chaque mesure se déplie pour voir ses référenceurs un à un (mesures,
  tables calculées, colonnes calculées, fichiers du rapport) ; la colonne
  « Référencé par » en donne le sommaire ;
- supprimer une mesure « used by unused » inclut d'office ses référenceurs
  (sinon leur DAX serait cassé).

IMPORTANT : Desktop peut rester ouvert, mais doit ensuite être fermé SANS
enregistrer puis rouvert (il ne relit les fichiers qu'à l'ouverture, et
enregistrer remettrait ce qui vient d'être supprimé).
Backup automatique sous _backupsPBIdouille\\_tmdl_backups\\<horodatage>\\ avant
chaque écriture.

Lancement    : py unused_measures_ui.py
Dépendances  : py -m pip install qtpy pyside6
"""

from __future__ import annotations  # annotations paresseuses : Python 3.8+

import csv
import os
import sys
import tempfile
from pathlib import Path

from qtpy.QtCore import QSettings, Qt
from qtpy.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from qtpy.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import unused_measures as um

# Thème partagé BIdouille (« Dark Teal Pro » : vert néon sur bleu nuit).
# Fallback : si le dossier bidouille\ n'est pas à côté (copie isolée de
# ChopChop), on retombe sur l'ancien style autonome (qdarkstyle + rose).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from core import theme as _theme
except ImportError:
    _theme = None
# PRODUCTION : analyse et export seulement, pas de suppression (cf.
# core/edition.py). Sans le dossier bidouille\ à côté, on reste prudent :
# production.
try:
    from core.edition import production as _production
except ImportError:
    def _production():
        return True

APP_NAME  = "ChopChopRapport"
APP_EMOJI = "🪓"


def emoji_icon(emoji: str) -> QIcon:
    """Icône d'application à partir d'un émoji, rendue avec Segoe UI Emoji
    (couleur native Windows) — aucun fichier .ico à trimballer."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        font = QFont("Segoe UI Emoji")
        font.setPixelSize(int(size * 0.82))
        painter.setFont(font)
        painter.drawText(pm.rect(), Qt.AlignCenter, emoji)
        painter.end()
        icon.addPixmap(pm)
    return icon

COL_NAME, COL_TABLE, COL_REFS = range(3)

# palette de statut : sémantiques du thème néon (rouge « bad », ambre
# « neutral ») sur fonds bleu nuit teintés ; fallback = anciennes couleurs
if _theme:
    RED_BG    = QBrush(QColor("#33191E"))            # inutilisée, aucune référence
    RED_FG    = QBrush(QColor(_theme.RED))
    YELLOW_BG = QBrush(QColor("#332B15"))            # used by unused
    YELLOW_FG = QBrush(QColor(_theme.YELLOW))
    GRAY_FG   = QBrush(QColor(_theme.TEXT_MUTED))    # mesure générée par le script TE
else:
    RED_BG    = QBrush(QColor(64, 16, 16))
    RED_FG    = QBrush(QColor(255, 92, 92))
    YELLOW_BG = QBrush(QColor(64, 52, 6))
    YELLOW_FG = QBrush(QColor(255, 210, 70))
    GRAY_FG   = QBrush(QColor(150, 150, 150))

HOT_PINK = "#FF69B4"


def _style_group_header(group: "QTreeWidgetItem", dimmed: bool) -> None:
    """En-tête de groupe : gras. Un groupe SUPPRIMABLE garde la couleur normale
    (affordance : on peut cliquer sans danger) ; un groupe « utilisé »
    (informatif, non supprimable) est atténué en gris. La sévérité rouge/jaune
    vit sur les puces des lignes enfants, pas sur le titre — le rouge/jaune sur
    un en-tête actionnable donnerait à tort une impression d'avertissement."""
    font = group.font(COL_NAME)
    font.setBold(True)
    group.setFont(COL_NAME, font)
    if dimmed:
        group.setForeground(COL_NAME, GRAY_FG)


def _write_indicator_icons() -> tuple[str, str]:
    """Peint la coche et le tiret hot pink en PNG dans le dossier temp et
    retourne leurs chemins (les stylesheets Qt exigent des fichiers).
    PNG plutôt que SVG : PyQt5 (poste du travail) n'a pas toujours le
    plugin SVG, et l'échec serait silencieux."""
    d = Path(tempfile.gettempdir())
    check_path = d / "chopchop_check.png"
    dash_path = d / "chopchop_dash.png"

    pen = QPen(QColor(HOT_PINK))
    pen.setWidthF(2.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)

    for path, kind in ((check_path, "check"), (dash_path, "dash")):
        pm = QPixmap(15, 15)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(pen)
        if kind == "check":
            painter.drawLine(3, 8, 6, 11)
            painter.drawLine(6, 11, 12, 4)
        else:
            painter.drawLine(4, 7, 11, 7)
        painter.end()
        pm.save(str(path), "PNG")

    return check_path.as_posix(), dash_path.as_posix()


def _tree_stylesheet() -> str:
    if _theme:  # coches vertes néon du thème partagé
        return _theme.checkable_list_stylesheet()
    check, dash = _write_indicator_icons()
    return f"""
QTreeWidget::item {{ padding: 1px 2px; }}
QTreeWidget::indicator {{
    width: 15px; height: 15px;
    margin-right: 7px;
    border: 1px solid #6a6a6a;
    border-radius: 4px;
    background: #262626;
}}
QTreeWidget::indicator:hover {{ border-color: {HOT_PINK}; }}
QTreeWidget::indicator:checked {{
    image: url("{check}");
    border-color: {HOT_PINK};
    background: #262626;
}}
QTreeWidget::indicator:indeterminate {{
    image: url("{dash}");
    border-color: {HOT_PINK};
    background: #262626;
}}
"""


COLS_TOOLTIP = (
    "Cocher pour supprimer. Colonne calculée → bloc TMDL retiré ; colonne\n"
    "importée → retirée aussi de la requête Power Query (Table.RemoveColumns) ;\n"
    "colonne d'une table calculée → non supprimable ici (modifier le DAX).\n"
    "\n"
    "Une colonne citée par une AUTRE requête Power Query (clé de jointure,\n"
    "colonne développée) reste marquée utilisée : la retirer casserait\n"
    "l'actualisation de la requête qui s'en sert."
)

TABLES_TOOLTIP = (
    "Tables dont RIEN d'externe ne dépend (aucune relation, aucun visuel,\n"
    "aucune mesure utilisée), dont les paramètres de champ que plus aucun\n"
    "visuel n'utilise. Cocher supprime la table ENTIÈRE : son fichier .tmdl\n"
    "et sa référence dans model.tmdl (backup fait ; rouvrir le .pbip sans enregistrer).\n"
    "\n"
    "Une table dont la requête Power Query est consommée par une AUTRE\n"
    "requête (fusion, ajout, jointure) n'est jamais proposée ici : la\n"
    "supprimer casserait l'actualisation. Le journal dit lesquelles."
)


def col_summary(key: str, result: dict) -> str:
    """Sommaire des usages d'une colonne : « rapport (2 fichiers), relation,
    3 mesures »."""
    parts = []
    files = result["column_report_refs"].get(key, [])
    if files:
        parts.append("rapport (" + str(len(files)) + (" fichiers)" if len(files) > 1 else " fichier)"))
    kinds = []
    for kind, _label in result["column_struct_refs"].get(key, []):
        if kind not in kinds:
            kinds.append(kind)
    parts.extend(kinds)
    meas = result["column_referencers"].get(key, [])
    if meas:
        parts.append(f"{len(meas)} mesure{'s' if len(meas) > 1 else ''}")
    return ", ".join(parts) if parts else "aucune référence"


def col_details(key: str, result: dict) -> list[str]:
    """Chaque usage distinct d'une colonne, une ligne par élément."""
    out = []
    for f in result["column_report_refs"].get(key, []):
        out.append(f"rapport : {f}")
    for kind, label in result["column_struct_refs"].get(key, []):
        out.append(f"{kind} : {label}")
    for m in result["column_referencers"].get(key, []):
        out.append(f"mesure : {m}")
    return out


def ref_summary(name: str, result: dict) -> str:
    """Sommaire des référenceurs : « rapport (3 fichiers), 2 mesures, 1 table
    calculée »."""
    parts = []
    files = result["report_refs"].get(name, [])
    if files:
        parts.append("rapport (" + str(len(files)) + (" fichiers)" if len(files) > 1 else " fichier)"))

    by_kind: dict[str, int] = {}
    for kind, _label in result["struct_refs"].get(name, []):
        by_kind[kind] = by_kind.get(kind, 0) + 1
    for kind in sorted(by_kind):
        n = by_kind[kind]
        if n > 1:
            plural = " ".join(w + ("s" if not w.endswith("s") else "") for w in kind.split(" "))
            parts.append(f"{n} {plural}")
        else:
            parts.append(f"1 {kind}")

    meas = result["referencers"].get(name, [])
    if meas:
        parts.append(f"{len(meas)} mesure{'s' if len(meas) > 1 else ''}")

    return ", ".join(parts) if parts else "aucune référence"


def ref_details(name: str, result: dict) -> list[str]:
    """Chaque référenceur distinct, une ligne par élément."""
    out = []
    for f in result["report_refs"].get(name, []):
        out.append(f"rapport : {f}")
    for kind, label in result["struct_refs"].get(name, []):
        out.append(f"{kind} : {label}")
    for m in result["referencers"].get(name, []):
        out.append(f"mesure : {m}")
    return out


class ChopChopPanel(QWidget):
    """Le cœur de ChopChop, sans barre projet : arbre + boutons + journal.
    Réutilisé par la fenêtre autonome (ChopChopWindow) ET par l'onglet
    « ChopChop 🪓 » de BIdouille (le projet vient alors de la barre de l'app).
    Point d'entrée : set_pbip(chemin du .pbip) — analyse et peuple l'arbre."""

    def __init__(self):
        super().__init__()
        self.result = None
        self._unused_groups: list[QTreeWidgetItem] = []
        self._unused_col_groups: list[QTreeWidgetItem] = []
        self._dead_table_groups: list[QTreeWidgetItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.info = QLabel("")
        layout.addWidget(self.info)

        # filtre par table : masque l'affichage seulement (les cases cochées
        # d'autres tables restent vivantes ; le compteur montre le total réel)
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Table :"))
        self.cmb_table = QComboBox()
        self.cmb_table.addItem("Toutes")
        self.cmb_table.currentIndexChanged.connect(self._apply_table_filter)
        filter_bar.addWidget(self.cmb_table)
        filter_bar.addStretch()
        layout.addLayout(filter_bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Objet", "Table", "Référencé par"])
        self.tree.setStyleSheet(_tree_stylesheet())
        header = self.tree.header()
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_TABLE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_REFS, QHeaderView.Stretch)
        self._syncing = False          # garde anti-récursion sur itemChanged
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, stretch=3)

        buttons = QHBoxLayout()
        btn_refresh = QPushButton("Réanalyser")
        btn_refresh.clicked.connect(self.refresh)
        btn_manual = QPushButton("Cocher manuelles seulement")
        btn_manual.clicked.connect(self._check_manual)
        btn_export = QPushButton("Exporter…")
        btn_export.clicked.connect(self._export)
        # dans PBIdouille, ce bouton est au ruban (cf. tab_chopchop) ; il reste
        # ici pour la fenêtre autonome
        self.btn_backups = btn_backups = QPushButton("Sauvegardes…")
        btn_backups.setToolTip(
            "Lister les sauvegardes du projet (tous outils confondus) et en\n"
            "restaurer une. L'état courant est sauvegardé avant : une\n"
            "restauration reste annulable.")
        btn_backups.clicked.connect(self._show_backups)
        self.btn_delete = QPushButton("Supprimer la sélection (0)")
        self.btn_delete.clicked.connect(self._delete_checked)
        buttons.addWidget(btn_refresh)
        buttons.addWidget(btn_manual)
        buttons.addWidget(btn_export)
        buttons.addWidget(btn_backups)
        buttons.addStretch()
        buttons.addWidget(self.btn_delete)
        if _production():
            # « Cocher manuelles » ne sert qu'à préparer une suppression
            btn_manual.setVisible(False)
            self.btn_delete.setVisible(False)
        layout.addLayout(buttons)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        layout.addWidget(self.log, stretch=1)

        self._update_delete_label()

    # ---- projet ---------------------------------------------------------------

    def _invalider_analyse(self, message):
        self.result = None
        self._unused_groups = []
        self._unused_col_groups = []
        self._dead_table_groups = []
        self.tree.clear()
        self.info.setText(message)
        self._update_delete_label()

    def set_pbip(self, pbip_path) -> None:
        """Pointe le panneau vers un projet et (ré)analyse. Gère un projet
        invalide en douceur (message, pas d'exception)."""
        um.set_project(Path(pbip_path))
        if um.MODEL_DIR.exists():
            self.log.appendPlainText(f"Projet : {pbip_path}")
            self.refresh()
        else:
            self._invalider_analyse("Aucun projet valide, dossiers .Report/.SemanticModel introuvables.")

    # ---- construction de l'arbre ---------------------------------------------

    def _add_measure_item(self, parent: QTreeWidgetItem, name: str,
                          bg: QBrush | None, fg: QBrush | None,
                          checkable: bool) -> QTreeWidgetItem:
        info = self.result["measures"][name]
        label = name + ("   [générée]" if info["generated"] else "")

        item = QTreeWidgetItem([label, info["table"], ref_summary(name, self.result)])
        item.setData(COL_NAME, Qt.UserRole, name)
        if checkable:
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(COL_NAME, Qt.Unchecked)

        # CF sur la colonne « Référencé par » seulement — le reste de la ligne
        # suit le thème (évite le halo autour des cases à cocher)
        if bg is not None:
            item.setBackground(COL_REFS, bg)
            item.setForeground(COL_REFS, fg)
        if info["generated"]:
            item.setForeground(COL_NAME, GRAY_FG)
            item.setForeground(COL_TABLE, GRAY_FG)
        if info["generated"]:
            item.setToolTip(COL_NAME,
                "Générée depuis measures_config.json : la supprimer ici est inutile\n"
                "tant qu'elle y reste (elle sera recréée). Retirer plutôt la variation\n"
                "dans l'onglet « Mesures » de BIdouille.")

        # détail : un enfant par référenceur distinct
        for detail in ref_details(name, self.result):
            child = QTreeWidgetItem([detail, "", ""])
            child.setFlags(Qt.ItemIsEnabled)  # informatif : pas de case
            child.setForeground(COL_NAME, GRAY_FG)
            item.addChild(child)

        parent.addChild(item)
        return item

    def _add_group(self, title: str, names: list[str], bg: QBrush | None,
                   fg: QBrush | None, checkable: bool, expanded: bool) -> QTreeWidgetItem:
        group = QTreeWidgetItem([f"{title} ({len(names)})", "", ""])
        flags = Qt.ItemIsEnabled
        if checkable:
            # case « tout sélectionner » : gérée à la main (_on_item_changed) —
            # PAS ItemIsAutoTristate, qui se bloque dès qu'un enfant n'est pas
            # cochable (cf. colonnes de table calculée)
            flags |= Qt.ItemIsUserCheckable
        group.setFlags(flags)
        if checkable:
            group.setCheckState(COL_NAME, Qt.Unchecked)
        # supprimable = couleur normale (cliquable) ; « utilisées » = gris atténué
        _style_group_header(group, dimmed=fg is None)

        self.tree.addTopLevelItem(group)
        for n in names:
            self._add_measure_item(group, n, bg, fg, checkable)
        group.setExpanded(expanded)
        if checkable:
            self._unused_groups.append(group)
        return group

    # suffixe + tooltip par catégorie de colonne (cf. unused_measures)
    _CAT_LABEL = {"calc": "   [calculée]", "import": "   [importée]",
                  "structural": "   [table calc.]"}
    _CAT_TIP = {
        "calc": "Colonne calculée (DAX) : supprimée en retirant son bloc du "
                "TMDL.",
        "import": "Colonne importée : supprimée du modèle ET retirée de la "
                  "requête Power Query (étape Table.RemoveColumns ajoutée en "
                  "FIN de requête, donc les étapes précédentes (type, "
                  "renommage, colonne dérivée) continuent de fonctionner).",
        "structural": "Colonne d'une table calculée (paramètre de champ, sortie "
                      "DAX) : non supprimable ici, modifier l'expression DAX de la "
                      "table dans Power BI.",
    }

    def _add_column_group(self, title: str, keys: list[str], bg: QBrush | None,
                          fg: QBrush | None, expanded: bool,
                          checkable: bool) -> None:
        """Groupe de COLONNES. Cochable (calc/import) sauf les colonnes
        'structural' qui restent informatives (voir _CAT_TIP)."""
        columns = self.result["columns"]
        # le groupe n'est cochable que s'il contient au moins une colonne
        # supprimable (les groupes tout-structural n'ont pas de « tout cocher »)
        any_checkable = checkable and any(
            columns[k].get("category") != "structural" for k in keys)
        group = QTreeWidgetItem([f"{title} ({len(keys)})", "", ""])
        flags = Qt.ItemIsEnabled
        if any_checkable:
            flags |= Qt.ItemIsUserCheckable   # « tout cocher » manuel, cf. _add_group
        group.setFlags(flags)
        if any_checkable:
            group.setCheckState(COL_NAME, Qt.Unchecked)
        _style_group_header(group, dimmed=fg is None)   # « utilisées » = gris
        self.tree.addTopLevelItem(group)

        for key in keys:
            info = columns[key]
            cat = info.get("category", "import")
            label = info["name"] + self._CAT_LABEL.get(cat, "")
            item = QTreeWidgetItem([label, info["table"], col_summary(key, self.result)])
            item.setData(COL_NAME, Qt.UserRole, key)
            # cochable sauf structural (jamais supprimable ici)
            if checkable and cat != "structural":
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(COL_NAME, Qt.Unchecked)
            else:
                item.setFlags(Qt.ItemIsEnabled)
            item.setToolTip(COL_NAME, self._CAT_TIP.get(cat, COLS_TOOLTIP))
            if cat == "structural":
                item.setForeground(COL_NAME, GRAY_FG)
            if bg is not None:
                item.setBackground(COL_REFS, bg)
                item.setForeground(COL_REFS, fg)
            for detail in col_details(key, self.result):
                child = QTreeWidgetItem([detail, "", ""])
                child.setFlags(Qt.ItemIsEnabled)
                child.setForeground(COL_NAME, GRAY_FG)
                item.addChild(child)
            group.addChild(item)
        group.setExpanded(expanded)
        if any_checkable:
            self._unused_col_groups.append(group)

    def _add_dead_table_group(self, tables: list[str]) -> None:
        """Groupe « Tables entièrement inutilisées » (cochable). Chaque item =
        une table morte, supprimée en entier (fichier .tmdl + réf model.tmdl)."""
        info = self.result.get("dead_table_info", {})
        group = QTreeWidgetItem([f"🗑 Tables entièrement inutilisées ({len(tables)})", "", ""])
        group.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        group.setCheckState(COL_NAME, Qt.Unchecked)
        group.setToolTip(COL_NAME, TABLES_TOOLTIP)
        _style_group_header(group, dimmed=False)   # supprimable = couleur normale
        self.tree.addTopLevelItem(group)

        for t in tables:
            d = info.get(t, {})
            kind = "importée" if d.get("mode") == "m" else "calculée"
            bits = [f"{d.get('n_columns', 0)} colonnes", kind]
            if d.get("n_measures"):
                bits.append(f"{d['n_measures']} mesure(s)")
            item = QTreeWidgetItem([t + "   [table entière]", t, ", ".join(bits)])
            item.setData(COL_NAME, Qt.UserRole, t)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(COL_NAME, Qt.Unchecked)
            item.setToolTip(COL_NAME, TABLES_TOOLTIP)
            item.setBackground(COL_REFS, RED_BG)
            item.setForeground(COL_REFS, RED_FG)
            group.addChild(item)
        group.setExpanded(True)
        self._dead_table_groups.append(group)

    def refresh(self):
        try:
            self.result = um.analyze()
        except SystemExit as e:
            self._invalider_analyse(str(e))
            self.log.appendPlainText(str(e))
            QMessageBox.critical(self, "Erreur", str(e))
            return

        measures    = self.result["measures"]
        unused      = self.result["unused"]
        referencers = self.result["referencers"]

        no_ref  = [n for n in unused if not referencers.get(n)]
        chained = [n for n in unused if referencers.get(n)]
        used    = sorted(n for n in measures if n not in set(unused))
        generated = sum(1 for n in unused if measures[n]["generated"])

        columns      = self.result["columns"]
        col_no_ref   = self.result["unused_columns"]
        col_chained  = self.result["column_chained"]
        col_used     = sorted(
            (k for k in columns if k not in set(col_no_ref) and k not in set(col_chained)),
            key=str.lower,
        )
        dead_tables  = self.result.get("dead_tables", [])

        dead_txt = (f" · <b>{len(dead_tables)} table(s) entièrement inutilisée(s)</b>"
                    if dead_tables else "")
        self.info.setText(
            f"{len(measures)} mesures · <b>{len(unused)} inutilisée(s)</b> "
            f"(dont {generated} générée(s) depuis le config) · "
            f"{len(columns)} colonnes · <b>{len(col_no_ref) + len(col_chained)} inutilisée(s)</b>"
            f"{dead_txt}."
        )

        self.tree.blockSignals(True)
        self.tree.clear()
        self._unused_groups = []
        self._unused_col_groups = []
        self._dead_table_groups = []
        if dead_tables:
            self._add_dead_table_group(dead_tables)
        self._add_group("📏 Mesures inutilisées · aucune référence", no_ref, RED_BG, RED_FG, True, True)
        self._add_group("📏 Mesures inutilisées · used by unused", chained, YELLOW_BG, YELLOW_FG, True, True)
        self._add_group("📏 Mesures utilisées", used, None, None, False, False)
        self._add_column_group("🔢 Colonnes inutilisées · aucune référence", col_no_ref, RED_BG, RED_FG, True, True)
        self._add_column_group("🔢 Colonnes · used by unused", col_chained, YELLOW_BG, YELLOW_FG, True, True)
        self._add_column_group("🔢 Colonnes utilisées", col_used, None, None, False, False)
        self.tree.blockSignals(False)

        # filtre par table : liste des tables présentes (mesures + colonnes)
        tables = sorted({measures[n]["table"] for n in measures}
                        | {columns[k]["table"] for k in columns}, key=str.lower)
        self.cmb_table.blockSignals(True)
        self.cmb_table.clear()
        self.cmb_table.addItem("Toutes")
        self.cmb_table.addItems(tables)
        self.cmb_table.blockSignals(False)
        self._apply_table_filter()
        self._update_delete_label()

        # Tables qui paraissent mortes mais qu'on ÉPARGNE (surtout : une autre
        # requête Power Query les consomme). Sans cette trace, leur absence de
        # la liste ressemble à un bug — alors que c'est la garde qui évite de
        # casser l'actualisation.
        spared = self.result.get("spared_tables", {})
        if spared:
            self.log.appendPlainText(
                f"{len(spared)} table(s) sans usage visible mais conservée(s) :")
            for t, why in sorted(spared.items(), key=lambda kv: kv[0].lower()):
                self.log.appendPlainText(f"    • {t}, {why}")

    # ---- sélection -------------------------------------------------------------

    def _checked_names(self) -> list[str]:
        out = []
        for group in self._unused_groups:
            for i in range(group.childCount()):
                child = group.child(i)
                if child.checkState(COL_NAME) == Qt.Checked:
                    out.append(child.data(COL_NAME, Qt.UserRole))
        return out

    def _checked_columns(self) -> list[str]:
        """Clés « 'Table'[Colonne] » des colonnes cochées (structural exclues :
        elles n'ont pas de case)."""
        out = []
        for group in self._unused_col_groups:
            for i in range(group.childCount()):
                child = group.child(i)
                if (child.flags() & Qt.ItemIsUserCheckable
                        and child.checkState(COL_NAME) == Qt.Checked):
                    out.append(child.data(COL_NAME, Qt.UserRole))
        return out

    def _checked_tables(self) -> list[str]:
        """Noms des tables entières cochées."""
        out = []
        for group in self._dead_table_groups:
            for i in range(group.childCount()):
                child = group.child(i)
                if child.checkState(COL_NAME) == Qt.Checked:
                    out.append(child.data(COL_NAME, Qt.UserRole))
        return out

    # ---- cases à cocher : « tout sélectionner » manuel ------------------------

    def _check_groups(self):
        """Tous les en-têtes cochables (mesures + colonnes + tables mortes)."""
        return (self._unused_groups + self._unused_col_groups
                + self._dead_table_groups)

    def _group_checkable_children(self, group, *, visible_only=False):
        out = []
        for i in range(group.childCount()):
            ch = group.child(i)
            if not (ch.flags() & Qt.ItemIsUserCheckable):
                continue           # structural : jamais coché
            if visible_only and ch.isHidden():
                continue
            out.append(ch)
        return out

    def _on_item_changed(self, item, col):
        """Gère « tout cocher » d'un groupe sans ItemIsAutoTristate (qui casse
        dès qu'un enfant n'est pas cochable). Un clic sur l'en-tête coche/décoche
        tous les enfants COCHABLES et VISIBLES ; un clic sur un enfant met à jour
        l'état (plein / partiel / vide) de son groupe."""
        if col != COL_NAME or self._syncing:
            return
        self._syncing = True
        try:
            groups = self._check_groups()
            if item in groups:
                state = item.checkState(COL_NAME)
                if state == Qt.PartiallyChecked:
                    state = Qt.Checked
                for ch in self._group_checkable_children(item, visible_only=True):
                    ch.setCheckState(COL_NAME, state)
            else:
                parent = item.parent()
                if parent in groups:
                    self._refresh_group_state(parent)
        finally:
            self._syncing = False
        self._update_delete_label()

    def _refresh_group_state(self, group):
        """État de l'en-tête d'après ses enfants cochables VISIBLES : plein,
        partiel ou vide (affichage seulement — le filtre ne change pas les
        coches hors vue)."""
        vis = self._group_checkable_children(group, visible_only=True)
        if not vis:
            return
        checked = sum(c.checkState(COL_NAME) == Qt.Checked for c in vis)
        state = (Qt.Checked if checked == len(vis)
                 else Qt.Unchecked if checked == 0 else Qt.PartiallyChecked)
        if group.checkState(COL_NAME) != state:
            group.setCheckState(COL_NAME, state)

    def _apply_table_filter(self, *_):
        """Masque les lignes dont la table ≠ table choisie (affichage seulement ;
        les cases restent cochées). « Toutes » = tout visible."""
        table = self.cmb_table.currentText() if self.cmb_table.count() else "Toutes"
        show_all = (self.cmb_table.currentIndex() <= 0) or table == "Toutes"
        self._syncing = True
        try:
            for group in (self.tree.topLevelItem(i)
                          for i in range(self.tree.topLevelItemCount())):
                visible_kids = 0
                for i in range(group.childCount()):
                    child = group.child(i)
                    hide = not show_all and child.text(COL_TABLE) != table
                    child.setHidden(hide)
                    visible_kids += not hide
                # un groupe sans enfant visible se masque aussi
                group.setHidden(not show_all and visible_kids == 0)
                if group.flags() & Qt.ItemIsUserCheckable:
                    self._refresh_group_state(group)  # état d'après la vue courante
        finally:
            self._syncing = False

    def _check_manual(self):
        if not self.result:
            return
        measures = self.result["measures"]
        self.tree.blockSignals(True)
        for group in self._unused_groups:
            for i in range(group.childCount()):
                child = group.child(i)
                name = child.data(COL_NAME, Qt.UserRole)
                child.setCheckState(
                    COL_NAME,
                    Qt.Unchecked if measures[name]["generated"] else Qt.Checked,
                )
            self._refresh_group_state(group)   # en-tête au diapason des enfants
        self.tree.blockSignals(False)
        self._update_delete_label()

    def _update_delete_label(self, *_):
        nm = len(self._checked_names())
        nc = len(self._checked_columns())
        nt = len(self._checked_tables())
        parts = []
        if nt:
            parts.append(f"{nt} table{'s' if nt > 1 else ''}")
        if nm:
            parts.append(f"{nm} mesure{'s' if nm > 1 else ''}")
        if nc:
            parts.append(f"{nc} colonne{'s' if nc > 1 else ''}")
        detail = (" (" + ", ".join(parts) + ")") if parts else " (0)"
        self.btn_delete.setText("Supprimer la sélection" + detail)
        self.btn_delete.setEnabled(nm + nc + nt > 0)

    # ---- sauvegardes / restauration -------------------------------------------

    def _show_backups(self):
        """Dialogue commun de restauration (toutes sauvegardes du projet :
        ChopChop, Propagation, Wireframe). Après restauration, on réanalyse —
        le modèle sur disque a changé."""
        try:
            from tabs.dialog_backups import BackupsDialog
        except ImportError:      # copie isolée : bidouille\ absent à côté
            QMessageBox.information(
                self, "Sauvegardes",
                "Le dialogue de restauration vit dans bidouille\\tabs\\.\n"
                f"Les sauvegardes sont dans :\n{um.PBIP_DIR}\\_backupsPBIdouille\\_tmdl_backups\\\n"
                "(chaque dossier contient un manifeste.json qui dit d'où "
                "vient chaque fichier).")
            return

        def after(rep):
            self.log.appendPlainText(
                f"Restauré : {len(rep['restaurés'])} fichier(s) "
                f"(état précédent sous {Path(rep['sauvegarde_avant']).name})"
                if rep.get("sauvegarde_avant")
                else f"Restauré : {len(rep['restaurés'])} fichier(s)")
            if um.MODEL_DIR.exists():
                self.refresh()

        dlg = BackupsDialog(um.PBIP_DIR, self, on_restored=after)
        dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()

    # ---- export ----------------------------------------------------------------

    def _export_rows(self):
        """L'audit complet : une ligne par mesure ET par colonne, utilisées
        comprises."""
        measures    = self.result["measures"]
        unused      = set(self.result["unused"])
        referencers = self.result["referencers"]

        header = ["Type", "Nom", "Table", "Statut", "Référencé par",
                  "Détail des référenceurs", "Générée"]
        rows = []
        for n in sorted(measures):
            if n in unused:
                statut = "INUTILISÉE (used by unused)" if referencers.get(n) else "INUTILISÉE"
            else:
                statut = "utilisée"
            rows.append([
                "mesure",
                n,
                measures[n]["table"],
                statut,
                ref_summary(n, self.result),
                " | ".join(ref_details(n, self.result)),
                "oui" if measures[n]["generated"] else "non",
            ])

        columns     = self.result["columns"]
        col_no_ref  = set(self.result["unused_columns"])
        col_chained = set(self.result["column_chained"])
        for key in sorted(columns, key=str.lower):
            if key in col_no_ref:
                statut = "INUTILISÉE"
            elif key in col_chained:
                statut = "INUTILISÉE (used by unused)"
            else:
                statut = "utilisée"
            rows.append([
                "colonne",
                columns[key]["name"],
                columns[key]["table"],
                statut,
                col_summary(key, self.result),
                " | ".join(col_details(key, self.result)),
                "",
            ])
        return header, rows

    def _write_xlsx(self, path: str, header: list, rows: list):
        """xlsx le plus simple possible : pandas si présent (cas du travail),
        sinon openpyxl. ImportError remonte si ni l'un ni l'autre."""
        try:
            import pandas as pd
            pd.DataFrame(rows, columns=header).to_excel(
                path, index=False, sheet_name="Audit mesures")
            return
        except ImportError:
            pass
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Audit mesures"
        ws.append(header)
        for r in rows:
            ws.append(r)
        wb.save(path)

    def _export(self):
        if not self.result:
            return
        default = str(um.PBIP_DIR / f"chopchop_{um.PROJECT}.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter l'audit", default,
            "CSV : s'ouvre dans Excel (*.csv);;Excel (*.xlsx)")
        if not path:
            return
        header, rows = self._export_rows()
        header = list(header) + ["Rapport analysé"]
        rows = [list(row) + [self.result["report_path"]] for row in rows]
        try:
            if path.lower().endswith(".xlsx"):
                self._write_xlsx(path, header, rows)
            else:
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f, delimiter=";")
                    w.writerow(header)
                    w.writerows(rows)
        except ImportError:
            QMessageBox.warning(
                self, "Excel non disponible",
                "Ni pandas ni openpyxl n'est installé, exporter en CSV, "
                "il s'ouvre directement dans Excel.")
            return
        except OSError as e:
            QMessageBox.critical(self, "Erreur d'écriture",
                                 f"{e}\n(Le fichier est peut-être ouvert dans Excel.)")
            return
        self.log.appendPlainText(f"Exporté : {path}")
        if QMessageBox.question(
            self, "Export terminé", "Ouvrir le fichier ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes:
            os.startfile(path)

    # ---- suppression -----------------------------------------------------------

    def _delete_checked(self):
        if _production() or not self.result:
            return
        measures    = self.result["measures"]
        referencers = self.result["referencers"]
        columns     = self.result["columns"]
        col_refs    = self.result["column_referencers"]

        selected = set(self._checked_names())
        col_selected = set(self._checked_columns())
        tbl_selected = set(self._checked_tables())
        if not selected and not col_selected and not tbl_selected:
            return

        # une table cochée subsume ses propres mesures/colonnes (elles partent
        # avec elle) : on les retire des sélections individuelles
        selected = {n for n in selected if measures[n]["table"] not in tbl_selected}
        col_selected = {k for k in col_selected
                        if columns[k]["table"] not in tbl_selected}

        # fermeture mesure->mesure : supprimer une mesure référencée exige de
        # supprimer ses référenceurs (tous inutilisés), sinon DAX cassé
        forced = set()
        queue = list(selected)
        # fermeture colonne->mesure : une colonne cochée référencée par des
        # mesures (inutilisées) force ces mesures — sinon leur DAX pointerait
        # vers une colonne disparue
        for key in col_selected:
            for m in col_refs.get(key, []):
                if m not in selected and measures[m]["table"] not in tbl_selected:
                    selected.add(m); forced.add(m); queue.append(m)
        while queue:
            n = queue.pop()
            for r in referencers.get(n, []):
                if r not in selected and measures[r]["table"] not in tbl_selected:
                    selected.add(r); forced.add(r); queue.append(r)

        gen = sorted(n for n in selected if measures[n]["generated"])
        # colonnes importées -> une étape Power Query par table concernée
        m_tables: dict[str, list[str]] = {}
        for key in col_selected:
            info = columns[key]
            if info.get("category") == "import":
                m_tables.setdefault(info["table"], []).append(info["name"])

        # Résumé COMPACT (le détail complet part dans le journal après coup) —
        # sinon le dialogue déborde et le bouton passe sous l'écran. Les
        # énumérations (mesures forcées, colonnes par requête M) deviennent des
        # compteurs ; les tables (peu nombreuses) sont listées, plafonnées.
        dead_info = self.result.get("dead_table_info", {})
        lines = []
        if tbl_selected:
            lines.append(f"• {len(tbl_selected)} table(s) entière(s) "
                         "(.tmdl + réf model.tmdl) :")
            shown = sorted(tbl_selected)
            for t in shown[:10]:
                d = dead_info.get(t, {})
                n = d.get("n_columns", 0) + d.get("n_measures", 0)
                lines.append(f"     – {t} ({n} élément(s))")
            if len(shown) > 10:
                lines.append(f"     … et {len(shown) - 10} autre(s)")
        if selected:
            extra = f" (dont {len(forced)} incluse(s) d'office)" if forced else ""
            lines.append(f"• {len(selected)} mesure(s){extra}")
        if col_selected:
            extra = (f" · {len(m_tables)} requête(s) Power Query modifiée(s)"
                     if m_tables else "")
            lines.append(f"• {len(col_selected)} colonne(s){extra}")

        msg = ["Supprimer des fichiers TMDL :", ""] + lines + [""]
        if gen:
            msg.append(f"⚠ {len(gen)} mesure(s) générée(s) reviendront à la "
                       "prochaine génération (config).")
        msg.append("Backup sous _backupsPBIdouille\\_tmdl_backups\\ · "
                   "détail complet dans le journal.")

        if QMessageBox.question(
            self, "Confirmer la suppression", "\n".join(msg),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        ) != QMessageBox.Yes:
            return

        try:
            # Le rapport peut avoir changé depuis la sélection.
            courant = um.analyze()
            if (not set(selected).issubset(courant["unused"])
                    or not set(col_selected).issubset(set(courant["unused_columns"]) | set(courant["column_chained"]))
                    or not set(tbl_selected).issubset(courant["dead_table_info"])):
                self.refresh()
                QMessageBox.information(self, "Rapport modifié", "Les usages ont changé. Revoir la sélection.")
                return
            rep = um.delete_objects(
                courant, measure_names=sorted(selected),
                column_keys=sorted(col_selected),
                table_names=sorted(tbl_selected),
                log=self.log.appendPlainText,
            )
        except (OSError, SystemExit) as e:
            self._invalider_analyse(str(e))
            QMessageBox.critical(self, "Suppression interrompue", str(e))
            return

        if rep["tables_deleted"]:
            self.log.appendPlainText(
                f"Tables supprimées ({len(rep['tables_deleted'])}) : "
                + ", ".join(rep["tables_deleted"]))
        for kept in rep.get("tables_skipped", []):
            self.log.appendPlainText(
                f"⚠ table conservée, {kept} : la supprimer casserait "
                "l'actualisation de la requête qui la consomme.")
        if rep["measures_deleted"]:
            self.log.appendPlainText(
                f"Mesures supprimées ({len(rep['measures_deleted'])}) : "
                + ", ".join(rep["measures_deleted"]))
        if rep["columns_deleted"]:
            self.log.appendPlainText(
                f"Colonnes supprimées ({len(rep['columns_deleted'])}) : "
                + ", ".join(rep["columns_deleted"]))
        for table, cols in sorted(rep["m_edits"].items()):
            self.log.appendPlainText(
                f"Power Query · {table} : étape RemoveColumns ({', '.join(cols)})")
        for table in rep["m_skipped"]:
            self.log.appendPlainText(
                f"⚠ {table} : requête M non reconnue, colonne retirée du modèle, "
                "modifier Power Query à la main pour stopper l'import.")
        self.log.appendPlainText(
            f"Fichiers modifiés : {', '.join(rep['files'])} (backup fait)")
        self.refresh()


class ChopChopWindow(QMainWindow):
    """Fenêtre autonome : barre projet (dernier .pbip mémorisé) + le panneau.
    Dans BIdouille, c'est l'onglet « ChopChop 🪓 » qui embarque le panneau."""

    def __init__(self):
        super().__init__()
        self.resize(1100, 720)
        self.settings = QSettings("ChopChop", APP_NAME)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # ---- barre projet ----
        project_bar = QHBoxLayout()
        self.project_label = QLabel("")
        btn_project = QPushButton("Changer de rapport…")
        btn_project.clicked.connect(self._choose_project)
        project_bar.addWidget(self.project_label, stretch=1)
        project_bar.addWidget(btn_project)
        layout.addLayout(project_bar)

        self.panel = ChopChopPanel()
        layout.addWidget(self.panel, stretch=1)

        # projet initial : dernier utilisé, sinon défaut du module
        last = self.settings.value("last_pbip", "")
        pbip = last if (last and Path(last).exists()) \
            else str(um.PBIP_DIR / (um.PROJECT + ".pbip"))
        self._set_project(pbip, initial=True)

    def _set_project(self, pbip_path, initial=False):
        self.project_label.setText(f"Projet : {pbip_path}")
        self.setWindowTitle(f"{APP_NAME} · {Path(pbip_path).stem}")
        if not initial:
            self.settings.setValue("last_pbip", str(pbip_path))
        if Path(pbip_path).exists():
            self.panel.set_pbip(pbip_path)
        else:
            self.panel.info.setText(
                "Aucun projet valide, cliquer sur « Changer de rapport… » pour en choisir un.")

    def _choose_project(self):
        start_dir = str(um.PBIP_DIR) if um.PBIP_DIR.exists() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir un projet Power BI", start_dir, "Projet Power BI (*.pbip)")
        if path:
            self._set_project(path)


def main():
    app = QApplication(sys.argv)

    if _theme:
        # thème néon partagé (Dark Teal Pro) : QSS autonome, identique
        # PyQt5/PySide6 ; pose aussi l'icône et l'identité Windows
        _theme.apply_app_theme(app, APP_EMOJI, f"ChopChop.{APP_NAME}")
    else:
        # fallback copie isolée : identité Windows, qdarkstyle si présent
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"ChopChop.{APP_NAME}")
        except Exception:
            pass
        try:
            import qdarkstyle
            app.setStyleSheet(qdarkstyle.load_stylesheet())
        except ImportError:
            pass
        app.setWindowIcon(emoji_icon(APP_EMOJI))

    win = ChopChopWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
