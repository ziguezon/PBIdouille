# -*- coding: utf-8 -*-
"""Thème partagé des outils — palette « Dark Teal Pro », le thème néon des
rapports Power BI (Fitbit ...Report\\StaticResources\\RegisteredResources\\
Dark_Teal_Pro*.json) : vert néon sur fonds bleu nuit.

Le QSS est AUTONOME (aucune dépendance qdarkstyle) → rendu identique à la
maison (PySide6/Qt6) et au travail (PyQt5/Qt5). ChopChopRapport importe ce
module ; BIdouille aussi. Icône émoji et identité Windows incluses."""

from __future__ import annotations

import tempfile
from pathlib import Path

from qtpy.QtCore import QPointF, Qt
from qtpy.QtGui import (QColor, QFont, QIcon, QPainter, QPainterPath, QPen,
                        QPixmap)
from qtpy.QtWidgets import QSplitter, QSplitterHandle

# ---- palette Dark Teal Pro (mêmes hex que le thème Power BI) ---------------
BG_WINDOW   = "#0F1629"   # fond de fenêtre (= fond de page du rapport)
BG_DARKEST  = "#090D1A"   # wallpaper (zones creuses : éditeurs, journaux)
SURFACE     = "#162032"   # surfaces : groupbox, champs, cartes
SURFACE_ALT = "#1A2640"   # lignes alternées / éléments discrets
BORDER      = "#1E2D3D"   # bordures, survols, entêtes
ACCENT      = "#56C596"   # vert néon — couleur principale
ACCENT_DIM  = "#3D8F6D"   # vert atténué (pressed / bordures actives)
TEXT        = "#E2E8F0"   # texte principal
TEXT_DIM    = "#C8D4E0"   # texte secondaire
TEXT_MUTED  = "#7F898A"   # texte désactivé / grisé
RED         = "#E8604E"   # sémantique « bad »
ORANGE      = "#E8873A"   # « il y a quelque chose à écrire » (bouton en attente)
YELLOW      = "#D4AE28"   # sémantique « neutral »
BLUE        = "#38BDF8"   # sémantique secondaire
GREEN       = ACCENT      # sémantique « good » = l'accent
# un trait de séparation (poignées, journal) : entre BORDER, trop pâle sur
# les fonds sombres, et TEXT_MUTED, trop présent pour un simple séparateur
TRAIT       = "#2E4560"

# titres de groupe : leur police et leur taille (le texte courant est en
# Segoe UI 9 pt). Bahnschrift — la DIN de Windows 10 et 11 — les distingue
# du texte autrement que par la couleur. Nommée par son instance
# « SemiBold » : ce nom-là marche aussi avec le moteur de polices GDI de
# Qt 5 (poste du travail). Absente (Windows ancien) : Qt retombe sur la
# police par défaut.
TITRE_POLICE = "Bahnschrift SemiBold"
TITRE_PT = 11

# rétro-compatibilité (ancien accent rose de ChopChopRapport)
HOT_PINK = ACCENT


