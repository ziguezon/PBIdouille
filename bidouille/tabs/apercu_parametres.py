# -*- coding: utf-8 -*-
"""Mesures → Paramètres de champ, moitié du bas : ce que les tables
contiendront, avant de générer.

- la MATRICE dit quels KPI sont dans quelles tables (et combien de rangées
  chacun y a) ;
- le CONTENU montre la table choisie rangée par rangée, telle que Power BI
  la listera : ce qu'affiche la rangée (le calcul, le KPI ou son libellé),
  la mesure derrière, et les valeurs des colonnes KPI, Calcul et Branche.

Tout vient du générateur en aperçu (stats["parametres"]) sur le config en
mémoire et les réglages en cours : on voit ce que « Générer » écrira.
"""

from __future__ import annotations

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QBrush, QColor, QFont, QFontMetrics
from qtpy.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.theme import ACCENT, BLUE, RED, TEXT_DIM, TEXT_MUTED, YELLOW

COULEUR_ETAT = {"nouvelle": ACCENT, "modifiée": YELLOW, "vide": YELLOW,
                "source introuvable": YELLOW, "conflit": RED}
# colonnes du contenu
C_AFFICHAGE, C_MESURE, C_CALCUL, C_BRANCHE, C_ORDRE = range(5)
# autour du nom d'une table, dans l'en-tête de la matrice : le padding du thème
# et les marges du style
MARGE_ENTETE = 28


