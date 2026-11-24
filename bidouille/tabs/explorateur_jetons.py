# -*- coding: utf-8 -*-
"""Mesures → Variations, « Jetons disponibles… » : ce que vaut chaque jeton.

Une fenêtre non modale, à garder ouverte à côté du DAX. On choisit une mesure
(un KPI ou une cible) et une branche. En haut, les jetons {…} : leur valeur et
le réglage qui les décide. En bas, les attributs de TD_Indicateurs, qui se
modifient ICI, directement dans les cases : nom du jeton, colonne, valeur du
KPI. C'est la même liste que ⚙ Réglages → Excel des indicateurs.

Ce widget ne touche ni au config ni à l'Excel : il émet ce que l'usager
demande, et l'onglet Mesures l'exécute puis lui redonne l'état à jour. Les
signaux partent au tour suivant de la boucle : la réponse reconstruit le
tableau, donc détruit la case d'où vient le geste.

Les valeurs viennent de generate_measures.apercu_jetons, donc de la génération
elle-même. Les couleurs sont celles de l'éditeur : {…} en bleu, <<…>> en vert.
"""

from __future__ import annotations

from qtpy.QtCore import Qt, QTimer, Signal
from qtpy.QtGui import QBrush, QColor, QFont
from qtpy.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.theme import ACCENT, BLUE, TEXT, TEXT_DIM, TEXT_MUTED, YELLOW

COL_JETON, COL_VALEUR, COL_ROLE, COL_OU = 0, 1, 2, 3
A_JETON, A_COLONNE, A_VALEUR, A_INSERER, A_ACTION = 0, 1, 2, 3, 4
POLICE_CODE = QFont("Consolas", 9)

# où se règlent les choses : les noms exacts de ⚙ Réglages
R_GENERATION = "⚙ Réglages → Génération"
R_BRANCHES = "⚙ Réglages → Branches"
R_CIBLES = "⚙ Réglages → Mesures cibles"

ROLES = {
    "{base}": "le nom de la mesure traitée",
    "{baseRef}": "la même mesure, en référence DAX",
    "{kpi}": "le nom de l'ICP, sans branche ni cible",
    "{kpiRef}": "la mesure de l'ICP, dans cette branche",
    "{branch}": "le nom de la branche (rien en Réel)",
    "{variation}": "l'identifiant de la variation ouverte",
    "{date}": "la colonne de dates",
    "{deltaScale}": "100 si la base est en %, sinon 1",
    "{baseFormatString}": "le format de la base, en texte DAX",
    "<<tables>>": "les tables de l'ICP, en liste",
    "<<allTables>>": "ALL() sur chaque table de l'ICP",
    "<<removeFilters>>": "REMOVEFILTERS() sur chaque table de l'ICP",
    "<<each ALLSELECTED({table})>>": "la fonction, répétée par table",
}


def nom_attribut(texte: str) -> str:
    """Le nom nu d'un attribut : « <<unite>> » et « unite » donnent « unite ».
    Les jetons s'affichent avec leurs chevrons, le config les garde sans."""
    return (texte or "").strip().lstrip("<").rstrip(">").strip()


def ou_se_regle(jeton: str, b: dict) -> str:
    """Le réglage qui décide de ce jeton, pour cette mesure."""
    base = (R_CIBLES if b["cible"] else
            R_BRANCHES if b["branche"] else R_GENERATION + " → sourceFolder")
    return {
        "{base}": base,
        "{baseRef}": base,
        "{kpi}": R_GENERATION + " → sourceFolder",
        "{kpiRef}": R_BRANCHES if b["branche"] else R_GENERATION + " → sourceFolder",
        "{branch}": R_BRANCHES,
        "{variation}": "la liste des variations, à gauche",
        "{date}": R_GENERATION + " → dateColumn",
        "{deltaScale}": "le format de la mesure, dans Power BI",
        "{baseFormatString}": "le format de la mesure, dans Power BI",
    }.get(jeton, "")