def emoji_icon(emoji: str) -> QIcon:
    """Icône d'app à partir d'un émoji (Segoe UI Emoji, couleur native
    Windows) — aucun fichier .ico à trimballer."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        f = QFont("Segoe UI Emoji")
        f.setPixelSize(int(size * 0.82))
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, emoji)
        p.end()
        icon.addPixmap(pm)
    return icon


def _write_indicator_icons() -> tuple:
    """Peint la coche et le tiret VERT NÉON en PNG dans le dossier temp et
    retourne leurs chemins (les stylesheets Qt exigent des fichiers). PNG
    plutôt que SVG : PyQt5 (poste du travail) n'a pas toujours le plugin SVG
    et l'échec serait silencieux.

    Trait fin (1,6 px), extrémités nettes et angle vif : l'ancienne coche —
    2,2 px, bouts et angle ARRONDIS — faisait une tache ronde dans la case.
    Elle est aussi plus petite, avec de l'air autour.

    Chaque image existe aussi en « @2x » : Qt la choisit d'office sur un
    écran à 150 % ou 200 %, où la version simple serait agrandie, donc floue
    — et floue, une coche fine redevient ronde."""
    d = Path(tempfile.gettempdir())
    check_path = d / "bidouille_check.png"
    dash_path = d / "bidouille_dash.png"

    for path, kind in ((check_path, "check"), (dash_path, "dash")):
        for echelle, suffixe in ((1, ""), (2, "@2x")):
            pm = QPixmap(15 * echelle, 15 * echelle)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.scale(echelle, echelle)
            pen = QPen(QColor(ACCENT))
            pen.setWidthF(1.6)
            pen.setCapStyle(Qt.FlatCap)
            pen.setJoinStyle(Qt.MiterJoin)
            p.setPen(pen)
            if kind == "check":
                trace = QPainterPath(QPointF(4.2, 7.6))
                trace.lineTo(6.6, 10.0)
                trace.lineTo(10.9, 5.0)
                p.drawPath(trace)
            else:
                p.drawLine(QPointF(4.5, 7.5), QPointF(10.5, 7.5))
            p.end()
            pm.save(str(path.with_name(path.stem + suffixe + path.suffix)), "PNG")

    return check_path.as_posix(), dash_path.as_posix()


def _indicator_qss(scopes: str) -> str:
    """Règles d'indicateur (case à cocher) pour les sélecteurs donnés :
    carré sombre, bord vert au survol, coche/tiret verts. `scopes` est une
    liste de sélecteurs « X::indicator » séparés par des virgules."""
    check, dash = _write_indicator_icons()

    def variant(state: str) -> str:
        return ", ".join(s.strip() + state for s in scopes.split(","))

    return f"""
{scopes} {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {SURFACE_ALT};
}}
{variant(":hover")} {{ border-color: {ACCENT}; }}
{variant(":checked")} {{
    image: url("{check}");
    border-color: {ACCENT};
}}
{variant(":indeterminate")} {{
    image: url("{dash}");
    border-color: {ACCENT};
}}
"""


def bouton_en_attente(bouton, actif: bool, en_attente: str = "",
                      au_repos: str = "") -> None:
    """Allume un bouton en ORANGE tant qu'il reste quelque chose à écrire.

    Remplace le voyant « ● modifications non sauvegardées » posé à côté :
    l'état se lit sur le bouton qui le résout, donc l'œil n'a qu'un endroit à
    regarder et le remède est là où est le symptôme.

    Le QSS d'app est redonné en entier (fond, bordure, coins, marge) : une
    feuille de style posée sur un widget REMPLACE celle de l'application pour
    lui, et sans ça le bouton changerait de forme en s'allumant."""
    bouton.setStyleSheet(f"""
QPushButton {{
    background: {ORANGE};
    color: {BG_WINDOW};
    border: 1px solid {ORANGE};
    border-radius: 6px;
    padding: 5px 14px;
    font-weight: bold;
}}
QPushButton:hover {{ background: {TEXT}; border-color: {TEXT}; }}
QPushButton:pressed {{ background: {ACCENT_DIM}; border-color: {ACCENT_DIM}; }}
""" if actif else "")
    if en_attente or au_repos:
        bouton.setToolTip(en_attente if actif else au_repos)


def police_code(widget, petit: bool = False) -> None:
    """Marque `widget` comme du CODE : chasse fixe (Consolas), via le thème.

    Pourquoi pas setFont() : le QSS d'app fixe `font-family` sur TOUS les
    widgets, et une feuille de style l'emporte sur setFont() — l'éditeur
    DAX s'affichait donc en Segoe UI depuis toujours : un retrait de 4
    espaces y faisait 12 px, et l'aide-mémoire des jetons perdait ses
    colonnes. Seule une règle plus PRÉCISE gagne : l'attribut code=… (cf.
    neon_stylesheet). Le setFont reste pour un widget montré SANS le thème
    (tests, fenêtre autonome).

    À appeler AVANT le premier affichage : la feuille de style est appliquée
    au moment où le widget se montre."""
    widget.setProperty("code", "petit" if petit else "true")
    widget.setFont(QFont("Consolas", 8 if petit else 9))


def rangee_transparente(widget) -> None:
    """Un conteneur de rangée (libellé + champ + ⓘ) sans fond : dans un
    groupe, il laisse voir la surface du groupe au lieu d'y découper une
    bande couleur fenêtre."""
    widget.setProperty("fond", "aucun")


