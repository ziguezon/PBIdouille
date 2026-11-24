# -*- coding: utf-8 -*-
"""Vue « Lignage » de la Radiographie : tout le rapport, de la source au visuel.

Un graphe (moteurs/lignage.py) en bandes : sources, requêtes Power Query,
tables calculées, mesures par famille, paramètres de champ, filtres et
segments, visuels rangés par page, et les pages. De gauche à droite, ou de
haut en bas.

Le menu « Colonnes » MASQUE des bandes entières : leurs boîtes disparaissent
et les liens passent à travers elles, de sorte que « Sources » et « Visuels »
seuls montrent quelle source mène à quel visuel. Le menu « Pages » ne garde
que ce qui mène aux pages cochées.

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

import math
import re
from pathlib import Path

from qtpy.QtCore import QPointF, QRectF, Qt, Signal
from qtpy.QtGui import (QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath,
                        QPainterPathStroker, QPen)
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
    QMenu,
    QPushButton,
    QToolButton,
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
           "visuel": TEXT_DIM, "page": "#5EEAD4"}
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
                tip += f"\nBase {noeud.get('famille', '')}\n\nDouble-clic : replier la base."
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


class _Lien:
    """Un lien entre deux boîtes, donné par ses points en (axe principal, axe
    transversal) : le départ, puis pour chaque colonne qu'il saute une entrée
    et une sortie dans un passage entre deux boîtes, puis l'arrivée. Entre deux
    colonnes, une courbe ; à travers une colonne sautée, un trait droit dans le
    passage : le lien contourne les boîtes au lieu de les traverser.

    Il ne se dessine pas lui-même : ses morceaux sont des _Troncon, que
    partagent les liens qui font le même trajet."""

    def __init__(self, points, libelle=""):
        self.points = points
        self.libelle = libelle
        self.couleur = None             # celle de la chaîne, ou None
        self.eteint = False

    def morceaux(self) -> list:
        """[(clé, (m0, c0), (m1, c1), droit)] : deux liens qui ont le même
        morceau ont la même clé."""
        out = []
        for i in range(1, len(self.points)):
            p0, p1 = self.points[i - 1], self.points[i]
            droit = i % 2 == 0          # d'une entrée à sa sortie : tout droit
            cle = tuple(round(v, 1) for v in (*p0, *p1)) + (droit,)
            out.append((cle, p0, p1, droit))
        return out

    def colorer(self, couleur, eteint=False):
        """`couleur` : celle de la chaîne, ou None pour un lien ordinaire."""
        self.couleur, self.eteint = couleur, eteint


def intensite(n: int) -> float:
    """0 pour un lien seul, 1 à partir de 8 liens sur le même trajet : un
    écart qui se voit entre 1 et 2, et encore entre 4 et 8."""
    return min(1.0, math.log2(max(n, 1)) / 3)


def _melange(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t),
                  round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t))


def teinte_chaine(couleur: str, t: float) -> QColor:
    """La couleur d'un trait de la chaîne (vert ou orange) selon son
    intensité `t` : un lien seul est la couleur un peu assombrie vers le fond,
    un tronc de 8 liens et plus, la couleur éclaircie vers le blanc. Le même
    dégradé que les traits ordinaires, dans la teinte de la chaîne."""
    sombre, clair = _melange(SURFACE, couleur, 0.6), _melange(couleur, "#FFFFFF", 0.35)
    if t <= 0.5:
        return _melange(sombre.name(), couleur, t / 0.5)
    return _melange(couleur, clair.name(), (t - 0.5) / 0.5)


class _Troncon(QGraphicsPathItem):
    """Un morceau de trajet, dessiné UNE fois pour tous les liens qui le
    suivent. Plus il en porte, plus il est clair : un tronc où cinq liens
    voyagent ensemble se voit plus qu'un lien seul. L'épaisseur, elle, ne
    change pas."""

    def __init__(self, p0, p1, droit, vertical, liens):
        super().__init__()
        self.liens = liens

        def pt(m, c):
            return QPointF(c, m) if vertical else QPointF(m, c)

        (m0, c0), (m1, c1) = p0, p1
        chemin = QPainterPath(pt(m0, c0))
        if droit:
            chemin.lineTo(pt(m1, c1))
        else:
            d = max((m1 - m0) / 2, 12)
            chemin.cubicTo(pt(m0 + d, c0), pt(m1 - d, c1), pt(m1, c1))
        self.setPath(chemin)
        noms = sorted({l.libelle for l in liens}, key=str.lower)
        if len(noms) > 1:
            self.setToolTip(f"{len(noms)} liens sur ce trajet :\n"
                            + "\n".join(noms[:12])
                            + (f"\net {len(noms) - 12} autres" if len(noms) > 12 else ""))
        self.colorer()

    def shape(self):
        # la courbe seule, pas l'aire qu'elle ferme : l'infobulle suit le trait
        bord = QPainterPathStroker()
        bord.setWidth(8)
        return bord.createStroke(self.path())

    def colorer(self):
        """D'après ses liens : la couleur de la chaîne si l'un d'eux en est,
        vert avant orange ; l'intensité, d'après combien la partagent."""
        for couleur in (AMONT_C, AVAL_C):
            n = sum(1 for l in self.liens if l.couleur == couleur)
            if n:
                self.setPen(QPen(teinte_chaine(couleur, intensite(n)), 2))
                self.setZValue(1 + intensite(n))
                return
        vifs = [l for l in self.liens if not l.eteint]
        t = intensite(len(vifs) or len(self.liens))
        c = _melange(TRAIT, TEXT_DIM, 0.6 * t)
        if not vifs:
            c.setAlphaF(0.25)
        # la même épaisseur partout : un trait qui s'épaississait d'un coup là
        # où les liens se rejoignent faisait une marche. Seule la clarté dit
        # combien de liens il porte.
        self.setPen(QPen(c, 1.2))
        self.setZValue(-1 + t / 2)


def _echapper(texte: str) -> str:
    return (str(texte).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class _MenuCoches(QMenu):
    """Un menu de cases qui reste ouvert quand on en coche une : on en
    décoche souvent plusieurs d'affilée."""

    def mouseReleaseEvent(self, event):
        a = self.activeAction()
        if a is not None and a.isCheckable() and a.isEnabled():
            a.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)


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
        self.masquees: set = set()      # les bandes masquées : leurs liens passent à travers
        self.pages_choisies = None      # None : toutes ; sinon les ids des pages gardées
        self.deplies: set = set()       # les familles dépliées en mesures
        self.constructeur = None        # deplies -> graphe (lignage.construire)
        self.dossier = None             # où proposer l'export
        self.boites: dict = {}          # id affiché -> _Boite
        self.liens: list = []           # [(A, B, _Lien, [(a, b) d'origine])]
        self.troncons: list = []        # [_Troncon] : les morceaux dessinés
        self.titres: dict = {}          # bande -> _Titre
        self._aff: dict = {}            # id d'origine -> id affiché
        self._texte = ""

        # UNE rangée : ce qu'on montre (colonnes, pages), la chaîne (sens,
        # chaîne seule), puis à droite l'affichage et les actions. Les comptes
        # vont sous le graphe. Il y en avait deux, sous la barre du filtre et
        # les onglets : quatre étages de boutons avant de voir le graphe.
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        haut = QHBoxLayout()
        haut.setSpacing(6)
        self.puces_sens = Puces("")
        self.puces_sens.remplir(SENS)
        self.puces_sens.change.connect(self._sens_change)
        b_ajuster = QPushButton("Ajuster")
        b_ajuster.setToolTip("Montre tout le graphe. Ctrl + molette zoome, glisser déplace.")
        b_ajuster.clicked.connect(self.ajuster)
        self.btn_export = QPushButton("Exporter…")
        self.btn_export.setToolTip("Écrit en CSV la chaîne de la boîte choisie, dans le sens "
                                   "choisi : une ligne par élément (par mesure pour une "
                                   "base), une colonne disant l'amont ou l'aval.")
        self.btn_export.clicked.connect(self._exporter)
        self.btn_export.setEnabled(False)

        self.btn_colonnes = QToolButton()
        self.btn_colonnes.setPopupMode(QToolButton.InstantPopup)
        self.btn_colonnes.setToolTip("Les colonnes à montrer. Une colonne masquée disparaît, "
                                     "et ses liens passent à travers elle : Sources et "
                                     "Visuels seuls montrent quelle source mène à quel visuel.")
        self.menu_colonnes = _MenuCoches(self.btn_colonnes)
        self.btn_colonnes.setMenu(self.menu_colonnes)
        self.btn_pages = QToolButton()
        self.btn_pages.setPopupMode(QToolButton.InstantPopup)
        self.btn_pages.setToolTip("Les pages à garder : seul ce qui mène à leurs visuels "
                                  "reste dans le graphe.")
        self.menu_pages = _MenuCoches(self.btn_pages)
        self.btn_pages.setMenu(self.menu_pages)
        # l'affichage : la disposition, et ce qui ne mène à aucun visuel
        self.btn_affichage = QToolButton()
        self.btn_affichage.setText("Affichage  ▾")
        self.btn_affichage.setPopupMode(QToolButton.InstantPopup)
        self.btn_affichage.setToolTip("La disposition du graphe, et ce qu'il montre en plus.")
        menu = QMenu(self.btn_affichage)
        self._act_dispo = {}
        for cle, libelle, aide in DISPOSITIONS:
            a = menu.addAction(libelle)
            a.setCheckable(True)
            a.setToolTip(aide)
            a.triggered.connect(lambda *_, cle=cle: self.disposer(cle))
            self._act_dispo[cle] = a
        self._act_dispo["horizontal"].setChecked(True)
        menu.addSeparator()
        # garde le nom de la case qu'il était : il en a l'usage (toggled, setText)
        self.cb_tout = menu.addAction("Montrer aussi ce qui ne mène à aucun visuel")
        self.cb_tout.setCheckable(True)
        self.cb_tout.toggled.connect(lambda *_: self._dessiner())
        self.btn_affichage.setMenu(menu)
        for b in (self.btn_colonnes, self.btn_pages, self.btn_affichage):
            # la flèche du style rognait le texte : elle est dans le texte
            b.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        self.cb_chaine = QCheckBox("Chaîne seule")
        self.cb_chaine.setToolTip("Redessine le graphe avec la chaîne de la boîte choisie, "
                                  "dans le sens choisi, rien d'autre.")
        self.cb_chaine.toggled.connect(lambda *_: self._dessiner())
        self.cb_chaine.setEnabled(False)

        haut.addWidget(self.btn_colonnes)
        haut.addWidget(self.btn_pages)
        haut.addSpacing(14)
        haut.addWidget(self.puces_sens)
        haut.addWidget(self.cb_chaine)
        haut.addStretch(1)
        haut.addWidget(self.btn_affichage)
        haut.addWidget(b_ajuster)
        haut.addWidget(self.btn_export)
        v.addLayout(haut)

        self.scene = QGraphicsScene(self)
        self.vue = _Vue(self.scene)
        self.vue.clic.connect(self._clic)
        self.vue.double.connect(self._double)
        v.addWidget(self.vue, 1)
        # sous le graphe : ce qu'il montre, ou les dépendances de la boîte choisie
        self.lbl = QLabel("")
        self.lbl.setStyleSheet(f"color:{TEXT_DIM};")
        self.lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.lbl)
        self._comptes_txt = ""
        self._remplir_menus()

    # ---- données ---------------------------------------------------------------

    @property
    def sens(self) -> str:
        return self.puces_sens.valeur() or "deux"

    @property
    def vertical(self) -> bool:
        return self._act_dispo["vertical"].isChecked()

    def disposer(self, cle):
        """« horizontal » (gauche -> droite) ou « vertical » (haut -> bas)."""
        for c, a in self._act_dispo.items():
            a.setChecked(c == cle)
        self._redessiner_et_ajuster()

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
        self.pages_choisies = None
        self._remplir_menus()
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
        self._ecrire_lbl()
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
        self._remplir_menus()
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
        if self.pages_choisies is not None:
            vus &= self._pour_pages(self.pages_choisies)
        if self.cb_chaine.isChecked() and self.choix is not None:
            amont, aval = self._chaine()
            vus &= amont | aval
        return vus

    # ---- colonnes masquées, pages choisies ---------------------------------------

    def _pour_pages(self, pids) -> set:
        """Ce que montrent ces pages : leur amont, de la source au visuel."""
        noeuds = self.graphe["noeuds"]
        gardes = set()
        for pid in pids:
            if ("page", pid) in noeuds:
                gardes |= lgn.chaine_sens(self.graphe["liens"], ("page", pid), amont=True)
        return gardes

    def _pages(self) -> list:
        """[(id, nom)] des pages du graphe, dans l'ordre du rapport."""
        return [(n[1], x["libelle"]) for n, x in (self.graphe.get("noeuds") or {}).items()
                if x["genre"] == "page"]

    def _remplir_menus(self):
        """Refait les deux menus d'après le graphe. Jamais depuis un de leurs
        signaux : vider un menu détruirait l'action qui l'émet ; les cases se
        remettent à jour par _synchroniser_menus."""
        noeuds = self.graphe.get("noeuds") or {}
        presentes = [b for b in lgn.BANDES if any(x["bande"] == b for x in noeuds.values())]
        self.menu_colonnes.clear()
        self._act_bandes = {}
        tout = self.menu_colonnes.addAction("Toutes les colonnes")
        tout.triggered.connect(lambda *_: self.masquer_bandes(set()))
        self.menu_colonnes.addSeparator()
        for b in presentes:
            a = self.menu_colonnes.addAction(lgn.TITRES[b])
            a.setCheckable(True)
            a.toggled.connect(lambda oui, b=b: self.masquer_bandes(
                self.masquees - {b} if oui else self.masquees | {b}))
            self._act_bandes[b] = a
        pages = self._pages()
        self.menu_pages.clear()
        self._act_pages = {}
        tout = self.menu_pages.addAction("Toutes les pages")
        tout.triggered.connect(lambda *_: self.choisir_pages(None))
        self.menu_pages.addSeparator()
        for pid, nom in pages:
            a = self.menu_pages.addAction(nom)
            a.setCheckable(True)
            a.toggled.connect(lambda oui, pid=pid: self._cocher_page(pid, oui))
            self._act_pages[pid] = a
        self.btn_pages.setEnabled(bool(pages))
        self._synchroniser_menus()

    def _synchroniser_menus(self):
        """Les cases et le texte des deux boutons, d'après l'état."""
        for actions, coche in ((getattr(self, "_act_bandes", {}),
                                lambda b: b not in self.masquees),
                               (getattr(self, "_act_pages", {}),
                                lambda p: self.pages_choisies is None
                                or p in self.pages_choisies)):
            for cle, a in actions.items():
                a.blockSignals(True)
                a.setChecked(coche(cle))
                a.blockSignals(False)
        noeuds = self.graphe.get("noeuds") or {}
        presentes = {x["bande"] for x in noeuds.values()}
        n_vues = len(presentes - self.masquees)
        self.btn_colonnes.setText(("Colonnes" if n_vues == len(presentes)
                                   else f"Colonnes : {n_vues} sur {len(presentes)}") + "  ▾")
        n_pages = len(self._pages())
        self.btn_pages.setText(("Pages : toutes" if self.pages_choisies is None
                                else f"Pages : {len(self.pages_choisies)} sur {n_pages}")
                               + "  ▾")

    def masquer_bandes(self, bandes):
        """Masque ces bandes (et montre les autres) : leurs liens passent à
        travers elles."""
        self.masquees = set(bandes)
        self._synchroniser_menus()
        self._dessiner()

    def _cocher_page(self, pid, oui):
        toutes = [p for p, _n in self._pages()]
        gardes = set(toutes) if self.pages_choisies is None else set(self.pages_choisies)
        gardes = gardes | {pid} if oui else gardes - {pid}
        self.choisir_pages(None if gardes >= set(toutes) else gardes)

    def choisir_pages(self, pages):
        """Ne garde que ce qui mène à ces pages (des ids) ; None : toutes."""
        self.pages_choisies = None if pages is None else set(pages)
        self._synchroniser_menus()
        self._dessiner()

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
        montres = {n for n in vus if noeuds[n]["bande"] not in self.masquees}
        for n in montres:
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
        for a, b in self._liens_montres(vus, montres):
            if aff[a] != aff[b]:
                liens.setdefault((aff[a], aff[b]), []).append((a, b))
        self._aff = aff
        return affiches, liens

    def _liens_montres(self, vus, montres) -> list:
        """Les liens entre boîtes montrées. Un lien qui entre dans une bande
        masquée en ressort vers chaque boîte montrée qu'il atteint à travers
        elle : Source -> Requête -> Table -> Mesure devient Source -> Mesure
        quand Power Query et les tables calculées sont masquées."""
        liens = self.graphe["liens"]
        if montres == vus:
            return [(a, b) for a, b in liens if a in vus and b in vus]
        aval: dict = {}
        for a, b in liens:
            if a in vus and b in vus:
                aval.setdefault(a, []).append(b)
        out = []
        for a in montres:
            vus_ici, pile = set(), list(aval.get(a, []))
            while pile:
                x = pile.pop()
                if x in vus_ici:
                    continue
                vus_ici.add(x)
                if x in montres:
                    out.append((a, x))
                else:
                    pile.extend(aval.get(x, []))
        return out

    def _dessiner(self):
        self.scene.clear()
        self.boites, self.liens, self.titres, self.troncons = {}, [], {}, []
        noeuds = self.graphe.get("noeuds") or {}
        if not noeuds:
            self._comptes_txt = ("Rien à dessiner : le modèle n'est pas local, ou le rapport "
                                 "est vide.")
            self.lbl.setText(self._comptes_txt)
            return
        vus = self.visibles()
        affiches, liens = self._affichage(vus)
        if not affiches:
            self._comptes_txt = ("Rien à montrer : toutes les colonnes sont masquées."
                                 if self.masquees else "Rien à montrer avec ces pages.")
            self._ecrire_lbl()
            return
        colonnes = self._ordonner(affiches, liens)
        positions = self._placer(affiches, colonnes)
        vertical = self.vertical
        self._troncs = self._calculer_troncs(liens, positions)
        morceaux: dict = {}
        for (a, b), origine in liens.items():
            trait = _Lien(self._trajet(a, b, positions),
                          f"{affiches[a]['libelle']} → {affiches[b]['libelle']}")
            self.liens.append((a, b, trait, origine))
            for cle, p0, p1, droit in trait.morceaux():
                morceaux.setdefault(cle, (p0, p1, droit, []))[3].append(trait)
        for p0, p1, droit, portes in morceaux.values():
            troncon = _Troncon(p0, p1, droit, vertical, portes)
            self.scene.addItem(troncon)
            self.troncons.append(troncon)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-20, -10, 20, 20))
        montres = [n for n in vus if n in self._aff]
        n_vis = sum(1 for n in montres if noeuds[n]["genre"] == "visuel")
        self._comptes_txt = (f"{len(montres)} éléments · "
                             f"{sum(len(o) for o in liens.values())} liens"
                             + (f" · {n_vis} visuels" if n_vis else ""))
        self._ecrire_lbl()
        self._allumer()

    def _ecrire_lbl(self):
        """Sous le graphe : ce qu'il montre ; avec un choix, combien la boîte
        a de dépendances, directes et en tout, de chaque côté."""
        texte = self._comptes_txt
        if self.choix is not None:
            c = lgn.comptes(self.graphe["liens"], self.choix)
            nom = self.graphe["noeuds"][self.choix]["libelle"]

            def cote(x):
                return (f"{x['directs']} direct{'s' if x['directs'] > 1 else ''}, "
                        f"{x['total']} en tout")
            texte = (f"<b>{_echapper(nom)}</b> · vient de {cote(c['amont'])} · "
                     f"mène à {cote(c['aval'])}"
                     + (f"<span style='color:{TEXT_MUTED}'> · graphe : {texte}</span>"
                        if texte else ""))
        self.lbl.setText(texte)

    def _depart(self, a, positions) -> tuple:
        """Le point d'où partent les liens de A, en (axe principal, transversal)."""
        x, y = positions[a]
        return (y + H, x + L / 2) if self.vertical else (x + L, y + H / 2)

    def _arrivee(self, b, positions) -> tuple:
        """Le point où arrivent les liens de B, en (axe principal, transversal)."""
        x, y = positions[b]
        return (y, x + L / 2) if self.vertical else (x, y + H / 2)

    def _calculer_troncs(self, liens, positions) -> dict:
        """{cible: {colonne: passage}} : les liens qui vont vers une même boîte
        lointaine se rejoignent dès la sortie de leur colonne et voyagent
        ensemble jusqu'à elle, en un seul tronc. Sans lui, chaque lien visait la
        cible depuis sa propre hauteur, et deux liens voisins ne se
        rejoignaient qu'à l'arrivée, après un long trajet côte à côte.

        Le tronc part de la hauteur moyenne de ses sources, depuis la colonne
        de la plus lointaine, et passe chaque colonne par le passage le plus
        proche de la droite qui le mène à la cible. Une source plus proche le
        rejoint à la colonne qui suit la sienne."""
        sources: dict = {}
        for a, b in liens:
            if self._col_de[b] - self._col_de[a] > 1:
                sources.setdefault(b, []).append(a)
        troncs = {}
        for b, venues in sources.items():
            ia, ib = min(self._col_de[a] for a in venues), self._col_de[b]
            depart = sum(self._depart(a, positions)[1] for a in venues) / len(venues)
            arrivee = self._arrivee(b, positions)[1]
            troncs[b] = {k: self._passage(self._cols[k][1],
                                          depart + (arrivee - depart) * (k - ia) / (ib - ia))
                         for k in range(ia + 1, ib)}
        return troncs

    def _trajet(self, a, b, positions) -> list:
        """Les points d'un lien en (axe principal, axe transversal) : il part du
        bord de A, traverse chaque colonne sautée par le passage du tronc de B
        (voir _calculer_troncs), et arrive au bord de B."""
        depart, arrivee = self._depart(a, positions), self._arrivee(b, positions)
        epaisseur = H if self.vertical else L
        points = [depart]
        ia, ib = self._col_de[a], self._col_de[b]
        tronc = (getattr(self, "_troncs", None) or {}).get(b) or {}
        for k in range(ia + 1, ib):
            principal, boites = self._cols[k]
            passage = tronc.get(k)
            if passage is None:
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
                        if affiches[d]["genre"] in ("visuel", "page") else 0
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
        for troncon in self.troncons:
            troncon.colorer()

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
