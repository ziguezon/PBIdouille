# -*- coding: utf-8 -*-
"""Onglet « Radiographie 🩻 » : comprendre vite un rapport qu'on n'a pas fait.

À gauche, les vues du même rapport, d'abord le LIGNAGE (tabs/vue_lignage.py) :
tout le rapport en un graphe, de la source de données au visuel, en passant
par Power Query, les tables calculées, les mesures, les paramètres de champ,
les filtres et les segments. Puis :
  · PAR PAGE : la carte : chaque page, ses visuels, ce que chacun affiche, à
    quoi mène chaque mesure (ses mesures de base) et ce qui filtre le visuel
    (filtres du volet, de la page, du rapport, segments de la page) ;
  · PAR KPI : les familles de mesures (un KPI et ses variations), de la plus
    affichée à la moins affichée, puis les briques (les mesures que d'autres
    reprennent), les mesures jamais affichées, et les variations repérées ;
  · PAR COLONNE : chaque colonne utilisée, et où : segments, filtres,
    visuels, mesures. Ce qu'il faut regarder quand un chiffre est faux ;
  · PAR SOURCE : d'où vient chaque table (Excel, CSV, ODBC…, tabs/
    tab_lineage.py), et combien d'éléments du rapport en dépendent : tables
    et colonnes calculées, mesures, filtres et segments, visuels
    (radiographie.dependants). La fiche en donne la liste, pour la table et
    pour toute sa source.
Dans la vue Par page, les champs d'un visuel sont rangés par RÔLE, comme dans
le volet Visualisations (Axe, Valeurs, Légende…), et les variations d'un même
KPI tiennent sur une ligne repliée. Sous les vues Par page et Par colonne,
les pastilles « Afficher » éteignent une catégorie de lignes (mesures,
colonnes, filtres, segments, visuels masqués ; usages par genre).
À droite, la fiche de ce qui est choisi : mesure, visuel, page, colonne ou
paramètre de champ, avec des liens pour passer de l'un à l'autre. Sans choix,
ou par le bouton « Vue d'ensemble », la fiche résume le rapport : ses KPI, et
page par page, ce que chaque visuel affiche, par quoi, et ce qui le filtre.

Rien n'y dépend de PBIdouille : ni config, ni TD_Indicateurs, ni annotation.
Tout se déduit du DAX, des noms et des visual.json (moteurs/radiographie.py).
Lecture seule.
"""

from __future__ import annotations

import html
from pathlib import Path

from qtpy.QtCore import QRect, Qt
from qtpy.QtGui import QBrush, QColor, QFont, QFontMetrics
from qtpy.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import lignage as lgn
import lineage as lg
import radiographie as rg
from core.journal import Journal
from core.project import lire_reglage, ecrire_reglage
from core.puces import Puces
from tabs.tab_lineage import LineageTab, source_et_lieu, type_de
from tabs.vue_lignage import VueLignage
from core.theme import (ACCENT, BLUE, BORDER, ORANGE, SURFACE_ALT, TEXT, TEXT_DIM,
                        TEXT_MUTED, TITRE_POLICE, TITRE_PT, YELLOW)

C_NOM, C_VAR, C_VUS, C_TABLE = 0, 1, 2, 3
ROLE = Qt.UserRole
CATEGORIE = Qt.UserRole + 1      # ce que les pastilles « Afficher » allument ou éteignent
CONTENEUR = Qt.UserRole + 2      # un nœud qui n'a de sens qu'avec un enfant visible
PREFIXE = Qt.UserRole + 3        # le début du nom, en gris : « Axe : », « Courbes · »
SUFFIXE = Qt.UserRole + 4        # la fin du nom, en gris : « · 16 mesures »
# ce que « Déplier » laisse fermé dans la vue Par page : le détail d'une famille
# ou d'un paramètre de champ, une ligne par mesure, qui noierait les visuels
REPLIES = ("mesure", "famille", "parametre")
GROUPE_BRIQUES = "Briques"
# les pastilles de chaque vue : (clé, libellé, infobulle)
PUCES_PAGES = (
    ("mesures", "Mesures", "Les mesures et les paramètres de champ des visuels"),
    ("colonnes", "Colonnes", "Les colonnes des visuels : axes, lignes, légendes"),
    ("filtres", "Filtres", "Ce qui filtre chaque visuel : filtres du volet, de la page, du "
                           "rapport, et segments de la page"),
    ("segments", "Segments", "Les segments, dans la liste des visuels de chaque page"),
    ("masques", "Visuels masqués", "Les visuels masqués dans le volet Sélection"),
)
PUCES_COLONNES = (
    ("segments", "Segments", "Les segments qui filtrent sur la colonne"),
    ("filtres", "Filtres", "Les filtres du rapport, des pages et des visuels"),
    ("visuels", "Visuels", "Les visuels qui affichent la colonne"),
    ("mesures", "Mesures", "Les mesures dont le DAX lit la colonne"),
)
CATEGORIE_USAGE = {"segment": "segments", "filtre de rapport": "filtres",
                   "filtre de page": "filtres", "filtre de visuel": "filtres",
                   "visuel": "visuels", "mesure": "mesures"}
GROUPE_JAMAIS = "Jamais affichées"
GROUPE_PATRONS = "Variations repérées"
MAX_LISTE = 40          # au-delà, une liste de la fiche se résume
# une liste de la fiche plus longue que PLIER_APRES ne montre que ses
# PREMIERES lignes, et un lien « afficher les N autres » : la fiche se lit
# d'un coup d'œil, le détail reste à un clic
PLIER_APRES = 4
PREMIERES = 2
DAX_LIGNES = 8          # un DAX plus long se replie sur ses premières lignes


def _e(s) -> str:
    return html.escape(str(s))


def _vus(n_vis: int, n_pages: int | None = None) -> str:
    if not n_vis:
        return "·"
    s = f"{n_vis} visuel" + ("s" if n_vis > 1 else "")
    if n_pages is not None:
        s += f" · {n_pages} page" + ("s" if n_pages > 1 else "")
    return s


class _NomEnDeuxTons(QStyledItemDelegate):
    """La colonne du nom avec un début et une fin en gris : le rôle d'un champ
    (« Axe : »), le type d'un visuel (« Courbes · »), le compte d'une famille
    (« · 16 mesures »). L'œil lit d'abord ce qui compte, le nom."""

    def paint(self, painter, option, index):
        prefixe = index.data(PREFIXE) or ""
        suffixe = index.data(SUFFIXE) or ""
        if index.column() != C_NOM or not (prefixe or suffixe):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        texte = opt.text
        if not (texte.startswith(prefixe) and texte.endswith(suffixe)):
            super().paint(painter, option, index)
            return
        milieu = texte[len(prefixe):len(texte) - len(suffixe)]
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        opt.text = ""                   # le fond, la sélection, l'icône : comme d'habitude
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        zone = style.subElementRect(QStyle.SE_ItemViewItemText, opt, widget)
        marge = style.pixelMetric(QStyle.PM_FocusFrameHMargin, None, widget) + 1
        zone = zone.adjusted(marge, 0, -marge, 0)
        brosse = index.data(Qt.ForegroundRole)
        principal = brosse.color() if isinstance(brosse, QBrush) else QColor(TEXT)
        fm = QFontMetrics(opt.font)
        painter.save()
        painter.setFont(opt.font)
        x = zone.left()
        # sur le vert de la sélection, le gris des bouts doit rester lisible
        bouts = QColor(TEXT_DIM if opt.state & QStyle.State_Selected else TEXT_MUTED)
        for morceau, couleur in ((prefixe, bouts), (milieu, principal), (suffixe, bouts)):
            reste = zone.right() - x
            if not morceau or reste <= 0:
                continue
            vu = fm.elidedText(morceau, Qt.ElideRight, reste)
            painter.setPen(couleur)
            painter.drawText(QRect(x, zone.top(), reste, zone.height()),
                             int(Qt.AlignVCenter | Qt.AlignLeft | Qt.TextSingleLine), vu)
            x += fm.horizontalAdvance(vu)
        painter.restore()