class _Poignee(QSplitterHandle):
    """Poignée d'un Separateur : un trait d'un pixel au milieu de sa bande,
    en retrait des bords, vert atténué au survol (on voit qu'elle se saisit)."""

    RETRAIT = 8     # px laissés libres aux deux bouts du trait

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WA_Hover, True)

    def enterEvent(self, ev):
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, ev):
        # pas de super() : le QSS « QSplitter::handle » peindrait la bande
        # ENTIÈRE, c'est précisément ce qu'on ne veut plus
        p = QPainter(self)
        p.setPen(QPen(QColor(ACCENT_DIM if self.underMouse() else TRAIT), 1))
        r, m = self.rect(), self.RETRAIT
        if self.orientation() == Qt.Horizontal:
            x = r.width() // 2
            p.drawLine(x, r.top() + m, x, r.bottom() - m)
        else:
            y = r.height() // 2
            p.drawLine(r.left() + m, y, r.right() - m, y)
        p.end()


class Separateur(QSplitter):
    """QSplitter dont la poignée est un TRAIT FIN au milieu d'une bande d'air.

    La poignée par défaut est une barre pleine de 4 px, collée aux volets : les
    groupes butaient dessus. Ici la bande fait LARGEUR px — une prise facile à
    attraper — et seul son milieu est dessiné : 6 px d'air de chaque côté.

    Pas de QSS pour ça : pour dimensionner une poignée stylée, Qt lit la règle
    « QSplitter::handle:vertical » même pour un splitter HORIZONTAL (constaté
    en Qt 6), et ignore largeur et marges sinon. La poignée est donc dessinée
    à la main — même rendu en Qt5 et en Qt6."""

    LARGEUR = 13

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setHandleWidth(self.LARGEUR)

    def createHandle(self):
        return _Poignee(self.orientation(), self)


def checkable_list_stylesheet() -> str:
    """Style des cases à cocher pour QListWidget/QTreeWidget (utile seul si le
    QSS global n'est pas appliqué ; sinon redondant et inoffensif)."""
    return ("QListWidget::item, QTreeWidget::item { padding: 1px 2px; }"
            + _indicator_qss("QListWidget::indicator, QTreeWidget::indicator"))


