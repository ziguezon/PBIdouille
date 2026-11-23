# -*- coding: utf-8 -*-
"""Vue « Lignage » de la Radiographie : tout le rapport, de la source au visuel.

Un graphe (moteurs/lignage.py) en bandes : sources, requêtes Power Query,
tables calculées, mesures par famille, paramètres de champ, filtres et
segments, visuels rangés par page. De gauche à droite, ou de haut en bas.

Un clic sur une boîte allume sa chaîne : en VERT ce dont elle vient (l'amont),
en ORANGE ce qui en dépend (l'aval). Les pastilles « Sens » ne gardent que
l'un ou l'autre. « Seulement la chaîne » redessine le graphe avec la chaîne
seule ; « Exporter la chaîne… » l'écrit en CSV, une colonne disant l'amont
ou l'aval. Un clic sur le titre d'une bande la replie en une seule boîte : sur
un gros rapport, une bande de plus de REPLI_AUTO éléments part repliée.

Une famille de mesures est une boîte ; un double-clic la DÉPLIE en une boîte
par mesure, pour suivre la chaîne d'une seule mesure (un double-clic sur une
de ses mesures la replie). Le graphe est alors reconstruit par le
`constructeur` que donne la Radiographie (lignage.construire avec les
familles dépliées).

Par défaut, seul ce qui mène à un visuel est dessiné ; une case montre le
reste, en pointillés. Ctrl + molette zoome, glisser déplace, « Ajuster » montre
tout. Lecture seule, hors l'export qui écrit là où on le lui dit.
"""

from __future__ import annotations

import re
from pathlib import Path

from qtpy.QtCore import QPointF, QRectF, Qt, Signal
from qtpy.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from qtpy.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import lignage as lgn
from core.journal import Journal
from core.puces import Puces
from core.theme import (ACCENT, BLUE, BORDER, ORANGE, SURFACE, SURFACE_ALT, TEXT, TEXT_DIM,
                        TEXT_MUTED, TITRE_POLICE, TRAIT, YELLOW)

L, H = 180, 40                  # une boîte
ECART_X, ECART_Y = 48, 12       # entre colonnes, entre boîtes (le passage des liens)
ECART_RANG = 78                 # de haut en bas : entre deux rangées
MARGE_TITRE = 150               # de haut en bas : la place des titres, à gauche
HAUT = 34                       # de gauche à droite : la place des titres, en haut
REPLI_AUTO = 40                 # une bande plus nombreuse part repliée
# la couleur du liseré de chaque genre : on reconnaît une bande d'un coup d'œil
TEINTES = {"source": ORANGE, "requete": YELLOW, "calculee": BLUE, "mesures": ACCENT,
           "mesure": ACCENT,
           "parametre": "#A78BFA", "filtre": "#F472B6", "segment": "#F472B6",
           "visuel": TEXT_DIM}
AMONT_C, AVAL_C = ACCENT, ORANGE  # la chaîne : d'où ça vient, ce qui en dépend
ETEINT = 0.16                   # l'opacité de ce qui n'est pas dans la chaîne
SENS = (("deux", "Amont et aval", "Ce dont la boîte vient (vert) et ce qui en dépend "
                                  "(orange)"),
        ("amont", "Amont", "Seulement ce dont la boîte vient : ses sources, tables, mesures"),
        ("aval", "Aval", "Seulement ce qui dépend de la boîte : mesures, filtres, visuels"))
DISPOSITIONS = (("horizontal", "Gauche → droite", "Les bandes en colonnes"),
                ("vertical", "Haut → bas", "Les bandes en rangées"))