class ApercuParametres(QWidget):
    # l'usager a cliqué une table (matrice) : l'éditeur du haut la choisit,
    # ce qui revient ici par montrer_table
    table_demandee = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tables: list = []
        self._colonnes = {"kpi": "Indicateur", "calcul": "Calcul", "branche": "Branche"}
        self._courante = ""
        self._replies: set = set()       # (table, KPI) repliés par l'usager

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.lbl_resume = QLabel("")
        self.lbl_resume.setWordWrap(True)
        self.lbl_resume.setStyleSheet(f"color:{TEXT_DIM};")
        v.addWidget(self.lbl_resume)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        gb_m = QGroupBox("Quels KPI dans quelles tables")
        mv = QVBoxLayout(gb_m)
        self.matrice = QTableWidget()
        self.matrice.setEditTriggers(QTableWidget.NoEditTriggers)
        self.matrice.setSelectionMode(QTableWidget.SingleSelection)
        self.matrice.verticalHeader().setDefaultSectionSize(22)
        self.matrice.setToolTip("Le nombre de rangées de chaque KPI dans chaque table.\n"
                                "Cliquer sur une colonne ou une case : la table s'ouvre à droite.")
        self.matrice.cellClicked.connect(self._on_case)
        self.matrice.horizontalHeader().sectionClicked.connect(
            lambda c: self._demander(c, None))
        mv.addWidget(self.matrice)
        split.addWidget(gb_m)

        gb_c = QGroupBox("Contenu de la table")
        cv = QVBoxLayout(gb_c)
        haut = QHBoxLayout()
        self.lbl_table = QLabel("")
        self.lbl_table.setTextFormat(Qt.RichText)
        self.ed_filtre = QLineEdit()
        self.ed_filtre.setPlaceholderText("Filtrer (KPI, calcul, mesure…)")
        self.ed_filtre.setClearButtonEnabled(True)
        self.ed_filtre.textChanged.connect(self._filtrer)
        haut.addWidget(self.lbl_table, 1)
        haut.addWidget(self.ed_filtre, 1)
        cv.addLayout(haut)
        self.contenu = QTreeWidget()
        self.contenu.setColumnCount(5)
        self.contenu.setUniformRowHeights(True)
        h = self.contenu.header()
        for c in range(5):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        h.setStretchLastSection(False)
        self.contenu.itemCollapsed.connect(
            lambda it: self._replies.add((self._courante, it.data(0, Qt.UserRole))))
        self.contenu.itemExpanded.connect(
            lambda it: self._replies.discard((self._courante, it.data(0, Qt.UserRole))))
        cv.addWidget(self.contenu, 1)
        split.addWidget(gb_c)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        v.addWidget(split, 1)

        self.lbl_avis = QLabel("")
        self.lbl_avis.setWordWrap(True)
        self.lbl_avis.setStyleSheet(f"color:{YELLOW};")
        self.lbl_avis.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_avis.hide()
        v.addWidget(self.lbl_avis)

    # ---- API ---------------------------------------------------------------

    def afficher(self, tables, colonnes=None, actif=True, avis=()) -> None:
        """`tables` : stats["parametres"] du générateur ; `colonnes` :
        stats["parametres_colonnes"] ; `actif` : la génération des tables
        est-elle cochée."""
        self._tables = list(tables or [])
        self._colonnes = dict(colonnes or self._colonnes)
        avis = [a for a in avis if a]
        self.lbl_avis.setText("\n".join(avis[:4]))
        self.lbl_avis.setVisible(bool(avis))
        if not actif:
            self.lbl_resume.setText(
                "Les tables paramètre ne sont pas générées : la case "
                "« Générer les tables paramètre de champ » est décochée.")
        else:
            n_kpi = len({r["indicateur"] for t in self._tables for r in t["rangees"]})
            self.lbl_resume.setText(
                f"{len(self._tables)} table(s), {n_kpi} KPI. Colonnes : "
                f"{self._colonnes['kpi']} (le KPI), {self._colonnes['calcul']}, "
                f"{self._colonnes['branche']}. Aperçu des réglages en cours, "
                "rien n'est écrit.")
        self._remplir_matrice()
        noms = [t["name"] for t in self._tables]
        self.montrer_table(self._courante if self._courante in noms
                           else (noms[0] if noms else ""))

    def erreur(self, texte: str) -> None:
        self._tables = []
        self.matrice.clear()
        self.matrice.setRowCount(0)
        self.matrice.setColumnCount(0)
        self.contenu.clear()
        self.lbl_table.setText("")
        self.lbl_resume.setText("")
        self.lbl_avis.setText(texte)
        self.lbl_avis.setVisible(True)

    def montrer_table(self, nom: str, kpi: str | None = None) -> None:
        """Le contenu de la table `nom` ; `kpi` : la faire défiler jusqu'à
        ce KPI."""
        self._courante = nom or ""
        # la colonne de la table ouverte se reconnaît dans la matrice. La police
        # part de celle de l'en-tête : celle d'un élément neuf n'est pas celle
        # que le thème affiche
        base = self.matrice.horizontalHeader().font()
        for c in range(self.matrice.columnCount()):
            h = self.matrice.horizontalHeaderItem(c)
            if h is not None:
                f = QFont(base)
                f.setBold(h.text() == self._courante)
                h.setFont(f)
                h.setForeground(QBrush(QColor(ACCENT if h.text() == self._courante
                                              else TEXT_DIM)))
        t = next((x for x in self._tables if x["name"] == nom), None)
        self.contenu.clear()
        col = self._colonnes
        self.contenu.setHeaderLabels(
            ["Affichage", "Mesure", col["calcul"], col["branche"], "Ordre"])
        if t is None:
            self.lbl_table.setText(f"<span style='color:{TEXT_MUTED}'>"
                                   "Aucune table choisie.</span>")
            return
        etat = t.get("etat") or ""
        couleur = COULEUR_ETAT.get(etat, TEXT_DIM)
        quoi = "un KPI par rangée" if t.get("rows") == "kpi" else "un calcul par rangée"
        self.lbl_table.setText(
            f"<b>{_html(t['name'])}</b>  <span style='color:{TEXT_DIM}'>"
            f"{len(t['rangees'])} rangées, {quoi}</span>"
            + (f"  <span style='color:{couleur}'>{_html(etat)}</span>" if etat else ""))
        if not t["rangees"]:
            vide = QTreeWidgetItem(["Aucune rangée après les filtres de la table : "
                                    "le générateur n'y touchera pas."])
            vide.setForeground(0, QBrush(QColor(YELLOW)))
            self.contenu.addTopLevelItem(vide)
            return
        groupes: dict = {}
        for r in t["rangees"]:
            groupes.setdefault(r["indicateur"], []).append(r)
        cible = None
        for k, rangees in groupes.items():
            g = QTreeWidgetItem([k, "", "", "", ""])
            g.setData(0, Qt.UserRole, k)
            f = QFont(g.font(0))
            f.setBold(True)
            g.setFont(0, f)
            g.setText(C_MESURE, f"{len(rangees)} rangée{'s' if len(rangees) > 1 else ''}")
            g.setForeground(C_MESURE, QBrush(QColor(TEXT_MUTED)))
            g.setToolTip(0, f"{col['kpi']} = « {k} »")
            for r in rangees:
                g.addChild(self._rangee(r))
            self.contenu.addTopLevelItem(g)
            g.setExpanded((nom, k) not in self._replies)
            if k == kpi:
                cible = g
        if cible is not None:
            cible.setExpanded(True)
            self.contenu.scrollToItem(cible, QTreeWidget.PositionAtTop)
            self.contenu.setCurrentItem(cible)
        self._filtrer()

    def table_courante(self) -> str:
        return self._courante

    # ---- construction ----------------------------------------------------------

    def _rangee(self, r) -> QTreeWidgetItem:
        aff = r["affichage"]
        if r.get("libelle") and not r.get("libelle_trouve"):
            aff = f"libellé de « {r['indicateur']} »"
        it = QTreeWidgetItem([aff, r["mesure"], r["calcul"], r["branche"], str(r["ordre"])])
        if r.get("libelle"):
            f = QFont(it.font(0))
            f.setItalic(True)
            it.setFont(0, f)
            it.setForeground(0, QBrush(QColor(BLUE)))
            it.setToolTip(0, "Le LIBELLÉ du KPI, lu par LOOKUPVALUE dans la table de "
                             "correspondance"
                          + ("." if r.get("libelle_trouve") else
                             " (introuvable dans l'Excel : la valeur n'existera "
                             "qu'au rafraîchissement)."))
        it.setForeground(C_ORDRE, QBrush(QColor(TEXT_MUTED)))
        it.setToolTip(C_MESURE, "[" + r["mesure"] + "]")
        return it

    def _remplir_matrice(self) -> None:
        m = self.matrice
        m.clear()
        kpis: list = []
        for t in self._tables:
            for r in t["rangees"]:
                if r["indicateur"] not in kpis:
                    kpis.append(r["indicateur"])
        m.setRowCount(len(kpis))
        m.setColumnCount(len(self._tables))
        m.setHorizontalHeaderLabels([t["name"] for t in self._tables])
        m.setVerticalHeaderLabels(kpis)
        for c, t in enumerate(self._tables):
            par_kpi: dict = {}
            for r in t["rangees"]:
                par_kpi.setdefault(r["indicateur"], []).append(r)
            for li, k in enumerate(kpis):
                rs = par_kpi.get(k, [])
                case = QTableWidgetItem(str(len(rs)) if rs else "0")
                case.setTextAlignment(Qt.AlignCenter)
                if rs:
                    calculs = list(dict.fromkeys(r["calcul"] for r in rs))
                    case.setToolTip(f"{k} dans {t['name']} : {len(rs)} rangées\n"
                                    + ", ".join(calculs))
                    case.setForeground(QBrush(QColor(ACCENT)))
                else:
                    case.setToolTip(f"{k} n'est pas dans {t['name']}.")
                    case.setForeground(QBrush(QColor(TEXT_MUTED)))
                m.setItem(li, c, case)
        # chaque colonne a la largeur de son nom EN GRAS : le nom reste entier
        # quand sa table est ouverte, et les colonnes ne bougent pas au choix
        h = m.horizontalHeader()
        h.ensurePolished()
        h.setSectionResizeMode(QHeaderView.Interactive)
        gras = QFont(h.font())
        gras.setBold(True)
        mesure = QFontMetrics(gras)
        for c, t in enumerate(self._tables):
            largeur = (mesure.horizontalAdvance(t["name"])
                       if hasattr(mesure, "horizontalAdvance") else mesure.width(t["name"]))
            h.resizeSection(c, largeur + MARGE_ENTETE)
        m.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    # ---- gestes ----------------------------------------------------------------

    def _on_case(self, ligne, colonne) -> None:
        kpi = self.matrice.verticalHeaderItem(ligne)
        self._demander(colonne, kpi.text() if kpi else None)

    def _demander(self, colonne, kpi) -> None:
        if not (0 <= colonne < len(self._tables)):
            return
        nom = self._tables[colonne]["name"]
        self.table_demandee.emit(nom)
        # l'éditeur a peut-être déjà renvoyé montrer_table(nom) ; on y ajoute
        # le KPI visé
        self.montrer_table(nom, kpi)

    def _filtrer(self, *_) -> None:
        txt = self.ed_filtre.text().strip().lower()
        for i in range(self.contenu.topLevelItemCount()):
            g = self.contenu.topLevelItem(i)
            moi = txt in g.text(0).lower()
            n_vis = 0
            for j in range(g.childCount()):
                e = g.child(j)
                vis = not txt or moi or any(txt in e.text(c).lower() for c in range(5))
                e.setHidden(not vis)
                n_vis += vis
            g.setHidden(bool(txt) and n_vis == 0 and not moi)


def _html(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