class RadiographieTab(QWidget):
    def __init__(self, journal=None):
        super().__init__()
        self.journal = journal or Journal()
        self._pbip = None
        self._pending = False
        self.res: dict = {}
        self._item_mesure: dict = {}     # nom -> item de la vue Par KPI
        self._item_visuel: dict = {}     # (page_id, id) -> item de la vue Par page
        self._liens: list = []           # cible des liens de la fiche
        self._ouverts: set = set()       # listes de la fiche dépliées
        self._fiche_courante = None      # (fabrique, args) de la fiche affichée
        self.dep_colonnes: list = []     # ce qui dépend de chaque colonne utilisée

        v = QVBoxLayout(self)
        haut = QHBoxLayout()
        self.ed_filtre = QLineEdit()
        self.ed_filtre.setPlaceholderText("Filtrer (mesure, page, visuel…)")
        self.ed_filtre.setClearButtonEnabled(True)
        self.ed_filtre.textChanged.connect(self._filtrer)
        b_relire = QPushButton("↻ Relire")
        b_relire.setToolTip("Relit le modèle et les pages du rapport.")
        b_relire.clicked.connect(self.reload)
        self.btn_ensemble = QPushButton("Vue d'ensemble")
        self.btn_ensemble.setToolTip("Résume le rapport dans la fiche : ses KPI, et page par "
                                     "page, ce que chaque visuel affiche.")
        self.btn_ensemble.clicked.connect(self._vider_fiche)
        # la fiche se ferme pour laisser la place au graphe ou aux listes ;
        # le choix est retenu d'une session à l'autre
        self.btn_fiche = QPushButton("")
        self.btn_fiche.setCheckable(True)
        self.btn_fiche.setToolTip("Montre ou cache la fiche, à droite.")
        self.btn_fiche.toggled.connect(self._montrer_fiche)
        haut.addWidget(self.ed_filtre, 1)
        haut.addWidget(self.btn_ensemble)
        haut.addWidget(self.btn_fiche)
        haut.addWidget(b_relire)
        v.addLayout(haut)

        self.lbl_resume = QLabel("")
        self.lbl_resume.setWordWrap(True)
        self.lbl_resume.setStyleSheet(f"color:{TEXT_DIM};")
        self.lbl_resume.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.lbl_resume)

        split = QSplitter(Qt.Horizontal)
        gauche = QWidget()
        vg = QVBoxLayout(gauche)
        vg.setContentsMargins(0, 0, 0, 0)
        self.vues = QTabWidget()
        self.vues.setObjectName("sousOnglets")
        self.arbre_kpi = self._arbre(["Mesure", "Variation", "Affichée", "Table"])
        self.arbre_pages = self._arbre(["Page / visuel / champ", "Mène à", "Détail", "Table"])
        # les pages ont un bandeau plus haut que les autres lignes
        self.arbre_pages.setUniformRowHeights(False)
        # la carte du rapport d'abord : page, visuel, ce qu'il affiche, à quoi
        # ça mène et ce qui le filtre
        self.arbre_cols = self._arbre(["Table / colonne / usage", "Mesures", "Filtres",
                                       "Visuels", "Détail"], comptes=True)
        # d'où vient chaque table, et ce qui en dépend dans le rapport
        self.vue_sources = LineageTab(self.journal, integre=True)
        self.vue_sources.choisi.connect(self._montrer_source)
        # tout, de la source au visuel, en un graphe
        self.vue_lignage = VueLignage(self.journal)
        self.vue_lignage.choisi.connect(self._montrer_noeud)
        # du plus large au plus fin : le lignage, d'où viennent les données, ce
        # que montre chaque page, où sert chaque colonne, les familles de mesures
        self.vues.addTab(self.vue_lignage, "Lignage")
        self.vues.addTab(self.vue_sources, "Par source")
        self.vues.addTab(self.arbre_pages, "Par page")
        self.vues.addTab(self.arbre_cols, "Par colonne")
        self.vues.addTab(self.arbre_kpi, "Par KPI")
        self.lineage: dict = {}
        self.impacts: dict | None = None
        self.vues.currentChanged.connect(lambda *_: self._montrer_puces())
        vg.addWidget(self.vues, 1)
        # la vue Par KPI dit comment elle range : rien n'y vient d'un config
        self.lbl_kpi = QLabel(
            "Une <b>famille</b> : un KPI et les mesures dont le DAX le reprend en ajoutant "
            "quelque chose à son nom (<i>Ventes YTD</i> utilise <i>[Ventes]</i>). La colonne "
            "Variation donne cet ajout. Tout vient du DAX et des noms, sur n'importe quel "
            "rapport. Nom en <i>italique</i> ou variation en "
            f"<span style='color:{YELLOW}'>jaune</span> : rapprochées par le nom seulement, "
            "à vérifier.")
        self.lbl_kpi.setWordWrap(True)
        self.lbl_kpi.setStyleSheet(f"color:{TEXT_DIM};")
        vg.addWidget(self.lbl_kpi)

        # sous la vue : ce qu'elle montre, et de quoi tout déplier d'un coup
        bas = QHBoxLayout()
        self.puces_pages = Puces("Afficher :", exclusive=False)
        self.puces_pages.remplir(PUCES_PAGES)
        self.puces_cols = Puces("Afficher :", exclusive=False)
        self.puces_cols.remplir(PUCES_COLONNES)
        for p in (self.puces_pages, self.puces_cols):
            p.change.connect(lambda: self._filtrer(self.ed_filtre.text()))
            bas.addWidget(p, 100)
        self.btn_deplier = QPushButton("Déplier")
        self.btn_deplier.setToolTip("Déplie tout ce que la vue montre.")
        self.btn_deplier.clicked.connect(lambda: self._deplier(True))
        self.btn_replier = QPushButton("Replier")
        self.btn_replier.setToolTip("Replie la vue sur ses pages, ses familles ou ses tables.")
        self.btn_replier.clicked.connect(lambda: self._deplier(False))
        bas.addStretch(1)
        bas.addWidget(self.btn_deplier)
        bas.addWidget(self.btn_replier)
        vg.addLayout(bas)
        split.addWidget(gauche)
        self._montrer_puces()

        self.fiche = QTextBrowser()
        self.fiche.setOpenLinks(False)
        self.fiche.anchorClicked.connect(self._lien)
        split.addWidget(self.fiche)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self._split = split
        self._partage_fait = False
        v.addWidget(split, 1)
        self._vider_fiche()
        self.btn_fiche.setChecked(lire_reglage("radiographie_fiche", "1") != "0")
        self._montrer_fiche(self.btn_fiche.isChecked())

    def _montrer_fiche(self, oui: bool):
        self.fiche.setVisible(oui)
        self.btn_fiche.setText("Masquer la fiche" if oui else "Afficher la fiche")
        self.btn_fiche.blockSignals(True)
        self.btn_fiche.setChecked(oui)
        self.btn_fiche.blockSignals(False)
        ecrire_reglage("radiographie_fiche", "1" if oui else "0")

    @property
    def graphe(self) -> dict:
        """Le graphe du lignage, tel que la vue le montre : elle le reconstruit
        quand une famille se déplie en mesures."""
        return self.vue_lignage.graphe

    def _arbre(self, entetes, comptes=False) -> QTreeWidget:
        a = QTreeWidget()
        a.setColumnCount(len(entetes))
        a.setHeaderLabels(entetes)
        a.setUniformRowHeights(True)
        h = a.header()
        dernier = len(entetes) - 1
        if comptes:
            # des colonnes de nombres, à leur largeur, entre le nom et le détail
            h.setSectionResizeMode(C_NOM, QHeaderView.Interactive)
            for c in range(1, dernier):
                h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        else:
            # la 2e colonne (Mène à, Variation) peut être longue : une largeur
            # fixe, le texte entier au survol, pour que Détail reste visible
            for c in (C_NOM, C_VAR):
                h.setSectionResizeMode(c, QHeaderView.Interactive)
            h.setSectionResizeMode(C_VUS, QHeaderView.ResizeToContents)
            a.setColumnWidth(C_VAR, 200)
        # la dernière colonne prend le reste : le bandeau d'une page va jusqu'au bord
        h.setSectionResizeMode(dernier, QHeaderView.Stretch)
        h.setStretchLastSection(True)
        a.setColumnWidth(C_NOM, 300)
        a.setItemDelegate(_NomEnDeuxTons(a))
        a.currentItemChanged.connect(lambda cur, _prev: self._montrer(cur))
        return a

    # ---- projet (différé : changer de projet reste instantané) ----------------

    def set_project(self, project):
        self._pbip = str(project.pbip)
        self._pending = True
        if self.isVisible():
            self._analyser()

    def reload(self):
        if not self._pbip:
            return
        self._pending = True
        if self.isVisible():
            self._analyser()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._partage_fait and self.width() > 200:
            # trois cinquièmes pour la vue, deux pour la fiche, quelle que soit
            # la largeur de la rangée de pastilles
            self._partage_fait = True
            self._split.setSizes([self.width() * 3 // 5, self.width() * 2 // 5])
        if self._pending:
            self._analyser()

    def _analyser(self):
        self._pending = False
        # les sources d'abord : elles se lisent même sans modèle local
        # (connexion live), quand le reste ne le peut pas
        try:
            self.lineage = lg.scan_projet(self._pbip)
        except (OSError, UnicodeDecodeError) as e:
            self.lineage = {"lignes": [], "erreur": f"lecture impossible : {e}"}
        self.impacts = None
        try:
            self.res = rg.analyser(self._pbip)
        except (OSError, UnicodeDecodeError, ValueError, SystemExit) as e:
            self.res = {}
            self.arbre_kpi.clear()
            self.arbre_pages.clear()
            self.arbre_cols.clear()
            self.lbl_resume.setText(f"Lecture impossible : {e}")
            self.journal.erreur(f"Radiographie : lecture impossible ({e})")
            self.vue_sources.afficher(self.lineage, None)
            self.vue_lignage.afficher(None)
            self._vider_fiche()
            return
        try:
            modele = self.lineage.get("modele_dir")
            cc = lg.colonnes_calculees(modele) if modele else []
            self.impacts = rg.dependants(self.res, self.lineage.get("lignes") or [], cc)
        except (OSError, UnicodeDecodeError) as e:
            self.journal.erreur(f"Radiographie : dépendances des sources illisibles ({e})")
        self.vue_sources.afficher(self.lineage, self.impacts)
        res, lignes = self.res, self.lineage.get("lignes") or []
        self.vue_lignage.dossier = str(Path(self._pbip).parent)
        self.vue_lignage.afficher(lgn.construire(res, lignes),
                                  lambda deplies: lgn.construire(res, lignes, deplies))
        self._construire()

    # ---- construction --------------------------------------------------------

    @staticmethod
    def _item(textes, donnee=None) -> QTreeWidgetItem:
        it = QTreeWidgetItem([str(t) for t in textes])
        it.setData(C_NOM, ROLE, donnee)
        for c, t in enumerate(textes):
            if t:
                it.setToolTip(c, str(t))
        return it

    @staticmethod
    def _teinter(it, couleur, colonnes=(C_NOM, C_VAR, C_VUS, C_TABLE)):
        for c in colonnes:
            it.setForeground(c, QBrush(QColor(couleur)))

    @staticmethod
    def _deux_tons(it, prefixe="", suffixe="") -> QTreeWidgetItem:
        """Le début et la fin du nom en gris (voir _NomEnDeuxTons)."""
        if prefixe:
            it.setData(C_NOM, PREFIXE, prefixe)
        if suffixe:
            it.setData(C_NOM, SUFFIXE, suffixe)
        return it

    def _bandeau(self, it, n_colonnes=4) -> QTreeWidgetItem:
        """Une page (ou les filtres du rapport) : un bandeau sur toute la
        largeur, dans la police des titres, pour qu'on voie où commence chaque
        page même tout déplié."""
        police = QFont(TITRE_POLICE)
        police.setPointSize(TITRE_PT)
        it.setFont(C_NOM, police)
        for c in range(n_colonnes):
            it.setBackground(c, QBrush(QColor(BORDER)))
        self._teinter(it, TEXT, (C_NOM,))
        self._teinter(it, TEXT_DIM, (C_VAR, C_VUS, C_TABLE))
        return it

    def _construire(self):
        r = self.res
        nv = len(r["visuels"])
        n_fam = sum(1 for f in r["kpis"] if f["membres"])
        self.lbl_resume.setText(
            f"{len(r['mesures'])} mesures · {len(r['kpis'])} KPI, dont {n_fam} avec des "
            f"variations · {nv} visuels sur {len(r['pages'])} page(s) · "
            f"{len(r['parametres'])} paramètre(s) de champ · {len(r['briques'])} brique(s) · "
            f"{len(r['colonnes_utilisees'])} colonne(s) utilisée(s)")
        self._construire_kpi()
        self._construire_pages()
        self._construire_colonnes()
        self._filtrer(self.ed_filtre.text())
        self._vider_fiche()

    def _feuille_mesure(self, nom, variation="", par=None) -> QTreeWidgetItem:
        r = self.res
        m = r["mesures"][nom]
        n = len({(v["page_id"], v["id"]) for v, _ in r["affichee"][nom]})
        it = self._item([nom, variation, _vus(n), m["table"]], ("mesure", nom))
        if par == rg.NOM:
            it.setToolTip(C_VAR, f"{variation}\n\nRapprochée par le NOM seulement : "
                                 "elle ne référence pas la mesure de base.")
            it.setForeground(C_VAR, QBrush(QColor(YELLOW)))
        if not n:
            self._teinter(it, TEXT_MUTED, (C_NOM, C_VUS))
        self._item_mesure.setdefault(nom, it)
        return it

    def _construire_kpi(self):
        r = self.res
        a = self.arbre_kpi
        a.setUpdatesEnabled(False)
        a.clear()
        self._item_mesure = {}
        gras = QFont(a.font())
        gras.setBold(True)
        italique = QFont(gras)
        italique.setItalic(True)

        for f in r["kpis"]:
            n_var = len(f["membres"])
            var = f"{n_var} variation" + ("s" if n_var > 1 else "") if n_var else ""
            if f["reel"]:
                top = self._feuille_mesure(f["kpi"], var)
                top.setText(C_VUS, _vus(f["visuels"], f["pages"]))
                top.setToolTip(C_VUS, f"Le KPI et ses variations : {_vus(f['visuels'], f['pages'])}"
                                      f"\nLe KPI lui-même : {_vus(f['visuels_kpi'])}")
            else:
                top = self._item([f["kpi"] + " …", var, _vus(f["visuels"], f["pages"]), ""],
                                 ("famille", f["kpi"]))
                top.setToolTip(C_NOM, "Famille rapprochée par le NOM : ces mesures commencent "
                                      "par les mêmes mots, mais aucune ne référence l'autre.")
            top.setFont(C_NOM, italique if f["genre"] == rg.NOM else gras)
            if f["genre"] == rg.NOM:
                self._teinter(top, YELLOW, (C_VAR,))
            if not f["visuels"]:
                self._teinter(top, TEXT_MUTED, (C_NOM, C_VUS))
            for x in f["membres"]:
                top.addChild(self._feuille_mesure(x["nom"], x["patron"], x["par"]))
            a.addTopLevelItem(top)

        def groupe(titre, aide, enfants):
            g = self._item([f"{titre} ({len(enfants)})", "", "", ""], ("groupe", titre))
            g.setFont(C_NOM, gras)
            g.setToolTip(C_NOM, aide)
            self._teinter(g, BLUE, (C_NOM,))
            for e in enfants:
                g.addChild(e)
            a.addTopLevelItem(g)
            return g

        briques = []
        for b in r["briques"]:
            it = self._feuille_mesure(b["nom"])
            it.setText(C_VAR, f"utilisée par {len(b['utilisateurs'])}")
            it.setToolTip(C_VAR, "Utilisée par :\n" + "\n".join(b["utilisateurs"][:MAX_LISTE]))
            briques.append(it)
        groupe(GROUPE_BRIQUES, "Mesures que d'autres mesures reprennent, hors de leur "
                               "propre famille : souvent invisibles dans les visuels, et "
                               "ce qu'il faut lire en premier.", briques)
        groupe(GROUPE_JAMAIS, "Ni affichées par un visuel, ni dans une famille, ni "
                              "reprises par d'autres mesures. ChopChop dit si on peut "
                              "les supprimer.",
               [self._feuille_mesure(n) for n in r["jamais"]])
        patrons = []
        for p, n in r["patrons"]:
            it = self._item([p, f"{n} KPI", "", ""], ("patron", p))
            patrons.append(it)
        g = groupe(GROUPE_PATRONS, "Les variations écrites pour plusieurs KPI : le nom de "
                                   "la variation, son KPI remplacé par « … ».", patrons)
        g.setExpanded(False)
        a.setUpdatesEnabled(True)

    def _mene_a(self, nom) -> tuple:
        """(texte court, infobulle) de ce à quoi mène une mesure : ses mesures
        de base, ou, si elle en est une, les colonnes qu'elle lit."""
        r = self.res
        bases = r["bases"][nom]
        if bases:
            cols = [c for b in bases for c in r["colonnes"][b]]
            tip = ("Mesures de base :\n" + "\n".join(f"[{b}]" for b in bases)
                   + ("\n\nColonnes lues :\n" + "\n".join(f"'{t}'[{c}]" for t, c in cols)
                      if cols else ""))
            return ", ".join(bases), tip
        cols = r["colonnes"][nom]
        if cols:
            return ("lit " + ", ".join(f"'{t}'[{c}]" for t, c in cols),
                    "Mesure de base : elle lit directement ces colonnes.")
        return "", ""

    @staticmethod
    def texte_filtre(f) -> str:
        champ = (f"[{f['nom']}]" if f["genre"] == "Measure"
                 else f"'{f['table']}'[{f['nom']}]" if f["table"] else f["nom"])
        return f"{champ} {f['texte']}" if f["actif"] else f"{champ} (aucune valeur choisie)"

    def _noeud_filtres(self, titre, filtres, segments=()) -> QTreeWidgetItem | None:
        """« Filtré par » : filtres (visuel, page, rapport) et segments de la
        page qui ont une sélection. Les champs du volet SANS valeur ne filtrent
        rien (Power BI y pose chaque champ du visuel) : ils tiennent sur une
        seule ligne grisée, la liste en infobulle."""
        actifs = [f for f in filtres if f["actif"]]
        vides = [f for f in filtres if not f["actif"]]
        if not filtres and not segments:
            return None
        if not actifs and not segments:
            # rien ne filtre : une ligne, pas un nœud à déplier pour n'y rien trouver
            it = self._item([f"{titre} : rien", "", f"{len(vides)} champ(s) sans valeur", ""],
                            ("filtre", None))
            it.setToolTip(C_NOM, "Dans le volet des filtres, sans valeur choisie :\n"
                          + "\n".join(self.texte_filtre(f).split(" (")[0]
                                      for f in vides[:MAX_LISTE]))
            self._teinter(it, TEXT_MUTED)
            return self._ranger(it, "filtres")
        g = self._item([f"{titre} ({len(actifs) + len(segments)})", "", "", ""],
                       ("filtres", None))
        self._teinter(g, BLUE, (C_NOM,))
        self._ranger(g, "filtres")
        for f in actifs:
            g.addChild(self._ranger(self._item([self.texte_filtre(f), "",
                                                f"filtre de {f['niveau']}", f["table"]],
                                               ("filtre", None)), "filtres"))
        for s in segments:
            it = self._item([f"{s['libelle']} {s['selection']}", "", "segment de la page", ""],
                            ("visuel", (s["page_id"], s["id"])))
            g.addChild(self._ranger(it, "filtres"))
        if vides:
            it = self._item([f"{len(vides)} champ(s) dans le volet, sans valeur", "",
                             "ne filtrent rien", ""], ("filtre", None))
            it.setToolTip(C_NOM, "\n".join(self.texte_filtre(f).split(" (")[0]
                                           for f in vides[:MAX_LISTE]))
            self._teinter(it, TEXT_MUTED)
            g.addChild(self._ranger(it, "filtres"))
        return g

    @staticmethod
    def _ranger(it, categorie=None, conteneur=False) -> QTreeWidgetItem:
        """Range une ligne dans une catégorie des pastilles « Afficher ». Un
        CONTENEUR (un rôle, une famille, un groupe de filtres) se cache quand
        les pastilles ont éteint tout ce qu'il contient."""
        if categorie:
            it.setData(C_NOM, CATEGORIE, categorie)
        if conteneur:
            it.setData(C_NOM, CONTENEUR, True)
        return it

    def _construire_pages(self):
        r = self.res
        a = self.arbre_pages
        a.setUpdatesEnabled(False)
        a.clear()
        self._item_visuel = {}
        g = self._noeud_filtres("Filtres du rapport", r["filtres_rapport"])
        if g is not None:
            self._bandeau(g)
            a.addTopLevelItem(g)
        for p in r["pages"]:
            vis = p["visuels"]
            n_seg = sum(1 for v in vis if v["segment"])
            compte = f"{len(vis) - n_seg} visuel" + ("s" if len(vis) - n_seg > 1 else "")
            if n_seg:
                compte += f" · {n_seg} segment" + ("s" if n_seg > 1 else "")
            top = self._bandeau(self._item([p["nom"], "", compte, ""], ("page", p["id"])))
            g = self._noeud_filtres("Filtres de la page", p["filtres"])
            if g is not None:
                top.addChild(g)
            # les visuels d'abord, les segments ensuite : ce qu'on regarde, puis
            # ce qui choisit
            for v in sorted(vis, key=lambda v: v["segment"]):
                top.addChild(self._noeud_visuel(v, p))
            a.addTopLevelItem(top)
            top.setExpanded(True)
        a.setUpdatesEnabled(True)

    def _noeud_visuel(self, v, p) -> QTreeWidgetItem:
        r = self.res
        n_mes = sum(1 if c["genre"] == "mesure" else len(c.get("mesures") or [])
                    for c in v["champs"] if c["genre"] != "colonne")
        n_flt = (sum(1 for f in v["filtres"] if f["actif"]) + len(v["segments"])
                 + sum(1 for f in p["filtres"] + r["filtres_rapport"] if f["actif"]))
        casses = sum(1 for c in v["champs"] if c["genre"] == "colonne" and not c["connue"])
        lib = ("⚠ " if casses else "") + v["libelle"] + ("  (masqué)" if v["masque"] else "")
        if v["segment"]:
            detail, mene, tip = v["selection"] or "aucune sélection", "", ""
        else:
            detail = " · ".join(x for x in (
                f"{n_mes} mesure" + ("s" if n_mes > 1 else "") if n_mes else "",
                f"{n_flt} filtre" + ("s" if n_flt > 1 else "") if n_flt else "") if x)
            mene, tip = self._mene_a_visuel(v)
        it = self._item([lib, mene, detail, ""], ("visuel", (v["page_id"], v["id"])))
        if tip:
            it.setToolTip(C_VAR, tip)
        # « Courbes · Body Fat % YTD » : le type en gris, ce qu'il montre en gras
        if not casses and v["libelle"].startswith(v["libelle_type"] + " "):
            sep = " · " if v["libelle"].startswith(v["libelle_type"] + " · ") else " "
            self._deux_tons(it, v["libelle_type"] + sep,
                            "  (masqué)" if v["masque"] else "")
        if not v["segment"]:
            gras = QFont(self.arbre_pages.font())
            gras.setBold(True)
            it.setFont(C_NOM, gras)
        self._teinter(it, TEXT_MUTED, (C_VUS,))
        categorie = "masques" if v["masque"] else "segments" if v["segment"] else None
        self._ranger(it, categorie)
        if v["segment"] or v["masque"]:
            self._teinter(it, TEXT_MUTED)
        if casses:
            self._teinter(it, YELLOW, (C_NOM,))
            it.setToolTip(C_NOM, f"{casses} champ(s) introuvable(s) dans le modèle")
        for role, champs in self._par_role(v):
            it.addChild(self._noeud_role(role, champs))
        if not v["segment"]:
            g = self._noeud_filtres("Filtré par", v["filtres"], v["segments"])
            if g is not None:
                it.addChild(g)
        self._item_visuel[(v["page_id"], v["id"])] = it
        return it

    @staticmethod
    def _par_role(v) -> list:
        """[(libellé du rôle, [champs])], dans l'ordre du volet Visualisations."""
        groupes: dict = {}
        for c in v["champs"]:
            groupes.setdefault(rg.libelle_role(c.get("role", ""), v["segment"]) or "Champs",
                               []).append(c)
        ordre = {r: i for i, r in enumerate(rg.ORDRE_ROLES)}
        return sorted(groupes.items(), key=lambda kv: ordre.get(kv[0], len(ordre)))

    def _mene_a_visuel(self, v) -> tuple:
        """Les mesures de base de tout ce qu'un visuel affiche : d'où viennent
        ses chiffres, lisible sans le déplier."""
        bases = []
        for c in v["champs"]:
            if c["genre"] == "mesure":
                for b in self.res["bases"][c["nom"]] or [c["nom"]]:
                    if b not in bases:
                        bases.append(b)
        if not bases:
            return "", ""
        court = ", ".join(bases[:3]) + (f" et {len(bases) - 3} autres" if len(bases) > 3 else "")
        return court, "Mesures de base de ce visuel :\n" + "\n".join(f"[{b}]" for b in bases)

    def _noeud_role(self, role, champs) -> QTreeWidgetItem:
        """Les champs d'un rôle. Les mesures d'une même famille (un KPI et ses
        variations) tiennent sur une ligne à déplier. Un rôle qui n'a qu'une
        ligne la porte directement : « Axe : 'dim_Date'[1 month] »."""
        entrees = []
        mesures = [c for c in champs if c["genre"] == "mesure"]
        familles: dict = {}
        for c in mesures:
            familles.setdefault(self.res["famille_de"].get(c["nom"], c["nom"]), []).append(c)
        vues = set()
        for c in champs:
            if c["genre"] != "mesure":
                entrees.append(self._feuille_champ(c))
                continue
            kpi = self.res["famille_de"].get(c["nom"], c["nom"])
            if kpi in vues:
                continue
            vues.add(kpi)
            membres = familles[kpi]
            entrees.append(self._feuille_champ(c) if len(membres) == 1
                           else self._noeud_famille(kpi, [m["nom"] for m in membres]))
        if len(entrees) == 1:
            seul = entrees[0]
            seul.setText(C_NOM, f"{role} : {seul.text(C_NOM)}")
            seul.setData(C_NOM, PREFIXE, f"{role} : ")
            return seul
        n = len(champs)
        g = self._item([f"{role} ({n})", "", "", ""], ("role", None))
        self._teinter(g, TEXT_MUTED, (C_NOM,))
        cats = {e.data(C_NOM, CATEGORIE) for e in entrees}
        self._ranger(g, cats.pop() if len(cats) == 1 else None, conteneur=True)
        for e in entrees:
            g.addChild(e)
        g.setExpanded(True)
        return g

    def _noeud_famille(self, kpi, noms) -> QTreeWidgetItem:
        """Plusieurs mesures d'une famille dans un visuel : une ligne repliée,
        « Body Fat % · 16 mesures », qui mène à leurs mesures de base."""
        r = self.res
        bases = list(dict.fromkeys(b for n in noms for b in (r["bases"][n] or [n])))
        tables = {r["mesures"][n]["table"] for n in noms}
        n_var = sum(1 for n in noms if n != kpi)
        detail = (("KPI et " if kpi in noms else "")
                  + f"{n_var} variation" + ("s" if n_var > 1 else ""))
        it = self._item([f"{kpi} · {len(noms)} mesures", ", ".join(bases), detail,
                         tables.pop() if len(tables) == 1 else ""], ("mesure", kpi)
                        if kpi in r["mesures"] else ("famille", kpi))
        self._deux_tons(it, suffixe=f" · {len(noms)} mesures")
        self._teinter(it, ACCENT, (C_NOM,))
        self._teinter(it, TEXT_MUTED, (C_VUS, C_TABLE))
        self._ranger(it, "mesures")
        for n in sorted(noms, key=lambda n: n != kpi):      # le KPI d'abord
            sub = self._feuille_champ({"genre": "mesure", "nom": n})
            f = self._famille(kpi)
            x = next((x for x in (f["membres"] if f else []) if x["nom"] == n), None)
            sub.setText(C_VUS, "KPI" if n == kpi else (x["patron"] if x else ""))
            # ce que la ligne de la famille dit déjà ne se répète pas 16 fois
            for c in (C_VAR, C_TABLE):
                if sub.text(c) == it.text(c):
                    sub.setText(c, "")
            it.addChild(sub)
        return it

    def _role(self, nom) -> str:
        """« KPI », « variation de X » ou rien : la place d'une mesure dans
        les familles."""
        kpi = self.res["famille_de"].get(nom)
        if not kpi:
            return ""
        if kpi == nom:
            return "KPI"
        f = self._famille(kpi)
        return f"variation de {kpi}" if f and f["reel"] else f"famille {kpi} … (par le nom)"

    def _feuille_champ(self, c) -> QTreeWidgetItem:
        r = self.res
        if c["genre"] == "mesure":
            mene, tip = self._mene_a(c["nom"])
            it = self._item([f'[{c["nom"]}]', mene, self._role(c["nom"]),
                             r["mesures"][c["nom"]]["table"]], ("mesure", c["nom"]))
            if tip:
                it.setToolTip(C_VAR, tip)
            self._teinter(it, ACCENT, (C_NOM,))
            self._teinter(it, TEXT_MUTED, (C_VUS, C_TABLE))
            return self._ranger(it, "mesures")
        if c["genre"] == "parametre":
            n = len(c["mesures"])
            it = self._item([f'{c["table"]}  (paramètre de champ)', "",
                             f"{n} mesure" + ("s" if n > 1 else "") + " au choix", c["table"]],
                            ("parametre", c["table"]))
            self._teinter(it, ORANGE, (C_NOM,))
            for m in c["mesures"]:
                mene, tip = self._mene_a(m)
                sub = self._item([f"[{m}]", mene, self._role(m), r["mesures"][m]["table"]],
                                 ("mesure", m))
                if tip:
                    sub.setToolTip(C_VAR, tip)
                it.addChild(sub)
            return self._ranger(it, "mesures")
        nom = f"[{c['nom']}]" if c.get("mesure") else f"'{c['table']}'[{c['nom']}]"
        if c.get("agregat"):
            nom = f"{c['agregat']} de {nom}"
        if not c["connue"]:
            it = self._item(["⚠ " + nom, "", "introuvable", c["table"]], ("colonne", c["ref"]))
            it.setToolTip(C_NOM, nom + "\n\nCe champ n'existe pas dans le modèle (renommé ou "
                                 "supprimé) : le visuel s'affiche en erreur.")
            self._teinter(it, YELLOW, (C_NOM, C_VUS))
            return self._ranger(it, "colonnes")
        it = self._item([nom, "", "", c["table"]], ("colonne", c["ref"]))
        self._teinter(it, TEXT_DIM, (C_NOM,))
        self._teinter(it, TEXT_MUTED, (C_TABLE,))
        return self._ranger(it, "colonnes")

    # ---- filtre --------------------------------------------------------------

    def _filtrer(self, texte):
        t = (texte or "").strip().lower()
        for a, puces in ((self.arbre_kpi, None), (self.arbre_pages, self.puces_pages),
                         (self.arbre_cols, self.puces_cols)):
            allumees = puces.valeurs() if puces is not None else None
            for i in range(a.topLevelItemCount()):
                self._filtrer_item(a.topLevelItem(i), t, allumees)
        self.vue_sources.filtrer_texte((texte or "").strip())
        self.vue_lignage.filtrer_texte(texte or "")

    def _filtrer_item(self, it, t, allumees=None, parent_ok=False) -> bool:
        """Visible si sa catégorie est allumée, et si lui, un parent ou un
        descendant contient le texte : un parent qui correspond garde ses
        enfants. Un conteneur dont tout le contenu est éteint se cache."""
        cat = it.data(C_NOM, CATEGORIE)
        if allumees is not None and cat and cat not in allumees:
            it.setHidden(True)
            return False
        moi = parent_ok or not t or t in it.text(C_NOM).lower()
        enfant = False
        for i in range(it.childCount()):
            enfant = self._filtrer_item(it.child(i), t, allumees, moi) or enfant
        visible = (moi or enfant) and not (it.data(C_NOM, CONTENEUR) and it.childCount()
                                           and not enfant)
        it.setHidden(not visible)
        if t and enfant and not moi:
            it.setExpanded(True)
        return visible

    def _montrer_puces(self):
        """Les pastilles de la vue ouverte : la vue Par KPI n'en a pas."""
        w = self.vues.currentWidget()
        self.puces_pages.setVisible(w is self.arbre_pages)
        self.puces_cols.setVisible(w is self.arbre_cols)
        self.lbl_kpi.setVisible(w is self.arbre_kpi)
        # la vue Par source est une liste à plat, avec ses propres pastilles
        for b in (self.btn_deplier, self.btn_replier):
            b.setVisible(w not in (self.vue_sources, self.vue_lignage))

    def _deplier(self, tout: bool):
        a = self.vues.currentWidget()
        if tout:
            a.expandAll()
            if a is self.arbre_pages:
                self._replier_details(a.invisibleRootItem())
            return
        a.collapseAll()
        if a is not self.arbre_kpi:     # les pages et les tables restent ouvertes
            for i in range(a.topLevelItemCount()):
                a.topLevelItem(i).setExpanded(True)

    def _replier_details(self, it):
        """Ferme les familles et les paramètres de champ : tout déplié, un
        visuel reste une poignée de lignes, une par rôle."""
        for i in range(it.childCount()):
            e = it.child(i)
            donnee = e.data(C_NOM, ROLE)
            if donnee and donnee[0] in REPLIES and e.childCount():
                e.setExpanded(False)
            else:
                self._replier_details(e)

    # ---- fiche ---------------------------------------------------------------

    def _vider_fiche(self):
        """Sans choix : la vue d'ensemble du rapport, s'il est lu. Appelée par
        le bouton Vue d'ensemble, elle rouvre la fiche si elle est fermée."""
        if self.sender() is getattr(self, "btn_ensemble", None) and not self.fiche.isVisible():
            self._montrer_fiche(True)
        self._liens = []
        if not self.res:
            self._fiche_courante = None
            self.fiche.setHtml(f"<p style='color:{TEXT_MUTED}'>Choisir une mesure, une page "
                               "ou un visuel pour voir sa fiche.</p>")
            return
        self._afficher(self._fiche_rapport)

    def _afficher(self, fabrique, *args):
        """Rend une fiche. Ses listes longues sont repliées ; un clic sur
        « afficher les N autres » la rend à nouveau, au même endroit, avec
        cette liste dépliée. Changer de fiche replie tout."""
        cle = (fabrique.__name__, repr(args))
        meme = cle == getattr(self, "_fiche_cle", None)
        if not meme:
            self._ouverts = set()
        self._fiche_cle = cle
        self._fiche_courante = (fabrique, args)
        position = self.fiche.verticalScrollBar().value() if meme else 0
        self._liens = []
        self._n_liste = 0
        self.fiche.setHtml(fabrique(*args))
        self.fiche.verticalScrollBar().setValue(position)

    def _plier(self, cle):
        """Déplie (ou replie) une liste de la fiche courante."""
        self._ouverts ^= {cle}
        if self._fiche_courante:
            fabrique, args = self._fiche_courante
            self._afficher(fabrique, *args)

    def _fiche_rapport(self) -> str:
        """Ce que contient le rapport, de haut en bas : ses KPI les plus vus, ses
        filtres, puis chaque page et ce que montre chacun de ses visuels."""
        r = self.res
        gris = f"style='color:{TEXT_MUTED}'"
        nv = sum(1 for v in r["visuels"] if not v["segment"])
        ns = len(r["visuels"]) - nv
        out = ["<h3>Vue d'ensemble du rapport</h3>",
               f"<p style='color:{TEXT_DIM}'>{len(r['pages'])} page(s) · {nv} visuel(s) · "
               f"{ns} segment(s) · {len(r['kpis'])} KPI. Choisir une ligne à gauche pour "
               "sa fiche.</p>"]
        casses = [v for v in r["visuels"]
                  if any(c["genre"] == "colonne" and not c["connue"] for c in v["champs"])]
        if casses:
            out.append(f"<p style='color:{YELLOW}'>⚠ {len(casses)} visuel(s) avec un champ "
                       "introuvable : " + ", ".join(self._ou(v) for v in casses) + "</p>")
        vus = [f for f in r["kpis"] if f["visuels"]]
        if vus:
            out.append("<h4>KPI affichés</h4>" + self._liste(
                [(self._a(f["kpi"], ("mesure", f["kpi"])) if f["kpi"] in r["mesures"]
                  else _e(f["kpi"] + " …"))
                 + f" <span {gris}>· {_vus(f['visuels'], f['pages'])}"
                 + (f" · {len(f['membres'])} variation(s)" if f["membres"] else "")
                 + "</span>" for f in vus]))
        actifs = [f for f in r["filtres_rapport"] if f["actif"]]
        if actifs:
            out.append("<h4>Filtres du rapport</h4>"
                       + self._liste([_e(self.texte_filtre(f)) for f in actifs]))
        for p in r["pages"]:
            out.append(f"<h3 style='margin-top:14px'>"
                       f"{self._a(p['nom'], ('page', p['id']))}</h3>")
            out.append(self._bloc_page(p))
        return "".join(out)

    def _bloc_page(self, p) -> str:
        """Une page en un coup d'œil : ses segments et leur sélection, ses
        filtres, puis un tableau visuel par visuel : ce qu'il affiche, par
        quoi, et ce qui le filtre en plus des segments."""
        gris = f"style='color:{TEXT_MUTED}'"
        vis = [v for v in p["visuels"] if not v["segment"]]
        segs = [v for v in p["visuels"] if v["segment"]]
        out = []
        if segs:
            # ceux qui ont une sélection d'abord, en clair ; les autres ensemble,
            # en gris, chaque champ une fois
            def champ(s):
                prefixe = s["libelle_type"] + " · "
                return s["libelle"][len(prefixe):] if s["libelle"].startswith(prefixe) \
                    else s["libelle"]
            choisis = [self._a(champ(s), ("visuel", (s["page_id"], s["id"])))
                       + f" <b>{_e(s['selection'])}</b>" for s in segs if s["selection"]]
            libres: dict = {}
            for s in segs:
                if not s["selection"]:
                    libres[champ(s)] = libres.get(champ(s), 0) + 1
            texte = " · ".join(choisis)
            if libres:
                texte += ((" · " if choisis else "") + f"<span {gris}>sans sélection : "
                          + _e(", ".join(n + (f" (×{k})" if k > 1 else "")
                                         for n, k in libres.items())) + "</span>")
            out.append(f"<p><b>Segments</b> : {texte}</p>")
        actifs = [f for f in p["filtres"] if f["actif"]]
        if actifs:
            out.append("<p><b>Filtres de la page</b> : "
                       + " · ".join(_e(self.texte_filtre(f)) for f in actifs) + "</p>")
        if not vis:
            out.append(f"<p {gris}>Aucun visuel.</p>")
            return "".join(out)
        # les segments qui filtrent au moins un visuel : ceux dont un visuel se
        # passe valent d'être dits
        filtrants = {(s["page_id"], s["id"]): s for v in vis for s in v["segments"]}
        lignes = [f"<tr><th align='left' bgcolor='{BORDER}'>Visuel</th>"
                  f"<th align='left' bgcolor='{BORDER}'>Affiche</th>"
                  f"<th align='left' bgcolor='{BORDER}'>Par</th></tr>"]
        for i, v in enumerate(vis):
            nom = self._a(v["libelle"], ("visuel", (v["page_id"], v["id"])))
            if v["masque"]:
                nom += f" <span {gris}>(masqué)</span>"
            filtres = [_e(f"{f['nom']} {f['texte']}") for f in v["filtres"] if f["actif"]]
            siens = {(s["page_id"], s["id"]) for s in v["segments"]}
            sauf = [s["libelle"] for k, s in filtrants.items() if k not in siens]
            if filtres:
                nom += f"<br><span {gris}>filtré par</span> " + ", ".join(filtres)
            if sauf:
                nom += f"<br><span {gris}>sans le segment " + _e(", ".join(sauf)) + "</span>"
            fond = f" bgcolor='{SURFACE_ALT}'" if i % 2 else ""
            lignes.append(f"<tr{fond}><td valign='top'>{nom}</td>"
                          f"<td valign='top'>{self._affiche(v)}</td>"
                          f"<td valign='top'>{self._par(v)}</td></tr>")
        out.append("<table width='100%' cellspacing='0' cellpadding='4'>"
                   + "".join(lignes) + "</table>")
        return "".join(out)

    def _affiche(self, v) -> str:
        """Les mesures d'un visuel, une famille par entrée : « Body Fat % (16) »."""
        r = self.res
        gris = f"style='color:{TEXT_MUTED}'"
        out, faites = [], {}
        for c in v["champs"]:
            if c["genre"] == "mesure":
                kpi = r["famille_de"].get(c["nom"], c["nom"])
                faites.setdefault(kpi, []).append(c["nom"])
            elif c["genre"] == "parametre":
                out.append(self._a(c["table"], ("parametre", c["table"]))
                           + f" <span {gris}>({len(c['mesures'])} au choix)</span>")
        for kpi, noms in faites.items():
            if len(noms) == 1:
                out.append(self._a(noms[0], ("mesure", noms[0])))
            else:
                cible = ("mesure", kpi) if kpi in r["mesures"] else ("mesure", noms[0])
                out.append(self._a(kpi, cible) + f" <span {gris}>({len(noms)})</span>")
        return "<br>".join(out) or f"<span {gris}>·</span>"

    def _par(self, v) -> str:
        """Les colonnes d'un visuel (axes, lignes, légendes), par leur nom."""
        cols = list(dict.fromkeys(
            ("⚠ " if not c["connue"] else "") + c["nom"] for c in v["champs"]
            if c["genre"] == "colonne" and not c.get("mesure")))
        return _e(", ".join(cols)) if cols else f"<span style='color:{TEXT_MUTED}'>·</span>"

    def _a(self, texte, cible) -> str:
        self._liens.append(cible)
        return f"<a href='#{len(self._liens) - 1}' style='color:{ACCENT}'>{_e(texte)}</a>"

    def _liste(self, items) -> str:
        """Une liste de la fiche. Longue, elle ne montre que ses premières
        lignes et un lien pour le reste ; dépliée, un lien pour la replier."""
        if not items:
            return f"<p style='color:{TEXT_MUTED}'>aucun</p>"
        self._n_liste = getattr(self, "_n_liste", 0) + 1
        cle = ("liste", self._n_liste)
        ouverte = cle in getattr(self, "_ouverts", set())
        lien = ""
        if len(items) > PLIER_APRES and not ouverte:
            vus = items[:PREMIERES]
            lien = self._a(f"▸ afficher les {len(items) - PREMIERES} autres", ("plier", cle))
        else:
            vus = items
            if len(items) > PLIER_APRES:
                lien = self._a("▴ replier", ("plier", cle))
        lignes = "".join(f"<li>{x}</li>" for x in vus)
        if lien:
            lignes += f"<li style='list-style-type:none'>{lien}</li>"
        return f"<ul style='margin-top:2px'>{lignes}</ul>"

    def _ou(self, v, via=None) -> str:
        return (f"{_e(v['page'])} › " + self._a(v["libelle"], ("visuel", (v["page_id"], v["id"])))
                + (f" <span style='color:{TEXT_MUTED}'>via {_e(via)}</span>" if via else ""))

    def _montrer(self, it):
        if it is None:
            return
        donnee = it.data(C_NOM, ROLE)
        if not donnee:
            return
        genre, cle = donnee
        self._liens = []
        fiches = {"mesure": self._fiche_mesure, "visuel": self._fiche_visuel,
                  "page": self._fiche_page, "famille": self._fiche_famille,
                  "parametre": self._fiche_parametre, "colonne_rapport": self._fiche_colonne}
        if genre in fiches:
            self._afficher(fiches[genre], cle)

    def _famille(self, kpi):
        return next((f for f in self.res["kpis"] if f["kpi"] == kpi), None)

    def _fiche_mesure(self, nom) -> str:
        r = self.res
        m = r["mesures"][nom]
        out = [f"<h3>{_e(nom)}</h3>"]
        kpi = r["famille_de"].get(nom)
        f = self._famille(kpi) if kpi else None
        if f and kpi == nom:
            n = len(f["membres"])
            out.append(f"<p><b>KPI</b>" + (f", {n} variation(s)" if n else "") + "</p>")
        elif f:
            x = next(x for x in f["membres"] if x["nom"] == nom)
            if f["reel"]:
                base = x["base"] or kpi
                par = ("par le DAX" if x["par"] == rg.DAX else
                       f"<span style='color:{YELLOW}'>par le nom seulement</span>")
                out.append(f"<p>Variation de {self._a(base, ('mesure', base))} : "
                           f"<b>{_e(x['patron'])}</b> ({par})</p>")
            else:
                out.append(f"<p>Dans la famille <b>{_e(kpi)} …</b>, "
                           f"<span style='color:{YELLOW}'>rapprochée par le nom "
                           "seulement</span> : aucune mesure de base commune.</p>")
        details = [f"table <b>{_e(m['table'])}</b>"]
        if m["dossier"]:
            details.append(f"dossier {_e(m['dossier'])}")
        if m["format"]:
            details.append(f"format {_e(m['format'])}")
        out.append(f"<p style='color:{TEXT_DIM}'>" + " · ".join(details) + "</p>")

        out.append("<h4>Affichée dans</h4>" + self._liste(
            [self._ou(v, via) for v, via in r["affichee"][nom]]))
        if r["choisie"][nom]:
            out.append("<h4>Proposée par un segment</h4>" + self._liste(
                [self._ou(v, via) for v, via in r["choisie"][nom]]))
        if r["proposee_par"][nom]:
            out.append("<h4>Dans les paramètres de champ</h4>" + self._liste(
                [self._a(t, ("parametre", t)) for t in r["proposee_par"][nom]]))
        out.append("<h4>Mène à</h4>" + self._liste([self._champ_mesure(nom)]))
        out.append("<h4>Utilise</h4>" + self._liste(
            [self._a(u, ("mesure", u)) for u in r["uses"][nom]]))
        out.append("<h4>Utilisée par</h4>" + self._liste(
            [self._a(u, ("mesure", u)) for u in r["used_by"][nom]]))
        if self.graphe:
            out.append("<p>" + self._a("Voir dans le lignage : d'où elle vient, ce qui en "
                                       "dépend", ("lignage", nom)) + "</p>")
        dax = (m["dax"] or "(vide)").splitlines()
        if len(dax) > DAX_LIGNES and ("dax", nom) not in self._ouverts:
            out.append("<h4>DAX</h4><pre style='font-family:Consolas,monospace'>"
                       + _e("\n".join(dax[:DAX_LIGNES - 2])) + "</pre>"
                       + self._a(f"▸ afficher les {len(dax) - DAX_LIGNES + 2} autres lignes",
                                 ("plier", ("dax", nom))))
        else:
            out.append("<h4>DAX</h4><pre style='font-family:Consolas,monospace'>"
                       + _e("\n".join(dax)) + "</pre>"
                       + (self._a("▴ replier", ("plier", ("dax", nom)))
                          if len(dax) > DAX_LIGNES else ""))
        return "".join(out)

    def _fiche_famille(self, kpi) -> str:
        f = self._famille(kpi)
        out = [f"<h3>{_e(kpi)} …</h3>",
               f"<p style='color:{YELLOW}'>Famille rapprochée par le nom : ces mesures "
               "commencent par les mêmes mots, mais aucune ne référence l'autre. À "
               "vérifier.</p>", f"<p>{_vus(f['visuels'], f['pages'])}</p>"]
        out.append(self._liste([self._a(x["nom"], ("mesure", x["nom"])) for x in f["membres"]]))
        return "".join(out)

    def _visuel(self, cle):
        return next(v for v in self.res["visuels"] if (v["page_id"], v["id"]) == cle)

    def _fiche_visuel(self, cle) -> str:
        v = self._visuel(cle)
        out = [f"<h3>{_e(v['libelle'])}</h3>",
               f"<p style='color:{TEXT_DIM}'>page <b>{_e(v['page'])}</b> · type "
               f"{_e(v['libelle_type'])}" + (" · masqué" if v["masque"] else "") + "</p>"]
        if v["segment"]:
            out.append("<p>Un segment : il <b>choisit</b> ce que les autres visuels "
                       "affichent.</p>")
        # les champs comme dans le volet Visualisations : rôle par rôle, les
        # variations d'un même KPI sur une ligne
        gris = f"style='color:{TEXT_MUTED}'"
        for role, champs in self._par_role(v):
            lignes, faites = [], set()
            for c in champs:
                if c["genre"] == "mesure":
                    kpi = self.res["famille_de"].get(c["nom"], c["nom"])
                    if kpi in faites:
                        continue
                    faites.add(kpi)
                    noms = [x["nom"] for x in champs if x["genre"] == "mesure"
                            and self.res["famille_de"].get(x["nom"], x["nom"]) == kpi]
                    lignes.append(self._ligne_famille(kpi, noms))
                elif c["genre"] == "parametre":
                    lignes.append(self._a(c["table"], ("parametre", c["table"]))
                                  + f" <span {gris}>· paramètre de champ, "
                                    f"{len(c['mesures'])} mesure(s) au choix</span>")
                else:
                    nom = (f"[{c['nom']}]" if c.get("mesure")
                           else f"'{c['table']}'[{c['nom']}]")
                    txt = _e((c["agregat"] + " de " if c.get("agregat") else "") + nom)
                    if not c["connue"]:
                        txt = (f"<span style='color:{YELLOW}'>⚠ {txt} : introuvable dans le "
                               "modèle</span>")
                    lignes.append(txt)
            out.append(f"<h4>{_e(role)}</h4>" + self._liste(lignes))
        if not v["segment"]:
            origines = self._origines(v)
            if origines:
                out.append("<h4>D'où viennent les chiffres</h4>" + self._liste(origines))
        if not v["segment"]:
            p = next(p for p in self.res["pages"] if p["id"] == v["page_id"])
            filtres = ([_e(self.texte_filtre(f)) for f in v["filtres"] if f["actif"]]
                       + [_e(self.texte_filtre(f)) + f" <span style='color:{TEXT_MUTED}'>"
                          "· page</span>" for f in p["filtres"] if f["actif"]]
                       + [_e(self.texte_filtre(f)) + f" <span style='color:{TEXT_MUTED}'>"
                          "· rapport</span>" for f in self.res["filtres_rapport"] if f["actif"]]
                       + [self._a(s["libelle"], ("visuel", (s["page_id"], s["id"])))
                          + f" {_e(s['selection'])}" for s in v["segments"]])
            out.append("<h4>Filtré par</h4>" + self._liste(filtres))
            vides = [f for f in v["filtres"] if not f["actif"]]
            if vides:
                # Power BI y pose chaque champ du visuel : ils ne filtrent rien, la
                # liste complète noierait la fiche
                noms = [_e(self.texte_filtre(f).split(" (")[0]) for f in vides]
                reste = len(noms) - 8
                out.append(f"<p style='color:{TEXT_MUTED}'>{len(noms)} champ(s) dans le volet "
                           "des filtres, sans valeur choisie : ils ne filtrent rien. "
                           + ", ".join(noms[:8]) + (f" et {reste} autres" if reste > 0 else "")
                           + "</p>")
        else:
            out.append("<h4>Sélection</h4>" + self._liste(
                [_e(v["selection"])] if v["selection"] else []))
        return "".join(out)

    def _ligne_famille(self, kpi, noms) -> str:
        """Une mesure seule : son lien et sa place. Plusieurs mesures d'une
        famille : « Body Fat % : KPI, … YTD, … 7d avg », chaque variation par
        ce qu'elle ajoute au nom du KPI."""
        gris = f"style='color:{TEXT_MUTED}'"
        if len(noms) == 1:
            role = self._role(noms[0])
            return self._a(f"[{noms[0]}]", ("mesure", noms[0])) + (
                f" <span {gris}>· {_e(role)}</span>" if role else "")
        f = self._famille(kpi)
        patrons = {x["nom"]: x["patron"] for x in (f["membres"] if f else [])}
        noms = sorted(noms, key=lambda n: n != kpi)       # le KPI d'abord
        liens = [self._a("KPI" if n == kpi else patrons.get(n) or n, ("mesure", n))
                 for n in noms]
        tete = (self._a(kpi, ("mesure", kpi)) if kpi in self.res["mesures"] else _e(kpi + " …"))
        return f"<b>{tete}</b> <span {gris}>· {len(noms)} mesures :</span> " + ", ".join(liens)

    def _origines(self, v) -> list:
        """Les mesures de base de ce que le visuel affiche, une fois chacune,
        avec les colonnes qu'elles lisent."""
        r = self.res
        bases = []
        for c in v["champs"]:
            if c["genre"] == "mesure":
                for b in r["bases"][c["nom"]] or [c["nom"]]:
                    if b not in bases:
                        bases.append(b)
        out = []
        for b in bases:
            cols = list(dict.fromkeys(r["colonnes"][b]))
            out.append(self._a(f"[{b}]", ("mesure", b)) + (
                f" <span style='color:{TEXT_MUTED}'>lit "
                + ", ".join(_e(f"'{t}'[{c}]") for t, c in cols) + "</span>" if cols else ""))
        return out

    def _champ_mesure(self, nom) -> str:
        """[mesure] · son rôle → ses mesures de base → les colonnes lues."""
        r = self.res
        txt = self._a(f"[{nom}]", ("mesure", nom))
        role = self._role(nom)
        if role:
            txt += f" <span style='color:{TEXT_MUTED}'>· {_e(role)}</span>"
        bases = r["bases"][nom]
        if bases:
            txt += " → " + ", ".join(self._a(b, ("mesure", b)) for b in bases)
        cols = [c for b in (bases or [nom]) for c in r["colonnes"][b]]
        if cols:
            txt += (f"<br><span style='color:{TEXT_MUTED}'>lit "
                    + ", ".join(_e(f"'{t}'[{c}]") for t, c in dict.fromkeys(cols))
                    + "</span>")
        return txt

    def _fiche_page(self, pid) -> str:
        p = next(p for p in self.res["pages"] if p["id"] == pid)
        kpis = []
        for v in p["visuels"]:
            if v["segment"]:
                continue
            for c in v["champs"]:
                noms = [c["nom"]] if c["genre"] == "mesure" else c.get("mesures") or []
                for n in noms:
                    k = self.res["famille_de"].get(n, n)
                    if k not in kpis:
                        kpis.append(k)
        n_seg = sum(1 for v in p["visuels"] if v["segment"])
        out = [f"<h3>{_e(p['nom'])}</h3>",
               f"<p style='color:{TEXT_DIM}'>{len(p['visuels']) - n_seg} visuel(s) · "
               f"{n_seg} segment(s)</p>",
               "<h4>KPI affichés</h4>",
               self._liste([self._a(k, ("mesure", k)) if k in self.res["mesures"] else _e(k)
                            for k in kpis]),
               "<h4>Visuels</h4>", self._bloc_page(p)]
        return "".join(out)

    def _fiche_parametre(self, table) -> str:
        fp = self.res["parametres"][table]
        vis = [v for v in self.res["visuels"]
               if any(c["genre"] == "parametre" and c["table"] == table for c in v["champs"])]
        out = [f"<h3>{_e(table)}</h3>",
               "<p>Paramètre de champ : un segment choisit laquelle de ces mesures les "
               "visuels affichent.</p>",
               "<h4>Utilisé par</h4>", self._liste([self._ou(v) for v in vis]),
               f"<h4>Mesures proposées ({len(fp['mesures'])})</h4>",
               self._liste([self._a(m, ("mesure", m)) for m in fp["mesures"]])]
        return "".join(out)

    # genre d'usage -> libellé au pluriel, dans l'ordre où on les cherche
    # quand un chiffre est faux
    GENRES_USAGE = (("segment", "segments"), ("filtre de rapport", "filtres de rapport"),
                    ("filtre de page", "filtres de page"), ("filtre de visuel", "filtres de visuel"),
                    ("visuel", "visuels"), ("mesure", "mesures"))

    def _resume_usages(self, usages) -> str:
        parts = []
        for genre, pluriel in self.GENRES_USAGE:
            n = sum(1 for u in usages if u["genre"] == genre)
            if n:
                parts.append(f"{n} {pluriel if n > 1 else genre}")
        return " · ".join(parts)

    def _construire_colonnes(self):
        """Par colonne : chaque table, ses colonnes utilisées, et pour chacune
        où elle sert (segment, filtre, visuel, mesure)."""
        r = self.res
        a = self.arbre_cols
        a.setUpdatesEnabled(False)
        a.clear()
        ordre = {g: i for i, (g, _m) in enumerate(self.GENRES_USAGE)}
        self.dep_colonnes = rg.dependants_colonnes(r)
        par_table: dict = {}
        for i, c in enumerate(r["colonnes_utilisees"]):
            par_table.setdefault(c["table"], []).append((i, c))
        for table in sorted(par_table, key=str.lower):
            cols = par_table[table]
            top = self._bandeau(self._item([table, "", "", "", f"{len(cols)} colonne(s)"],
                                           ("table", table)), 5)
            self._ranger(top, conteneur=True)
            for i, c in cols:
                top.addChild(self._noeud_colonne(i, c, ordre))
            a.addTopLevelItem(top)
            top.setExpanded(True)
        a.setUpdatesEnabled(True)

    def _noeud_colonne(self, i, c, ordre) -> QTreeWidgetItem:
        """Une colonne : combien de mesures, de filtres et de visuels en
        dépendent, puis chaque usage. Ce qui en dépend PAR UNE MESURE (les
        mesures qui reprennent celles qui la lisent, les visuels qui les
        affichent) tient dans deux lignes repliées."""
        d = self.dep_colonnes[i]
        nom = ("⚠ " if not c["connue"] else "") + c["nom"]
        comptes = [len(d["mesures"]), len(d["filtres"]) + len(d["segments"]), len(d["visuels"])]
        it = self._item([nom] + [str(n) if n else "·" for n in comptes]
                        + [self._resume_usages(c["usages"])], ("colonne_rapport", i))
        self._ranger(it, conteneur=True)
        for col, n in zip((1, 2, 3), comptes):
            it.setTextAlignment(col, int(Qt.AlignRight | Qt.AlignVCenter))
            if not n:
                it.setForeground(col, QBrush(QColor(TEXT_MUTED)))
        self._teinter(it, TEXT_MUTED, (4,))
        n_dir = len(d["mesures_directes"])
        if d["mesures"]:
            it.setToolTip(1, f"{len(d['mesures'])} mesure(s) en dépendent : {n_dir} la lisent, "
                             f"{len(d['mesures']) - n_dir} reprennent ces mesures.")
        if d["filtres"] or d["segments"]:
            it.setToolTip(2, f"{len(d['filtres'])} filtre(s) avec une valeur, "
                             f"{len(d['segments'])} segment(s)")
        if d["visuels"]:
            it.setToolTip(3, f"{len(d['visuels'])} visuel(s) sur {d['pages']} page(s) : "
                             f"{len(d['visuels_directs'])} l'affichent, les autres affichent "
                             "une mesure qui la lit.")
        if not c["connue"]:
            self._teinter(it, YELLOW, (C_NOM,))
            it.setToolTip(C_NOM, "Introuvable dans le modèle : renommée ou supprimée.")
        directes = d["mesures_directes"]
        regrouper = len(directes) > PLIER_APRES
        for u in sorted(c["usages"], key=lambda u: (ordre.get(u["genre"], 9), u["ou"].lower())):
            if u["genre"] == "mesure" and regrouper:
                continue                # en familles, plus bas
            detail = u["genre"] + (f" · {u['texte']}" if u["texte"] else "")
            sub = self._item([u["ou"], "", "", "", detail], u["cible"])
            self._ranger(sub, CATEGORIE_USAGE.get(u["genre"]))
            self._teinter(sub, TEXT_MUTED, (4,))
            if u["genre"] == "mesure":
                self._teinter(sub, ACCENT, (C_NOM,))
            elif u["texte"] == "sans valeur choisie":
                self._teinter(sub, TEXT_MUTED)
            it.addChild(sub)
        if regrouper:
            it.addChild(self._noeud_familles(f"Lue par {len(directes)} mesures", directes,
                                             "leur DAX lit cette colonne"))
        autres = [m for m in d["mesures"] if m not in directes]
        if autres:
            it.addChild(self._noeud_familles(f"Reprise par {len(autres)} autre(s) mesure(s)",
                                             autres, "reprennent celles qui la lisent"))
        via = [v for v in d["visuels"] if v not in d["visuels_directs"]]
        if via:
            g = self._item([f"{len(via)} visuel(s) par ces mesures", "", "", "",
                            "affichent une mesure qui en dépend"], ("groupe", None))
            self._teinter(g, TEXT_MUTED)
            self._ranger(g, "visuels")
            for v in via:
                sub = self._item([f"{v['page']} › {v['libelle']}", "", "", "", ""],
                                 ("visuel", (v["page_id"], v["id"])))
                g.addChild(sub)
            it.addChild(g)
        return it

    def _noeud_familles(self, titre, noms, detail) -> QTreeWidgetItem:
        """Une ligne repliée « Lue par 102 mesures », une famille par enfant."""
        g = self._item([titre, "", "", "", detail], ("groupe", None))
        self._teinter(g, TEXT_MUTED)
        self._ranger(g, "mesures")
        for kpi, ns in self._par_famille(noms):
            cible = kpi if kpi in self.res["mesures"] else ns[0]
            sub = self._item([kpi, "", "", "", f"{len(ns)} mesures" if len(ns) > 1 else ""],
                             ("mesure", cible))
            self._teinter(sub, ACCENT, (C_NOM,))
            self._teinter(sub, TEXT_MUTED, (4,))
            sub.setToolTip(C_NOM, "\n".join(ns[:MAX_LISTE]))
            g.addChild(sub)
        return g

    def _par_famille(self, noms) -> list:
        """[(kpi, [mesures])] : des mesures rangées par famille, dans l'ordre."""
        familles: dict = {}
        for m in noms:
            familles.setdefault(self.res["famille_de"].get(m, m), []).append(m)
        return list(familles.items())

    def _fiche_colonne(self, i) -> str:
        c = self.res["colonnes_utilisees"][i]
        ordre = {g: k for k, (g, _m) in enumerate(self.GENRES_USAGE)}
        out = [f"<h3>{_e(chr(39) + c['table'] + chr(39) + '[' + c['nom'] + ']')}</h3>"]
        if not c["connue"]:
            out.append(f"<p style='color:{YELLOW}'>⚠ Introuvable dans le modèle : renommée "
                       "ou supprimée. Les visuels qui l'utilisent s'affichent en erreur.</p>")
        d = self.dep_colonnes[i]
        out.append(f"<p><b>{_e(self._resume_dependances_colonne(d))}</b></p>")
        via = [v for v in d["visuels"] if v not in d["visuels_directs"]]
        for genre, mot in self.GENRES_USAGE:
            us = [u for u in c["usages"] if u["genre"] == genre]
            if genre == "mesure" and via:
                # avant les mesures : ce qu'on voit dans le rapport
                out.append(f"<h4>Visuels par une mesure ({len(via)})</h4>"
                           + self._liste([self._ou(v) for v in via]))
            if not us:
                continue
            if genre == "mesure" and len(us) > PLIER_APRES:
                out.append(f"<h4>Mesures qui la lisent ({len(us)})</h4>"
                           + self._liste(self._lignes_familles(d["mesures_directes"])))
                continue
            lignes = []
            for u in sorted(us, key=lambda u: u["ou"].lower()):
                lien = self._a(u["ou"], u["cible"]) if u["cible"] else _e(u["ou"])
                lignes.append(lien + (f" <span style='color:{TEXT_MUTED}'>{_e(u['texte'])}</span>"
                                      if u["texte"] else ""))
            titre = {"segment": "Segments", "filtre de rapport": "Filtres du rapport",
                     "filtre de page": "Filtres de page", "filtre de visuel": "Filtres de visuel",
                     "visuel": "Visuels", "mesure": "Mesures qui la lisent"}[genre]
            out.append(f"<h4>{titre} ({len(lignes)})</h4>" + self._liste(lignes))
        autres = [m for m in d["mesures"] if m not in d["mesures_directes"]]
        if autres:
            out.append(f"<h4>Mesures qui les reprennent ({len(autres)})</h4>"
                       + self._liste(self._lignes_familles(autres)))
        return "".join(out)

    @staticmethod
    def _resume_dependances_colonne(d) -> str:
        parts = []
        if d["mesures"]:
            parts.append(f"{len(d['mesures'])} mesure(s), dont {len(d['mesures_directes'])} "
                         "qui la lisent")
        if d["filtres"]:
            parts.append(f"{len(d['filtres'])} filtre(s)")
        if d["segments"]:
            parts.append(f"{len(d['segments'])} segment(s)")
        if d["visuels"]:
            parts.append(f"{len(d['visuels'])} visuel(s) sur {d['pages']} page(s)")
        return " · ".join(parts) or "Rien n'en dépend dans le rapport."

    def _lignes_familles(self, noms) -> list:
        """Des mesures en lignes de fiche, une par famille : « Body Fat % · 21 »."""
        gris = f"style='color:{TEXT_MUTED}'"
        out = []
        for kpi, ns in self._par_famille(noms):
            cible = kpi if kpi in self.res["mesures"] else ns[0]
            out.append(self._a(kpi, ("mesure", cible))
                       + (f" <span {gris}>· {len(ns)} mesures</span>" if len(ns) > 1 else ""))
        return out

    # ---- Lignage : la fiche d'une boîte -----------------------------------------

    def _montrer_noeud(self, nid):
        if nid is None:
            self._vider_fiche()
            return
        self._afficher(self._fiche_noeud, nid)

    def _fiche_noeud(self, nid) -> str:
        """En tête, la chaîne de la boîte : d'où elle vient, à quoi elle mène,
        bande par bande. Ensuite, la fiche de ce qu'elle est."""
        n = self.graphe["noeuds"][nid]
        amont = lgn.chaine_sens(self.graphe["liens"], nid, amont=True) - {nid}
        aval = lgn.chaine_sens(self.graphe["liens"], nid, amont=False) - {nid}
        out = [f"<p style='color:{TEXT_MUTED}'>Lignage · {_e(lgn.TITRES[n['bande']])}</p>"]
        for titre, ens in (("Vient de", amont), ("Mène à", aval)):
            par_bande = self._par_bande(ens)
            if par_bande:
                out.append(f"<h4>{titre}</h4><table cellspacing='0' cellpadding='2'>"
                           + "".join(par_bande) + "</table>")
        if not n["utilise"]:
            out.append(f"<p style='color:{YELLOW}'>Ne mène à aucun visuel : rien de ce qu'on "
                       "voit dans le rapport n'en dépend.</p>")
        if n["genre"] == "mesures" and len(n.get("membres") or []) > 1:
            out.append("<p>" + self._a(f"▸ Déplier la famille : une boîte par mesure "
                                       f"({len(n['membres'])})",
                                       ("lignage_deplier", n["libelle"])) + "</p>")
        elif n["genre"] == "mesure":
            out.append(f"<p style='color:{TEXT_DIM}'>Une mesure de la famille "
                       f"<b>{_e(n.get('famille', ''))}</b> · "
                       + self._a("replier la famille", ("lignage_replier", n.get("famille")))
                       + "</p>")
        genre, cle = n["cible"] or (None, None)
        corps = ""
        if genre == "source" and cle.get("genre") == lg.SOURCE:
            corps = self._fiche_source_entiere(cle)
        elif genre in ("source", "table"):
            corps = self._fiche_source(cle)
        elif genre == "mesure":
            corps = self._fiche_mesure(cle)
        elif genre == "famille":
            corps = self._fiche_famille(cle)
        elif genre == "parametre" and cle in self.res["parametres"]:
            corps = self._fiche_parametre(cle)
        elif genre == "visuel":
            corps = self._fiche_visuel(cle)
        elif genre == "filtre":
            visuels = [self.graphe["noeuds"][b] for a, b in self.graphe["liens"] if a == nid]
            corps = (f"<h3>{_e(n['libelle'])}</h3><p style='color:{TEXT_DIM}'>"
                     f"{_e(n['detail'])}</p><h4>Filtre ({len(visuels)})</h4>"
                     + self._liste([_e(f"{v['page']} › {v['libelle']}") for v in visuels]))
        return "".join(out) + "<hr>" + corps

    def _fiche_source_entiere(self, l) -> str:
        """Une source : son type, les tables qui la lisent, et tout ce qui en
        dépend, toutes tables confondues."""
        source, lieu = source_et_lieu(l)
        cle = (l["connecteur"], l["detail1"], l["detail2"])
        tables = sorted({lg.nom_noeud(x) for x in self.lineage.get("lignes", [])
                         if x["genre"] == lg.SOURCE
                         and (x["connecteur"], x["detail1"], x["detail2"]) == cle},
                        key=str.lower)
        out = [f"<h3>{_e(source)}</h3>",
               f"<p style='color:{TEXT_DIM}'>{_e(type_de(l))} · {_e(l['connecteur'])}</p>"]
        if lieu:
            out.append(f"<p style='color:{TEXT_MUTED}'>dans {_e(lieu)}</p>")
        out.append(f"<h4>Lue par {len(tables)} table(s)</h4>"
                   + self._liste([f"<b>{_e(t)}</b>" for t in tables]))
        if self.impacts is not None:
            out.append("<h4>Ce qui en dépend dans le rapport</h4>"
                       + self._bloc_dependances(rg.cumuler(self.impacts, tables)))
        return "".join(out)

    def _par_bande(self, ids) -> list:
        """Une ligne de tableau par bande : « 7 | Visuels | Aires…, Carte… »."""
        noeuds = self.graphe["noeuds"]
        out = []
        for bande in lgn.BANDES:
            ns = [noeuds[i] for i in ids if noeuds[i]["bande"] == bande]
            if not ns:
                continue
            noms = sorted({x["libelle"] for x in ns}, key=str.lower)
            texte = _e(", ".join(noms[:3])) + (f" et {len(noms) - 3} autres"
                                              if len(noms) > 3 else "")
            # une boîte de la bande Mesures est une famille, ou une mesure
            # d'une famille dépliée
            titre = lgn.TITRES[bande]
            if bande == "mesures":
                n_fam = sum(1 for x in ns if x["genre"] == "mesures")
                titre = ("Familles de mesures" if n_fam == len(ns) else
                         "Mesures" if not n_fam else "Mesures et familles")
            out.append(f"<tr><td align='right' valign='top'><b>{len(ns)}</b></td>"
                       f"<td valign='top'>{_e(titre)}</td>"
                       f"<td valign='top' style='color:{TEXT_MUTED}'>{texte}</td></tr>")
        return out

    # ---- Par source : ce qui dépend d'une table ---------------------------------

    def _montrer_source(self, ligne):
        if not ligne:
            return
        self._afficher(self._fiche_source, ligne)

    @staticmethod
    def _resume_dependances(d) -> str:
        """« 2 tables calculées · 66 mesures · 4 visuels sur 2 pages »."""
        def n(x, un, plusieurs):
            return f"{x} {un if x == 1 else plusieurs}" if x else ""
        parts = [n(len(d["tables_calculees"]), "table calculée", "tables calculées"),
                 n(len(d["colonnes_calculees"]), "colonne calculée", "colonnes calculées"),
                 n(len(d["mesures"]), "mesure", "mesures"),
                 n(len(d["filtres"]), "filtre", "filtres"),
                 n(len(d["segments"]), "segment", "segments"),
                 n(len(d["visuels"]), "visuel", "visuels")
                 + (f" sur {d['pages']} page" + ("s" if d["pages"] > 1 else "")
                    if d["visuels"] else "")]
        return " · ".join(x for x in parts if x)

    def _fiche_source(self, l) -> str:
        gris = f"style='color:{TEXT_MUTED}'"
        nom = lg.nom_noeud(l) if l.get("table") is not None else ""
        source, lieu = source_et_lieu(l)
        details = [type_de(l)] + [x for x in (source, l.get("objet", ""), l.get("mode", "")) if x]
        out = [f"<h3>{_e(nom or self.lineage.get('modele', ''))}</h3>",
               f"<p style='color:{TEXT_DIM}'>" + " · ".join(_e(x) for x in details) + "</p>"]
        if lieu:
            out.append(f"<p {gris}>dans {_e(lieu)}</p>")
        if l.get("lit"):
            out.append("<p>Calculée à partir de : <b>" + ", ".join(_e(t) for t in l["lit"])
                       + "</b></p>")
        imp = (self.impacts or {}).get(nom)
        if imp is None:
            out.append(f"<p {gris}>Ce qui dépend des tables se lit quand le modèle est "
                       "local.</p>")
            return "".join(out)
        out.append("<h4>Ce qui en dépend dans le rapport</h4>")
        out.append(self._bloc_dependances(imp))
        if l["genre"] == lg.SOURCE:
            cle = (l["connecteur"], l["detail1"], l["detail2"])
            soeurs = sorted({lg.nom_noeud(x) for x in self.lineage.get("lignes", [])
                             if x["genre"] == lg.SOURCE
                             and (x["connecteur"], x["detail1"], x["detail2"]) == cle},
                            key=str.lower)
            if len(soeurs) > 1:
                tot = self._resume_dependances(rg.cumuler(self.impacts, soeurs))
                out.append(f"<h4>Toute la source {_e(source)}</h4>"
                           f"<p>{len(soeurs)} tables la lisent : "
                           + ", ".join(f"<b>{_e(t)}</b>" for t in soeurs) + ".</p>"
                           + "<p>" + _e(tot or "Rien n'en dépend.") + "</p>")
        return "".join(out)

    def _bloc_dependances(self, d) -> str:
        gris = f"style='color:{TEXT_MUTED}'"
        resume = self._resume_dependances(d)
        if not resume:
            return (f"<p {gris}>Rien : ni table ou colonne calculée, ni mesure, ni filtre, "
                    "ni visuel ne la lit.</p>")
        out = [f"<p><b>{_e(resume)}</b></p>"]
        # ce qu'on voit dans le rapport d'abord, ce qui est dans le modèle ensuite
        if d["visuels"]:
            out.append(f"<h4>Visuels ({len(d['visuels'])})</h4>"
                       + self._liste([self._ou(v) for v in d["visuels"]]))
        if d["filtres"]:
            out.append(f"<h4>Filtres ({len(d['filtres'])})</h4>" + self._liste(
                [_e(u["genre"]) + " · " + (self._a(u["ou"], u["cible"]) if u["cible"]
                                           else _e(u["ou"]))
                 + (f" <span {gris}>{_e(u['texte'])}</span>" if u["texte"] else "")
                 for u in d["filtres"]]))
        if d["segments"]:
            out.append(f"<h4>Segments ({len(d['segments'])})</h4>" + self._liste(
                [self._a(u["ou"], u["cible"])
                 + (f" <span {gris}>{_e(u['texte'])}</span>" if u["texte"] else "")
                 for u in d["segments"]]))
        if d["tables_calculees"]:
            out.append("<h4>Tables calculées</h4>"
                       + self._liste([_e(t) for t in d["tables_calculees"]]))
        if d["colonnes_calculees"]:
            out.append("<h4>Colonnes calculées</h4>"
                       + self._liste([_e(f"'{t}'[{c}]") for t, c in d["colonnes_calculees"]]))
        if d["mesures"]:
            directes = d["mesures_directes"]
            autres = [m for m in d["mesures"] if m not in directes]
            out.append(f"<h4>Mesures ({len(d['mesures'])})</h4>")
            if directes:
                out.append(f"<p {gris}>Lisent la table ({len(directes)}) :</p>"
                           + self._liste([self._a(m, ("mesure", m)) for m in directes]))
            if autres:
                # une ligne par famille : 64 mesures en font souvent 3
                lignes = self._lignes_familles(autres)
                out.append(f"<p {gris}>Reprennent ces mesures ({len(autres)}), par famille :</p>"
                           + self._liste(lignes))
        return "".join(out)

    # ---- navigation ----------------------------------------------------------

    def _lien(self, url):
        try:
            genre, cle = self._liens[int(url.fragment() or url.toString().lstrip("#"))]
        except (ValueError, IndexError):
            return
        if genre == "plier":
            self._plier(cle)
            return
        self.aller_a(genre, cle)

    def aller_a(self, genre, cle) -> None:
        """Sélectionne une mesure (vue Par KPI) ou un visuel (vue Par page) ;
        ou, dans le lignage, une mesure seule, ou une famille à déplier ou
        replier."""
        if genre in ("lignage", "lignage_deplier", "lignage_replier"):
            vl = self.vue_lignage
            self.vues.setCurrentWidget(vl)
            if genre == "lignage":
                vl.choisir_mesure(cle)
            elif genre == "lignage_deplier":
                vl.deplier_famille(cle, ("mesure", cle) if ("mesures", cle) in
                                   vl.graphe["noeuds"] and cle in
                                   vl.graphe["noeuds"][("mesures", cle)].get("membres", [])
                                   else None)
            else:
                vl.replier_famille(cle)
            return
        if genre == "mesure":
            it, arbre = self._item_mesure.get(cle), self.arbre_kpi
        elif genre == "visuel":
            it, arbre = self._item_visuel.get(cle), self.arbre_pages
        else:
            fiches = {"parametre": self._fiche_parametre, "page": self._fiche_page}
            if genre in fiches:
                self._afficher(fiches[genre], cle)
            return
        if it is None:
            return
        if self.ed_filtre.text() and it.isHidden():
            self.ed_filtre.clear()
        self.vues.setCurrentWidget(arbre)
        p = it.parent()
        while p is not None:
            p.setExpanded(True)
            p = p.parent()
        arbre.setCurrentItem(it)
        arbre.scrollToItem(it)