class _Boite(QGraphicsItem):
    """Un nœud : un liseré de couleur, son nom, et une ligne de détail. Une
    bande repliée est une boîte aussi, au fond plus clair."""

    def __init__(self, noeud):
        super().__init__()
        self.noeud = noeud
        self.choisie = False
        self.survol = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        # « + » : une famille qui se déplie en mesures ; « − » : une mesure dont
        # la famille se replie
        self.repere = ("+" if noeud["genre"] == "mesures" and len(noeud.get("membres") or []) > 1
                       else "−" if noeud["genre"] == "mesure" else "")
        if noeud["genre"] == "bande":
            tip = f"{noeud['libelle']} : {noeud['detail']}\n\nCliquer pour la déplier."
        else:
            tip = noeud["libelle"] + (f"\n{noeud['detail']}" if noeud["detail"] else "")
            if not noeud["utilise"]:
                tip += "\n\nNe mène à aucun visuel."
            if self.repere == "+":
                tip += "\n\nDouble-clic : une boîte par mesure."
            elif self.repere == "−":
                tip += f"\nFamille {noeud.get('famille', '')}\n\nDouble-clic : replier la famille."
        self.setToolTip(tip)

    def boundingRect(self):
        return QRectF(0, 0, L, H)

    def hoverEnterEvent(self, event):
        self.survol = True
        self.update()

    def hoverLeaveEvent(self, event):
        self.survol = False
        self.update()

    def paint(self, p, option, widget=None):
        n = self.noeud
        bande = n["genre"] == "bande"
        p.setRenderHint(QPainter.Antialiasing)
        cadre = QPen(QColor(ACCENT if self.choisie else TRAIT), 2 if self.choisie else 1)
        if not n["utilise"]:
            cadre.setStyle(Qt.DashLine)
        p.setPen(cadre)
        fond = BORDER if bande else (SURFACE_ALT if self.survol else SURFACE)
        p.setBrush(QBrush(QColor(fond)))
        p.drawRoundedRect(QRectF(0.5, 0.5, L - 1, H - 1), 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(TEINTES.get(n["bande"] if bande else n["genre"], TEXT_DIM))))
        p.drawRoundedRect(QRectF(1, 1, 5 if not bande else 9, H - 2), 2, 2)
        police = QFont(p.font())
        police.setPointSizeF(8.5)
        police.setBold(bande)
        fm = QFontMetrics(police)
        p.setFont(police)
        large = L - 20 - (14 if self.repere else 0)
        if self.repere:
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(QRectF(L - 18, 3, 12, 18), int(Qt.AlignCenter), self.repere)
        p.setPen(QColor(TEXT if n["utilise"] else TEXT_MUTED))
        p.drawText(QRectF(14, 3, large, 18), int(Qt.AlignLeft | Qt.AlignVCenter),
                   fm.elidedText(n["libelle"], Qt.ElideRight, large))
        if n["detail"]:
            police.setPointSizeF(7.5)
            police.setBold(False)
            fm = QFontMetrics(police)
            p.setFont(police)
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(QRectF(14, 20, L - 20, 16), int(Qt.AlignLeft | Qt.AlignVCenter),
                       fm.elidedText(str(n["detail"]), Qt.ElideRight, L - 20))


class _Titre(QGraphicsSimpleTextItem):
    """Le titre d'une bande : un clic la replie ou la déplie."""

    def __init__(self, bande, texte):
        super().__init__(texte)
        self.bande = bande
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Cliquer pour replier ou déplier cette bande.")


class _Lien(QGraphicsPathItem):
    """Un lien, donné par ses points en (axe principal, axe transversal) :
    le départ, puis pour chaque colonne qu'il saute une entrée et une sortie
    dans un passage entre deux boîtes, puis l'arrivée. Entre deux colonnes, une
    courbe ; à travers une colonne sautée, un trait droit dans le passage : le
    lien contourne les boîtes au lieu de les traverser."""

    def __init__(self, points, vertical=False):
        super().__init__()

        def pt(m, c):
            return QPointF(c, m) if vertical else QPointF(m, c)

        chemin = QPainterPath(pt(*points[0]))
        for i in range(1, len(points)):
            (m0, c0), (m1, c1) = points[i - 1], points[i]
            if i % 2 == 0:                  # d'une entrée à sa sortie : tout droit
                chemin.lineTo(pt(m1, c1))
            else:
                d = max((m1 - m0) / 2, 12)
                chemin.cubicTo(pt(m0 + d, c0), pt(m1 - d, c1), pt(m1, c1))
        self.setPath(chemin)
        self.colorer(None)

    def colorer(self, couleur, eteint=False):
        """`couleur` : celle de la chaîne, ou None pour un lien ordinaire."""
        c = QColor(couleur or TRAIT)
        if eteint:
            c.setAlphaF(0.25)
        self.setPen(QPen(c, 2 if couleur else 1.2))
        self.setZValue(0 if couleur else -1)


