# -*- coding: utf-8 -*-
"""La grille des sources du formatage — de quel KPI chaque KPI copie chaque
variation.

Une ligne par KPI, une colonne par variation, et dans chaque case le NOM du
KPI copié — en toutes lettres, pas en symboles. Le gabarit de BASE sert à tout
le monde. Un GROUPE est une famille de KPI qui se propagent entre eux : son
gabarit, un de ses membres, donne aux autres — et il se pose PAR-DESSUS la
base : il en reçoit d'abord tout, puis ses propres réglages l'emportent. La
ligne « Tous les KPI » donne un gabarit PAR VARIATION, pour tout le monde
(aux groupes, par leur gabarit) : le PY se règle une fois. Et une case peut
avoir sa propre règle : copier un autre KPI, ou rester « à la main ».

Les règles (l'ordre de priorité, une source est toujours sa propre source,
ceux qui copiaient suivent…) vivent dans propagate_cf.Sources : cette fenêtre
montre et relaie. Le fichier est propagation.json, à côté des .pbip, partagé
par toutes les versions du rapport.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from qtpy.QtCore import QPointF, Qt
from qtpy.QtGui import (QBrush, QColor, QFont, QFontMetrics, QGuiApplication,
                        QPen, QPolygonF)
from qtpy.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import propagate_cf as pc

try:
    from core.theme import (ACCENT, BORDER, ORANGE, SURFACE, TEXT, TEXT_DIM,
                            TEXT_MUTED, YELLOW)
except ImportError:                                  # copie isolée
    ACCENT, BORDER, ORANGE, SURFACE = "#56C596", "#1E2D3D", "#E8873A", "#162032"
    TEXT, TEXT_DIM, TEXT_MUTED, YELLOW = ("#E2E8F0", "#C8D4E0", "#7F898A",
                                          "#D4AE28")

AUCUN = "(aucun)"
TOUS = "Tous les ICP"
SANS_GROUPE = "Sans groupe"
# ce qu'on lit dans une case — des mots, pas des symboles
GABARIT = "Gabarit"
SUR_LA_BASE = "Gabarit sur la base"      # un gabarit de groupe, par-dessus
A_LA_MAIN = "À la main"
NON_PROPAGE = "non propagé"
PAS_DE_MESURE = "pas de mesure"

# le fond d'une case dit sa SOURCE : une couleur par KPI source, dans l'ordre
# où elles apparaissent. Sombres, pour que le texte clair reste lisible ;
# pâlies quand la case HÉRITE (règle posée plus haut), franches quand la
# règle est posée sur la case elle-même.
TEINTES = ["#1F4E6B", "#5A3A6E", "#6B4A1F", "#1F5E4A", "#6B2F3A",
           "#4A5A1F", "#2F3F6B", "#5E3F2A"]
TEINTE_BASE = "#1C3A33"          # le gabarit de base : l'accent, éteint
TEINTE_MAIN = "#2A3346"          # « à la main »
FOND_TITRE = "#0F1829"           # lignes « Tous les KPI », groupes
LARGEUR_COLONNE = 128            # un nom de KPI se lit en entier (ou presque)

ROLE_FOND = Qt.UserRole + 1
ROLE_ENCRE = Qt.UserRole + 2
ROLE_GRAS = Qt.UserRole + 3
ROLE_ITALIQUE = Qt.UserRole + 4
ROLE_PERTE = Qt.UserRole + 5

# d'où vient la règle d'une case, en mots (cf. propagate_cf.NIVEAUX)
ORIGINE = {
    "case": "règle posée sur cette case",
    "groupe": "règle du groupe « {} » pour cette variation",
    "tous": "ligne « Tous les ICP »",
    "ligne": "règle posée sur cet ICP, toutes variations",
    "gabarit_groupe": "gabarit du groupe « {} »",
    "base": "gabarit de base",
}


def _palir(couleur, part=0.45):
    """La teinte d'une case qui HÉRITE : la couleur de sa source, fondue dans
    le fond."""
    a, b = QColor(couleur), QColor(SURFACE)
    return QColor(round(a.red() * part + b.red() * (1 - part)),
                  round(a.green() * part + b.green() * (1 - part)),
                  round(a.blue() * part + b.blue() * (1 - part))).name()


class _Delegue(QStyledItemDelegate):
    """Peint une case : le fond de sa source, son texte, un coin orange si du
    formatage serait retiré, et un CADRE quand elle est sélectionnée — la
    couleur reste visible pendant qu'on sélectionne."""

    def paint(self, p, opt, index):
        p.save()
        r = opt.rect
        p.fillRect(r, QColor(index.data(ROLE_FOND) or SURFACE))
        police = QFont(opt.font)
        police.setBold(bool(index.data(ROLE_GRAS)))
        police.setItalic(bool(index.data(ROLE_ITALIQUE)))
        p.setFont(police)
        p.setPen(QColor(index.data(ROLE_ENCRE) or TEXT))
        texte = QFontMetrics(police).elidedText(
            index.data(Qt.DisplayRole) or "", Qt.ElideRight,
            max(0, r.width() - 10))
        p.drawText(r.adjusted(5, 0, -5, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   texte)
        if index.data(ROLE_PERTE):
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(ORANGE)))
            c = 9
            p.drawPolygon(QPolygonF([QPointF(r.right() - c, r.top()),
                                     QPointF(r.right() + 1, r.top()),
                                     QPointF(r.right() + 1, r.top() + c + 1)]))
        if opt.state & QStyle.State_Selected:
            p.setPen(QPen(QColor(ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(1, 1, -2, -2))
        p.restore()


class SourcesDialog(QDialog):
    """Édite la grille des sources (propagation.json)."""

    def __init__(self, chemin, kpis, parent=None, source=None, analyse=None):
        super().__init__(parent)
        # `chemin` : où l'on ÉCRIT (le fichier partagé) ; `source` : d'où l'on
        # lit, si ce n'est pas lui (un ancien fichier propre au rapport)
        self.chemin = Path(chemin)
        self.source = Path(source) if source else self.chemin
        self.analyse = analyse or {}
        self.enregistre = False
        self.confirmer_fermeture = True       # les tests la coupent
        kpis = list(self.analyse.get("kpis") or kpis)
        regles = pc.lire_regles(self.source)
        self.grille = pc.Sources.depuis_regles(
            regles, kpis, self.analyse.get("variations") or [pc.libelle_reel({})])
        self.grille.menage()
        self._depart = self._empreinte()
        self._teintes: dict = {}
        self._notes: list = []
        self._rangs: list = []                # ce que montre chaque ligne

        self.setWindowTitle("Sources du formatage · " + self.chemin.name)
        lay = QVBoxLayout(self)

        intro = QLabel(
            "Chaque case dit de quel ICP cet ICP copie le formatage de cette "
            "variation. Par défaut, tout vient du <b>gabarit de base</b>. Un "
            "<b>groupe</b> a son propre gabarit, posé <b>par-dessus</b> la "
            "base : il en reçoit d'abord tout, puis ses propres réglages "
            "l'emportent, et ses ICP copient le résultat. La ligne <b>Tous "
            "les ICP</b> donne un gabarit par variation, pour tout le monde "
            "(aux groupes, par leur gabarit). Sélectionner des cases "
            "(clic-glisser, ou un en-tête de ligne ou de colonne), puis "
            "choisir ce qu'elles copient.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{TEXT_DIM};")
        lay.addWidget(intro)

        haut = QHBoxLayout()
        haut.addWidget(QLabel("Gabarit de base :"))
        self.cmb_base = QComboBox()
        self.cmb_base.addItems([AUCUN] + self.grille.kpis)
        self.cmb_base.setCurrentText(self.grille.base or AUCUN)
        self.cmb_base.setToolTip(
            "L'ICP formaté en entier dans Desktop, et que tous les\n"
            "autres copient, sauf ce qu'une règle plus précise décide.")
        self.cmb_base.currentTextChanged.connect(self._changer_base)
        haut.addWidget(self.cmb_base)
        ordre = QLabel("Priorité : règle de la case › groupe (variation) › "
                       "gabarit du groupe › Tous les ICP › gabarit de base\n"
                       "Un gabarit de groupe se pose par-dessus Tous les ICP "
                       "et la base : ce qu'il règle l'emporte.")
        ordre.setStyleSheet(f"color:{TEXT_MUTED};")
        haut.addSpacing(16)
        haut.addWidget(ordre)
        haut.addStretch()
        lay.addLayout(haut)

        g = self.grille
        self.table = QTableWidget(0, len(g.variations))
        self.table.setHorizontalHeaderLabels(g.variations)
        self.table.setItemDelegate(_Delegue(self.table))
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setStyleSheet(f"QTableWidget {{ gridline-color: {BORDER}; }}")
        h = self.table.horizontalHeader()
        # assez large pour lire un nom de KPI ; la grille occupe la largeur
        # disponible, et défile quand toutes les variations n'y tiennent pas
        h.setMinimumSectionSize(LARGEUR_COLONNE)
        h.setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemSelectionChanged.connect(self._selection_changee)
        lay.addWidget(self.table, 1)

        barre = QHBoxLayout()
        barre.addWidget(QLabel("Copier depuis :"))
        self.cmb_source = QComboBox()
        self.cmb_source.addItems(g.kpis)
        barre.addWidget(self.cmb_source)
        self.btn_appliquer = QPushButton("Appliquer")
        self.btn_appliquer.setToolTip(
            "Les cases sélectionnées copient cet ICP.")
        self.btn_appliquer.clicked.connect(
            lambda: self._appliquer(self.cmb_source.currentText()))
        self.btn_main = QPushButton(A_LA_MAIN)
        self.btn_main.setToolTip(
            "Les cases sélectionnées ne copient rien : chaque ICP garde ce\n"
            "qui a été formaté sur lui dans Desktop.")
        self.btn_main.clicked.connect(lambda: self._appliquer(pc.MANUEL))
        self.btn_retirer = QPushButton("Retirer la règle")
        self.btn_retirer.setToolTip(
            "Les cases sélectionnées suivent de nouveau la règle plus large :\n"
            "leur groupe, la ligne « Tous les ICP », le gabarit du groupe,\n"
            "puis le gabarit de base.")
        self.btn_retirer.clicked.connect(lambda: self._appliquer(None))
        for b in (self.btn_appliquer, self.btn_main, self.btn_retirer):
            barre.addWidget(b)
        barre.addSpacing(16)
        self.btn_groupes = QPushButton("Groupes")
        self.menu_groupes = QMenu(self.btn_groupes)
        self.menu_groupes.aboutToShow.connect(
            lambda: self._remplir_menu_groupes(self.menu_groupes))
        self.btn_groupes.setMenu(self.menu_groupes)
        self.btn_groupes.setToolTip(
            "Un groupe : un ensemble d'ICP qui copient leur propre gabarit.")
        barre.addWidget(self.btn_groupes)
        barre.addStretch()
        lay.addLayout(barre)

        legende = QLabel(
            f"<b>{GABARIT}</b> : formaté à la main, copié par d'autres"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;<b>{SUR_LA_BASE}</b> : un gabarit de "
            "groupe, qui reçoit d'abord la base (ou « Tous les ICP ») puis "
            "ses propres réglages"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;<b>{A_LA_MAIN}</b> : rien n'y est copié"
            "&nbsp;&nbsp;·&nbsp;&nbsp;<b>un nom</b> : la case copie cet ICP "
            "(en gras : règle posée sur cette ligne)"
            "&nbsp;&nbsp;·&nbsp;&nbsp;<b>coin orange</b> : du formatage "
            "serait retiré")
        legende.setWordWrap(True)
        legende.setStyleSheet(f"color:{TEXT_MUTED};")
        lay.addWidget(legende)
        self.lbl_couleurs = QLabel("")
        self.lbl_couleurs.setWordWrap(True)
        lay.addWidget(self.lbl_couleurs)

        self.lbl_verdict = QLabel("")
        self.lbl_verdict.setWordWrap(True)
        lay.addWidget(self.lbl_verdict)
        self.lbl_notes = QLabel("")
        self.lbl_notes.setWordWrap(True)
        self.lbl_notes.setStyleSheet(f"color:{TEXT_DIM};")
        lay.addWidget(self.lbl_notes)

        bas = QHBoxLayout()
        fichier = QLabel(
            "Fichier : " + self.chemin.name + ", partagé par les rapports du "
            "dossier" + ("" if self.source == self.chemin else
                         f", lu depuis « {self.source.name} », l'ancien "
                         "fichier de ce rapport"))
        fichier.setStyleSheet(f"color:{TEXT_MUTED};")
        fichier.setToolTip(str(self.chemin))
        bas.addWidget(fichier)
        bas.addStretch()
        self.btn_save = QPushButton("Enregistrer")
        self.btn_save.clicked.connect(self._enregistrer)
        b_close = QPushButton("Fermer")
        b_close.clicked.connect(self.reject)
        bas.addWidget(self.btn_save)
        bas.addWidget(b_close)
        lay.addLayout(bas)

        self._remplir()
        self._selection_changee()
        # la fenêtre à la largeur de la grille : toutes les variations
        # lisibles d'un coup d'œil, sans dépasser l'écran
        voulu = (self.table.verticalHeader().sizeHint().width()
                 + LARGEUR_COLONNE * self.table.columnCount() + 60)
        ecran = QGuiApplication.primaryScreen()
        dispo = ecran.availableGeometry().width() - 80 if ecran else voulu
        self.resize(max(1120, min(voulu, dispo)), self.height())

    # ---- les lignes de la grille ---------------------------------------------

    def _rangs_voulus(self) -> list:
        """Ce que montre chaque ligne : ("tous", None), ("groupe", nom),
        ("sans_groupe", None) ou ("kpi", nom du KPI) — les groupes d'abord,
        chacun suivi de ses KPI, puis les KPI sans groupe."""
        g = self.grille
        rangs = [("tous", None)]
        for nom, gr in g.groupes.items():
            rangs.append(("groupe", nom))
            rangs += [("kpi", k) for k in gr["kpis"]]
        libres = [k for k in g.kpis if k not in g.groupe_de]
        if g.groupes and libres:
            rangs.append(("sans_groupe", None))
        rangs += [("kpi", k) for k in libres]
        return rangs

    def rang_de(self, quoi, qui=None) -> int:
        """La ligne de la grille qui montre (quoi, qui) — pour les tests."""
        return self._rangs.index((quoi, qui))

    def _entete(self, quoi, qui) -> str:
        g = self.grille
        if quoi == "tous":
            return TOUS
        if quoi == "groupe":
            return pc.groupe_en_mots(qui, majuscule=True) + (
                ", indépendant" if g.groupes[qui].get("independant") else "")
        if quoi == "sans_groupe":
            return SANS_GROUPE
        role = ""
        if qui == g.base:
            role = " (gabarit de base)"
        elif qui in g.groupe_de and g.groupes[g.groupe_de[qui]]["base"] == qui:
            role = " (gabarit du groupe)"
        retrait = "    " if qui in g.groupe_de else ""
        return retrait + qui + role

    # ---- ce que montre une case ------------------------------------------------

    def _teinte(self, source):
        if source == self.grille.base:
            return TEINTE_BASE
        if source not in self._teintes:
            self._teintes[source] = TEINTES[len(self._teintes) % len(TEINTES)]
        return self._teintes[source]

    def _case_regle(self, valeur, v, ou):
        """Une case des lignes « Tous les KPI » et groupe : la règle posée à
        ce niveau, ou rien."""
        if valeur is None:
            etiquette = pc.etiquette_du_detail(v)
            return ("", FOND_TITRE, TEXT_MUTED, False, False, False,
                    f"{ou} · {v}\nAucune règle ici : "
                    + (f"le détail suit son étiquette, « {etiquette} »."
                       if etiquette else "les ICP suivent la règle plus large."))
        if valeur == pc.MANUEL:
            return (A_LA_MAIN, TEINTE_MAIN, TEXT, True, False, False,
                    f"{ou} · {v}\nÀ la main : chaque ICP garde ce qui est "
                    "formaté sur lui.")
        return (valeur, self._teinte(valeur), TEXT, True, False, False,
                f"{ou} · {v}\nCopient « {valeur} ».")

    def _case(self, k, v, retraits):
        """(texte, fond, encre, gras, italique, perte, infobulle) de (k, v)."""
        g = self.grille
        s = g.source(k, v)
        quoi, qui = g.niveau(k, v)
        origine = ORIGINE[quoi].format(qui)
        suit = g.suit_son_etiquette(k, v)
        if suit:
            # aucune règle sur le détail : celle de son étiquette décide
            origine = (f"le détail suit son étiquette, « "
                       f"{pc.etiquette_du_detail(v)} », {origine}")
        mesures = self.analyse.get("mesures")
        reglages = self.analyse.get("reglages") or {}
        tete = f"{k} · {v}\n"
        if mesures is not None and (k, v) not in mesures:
            return (PAS_DE_MESURE, None, TEXT_MUTED, False, True, False,
                    tete + f"« {k} » n'a pas de mesure « {v} » : rien à y "
                    "écrire.")
        if s is None:
            texte, fond, encre, gras, ital = NON_PROPAGE, None, TEXT_MUTED, False, True
            info = tete + "Non propagé : ni rempli, ni nettoyé."
        elif s == k and g.gabarit(k, v):
            texte, fond, encre, gras, ital = GABARIT, self._teinte(k), TEXT, True, False
            copieurs = [x for x in g.kpis if x != k and g.source(x, v) == k]
            u = g.sous_couche(k, v)
            if u:
                texte = SUR_LA_BASE if u == g.base else f"{GABARIT} sur {u}"
                info = (tete + f"Gabarit du groupe, posé par-dessus « {u} » ("
                        + ("la base" if u == g.base else "Tous les ICP")
                        + f") : il reçoit d'abord le formatage de « {u} », "
                        "puis le sien par-dessus, ce qu'il règle lui-même "
                        f"l'emporte, le reste vient de « {u} ». Retoucher "
                        "un réglage reçu dans Desktop le fait sien.")
            else:
                info = (tete + f"Gabarit ({origine}) : formaté à la main dans "
                        "Desktop.")
                nom_g = g.groupe_de.get(k)
                if (nom_g and g.groupes[nom_g]["base"] == k
                        and g.groupes[nom_g].get("independant")):
                    info += " Groupe indépendant : il ne reçoit rien de la base."
            info += (f"\nCopié par : {', '.join(copieurs)}." if copieurs else "")
        elif s == k:
            texte, fond, encre, gras, ital = (A_LA_MAIN, TEINTE_MAIN, TEXT,
                                              quoi in ("case", "ligne") and not suit,
                                              False)
            info = (tete + f"À la main ({origine}) : rien ne lui est copié, "
                    "il garde ce qui est formaté sur lui.")
        else:
            posee = quoi in ("case", "ligne") and not suit
            if posee:
                fond, encre = self._teinte(s), TEXT
            elif s == g.base:
                fond, encre = None, TEXT_DIM
            else:
                fond, encre = _palir(self._teinte(s)), TEXT
            texte, gras, ital = s, posee, False
            info = tete + f"Copie « {s} », {origine}."
            u = g.sous_couche(s, v)
            if u:
                info += (f"\n« {s} » se pose par-dessus « {u} » : ce que "
                         f"« {s} » ne règle pas vient de « {u} ».")
            if mesures is not None and (s, v) not in mesures:
                # la source n'a pas cette mesure (une cible que la base n'a
                # pas) : rien ne sera copié — la case le montre, en retrait
                encre, ital = TEXT_MUTED, True
                info += (f"\nMais « {s} » n'a pas de mesure « {v} » : rien ne "
                         "sera copié. Choisir un ICP qui l'a (ligne « Tous "
                         "les ICP », par exemple).")
        n = sum((reglages.get((k, v)) or {}).values())
        if s not in (None, k):
            n_src = sum((reglages.get((s, v)) or {}).values())
            info += f"\nRéglages : {n} chez « {k} », {n_src} chez « {s} »."
        elif reglages:
            info += f"\nRéglages : {n}."
        perte = (k, v) in retraits
        if perte:
            info += (f"\nCoin orange : {retraits[(k, v)]} réglage(s) seraient "
                     f"retirés à la prochaine propagation, « {s} » n'en "
                     f"porte aucun pour « {v} ».")
        return texte, fond, encre, gras, ital, perte, info

    def _poser(self, r, c, texte, fond, encre, gras, ital, perte, info,
               selectionnable=True):
        it = self.table.item(r, c)
        if it is None:
            it = QTableWidgetItem()
            self.table.setItem(r, c, it)
        it.setText(texte)
        it.setData(ROLE_FOND, fond)
        it.setData(ROLE_ENCRE, encre)
        it.setData(ROLE_GRAS, gras)
        it.setData(ROLE_ITALIQUE, ital)
        it.setData(ROLE_PERTE, perte)
        it.setToolTip(info)
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable if selectionnable
                    else Qt.ItemIsEnabled)

    def _remplir(self):
        g = self.grille
        rangs = self._rangs_voulus()
        if rangs != self._rangs:            # la structure change : on rebâtit
            self.table.clearSelection()
            self.table.setRowCount(len(rangs))
            self._rangs = rangs
            # la fenêtre à la taille de la grille : ni vide sous 5 KPI, ni
            # plus haute que l'écran sous 40
            self.resize(max(self.width(), 1120),
                        min(860, 340 + 26 * len(rangs)))
        retraits = {(k, v): n for k, v, _s, n
                    in pc.retraits_prevus(self.analyse, g)}
        for r, (quoi, qui) in enumerate(rangs):
            tete = QTableWidgetItem(self._entete(quoi, qui))
            if quoi != "kpi":
                police = QFont(self.table.font())
                police.setBold(True)
                tete.setFont(police)
            self.table.setVerticalHeaderItem(r, tete)
            for c, v in enumerate(g.variations):
                if quoi == "tous":
                    self._poser(r, c, *self._case_regle(
                        g.colonnes.get(v), v, TOUS))
                elif quoi == "groupe":
                    self._poser(r, c, *self._case_regle(
                        g.groupes[qui]["colonnes"].get(v), v, f"Groupe {qui}"))
                elif quoi == "sans_groupe":
                    self._poser(r, c, "", FOND_TITRE, TEXT_MUTED, False, False,
                                False, "", selectionnable=False)
                else:
                    self._poser(r, c, *self._case(qui, v, retraits))
        self.table.viewport().update()
        self._legende_couleurs()
        self._verdict(retraits)

    def _legende_couleurs(self):
        """Quel KPI derrière quelle couleur : les sources présentes."""
        g = self.grille
        # les KPI dont une case porte la COULEUR : copiés par d'autres, ou
        # nommés gabarit (base, groupe, « Tous les KPI ») — pas ceux qui ne
        # sont qu'« à la main », peints de la teinte « à la main »
        copies = {s for v in g.variations for k in g.kpis
                  for s in [g.source(k, v)] if s not in (None, k)}
        nommes = ({g.base} | {gr["base"] for gr in g.groupes.values()}
                  | set(g.colonnes.values()))
        sources = [s for s in g.sources() if s and (s in copies or s in nommes)]
        morceaux = []
        for s in sources:
            role = " (gabarit de base)" if s == g.base else ""
            morceaux.append(
                f"<span style='background:{self._teinte(s)};'>"
                "&nbsp;&nbsp;&nbsp;&nbsp;</span>&nbsp;"
                f"<span style='color:{TEXT_DIM};'>{html.escape(s)}{role}</span>")
        self.lbl_couleurs.setText(
            f"<span style='color:{TEXT_MUTED};'>Sources :</span>&nbsp;&nbsp;"
            + "&nbsp;&nbsp;&nbsp;".join(morceaux) if morceaux else "")

    def _verdict(self, retraits):
        g = self.grille
        erreurs, avert = g.problemes()
        lignes = ["Problème : " + e for e in erreurs]
        if not erreurs:
            if not (g.base or g.groupes or g.cases or g.lignes or g.colonnes):
                lignes.append("Choisir le gabarit de base : c'est lui que "
                              "tout le monde copie.")
            else:
                court = g.resume_court()
                lignes.append(court[:1].upper() + court[1:] + ".")
        lignes += ["Attention : " + a for a in avert]
        sans = self._sources_sans_mesure()
        for (v, s), ks in sans.items():
            lignes.append(
                f"Attention : « {v} », {len(ks)} ICP copient « {s} », qui n'a "
                "pas cette mesure : rien ne leur sera copié. Leur donner un ICP "
                "qui l'a (ligne « Tous les ICP », par exemple).")
        if retraits:
            lignes.append(
                f"Attention : {sum(retraits.values())} réglage(s) seraient "
                "retirés à la prochaine propagation, les cases au coin orange "
                "copient un ICP qui n'a rien pour cette variation.")
        self.lbl_verdict.setText("\n".join(lignes))
        alerte = bool(erreurs or avert or retraits or sans)
        self.lbl_verdict.setStyleSheet(
            f"color:{YELLOW if alerte else TEXT_DIM};")
        self.btn_save.setEnabled(not erreurs)
        self.lbl_notes.setText("\n".join(self._notes))

    def _sources_sans_mesure(self) -> dict:
        """{(variation, source): [KPI]} — des KPI qui ONT la mesure mais
        copient un KPI qui ne l'a pas : typiquement les colonnes d'une cible,
        quand la base n'en a pas. Rien ne leur serait copié."""
        mesures = self.analyse.get("mesures")
        if mesures is None:
            return {}
        g = self.grille
        out: dict = {}
        for v in g.variations:
            for k in g.kpis:
                s = g.source(k, v)
                if (s not in (None, k) and (k, v) in mesures
                        and (s, v) not in mesures):
                    out.setdefault((v, s), []).append(k)
        return out

    # ---- édition -------------------------------------------------------------

    def _selection(self) -> list:
        """[(qui, variation)] — qui : un KPI, None (Tous les KPI) ou
        ("groupe", nom)."""
        g = self.grille
        cases = []
        for ix in self.table.selectedIndexes():
            quoi, qui = self._rangs[ix.row()]
            v = g.variations[ix.column()]
            if quoi == "tous":
                cases.append((None, v))
            elif quoi == "groupe":
                cases.append((("groupe", qui), v))
            elif quoi == "kpi":
                cases.append((qui, v))
        return cases

    def kpis_selectionnes(self) -> list:
        """Les KPI des lignes sélectionnées, dans l'ordre du modèle."""
        choisis = {self._rangs[ix.row()][1] for ix in self.table.selectedIndexes()
                   if self._rangs[ix.row()][0] == "kpi"}
        return [k for k in self.grille.kpis if k in choisis]

    def _selection_changee(self):
        rien = not self._selection()
        for b in (self.btn_appliquer, self.btn_main, self.btn_retirer):
            b.setEnabled(not rien)

    def _apres(self, notes):
        self._notes = notes
        self._remplir()
        self._selection_changee()

    def _appliquer(self, valeur):
        cases = self._selection()
        if cases:
            self._apres(self.grille.appliquer(cases, valeur))

    def _changer_base(self, texte):
        base = None if texte == AUCUN else texte
        if base != self.grille.base:
            self._apres(self.grille.changer_base(base))

    # ---- les groupes -----------------------------------------------------------

    def nouveau_groupe(self, nom=None):
        kpis = self.kpis_selectionnes()
        if not kpis:
            self._apres(["Sélectionner d'abord des lignes d'ICP : ce seront "
                         "les membres du groupe."])
            return
        if nom is None:
            nom, ok = QInputDialog.getText(
                self, "Nouveau groupe",
                "Nom du groupe (son gabarit sera « " + kpis[0]
                + " », à changer dans le menu Groupes) :")
            if not ok:
                return
        self._apres(self.grille.creer_groupe(nom, kpis))

    def ajouter_au_groupe(self, nom):
        self._apres(self.grille.mettre_dans(nom, self.kpis_selectionnes()))

    def retirer_du_groupe(self):
        self._apres(self.grille.sortir_du_groupe(self.kpis_selectionnes()))

    def changer_gabarit_groupe(self, nom, gabarit):
        self._apres(self.grille.changer_gabarit_groupe(nom, gabarit))

    def rendre_independant(self, nom, independant=True):
        self._apres(self.grille.rendre_independant(nom, independant))

    def renommer_groupe(self, nom, nouveau=None):
        if nouveau is None:
            nouveau, ok = QInputDialog.getText(self, "Renommer le groupe",
                                               "Nouveau nom :", text=nom)
            if not ok:
                return
        self._apres(self.grille.renommer_groupe(nom, nouveau))

    def supprimer_groupe(self, nom):
        self._apres(self.grille.supprimer_groupe(nom))

    def _remplir_menu_groupes(self, menu):
        menu.clear()
        g = self.grille
        choisis = bool(self.kpis_selectionnes())
        a = menu.addAction("Nouveau groupe avec les ICP sélectionnés…",
                           self.nouveau_groupe)
        a.setEnabled(choisis)
        ajouter = menu.addMenu("Ajouter les ICP sélectionnés au groupe")
        ajouter.setEnabled(choisis and bool(g.groupes))
        for nom in g.groupes:
            ajouter.addAction(nom, lambda nom=nom: self.ajouter_au_groupe(nom))
        a = menu.addAction("Retirer les ICP sélectionnés de leur groupe",
                           self.retirer_du_groupe)
        a.setEnabled(choisis)
        if g.groupes:
            menu.addSeparator()
        for nom, gr in g.groupes.items():
            sous = menu.addMenu(f"Groupe {nom}")
            gab = sous.addMenu("Gabarit du groupe")
            for k in gr["kpis"]:
                act = gab.addAction(
                    k, lambda nom=nom, k=k: self.changer_gabarit_groupe(nom, k))
                act.setCheckable(True)
                act.setChecked(gr["base"] == k)
            gab.addSeparator()
            act = gab.addAction(
                "À la main (chaque ICP garde le sien)",
                lambda nom=nom: self.changer_gabarit_groupe(nom, pc.MANUEL))
            act.setCheckable(True)
            act.setChecked(gr["base"] == pc.MANUEL)
            act = gab.addAction(
                "Aucun (ses ICP suivent le gabarit de base)",
                lambda nom=nom: self.changer_gabarit_groupe(nom, None))
            act.setCheckable(True)
            act.setChecked(gr["base"] is None)
            act = sous.addAction(
                "Gabarit posé par-dessus la base (décoché : groupe indépendant)",
                lambda nom=nom, gr=gr: self.rendre_independant(
                    nom, not gr.get("independant")))
            act.setCheckable(True)
            act.setChecked(not gr.get("independant"))
            sous.addAction("Renommer…", lambda nom=nom: self.renommer_groupe(nom))
            sous.addAction("Supprimer le groupe",
                           lambda nom=nom: self.supprimer_groupe(nom))

    def _menu(self, pos):
        menu = QMenu(self)
        if self._selection():
            copier = menu.addMenu("Copier depuis")
            for k in self.grille.kpis:
                copier.addAction(k, lambda k=k: self._appliquer(k))
            menu.addAction(A_LA_MAIN, lambda: self._appliquer(pc.MANUEL))
            menu.addAction("Retirer la règle", lambda: self._appliquer(None))
            menu.addSeparator()
        self._remplir_menu_groupes(menu.addMenu("Groupes"))
        point = self.table.viewport().mapToGlobal(pos)
        (menu.exec_ if hasattr(menu, "exec_") else menu.exec)(point)

    # ---- enregistrement --------------------------------------------------------

    def _empreinte(self) -> str:
        return json.dumps(self.grille.vers_regles(), sort_keys=True,
                          ensure_ascii=False)

    def modifie(self) -> bool:
        return self._empreinte() != self._depart

    def _enregistrer(self):
        erreurs, _ = self.grille.problemes()
        if erreurs:
            QMessageBox.warning(
                self, "Sources du formatage",
                "Le fichier n'a pas été écrit :\n\n· " + "\n· ".join(erreurs)
                + "\n\nCorriger d'abord, une propagation sur des règles "
                  "incohérentes réécrirait le rapport de travers.")
            return
        try:
            pc.ecrire_regles(self.chemin, self.grille.vers_regles())
        except OSError as e:
            QMessageBox.critical(self, "Erreur d'écriture", str(e))
            return
        self.enregistre = True
        self.accept()

    def reject(self):
        if (self.confirmer_fermeture and self.modifie()
                and QMessageBox.question(
                    self, "Sources du formatage",
                    "Fermer sans enregistrer les changements ?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                != QMessageBox.Yes):
            return
        super().reject()