class ExplorateurJetons(QWidget):
    AIDE = "Double-clic sur un jeton {…} : il part dans le DAX."
    besoin = Signal()                         # s'affiche : il lui faut ses données
    inserer = Signal(str)                     # un jeton pour le DAX
    attribut_ajoute = Signal(str, str, str, str)    # jeton, colonne, valeur, KPI
    attribut_renomme = Signal(str, str)       # ancien jeton, nouveau
    attribut_colonne = Signal(str, str)       # jeton, colonne
    attribut_valeur = Signal(str, str, str, str)    # jeton, colonne, KPI, valeur
    attribut_retire = Signal(str)             # jeton

    def __init__(self, parent=None):
        super().__init__(parent)
        self._donnees: dict = {}
        self._variation = ""
        self._attributs: list = []     # ceux du tableau, ligne par ligne
        self._remplissage = False

        v = QVBoxLayout(self)
        haut = QHBoxLayout()
        haut.addWidget(QLabel("Mesure :"))
        self.cmb_base = QComboBox()
        self.cmb_base.setToolTip("Les ICP, et sous chacun ses cibles.")
        haut.addWidget(self.cmb_base, 1)
        haut.addWidget(QLabel("Branche :"))
        self.cmb_branche = QComboBox()
        self.cmb_branche.setMinimumWidth(110)
        haut.addWidget(self.cmb_branche)
        v.addLayout(haut)

        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(f"color:{TEXT_DIM};")
        v.addWidget(self.lbl_note)

        self.arbre = QTreeWidget()
        self.arbre.setColumnCount(4)
        self.arbre.setHeaderLabels(["Jeton", "Valeur ici", "Ce que c'est", "Où ça se règle"])
        self.arbre.setRootIsDecorated(False)
        self.arbre.setUniformRowHeights(True)
        h = self.arbre.header()
        h.setSectionResizeMode(COL_JETON, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_VALEUR, QHeaderView.Interactive)
        h.setSectionResizeMode(COL_ROLE, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_OU, QHeaderView.Stretch)
        self.arbre.setColumnWidth(COL_VALEUR, 250)
        self.arbre.itemDoubleClicked.connect(self._on_double_clic)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(self.arbre)
        split.addWidget(self._panneau_attributs())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        v.addWidget(split, 1)

        self.lbl_aide = QLabel(self.AIDE)
        self.lbl_aide.setWordWrap(True)
        self.lbl_aide.setStyleSheet(f"color:{TEXT_DIM};")
        v.addWidget(self.lbl_aide)

        self.cmb_base.currentIndexChanged.connect(self._remplir)
        self.cmb_branche.currentIndexChanged.connect(self._remplir)

    def _panneau_attributs(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        titre = QLabel("<b>Attributs de TD_Indicateurs</b>"
                       f"  <span style='color:{TEXT_MUTED}'>écrire directement dans les "
                       "cases, c'est la même liste que dans ⚙ Réglages</span>")
        v.addWidget(titre)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Jeton", "Colonne de l'Excel", "Valeur", "", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(A_JETON, QHeaderView.Interactive)
        h.setSectionResizeMode(A_COLONNE, QHeaderView.Interactive)
        h.setSectionResizeMode(A_VALEUR, QHeaderView.Stretch)
        h.setSectionResizeMode(A_INSERER, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(A_ACTION, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(A_JETON, 190)
        self.table.setColumnWidth(A_COLONNE, 210)
        self.table.itemChanged.connect(self._on_case)
        v.addWidget(self.table, 1)

        ajout = QHBoxLayout()
        self.ed_jeton = QLineEdit()
        self.ed_jeton.setPlaceholderText("nouveau jeton, ex. <<objectif>>")
        self.cmb_colonne = QComboBox()
        self.cmb_colonne.setEditable(True)
        self.cmb_colonne.setInsertPolicy(QComboBox.NoInsert)
        self.cmb_colonne.lineEdit().setPlaceholderText("colonne, existante ou nouvelle")
        self.ed_valeur = QLineEdit()
        self.btn_ajouter = QPushButton("Ajouter")
        self.btn_ajouter.setToolTip("Déclare le jeton. Une colonne qui n'existe pas encore\n"
                                    "est créée dans l'Excel.")
        self.btn_ajouter.clicked.connect(self._ajouter)
        for ed in (self.ed_jeton, self.ed_valeur, self.cmb_colonne.lineEdit()):
            ed.returnPressed.connect(self._ajouter)
        ajout.addWidget(self.ed_jeton, 2)
        ajout.addWidget(self.cmb_colonne, 2)
        ajout.addWidget(self.ed_valeur, 3)
        ajout.addWidget(self.btn_ajouter)
        v.addLayout(ajout)
        return w

    # ---- API ---------------------------------------------------------------

    def afficher(self, donnees, libelle_reel="Réel") -> None:
        """`donnees` : generate_measures.apercu_jetons. Garde le choix en cours."""
        self._donnees = donnees or {}
        bases = self._donnees.get("bases") or []
        base, branche = self.choix()
        kpis: list = []
        for b in bases:
            if b["kpi"] not in kpis:
                kpis.append(b["kpi"])
        racines = {b["nom"]: b for b in bases if not b["branche"]}
        # chaque cible juste sous son KPI
        ordre = sorted(racines.values(), key=lambda b: (kpis.index(b["kpi"]), b["cible"], b["nom"]))
        branches = list(dict.fromkeys(b["branche"] for b in bases if b["branche"]))

        for cmb in (self.cmb_base, self.cmb_branche):
            cmb.blockSignals(True)
            cmb.clear()
        for b in ordre:
            self.cmb_base.addItem(("    " if b["cible"] else "") + b["nom"], b["nom"])
        self.cmb_branche.addItem(libelle_reel or "Réel", "")
        for b in branches:
            self.cmb_branche.addItem(b, b)
        self.cmb_base.setCurrentIndex(max(0, self.cmb_base.findData(base)))
        self.cmb_branche.setCurrentIndex(max(0, self.cmb_branche.findData(branche)))
        for cmb in (self.cmb_base, self.cmb_branche):
            cmb.blockSignals(False)
        texte = self.cmb_colonne.currentText()
        self.cmb_colonne.clear()
        self.cmb_colonne.addItems(self._donnees.get("colonnes") or [])
        self.cmb_colonne.setCurrentText(texte)
        self._remplir()

    def erreur(self, texte: str) -> None:
        self._donnees = {}
        self.cmb_base.clear()
        self.cmb_branche.clear()
        self.arbre.clear()
        self.table.setRowCount(0)
        self.lbl_note.setText(texte)

    def message(self, texte: str = "", alerte: bool = False) -> None:
        self.lbl_aide.setText(texte or self.AIDE)
        self.lbl_aide.setStyleSheet(f"color:{YELLOW if alerte else TEXT_DIM};")

    def vider_ajout(self) -> None:
        self.ed_jeton.clear()
        self.cmb_colonne.setCurrentText("")
        self.ed_valeur.clear()

    def set_variation(self, vid: str) -> None:
        self._variation = vid or ""
        self._remplir()

    def choix(self) -> tuple:
        return self.cmb_base.currentData() or "", self.cmb_branche.currentData() or ""

    def choisir(self, base: str, branche: str = "") -> bool:
        i, j = self.cmb_base.findData(base), self.cmb_branche.findData(branche)
        if i < 0 or j < 0:
            return False
        self.cmb_base.setCurrentIndex(i)
        self.cmb_branche.setCurrentIndex(j)
        return True

    def valeur(self, jeton: str):
        """Ce que vaut `jeton` pour le choix en cours (tests)."""
        b = self._courante()
        return b["valeurs"].get(jeton) if b else None

    # ---- affichage ---------------------------------------------------------

    def showEvent(self, ev):
        super().showEvent(ev)
        self.besoin.emit()

    def _courante(self):
        base, branche = self.choix()
        return next((b for b in self._donnees.get("bases") or []
                     if b["nom"] == base and b["branche"] == branche), None)

    def _kpi_courant(self) -> str:
        base = self.choix()[0]
        return next((b["kpi"] for b in self._donnees.get("bases") or []
                     if b["nom"] == base), "")

    def _groupe(self, titre) -> QTreeWidgetItem:
        g = QTreeWidgetItem([titre])
        f = QFont(g.font(0))
        f.setBold(True)
        g.setFont(COL_JETON, f)
        g.setForeground(COL_JETON, QBrush(QColor(TEXT_DIM)))
        g.setFlags(Qt.ItemIsEnabled)
        self.arbre.addTopLevelItem(g)
        g.setFirstColumnSpanned(True)
        return g

    def _ligne(self, jeton, valeur, role, ou, couleur, vide=""):
        it = QTreeWidgetItem([jeton, valeur if valeur is not None else vide, role, ou])
        it.setFont(COL_JETON, POLICE_CODE)
        it.setFont(COL_VALEUR, POLICE_CODE)
        it.setForeground(COL_JETON, QBrush(QColor(couleur)))
        it.setForeground(COL_VALEUR, QBrush(QColor(YELLOW if valeur is None else TEXT)))
        it.setForeground(COL_ROLE, QBrush(QColor(TEXT_DIM)))
        it.setForeground(COL_OU, QBrush(QColor(TEXT_MUTED)))
        it.setToolTip(COL_VALEUR, valeur if valeur is not None else vide)
        it.setToolTip(COL_OU, ou)
        it.setData(COL_JETON, Qt.UserRole, jeton)
        self.arbre.addTopLevelItem(it)
        return it

    def _remplir(self, *_) -> None:
        self.arbre.clear()
        self._remplir_attributs()
        b = self._courante()
        if b is None:
            base, branche = self.choix()
            suite = (f" Pour une cible, cocher « générer pour les cibles » sur la "
                     f"variation {branche}." if any(
                         x["nom"] == base and x["cible"]
                         for x in self._donnees.get("bases") or []) else "")
            self.lbl_note.setText(f"« {base} » n'a pas de mesure dans la branche "
                                  f"{branche}.{suite}" if base else "")
            return
        self.lbl_note.setText(self._note(b))
        val = b["valeurs"]
        for j, role in ROLES.items():
            if j.startswith("{"):
                v = self._variation if j == "{variation}" else val.get(j)
                self._ligne(j, v if v is not None else "", role, ou_se_regle(j, b), BLUE)
        portee = self._donnees.get("portee") or []
        if portee:                  # un ancien config (kpiTables) les utilise encore
            self._groupe("<<…>>  Tables de l'ICP (ancien réglage kpiTables du config)")
            for j in portee:
                self._ligne(j, val.get(j), ROLES.get(j, ""), "JSON brut → kpiTables",
                            ACCENT, vide="aucune table pour cet ICP")
        self.arbre.resizeColumnToContents(COL_JETON)

    def _remplir_attributs(self) -> None:
        kpi = self._kpi_courant()
        b = self._courante()
        self._attributs = list(self._donnees.get("attributs") or [])
        colonnes = self._donnees.get("colonnes") or []
        self.table.horizontalHeaderItem(A_VALEUR).setText(
            f"Valeur pour {kpi}" if kpi else "Valeur")
        self.ed_valeur.setPlaceholderText(f"valeur pour {kpi}" if kpi else "valeur")
        self._remplissage = True
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._attributs))
        for li, a in enumerate(self._attributs):
            label = a["jeton"][2:-2]
            actif = a["declare"]
            it = QTableWidgetItem(a["jeton"])
            it.setFont(POLICE_CODE)
            it.setForeground(QBrush(QColor(ACCENT if actif else TEXT_MUTED)))
            it.setData(Qt.UserRole, label)
            it.setToolTip("Le jeton, tel qu'il s'écrit dans le DAX.")
            if not actif:
                it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(li, A_JETON, it)

            cmb = QComboBox()
            cmb.setEditable(True)
            cmb.setInsertPolicy(QComboBox.NoInsert)
            cmb.addItems(colonnes)
            cmb.setCurrentText(a["colonne"])
            cmb.setEnabled(actif)
            cmb.activated.connect(lambda _i=0, l=label, c=cmb: self._on_colonne(l, c))
            cmb.lineEdit().editingFinished.connect(
                lambda l=label, c=cmb: self._on_colonne(l, c))
            self.table.setCellWidget(li, A_COLONNE, cmb)

            brute = (a.get("valeurs") or {}).get(kpi, "")
            v = QTableWidgetItem(brute)
            v.setFont(POLICE_CODE)
            v.setData(Qt.UserRole, brute)
            developpee = b["valeurs"].get(a["jeton"]) if b else None
            v.setToolTip(f"Dans le DAX : {developpee}" if developpee else
                         "Case vide : pas de mesure pour cet ICP.")
            if not actif or a.get("absente") or not kpi:
                v.setFlags(Qt.ItemIsEnabled)
                v.setForeground(QBrush(QColor(TEXT_MUTED)))
            self.table.setItem(li, A_VALEUR, v)

            b_ins = QToolButton()
            b_ins.setText("Insérer")
            b_ins.setToolTip("Met le jeton dans le DAX.")
            b_ins.setEnabled(actif)
            b_ins.clicked.connect(lambda _=False, j=a["jeton"]: self._plus_tard(self.inserer, j))
            self.table.setCellWidget(li, A_INSERER, b_ins)

            b_act = QToolButton()
            if actif:
                b_act.setText("✕")
                b_act.setToolTip("Retire le jeton. La colonne reste dans l'Excel.")
                b_act.clicked.connect(
                    lambda _=False, l=label: self._plus_tard(self.attribut_retire, l))
            else:
                b_act.setText("＋")
                b_act.setToolTip("Déclare ce jeton." if not a.get("absente")
                                 else "Crée la colonne dans l'Excel et déclare le jeton.")
                b_act.clicked.connect(
                    lambda _=False, l=label, c=a["colonne"]:
                    self._plus_tard(self.attribut_ajoute, l, c, "", self._kpi_courant()))
            self.table.setCellWidget(li, A_ACTION, b_act)
        self._remplissage = False

    @staticmethod
    def _note(b) -> str:
        if b["cible"]:
            return (f"« {b['nom']} » est une cible : {{base}} et {{baseRef}} la désignent, "
                    f"{{kpi}} et {{kpiRef}} désignent son ICP, {b['kpi']}. "
                    "Ses attributs sont ceux de la ligne de cet ICP.")
        if b["branche"]:
            return (f"En {b['branche']} : {{base}} et {{kpiRef}} suivent la branche, "
                    "{kpi} reste l'ICP.")
        return f"« {b['nom']} » est un ICP : {{base}} et {{kpi}} donnent le même nom."

    # ---- gestes ------------------------------------------------------------

    @staticmethod
    def _plus_tard(signal, *args) -> None:
        QTimer.singleShot(0, lambda: signal.emit(*args))

    def _on_double_clic(self, it, _col=0) -> None:
        jeton = it.data(COL_JETON, Qt.UserRole)
        if jeton:
            self.inserer.emit(jeton)

    def _on_case(self, it) -> None:
        if self._remplissage:
            return
        li, col = it.row(), it.column()
        if not 0 <= li < len(self._attributs) or col not in (A_JETON, A_VALEUR):
            return
        avant = it.data(Qt.UserRole) or ""
        a = self._attributs[li]
        if col == A_JETON:
            texte = nom_attribut(it.text())
            if texte == avant:              # même nom : la case reprend ses chevrons
                self._remplissage = True
                it.setText(a["jeton"])
                self._remplissage = False
            else:
                self._plus_tard(self.attribut_renomme, avant, texte)
            return
        texte = it.text().strip()
        if texte != avant:
            self._plus_tard(self.attribut_valeur, a["jeton"][2:-2], a["colonne"],
                            self._kpi_courant(), texte)

    def _on_colonne(self, label, cmb) -> None:
        if self._remplissage:
            return
        a = next((x for x in self._attributs if x["jeton"][2:-2] == label), None)
        try:
            texte = cmb.currentText().strip()
        except RuntimeError:        # la ligne vient d'être reconstruite
            return
        if a is not None and texte and texte != a["colonne"]:
            a["colonne"] = texte    # un seul envoi : activated puis editingFinished
            self._plus_tard(self.attribut_colonne, label, texte)

    def _ajouter(self) -> None:
        self._plus_tard(self.attribut_ajoute, nom_attribut(self.ed_jeton.text()),
                        self.cmb_colonne.currentText().strip(),
                        self.ed_valeur.text().strip(), self._kpi_courant())


class FenetreJetons(QDialog):
    """La fenêtre de l'explorateur : non modale, on écrit le DAX à côté."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jetons disponibles")
        self.setModal(False)
        self.resize(1080, 760)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.explorateur = ExplorateurJetons(self)
        v.addWidget(self.explorateur)

    def montrer(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