class _Vue(QGraphicsView):
    """Glisser déplace, Ctrl + molette zoome ; un clic choisit une boîte ou
    replie une bande, un clic dans le vide efface le choix."""
    clic = Signal(object)               # _Boite, _Titre ou None
    double = Signal(object)             # _Boite

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(SURFACE)))
        # le graphe part du coin haut gauche, comme une page qu'on lit
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._appui = None

    def mousePressEvent(self, event):
        self._appui = event.pos()
        cible = self._cible(event.pos())
        if cible is not None and event.button() == Qt.LeftButton:
            self.clic.emit(cible)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        cible = self._cible(event.pos())
        if isinstance(cible, _Boite):
            self.double.emit(cible)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._appui is not None and self._cible(event.pos()) is None \
                and (event.pos() - self._appui).manhattanLength() < 4:
            self.clic.emit(None)
        self._appui = None

    def _cible(self, pos):
        it = self.itemAt(pos)
        while it is not None and not isinstance(it, (_Boite, _Titre)):
            it = it.parentItem()
        return it

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            f = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(f, f)
            event.accept()
            return
        super().wheelEvent(event)


class VueLignage(QWidget):
    choisi = Signal(object)             # l'id du nœud choisi, ou None

    def __init__(self, journal=None):
        super().__init__()
        self.journal = journal or Journal()
        self.graphe: dict = {}
        self.choix = None
        self.repliees: set = set()      # les bandes repliées
        self.deplies: set = set()       # les familles dépliées en mesures
        self.constructeur = None        # deplies -> graphe (lignage.construire)
        self.dossier = None             # où proposer l'export
        self.boites: dict = {}          # id affiché -> _Boite
        self.liens: list = []           # [(A, B, _Lien, [(a, b) d'origine])]
        self.titres: dict = {}          # bande -> _Titre
        self._aff: dict = {}            # id d'origine -> id affiché
        self._texte = ""

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        haut = QHBoxLayout()
        self.puces_sens = Puces("Sens :")
        self.puces_sens.remplir(SENS)
        self.puces_sens.change.connect(self._sens_change)
        self.puces_dispo = Puces("Disposition :")
        self.puces_dispo.remplir(DISPOSITIONS)
        self.puces_dispo.change.connect(self._redessiner_et_ajuster)
        haut.addWidget(self.puces_sens)
        haut.addSpacing(16)
        haut.addWidget(self.puces_dispo)
        haut.addStretch(1)
        b_ajuster = QPushButton("Ajuster")
        b_ajuster.setToolTip("Montre tout le graphe. Ctrl + molette zoome.")
        b_ajuster.clicked.connect(self.ajuster)
        self.btn_export = QPushButton("Exporter la chaîne…")
        self.btn_export.setToolTip("Écrit en CSV la chaîne de la boîte choisie, dans le sens "
                                   "choisi : une ligne par élément (par mesure pour une "
                                   "famille), une colonne disant l'amont ou l'aval.")
        self.btn_export.clicked.connect(self._exporter)
        self.btn_export.setEnabled(False)
        haut.addWidget(b_ajuster)
        haut.addWidget(self.btn_export)
        v.addLayout(haut)

        bas = QHBoxLayout()
        self.cb_chaine = QCheckBox("Seulement la chaîne choisie")
        self.cb_chaine.setToolTip("Redessine le graphe avec la chaîne de la boîte choisie, "
                                  "dans le sens choisi, rien d'autre.")
        self.cb_chaine.toggled.connect(lambda *_: self._dessiner())
        self.cb_chaine.setEnabled(False)
        self.cb_tout = QCheckBox("Montrer aussi ce qui ne mène à aucun visuel")
        self.cb_tout.toggled.connect(lambda *_: self._dessiner())
        self.lbl = QLabel("")
        self.lbl.setStyleSheet(f"color:{TEXT_DIM};")
        bas.addWidget(self.cb_chaine)
        bas.addWidget(self.cb_tout)
        bas.addStretch(1)
        bas.addWidget(self.lbl)
        v.addLayout(bas)

        self.scene = QGraphicsScene(self)
        self.vue = _Vue(self.scene)
        self.vue.clic.connect(self._clic)
        self.vue.double.connect(self._double)
        v.addWidget(self.vue, 1)

    # ---- données ---------------------------------------------------------------

    @property
    def sens(self) -> str:
        return self.puces_sens.valeur() or "deux"

    @property
    def vertical(self) -> bool:
        return self.puces_dispo.valeur() == "vertical"

    def afficher(self, graphe: dict | None, constructeur=None):
        """Un nouveau graphe (nouveau projet, relecture). `constructeur`
        reconstruit le graphe avec des familles dépliées."""
        self.constructeur = constructeur
        self.deplies = set()
        self.graphe = graphe or {}
        self.choix = None
        self.cb_chaine.blockSignals(True)
        self.cb_chaine.setChecked(False)
        self.cb_chaine.blockSignals(False)
        self.cb_chaine.setEnabled(False)
        self.btn_export.setEnabled(False)
        noeuds = self.graphe.get("noeuds") or {}
        inutiles = sum(1 for n in noeuds.values() if not n["utilise"])
        self.cb_tout.setText("Montrer aussi ce qui ne mène à aucun visuel"
                             + (f" ({inutiles})" if inutiles else ""))
        self.cb_tout.setEnabled(bool(inutiles))
        # un gros rapport : ses bandes nombreuses partent repliées
        par_bande: dict = {}
        for n in noeuds.values():
            if n["utilise"]:
                par_bande[n["bande"]] = par_bande.get(n["bande"], 0) + 1
        self.repliees = {b for b, k in par_bande.items() if k > REPLI_AUTO}
        self._dessiner()
        self.ajuster(largeur_seule=True)

    def choisir(self, nid):
        """Choisit une boîte (ou rien) : sa chaîne s'allume."""
        self.choix = nid if nid in (self.graphe.get("noeuds") or {}) else None
        self.cb_chaine.setEnabled(self.choix is not None)
        self.btn_export.setEnabled(self.choix is not None)
        if self.choix is None and self.cb_chaine.isChecked():
            self.cb_chaine.setChecked(False)          # redessine
        elif self.cb_chaine.isChecked():
            self._dessiner()
        else:
            self._allumer()
        # choisie depuis un lien de la fiche, la boîte peut être hors de vue
        boite = self.boites.get(self._aff.get(self.choix))
        if boite is not None:
            self.vue.ensureVisible(boite, 60, 60)
        self.choisi.emit(self.choix)

    # ---- familles dépliées : la chaîne d'une seule mesure ------------------

    def famille_de(self, nom):
        """La famille d'une mesure, d'après le graphe ; None si inconnue."""
        for x in (self.graphe.get("noeuds") or {}).values():
            if x["genre"] == "mesure" and x["libelle"] == nom:
                return x.get("famille")
            if x["genre"] == "mesures" and nom in (x.get("membres") or []):
                return x["libelle"]
        return None

    def deplier_famille(self, kpi, choix=None):
        """Une boîte par mesure de la famille ; `choix` est choisi ensuite."""
        self.deplies.add(kpi)
        self._reconstruire(choix)

    def replier_famille(self, kpi):
        """Revient à une seule boîte pour la famille, choisie si l'une de ses
        mesures l'était."""
        dedans = self.choix is not None and self.choix[0] == "mesure" \
            and self.graphe["noeuds"][self.choix].get("famille") == kpi
        self.deplies.discard(kpi)
        self._reconstruire(("mesures", kpi) if dedans else self.choix)

    def choisir_mesure(self, nom):
        """Choisit UNE mesure : sa famille se déplie si elle en a plusieurs."""
        kpi = self.famille_de(nom)
        if kpi is None:
            return
        famille = (self.graphe["noeuds"].get(("mesures", kpi)) or {})
        if ("mesure", nom) in self.graphe["noeuds"]:
            self.choisir(("mesure", nom))
        elif len(famille.get("membres") or []) > 1:
            self.deplier_famille(kpi, ("mesure", nom))
        else:
            self.choisir(("mesures", kpi))

    def _reconstruire(self, choix=None):
        if self.constructeur is None:
            return
        self.graphe = self.constructeur(set(self.deplies)) or {}
        self.choix = None
        self._dessiner()
        self.choisir(choix if choix in self.graphe.get("noeuds", {}) else None)

    def _double(self, boite):
        n = boite.noeud
        if n["genre"] == "mesures" and len(n.get("membres") or []) > 1:
            self.deplier_famille(n["libelle"], ("mesure", n["libelle"])
                                 if n["libelle"] in n["membres"] else None)
        elif n["genre"] == "mesure":
            self.replier_famille(n.get("famille"))

    def basculer_bande(self, bande):
        """Replie une bande dépliée, déplie une bande repliée."""
        self.repliees ^= {bande}
        self._dessiner()

    def filtrer_texte(self, texte: str):
        self._texte = (texte or "").strip().lower()
        self._allumer()

    def _chaine(self) -> tuple:
        """(amont, aval) du choix, chacun vide si le sens ne le garde pas."""
        if self.choix is None:
            return set(), set()
        liens = self.graphe["liens"]
        amont = lgn.chaine_sens(liens, self.choix, amont=True) if self.sens != "aval" \
            else {self.choix}
        aval = lgn.chaine_sens(liens, self.choix, amont=False) if self.sens != "amont" \
            else {self.choix}
        return amont, aval

    def visibles(self) -> set:
        noeuds = self.graphe.get("noeuds") or {}
        vus = {n for n, x in noeuds.items() if x["utilise"] or self.cb_tout.isChecked()}
        if self.cb_chaine.isChecked() and self.choix is not None:
            amont, aval = self._chaine()
            vus &= amont | aval
        return vus

    # ---- dessin ----------------------------------------------------------------

    def _redessiner_et_ajuster(self):
        self._dessiner()
        self.ajuster(largeur_seule=True)

    def _sens_change(self):
        if self.cb_chaine.isChecked():
            self._dessiner()
        else:
            self._allumer()

    def _affichage(self, vus) -> tuple:
        """(nœuds affichés, liens affichés) : une bande repliée devient une
        seule boîte, et ses liens passent par elle."""
        noeuds = self.graphe["noeuds"]
        aff, affiches = {}, {}
        for n in vus:
            b = noeuds[n]["bande"]
            if b in self.repliees:
                d = ("bande", b)
                if d not in affiches:
                    affiches[d] = {"id": d, "genre": "bande", "bande": b,
                                   "libelle": lgn.TITRES[b], "detail": "", "page": "",
                                   "couche": noeuds[n]["couche"], "utilise": True,
                                   "membres": []}
                affiches[d]["couche"] = min(affiches[d]["couche"], noeuds[n]["couche"])
                affiches[d]["membres"].append(n)
            else:
                d = n
                affiches[d] = noeuds[n]
            aff[n] = d
        for d, x in affiches.items():
            if x["genre"] == "bande":
                x["detail"] = f"{len(x['membres'])} éléments, repliés"
        liens: dict = {}
        for a, b in self.graphe["liens"]:
            if a in aff and b in aff and aff[a] != aff[b]:
                liens.setdefault((aff[a], aff[b]), []).append((a, b))
        self._aff = aff
        return affiches, liens

    def _dessiner(self):
        self.scene.clear()
        self.boites, self.liens, self.titres = {}, [], {}
        noeuds = self.graphe.get("noeuds") or {}
        if not noeuds:
            self.lbl.setText("Rien à dessiner : le modèle n'est pas local, ou le rapport "
                             "est vide.")
            return
        vus = self.visibles()
        affiches, liens = self._affichage(vus)
        colonnes = self._ordonner(affiches, liens)
        positions = self._placer(affiches, colonnes)
        vertical = self.vertical
        for (a, b), origine in liens.items():
            trait = _Lien(self._trajet(a, b, positions), vertical)
            self.scene.addItem(trait)
            self.liens.append((a, b, trait, origine))
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-20, -10, 20, 20))
        n_vis = sum(1 for n in vus if noeuds[n]["genre"] == "visuel")
        self.lbl.setText(f"{len(vus)} éléments · {sum(len(o) for o in liens.values())} liens · "
                         f"{n_vis} visuels")
        self._allumer()

    def _trajet(self, a, b, positions) -> list:
        """Les points d'un lien en (axe principal, axe transversal) : il part du
        bord de A, traverse chaque colonne sautée par le passage le plus proche
        de la droite qui le mènerait à B, et arrive au bord de B."""
        xa, ya = positions[a]
        xb, yb = positions[b]
        if self.vertical:
            depart, arrivee, epaisseur = (ya + H, xa + L / 2), (yb, xb + L / 2), H
        else:
            depart, arrivee, epaisseur = (xa + L, ya + H / 2), (xb, yb + H / 2), L
        points = [depart]
        ia, ib = self._col_de[a], self._col_de[b]
        for k in range(ia + 1, ib):
            principal, boites = self._cols[k]
            vise = depart[1] + (arrivee[1] - depart[1]) * (k - ia) / (ib - ia)
            passage = self._passage(boites, vise)
            points += [(principal - 6, passage), (principal + epaisseur + 6, passage)]
        points.append(arrivee)
        return points

    @staticmethod
    def _passage(boites, vise) -> float:
        """Le passage d'une colonne le plus proche de `vise` : au-dessus de
        la première boîte, entre deux boîtes, ou sous la dernière."""
        if not boites:
            return vise
        boites = sorted(boites)
        passages = [boites[0][0] - ECART_Y / 2, boites[-1][1] + ECART_Y / 2]
        passages += [(boites[i][1] + boites[i + 1][0]) / 2 for i in range(len(boites) - 1)]
        return min(passages, key=lambda g: abs(g - vise))

    def _placer(self, affiches, colonnes) -> dict:
        """Pose les boîtes et les titres ; {id affiché: (x, y)}. Retient, pour
        le tracé des liens, la colonne de chaque boîte et la place des boîtes
        de chaque colonne."""
        vertical = self.vertical
        positions = {}
        faites = set()
        self._col_de, self._cols = {}, {}
        for i, couche in enumerate(sorted(colonnes)):
            self._cols[i] = (0, [])         # (début sur l'axe principal, [boîtes])
            if vertical:
                x, y = MARGE_TITRE, i * (H + ECART_RANG) + 18
            else:
                x, y = i * (L + ECART_X), HAUT
            page = None
            for d in colonnes[couche]:
                n = affiches[d]
                if n["bande"] not in faites:
                    faites.add(n["bande"])
                    if vertical:
                        self._titre(n["bande"], 0, y + H / 2 - 9)
                    else:
                        self._titre(n["bande"], x, 0)
                if n["genre"] == "visuel" and n["page"] != page:
                    # les visuels d'une même page ensemble, sous son nom
                    page = n["page"]
                    t = QGraphicsSimpleTextItem(page)
                    t.setBrush(QBrush(QColor(TEXT_DIM)))
                    if vertical:
                        if x > MARGE_TITRE:
                            x += 16
                        t.setPos(x + 2, y - 18)
                    else:
                        if y > HAUT:
                            y += 10
                        t.setPos(x + 2, y)
                        y += 18
                    self.scene.addItem(t)
                b = _Boite(n)
                b.setPos(x, y)
                self.scene.addItem(b)
                self.boites[d] = b
                positions[d] = (x, y)
                self._col_de[d] = i
                self._cols[i] = ((y if vertical else x), self._cols[i][1]
                                 + [(x, x + L) if vertical else (y, y + H)])
                if vertical:
                    x += L + ECART_Y
                else:
                    y += H + ECART_Y
        return positions

    def _titre(self, bande, x, y):
        replie = bande in self.repliees
        t = _Titre(bande, ("▸ " if replie else "▾ ") + lgn.TITRES[bande])
        police = QFont(TITRE_POLICE)
        police.setPointSize(10)
        t.setFont(police)
        t.setBrush(QBrush(QColor(TEXT_DIM if replie else ACCENT)))
        t.setPos(x, y)
        self.scene.addItem(t)
        self.titres[bande] = t

    def _ordonner(self, affiches, liens) -> dict:
        """{couche: [ids]} dans un ordre qui croise peu de liens : chaque boîte
        se place à la hauteur moyenne de ses voisines (méthode du barycentre),
        en allant puis en revenant. Les visuels restent groupés par page."""
        colonnes: dict = {}
        for d, x in affiches.items():
            colonnes.setdefault(x["couche"], []).append(d)
        ordre_page = {}                 # l'ordre des pages du rapport
        for x in (self.graphe.get("noeuds") or {}).values():
            if x["genre"] == "visuel":
                ordre_page.setdefault(x["page"], len(ordre_page))
        for c in colonnes:
            colonnes[c].sort(key=lambda d: (affiches[d]["genre"],
                                            str(affiches[d].get("famille", "")).lower(),
                                            affiches[d]["libelle"].lower()))
        amont: dict = {}
        aval: dict = {}
        for a, b in liens:
            aval.setdefault(a, []).append(b)
            amont.setdefault(b, []).append(a)

        def rang(c):
            return {d: (i + 0.5) / len(colonnes[c]) for i, d in enumerate(colonnes[c])}

        pos: dict = {}
        for c in colonnes:
            pos.update(rang(c))
        cles = sorted(colonnes)
        # aller (d'après l'amont), retour (d'après l'aval), deux fois
        for sens, voisins in ((cles, amont), (cles[::-1], aval)) * 2:
            for c in sens:
                def cle(d):
                    vs = [pos[x] for x in voisins.get(d, []) if x in pos]
                    moy = sum(vs) / len(vs) if vs else pos[d]
                    groupe = ordre_page.get(affiches[d]["page"], 0) \
                        if affiches[d]["genre"] == "visuel" else 0
                    return (groupe, moy)
                colonnes[c].sort(key=cle)
                pos.update(rang(c))
        return colonnes

    # ---- choix et surlignage -------------------------------------------------

    def _clic(self, cible):
        if isinstance(cible, _Titre):
            self.basculer_bande(cible.bande)
        elif isinstance(cible, _Boite) and cible.noeud["genre"] == "bande":
            self.basculer_bande(cible.noeud["bande"])
        else:
            self.choisir(cible.noeud["id"] if cible is not None else None)

    def _allumer(self):
        """L'amont du choix en vert, son aval en orange, le reste éteint ; sans
        choix, le texte du filtre éteint ce qui ne le contient pas."""
        noeuds = self.graphe.get("noeuds") or {}
        if self.choix is not None:
            amont, aval = self._chaine()
            dedans = amont | aval
        elif self._texte:
            amont = aval = set()
            dedans = {n for n, x in noeuds.items()
                      if self._texte in (x["libelle"] + " " + str(x["detail"])).lower()}
        else:
            amont = aval = set()
            dedans = None
        allumes = None if dedans is None else {self._aff[n] for n in dedans if n in self._aff}
        choisie = self._aff.get(self.choix)
        for d, b in self.boites.items():
            b.choisie = d == choisie
            b.setOpacity(1 if allumes is None or d in allumes else ETEINT)
            b.update()
        for a, b, trait, origine in self.liens:
            if self.choix is None:
                trait.colorer(None, eteint=allumes is not None
                              and not (a in allumes and b in allumes))
                continue
            if any(x in amont and y in amont for x, y in origine):
                trait.colorer(AMONT_C)
            elif any(x in aval and y in aval for x, y in origine):
                trait.colorer(AVAL_C)
            else:
                trait.colorer(None, eteint=True)

    def ajuster(self, largeur_seule=False):
        """Tout le graphe dans la vue ; ou, à l'ouverture, depuis le coin haut
        gauche sans descendre sous une taille lisible."""
        rect = self.scene.sceneRect()
        if rect.isEmpty():
            return
        self.vue.resetTransform()
        if largeur_seule:
            f = min(1.0, max(0.85, self.vue.viewport().width() / rect.width()))
            self.vue.scale(f, f)
            self.vue.horizontalScrollBar().setValue(self.vue.horizontalScrollBar().minimum())
            self.vue.verticalScrollBar().setValue(self.vue.verticalScrollBar().minimum())
        else:
            self.vue.fitInView(rect, Qt.KeepAspectRatio)

    # ---- export ----------------------------------------------------------------

    def lignes_export(self) -> list:
        if self.choix is None:
            return []
        return lgn.lignes_export(self.graphe, self.choix, self.sens)

    def _exporter(self):
        lignes = self.lignes_export()
        if not lignes:
            return
        nom = self.graphe["noeuds"][self.choix]["libelle"]
        propre = re.sub(r"[^\w\- ]+", "_", nom).strip() or "chaine"
        defaut = str(Path(self.dossier or Path.home()) / f"lignage_{propre}.csv")
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter la chaîne", defaut,
                                                "CSV (*.csv)")
        if not chemin:
            return
        try:
            lgn.ecrire_csv(lignes, chemin)
        except OSError as e:
            self.journal.erreur(f"Lignage : export impossible, {e}")
            return
        self.journal.info(f"Lignage : chaîne de « {nom} » exportée, {len(lignes)} lignes, "
                          f"vers {chemin}")