def neon_stylesheet() -> str:
    """QSS complet de l'app : Dark Teal Pro — fonds bleu nuit, accent vert."""
    return f"""
/* ---- base -------------------------------------------------------------- */
QWidget {{
    background: {BG_WINDOW};
    color: {TEXT};
    font-family: "Segoe UI";
    font-size: 9pt;
}}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QToolTip {{
    background: {BORDER};
    color: {TEXT};
    border: 1px solid {ACCENT_DIM};
    padding: 3px 6px;
}}

/* ---- groupes ------------------------------------------------------------
   Le titre se lit comme un TITRE : dans sa propre police (TITRE_POLICE), et
   DANS le cadre, posé à cheval sur la bordure, le trait le barrait. La
   marge du haut du cadre lui est réservée (padding-top), le contenu commence
   dessous.

   Qt ignore toute police posée sur « QGroupBox::title » : le titre prend
   celle du GROUPE. Le groupe la porte donc, et ses enfants directs repartent
   en poids normal (leur famille et leur taille, la règle QWidget les fixe
   déjà widget par widget). Qt 6 ne transmet pas le poids aux enfants ; Qt 5
  , celui du poste du travail, est connu pour le faire, d'où cette remise à
   zéro, sans effet ici mais sans coût. */
QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 0px;
    padding: 24px 6px 6px 6px;
    font-family: "{TITRE_POLICE}";
    font-size: {TITRE_PT}pt;
    font-weight: normal;
}}
QGroupBox > QWidget {{ font-weight: normal; }}
QGroupBox::title {{
    subcontrol-origin: padding;
    subcontrol-position: top left;
    left: 11px;
    top: 7px;
    padding: 0;
    color: {ACCENT};
    background: transparent;
}}

/* ---- boutons ------------------------------------------------------------ */
QPushButton {{
    background: {SURFACE_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 14px;
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; color: {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: {SURFACE_ALT}; }}
QPushButton:default {{ border-color: {ACCENT_DIM}; }}

/* ---- champs ------------------------------------------------------------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {SURFACE_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 6px;
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled {{ color: {TEXT_MUTED}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_DIM};
    margin-right: 5px;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT};
    outline: none;
}}

/* ---- code : chasse fixe ------------------------------------------------------
   La règle QWidget ci-dessus fixe font-family sur TOUS les widgets, ce qui
   écrase le moindre setFont(). Un widget marqué code=… (cf. police_code)
   reprend la main : un attribut est plus précis qu'un type. */
*[code="true"] {{ font-family: Consolas, "Courier New"; font-size: 9pt; }}
*[code="petit"] {{ font-family: Consolas, "Courier New"; font-size: 8pt; }}

/* ---- rangées de formulaire : sans fond propre ------------------------------
   Un QWidget nu peint BG_WINDOW : posé dans un groupe (SURFACE), il y
   dessinait une bande sombre derrière ses champs (cf. rangee_transparente). */
*[fond="aucun"] {{ background: transparent; }}

/* ---- éditeurs / journaux -------------------------------------------------*/
QPlainTextEdit, QTextEdit {{
    background: {BG_DARKEST};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT};
}}

/* ---- listes / arbres / tables -------------------------------------------*/
QListWidget, QTreeWidget, QTreeView, QTableView, QListView {{
    background: {SURFACE};
    alternate-background-color: {SURFACE_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{ padding: 1px 2px; }}
QListWidget::item:selected, QTreeWidget::item:selected,
QTreeView::item:selected, QListView::item:selected {{
    background: {ACCENT_DIM};
    color: {TEXT};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {SURFACE_ALT}; }}
QHeaderView::section {{
    background: {BORDER};
    color: {ACCENT};
    border: none;
    border-right: 1px solid {SURFACE};
    padding: 4px 6px;
}}

/* ---- onglets ------------------------------------------------------------ */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    background: {SURFACE_ALT};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 16px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {SURFACE};
    color: {ACCENT};
    border-color: {ACCENT_DIM};
}}
QTabBar::tab:hover:!selected {{ color: {ACCENT}; }}
/* les onglets de l'app : plus grands, un vrai niveau de navigation */
/* Qt 5 mesure le texte avec la police de la barre, y compris à DPI élevé. */
QTabWidget#ongletsPrincipaux > QTabBar {{
    font-size: 10pt;
    font-weight: 600;
}}
QTabWidget#ongletsPrincipaux > QTabBar::tab {{
    padding: 7px 22px;
}}
/* les sous-onglets (Mesures) : un soulignement, pas des cartes. Deux niveaux
   au même style se lisaient comme une seule rangée coupée en deux */
QTabWidget#sousOnglets::pane {{
    border: none;
    border-top: 1px solid {BORDER};
    border-radius: 0;
    top: 0;
}}
QTabWidget#sousOnglets > QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 5px 12px;
    margin-right: 4px;
}}
QTabWidget#sousOnglets > QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}

/* ---- le ruban ------------------------------------------------------------ */
QToolButton#btnProjet {{
    background: {SURFACE_ALT};
    color: {ACCENT};
    border: 1px solid {ACCENT_DIM};
    border-radius: 6px;
    padding: 5px 12px;
    font-weight: 600;
}}
QToolButton#btnProjet:hover {{ border-color: {ACCENT}; }}
QToolButton#btnProjet::menu-indicator {{ image: none; width: 0; }}
QPushButton#btnConfig {{
    background: transparent;
    border: 1px solid transparent;
    text-align: left;
    padding: 5px 8px;
}}
QPushButton#btnConfig:hover {{ border-color: {BORDER}; }}

/* ---- cases à cocher ------------------------------------------------------*/
{_indicator_qss("QCheckBox::indicator, QListWidget::indicator, QTreeWidget::indicator")}

/* ---- barres de défilement ------------------------------------------------*/
QScrollBar:vertical {{
    background: {BG_WINDOW}; width: 11px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 5px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DIM}; }}
QScrollBar:horizontal {{
    background: {BG_WINDOW}; height: 11px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER}; border-radius: 5px; min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background: {ACCENT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---- divers --------------------------------------------------------------*/
QSplitter::handle {{ background: {BORDER}; }}
QStatusBar {{ background: {SURFACE}; color: {TEXT_DIM}; }}
QMenu {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
}}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QMessageBox {{ background: {SURFACE}; }}
"""


def apply_app_theme(app, emoji: str, app_id: str) -> None:
    """Applique le thème néon et l'identité Windows sur le QApplication (une
    fois). Le QSS étant autonome, le rendu est le même avec PyQt5 (travail)
    et PySide6 (maison). Pose aussi l'icône de fenêtre."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass
    app.setStyleSheet(neon_stylesheet())
    app.setWindowIcon(emoji_icon(emoji))
