# -*- coding: utf-8 -*-
"""Onglet « Wireframe » : plan des pages du rapport — chaque visuel est un
rectangle positionné/dimensionné comme dans Power BI (les visual.json portent
x/y/z/largeur/hauteur, relatifs au groupe parent → report_reader calcule
l'absolu).

Édition par NIVEAU ACTIF (« scope ») : à tout moment on agit sur les enfants
DIRECTS d'un conteneur (la page, ou un groupe dans lequel on est entré par
double-clic / arbre). Ces enfants — visuels ET groupes — se réordonnent par
glisser (reflow bord à bord) ; les groupes se déplacent en bloc avec tout leur
sous-arbre (seule la position du groupe est réécrite : les enfants sont
stockés RELATIFS au parent). Le reste de la page est grisé et inerte, un fil
d'Ariane montre où l'on est, Échap remonte d'un niveau.

Panneau « Gabarits » : un PBIP gabarit fournit des modèles nommés (groupes
racine de ses pages) importables dans la page courante — voir
core/template_import.py."""

from __future__ import annotations

import json
import os
from pathlib import Path

from qtpy.QtCore import QPointF, QRectF, Qt, QTimer
from qtpy.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QPen
from qtpy.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import alignement, edition, report_reader, template_import
from core.journal import Journal
from core.project import Project, ecrire_reglage, lire_reglage, reglages
from core.theme import (ACCENT, ACCENT_DIM, BG_DARKEST, BG_WINDOW, BORDER,
                        SURFACE, TEXT, TEXT_DIM, TEXT_MUTED,
                        bouton_en_attente, checkable_list_stylesheet,
                        police_code)

import backup_restore as br
import generate_measures as gm


class WireItem(QGraphicsRectItem):
    """Rectangle d'élément (visuel OU groupe). L'interactivité est accordée
    par WireframeTab._apply_scope selon le niveau actif — pas par la classe.
    Au relâchement, si réellement déplacé, notifie la tab (réordonner +
    reflow) ; un groupe actif entraîne son sous-arbre EN DIRECT pendant le
    drag (itemChange), sinon le bloc se « déchirerait » visuellement.

    REDIMENSIONNEMENT : presser dans la BANDE DE BORD d'un visuel actif
    (RESIZE_EDGE px écran, curseurs ↔/↕/⤡ au survol) déplace ce(s) bord(s) au
    lieu de déplacer l'élément — marche du premier geste, même non
    sélectionné. Les petites poignées vertes sont de purs indicateurs."""

    RESIZE_EDGE = 8.0        # bande de saisie des bords, en pixels ÉCRAN

    def __init__(self, w, h, vid, tab, is_group):
        super().__init__(0, 0, w, h)
        self._vid = vid
        self._tab = tab
        self._is_group = is_group
        self._press = None
        self._last_pos = QPointF()
        self._resizing = None            # (hx, hy) pendant un resize par bord
        self.setAcceptHoverEvents(True)

    def setPos(self, *args):                    # appels PYTHON (programmatiques)
        super().setPos(*args)
        self._last_pos = self.pos()

    def _edge_at(self, p):
        """Zone de bord sous le point (coordonnées item) -> (hx, hy) dans
        {-1,0,1}² ; (0,0) = cœur (déplacement). Inactifs : jamais. Les groupes
        se redimensionnent aussi (leur contenu est rééchelonné — ScaleMode)."""
        if not (self.flags() & QGraphicsItem.ItemIsMovable):
            return (0, 0)
        scale = self._tab.view.transform().m11() or 1.0
        t = self.RESIZE_EDGE / scale
        w, h = self.rect().width(), self.rect().height()
        t = min(t, w / 3, h / 3)         # petit visuel : garder un cœur déplaçable
        hx = -1 if p.x() <= t else (1 if p.x() >= w - t else 0)
        hy = -1 if p.y() <= t else (1 if p.y() >= h - t else 0)
        return hx, hy

    def hoverMoveEvent(self, e):
        hx, hy = self._edge_at(e.pos())
        if hx and hy:
            self.setCursor(Qt.SizeFDiagCursor if hx == hy else Qt.SizeBDiagCursor)
        elif hx:
            self.setCursor(Qt.SizeHorCursor)
        elif hy:
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(e)

    def hoverLeaveEvent(self, e):
        self.unsetCursor()
        super().hoverLeaveEvent(e)

    def itemChange(self, change, value):
        # ne fire que si ItemSendsGeometryChanges (éléments du niveau actif)
        if (change == QGraphicsItem.ItemPositionChange
                and self._press is not None and not self._tab._applying):
            # drag interactif : l'élément reste DANS la page (clamp en direct)
            value = self._tab._clamp_pos_to_page(self._vid, value)
        if change == QGraphicsItem.ItemPositionHasChanged:
            if self._is_group and not self._tab._applying:
                delta = value - self._last_pos
                self._last_pos = QPointF(value)
                if delta.x() or delta.y():
                    self._tab._shift_descendants_visual(
                        self._vid, delta.x(), delta.y())
            else:
                self._last_pos = QPointF(value)
            if not self._tab._applying:
                self._tab._follow_item_grips(self._vid)   # poignées pendant le drag
        return super().itemChange(change, value)

    def mousePressEvent(self, e):
        hx, hy = self._edge_at(e.pos())
        if (hx or hy) and e.button() == Qt.LeftButton:
            self._tab._push_undo_geom()                     # état AVANT le geste
            self._resizing = (hx, hy)
            self._tab._select(self._vid, from_tree=False)   # resize => sélection
            e.accept()                   # pas de super : pas de drag-déplacement
            return
        self._press = self.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._resizing:
            hx, hy = self._resizing
            self._tab._resize_edge_to(self._vid, hx, hy, e.scenePos())
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._resizing:
            self._resizing = None
            self._tab._grip_released()
            e.accept()
            return
        super().mouseReleaseEvent(e)
        if self._press is None:
            return
        moved = (self.pos() - self._press).manhattanLength()
        self._press = None
        if moved > 2:
            self._tab._on_item_moved(self._vid)
        elif moved:
            self._tab._restore_item(self._vid)   # micro-jitter : resnap


class DividerHandle(QGraphicsRectItem):
    """Poignée d'une LIGNE-FRONTIÈRE partagée : une arête où des éléments
    « avant » (à gauche / au-dessus) rencontrent des éléments « après » (à
    droite / en dessous). La glisser déplace CETTE arête pour TOUS les éléments
    qui la bordent d'un coup (donc une arête de groupe partagée avec plusieurs
    visuels reste une seule ligne droite). `line` = dict {vertical, before:[ids],
    after:[ids]}. Déplaçable sur un seul axe (clamp dans itemChange)."""

    THICK = 6

    def __init__(self, tab, line):
        super().__init__()
        self._tab = tab
        self.line = line
        self.vertical = line["vertical"]
        self._ready = False
        self.setCursor(Qt.SplitHCursor if self.vertical else Qt.SplitVCursor)
        self.setBrush(QBrush(QColor(ACCENT)))
        self.setPen(QPen(QColor(ACCENT)))
        self.setZValue(2_000_000)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._ready:
            return self._tab._divider_moving(self, value)
        return super().itemChange(change, value)

    def mousePressEvent(self, e):
        self._tab._push_undo_geom()      # état AVANT le glisser de bordure
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        # reconstruire les poignées APRÈS l'événement (se supprimer soi-même
        # dans son propre handler ferait planter Qt)
        QTimer.singleShot(0, self._tab._divider_released)


class ResizeGrip(QGraphicsRectItem):
    """INDICATEUR de redimensionnement (coins + côtés de la sélection) —
    purement visuel : la saisie se fait sur la bande de bord de l'élément
    lui-même (WireItem, curseurs au survol). Clics traversants, taille
    constante à l'écran (ItemIgnoresTransformations)."""

    SIZE = 9

    def __init__(self, hx, hy):
        s = self.SIZE
        super().__init__(-s / 2, -s / 2, s, s)
        self._hx = hx          # -1 = bord gauche, 0 = milieu, 1 = bord droit
        self._hy = hy
        self.setBrush(QBrush(QColor(ACCENT)))
        self.setPen(QPen(QColor(BG_DARKEST)))
        self.setZValue(2_100_000)               # au-dessus des diviseurs
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.NoButton)


class WireframeView(QGraphicsView):
    """Vue qui garde la page entière visible (fit au resize). Double-clic :
    entrer dans un groupe (ou remonter depuis le fond) ; Échap : remonter."""

    def __init__(self, scene, tab):
        super().__init__(scene)
        self._tab = tab
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.TextAntialiasing)
        self.setBackgroundBrush(QBrush(QColor(BG_DARKEST)))
        self.setFocusPolicy(Qt.StrongFocus)      # sinon Échap muet après un clic bouton
        # lasso depuis le fond (les items gardent leurs propres drags) ;
        # Ctrl+clic ajoute/retire de la sélection -> bouton « Grouper »
        self.setDragMode(QGraphicsView.RubberBandDrag)

    def refit(self):
        rect = self.scene().sceneRect()
        if not rect.isEmpty():
            self.fitInView(rect.adjusted(-14, -14, 14, 14), Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._tab._scope_up()
            e.accept()
            return
        if e.matches(QKeySequence.Undo):     # Ctrl+Z
            self._tab._undo_last()
            e.accept()
            return
        super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        pos = self.mapToScene(e.pos())
        items = self.scene().items(pos)
        if items and isinstance(items[0], DividerHandle):
            super().mouseDoubleClickEvent(e)
            return
        vid = self._tab._scope_child_at(pos)
        if vid is not None and self._tab._data[vid]["is_group"]:
            self._tab._enter_scope(vid)          # drill : entrer dans le bloc
            e.accept()
            return
        if vid is None:                          # fond / hors du niveau actif
            self._tab._scope_up()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)         # visuel : comportement normal


class WireframeTab(QWidget):
    def __init__(self, journal=None):
        super().__init__()
        # le journal de l'app (colonne de droite) : le bandeau vert à côté de
        # la scène dit le DERNIER geste, le journal les garde tous, horodatés
        self.journal = journal or Journal()
        self.project = None
        self.settings = reglages()      # magasin unique (cf. core/project.py)
        self._data: dict = {}          # id -> dict du visuel/groupe
        self._id_to_item: dict = {}    # id -> WireItem
        self._id_to_tree: dict = {}    # id -> QTreeWidgetItem
        self._children_of: dict = {}   # id de groupe -> [ids enfants directs]
        self._selected_id = None
        self._syncing = False
        self._dividers: list = []      # poignées de bordure partagée
        # PRODUCTION : plan en lecture seule (cf. core/edition.py). Posé en
        # tête : toutes les méthodes qui écrivent le consultent.
        self.lecture_seule = edition.production()
        self._grips: list = []         # indicateurs de redimensionnement (sélection)
        self._multi_ids: list = []     # sélection MULTIPLE (Ctrl+clic / lasso)
        self._dirty: set = set()       # ids déplacés (non sauvegardés)
        self._undo: list = []          # pile Ctrl+Z : gestes (géométrie) + actions (fichiers)
        self._scope = None             # niveau actif : None = page, sinon id de groupe
        self._page_id = None           # la page dessinée (la liste peut être en avance)
        self._applying = False         # garde : setPos programmatique en cours
        self._tpl_project = None       # Project du PBIP gabarit (ou None)
        self._tpl_models: list = []    # modèles du gabarit (list_models)
        self._tpl_bases: list = []     # ICP du gabarit (mesures de base)
        self._icp_combos: dict = {}    # ICP du modèle -> QComboBox (ICP du rapport)

        root = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        # -- gauche : sélecteur de page + fil d'Ariane + scène --
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Page :"))
        self.cmb_pages = QComboBox()
        self.cmb_pages.currentIndexChanged.connect(self._on_page_choisie)
        bar.addWidget(self.cmb_pages, 1)
        self.lbl_dims = QLabel("")
        self.lbl_dims.setStyleSheet(f"color:{TEXT_DIM};")
        bar.addWidget(self.lbl_dims)
        btn_reload = QPushButton("Recharger")
        btn_reload.clicked.connect(self._recharger)
        bar.addWidget(btn_reload)
        lv.addLayout(bar)

        crumb_host = QWidget()
        self.crumb = QHBoxLayout(crumb_host)
        self.crumb.setContentsMargins(4, 2, 4, 2)
        self.crumb.setSpacing(2)
        lv.addWidget(crumb_host)

        self.scene = QGraphicsScene()
        self.scene.selectionChanged.connect(self._on_scene_selection)
        self.view = WireframeView(self.scene, self)
        lv.addWidget(self.view, 1)

        # -- barre d'édition --
        save_bar = QHBoxLayout()
        hint = QLabel("Double-clic groupe : entrer (Échap : remonter) · lâcher "
                      "SUR un voisin : insertion · à côté : placement aimanté "
                      "· bord d'un élément : redimensionner (un groupe "
                      "rééchelonne son contenu) · bordure verte : frontière de "
                      "deux collés · Ctrl+clic / lasso : Grouper · Ctrl+Z : "
                      "annuler.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{TEXT_DIM};")
        save_bar.addWidget(hint, 1)
        # pas de voyant « ● n modifié(s) » à côté : le compte vit sur le
        # bouton « Enregistrer », qui s'allume en orange tant qu'il reste
        # quelque chose à écrire
        self.btn_cancel = QPushButton("⌫ Annuler (Ctrl+Z)")
        self.btn_cancel.setToolTip("Annule le dernier geste ou la dernière action "
                                   "(import, groupement, enregistrement…).")
        self.btn_cancel.clicked.connect(self._undo_last)
        self.btn_cancel.setEnabled(False)
        self.btn_save = QPushButton("💾 Enregistrer")
        self.btn_save.setToolTip("Écrit les positions modifiées dans les visual.json "
                                 "(backup automatique ; annulable par Ctrl+Z).")
        self.btn_save.clicked.connect(self._save_positions)
        self.btn_save.setEnabled(False)
        save_bar.addWidget(self.btn_cancel)
        save_bar.addWidget(self.btn_save)
        lv.addLayout(save_bar)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color:{ACCENT};")
        lv.addWidget(self.lbl_status)
        split.addWidget(left)

        # -- droite : hiérarchie + détails + gabarits --
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("Structure de la page :"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet(checkable_list_stylesheet())
        self.tree.currentItemChanged.connect(self._on_tree_current)
        self.tree.itemDoubleClicked.connect(self._on_tree_double)
        rv.addWidget(self.tree, 1)
        rv.addWidget(QLabel("Sélection :"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        police_code(self.details)   # chasse fixe, via le thème
        rv.addWidget(self.details, 1)
        btn_row = QHBoxLayout()
        self.btn_open = QPushButton("Ouvrir visual.json")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_json)
        btn_row.addWidget(self.btn_open)
        self.btn_enter = QPushButton("Entrer dans le groupe")
        self.btn_enter.setEnabled(False)
        self.btn_enter.clicked.connect(lambda: self._enter_scope(self._selected_id))
        btn_row.addWidget(self.btn_enter)
        self.btn_group = QPushButton("Grouper")
        self.btn_group.setToolTip("Crée un groupe (visualGroup) contenant la "
                                  "sélection multiple (Ctrl+clic ou lasso).")
        self.btn_group.setEnabled(False)
        self.btn_group.clicked.connect(self._group_selection)
        btn_row.addWidget(self.btn_group)
        self.btn_ungroup = QPushButton("Dégrouper")
        self.btn_ungroup.setToolTip("Dissout le groupe sélectionné : ses enfants "
                                    "remontent d'un niveau (rien ne bouge à l'écran).")
        self.btn_ungroup.setEnabled(False)
        self.btn_ungroup.clicked.connect(self._ungroup_selection)
        btn_row.addWidget(self.btn_ungroup)
        rv.addLayout(btn_row)

        self.btn_distribute = QPushButton("⬍⬌ Répartir également dans la zone")
        self.btn_distribute.setToolTip("Range les éléments en GRILLE dans leur zone : "
                                       "rangées détectées (hauteurs ∝ hauteur max, "
                                       "collées), cellules ÉGALES pleine largeur par "
                                       "rangée. Cible : la sélection multiple ; OU le "
                                       "GROUPE sélectionné (répartit SES enfants dans "
                                       "sa boîte, rien d'autre ne bouge) ; sinon tout "
                                       "le niveau actif. Annulable (Ctrl+Z).")
        self.btn_distribute.setEnabled(False)
        self.btn_distribute.clicked.connect(self._distribute)
        rv.addWidget(self.btn_distribute)

        # aligner : bords presque alignés -> alignés, gouttières égales, pixel
        align_row = QHBoxLayout()
        align_row.setContentsMargins(0, 0, 0, 0)
        self.btn_align = QPushButton("📐 Aligner les bords")
        self.btn_align.setToolTip(
            "Range au pixel ce qui est à quelques pixels près :\n"
            "• les bords proches les uns des autres (moins que la tolérance)\n"
            "  se posent sur une même ligne : presque collés = collés,\n"
            "  presque alignés = alignés, près du bord de page = sur le bord ;\n"
            "• les gouttières presque égales entre voisins deviennent égales,\n"
            "  les marges aussi (chacune avec sa famille) ;\n"
            "• tout finit sur des pixels entiers.\n\n"
            "Cible : la sélection (un élément, un groupe, plusieurs) ; sinon\n"
            "tout le niveau actif, contenu des groupes compris. Le reste de la\n"
            "page sert d'appui sans bouger. Annulable (Ctrl+Z).")
        self.btn_align.setEnabled(False)
        self.btn_align.clicked.connect(self._aligner)
        align_row.addWidget(self.btn_align, 1)
        align_row.addWidget(QLabel("à"))
        self.spn_tol = QSpinBox()
        self.spn_tol.setRange(1, 20)
        # le nombre seul, sans flèches : elles étaient trop petites pour
        # être cliquées, et un clic dessus sélectionnait le texte. Le
        # clavier et la molette changent toujours la valeur.
        self.spn_tol.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spn_tol.setAlignment(Qt.AlignRight)
        self.spn_tol.setFixedWidth(40)
        self.spn_tol.setToolTip(
            "Tolérance : deux bords plus proches que ça sont « le même bord ».\n"
            "Une gouttière voulue plus petite que la tolérance se refermerait :\n"
            "garder la tolérance sous la plus petite gouttière du rapport.\n\n"
            "De 1 à 20 : taper le nombre, ou la molette, ou les flèches du clavier.")
        try:
            self.spn_tol.setValue(int(lire_reglage(self.CLE_TOLERANCE, "5")))
        except (TypeError, ValueError):
            self.spn_tol.setValue(5)
        self.spn_tol.valueChanged.connect(
            lambda v: ecrire_reglage(self.CLE_TOLERANCE, v))
        align_row.addWidget(self.spn_tol)
        align_row.addWidget(QLabel("px près"))
        self.align_host = QWidget()
        self.align_host.setLayout(align_row)
        rv.addWidget(self.align_host)

        # -- panneau Gabarits (replié par défaut) --
        self.grp_tpl = QGroupBox("Gabarits")
        self.grp_tpl.setCheckable(True)
        self.grp_tpl.setChecked(False)
        tpl_body = QWidget()
        tv = QVBoxLayout(tpl_body)
        tv.setContentsMargins(4, 4, 4, 4)
        rowp = QHBoxLayout()
        self.lbl_tpl = QLabel("(aucun gabarit choisi)")
        self.lbl_tpl.setStyleSheet(f"color:{TEXT_MUTED};")
        rowp.addWidget(self.lbl_tpl, 1)
        btn_tpl = QPushButton("Choisir…")
        btn_tpl.clicked.connect(self._tpl_choose)
        rowp.addWidget(btn_tpl)
        tv.addLayout(rowp)
        self.cmb_tpl_pages = QComboBox()
        self.cmb_tpl_pages.currentIndexChanged.connect(self._tpl_refresh_models)
        tv.addWidget(self.cmb_tpl_pages)
        self.lst_models = QListWidget()
        self.lst_models.setStyleSheet(checkable_list_stylesheet())
        self.lst_models.setMaximumHeight(150)
        self.lst_models.itemSelectionChanged.connect(self._tpl_update_button)
        self.lst_models.itemSelectionChanged.connect(self._tpl_refresh_icp)
        tv.addWidget(self.lst_models)
        # le gabarit vient d'un autre rapport : ses visuels citent SES
        # indicateurs. Une rangée par indicateur trouvé dans le modèle, pour
        # choisir celui de CE rapport qui le remplace à l'import.
        self.lbl_icp = QLabel("Indicateurs du modèle :")
        self.lbl_icp.setToolTip(
            "Les indicateurs que cite le modèle choisi : ses mesures (« Body Fat %\n"
            "30d avg » est une déclinaison de « Body Fat % ») et ses filtres ou\n"
            "segments sur un indicateur.\n\n"
            "À l'import, chacun est remplacé par l'indicateur choisi à côté :\n"
            "« Body Fat % 30d avg » devient « Weight 30d avg », le filtre\n"
            "'Body Fat %' devient 'Weight'. Les titres ne sont pas touchés.")
        tv.addWidget(self.lbl_icp)
        self.icp_host = QWidget()
        self.icp_form = QFormLayout(self.icp_host)
        self.icp_form.setContentsMargins(0, 0, 0, 0)
        tv.addWidget(self.icp_host)
        self.lbl_icp.setVisible(False)
        self.btn_import = QPushButton("Importer dans la page courante")
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self._tpl_import)
        tv.addWidget(self.btn_import)
        gl = QVBoxLayout(self.grp_tpl)
        gl.setContentsMargins(4, 2, 4, 4)
        gl.addWidget(tpl_body)
        self.grp_tpl.toggled.connect(tpl_body.setVisible)
        tpl_body.setVisible(False)
        rv.addWidget(self.grp_tpl)

        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        if self.lecture_seule:
            # rien qui écrive dans les visual.json n'est offert ; la
            # navigation (sélection, entrer dans un groupe, détails) reste
            for w in (self.btn_cancel, self.btn_save, self.btn_group,
                      self.btn_ungroup, self.btn_distribute, self.align_host,
                      self.grp_tpl):
                w.setVisible(False)
            hint.setText("Lecture seule · clic : détails d'un visuel · "
                         "double-clic sur un groupe : entrer (Échap : remonter).")

    # ---- projet ----------------------------------------------------------------

    def set_project(self, project):
        self.project = project
        self._reload()
        self._tpl_load_for_project()

    def reload(self):
        """« ↻ Tout recharger » : relit le rapport en restant sur la page
        courante. Les déplacements non enregistrés sont perdus — l'app demande
        avant d'arriver ici (cf. app._reload_all)."""
        if not self.project:
            return
        self._dirty = set()          # on repart du disque, pas de l'écran
        self._undo = []              # la pile ne décrit plus l'état affiché
        self._reload_keep_page()
        self._update_dirty_ui()

    def _reload(self):
        self.cmb_pages.blockSignals(True)
        self.cmb_pages.clear()
        pages = report_reader.pages(self.project.report_dir) if (
            self.project and self.project.report_dir.exists()) else []
        for p in pages:
            self.cmb_pages.addItem(p["display"], p)
        self.cmb_pages.blockSignals(False)
        self._build_page()

    # ---- ce qui n'est pas écrit, avant de quitter la page ----------------------

    def _on_page_choisie(self, *_):
        """Une autre page est choisie. Dessiner repart des fichiers : les
        déplacements non enregistrés seraient perdus sans un mot."""
        if self._dirty and not self._regler_non_ecrits("Changer de page"):
            self._revenir_page_affichee()
            return
        self._build_page()

    def _recharger(self, *_):
        """Le bouton « Recharger » : même question, il relit les fichiers."""
        if self._dirty and not self._regler_non_ecrits("Recharger"):
            return
        self._reload()

    def _regler_non_ecrits(self, geste) -> bool:
        """Rend True si `geste` peut continuer. Un enregistrement qui échoue
        laisse les éléments à écrire : on reste alors sur la page."""
        choix = self._demander_non_ecrits(geste)
        if choix == "enregistrer":
            self._save_positions()
            return not self._dirty
        return choix == "abandonner"

    def _demander_non_ecrits(self, geste) -> str:
        """« enregistrer », « abandonner » ou « rester »."""
        box = QMessageBox(self)
        box.setWindowTitle("Déplacements non enregistrés")
        box.setText(f"{len(self._dirty)} élément(s) déplacé(s) ou redimensionné(s) "
                    "ne sont pas encore écrits.\n\n"
                    f"{geste} sans enregistrer les ferait perdre.")
        b_save = box.addButton("Enregistrer", QMessageBox.AcceptRole)
        b_jeter = box.addButton("Abandonner les changements", QMessageBox.DestructiveRole)
        box.addButton("Rester ici", QMessageBox.RejectRole)
        box.setDefaultButton(b_save)
        box.exec_() if hasattr(box, "exec_") else box.exec()
        clic = box.clickedButton()
        if clic is b_save:
            return "enregistrer"
        return "abandonner" if clic is b_jeter else "rester"

    def _revenir_page_affichee(self):
        """Remet la liste sur la page dessinée, sans la redessiner."""
        self.cmb_pages.blockSignals(True)
        for i in range(self.cmb_pages.count()):
            data = self.cmb_pages.itemData(i)
            if data and data["id"] == self._page_id:
                self.cmb_pages.setCurrentIndex(i)
                break
        self.cmb_pages.blockSignals(False)

    # ---- construction de la scène + arbre ---------------------------------------

    def _build_page(self, *_):
        self.scene.blockSignals(True)
        self.scene.clear()
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.blockSignals(False)
        self._data = {}
        self._id_to_item = {}
        self._id_to_tree = {}
        self._children_of = {}
        self._dividers = []
        self._grips = []
        self._multi_ids = []
        self._dirty = set()
        # les gestes (géométrie) sont liés à la page affichée -> on ne garde
        # que les actions FICHIERS (annulables après rechargement)
        self._undo = [e for e in self._undo if e.get("kind") != "geom"]
        self._selected_id = None
        self.details.setPlainText("")
        self.btn_open.setEnabled(False)
        self.btn_enter.setEnabled(False)
        self.btn_group.setEnabled(False)
        self.btn_ungroup.setEnabled(False)
        self.btn_distribute.setEnabled(False)
        self.btn_align.setEnabled(False)
        self._update_dirty_ui()

        page = self.cmb_pages.currentData()
        self._page_id = page["id"] if page else None
        if not page:
            self.lbl_dims.setText("")
            self.scene.setSceneRect(QRectF())
            self.scene.blockSignals(False)
            self._set_scope(None)
            return
        W, H = page["width"], page["height"]
        self.lbl_dims.setText(f"{int(W)} × {int(H)}")

        bg = QGraphicsRectItem(0, 0, W, H)
        bg.setBrush(QBrush(QColor(BG_WINDOW)))
        bg.setPen(QPen(QColor(BORDER), 1.5))
        bg.setZValue(-1_000_000)
        bg.setAcceptedMouseButtons(Qt.NoButton)
        self.scene.addItem(bg)

        items = report_reader.visuals(self.project.report_dir, page["id"])
        for d in items:
            self._data[d["id"]] = d
        for d in items:
            if self._parent_of(d) is not None:
                self._children_of.setdefault(d["parent"], []).append(d["id"])
        for d in items:
            rect = WireItem(d["w"], d["h"], d["id"], self, d["is_group"])
            rect.setPos(d["x"], d["y"])
            rect.setData(0, d["id"])
            self.scene.addItem(rect)
            self._id_to_item[d["id"]] = rect
            self._add_labels(rect, d)

        self._build_tree(items)
        self.scene.setSceneRect(0, 0, W, H)
        self.scene.blockSignals(False)
        # préserve le niveau actif s'il existe encore (Recharger/Annuler),
        # retombe sur la page sinon ; applique flags/styles/diviseurs/fil.
        self._set_scope(self._scope)
        self.view.refit()

    def _add_labels(self, rect, d):
        if d["is_group"]:
            # nom du groupe en HAUT-DROITE, décalé verticalement par profondeur
            # d'imbrication : évite qu'il chevauche les autres groupes (coins
            # coïncidents) et les noms de visuels (posés en haut-GAUCHE).
            lab = QGraphicsSimpleTextItem(d["group_name"] or "groupe", rect)
            f = QFont("Segoe UI"); f.setPixelSize(11); f.setItalic(True)
            lab.setFont(f); lab.setBrush(QBrush(QColor(ACCENT_DIM)))
            rect._name_label = lab           # recalé au redimensionnement (_apply_geometry)
            self._place_name_label(rect, d)
            return
        t_type = QGraphicsSimpleTextItem(d["type"] + (" 🎨" if d["has_color_template"] else ""), rect)
        f = QFont("Segoe UI"); f.setPixelSize(11)
        t_type.setFont(f); t_type.setBrush(QBrush(QColor(TEXT_DIM))); t_type.setPos(5, 3)
        if d["title"]:
            t_title = QGraphicsSimpleTextItem(self._elide(d["title"], d["w"]), rect)
            f2 = QFont("Segoe UI"); f2.setPixelSize(13); f2.setBold(True)
            t_title.setFont(f2); t_title.setBrush(QBrush(QColor(TEXT))); t_title.setPos(5, 17)

    def _place_name_label(self, rect, d):
        """Repositionne le nom d'un groupe en haut-DROITE selon sa largeur
        courante (décalé par profondeur pour ne pas chevaucher)."""
        lab = getattr(rect, "_name_label", None)
        if lab is not None:
            x = max(4.0, d["w"] - lab.boundingRect().width() - 5)
            lab.setPos(x, 2 + d.get("depth", 0) * 15)

    def _style_rect(self, rect, d, selected):
        tier = self._tier(d)
        if d["is_group"]:
            if tier == "container":            # le groupe DANS lequel on est
                pen = QPen(QColor(ACCENT))
                pen.setStyle(Qt.DashLine)
                pen.setWidthF(2.0)
                rect.setPen(pen)
                c = QColor(ACCENT); c.setAlpha(14)   # voile « tu es dedans »
                rect.setBrush(QBrush(c))
                rect.setZValue(700_000 + d["z"])
                return
            pen = QPen(QColor(ACCENT if selected else ACCENT_DIM))
            pen.setStyle(Qt.DashLine)
            pen.setWidthF(2.2 if selected else 1.2)
            rect.setPen(pen)
            if selected:
                c = QColor(ACCENT); c.setAlpha(38)
                rect.setBrush(QBrush(c))
            else:
                rect.setBrush(QBrush(Qt.NoBrush))
            # bloc du niveau actif AU-DESSUS de tout (drag plein rectangle) ;
            # sinon bande « contour visible » habituelle
            base = 1_000_000 if tier == "active" else 700_000
            rect.setZValue(base + d["z"] + (100_000 if selected else 0))
        else:
            pen = QPen(QColor(ACCENT if selected else BORDER))
            pen.setWidthF(2.5 if selected else 1.0)
            pen.setStyle(Qt.DashLine if d["hidden"] else Qt.SolidLine)
            rect.setPen(pen)
            b = QColor(SURFACE)
            if d["hidden"]:
                b.setAlpha(90)
            rect.setBrush(QBrush(b))
            base = 1_000_000 if tier == "active" else 1000
            rect.setZValue(base + d["z"] + (5000 if selected else 0))

    @staticmethod
    def _elide(text, width):
        max_chars = max(int(width / 7), 4)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    def _tree_label(self, d):
        if d["is_group"]:
            return f"📦 {d['group_name']}  ({d['child_count']})"
        t = d["type"] + (" 🎨" if d["has_color_template"] else "")
        if d["title"]:
            t += " · " + d["title"]
        return t + ("   (caché)" if d["hidden"] else "")

    def _build_tree(self, items):
        def add(parent_node, d):
            node = QTreeWidgetItem([self._tree_label(d)])
            node.setData(0, Qt.UserRole, d["id"])
            if d["is_group"]:
                fnt = node.font(0); fnt.setBold(True); node.setFont(0, fnt)
            if parent_node is None:
                self.tree.addTopLevelItem(node)
            else:
                parent_node.addChild(node)
            self._id_to_tree[d["id"]] = node
            kids = [self._data[c] for c in self._children_of.get(d["id"], [])]
            for ch in sorted(kids, key=lambda c: -c["z"]):
                add(node, ch)
            node.setExpanded(True)

        roots = [d for d in items if self._parent_of(d) is None]
        for d in sorted(roots, key=lambda c: -c["z"]):
            add(None, d)

    # ---- niveau actif (« scope ») ------------------------------------------------

    def _parent_of(self, d):
        """Id du groupe parent si présent sur la page, sinon None (racine)."""
        p = d.get("parent")
        return p if p and p in self._data else None

    def _descendants(self, gid):
        """Ids de tout le sous-arbre de `gid` (gid exclu)."""
        out, stack = [], [gid]
        while stack:
            for ch in self._children_of.get(stack.pop(), []):
                out.append(ch)
                stack.append(ch)
        return out

    def _scope_path(self):
        """[None, …, scope] : chaîne des conteneurs depuis la page."""
        path, cur, seen = [], self._scope, set()
        while cur is not None and cur in self._data and cur not in seen:
            seen.add(cur)
            path.append(cur)
            cur = self._parent_of(self._data[cur])
        path.append(None)
        path.reverse()
        return path

    def _tier(self, d):
        """Palier d'un élément vs le niveau actif :
        container = le groupe dans lequel on est ; active = enfant DIRECT
        (manipulable) ; inside = plus profond dans le sous-arbre ;
        outside = tout le reste (grisé)."""
        if self._scope is None:
            return "active" if self._parent_of(d) is None else "inside"
        if d["id"] == self._scope:
            return "container"
        parent = self._parent_of(d)
        if parent == self._scope:
            return "active"
        cur = parent
        while cur is not None:
            if cur == self._scope:
                return "inside"
            cur = self._parent_of(self._data[cur])
        return "outside"

    def _set_scope(self, gid):
        """Point d'entrée UNIQUE du changement de niveau (None = page).
        Valide l'id (disparu après rechargement → retombe sur la page)."""
        d = self._data.get(gid) if gid is not None else None
        self._scope = gid if (d is not None and d["is_group"]) else None
        self._apply_scope()
        self._update_breadcrumb()
        self._sync_tree_scope()
        self._rebuild_dividers()
        self._select(None, from_tree=False)
        self.view.setFocus()

    def _enter_scope(self, gid):
        d = self._data.get(gid)
        if d is not None and d["is_group"]:
            self._set_scope(gid)

    def _scope_up(self):
        if self._scope is None:
            return
        self._set_scope(self._parent_of(self._data[self._scope]))

    def _distribute_target(self):
        """(ids, zone, libellé) à répartir, par priorité :
        1. sélection MULTIPLE (≥2 du niveau actif) — zone = leur boîte ;
        2. UN GROUPE sélectionné — ses enfants, zone = LA BOÎTE DU GROUPE
           (on remplit le groupe, rien d'autre ne bouge) ;
        3. sinon les enfants directs du niveau actif — zone = la boîte du
           groupe-scope si on est dans un groupe, sinon la boîte des éléments.
        zone=None => boîte englobante des éléments (∩ page)."""
        multi = [i for i in self._multi_ids
                 if i in self._data and self._tier(self._data[i]) == "active"]
        if len(multi) >= 2:
            return multi, None, "sélection"
        d = self._data.get(self._selected_id)
        if d and d["is_group"]:
            kids = list(self._children_of.get(d["id"], []))
            if len(kids) >= 2:
                zone = (d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"])
                return kids, zone, f"dans « {d['group_name'] or 'groupe'} »"
        ids = [o["id"] for o in self._data.values()
               if self._parent_of(o) == self._scope]
        if self._scope is not None and self._scope in self._data:
            g = self._data[self._scope]
            return ids, (g["x"], g["y"], g["x"] + g["w"], g["y"] + g["h"]), \
                f"dans « {g['group_name'] or 'groupe'} »"
        return ids, None, "sur la page"

    def _update_distribute_btn(self):
        self.btn_distribute.setEnabled(len(self._distribute_target()[0]) >= 2)
        self.btn_align.setEnabled(bool(self._aligner_cible()[0]))

    def _apply_scope(self):
        """Accorde l'interactivité aux enfants directs du niveau actif ;
        grise et fige tout le reste."""
        self._syncing = True
        self.scene.blockSignals(True)
        self.scene.clearSelection()
        self.scene.blockSignals(False)
        self._syncing = False
        for vid, rect in self._id_to_item.items():
            d = self._data[vid]
            tier = self._tier(d)
            if tier == "active":
                rect.setAcceptedMouseButtons(Qt.AllButtons)
                rect.setFlag(QGraphicsItem.ItemIsSelectable, True)
                rect.setFlag(QGraphicsItem.ItemIsMovable, not self.lecture_seule)
                # resynchronise le point de référence AVANT d'activer le suivi
                # (groupes : sous-arbre ; tous : poignées pendant le drag)
                rect._last_pos = rect.pos()
                rect.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
                rect.setOpacity(1.0)
            else:
                rect.setAcceptedMouseButtons(Qt.NoButton)
                rect.setFlag(QGraphicsItem.ItemIsSelectable, False)
                rect.setFlag(QGraphicsItem.ItemIsMovable, False)
                rect.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
                rect.setOpacity(0.35 if tier == "outside" else 1.0)
            self._style_rect(rect, d, selected=(vid == self._selected_id))
        self._update_distribute_btn()

    def _scope_child_at(self, scene_pos):
        """Résout l'item sous le curseur en son ancêtre enfant DIRECT du
        niveau actif (None = fond de page ou hors du sous-arbre du scope)."""
        for it in self.scene.items(scene_pos):
            vid = it.data(0)
            if not vid or vid not in self._data:
                continue
            cur = vid
            while cur is not None:
                if self._parent_of(self._data[cur]) == self._scope:
                    return cur
                cur = self._parent_of(self._data[cur])
            return None            # premier item trouvé : hors du sous-arbre
        return None

    def _update_breadcrumb(self):
        while self.crumb.count():
            item = self.crumb.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        path = self._scope_path()
        link_qss = ("QPushButton { border:none; background:transparent; color:"
                    + ACCENT + "; padding:1px 6px; } QPushButton:hover { color:"
                    + TEXT + "; }")
        for i, gid in enumerate(path):
            name = "Page" if gid is None else (
                self._data[gid]["group_name"] or "groupe")
            if i == len(path) - 1:               # niveau courant
                lab = QLabel(name)
                lab.setStyleSheet(f"color:{ACCENT}; font-weight:bold; padding:1px 6px;")
                self.crumb.addWidget(lab)
            else:                                # ancêtre cliquable
                btn = QPushButton(name)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(link_qss)
                btn.clicked.connect(lambda _=None, g=gid: self._set_scope(g))
                self.crumb.addWidget(btn)
                sep = QLabel("▸")
                sep.setStyleSheet(f"color:{TEXT_MUTED};")
                self.crumb.addWidget(sep)
        if self._scope is not None:
            tip = QLabel("(Échap : remonter)")
            tip.setStyleSheet(f"color:{TEXT_MUTED}; padding-left:8px;")
            self.crumb.addWidget(tip)
        self.crumb.addStretch(1)

    def _sync_tree_scope(self):
        for vid, node in self._id_to_tree.items():
            node.setForeground(0, QBrush(QColor(
                ACCENT if vid == self._scope else TEXT)))
        node = self._id_to_tree.get(self._scope)
        if node is not None:
            self.tree.scrollToItem(node)

    def _on_tree_double(self, item, _col):
        self._enter_scope(item.data(0, Qt.UserRole))

    def _group_selection(self):
        """Crée un visualGroup PBIR contenant la sélection multiple (frères du
        niveau actif). Écriture IMMÉDIATE (backup + manifeste), rechargement,
        sélection posée sur le nouveau groupe."""
        if self.lecture_seule:
            return
        ids = [i for i in self._multi_ids
               if i in self._data and self._tier(self._data[i]) == "active"]
        page = self.cmb_pages.currentData()
        if len(ids) < 2 or not page or not self.project:
            return
        if self._dirty:
            self._save_positions()             # silencieux : backupé + annulable
        n = sum(1 for d in self._data.values() if d["is_group"]) + 1
        name, ok = QInputDialog.getText(self, "Grouper la sélection",
                                        "Nom du groupe :", text=f"Groupe {n}")
        name = (name or "").strip()
        if not ok or not name:
            return
        member_paths = [self._data[i]["path"] for i in ids]
        try:
            gid, backup_dir = report_reader.create_group(
                self.project.report_dir, page["id"], ids, name,
                br.backup_root(self.project.folder, "_wireframe_backups"))
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Erreur de groupement", str(e))
            return
        vis_dir = Path(member_paths[0]).parent.parent
        restored = {p: str(backup_dir / (Path(p).parent.name + "_visual.json"))
                    for p in member_paths}
        self._reload_keep_page()
        self._push_undo_files(f"Groupement « {name} »",
                              created=[str(vis_dir / gid / "visual.json")],
                              restored=restored)
        self._select(gid, from_tree=False)
        self._status(f"📦 Groupe « {name} » créé ({len(ids)} éléments, backup "
                     f"{backup_dir.name}), Ctrl+Z pour annuler. "
                     "Double-clic dessus pour entrer dedans.")

    @staticmethod
    def _cluster_1d(elems, lo_key, size_key):
        """Regroupe les éléments dont les intervalles [lo, lo+size] se
        chevauchent (union-find ; seuil : > 50 % du plus petit). lo_key='y' →
        rangées, lo_key='x' → colonnes. Retourne les groupes triés par lo."""
        parent = {e["id"]: e["id"] for e in elems}

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for a in elems:
            for b in elems:
                if a is b:
                    continue
                ov = (min(a[lo_key] + a[size_key], b[lo_key] + b[size_key])
                      - max(a[lo_key], b[lo_key]))
                if ov > 0.5 * min(a[size_key], b[size_key]):
                    ra, rb = find(a["id"]), find(b["id"])
                    if ra != rb:
                        parent[ra] = rb
        out: dict = {}
        for e in elems:
            out.setdefault(find(e["id"]), []).append(e)
        return sorted(out.values(), key=lambda g: min(m[lo_key] for m in g))

    def _distribute(self):
        """Répartit les éléments dans leur zone en RESPECTANT la grille :
        les rangées sont détectées (chevauchement vertical), empilées bord à
        bord avec des hauteurs proportionnelles à la hauteur MAX de chaque
        rangée (robuste aux éléments décalés), et chaque rangée est découpée
        en cellules ÉGALES pleine largeur (une rangée d'un seul élément =
        pleine largeur). Une seule rangée/colonne = le cas simple. La zone
        vient de `_distribute_target` (sélection / groupe / niveau). Un groupe
        posé dans une cellule rééchelonne son contenu. En mémoire (Ctrl+Z)."""
        if self.lecture_seule:
            return
        ids, zone, label = self._distribute_target()
        if len(ids) < 2:
            return
        self._push_undo_geom()
        elems = [self._data[i] for i in ids]
        if zone is not None:
            x0, y0, x1, y1 = zone
        else:
            x0 = min(e["x"] for e in elems); x1 = max(e["x"] + e["w"] for e in elems)
            y0 = min(e["y"] for e in elems); y1 = max(e["y"] + e["h"] for e in elems)
            # la zone est BORNÉE à la page : répartir ramène aussi dans la page
            # ce qui débordait (garde-fou si la zone clampée devient dégénérée)
            W, H = self._page_size()
            if W and min(x1, W) - max(x0, 0.0) > 20:
                x0, x1 = max(x0, 0.0), min(x1, W)
            if H and min(y1, H) - max(y0, 0.0) > 20:
                y0, y1 = max(y0, 0.0), min(y1, H)

        rows = self._cluster_1d(elems, "y", "h")
        cols = self._cluster_1d(elems, "x", "w")
        if len(cols) == 1 and len(rows) > 1:
            # une seule COLONNE : cellules égales empilées, pleine largeur
            order = sorted(elems, key=lambda e: e["y"] + e["h"] / 2)
            n = len(order)
            for k, e in enumerate(order):
                a = y0 + (y1 - y0) * k / n
                b = y0 + (y1 - y0) * (k + 1) / n
                self._set_item_box(e["id"], x0, a, x1, b)
            msg = f"{n} élément(s) répartis {label} (en colonne)"
        else:
            # grille rangée par rangée (1 rangée = le cas simple) : hauteur de
            # rangée ∝ hauteur MAX de ses éléments (l'étendue de bande gonfle
            # dès que des éléments sont décalés → proportions faussées)
            weights = [max(m["h"] for m in g) for g in rows]
            total = sum(weights) or 1.0
            cur = y0
            for gi, g in enumerate(rows):
                bottom = y1 if gi == len(rows) - 1 else \
                    cur + (y1 - y0) * weights[gi] / total
                order = sorted(g, key=lambda e: e["x"] + e["w"] / 2)
                n = len(order)
                for k, e in enumerate(order):
                    a = x0 + (x1 - x0) * k / n
                    b = x0 + (x1 - x0) * (k + 1) / n
                    self._set_item_box(e["id"], a, cur, b, bottom)
                cur = bottom
            msg = (f"{len(elems)} élément(s) répartis {label} en grille "
                   f"({len(rows)} rangée(s))")
        self._rebuild_dividers()
        self._place_grips()
        self._status(f"⬍⬌ {msg}, Ctrl+Z pour annuler.")

    CLE_TOLERANCE = "wireframe_tolerance_alignement"

    def _aligner_cible(self):
        """(ids du niveau actif à aligner, libellé) : la sélection multiple,
        sinon l'élément sélectionné (un groupe vient avec son contenu), sinon
        tout le niveau actif."""
        def actifs(ids):
            return [i for i in ids if i in self._data
                    and self._tier(self._data[i]) == "active"]
        multi = actifs(self._multi_ids)
        if multi:
            return multi, f"({len(multi)} éléments sélectionnés)"
        sel = actifs([self._selected_id] if self._selected_id else [])
        if sel:
            d = self._data[sel[0]]
            if d["is_group"]:
                nom = d["group_name"] or "groupe"
            else:
                nom = d.get("title") or d["type"]
            return sel, f"(« {nom} »)"
        ids = [o["id"] for o in self._data.values()
               if self._parent_of(o) == self._scope]
        if self._scope is not None and self._scope in self._data:
            g = self._data[self._scope]
            return ids, f"dans « {g['group_name'] or 'groupe'} »"
        return ids, "sur la page"

    def _feuilles(self, vid):
        """Les visuels (pas les groupes) du sous-arbre de `vid`, lui compris.
        Un groupe vide compte comme un visuel : il a une boîte à lui."""
        kids = self._children_of.get(vid, [])
        if not kids:
            return [vid]
        out = []
        for k in kids:
            out += self._feuilles(k)
        return out

    def _aligner(self):
        """Bouton « Aligner les bords » : voir core/alignement.py. Les VISUELS
        de la cible sont alignés ; un groupe dont la boîte épousait son contenu
        l'épouse encore après, les autres gardent la leur ; les positions
        relatives suivent. En mémoire, annulable (Ctrl+Z)."""
        if self.lecture_seule:
            return
        cible, label = self._aligner_cible()
        if not cible:
            return
        tol = float(self.spn_tol.value())

        def boite(d):
            return (d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"])

        feuilles = []
        for vid in cible:
            feuilles += self._feuilles(vid)
        dans_cible = set(feuilles)
        groupes = set()
        for vid in cible:
            if self._children_of.get(vid):
                groupes |= {vid} | {g for g in self._descendants(vid)
                                    if self._children_of.get(g)}
        # appuis : les visuels visibles du niveau hors de la cible
        fixes = [boite(d) for d in self._data.values()
                 if d["id"] not in dans_cible
                 and not self._children_of.get(d["id"])
                 and self._tier(d) in ("active", "inside")]
        if self._scope is not None and self._scope in self._data:
            cadre = boite(self._data[self._scope])
        else:
            W, H = self._page_size()
            cadre = (0.0, 0.0, W, H) if W and H else None

        def union(gid):
            bs = [boite(self._data[k]) for k in self._children_of.get(gid, [])]
            return (min(b[0] for b in bs), min(b[1] for b in bs),
                    max(b[2] for b in bs), max(b[3] for b in bs))

        # un groupe qui épousait son contenu l'épousera encore ; un groupe
        # plus grand que son contenu (marge voulue) garde sa boîte
        epouse = {g for g in groupes
                  if max(abs(a - b) for a, b in
                         zip(boite(self._data[g]), union(g))) <= tol + 0.5}

        def relatif(d):
            return (d["x"] - d["parent_x"], d["y"] - d["parent_y"], d["w"], d["h"])

        avant = {k: relatif(d) for k, d in self._data.items()}
        nouvelles, n_gout = alignement.aligner(
            {k: boite(self._data[k]) for k in feuilles}, fixes, cadre, tol)
        self._push_undo_geom()
        for k, (x0, y0, x1, y1) in nouvelles.items():
            d = self._data[k]
            d["x"], d["y"], d["w"], d["h"] = x0, y0, x1 - x0, y1 - y0
        # du plus profond au moins profond : un groupe se refait sur des
        # enfants déjà refaits
        for g in sorted(groupes, key=lambda g: -self._data[g].get("depth", 0)):
            if g in epouse:
                x0, y0, x1, y1 = union(g)
                d = self._data[g]
                d["x"], d["y"], d["w"], d["h"] = x0, y0, x1 - x0, y1 - y0
        for d in self._data.values():
            p = self._parent_of(d)
            if p is not None:
                d["parent_x"] = self._data[p]["x"]
                d["parent_y"] = self._data[p]["y"]
        changes = [k for k, d in self._data.items()
                   if max(abs(a - b) for a, b in zip(relatif(d), avant[k])) > 1e-6]
        if not changes:
            self._undo.pop()
            self._update_dirty_ui()
            self._status(f"📐 Rien à aligner {label} à {int(tol)} px près : "
                         "tout est déjà en place.")
            return
        for k in self._data:
            self._apply_geometry(k)
        for k in changes:
            self._mark_dirty(k)
        self._rebuild_dividers()
        self._place_grips()
        bouges = sum(1 for k in changes if k in nouvelles)
        self._status(f"📐 {bouges} visuel(s) aligné(s) {label} à {int(tol)} px "
                     "près"
                     + (f", {n_gout} gouttière(s) ou marge(s) égalisée(s)"
                        if n_gout else "")
                     + ". Ctrl+Z pour annuler.")

    def _ungroup_selection(self):
        """Dissout le groupe sélectionné : ses enfants remontent d'un niveau
        (rien ne bouge à l'écran). Sans confirmation : backup + Ctrl+Z."""
        if self.lecture_seule:
            return
        d = self._data.get(self._selected_id)
        page = self.cmb_pages.currentData()
        if not d or not d["is_group"] or not page or not self.project:
            return
        if self._dirty:
            self._save_positions()             # silencieux : backupé + annulable
        name = d["group_name"] or d["id"]
        vis_dir = Path(d["path"]).parent.parent
        try:
            n, backup_dir = report_reader.ungroup(
                self.project.report_dir, page["id"], d["id"],
                br.backup_root(self.project.folder, "_wireframe_backups"))
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Erreur de dégroupement", str(e))
            return
        restored = {}
        for bak in backup_dir.glob("*_visual.json"):
            vid = bak.name[: -len("_visual.json")]
            restored[str(vis_dir / vid / "visual.json")] = str(bak)
        self._reload_keep_page()
        self._push_undo_files(f"Dégroupement de « {name} »", restored=restored)
        self._status(f"📤 Groupe « {name} » dissous ({n} élément(s) remontés), "
                     "Ctrl+Z pour annuler.")

    # ---- sélection (synchronisée canevas <-> arbre) ------------------------------

    def _select(self, vid, from_tree):
        if self._syncing:
            return
        self._syncing = True
        self._multi_ids = []
        self.btn_group.setEnabled(False)
        self._selected_id = vid
        for rid, rect in self._id_to_item.items():
            self._style_rect(rect, self._data[rid], selected=(rid == vid))
        # sélection de scène (éléments du niveau actif seulement)
        self.scene.blockSignals(True)
        for rid, rect in self._id_to_item.items():
            if rect.flags() & QGraphicsRectItem.ItemIsSelectable:
                rect.setSelected(rid == vid)
        self.scene.blockSignals(False)
        # arbre
        if not from_tree:
            self.tree.blockSignals(True)
            node = self._id_to_tree.get(vid)
            if node:
                self.tree.setCurrentItem(node)
            else:
                self.tree.clearSelection()
            self.tree.blockSignals(False)
        # détails
        if vid and vid in self._data:
            self._show_details(self._data[vid])
        else:
            self.details.setPlainText("")
            self.btn_open.setEnabled(False)
            self.btn_enter.setEnabled(False)
            self.btn_ungroup.setEnabled(False)
        self._refresh_grips()
        self._update_distribute_btn()          # sélection simple = enfants du niveau
        self._syncing = False

    def _on_scene_selection(self):
        if self._syncing:
            return
        try:
            sel = self.scene.selectedItems()
        except RuntimeError:       # scène en cours de destruction (fermeture)
            return
        ids = [it.data(0) for it in sel if it.data(0)]
        if len(ids) > 1:
            # sélection MULTIPLE (Ctrl+clic / lasso) : on n'écrase pas la
            # sélection de scène — on surligne et on arme « Grouper »
            self._multi_ids = ids
            self._selected_id = None
            self._syncing = True
            for rid, rect in self._id_to_item.items():
                self._style_rect(rect, self._data[rid], selected=(rid in ids))
            self._syncing = False
            self._refresh_grips()          # (exige une sélection simple -> vide)
            groupables = [i for i in ids if self._tier(self._data[i]) == "active"]
            self.details.setPlainText(
                f"{len(ids)} éléments sélectionnés"
                + ("\n« Grouper » les met dans un nouveau groupe."
                   if len(groupables) >= 2 else
                   "\n(pour grouper : ≥ 2 éléments du niveau actif)"))
            self.btn_open.setEnabled(False)
            self.btn_enter.setEnabled(False)
            self.btn_ungroup.setEnabled(False)
            self.btn_group.setEnabled(len(groupables) >= 2)
            self._update_distribute_btn()
            return
        self._select(ids[0] if ids else None, from_tree=False)

    def _on_tree_current(self, cur, _prev):
        if cur is not None:
            self._select(cur.data(0, Qt.UserRole), from_tree=True)

    def _show_details(self, d):
        self.btn_open.setEnabled(True)
        self.btn_enter.setEnabled(bool(d["is_group"]))
        self.btn_ungroup.setEnabled(bool(d["is_group"]))
        if d["is_group"]:
            lines = [
                f"GROUPE  : {d['group_name']}",
                f"mode    : {d['group_mode']}",
                f"contenu : {d['child_count']} élément(s) direct(s)",
                f"pos     : x={d['x']:.0f} y={d['y']:.0f}   {d['w']:.0f} × {d['h']:.0f}",
            ]
            if d["parent_name"]:
                lines.append(f"dans    : {d['parent_name']}")
        else:
            lines = [
                f"id      : {d['id']}",
                f"type    : {d['type']}" + ("   (caché)" if d["hidden"] else ""),
                f"titre   : {d['title'] or '(sans titre)'}",
                f"pos     : x={d['x']:.0f} y={d['y']:.0f}   {d['w']:.0f} × {d['h']:.0f}   z={d['z']:.0f}",
            ]
            if d["parent_name"]:
                lines.append(f"groupe  : {d['parent_name']}")
            if d["has_color_template"]:
                lines.append("🎨 gabarit de couleur « specific column » (opt-in Colorer)")
            if d["fields"]:
                lines.append("")
                lines.append("Champs :")
                lines += ["  • " + f for f in d["fields"]]
            if d["objects_keys"]:
                lines.append("")
                lines.append("Formatage (objects) : " + ", ".join(d["objects_keys"]))
        self.details.setPlainText("\n".join(lines))

    def _open_json(self):
        d = self._data.get(self._selected_id)
        if d:
            os.startfile(d["path"])

    # ---- édition : réordonner (reflow) + bordure partagée -----------------------

    def _apply_geometry(self, vid):
        """Applique data[x/y/w/h] au rect de la scène — sous garde `_applying`
        pour ne pas déclencher le suivi de sous-arbre des groupes."""
        d = self._data[vid]
        rect = self._id_to_item[vid]
        self._applying = True
        try:
            rect.setRect(0, 0, d["w"], d["h"])
            rect.setPos(d["x"], d["y"])
            self._place_name_label(rect, d)      # nom de groupe suit la largeur
        finally:
            self._applying = False

    def _restore_item(self, vid):
        """Resnap un item (et le sous-arbre d'un groupe) sur _data — annule le
        décalage visuel d'un micro-drag."""
        self._apply_geometry(vid)
        for did in self._descendants(vid):
            self._apply_geometry(did)
        self._place_grips()

    def _shift_descendants_visual(self, gid, dx, dy):
        """Pendant le drag d'un groupe : décale les rects descendants (scène
        SEULEMENT — _data est mis à jour une fois, au relâchement)."""
        self._applying = True
        try:
            for did in self._descendants(gid):
                it = self._id_to_item.get(did)
                if it is not None:
                    it.setPos(it.pos().x() + dx, it.pos().y() + dy)
        finally:
            self._applying = False

    def _move_group_to(self, gid, nx, ny):
        """Déplace un groupe ET tout son sous-arbre dans _data + scène. Seul le
        groupe devient dirty : les positions locales (lx/ly) des enfants ne
        changent pas, donc aucun fichier enfant à réécrire. parent_x/parent_y
        des descendants suivent le delta → l'invariant x - parent_x == lx du
        save reste vrai."""
        g = self._data[gid]
        dx, dy = nx - g["x"], ny - g["y"]
        for did in self._descendants(gid):
            o = self._data[did]
            o["x"] += dx; o["y"] += dy
            o["parent_x"] += dx; o["parent_y"] += dy
            self._apply_geometry(did)      # resnap même à delta nul (post-drag)
        g["x"], g["y"] = nx, ny
        self._apply_geometry(gid)
        self._mark_dirty(gid)

    def _move_item_to(self, vid, nx, ny):
        d = self._data[vid]
        if abs(nx - d["x"]) < 1e-9 and abs(ny - d["y"]) < 1e-9:
            return                             # déjà en place : pas de dirty
        if d["is_group"]:
            self._move_group_to(vid, nx, ny)
        else:
            d["x"], d["y"] = nx, ny
            self._apply_geometry(vid)
            self._mark_dirty(vid)

    SNAP = 10.0        # rayon d'aimantation des bords (unités de page)

    def _on_item_moved(self, vid):
        """Un élément du niveau actif a été lâché. Deux comportements :
        - lâché SUR un frère (chevauchement net) : il s'INSÈRE à côté de lui,
          dans la chaîne d'éléments collés du même axe — SEULE cette chaîne
          bouge, le reste de la page ne bouge jamais ;
        - lâché ailleurs : placement LIBRE aimanté — collage bord à bord au
          frère d'en face, alignement de bords, bords de page."""
        self._push_undo_geom()                 # état AVANT le geste (Ctrl+Z)
        d = self._data[vid]
        rect = self._id_to_item[vid]
        rx, ry = rect.pos().x(), rect.pos().y()
        others = [o for o in self._data.values()
                  if self._parent_of(o) == self._scope and o["id"] != vid]

        target, ratio = None, 0.0
        for o in others:
            ox = min(rx + d["w"], o["x"] + o["w"]) - max(rx, o["x"])
            oy = min(ry + d["h"], o["y"] + o["h"]) - max(ry, o["y"])
            if ox <= 0 or oy <= 0:
                continue
            r = (ox * oy) / min(d["w"] * d["h"], o["w"] * o["h"])
            if r > ratio:
                target, ratio = o, r
        if target is not None and ratio >= 0.20:
            self._insert_into_chain(vid, target, others, rx, ry)
        else:
            self._free_place(vid, others, rx, ry)
        self._restore_item(vid)                # garantit rect(s) == _data
        self._rebuild_dividers()
        self._place_grips()

    def _free_place(self, vid, others, rx, ry):
        """Placement libre aimanté : collage bord à bord (seulement face à
        face — étendues qui se chevauchent sur l'autre axe), alignement de
        bords (même à distance, façon guides), bords de la page. Au-delà de
        SNAP : position lâchée telle quelle (le chevauchement reste permis,
        comme dans Power BI)."""
        d = self._data[vid]
        page = self.cmb_pages.currentData() or {}
        W, H = page.get("width", 0), page.get("height", 0)

        def best(value, cands):
            c = min(cands, key=lambda v: abs(v - value)) if cands else None
            return c if c is not None and abs(c - value) <= self.SNAP else value

        cx, cy = [], []
        if W:
            cx += [0.0, W - d["w"]]
        if H:
            cy += [0.0, H - d["h"]]
        for o in others:
            y_overlap = min(ry + d["h"], o["y"] + o["h"]) - max(ry, o["y"])
            x_overlap = min(rx + d["w"], o["x"] + o["w"]) - max(rx, o["x"])
            if y_overlap > 0:                  # côte à côte : collage gauche/droite
                cx += [o["x"] + o["w"], o["x"] - d["w"]]
            if x_overlap > 0:                  # empilés : collage dessus/dessous
                cy += [o["y"] + o["h"], o["y"] - d["h"]]
            cx += [o["x"], o["x"] + o["w"] - d["w"]]      # alignements de bords
            cy += [o["y"], o["y"] + o["h"] - d["h"]]
        pos = self._clamp_pos_to_page(vid, QPointF(best(rx, cx), best(ry, cy)))
        self._move_item_to(vid, pos.x(), pos.y())

    def _insert_into_chain(self, vid, target, others, rx, ry):
        """Lâché SUR `target` : V s'insère dans la chaîne d'éléments collés de
        target sur l'axe choisi (décalage des centres, normalisé par les
        demi-étendues). Repack bord à bord ancré au début EXISTANT de la
        chaîne ; V s'aligne sur target dans l'autre axe. Rien d'autre ne bouge."""
        d = self._data[vid]
        dxn = ((rx + d["w"] / 2) - (target["x"] + target["w"] / 2)) / ((d["w"] + target["w"]) / 2)
        dyn = ((ry + d["h"] / 2) - (target["y"] + target["h"] / 2)) / ((d["h"] + target["h"]) / 2)
        horizontal = abs(dxn) >= abs(dyn)

        members = [self._data[c] for c in self._chain_of(target["id"], others, horizontal)]

        def center(o):
            if o["id"] == vid:
                return (rx + o["w"] / 2) if horizontal else (ry + o["h"] / 2)
            return (o["x"] + o["w"] / 2) if horizontal else (o["y"] + o["h"] / 2)

        order = sorted(members + [d], key=center)
        if horizontal:
            cur = min(o["x"] for o in members)     # ancre : la chaîne ne bouge pas
            for o in order:
                ny = target["y"] if o["id"] == vid else o["y"]
                self._move_item_to(o["id"], cur, ny)
                cur += o["w"]
        else:
            cur = min(o["y"] for o in members)
            for o in order:
                nx = target["x"] if o["id"] == vid else o["x"]
                self._move_item_to(o["id"], nx, cur)
                cur += o["h"]

    def _adjacent_pairs(self, sibs, side_by_side):
        """Paires (L, R) de frères collés : side_by_side=True = côte à côte
        (bordure verticale partagée), False = empilés (bordure horizontale)."""
        TOL = 3
        out = []
        for L in sibs:
            for R in sibs:
                if L is R:
                    continue
                if side_by_side:
                    if L["x"] < R["x"] and abs((L["x"] + L["w"]) - R["x"]) <= TOL:
                        o0 = max(L["y"], R["y"]); o1 = min(L["y"] + L["h"], R["y"] + R["h"])
                        if o1 - o0 > 6:
                            out.append((L, R))
                else:
                    if L["y"] < R["y"] and abs((L["y"] + L["h"]) - R["y"]) <= TOL:
                        o0 = max(L["x"], R["x"]); o1 = min(L["x"] + L["w"], R["x"] + R["w"])
                        if o1 - o0 > 6:
                            out.append((L, R))
        return out

    def _chain_of(self, start_id, sibs, horizontal):
        """Ids de la chaîne d'éléments collés contenant start_id le long de
        l'axe donné (horizontal=True : rangée côte à côte ; False : colonne)."""
        adj: dict = {}
        for L, R in self._adjacent_pairs(sibs, side_by_side=horizontal):
            adj.setdefault(L["id"], set()).add(R["id"])
            adj.setdefault(R["id"], set()).add(L["id"])
        seen, stack = {start_id}, [start_id]
        while stack:
            for n in adj.get(stack.pop(), ()):
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        return seen

    def _border_lines(self, sibs, vertical):
        """LIGNES-FRONTIÈRES du niveau actif sur un axe. Une ligne regroupe TOUS
        les éléments qui bordent une même arête (coordonnée commune, à TOL près,
        et intervalles de contact connexes) : « before » = à gauche/au-dessus
        (arête sortante = coord), « after » = à droite/en dessous (arête
        entrante = coord). Ainsi le bas d'un groupe partagé avec pivotTable ET
        lineChart = UNE ligne, pas deux paires."""
        TOL = 3
        contacts = []      # (coord, lo, hi, before_id, after_id)
        for A in sibs:
            for B in sibs:
                if A is B:
                    continue
                if vertical:
                    if A["x"] < B["x"] and abs((A["x"] + A["w"]) - B["x"]) <= TOL:
                        lo = max(A["y"], B["y"]); hi = min(A["y"] + A["h"], B["y"] + B["h"])
                        if hi - lo > 6:
                            contacts.append((B["x"], lo, hi, A["id"], B["id"]))
                else:
                    if A["y"] < B["y"] and abs((A["y"] + A["h"]) - B["y"]) <= TOL:
                        lo = max(A["x"], B["x"]); hi = min(A["x"] + A["w"], B["x"] + B["w"])
                        if hi - lo > 6:
                            contacts.append((B["y"], lo, hi, A["id"], B["id"]))
        lines = []
        used = [False] * len(contacts)
        for i, c in enumerate(contacts):
            if used[i]:
                continue
            coord = c[0]
            group = [c]; used[i] = True
            changed = True
            while changed:                     # étend la ligne aux contacts connexes
                changed = False
                glo = min(g[1] for g in group); ghi = max(g[2] for g in group)
                for j, c2 in enumerate(contacts):
                    if used[j] or abs(c2[0] - coord) > TOL:
                        continue
                    if c2[1] <= ghi + TOL and c2[2] >= glo - TOL:
                        group.append(c2); used[j] = True; changed = True
            before, after = [], []
            for _, _, _, bid, aid in group:
                if bid not in before:
                    before.append(bid)
                if aid not in after:
                    after.append(aid)
            lines.append({"vertical": vertical, "before": before, "after": after})
        return lines

    def _line_geometry(self, line):
        """(valide, coord, lo, hi) COURANTS d'une ligne-frontière (union des
        intervalles de contact avant×après ; invalide si plus aucun contact)."""
        TOL = 3
        before = [self._data[i] for i in line["before"] if i in self._data]
        after = [self._data[i] for i in line["after"] if i in self._data]
        ivals = []
        for a in before:
            for b in after:
                if line["vertical"]:
                    if abs((a["x"] + a["w"]) - b["x"]) <= TOL:
                        lo = max(a["y"], b["y"]); hi = min(a["y"] + a["h"], b["y"] + b["h"])
                        if hi - lo > 6:
                            ivals.append((b["x"], lo, hi))
                else:
                    if abs((a["y"] + a["h"]) - b["y"]) <= TOL:
                        lo = max(a["x"], b["x"]); hi = min(a["x"] + a["w"], b["x"] + b["w"])
                        if hi - lo > 6:
                            ivals.append((b["y"], lo, hi))
        if not ivals:
            return (False, 0.0, 0.0, 0.0)
        coord = sum(v[0] for v in ivals) / len(ivals)
        return (True, coord, min(v[1] for v in ivals), max(v[2] for v in ivals))

    def _build_dividers(self):
        """Une poignée par ligne-frontière du niveau actif — visuels ET groupes
        (glisser une frontière rééchelonne le contenu des groupes bordants,
        comme Desktop en ScaleMode). Poignées SEULEMENT au niveau actif."""
        if self.lecture_seule:
            return
        sibs = [d for d in self._data.values() if self._parent_of(d) == self._scope]
        for vertical in (True, False):
            for line in self._border_lines(sibs, vertical):
                self._add_divider(line)

    def _add_divider(self, line):
        h = DividerHandle(self, line)
        self.scene.addItem(h)
        self._dividers.append(h)
        self._position_handle(h)
        h._ready = True

    def _position_handle(self, h):
        """Recale une poignée sur la géométrie courante de sa ligne ; la masque
        si la ligne n'a plus de contact."""
        h._ready = False
        ok, coord, lo, hi = self._line_geometry(h.line)
        if ok:
            if h.vertical:
                h.setRect(-h.THICK / 2, 0, h.THICK, hi - lo)
                h.setPos(coord, lo)
            else:
                h.setRect(0, -h.THICK / 2, hi - lo, h.THICK)
                h.setPos(lo, coord)
        h.setVisible(ok)
        h._ready = True

    def _rebuild_dividers(self):
        for h in self._dividers:
            self.scene.removeItem(h)
        self._dividers = []
        self._build_dividers()

    def _divider_moving(self, handle, pos):
        """Glisse la ligne-frontière : déplace l'arête de TOUS ses éléments
        (before : arête droite/basse -> coord ; after : arête gauche/haute ->
        coord). Un groupe bordant rééchelonne son contenu. Taille min 20."""
        line = handle.line
        MIN = 20.0
        before = [self._data[i] for i in line["before"] if i in self._data]
        after = [self._data[i] for i in line["after"] if i in self._data]
        if not before or not after:
            return handle.pos()
        # aimante à toute autre arête visible du niveau (bords des slicers d'un
        # groupe voisin p.ex.), sauf les éléments de la ligne elle-même
        exclude = set(line["before"]) | set(line["after"])
        cands = self._snap_edges(handle.vertical, exclude)
        W, H = self._page_size()
        if handle.vertical:
            lo_b = max(d["x"] for d in before) + MIN
            hi_b = min(d["x"] + d["w"] for d in after) - MIN
            coord = self._snap(pos.x(), cands)
            if W:
                coord = max(0.0, min(coord, W))
            coord = max(lo_b, min(coord, hi_b)) if lo_b <= hi_b else (lo_b + hi_b) / 2
            for d in before:
                self._set_item_box(d["id"], d["x"], d["y"], coord, d["y"] + d["h"])
            for d in after:
                self._set_item_box(d["id"], coord, d["y"], d["x"] + d["w"], d["y"] + d["h"])
            out = QPointF(coord, handle.pos().y())
        else:
            lo_b = max(d["y"] for d in before) + MIN
            hi_b = min(d["y"] + d["h"] for d in after) - MIN
            coord = self._snap(pos.y(), cands)
            if H:
                coord = max(0.0, min(coord, H))
            coord = max(lo_b, min(coord, hi_b)) if lo_b <= hi_b else (lo_b + hi_b) / 2
            for d in before:
                self._set_item_box(d["id"], d["x"], d["y"], d["x"] + d["w"], coord)
            for d in after:
                self._set_item_box(d["id"], d["x"], coord, d["x"] + d["w"], d["y"] + d["h"])
            out = QPointF(handle.pos().x(), coord)
        self._sync_dividers(exclude=handle)
        self._place_grips()                    # la sélection a pu être redimensionnée
        return out

    def _sync_dividers(self, exclude=None):
        """Recale chaque poignée sur la géométrie COURANTE de sa ligne ; masque
        celles dont la ligne n'a plus de contact."""
        for h in self._dividers:
            if h is not exclude:
                self._position_handle(h)

    def _divider_released(self):
        """Après un glisser de bordure : reconstruit proprement poignées de
        bordure ET de redimensionnement (les adjacences ont pu changer)."""
        self._rebuild_dividers()
        self._place_grips()

    # ---- poignées de redimensionnement de la sélection ---------------------------

    def _refresh_grips(self):
        """(Re)crée les 8 indicateurs autour de l'élément sélectionné du
        niveau actif (visuel ou groupe)."""
        for g in self._grips:
            self.scene.removeItem(g)
        self._grips = []
        d = self._data.get(self._selected_id)
        if not d or self._tier(d) != "active":
            return
        for hx in (-1, 0, 1):
            for hy in (-1, 0, 1):
                if hx == 0 and hy == 0:
                    continue
                g = ResizeGrip(hx, hy)
                self.scene.addItem(g)
                self._grips.append(g)
        self._place_grips()

    def _place_grips(self):
        """Repositionne les indicateurs sur les bords COURANTS de la sélection."""
        d = self._data.get(self._selected_id)
        if not d or not self._grips:
            return
        for g in self._grips:
            gx = d["x"] + (0 if g._hx < 0 else d["w"] if g._hx > 0 else d["w"] / 2)
            gy = d["y"] + (0 if g._hy < 0 else d["h"] if g._hy > 0 else d["h"] / 2)
            g.setPos(gx, gy)

    def _follow_item_grips(self, vid):
        """Pendant le drag d'un élément : ses indicateurs suivent le rect (la
        position _data n'est commitée qu'au relâchement)."""
        if vid != self._selected_id or not self._grips:
            return
        d = self._data.get(vid)
        rect = self._id_to_item.get(vid)
        if not d or rect is None:
            return
        px, py = rect.pos().x(), rect.pos().y()
        for g in self._grips:
            gx = px + (0 if g._hx < 0 else d["w"] if g._hx > 0 else d["w"] / 2)
            gy = py + (0 if g._hy < 0 else d["h"] if g._hy > 0 else d["h"] / 2)
            g.setPos(gx, gy)

    def _set_item_box(self, vid, x0, y0, x1, y1):
        """Applique une nouvelle boîte (absolue) à un élément. GROUPE : tout le
        sous-arbre est RÉÉCHELONNÉ proportionnellement (simulation ScaleMode —
        c'est ce que Desktop fait quand on redimensionne un groupe) ; chaque
        descendant devient dirty, car ses position/taille RELATIVES changent
        dans les fichiers. L'invariant du save tient : lx' = sx·lx."""
        d = self._data[vid]
        if d["is_group"] and d["w"] and d["h"]:
            ox0, oy0 = d["x"], d["y"]
            sx = (x1 - x0) / d["w"]
            sy = (y1 - y0) / d["h"]
            for did in self._descendants(vid):
                o = self._data[did]
                o["x"] = x0 + (o["x"] - ox0) * sx
                o["y"] = y0 + (o["y"] - oy0) * sy
                o["w"] *= sx
                o["h"] *= sy
                o["parent_x"] = x0 + (o["parent_x"] - ox0) * sx
                o["parent_y"] = y0 + (o["parent_y"] - oy0) * sy
                self._apply_geometry(did)
                self._mark_dirty(did)
        d["x"], d["y"], d["w"], d["h"] = x0, y0, x1 - x0, y1 - y0
        self._apply_geometry(vid)
        self._mark_dirty(vid)

    def _page_size(self):
        page = self.cmb_pages.currentData() or {}
        return (float(page.get("width", 0) or 0),
                float(page.get("height", 0) or 0))

    def _clamp_pos_to_page(self, vid, pos):
        """Contraint une position (QPointF) pour que l'élément reste dans la
        page (un élément plus grand que la page se cale à 0)."""
        d = self._data.get(vid)
        if not d:
            return pos
        W, H = self._page_size()
        x, y = pos.x(), pos.y()
        if W:
            x = max(0.0, min(x, W - d["w"]))
        if H:
            y = max(0.0, min(y, H - d["h"]))
        return QPointF(x, y)

    def _snap_edges(self, vertical, exclude):
        """Coordonnées candidates pour l'aimantation sur un axe : bords de la
        page + bords de TOUS les éléments VISIBLES du niveau actif, y compris
        ceux À L'INTÉRIEUR des groupes voisins (descendants) — pour aligner sur
        la structure vue à l'écran (bords des slicers d'un groupe voisin, etc.),
        pas seulement les frères directs. `exclude` = ids à ignorer."""
        page = self.cmb_pages.currentData() or {}
        cands = [0.0, float(page.get("width" if vertical else "height", 0))]
        for d in self._data.values():
            if d["id"] in exclude or self._tier(d) not in ("active", "inside"):
                continue
            cands += [d["x"], d["x"] + d["w"]] if vertical else [d["y"], d["y"] + d["h"]]
        return cands

    def _snap(self, value, cands):
        c = min(cands, key=lambda t: abs(t - value)) if cands else None
        return c if c is not None and abs(c - value) <= self.SNAP else value

    def _resize_edge_to(self, vid, hx, hy, scene_pos):
        """Déplace le(s) bord(s) (hx, hy) de l'élément vers scene_pos : bords
        aimantés (SNAP) à toute arête visible du niveau (frères ET intérieur des
        groupes voisins) et à la page ; taille min 20. Utilisé par la bande de
        bord des WireItem — visuels ET groupes (contenu rééchelonné)."""
        d = self._data[vid]
        MIN = 20.0
        W, H = self._page_size()
        cx = self._snap_edges(True, {vid})
        cy = self._snap_edges(False, {vid})
        x0, y0 = d["x"], d["y"]
        x1, y1 = d["x"] + d["w"], d["y"] + d["h"]
        if hx > 0:
            x1 = self._snap(scene_pos.x(), cx)
            x1 = max(x0 + MIN, min(x1, W) if W else x1)   # borné à la page
        elif hx < 0:
            x0 = max(0.0, self._snap(scene_pos.x(), cx))
            x0 = min(x1 - MIN, x0)
        if hy > 0:
            y1 = self._snap(scene_pos.y(), cy)
            y1 = max(y0 + MIN, min(y1, H) if H else y1)
        elif hy < 0:
            y0 = max(0.0, self._snap(scene_pos.y(), cy))
            y0 = min(y1 - MIN, y0)
        self._set_item_box(vid, x0, y0, x1, y1)
        self._sync_dividers()
        self._place_grips()

    def _grip_released(self):
        """Fin de redimensionnement : les adjacences ont pu changer."""
        self._rebuild_dividers()
        self._place_grips()

    def _mark_dirty(self, vid):
        self._dirty.add(vid)
        self._update_dirty_ui()

    def _update_dirty_ui(self):
        n = len(self._dirty)
        self.btn_save.setText(f"💾 Enregistrer ({n})" if n else "💾 Enregistrer")
        self.btn_save.setEnabled(n > 0)
        bouton_en_attente(
            self.btn_save, n > 0,
            en_attente=f"{n} élément(s) déplacé(s)/redimensionné(s) NON écrits : "
                       "cliquer pour écrire les visual.json\n"
                       "(backup automatique ; annulable par Ctrl+Z).",
            au_repos="Écrit les positions modifiées dans les visual.json "
                     "(backup automatique ; annulable par Ctrl+Z).")
        self.btn_cancel.setEnabled(bool(self._undo))

    def _status(self, msg):
        self.lbl_status.setText(msg)
        self.journal.info(msg)

    def save_all(self):
        """Point d'entrée de « Enregistrer puis recharger » (app)."""
        self._save_positions()

    def _save_positions(self):
        """Écrit les positions modifiées — sans confirmation : backup
        systématique + annulable (Ctrl+Z)."""
        if self.lecture_seule:
            return
        if not self._dirty or not self.project:
            return
        updates = {}
        for vid in self._dirty:
            d = self._data.get(vid)
            if not d:
                continue
            updates[d["path"]] = (round(d["x"] - d["parent_x"], 6),
                                  round(d["y"] - d["parent_y"], 6),
                                  round(d["w"], 6), round(d["h"], 6))
        try:
            n, backup_dir = report_reader.write_positions(
                updates, br.backup_root(self.project.folder, "_wireframe_backups"))
        except OSError as e:
            QMessageBox.critical(self, "Erreur d'écriture", str(e))
            return
        restored = {p: str(backup_dir / (Path(p).parent.name + "_visual.json"))
                    for p in updates}
        self._push_undo_files(f"Enregistrement de {n} position(s)", restored=restored)
        self._dirty = set()
        self._update_dirty_ui()
        self._status(f"💾 {n} élément(s) écrit(s) (backup {backup_dir.name}), "
                     "Ctrl+Z pour annuler. Rouvrir le .pbip pour voir le résultat.")

    # ---- annulation (Ctrl+Z) -----------------------------------------------------

    UNDO_MAX = 50

    def _push_undo_geom(self):
        """Empile l'état géométrique COMPLET de la page (avant un geste)."""
        self._undo.append({
            "kind": "geom",
            "boxes": {k: (v["x"], v["y"], v["w"], v["h"], v["parent_x"], v["parent_y"])
                      for k, v in self._data.items()},
            "dirty": set(self._dirty),
        })
        del self._undo[:-self.UNDO_MAX]
        self._update_dirty_ui()

    def _push_undo_files(self, label, created=None, restored=None):
        """Empile une action FICHIERS : `created` = visual.json à supprimer au
        undo ; `restored` = {chemin: backup} à réécrire au undo."""
        self._undo.append({"kind": "files", "label": label,
                           "created": [str(p) for p in (created or [])],
                           "restored": {str(k): str(v)
                                        for k, v in (restored or {}).items()}})
        del self._undo[:-self.UNDO_MAX]
        self._update_dirty_ui()

    def _undo_geom(self, entry):
        for vid, (x, y, w, h, px, py) in entry["boxes"].items():
            d = self._data.get(vid)
            if not d:
                continue
            d["x"], d["y"], d["w"], d["h"] = x, y, w, h
            d["parent_x"], d["parent_y"] = px, py
            self._apply_geometry(vid)
        self._dirty = set(entry["dirty"]) & set(self._data)
        self._update_dirty_ui()
        self._rebuild_dividers()
        self._place_grips()

    def _undo_last(self):
        """Ctrl+Z : annule le dernier geste (géométrie en mémoire) ou la
        dernière action fichiers (import / groupement / enregistrement…)."""
        if self.lecture_seule:
            return
        if not self._undo:
            return
        entry = self._undo.pop()
        if entry["kind"] == "geom":
            self._undo_geom(entry)
            self._status("↩ Dernier geste annulé.")
        else:
            # une sauvegarde peut avoir disparu (ménage : on ne garde que les
            # plus récentes par outil). Se taire laisserait croire que tout a
            # été annulé — on dit lesquels n'ont pas pu l'être.
            manquants = []
            try:
                for p in entry["created"]:
                    if Path(p).parent.exists():
                        report_reader.rmtree_force(Path(p).parent)
                for p, bak in entry["restored"].items():
                    bak = Path(bak)
                    if not bak.exists():
                        manquants.append(Path(p).parent.name)
                        continue
                    dst = Path(p)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text(bak.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError as e:
                QMessageBox.critical(self, "Annulation impossible", str(e))
                self._update_dirty_ui()
                return
            self._reload_keep_page()
            if manquants:
                QMessageBox.warning(
                    self, "Annulation incomplète",
                    f"{len(manquants)} élément(s) n'ont pas pu être remis en "
                    "place : leur sauvegarde n'existe plus (le dossier ne "
                    f"garde que les {br.MAX_SESSIONS} plus récentes).\n\n"
                    + ", ".join(manquants))
            self._status(f"↩ {entry['label']}, annulé."
                         + (f"  ⚠ {len(manquants)} sans sauvegarde."
                            if manquants else ""))
        self._update_dirty_ui()

    def _reload_keep_page(self):
        """Relit le disque en restant sur la page courante (le _reload simple
        retombe sur la première page)."""
        page = self.cmb_pages.currentData()
        pid = page["id"] if page else None
        self._reload()
        if pid:
            for i in range(self.cmb_pages.count()):
                data = self.cmb_pages.itemData(i)
                if data and data["id"] == pid:
                    if self.cmb_pages.currentIndex() != i:
                        self.cmb_pages.setCurrentIndex(i)   # déclenche _build_page
                    break

    # ---- gabarits ----------------------------------------------------------------

    CLE_TPL_GLOBAL = "template_pbip"      # le dernier choisi, tous projets

    def _tpl_key(self):
        return "template_pbip::" + str(self.project.pbip)

    def _tpl_load_for_project(self):
        """Gabarit de CE projet, sinon le DERNIER choisi où que ce soit.

        Un choix propre au projet reste prioritaire ; le repli global évite de
        redésigner le même gabarit à chaque nouveau rapport, alors qu'on se
        sert en général toujours du même."""
        pbip = self.settings.value(self._tpl_key(), "") if self.project else ""
        self._tpl_set(pbip or lire_reglage(self.CLE_TPL_GLOBAL, "") or "")

    def _tpl_choose(self):
        start = str(self._tpl_project.pbip) if self._tpl_project else (
            str(self.project.folder) if self.project else "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir le PBIP gabarit", start, "Projet Power BI (*.pbip)")
        if path:
            self.settings.setValue(self._tpl_key(), path)
            ecrire_reglage(self.CLE_TPL_GLOBAL, path)   # et comme repli global
            self._tpl_set(path)

    def _tpl_set(self, pbip):
        self._tpl_project = None
        self._tpl_models = []
        self._tpl_bases = []
        self.cmb_tpl_pages.blockSignals(True)
        self.cmb_tpl_pages.clear()
        self.lst_models.clear()
        if pbip and Path(pbip).exists():
            proj = Project(pbip)
            if proj.report_dir.exists():
                self._tpl_project = proj
        if self._tpl_project is None:
            self.lbl_tpl.setText("(gabarit introuvable)" if pbip
                                 else "(aucun gabarit choisi)")
            self.lbl_tpl.setStyleSheet(f"color:{TEXT_MUTED};")
            self.lbl_tpl.setToolTip(str(pbip) if pbip else "")
            self.cmb_tpl_pages.blockSignals(False)
            self._tpl_update_button()
            return
        self.lbl_tpl.setText(Path(pbip).name)
        self.lbl_tpl.setStyleSheet(f"color:{TEXT};")
        self.lbl_tpl.setToolTip(str(pbip))
        self._tpl_models = template_import.list_models(self._tpl_project.report_dir)
        # le config du gabarit s'il en a un, sinon celui du rapport : il dit
        # où sont les mesures de base (table et dossier)
        config = self._lire_config(self._tpl_project) or self._lire_config(self.project)
        self._tpl_bases = self._bases_de(self._tpl_project, config)
        seen = []
        for m in self._tpl_models:
            if m["page_id"] not in seen:
                seen.append(m["page_id"])
                self.cmb_tpl_pages.addItem(m["page_display"], m["page_id"])
        self.cmb_tpl_pages.blockSignals(False)
        self._tpl_refresh_models()

    def _tpl_refresh_models(self, *_):
        self.lst_models.clear()
        pid = self.cmb_tpl_pages.currentData()
        models = [m for m in self._tpl_models if m["page_id"] == pid] if pid else []
        for m in models:
            if m["kind"] == "groupe":
                label = "📦 {0}  ({1} visuel(s), {2:.0f}×{3:.0f})".format(
                    m["name"], m["n_files"] - 1, m["w"], m["h"])
            else:
                label = "{0} · {1}".format(m["kind"], m["name"])
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, m["root_id"])
            self.lst_models.addItem(it)
        if not models:
            it = QListWidgetItem("(aucun modèle sur cette page)")
            it.setFlags(Qt.NoItemFlags)
            self.lst_models.addItem(it)
        self._tpl_update_button()

    @staticmethod
    def _lire_config(projet) -> dict:
        try:
            return json.loads(projet.config_json.read_text(encoding="utf-8"))
        except (AttributeError, OSError, ValueError):
            return {}

    @staticmethod
    def _bases_de(projet, config) -> list:
        """Les ICP (mesures de base) d'un projet, triés comme Power BI ; []
        si le modèle est illisible."""
        try:
            return list(gm.read_measures(projet.model_dir, config or {})[1])
        except (AttributeError, OSError, TypeError, ValueError):
            return []

    def _tpl_refresh_icp(self, *_):
        """Une rangée par ICP cité par le modèle sélectionné : l'ICP du
        gabarit, et à côté l'ICP du rapport qui le remplacera. Par défaut
        chacun se garde lui-même (le même nom, s'il existe ici)."""
        while self.icp_form.rowCount():
            self.icp_form.removeRow(0)
        self._icp_combos = {}
        sel = self.lst_models.selectedItems()
        model = None
        if sel and self._tpl_project is not None:
            rid = sel[0].data(Qt.UserRole)
            model = next((m for m in self._tpl_models if m["root_id"] == rid), None)
        if model is None:
            self.lbl_icp.setVisible(False)
            return
        cibles = self._bases_de(self.project, self._lire_config(self.project))
        trouves = template_import.indicateurs_du_modele(
            self._tpl_project.report_dir, model["page_id"], model["root_id"],
            list(self._tpl_bases) + cibles)
        self.lbl_icp.setVisible(True)
        if not trouves:
            self.lbl_icp.setText("Indicateurs du modèle : aucun")
            return
        self.lbl_icp.setText("Indicateurs du modèle, remplacés à l'import par :")
        for icp in trouves:
            cmb = QComboBox()
            if icp not in cibles:
                cmb.addItem(f"{icp} (absent de ce rapport)", icp)
            for c in cibles:
                cmb.addItem(c, c)
            cmb.setCurrentIndex(max(0, cmb.findData(icp)))
            self.icp_form.addRow(QLabel(icp + " →"), cmb)
            self._icp_combos[icp] = cmb

    def _tpl_remplacements(self) -> dict:
        return {icp: cmb.currentData() for icp, cmb in self._icp_combos.items()
                if cmb.currentData() and cmb.currentData() != icp}

    def _tpl_update_button(self, *_):
        sel = self.lst_models.selectedItems()
        self.btn_import.setEnabled(bool(
            self._tpl_project is not None
            and sel and sel[0].data(Qt.UserRole)
            and self.cmb_pages.currentData()))

    def _tpl_import(self):
        if self.lecture_seule:
            return
        sel = self.lst_models.selectedItems()
        page = self.cmb_pages.currentData()
        if not sel or not page or self._tpl_project is None or not self.project:
            return
        if self._dirty:
            self._save_positions()             # silencieux : backupé + annulable
        root_id = sel[0].data(Qt.UserRole)
        model = next((m for m in self._tpl_models if m["root_id"] == root_id), None)
        if model is None:
            return
        remplacements = self._tpl_remplacements()
        bases = list(self._tpl_bases) + self._bases_de(
            self.project, self._lire_config(self.project))
        try:
            new_root, written, manifest = template_import.import_model(
                self._tpl_project.report_dir, model["page_id"], root_id,
                self.project.report_dir, page["id"],
                br.backup_root(self.project.folder, "_wireframe_backups"),
                remplacements=remplacements, bases=bases)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Erreur d'import", str(e))
            return
        self._reload_keep_page()
        self._push_undo_files(f"Import de « {model['name']} »", created=written)
        self._set_scope(None)                  # l'import atterrit à la racine
        self._select(new_root, from_tree=False)
        warn = (" ⚠ déborde de la page (position d'origine conservée)."
                if (model["x"] + model["w"] > page["width"]
                    or model["y"] + model["h"] > page["height"]) else "")
        icp = "".join(f" {a} → {b}." for a, b in remplacements.items())
        absentes = template_import.mesures_absentes(written, self.project.model_dir)
        if absentes:
            liste = ", ".join(absentes[:3]) + (" …" if len(absentes) > 3 else "")
            warn += (f" ⚠ {len(absentes)} mesure(s) absente(s) de ce rapport "
                     f"({liste}) : ces visuels resteront vides.")
        self._status(f"📥 « {model['name']} » importé ({len(written)} fichier(s), "
                     f"manifeste {manifest.parent.name}).{icp}{warn} "
                     "Ctrl+Z pour annuler.")
        if len(absentes) > 3:
            self.journal.info("Mesures absentes : " + ", ".join(absentes))
