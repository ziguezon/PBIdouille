# -*- coding: utf-8 -*-
"""Onglet « Mesures » : édite measures_config.json, trois vues du MÊME config
en mémoire :
  - « Variations » (sous-onglet) : un formulaire par variation (nom, options,
    DAX en clair) — le format JSON array-of-lines devient invisible ;
  - « JSON brut » (sous-onglet) : tout le fichier, pour les cas non couverts ;
  - la fenêtre « ⚙ Réglages » (barre du haut) : settings, fieldParameter,
    branches… en cases et champs — ils servent aussi à l'onglet
    Rapport, d'où leur fenêtre à eux (cf. ouvrir_reglages).

Synchronisation : à chaque changement de sous-onglet, celui qu'on QUITTE est
committé dans le config en mémoire, celui qu'on OUVRE est rechargé depuis lui
(le JSON brut invalide bloque le changement). Sauvegarder : backup
measures_config.json.bak puis écriture indent=2.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from qtpy.QtCore import QEvent, Qt, QTimer, Signal
from qtpy.QtGui import (QColor, QFont, QStandardItem, QStandardItemModel,
                        QSyntaxHighlighter, QTextCharFormat, QTextCursor)
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import model_reader
from core.journal import Journal
from core.project import ecrire_reglage, lire_reglage
from core.theme import (ACCENT, BLUE, RED, YELLOW, TEXT_DIM, TEXT_MUTED,
                        Separateur, bouton_en_attente,
                        checkable_list_stylesheet, police_code,
                        rangee_transparente)
from tabs.tab_model import ModelTab
from tabs.fp_tables import EditeurTablesParametre
from tabs.dialog_guide import bouton_schema
from tabs.arbre_mesures import ArbreMesures
from tabs.apercu_parametres import ApercuParametres
from tabs.fiche_mesure import ROLE_HTML, DelegueRiche, ajouter_attributs
from tabs.explorateur_jetons import FenetreJetons, nom_attribut

import backup_restore as br
import xlsx_lecture as xl
import generate_measures as gm   # scan_cibles : mêmes règles que la génération

# index des sous-onglets de l'onglet « Mesures » (la génération n'a plus
# d'onglet : son panneau est posé en tête du journal)
IDX_VARIATIONS, IDX_ARBRE, IDX_PARAM, IDX_RAW = 0, 1, 2, 3

# largeur d'une TABULATION dans l'éditeur DAX, en caractères (cf. DaxEdit)
# — au lieu des 80 px de Qt, une dizaine de caractères
INDENT_DAX = 4

# placeholders compris par le générateur (generate_measures.py) ; tout autre {jeton}
# serré (sans espaces) est probablement une faute de frappe. « { ad } » avec
# espaces = constructeur de table DAX, jamais signalé.
KNOWN_PLACEHOLDERS = {
    "base", "baseRef", "date", "variation", "deltaScale",
    "kpi", "kpiRef", "folder", "baseFolder", "baseFormat", "branch",
    "baseFormatString",  # le format de la base, en chaîne DAX (FORMAT)
    "variationRef",     # enveloppe de branche : la mesure Réel de la variation
}

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# l'aperçu des noms générés, en couleur : la racine (KPI ou cible) telle
# quelle, et ce que chaque niveau lui AJOUTE — la branche, puis la variation.
# C'est la partie qu'on vient vérifier : elle doit sauter aux yeux.
COULEURS_APERCU = {"etiquette": TEXT_MUTED, "racine": TEXT_DIM,
                   "branche": BLUE, "variation": ACCENT}
JETON_NOM = re.compile(r"\{(base|kpi|variation|branch)\}")

# jetons <<…>> INTÉGRÉS : ceux de l'ancien réglage kpiTables. Tirés du
# moteur lui-même, pour ne pas diverger de ce qu'il sait remplacer.
JETONS_PORTEE = frozenset(gm.kpi_table_tokens(["t"]))
EACH_DEBUT = re.compile(r"<<each\s")


def reperer_jetons(texte: str, accolades, chevrons, dans_each=False):
    """Les jetons d'un texte DAX : ([(début, fin, genre, connu)], état).

    genre : « accolade » ({base}), « chevron » (<<label>>, un attribut codé
    en dur ou un jeton de portée), « each » (les bornes de <<each … >>).
    `état` dit si le texte s'arrête DANS un <<each … >> — il peut courir
    sur plusieurs lignes, et le surligneur travaille ligne par ligne.

    Dans un <<each … >>, {table} est connu : c'est le jeton que le moteur
    y remplace, table par table (cf. generate_measures.expand_each).
    « { ad } » avec espaces reste un constructeur de table DAX : ignoré."""
    spans, zones = [], []
    pos, n = 0, len(texte)
    if dans_each:                    # suite d'un <<each ouvert plus haut
        f = texte.find(">>")
        if f < 0:
            zones.append((0, n))
            pos = n
        else:
            zones.append((0, f))
            spans.append((f, f + 2, "each", True))
            pos, dans_each = f + 2, False
    while pos < n:
        d = texte.find("<<", pos)
        if d < 0:
            break
        m = EACH_DEBUT.match(texte, d)
        f = texte.find(">>", d + 2)
        if m:
            spans.append((d, m.end(), "each", True))
            if f < 0:
                zones.append((m.end(), n))
                dans_each = True
                break
            zones.append((m.end(), f))
            spans.append((f, f + 2, "each", True))
        else:
            if f < 0:
                break                # « << » sans fermeture : pas un jeton
            spans.append((d, f + 2, "chevron", texte[d + 2:f] in chevrons))
        pos = f + 2
    for m in PLACEHOLDER_RE.finditer(texte):
        dedans = any(a <= m.start() < b for a, b in zones)
        connu = m.group(1) in accolades or (dedans and m.group(1) == "table")
        spans.append((m.start(), m.end(), "accolade", connu))
    return spans, dans_each


def segments_nom(motif: str, base: list, valeurs: dict, style: str) -> list:
    """Développe un namePattern en segments [(texte, style)].

    `{base}` devient les segments de `base` (déjà colorés par le niveau
    d'en dessous) ; `{kpi}`, `{variation}`, `{branch}` prennent le texte ET
    le style donnés dans `valeurs` ; le texte littéral du motif prend
    `style` — c'est ce que CE niveau ajoute au nom. Concaténés, les
    segments redonnent exactement le nom que produit la génération."""
    out, pos = [], 0
    for m in JETON_NOM.finditer(motif):
        if m.start() > pos:
            out.append((motif[pos:m.start()], style))
        if m.group(1) == "base":
            out.extend(base)
        else:
            texte, st = valeurs.get(m.group(1), ("", style))
            if texte:
                out.append((texte, st))
            elif m.group(1) == "branch":
                # pas de branche : le jeton s'efface avec UNE espace voisine,
                # celle d'avant de préférence (cf. remplacer_branche)
                if (motif[m.start() - 1:m.start()] == " " and out
                        and out[-1][0].endswith(" ")):
                    t, st0 = out.pop()
                    if t[:-1]:
                        out.append((t[:-1], st0))
                elif motif[m.end():m.end() + 1] == " ":
                    pos = m.end() + 1
                    continue
        pos = m.end()
    if pos < len(motif):
        out.append((motif[pos:], style))
    return out

# gabarit d'une nouvelle variation
NEW_VARIATION = {
    "namePattern": "{base} X",
    "inFieldParameter": False,
    "dax": "",
    "formatString": "inherit",
    "description": "",
}


def dax_to_text(dax) -> str:
    """dax du JSON (str ou liste de lignes) -> texte éditable."""
    if isinstance(dax, list):
        return "\n".join(str(x) for x in dax)
    return str(dax) if dax is not None else ""


def text_to_dax(text: str):
    """Texte de l'éditeur -> valeur JSON : liste de lignes si multiligne,
    chaîne sinon (round-trip fidèle des deux formes du config)."""
    text = text.rstrip("\n")
    if "\n" in text:
        return text.split("\n")
    return text


def lines_to_list(text: str) -> list:
    """Zone multiligne -> liste (une entrée par ligne non vide)."""
    return [l.strip() for l in text.splitlines() if l.strip()]


def list_to_lines(value) -> str:
    """Liste JSON -> zone multiligne (une entrée par ligne)."""
    return "\n".join(str(x) for x in value) if isinstance(value, list) else ""


class CheckCombo(QComboBox):
    """Liste déroulante à cases : multi-choix, mais UNE seule ligne à l'écran
    qui affiche la sélection. Remplace une rangée de cases quand le vocabulaire
    peut s'allonger (les types de mesure viennent en partie d'une colonne
    Excel, donc leur nombre n'est pas connu d'avance)."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModel(QStandardItemModel(self))
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.view().pressed.connect(self._toggle)

    def set_items(self, items, checked=None):
        """`checked=None` = tout coché (= aucun filtre)."""
        m = self.model()
        m.clear()
        for nom in items:
            it = QStandardItem(nom)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            coche = Qt.Checked if (checked is None or nom in checked) else Qt.Unchecked
            it.setData(coche, Qt.CheckStateRole)
            m.appendRow(it)
        self._refresh_text()

    def checked(self) -> list:
        m = self.model()
        return [m.item(i).text() for i in range(m.rowCount())
                if m.item(i).checkState() == Qt.Checked]

    def all_checked(self) -> bool:
        return len(self.checked()) == self.model().rowCount()

    def _toggle(self, index):
        it = self.model().itemFromIndex(index)
        it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
        self._refresh_text()
        self.changed.emit()

    def _refresh_text(self):
        coches = self.checked()
        if self.all_checked():
            self.lineEdit().setText("tous")
        else:
            self.lineEdit().setText(", ".join(coches) or "aucun !")


class SurligneurJetons(QSyntaxHighlighter):
    """Colore les jetons du DAX à la frappe : {connus} en bleu, <<connus>>
    en vert, INCONNUS en rouge souligné — la faute de frappe se voit en
    l'écrivant, plutôt qu'au journal de la génération (où la mesure est
    sautée, ou fausse)."""

    def __init__(self, document):
        super().__init__(document)
        self.accolades = frozenset(KNOWN_PLACEHOLDERS)
        self.chevrons = frozenset(JETONS_PORTEE)
        self._formats = {}
        for cle, couleur in ((("accolade", True), BLUE),
                             (("chevron", True), ACCENT),
                             (("each", True), ACCENT)):
            f = QTextCharFormat()
            f.setForeground(QColor(couleur))
            f.setFontWeight(QFont.Bold)
            self._formats[cle] = f
        inconnu = QTextCharFormat()
        inconnu.setForeground(QColor(RED))
        inconnu.setFontWeight(QFont.Bold)
        inconnu.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        inconnu.setUnderlineColor(QColor(RED))
        for genre in ("accolade", "chevron", "each"):
            self._formats[(genre, False)] = inconnu

    def definir_chevrons(self, labels) -> None:
        """Les <<labels>> connus : ceux de la portée + ceux déclarés dans
        « Attributs codés en dur ». Ne recolore que s'ils ont changé."""
        nouveaux = frozenset(JETONS_PORTEE) | frozenset(labels)
        if nouveaux != self.chevrons:
            self.chevrons = nouveaux
            self.rehighlight()

    def highlightBlock(self, texte):
        spans, dans_each = reperer_jetons(
            texte, self.accolades, self.chevrons,
            self.previousBlockState() == 1)
        for d, f, genre, connu in spans:
            self.setFormat(d, f - d, self._formats[(genre, connu)])
        self.setCurrentBlockState(1 if dans_each else 0)


class DaxEdit(QPlainTextEdit):
    """L'éditeur de code (DAX, JSON brut) : TAB pose une TABULATION, large
    de INDENT_DAX caractères ; Maj+TAB la reprend ; Début va après le
    retrait (cf. _debut_intelligent).

    Qt donne 80 px à une tabulation — une dizaine de caractères, qui jettent
    le DAX au milieu de la zone. Le cran est ramené à INDENT_DAX caractères
    de la police AFFICHÉE (recalé quand le thème la pose).

    Maj+TAB défait aussi un retrait en ESPACES, celui des variations écrites
    avant (cf. « 7d avg ») : les deux formes cohabitent dans un config."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabChangesFocus(False)      # TAB indente, il ne quitte pas
        police_code(self)                   # chasse fixe, via le thème
        self._caler_tabulation()

    def _caler_tabulation(self):
        """Un cran de tabulation = INDENT_DAX espaces de la police AFFICHÉE."""
        fm = self.fontMetrics()
        blanc = " " * INDENT_DAX
        largeur = (fm.horizontalAdvance(blanc)
                   if hasattr(fm, "horizontalAdvance") else fm.width(blanc))
        if hasattr(self, "setTabStopDistance"):        # Qt >= 5.10
            self.setTabStopDistance(float(largeur))
        else:                                          # PyQt5 plus ancien
            self.setTabStopWidth(int(largeur))

    def changeEvent(self, ev):
        # la police définitive arrive avec la feuille de style, APRÈS le
        # constructeur : le cran se recale sur elle
        super().changeEvent(ev)
        if ev.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._caler_tabulation()

    def keyPressEvent(self, ev):
        shift = bool(ev.modifiers() & Qt.ShiftModifier)
        if ev.key() == Qt.Key_Tab and not shift:
            self.insertPlainText("\t")
            return
        if ev.key() == Qt.Key_Backtab or (ev.key() == Qt.Key_Tab and shift):
            self._desindenter()
            return
        if (ev.key() == Qt.Key_Home
                and not ev.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            self._debut_intelligent(shift)
            return
        super().keyPressEvent(ev)

    def _debut_intelligent(self, etendre: bool):
        """Début (Maj+Début pour sélectionner) va au PREMIER caractère de la
        ligne, après le retrait — pas à la colonne 0, qui embarquait le
        retrait dans la sélection. Un second appui, déjà là, va à la colonne
        0 : le retrait reste atteignable. C'est le comportement des éditeurs
        de code.

        La LIGNE est la ligne logique (le bloc) : une ligne longue qui revient
        à l'écran reste une seule ligne de DAX."""
        c = self.textCursor()
        texte = c.block().text()
        retrait = len(texte) - len(texte.lstrip(" \t"))
        cible = 0 if c.positionInBlock() == retrait else retrait
        mode = QTextCursor.KeepAnchor if etendre else QTextCursor.MoveAnchor
        c.setPosition(c.block().position() + cible, mode)
        self.setTextCursor(c)

    def _desindenter(self):
        """Maj+TAB : retire UN cran au DÉBUT de la ligne, où que soit le
        curseur — une tabulation, ou jusqu'à INDENT_DAX espaces si la ligne
        est indentée à l'ancienne. C'est le retrait qu'on veut défaire, pas
        ce qui précède le curseur au milieu d'une expression."""
        c = self.textCursor()
        texte = c.block().text()
        if texte.startswith("\t"):
            n = 1
        else:
            n = min(INDENT_DAX, len(texte) - len(texte.lstrip(" ")))
        if not n:
            return
        c.beginEditBlock()
        c.movePosition(QTextCursor.StartOfBlock)
        for _ in range(n):
            c.deleteChar()
        c.endEditBlock()


class ConfigTab(QWidget):
    # la vue affichée a changé — y compris SANS clic (un rechargement revient
    # sur Variations signaux bloqués) : la fenêtre en déduit où va le journal
    vue_changee = Signal()

    def __init__(self, journal=None):
        super().__init__()
        # le journal de l'app (colonne de droite), passé au panneau
        # « Générer » qui est celui qui écrit dedans
        self.journal = journal or Journal()
        self.project = None
        self._config: dict = {}
        self._current: str | None = None   # id de la variation affichée
        self._loading = False              # évite les signaux pendant le peuplement
        self._dirty = False
        # branche -> set des variations qu'elle N'applique PAS : une variation
        # absente de l'ensemble (ajoutée plus tard comprise) est appliquée
        self._branch_exclu: dict = {}
        self._branch_wrap: dict = {}       # branche -> patron écrit ("" = tiré de son DAX)
        self._branch_subst: dict = {}      # branche -> True si elle recopie (substitution)
        self._branch_pick_current = None   # branche affichée dans l'éditeur de restriction
        # en-têtes de TD_Indicateurs : lus une fois, gardés en mémoire, pour ne
        # plus toucher au classeur hors action explicite (cf. _td_entetes)
        self._td_entetes_cache: list = []
        self._td_entetes_src = ""

        root = QVBoxLayout(self)

        # affiché quand aucun measures_config.json n'est résolu pour le projet
        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(f"color:{YELLOW};")
        self.lbl_hint.hide()
        root.addWidget(self.lbl_hint)

        self._inner_prev = IDX_VARIATIONS
        self.inner = QTabWidget()
        self.inner.setObjectName("sousOnglets")      # cf. theme : un style à part
        self.inner.addTab(self._build_variations_tab(), "Variations")
        # ce que la génération produira, en arbre (aperçu, rien n'est écrit)
        self.arbre_mesures = ArbreMesures()
        self._cache_excel: dict = {}     # l'arbre ne relit l'Excel que s'il change
        self.inner.addTab(self.arbre_mesures, "Arbre des mesures")
        # les tables paramètre de champ : leur éditeur ET leur contenu. Elles
        # étaient une page de ⚙ Réglages, où l'on ne voyait pas ce qu'elles
        # contiendraient ; elles sont une affaire de mesures, pas de config
        self.inner.addTab(self._build_parametres_tab(), "Paramètres de champ")
        self.inner.addTab(self._build_raw_tab(), "JSON brut")
        # les réglages globaux ont LEUR fenêtre (⚙ Réglages, barre du haut) :
        # l'onglet Rapport s'en sert aussi (Excel des indicateurs, dossier
        # des cibles…), ils n'avaient rien à faire sous les Mesures
        self._dlg_reglages = self._build_reglages_dialog()
        # la génération n'a plus d'onglet : son panneau se pose EN TÊTE DU
        # JOURNAL — le run qu'il lance s'affiche juste en dessous. Visible
        # tant que l'onglet Mesures l'est (cf. showEvent / hideEvent).
        self.model_panel = ModelTab(self.journal)
        self.model_panel.sauver = self._save      # « Enregistrer puis générer »
        # après une génération, « nouvelle / modifiée » ne sont plus vrais
        self.model_panel.modele_genere.connect(self._arbre_si_visible)
        self.model_panel.hide()
        self.journal.poser_actions(self.model_panel)
        self.inner.currentChanged.connect(self._on_view_switch)
        root.addWidget(self.inner, 1)

        bottom = QHBoxLayout()
        # ne porte plus l'état « non sauvegardé » (c'est le bouton qui
        # s'allume) : sert à confirmer l'écriture, une fois faite
        self.lbl_dirty = QLabel("")
        self.lbl_dirty.setStyleSheet(f"color:{YELLOW};")
        bottom.addWidget(self.lbl_dirty, 1)
        self.btn_reload = QPushButton("Recharger (annule)")
        self.btn_reload.clicked.connect(self._reload)
        self.btn_save = QPushButton("Sauvegarder (backup .bak)")
        self.btn_save.clicked.connect(self._save)
        self._set_dirty(False)          # infobulle de repos posée par l'helper
        # la bibliothèque ne dépend d'aucun projet : son chemin s'affiche dès
        # l'ouverture, même si aucun rapport n'est encore chargé
        self._refresh_biblio_label()
        bottom.addWidget(self.btn_reload)
        bottom.addWidget(self.btn_save)
        root.addLayout(bottom)

    # ---- construction ----------------------------------------------------------

    def _build_variations_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        split = Separateur(Qt.Horizontal)     # un trait fin, de l'air autour
        lay.addWidget(split)

        # -- gauche : liste + boutons --
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.lst = QListWidget()
        self.lst.currentTextChanged.connect(self._on_select)
        lv.addWidget(self.lst, 1)
        self.lbl_catalogue = QLabel("")
        self.lbl_catalogue.setWordWrap(True)
        self.lbl_catalogue.setStyleSheet(f"color:{TEXT_DIM};")
        lv.addWidget(self.lbl_catalogue)
        biblio = QHBoxLayout()
        b_biblio = QPushButton("Bibliothèque…")
        b_biblio.setToolTip(
            "Piocher des variations dans un fichier GLOBAL, hors projet." + chr(10) +
            "Ce qui est importé entre dans le config de CE rapport.")
        b_biblio.clicked.connect(self._ouvrir_biblio)
        biblio.addWidget(b_biblio)
        biblio.addWidget(bouton_schema(self, "variations"))
        biblio.addWidget(self._help("Bibliothèque de variations", (
            "Un fichier GLOBAL, hors projet, qui garde les variations\n"
            "réutilisées d'un rapport à l'autre.\n\n"
            "IMPORTER copie la variation choisie DANS le measures_config.json\n"
            "de ce rapport. Le config reste donc autonome : ce qu'il contient\n"
            "est exactement ce qui sera généré, rien à cocher ni à retenir\n"
            "projet par projet.\n\n"
            "PUBLIER fait l'inverse : une variation écrite ici part dans la\n"
            "bibliothèque pour servir ailleurs.\n\n"
            "Une variation qui sert de BRANCHE amène son entrée de branche.\n"
            "Importer une variation déjà présente la REMPLACE (on confirme).\n\n"
            "Le chemin du fichier est retenu au niveau de l'APPLICATION, pas\n"
            "du projet, et il n'est pas relatif au rapport courant : le choisir\n"
            "une fois et il est retrouvé à chaque lancement, quel que soit le\n"
            "projet ouvert. Le poser sur un lecteur partagé permet à toute\n"
            "l'équipe d'y puiser.\n\n"
            "Le chemin retenu est affiché juste en dessous.")))
        biblio.addStretch()
        lv.addLayout(biblio)
        # le chemin retenu, VISIBLE : c'est ce qui manquait pour comprendre
        # qu'il n'y a rien à redonner d'un projet à l'autre
        self.lbl_biblio = QLabel("")
        self.lbl_biblio.setWordWrap(True)
        self.lbl_biblio.setStyleSheet(f"color:{TEXT_DIM};")
        lv.addWidget(self.lbl_biblio)
        row1 = QHBoxLayout()
        for label, slot in (("Ajouter", self._add), ("Dupliquer", self._duplicate)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row1.addWidget(b)
        lv.addLayout(row1)
        row2 = QHBoxLayout()
        for label, slot in (("Renommer", self._rename), ("Supprimer", self._delete)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row2.addWidget(b)
        lv.addLayout(row2)
        row3 = QHBoxLayout()
        for label, delta in (("↑ Monter", -1), ("↓ Descendre", 1)):
            b = QPushButton(label)
            b.setToolTip("Réordonne les variations. L'ordre pilote l'ordre des\n"
                         "calculs dans le paramètre de champ (et la génération).")
            b.clicked.connect(lambda _=False, d=delta: self._move(d))
            row3.addWidget(b)
        lv.addLayout(row3)
        split.addWidget(left)

        # -- milieu : ce que la variation EST (nom, format, dossier) et OÙ elle
        #    s'applique. Le DAX a sa propre colonne à droite : c'est là qu'on
        #    passe le plus de temps, il mérite la hauteur de la fenêtre plutôt
        #    que le bas d'un formulaire (la vue n'a pas besoin du journal, qui
        #    lui cède sa place — cf. app._colonne_selon_la_vue).
        milieu = QWidget()
        mv = QVBoxLayout(milieu)
        mv.setContentsMargins(0, 0, 0, 0)

        def formulaire(titre):
            """Groupe « libellé | champ ». Rend (groupe, ajouter, pleine) :
            `ajouter` pose une ligne libellée, `pleine` un widget ou une
            rangée sur les deux colonnes."""
            gb = QGroupBox(titre)
            g = QGridLayout(gb)
            g.setColumnStretch(1, 1)
            rang = [0]

            def ajouter(label, widget, tip=None, help_text=None,
                        titre_aide=None):
                lbl = QLabel(label)
                tip = tip or help_text
                if tip:
                    lbl.setToolTip(tip)
                    widget.setToolTip(tip)
                g.addWidget(lbl, rang[0], 0)
                if help_text:        # ⓘ collé au champ : aucune ligne en plus
                    box = QHBoxLayout()
                    box.setContentsMargins(0, 0, 0, 0)
                    box.addWidget(widget, 1)
                    box.addWidget(self._help(titre_aide or label.rstrip(" :"),
                                             help_text))
                    holder = QWidget()
                    rangee_transparente(holder)
                    holder.setLayout(box)
                    g.addWidget(holder, rang[0], 1)
                else:
                    g.addWidget(widget, rang[0], 1)
                rang[0] += 1

            def pleine(quoi):
                if isinstance(quoi, QWidget):
                    g.addWidget(quoi, rang[0], 0, 1, 2)
                else:
                    g.addLayout(quoi, rang[0], 0, 1, 2)
                rang[0] += 1

            return gb, ajouter, pleine

        # ---- la mesure générée ----
        gb_mesure, add_row, pleine = formulaire("Mesure générée")
        self.ed_name = QLineEdit()
        add_row("namePattern :", self.ed_name,
                "Nom de la mesure générée.\n{base} = mesure de base (branche incluse), "
                "{kpi} = KPI racine, {variation} = id de la variation.")
        self.ed_desc = QLineEdit()
        add_row("description :", self.ed_desc,
                "Description de la mesure générée (placeholders permis).")
        self.cmb_format = QComboBox()
        self.cmb_format.setEditable(True)   # presets + saisie libre
        self.cmb_format.addItems(["inherit", "delta", "text", "#,0", "#,0.0",
                                  "#,0.00", "0.0%", "+#,0.0%;-#,0.0%;#,0.0%"])
        add_row("formatString :", self.cmb_format, help_text=(
            "inherit = format de la mesure de base.\n"
            "delta = format signé ± dérivé de la base (une base en % donne des pts).\n"
            "text = AUCUN format, pour une mesure texte (ex. les hex des CF).\n"
            "Sinon : un format explicite ; {baseFormat} = section positive de la base.\n\n"
            "Littéraux : une espace est une espace. Espace, + - $ ( ) s'affichent\n"
            "d'eux-mêmes ; seules les lettres demandent un backslash (pts donne \\p\\t\\s)."))
        self.ed_folder = QLineEdit()
        self.ed_folder.setPlaceholderText("vide = displayFolderPattern des settings")
        add_row("displayFolder :", self.ed_folder,
                "Dossier d'affichage des mesures générées.\n"
                "Vide = le displayFolderPattern des settings. Placeholders : "
                "{folder} {baseFolder} {variation} {kpi} {branch}.\n"
                "Dossiers rangés PAR KPI (⚙ Réglages → Génération) : {baseFolder}\n"
                "y est le dossier du KPI (_indicateurs\\Weight), pour que la\n"
                "mesure reste avec son KPI."),
        self.cmb_folder_var = QComboBox()   # non éditable : ids existants
        add_row("folderVariation :", self.cmb_folder_var,
                "Dossier HÔTE : range les mesures générées dans le DOSSIER d'une\n"
                "AUTRE variation.\n"
                "Ex. « CF Δ 30d » vit dans le dossier de « Δ 30d » (la couleur à côté\n"
                "de la mesure qu'elle met en forme). Vide = son propre dossier.\n"
                "Sans effet quand les dossiers sont rangés PAR KPI.")
        self.cmb_datacat = QComboBox()
        self.cmb_datacat.setEditable(True)
        self.cmb_datacat.addItems(["", "ImageUrl", "WebUrl"])
        add_row("dataCategory :", self.cmb_datacat,
                "Catégorie de données de la mesure.\n"
                "ImageUrl = la mesure retourne une image (SVG en data-URI) ;\n"
                "WebUrl = un lien ; vide = mesure normale.")
        self.chk_infp = QCheckBox("dans les paramètres de champ (inFieldParameter)")
        self.chk_infp.setToolTip("Coché : la mesure générée entre dans les tables\n"
                                 "paramètre de champ (P_Indicateurs_*).")
        pleine(self.chk_infp)
        mv.addWidget(gb_mesure)

        # ---- la portée : cette variation est-elle déclinée pour les KPI, les
        #      cibles, et sur quelles bases ? ----
        gb_portee, add_row, pleine = formulaire("Portée")
        self.chk_kpi = QCheckBox("générer pour les KPI")
        self.chk_kpi.setToolTip("Décline cette variation sur les mesures de BASE (KPI).\n"
                                "Défaut : coché.")
        self.chk_cible = QCheckBox("générer pour les cibles")
        self.chk_cible.setToolTip(
            "Décline cette variation sur les mesures CIBLES (dossier dédié).\n"
            "Utile surtout pour l'écart réel−cible, via le jeton {kpiRef} :\n"
            "   {kpiRef} - {baseRef}\n"
            "     Réel →  [Weight]      - [Weight cible]\n"
            "     YTD  →  [Weight YTD]  - [Weight cible YTD]\n"
            "\n"
            "⚠ Ne PAS écrire « [{kpi}] - {baseRef} » : {kpi} est le KPI RACINE,\n"
            "sans branche, donc en YTD on comparerait le réel COURANT à la\n"
            "cible YTD. {kpiRef} suit la branche, {kpi} non, c'est voulu.\n"
            "\n"
            "Une variation « écart » se coche ici mais se DÉCOCHE côté KPI\n"
            "(elle vaudrait 0). Défaut : décoché.")
        # types de base acceptés : une combo à cases (le vocabulaire
        # s'allonge avec la colonne « type » de TD_Indicateurs)
        self.cmb_kinds = CheckCombo()
        self.cmb_kinds.setMinimumWidth(190)
        self.cmb_kinds.changed.connect(self._on_edit)
        self.chk_wrap = QCheckBox("envelopper en branche")
        self.chk_wrap.setToolTip(
            "En branche, cette variation est ENVELOPPÉE au lieu d'être" + chr(10) +
            " recopiée (défaut : cochée) :" + chr(10) +
            "   Weight YTD PY = CALCULATE([Weight PY], DATESYTD(…))" + chr(10) +
            "au lieu de" + chr(10) +
            "   Weight YTD PY = CALCULATE([Weight YTD], SAMEPERIODLASTYEAR(…))"
            + chr(10) + chr(10) +
            "Toutes les mesures de la branche se lisent alors pareil, le" + chr(10) +
            "DAX généré est trivial, et un correctif ici se répercute" + chr(10) +
            "sans régénérer." + chr(10) + chr(10) +
            "⚠ DÉCOCHER si le DAX ÉPINGLE une fenêtre sur la borne du" + chr(10) +
            "contexte (MAX, DATEADD, DATESINPERIOD) et que l'on veut la" + chr(10) +
            "version « du cumul » : « 7d avg » enveloppé est le 7d avg" + chr(10) +
            "ordinaire, pas la moyenne 7 jours de [Weight YTD]." + chr(10) + chr(10) +
            "Sans effet si la branche recopie tout (⚙ Réglages → Branches," + chr(10) +
            "« Envelopper » décoché), ou si le DAX cite {branch} : écrite" + chr(10) +
            "pour la branche, la variation est alors toujours recopiée.")
        pour = QHBoxLayout()
        pour.addWidget(self.chk_kpi)
        pour.addSpacing(12)
        pour.addWidget(self.chk_cible)
        pour.addStretch()
        pleine(pour)
        pleine(self.chk_wrap)

        kinds = QHBoxLayout()
        kinds.setContentsMargins(0, 0, 0, 0)
        kinds.addWidget(self.cmb_kinds)
        kinds.addWidget(self._help("Types de base acceptés", (
            "Limite la variation aux bases d'un certain TYPE. « tous » = aucun\n"
            "filtre. Une base écartée ne reçoit PAS la mesure : elle n'est pas\n"
            "créée du tout, plutôt que créée puis fausse.\n\n"
            "DÉDUITS du formatString :\n"
            "   0.0 %       donne  pourcentage\n"
            "   #,0.00 $    donne  devise\n"
            "   #,0 ou vide donne  nombre\n\n"
            "DÉCLARÉS dans TD_Indicateurs (colonne « type », ⚙\n"
            "Réglages) : ratio, durée, indice, ou toute autre valeur. Un format ne\n"
            "peut PAS les deviner, un ratio décimal (0,85) s'écrit comme un\n"
            "nombre. La déclaration prime toujours sur la déduction.\n\n"
            "Exemple : un « % du total » n'a de sens ni sur un pourcentage ni\n"
            "sur un ratio, cocher nombre et devise seulement.\n\n"
            "Le journal résume ce qui a été écarté, et l'aperçu suit le filtre.")))
        kinds.addStretch()
        holder_k = QWidget()
        rangee_transparente(holder_k)
        holder_k.setLayout(kinds)
        add_row("types de base :", holder_k)

        # exclure large / rattraper nommément : un champ chacun, l'aide sur
        # le second (elle explique les deux, et leur priorité)
        self.ed_exclude = QLineEdit()
        self.ed_exclude.setPlaceholderText("ex. : ratio, /, average")
        self.ed_exclude.textChanged.connect(self._on_edit)
        self.ed_include = QLineEdit()
        self.ed_include.setPlaceholderText("ex. : Average Steps")
        self.ed_include.textChanged.connect(self._on_edit)
        add_row("exclure si le nom contient :", self.ed_exclude,
                "Fragments séparés par des virgules, cf. ⓘ ci-dessous.")
        add_row("mais garder :", self.ed_include, titre_aide="Filtres par nom",
                help_text=(
            "Fragments séparés par des virgules. Une base écartée ne reçoit\n"
            "PAS la mesure : elle n'est pas créée du tout.\n\n"
            "EXCLURE : sert à ce que le formatString ne dit pas : un ratio en\n"
            "décimal (0,85) s'écrit comme un nombre, mais son NOM le trahit\n"
            "souvent (« Ratio … », « … / … », « Taux … »). Le nom complet d'un\n"
            "KPI y a sa place aussi, pour l'écarter entièrement.\n\n"
            "MAIS GARDER : le rattrapage nommé, qui PRIME sur tout : sur\n"
            "l'exclusion ci-contre ET sur le filtre de type.\n"
            "   exclure : average    mais garder : Average Steps\n"
            "écarte toutes les moyennes sauf celle-là, utile quand une\n"
            "mesure porte « average » dans son nom mais est en fait une somme.\n\n"
            "Insensible à la casse ET aux accents (« duree » attrape « Durée »).\n"
            "Le nom du KPI est testé en plus de celui de la base, donc exclure\n"
            "« Weight » écarte aussi « Weight cible ». Les branches héritent.\n\n"
            "L'aperçu (colonne de droite) suit ces filtres."))
        mv.addWidget(gb_portee)
        mv.addStretch(1)
        split.addWidget(milieu)

        # -- droite : le DAX, et ce qu'il va produire. Une poignée entre les
        #    deux : on agrandit l'aperçu quand on vérifie les noms, le DAX
        #    quand on l'écrit.
        droite = Separateur(Qt.Vertical)
        droite.setChildrenCollapsible(False)

        gb_dax = QGroupBox("DAX")
        gb_dax.setToolTip("En clair, sérialisé en lignes JSON à la sauvegarde.\n"
                          "TAB = une tabulation (4 caractères de large) · Maj+TAB\n"
                          "la reprend · Début va au premier caractère de la\n"
                          "ligne (2e appui : colonne 0).\n\n"
                          "Jetons : {connus} en bleu · <<attributs>> en vert ·\n"
                          "INCONNUS en rouge souligné. Un <<attribut>> se déclare\n"
                          "dans ⚙ Réglages → Excel des indicateurs.")
        dv = QVBoxLayout(gb_dax)
        self.ed_dax = DaxEdit()
        self.surligneur = SurligneurJetons(self.ed_dax.document())
        dv.addWidget(self.ed_dax, 1)

        self.lbl_lint = QLabel("")
        self.lbl_lint.setWordWrap(True)
        self.lbl_lint.setStyleSheet(f"color:{YELLOW};")
        dv.addWidget(self.lbl_lint)

        # les jetons, avec ce qu'ils valent pour le KPI ou la cible qu'on
        # choisit : une fenêtre à part, à garder ouverte à côté du DAX
        self.fenetre_jetons = FenetreJetons(self)
        self.explorateur_jetons = self.fenetre_jetons.explorateur
        self.explorateur_jetons.besoin.connect(self._rafraichir_jetons)
        self.explorateur_jetons.inserer.connect(self._inserer_jeton)
        self.explorateur_jetons.attribut_ajoute.connect(self._attribut_ajoute)
        self.explorateur_jetons.attribut_renomme.connect(self._attribut_renomme)
        self.explorateur_jetons.attribut_colonne.connect(self._attribut_colonne)
        self.explorateur_jetons.attribut_valeur.connect(self._attribut_valeur)
        self.explorateur_jetons.attribut_retire.connect(self._attribut_retire)
        self.btn_jetons = QPushButton("Jetons disponibles…")
        self.btn_jetons.setToolTip("Ce que vaut chaque jeton pour le KPI ou la cible\n"
                                   "choisie, et où il se règle.")
        self.btn_jetons.clicked.connect(self.fenetre_jetons.montrer)
        rang_jetons = QHBoxLayout()
        rang_jetons.addWidget(self.btn_jetons)
        rang_jetons.addWidget(bouton_schema(self, "jetons"))
        rang_jetons.addStretch()
        dv.addLayout(rang_jetons)
        droite.addWidget(gb_dax)

        gb_apercu = QGroupBox("Aperçu des noms générés")
        gb_apercu.setToolTip("Bases × branches, selon la PORTÉE cochée.")
        av = QVBoxLayout(gb_apercu)
        legende = QLabel(
            f"<span style='color:{COULEURS_APERCU['racine']}'>KPI ou cible</span>"
            f"  <span style='color:{COULEURS_APERCU['branche']}'>+ branche</span>"
            f"  <span style='color:{COULEURS_APERCU['variation']}'>"
            f"+ variation</span>")
        legende.setToolTip("Chaque nom est coloré selon ce qui l'a produit :\n"
                           "la racine telle quelle, puis ce que la branche et\n"
                           "la variation lui AJOUTENT (le texte de leur\n"
                           "namePattern).\n\n"
                           "Déplier un nom pour voir son DAX et ses attributs, tels que\n"
                           "« Générer » les écrira (jetons développés).")
        av.addWidget(legende)
        # un nom par ligne ; DÉPLIÉ, son DAX et ses attributs. Les noms sont
        # calculés ici à la frappe (instantané) ; leurs détails viennent du
        # générateur en aperçu, un instant plus tard (cf. _details_apercu)
        self.arbre_apercu = QTreeWidget()
        self.arbre_apercu.setHeaderHidden(True)
        self.arbre_apercu.setColumnCount(1)
        self.arbre_apercu.setUniformRowHeights(False)    # le DAX tient sur N lignes
        self.arbre_apercu.setItemDelegate(DelegueRiche(self.arbre_apercu))
        self.arbre_apercu.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.arbre_apercu.header().setStretchLastSection(False)
        police_code(self.arbre_apercu)
        self.arbre_apercu.setStyleSheet(f"color:{TEXT_DIM};")
        self._apercu_ouverts: set = set()     # noms dépliés, gardés à la frappe
        self.arbre_apercu.itemExpanded.connect(self._on_apercu_deplie)
        self.arbre_apercu.itemCollapsed.connect(
            lambda it: self._apercu_ouverts.discard(it.data(0, Qt.UserRole)))
        self._minuterie_apercu = QTimer(self)
        self._minuterie_apercu.setSingleShot(True)
        self._minuterie_apercu.setInterval(250)
        self._minuterie_apercu.timeout.connect(self._details_apercu)
        av.addWidget(self.arbre_apercu)
        droite.addWidget(gb_apercu)
        # à parts égales : un nom déplié montre son DAX, il lui faut la place
        droite.setStretchFactor(0, 1)
        droite.setStretchFactor(1, 1)

        split.addWidget(droite)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 4)

        # tout changement du formulaire marque « modifié » + relint + aperçu
        for sig in (self.ed_name.textChanged, self.ed_desc.textChanged,
                    self.cmb_format.currentTextChanged, self.ed_folder.textChanged,
                    self.cmb_folder_var.currentIndexChanged,
                    self.cmb_datacat.currentTextChanged,
                    self.ed_dax.textChanged):
            sig.connect(self._on_edit)
        self.chk_infp.stateChanged.connect(self._on_edit)
        self.chk_kpi.stateChanged.connect(self._on_edit)
        self.chk_wrap.stateChanged.connect(self._on_edit)
        self.chk_cible.stateChanged.connect(self._on_edit)
        return w

    def _build_parametres_tab(self) -> QWidget:
        """Mesures → Paramètres de champ : en haut l'éditeur des tables (la
        liste, les réglages de la table choisie, les réglages communs), en
        bas ce qu'elles contiendront (cf. ApercuParametres), recalculé à
        chaque réglage."""

        def line(tip=None):
            e = QLineEdit()
            if tip:
                e.setToolTip(tip)
            e.textChanged.connect(self._mark_dirty)
            e.textChanged.connect(self._fp_change)
            return e

        def check(text, tip=None):
            c = QCheckBox(text)
            if tip:
                c.setToolTip(tip)
            c.stateChanged.connect(self._mark_dirty)
            c.stateChanged.connect(self._fp_change)
            return c

        # -- paramètres de champ : une LISTE de tables, chacune ses réglages --
        self.g_fp_enabled = check("Générer les tables paramètre de champ")
        self.g_fp_tables = EditeurTablesParametre()
        self.g_fp_tables.changed.connect(self._mark_dirty)
        self.g_fp_kpiColumn = line("Colonne KPI (défaut Indicateur).")
        self.g_fp_calcColumn = line("Colonne Calcul (défaut Calcul).")
        self.g_fp_branchColumn = line("Colonne Branche (défaut Branche).")
        self.g_fp_baseLabel = line("Libellé de la rangée « base » (ex. Réel).")
        self.g_fp_baseLabel.textChanged.connect(
            lambda t: self.g_fp_tables.set_base_label(t.strip()))
        self.g_fp_noBranchLabel = line("Valeur Branche hors branche (ex. Réel).")
        self.g_lkp_table = line("Table du LOOKUPVALUE des libellés (ex. TD_Indicateurs).")
        self.g_lkp_key = line("Colonne clé = nom de la mesure (ex. mesure).")
        self.g_lkp_label = line("Colonne du libellé affiché (ex. libelle_indicateur).")
        gb_fp = self._form_group("Paramètres de champ", [
            (None, self.g_fp_enabled,
             "Coché : les tables de la liste sont créées ou mises à jour à\n"
             "chaque génération.\n"
             "Décoché : le générateur n'y touche plus, elles restent dans le\n"
             "modèle telles quelles."),
            (None, self.g_fp_tables, None),
        ], resume="Les tables qu'un segment utilise pour choisir ce qu'un visuel "
                  "affiche. Autant de tables qu'il en faut, chacune avec ses "
                  "réglages : ce qu'affichent ses rangées, et ce qu'elle garde.")
        communs = self._form_group("Réglages communs à toutes les tables", [
            ("Colonne KPI :", self.g_fp_kpiColumn,
             "Nom de la colonne (cachée) qui porte le KPI dans chaque table\n"
             "paramètre : le nom de sa mesure de base. C'est la CLÉ : la relier à\n"
             "TD_KPI pour filtrer par KPI :\n"
             "   TD_KPI[mesure] → P_Indicateurs_…[Indicateur]\n\n"
             "Défaut : Indicateur."),
            ("Colonne Calcul :", self.g_fp_calcColumn,
             "Nom de la colonne qui porte le CALCUL (Réel, PY, 7d avg…),\n"
             "celle que filtre un segment « calcul ».\n\n"
             "Défaut : Calcul."),
            ("Colonne Branche :", self.g_fp_branchColumn,
             "Nom de la colonne qui porte la BRANCHE (Réel, YTD…), pour\n"
             "filtrer une branche, ou mettre Réel et YTD côte à côte.\n\n"
             "Défaut : Branche."),
            ("Libellé de la base :", self.g_fp_baseLabel,
             "Libellé, dans la colonne Calcul, de la rangée de la mesure de\n"
             "BASE : le KPI lui-même, sans variation (case « Garder : la rangée de base »).\n\n"
             "Ex. Réel → le segment Calcul propose Réel, PY, 7d avg…\n"
             "Vide = Base."),
            ("Branche « hors branche » :", self.g_fp_noBranchLabel,
             "Valeur de la colonne Branche pour tout ce qui n'est PAS dans une\n"
             "branche.\n\n"
             "Ex. Réel → un segment Branche propose Réel et YTD.\n"
             "Vide = Base."),
            ("Libellés (table) :", self.g_lkp_table,
             "Table de CORRESPONDANCE KPI → libellé, pour les tables « par KPI »\n"
             "(case libellé) et « mixtes ». Le libellé y est lu par\n"
             "LOOKUPVALUE, dans le DAX des tables paramètre.\n\n"
             "Ex. TD_Indicateurs"),
            ("Libellés (colonne clé) :", self.g_lkp_key,
             "Colonne de cette table qui contient le NOM DE LA MESURE du KPI :\n"
             "la clé de recherche.\n\n"
             "Ex. mesure"),
            ("Libellés (colonne affichée) :", self.g_lkp_label,
             "Colonne de cette table qui contient le LIBELLÉ affiché.\n\n"
             "Ex. libelle_indicateur → « Poids » pour Weight"),
        ])
        rang_communs = QHBoxLayout()
        rang_communs.addWidget(
            self._collapsible("Réglages communs (noms de colonnes, libellés)", communs))
        rang_communs.addStretch()
        rang_communs.addWidget(bouton_schema(self, "parametres"))
        gb_fp.layout().addLayout(rang_communs, gb_fp.layout().rowCount(), 0, 1, 3)
        gb_fp.layout().addWidget(communs, gb_fp.layout().rowCount(), 0, 1, 3)

        self.g_fp_tables.changed.connect(self._fp_change)

        self.apercu_fp = ApercuParametres()
        # l'éditeur et l'aperçu montrent la MÊME table
        self.g_fp_tables.liste.currentRowChanged.connect(self._fp_table_choisie)
        self.apercu_fp.table_demandee.connect(self._fp_choisir_table)
        self._minuterie_fp = QTimer(self)
        self._minuterie_fp.setSingleShot(True)
        self._minuterie_fp.setInterval(300)
        self._minuterie_fp.timeout.connect(self._rafraichir_parametres)

        haut = QScrollArea()
        haut.setWidgetResizable(True)
        haut.setFrameShape(QFrame.NoFrame)
        haut.setWidget(gb_fp)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(haut)
        split.addWidget(self.apercu_fp)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        return split

    def _fp_change(self, *_) -> None:
        """Un réglage a bougé : l'aperçu se recalcule un instant plus tard."""
        if not self._loading and hasattr(self, "_minuterie_fp"):
            self._minuterie_fp.start()

    def _fp_table_choisie(self, row) -> None:
        it = self.g_fp_tables.liste.item(row) if row >= 0 else None
        self.apercu_fp.montrer_table(it.text() if it else "")

    def _fp_choisir_table(self, nom) -> None:
        liste = self.g_fp_tables.liste
        for i in range(liste.count()):
            if liste.item(i).text() == nom and liste.currentRow() != i:
                liste.setCurrentRow(i)
                return

    def _load_fp(self) -> None:
        """Peuple l'éditeur des tables paramètre depuis le config."""
        self._loading = True
        fp = self._config.get("fieldParameter") or {}
        # bloc absent = désactivé
        self.g_fp_enabled.setChecked(bool(fp.get("enabled", True)) if "fieldParameter" in self._config else False)
        self.g_fp_tables.set_vocab(**self._fp_vocabulaire())
        self.g_fp_tables.load(gm.fp_table_specs(fp) if "fieldParameter" in self._config
                              else [])
        self.g_fp_kpiColumn.setText(fp.get("kpiColumn", "") or "")
        self.g_fp_calcColumn.setText(fp.get("calcColumn", "") or "")
        self.g_fp_branchColumn.setText(fp.get("branchColumn", "") or "")
        self.g_fp_baseLabel.setText(fp.get("baseLabel", "") or "")
        self.g_fp_tables.set_base_label(fp.get("baseLabel", "") or "")
        self.g_fp_noBranchLabel.setText(fp.get("noBranchLabel", "") or "")
        lkp = fp.get("kpiLabelLookup") or {}
        self.g_lkp_table.setText(lkp.get("table", "") or "")
        self.g_lkp_key.setText(lkp.get("keyColumn", "") or "")
        self.g_lkp_label.setText(lkp.get("labelColumn", "") or "")

        self._loading = False

    def _commit_fp(self) -> None:
        self._fp_vers(self._config)

    def _fp_vers(self, config: dict) -> None:
        """Écrit les réglages des tables paramètre dans `config` : celui en
        mémoire, ou une COPIE (l'aperçu). Un bloc fieldParameter absent n'est
        pas matérialisé s'il reste désactivé (absent = off)."""
        fp_on = self.g_fp_enabled.isChecked()
        if fp_on or "fieldParameter" in config:
            fp = config.setdefault("fieldParameter", {})
            fp["enabled"] = fp_on

            def fset(key, val):
                if val:
                    fp[key] = val
                else:
                    fp.pop(key, None)

            # la liste fait foi : l'ancien format (trois familles aux options
            # communes) est relu par fp_table_specs puis remplacé
            fp["tables"] = [gm.fp_spec_compacte(t) for t in self.g_fp_tables.specs()]
            for vieux in ("tableName", "tableNames", "tableNamesByKpi",
                          "tableNamesKpiBase", "includeBase", "byKpiUsesLabel"):
                fp.pop(vieux, None)
            fset("kpiColumn", self.g_fp_kpiColumn.text().strip())
            fset("calcColumn", self.g_fp_calcColumn.text().strip())
            fset("branchColumn", self.g_fp_branchColumn.text().strip())
            fset("baseLabel", self.g_fp_baseLabel.text().strip())
            fset("noBranchLabel", self.g_fp_noBranchLabel.text().strip())
            lkp = {}
            for key, w in (("table", self.g_lkp_table), ("keyColumn", self.g_lkp_key),
                           ("labelColumn", self.g_lkp_label)):
                if w.text().strip():
                    lkp[key] = w.text().strip()
            if lkp:
                fp["kpiLabelLookup"] = lkp
            else:
                fp.pop("kpiLabelLookup", None)

    def _rafraichir_parametres(self) -> None:
        """L'aperçu des tables : la génération à blanc sur une COPIE du
        config où l'on a versé les réglages en cours. Rien n'est écrit."""
        import copy
        if not self.project or not self.project.model_dir.exists():
            self.apercu_fp.erreur("Aucun modèle : ouvrir un projet .pbip.")
            return
        cfg = copy.deepcopy(self._config)
        self._fp_vers(cfg)
        avis: list = []

        def log(ligne=""):
            ligne = str(ligne).strip()
            if ligne.startswith("⚠") and ("param" in ligne.lower()
                                          or "correspondance" in ligne):
                avis.append(ligne)
        try:
            st = gm.generate(self.project.model_dir, cfg, dry_run=True,
                             remove_orphans=False, log=log,
                             cache_excel=self._cache_excel)
        except SystemExit as e:
            self.apercu_fp.erreur("Aperçu impossible : " + str(e))
            return
        except Exception as e:
            self.apercu_fp.erreur(f"Aperçu impossible : {type(e).__name__} : {e}")
            return
        avis += [x for x in st.get("fp_statuses") or [] if x.startswith("⚠")]
        self.apercu_fp.afficher(st.get("parametres") or [],
                                st.get("parametres_colonnes"),
                                st.get("parametres_actifs", True), avis)
        it = self.g_fp_tables.liste.currentItem()
        if it is not None and it.text() != self.apercu_fp.table_courante():
            self.apercu_fp.montrer_table(it.text())

    def _build_raw_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        # du code aussi : mêmes gestes que dans le DAX (TAB, Maj+TAB, Début)
        self.ed_raw = DaxEdit()
        self.ed_raw.textChanged.connect(self._on_edit)
        lay.addWidget(self.ed_raw, 1)
        bar = QHBoxLayout()
        btn_check = QPushButton("Valider le JSON")
        btn_check.clicked.connect(self._validate_raw)
        bar.addStretch()
        bar.addWidget(btn_check)
        lay.addLayout(bar)
        return w

    # ---- fenêtre « ⚙ Réglages » (réglages globaux) ----------------------------

    def _help(self, titre, texte) -> QToolButton:
        """Petit « ⓘ » : survol = infobulle, clic = fenêtre. L'explication
        reste accessible sans occuper l'écran en permanence."""
        b = QToolButton()
        b.setText("ⓘ")
        b.setAutoRaise(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(texte)
        b.clicked.connect(lambda: QMessageBox.information(self, titre, texte))
        return b

    def _collapsible(self, titre, inner) -> QToolButton:
        """Bouton-flèche qui montre/cache `inner`, replié au départ. Pour les
        aide-mémoire qu'on consulte ponctuellement sans vouloir les garder à
        l'écran."""
        btn = QToolButton()
        btn.setText(titre)
        btn.setCheckable(True)
        btn.setAutoRaise(True)
        btn.setArrowType(Qt.RightArrow)
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setStyleSheet(f"QToolButton {{ border: none; color: {TEXT_DIM}; }}")
        inner.setVisible(False)

        def toggle(on):
            btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
            inner.setVisible(on)

        btn.toggled.connect(toggle)
        return btn

    def _resume(self, texte) -> QLabel:
        """Une phrase, en tête d'un groupe : À QUOI il sert. Le détail de
        chaque réglage est derrière son ⓘ."""
        lbl = QLabel(texte)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{TEXT_DIM};")
        return lbl

    def _form_group(self, title: str, rows, resume: str = "") -> QGroupBox:
        """Groupe formulaire : rows = [(libellé|None, widget, aide|None)].

        libellé None = le widget occupe les deux colonnes (cases à cocher).
        `aide` devient un ⓘ au bout de la ligne — survol = infobulle, clic =
        fenêtre — et l'infobulle du libellé et du champ : l'explication est
        là où l'on regarde, sans occuper l'écran. `resume` dit en une phrase à
        quoi sert le groupe."""
        gb = QGroupBox(title)
        grid = QGridLayout(gb)
        r = 0
        if resume:
            grid.addWidget(self._resume(resume), r, 0, 1, 3)
            r += 1
        for label, widget, aide in rows:
            if label is None:
                grid.addWidget(widget, r, 0, 1, 2)
            else:
                lbl = QLabel(label)
                if aide:
                    lbl.setToolTip(aide)
                grid.addWidget(lbl, r, 0)
                grid.addWidget(widget, r, 1)
            if aide:
                widget.setToolTip(aide)
                titre = (label or widget.text()).split(" — ")[0].rstrip(" :")
                grid.addWidget(self._help(titre, aide), r, 2)
            r += 1
        grid.setColumnStretch(1, 1)
        return gb

    # Les pages de la fenêtre ⚙ Réglages, dans l'ordre de la barre latérale :
    # (clé, libellé). La clé sert à ouvrir la fenêtre SUR une page
    # (ouvrir_reglages(page=…)) — le lien de la fiche Excel du Rapport.
    PAGES_REGLAGES = (
        ("generation", "Génération"),
        ("excel", "Excel des indicateurs"),
        ("branches", "Branches"),
        ("cibles", "Mesures cibles"),
        ("delta", "Formats « delta »"),
    )
    # les groupes d'une page, quand elle en a plusieurs : les attributs codés
    # en dur sont des COLONNES de l'Excel des indicateurs : ils se règlent
    # avec lui, pas trois pages plus loin
    GROUPES_PAGE = {"excel": ("excel", "attributs")}
    # les pages dont le groupe prend toute la hauteur (des listes à parcourir)
    PAGES_PLEINES = ("branches",)

    def _build_global_tab(self) -> QWidget:
        """Les réglages globaux, UNE page par sujet et une barre latérale
        pour passer de l'une à l'autre — au lieu d'un long défilement où
        tout se voit à la fois."""
        groupes: dict = {}          # clé de page -> son groupe

        def line(tip=None):
            e = QLineEdit()
            if tip:
                e.setToolTip(tip)
            e.textChanged.connect(self._mark_dirty)
            return e

        def check(text, tip=None):
            c = QCheckBox(text)
            if tip:
                c.setToolTip(tip)
            c.stateChanged.connect(self._mark_dirty)
            return c

        def multiline(tip=None):
            t = QPlainTextEdit()
            t.setMaximumHeight(66)
            police_code(t)
            if tip:
                t.setToolTip(tip)
            t.textChanged.connect(self._mark_dirty)
            return t

        # -- settings --
        self.g_sourceTable = line("Table des mesures de base (défaut _mesures).")
        self.g_sourceFolder = line("displayFolder des mesures de BASE à décliner (ex. _indicateurs). Vide = toutes.")
        self.g_dateColumn = line("Colonne de date pour {date} (ex. 'dim_Date'[Date]).")
        self.g_targetTable = line("Table où créer les mesures (vide = même table que la base).")
        self.g_folderPattern = line("Dossier des variations. {baseFolder} {base} {variation} {kpi} {branch}.")
        self.g_branchFolderPattern = line("Dossier racine d'une branche (ex. {baseFolder}\\__{branch}).")
        # rangement des dossiers : par variation (les deux motifs ci-dessus)
        # ou par KPI (motifs fixes, cf. generate_measures.DOSSIERS_PAR_KPI)
        self.g_folderLayout = QComboBox()
        self.g_folderLayout.addItem("par variation : _indicateurs\\_7d avg\\Weight 7d avg",
                                    "variation")
        self.g_folderLayout.addItem("par KPI : _indicateurs\\Weight\\Weight 7d avg", "kpi")
        self.g_folderLayout.currentIndexChanged.connect(self._on_folder_layout)
        self.g_overwrite = check("overwriteExisting : réécrit les mesures générées existantes")
        self.g_removeOrphans = check("removeOrphans : supprime les mesures générées absentes du config")
        self.g_dryRun = check("dryRun : aperçu, en ligne de commande seulement")

        # symboles des formats « delta » : les 3 sur UNE ligne, le pourquoi
        # derrière le ⓘ du groupe plutôt qu'en paragraphe permanent
        self.g_delta_pos = line()
        self.g_delta_neg = line()
        self.g_delta_zero = line()
        self.g_delta_fallback = line()
        self.lbl_delta_preview = QLabel("")
        police_code(self.lbl_delta_preview, petit=True)
        self.lbl_delta_preview.setStyleSheet(f"color:{TEXT_DIM};")
        for w in (self.g_delta_pos, self.g_delta_neg, self.g_delta_zero,
                  self.g_delta_fallback):
            w.textChanged.connect(self._refresh_delta_preview)
        # -- Excel des indicateurs : LA définition, utilisée partout --
        gb_td = QGroupBox("Excel des indicateurs (TD_Indicateurs)")
        tdv = QVBoxLayout(gb_td)
        tdv.addWidget(self._resume(
            "Le classeur qui décrit les KPI, une ligne par mesure de base, "
            "défini ici une fois, utilisé par tout l'outil (attributs, "
            "couleurs des matrices, ordre des KPI)."))
        ligne1 = QHBoxLayout()
        self.g_td_path = QLineEdit()
        self.g_td_path.setPlaceholderText(
            "TD_Indicateurs.xlsx, relatif au dossier du .pbip")
        self.g_td_path.textChanged.connect(self._mark_dirty)
        self.g_td_path.editingFinished.connect(self._td_reload_columns)
        b_td = QPushButton("Parcourir…")
        b_td.clicked.connect(self._td_browse)
        b_td_rel = QPushButton("↻")
        b_td_rel.setMaximumWidth(32)
        b_td_rel.setToolTip(
            "Relire les colonnes depuis l'Excel.\n"
            "Les en-têtes sont lus une fois et gardés en mémoire : l'outil ne\n"
            "rouvre pas le classeur pendant qu'on travaille dedans. Cliquer\n"
            "ici après avoir AJOUTÉ une colonne dans Excel.\n"
            "(Les générations et les couleurs, elles, relisent toujours le\n"
            "disque : rien à rafraîchir pour qu'elles voient les changements.)")
        # clicked(bool) passerait « False » comme premier argument : le lambda
        # garantit que le bouton FORCE bien la relecture
        b_td_rel.clicked.connect(lambda: self._td_reload_columns(force=True))
        ligne1.addWidget(QLabel("Fichier :"))
        ligne1.addWidget(self.g_td_path, 1)
        ligne1.addWidget(b_td)
        ligne1.addWidget(b_td_rel)
        ligne1.addWidget(self._help("Excel des indicateurs", (
            "Le classeur qui décrit les KPI, une ligne par mesure de base.\n"
            "Défini ICI une seule fois, et utilisé par TOUT l'outil :\n\n"
            "  · jetons <<label>> figés dans le DAX (colonnes ci-dessous) ;\n"
            "  · couleurs des matrices par KPI (onglet Rapport).\n\n"
            "L'onglet Rapport lit ce réglage au lieu d'avoir le sien :\n"
            "un seul endroit à tenir à jour, et plus de divergence possible.\n\n"
            "Chemin relatif = résolu depuis le dossier du .pbip, ce qui garde\n"
            "le config transportable d'un rapport à l'autre.")))
        tdv.addLayout(ligne1)
        ligne2 = QHBoxLayout()
        ligne2.addWidget(QLabel("Colonnes (clé) :"))
        self.g_td_key = self._td_combo("mesure")
        ligne2.addWidget(self.g_td_key)
        ligne2.addWidget(QLabel("couleur de fond :"))
        self.g_td_fill = self._td_combo("couleur_fill")
        ligne2.addWidget(self.g_td_fill)
        ligne2.addWidget(QLabel("couleur de texte :"))
        self.g_td_text = self._td_combo("couleur_text")
        ligne2.addWidget(self.g_td_text)
        ligne2.addStretch()
        tdv.addLayout(ligne2)
        ligne3 = QHBoxLayout()
        ligne3.addWidget(QLabel("Ordre des KPI :"))
        self.g_td_order = self._td_combo("")
        self.g_td_order.setToolTip(
            "Colonne qui fixe l'ordre des KPI dans les tables paramètre.\n"
            "Vide = ordre alphabétique (celui de Power BI).")
        ligne3.addWidget(self.g_td_order)
        ligne3.addWidget(self._help("Ordre des KPI", (
            "Par défaut, les KPI sortent dans l'ordre ALPHABÉTIQUE : celui que\n"
            "Power BI applique de lui-même. Cette colonne prend la main :\n"
            "sa valeur devient la colonne Ordre des tables paramètre, et donc\n"
            "l'ordre du slicer (sortByColumn).\n\n"
            "Y mettre des nombres (10, 20, 30… : on peut intercaler sans tout\n"
            "renuméroter). Ils sont comparés comme des NOMBRES, donc 10 vient\n"
            "bien après 9. Une valeur texte est acceptée et se range après les\n"
            "nombres, alphabétiquement.\n\n"
            "Un KPI absent de la colonne (ou à cellule vide) part à la FIN,\n"
            "pas en tête, et le journal de génération le nomme.\n\n"
            "L'ordre vit dans l'Excel, avec le rapport : ce config-ci reste\n"
            "transportable puisqu'il ne retient que le nom de la colonne.")))
        ligne3.addStretch()
        tdv.addLayout(ligne3)
        groupes["excel"] = gb_td

        groupes["generation"] = self._form_group("Génération (settings)", [
            ("sourceTable :", self.g_sourceTable,
             "Table où le générateur cherche les mesures de BASE : les KPI.\n\n"
             "Défaut : _mesures."),
            ("sourceFolder :", self.g_sourceFolder,
             "Dossier d'affichage (displayFolder) qui contient les KPI à\n"
             "décliner. Seules ses mesures deviennent des bases : le reste de\n"
             "la table est ignoré.\n\n"
             "Ex. _indicateurs\n"
             "Vide = TOUTES les mesures de sourceTable."),
            ("dateColumn :", self.g_dateColumn,
             "La colonne de dates qui remplace le jeton {date} dans le DAX\n"
             "des variations.\n\n"
             "Ex. 'dim_Date'[Date]\n"
             "   SAMEPERIODLASTYEAR({date}) devient\n"
             "   SAMEPERIODLASTYEAR('dim_Date'[Date])"),
            ("targetTable :", self.g_targetTable,
             "Table où CRÉER les mesures générées.\n\n"
             "Vide = la table de chaque mesure de base (le cas courant)."),
            ("Dossiers :", self.g_folderLayout,
             "Comment ranger les mesures générées.\n\n"
             "PAR VARIATION : un dossier par variation, tous KPI confondus :\n"
             "   _indicateurs\\Weight\n"
             "   _indicateurs\\_7d avg\\Weight 7d avg\n"
             "   _indicateurs\\__YTD\\Weight YTD\n"
             "   _indicateurs\\__YTD\\_7d avg\\Weight YTD 7d avg\n"
             "Les deux motifs ci-dessous décident des noms.\n\n"
             "PAR KPI : un dossier par KPI, la base restant dehors ; dedans,\n"
             "toutes ses variations et un dossier par branche :\n"
             "   _indicateurs\\Weight\n"
             "   _indicateurs\\Weight\\Weight 7d avg\n"
             "   _indicateurs\\Weight\\YTD\\Weight YTD\n"
             "   _indicateurs\\Weight\\YTD\\Weight YTD 7d avg\n"
             "Les motifs ci-dessous sont alors ignorés.\n\n"
             "Changer de rangement DÉPLACE les mesures déjà générées à la\n"
             "prochaine génération (elles sont « modifiées », rien n'est\n"
             "recréé). Le choix vit dans le config : c'est celui du rapport,\n"
             "pour tout le monde."),
            ("displayFolderPattern :", self.g_folderPattern,
             "Dossier d'affichage des mesures générées.\n\n"
             "Jetons : {baseFolder} dossier de la base · {base} · {variation}\n"
             "· {kpi} · {branch}\n\n"
             "Ex. {baseFolder}\\_{variation}\n"
             "   « Weight 7d avg » va dans _indicateurs\\_7d avg\n\n"
             "Une variation peut imposer le sien (champ displayFolder de\n"
             "l'éditeur de variations)."),
            ("branchFolderPattern :", self.g_branchFolderPattern,
             "Dossier de la mesure de BRANCHE elle-même (« Weight YTD »).\n\n"
             "Ex. {baseFolder}\\__{branch}\n"
             "   « Weight YTD » va dans _indicateurs\\__YTD"),
            (None, self.g_overwrite,
             "Coché (défaut) : une mesure DÉJÀ générée est mise à jour quand le\n"
             "config change (DAX, format, dossier…).\n"
             "Décoché : elle est laissée telle quelle ; seules les NOUVELLES\n"
             "sont créées.\n\n"
             "Une mesure écrite à la main n'est JAMAIS touchée, même si elle\n"
             "porte le même nom : le générateur ne modifie que ce qu'il a\n"
             "lui-même généré."),
            (None, self.g_removeOrphans,
             "Supprime du modèle les mesures générées qui ne correspondent plus\n"
             "au config : variation retirée, KPI disparu, branche supprimée…\n\n"
             "C'est l'état de DÉPART de la case « Supprimer les orphelines »\n"
             "du panneau de génération (colonne 🚀 Lancements), c'est elle\n"
             "qui décide, au moment de générer."),
            (None, self.g_dryRun,
             "Pour la ligne de commande seulement (py generate_measures.py) :\n"
             "calcule tout, n'écrit rien.\n\n"
             "Dans l'app, c'est la case « Aperçu (dry-run) » du panneau de\n"
             "génération qui décide : ce réglage-ci y est sans effet."),
        ], resume="Où le générateur trouve les KPI, où il range ce qu'il crée, "
                  "et ce qu'il a le droit de modifier.")

        gb_d = QGroupBox("Formats « delta »")
        dv = QVBoxLayout(gb_d)
        dv.addWidget(self._resume(
            "Le signe des variations au format « delta » (+ / −, ▲ / ▼…), et "
            "leur format de secours quand la mesure de base n'en a pas."))
        drow = QHBoxLayout()
        drow.addWidget(QLabel("symboles :"))
        for lbl, w in (("positif", self.g_delta_pos), ("négatif", self.g_delta_neg),
                       ("zéro", self.g_delta_zero)):
            drow.addWidget(QLabel(lbl))
            w.setMaximumWidth(70)
            drow.addWidget(w)
        drow.addSpacing(12)
        drow.addWidget(QLabel("repli sans format :"))
        drow.addWidget(self.g_delta_fallback, 1)
        drow.addWidget(self._help("Formats « delta »", (
            "S'applique aux variations dont formatString = delta.\n\n"
            "SYMBOLES : placés devant la valeur, par section du format.\n"
            "Power BI n'ajoute aucun signe tout seul : même le « - » du négatif\n"
            "doit être écrit ici, sinon la valeur s'affiche nue.\n"
            "   +  /  -  /  (vide)      donne  +12,3   -12,3   0\n"
            "   ▲  /  ▼  /  (vide)      donne  ▲ 12,3  ▼ 12,3  0\n"
            "Avec une flèche, ne PAS mettre de « - » : la flèche porte le sens et\n"
            "la valeur s'affiche en absolu.\n\n"
            "REPLI : format utilisé quand la mesure de BASE n'a aucun\n"
            "formatString. Sans lui le delta n'hérite de rien, n'a donc aucun\n"
            "format, et AUCUN signe n'apparaît quels que soient les symboles.\n"
            "Vide = ancien comportement (pas de format).")))
        dv.addLayout(drow)
        dv.addWidget(self.lbl_delta_preview)
        groupes["delta"] = gb_d

        # -- mesures cibles (dossier dédié : bases supplémentaires) --
        gb_c = QGroupBox("Mesures cibles (dossier dédié)")
        cv = QVBoxLayout(gb_c)
        note_c = QLabel("Créer À LA MAIN la cible RACINE par KPI (ex. « Weight cible ») dans "
                        "un dossier dédié : le générateur la décline en TOUTES les variations "
                        "(comme un KPI, enveloppant [Weight cible]). Au paramètre : Indicateur "
                        "= le KPI (préfixe du nom), Calcul = « Cible » / « Cible 7d avg »… "
                        "(préfixé par le libellé ci-dessous), Branche normale. Ne mettre que la "
                        "racine ; le dossier doit différer de sourceFolder (imbriqué = OK, "
                        "matché par sa feuille).")
        note_c.setWordWrap(True)
        note_c.setStyleSheet(f"color:{TEXT_DIM};")
        cv.addWidget(note_c)
        self.g_cible_table = QTableWidget(0, 2)
        self.g_cible_table.setHorizontalHeaderLabels(["Dossier (displayFolder)", "Calcul (libellé)"])
        self.g_cible_table.verticalHeader().setVisible(False)
        self.g_cible_table.setMaximumHeight(120)
        ch = self.g_cible_table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.Stretch)
        ch.setSectionResizeMode(1, QHeaderView.Stretch)
        self.g_cible_table.itemChanged.connect(self._mark_dirty)
        cv.addWidget(self.g_cible_table)
        c_btns = QHBoxLayout()
        b_c_add = QPushButton("Ajouter")
        b_c_add.clicked.connect(lambda: self._cible_add_row("", "Cible"))
        b_c_del = QPushButton("Retirer")
        b_c_del.clicked.connect(self._cible_del_row)
        c_btns.addStretch()
        c_btns.addWidget(b_c_add)
        c_btns.addWidget(b_c_del)
        cv.addLayout(c_btns)
        groupes["cibles"] = gb_c

        # -- attributs codés en dur (au lieu de LOOKUPVALUE) --
        gb_hc = QGroupBox("Attributs codés en dur (au lieu de LOOKUPVALUE)")
        hcv = QVBoxLayout(gb_hc)
        note_hc = QLabel("N'importe quelle colonne de l'Excel peut devenir un jeton. Dans une "
                         "variation, « <<label>> » est remplacé par la valeur de la colonne pour "
                         "le KPI : un nombre, un texte (entre guillemets dans le DAX), un nom de "
                         "variable, ou du DAX propre à chaque KPI, jetons compris. "
                         "Cellule vide : pas de mesure pour ce KPI.")
        note_hc.setWordWrap(True)
        note_hc.setStyleSheet(f"color:{TEXT_DIM};")
        hcv.addWidget(note_hc)
        self.g_hc_table = QTableWidget(0, 2)
        self.g_hc_table.setHorizontalHeaderLabels(["Jeton", "Colonne"])
        self.g_hc_table.verticalHeader().setVisible(False)
        self.g_hc_table.setMaximumHeight(130)
        hh = self.g_hc_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.g_hc_table.itemChanged.connect(self._mark_dirty)
        hcv.addWidget(self.g_hc_table)
        hc_btns = QHBoxLayout()
        b_hc_add = QPushButton("Ajouter")
        b_hc_add.clicked.connect(lambda: self._hc_add_row("", ""))
        b_hc_del = QPushButton("Retirer")
        b_hc_del.clicked.connect(self._hc_del_row)
        hc_btns.addStretch()
        hc_btns.addWidget(b_hc_add)
        hc_btns.addWidget(b_hc_del)
        hcv.addLayout(hc_btns)
        groupes["attributs"] = gb_hc

        # -- branches : deux colonnes pleine hauteur (les branches à gauche,
        # ce que fait celle qui est choisie à droite) — en une colonne, deux
        # listes de 110 px empilées ne laissaient rien voir --
        gb_b = QGroupBox("Branches (variations-de-variations)")
        vb_haut = QVBoxLayout(gb_b)
        colonnes = QHBoxLayout()
        vb_haut.addLayout(colonnes, 1)
        gauche = QVBoxLayout()
        colonnes.addLayout(gauche, 2)
        note = QLabel("Cocher une variation pour qu'elle devienne une BRANCHE : ses mesures sont "
                      "redéclinées (ex. YTD → YTD PY, YTD 7d avg…).")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{TEXT_DIM};")
        gauche.addWidget(note)
        self.g_branches = QListWidget()
        self.g_branches.setStyleSheet(checkable_list_stylesheet())
        self.g_branches.setMinimumHeight(160)
        self.g_branches.itemChanged.connect(self._on_branch_toggle)
        gauche.addWidget(self.g_branches, 1)

        # ce que la branche choisie APPLIQUE : toutes les variations, sauf
        # celles qu'on décoche
        droite = QVBoxLayout()
        colonnes.addLayout(droite, 3)
        pick = QHBoxLayout()
        pick.addWidget(QLabel("Branche :"))
        self.g_branch_pick = QComboBox()
        self.g_branch_pick.currentIndexChanged.connect(self._on_branch_pick)
        pick.addWidget(self.g_branch_pick, 1)
        droite.addLayout(pick)
        note2 = QLabel("Les variations que cette branche applique. Toutes le sont par "
                       "défaut, et une variation ajoutée plus tard aussi : décocher celles "
                       "à exclure, ex. une cible autonome en {kpi} qui n'a pas à être "
                       "re-forkée.")
        note2.setWordWrap(True)
        note2.setStyleSheet(f"color:{TEXT_DIM};")
        droite.addWidget(note2)
        aide_enveloppe = (
            "Deux façons de dériver une variation en branche.\n\n"
            "ENVELOPPE (défaut) : la branche entoure la variation RÉEL :\n"
            "   Weight YTD PY = CALCULATE([Weight PY], DATESYTD(…))\n"
            "Toutes les mesures de la branche se lisent pareil, donc un écart\n"
            "se débogue dans la variation Réel. Et un correctif apporté à\n"
            "celle-ci se répercute SANS régénérer.\n\n"
            "SUBSTITUTION (case décochée) : le DAX de la variation est\n"
            "recopié avec la mesure de branche à l'intérieur,\n"
            "   Weight YTD PY = CALCULATE([Weight YTD], SAMEPERIODLASTYEAR(…))\n\n"
            "Le PATRON vient du DAX de la branche : sa base ({baseRef})\n"
            "devient la variation ({variationRef}). YTD =\n"
            "CALCULATE({baseRef}, DATESYTD({date})) donne\n"
            "CALCULATE({variationRef}, DATESYTD({date})). Le champ ne sert\n"
            "qu'à en écrire un autre.\n\n"
            "⚠ Ce n'est pas toujours équivalent. Identique pour les variations\n"
            "qui DÉCALENT le contexte (SAMEPERIODLASTYEAR) ; autre sens pour\n"
            "celles qui ÉPINGLENT une fenêtre sur la borne du contexte\n"
            "(MAX({date}), DATEADD, DATESINPERIOD), « 7d avg » enveloppé\n"
            "est le 7d avg ordinaire, pas le 7d avg du cumul YTD.\n"
            "Pour celles-là, décocher « envelopper en branche » dans l'éditeur\n"
            "de la variation : elle seule repasse en substitution.")
        enveloppe_l = QHBoxLayout()
        self.g_branch_envelopper = QCheckBox(
            "Envelopper la variation Réel (au lieu de recopier son DAX)")
        self.g_branch_envelopper.setToolTip(aide_enveloppe)
        self.g_branch_envelopper.stateChanged.connect(self._on_branch_envelopper)
        enveloppe_l.addWidget(self.g_branch_envelopper, 1)
        enveloppe_l.addWidget(self._help("Enveloppe de branche", aide_enveloppe))
        droite.addLayout(enveloppe_l)
        enrobe = QHBoxLayout()
        enrobe.addWidget(QLabel("Patron :"))
        self.g_branch_wrap = QLineEdit()
        self.g_branch_wrap.setToolTip(aide_enveloppe)
        self.g_branch_wrap.textChanged.connect(self._on_branch_wrap_changed)
        enrobe.addWidget(self.g_branch_wrap, 1)
        droite.addLayout(enrobe)
        self.g_branch_restrict = QListWidget()
        self.g_branch_restrict.setStyleSheet(checkable_list_stylesheet())
        self.g_branch_restrict.setMinimumHeight(160)
        self.g_branch_restrict.itemChanged.connect(self._on_branch_restrict_changed)
        droite.addWidget(self.g_branch_restrict, 1)
        groupes["branches"] = gb_b

        # ---- la barre latérale et ses pages ----
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.reglages_nav = QListWidget()
        self.reglages_nav.setObjectName("reglagesNav")
        self.reglages_nav.setFixedWidth(210)
        self.reglages_nav.setStyleSheet(
            "QListWidget#reglagesNav { border: none; outline: 0; }"
            "QListWidget#reglagesNav::item { padding: 8px 10px; }")
        self.reglages_pages = QStackedWidget()
        for cle, libelle in self.PAGES_REGLAGES:
            page = QScrollArea()
            page.setWidgetResizable(True)
            page.setFrameShape(QFrame.NoFrame)
            contenu = QWidget()
            pv = QVBoxLayout(contenu)
            pv.setContentsMargins(4, 0, 4, 0)
            pleine = cle in self.PAGES_PLEINES
            for g in self.GROUPES_PAGE.get(cle, (cle,)):
                pv.addWidget(groupes.pop(g), 1 if pleine else 0)
            if not pleine:
                pv.addStretch()
            page.setWidget(contenu)
            self.reglages_pages.addWidget(page)
            it = QListWidgetItem(libelle)
            it.setData(Qt.UserRole, cle)
            self.reglages_nav.addItem(it)
        assert not groupes, f"groupe sans page : {sorted(groupes)}"
        self.reglages_nav.currentRowChanged.connect(self.reglages_pages.setCurrentIndex)
        self.reglages_nav.setCurrentRow(0)
        h.addWidget(self.reglages_nav)
        h.addWidget(self.reglages_pages, 1)
        return w

    def _on_folder_layout(self, *_) -> None:
        """Par KPI, les deux motifs de dossier ne servent pas : grisés."""
        par_variation = self.g_folderLayout.currentData() == "variation"
        for w in (self.g_folderPattern, self.g_branchFolderPattern):
            w.setEnabled(par_variation)
        self._mark_dirty()

    def aller_reglages(self, cle: str) -> bool:
        """Montre la page `cle` de la fenêtre ⚙ Réglages (cf. PAGES_REGLAGES).
        Rend False pour une clé inconnue, sans rien changer. « parametres »
        n'est plus une page : c'est l'onglet Mesures → Paramètres de champ."""
        if cle == "parametres":
            self.inner.setCurrentIndex(IDX_PARAM)
            return True
        for i in range(self.reglages_nav.count()):
            if self.reglages_nav.item(i).data(Qt.UserRole) == cle:
                self.reglages_nav.setCurrentRow(i)
                return True
        return False

    def _build_reglages_dialog(self) -> QDialog:
        """La fenêtre ⚙ Réglages : les réglages globaux du config, et deux
        boutons. Construite une fois ; chaque ouverture la recharge."""
        dlg = QDialog(self)
        dlg.setWindowTitle("⚙ Réglages globaux du config")
        dlg.resize(1040, 700)
        v = QVBoxLayout(dlg)
        v.addWidget(self._build_global_tab(), 1)
        bas = QHBoxLayout()
        self.lbl_reglages_fichier = QLabel("")
        self.lbl_reglages_fichier.setStyleSheet(f"color:{TEXT_DIM};")
        bas.addWidget(self.lbl_reglages_fichier, 1)
        b_annuler = QPushButton("Annuler")
        b_annuler.setToolTip("Referme sans rien garder de ce qui a été touché ici.")
        b_annuler.clicked.connect(dlg.reject)
        self.btn_reglages_ok = QPushButton("Enregistrer")
        self.btn_reglages_ok.setToolTip(
            "Écrit le measures_config.json (backup .bak), avec TOUT ce qui\n"
            "est en attente dans le config, variations comprises.")
        self.btn_reglages_ok.setDefault(True)
        self.btn_reglages_ok.clicked.connect(dlg.accept)
        bas.addWidget(b_annuler)
        bas.addWidget(self.btn_reglages_ok)
        v.addLayout(bas)
        return dlg

    def ouvrir_reglages(self, page: str = "") -> bool:
        """⚙ Réglages : les réglages globaux, dans leur fenêtre.

        `page` : la page à montrer (clé de PAGES_REGLAGES) ; vide = celle où
        on l'avait laissée.

        Ouvrir d'abord la vue en cours dans le config (un JSON brut invalide
        arrête tout, comme pour changer de vue). « Enregistrer » écrit le
        config, comme « Sauvegarder » ; « Annuler » oublie ce qui a été touché
        dans la fenêtre — y compris l'orange qu'il avait allumé.
        Rend True si le config a été écrit."""
        if page == "parametres":
            # ce n'est plus une page des Réglages : c'est un onglet
            self.inner.setCurrentIndex(IDX_PARAM)
            return False
        if not self.project or not self.project.config_json.exists():
            QMessageBox.information(
                self, "Réglages",
                "Aucun measures_config.json chargé pour ce rapport, le choisir\n"
                "d'abord avec le bouton 📄 du config, sous la barre du projet.")
            return False
        if not self._committer_vue():
            return False
        sale_avant = self._dirty
        self._load_global()
        self.lbl_reglages_fichier.setText(str(self.project.config_json))
        if page:
            self.aller_reglages(page)
        dlg = self._dlg_reglages
        ok = (dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()) == QDialog.Accepted
        if not ok:
            self._set_dirty(sale_avant)
            return False
        self._commit_global()
        self._rafraichir_vue()      # la vue ouverte redit le config à jour
        return self._save()

    def _committer_vue(self) -> bool:
        """Verse la vue ouverte dans le config en mémoire. False si le JSON
        brut ne se lit pas (on n'irait pas plus loin sur un config faux)."""
        if self.inner.currentIndex() == IDX_RAW:
            try:
                self._config = json.loads(self.ed_raw.toPlainText())
            except ValueError as e:
                QMessageBox.warning(self, "JSON invalide",
                                    f"{e}\n\nCorriger le JSON brut d'abord.")
                return False
        elif self.inner.currentIndex() == IDX_VARIATIONS:
            self._commit_form()
        elif self.inner.currentIndex() == IDX_PARAM:
            self._commit_fp()
        return True

    def _rafraichir_vue(self) -> None:
        """Remet la vue ouverte d'accord avec le config en mémoire — sans quoi
        « Sauvegarder » depuis le JSON brut réécrirait l'ANCIEN texte par-dessus
        des réglages tout juste changés."""
        if self.inner.currentIndex() == IDX_RAW:
            self.ed_raw.blockSignals(True)
            self.ed_raw.setPlainText(
                json.dumps(self._config, indent=2, ensure_ascii=False))
            self.ed_raw.blockSignals(False)
        elif self.inner.currentIndex() == IDX_ARBRE:
            self._rafraichir_arbre()
        elif self.inner.currentIndex() == IDX_PARAM:
            self._load_fp()
            self._rafraichir_parametres()
        else:
            self._populate_list(select=self._current)

    def _arbre_si_visible(self, *_):
        # après une génération : « nouvelle / modifiée » ne sont plus vrais
        if self.inner.currentIndex() == IDX_ARBRE:
            self._rafraichir_arbre()
        elif self.inner.currentIndex() == IDX_PARAM:
            self._rafraichir_parametres()

    def _rafraichir_arbre(self) -> None:
        """L'arbre = la génération en APERÇU sur le config EN MÉMOIRE (sur une
        copie : le générateur ne doit rien y laisser). Rien n'est écrit."""
        import copy
        if not self.project or not self.project.model_dir.exists():
            self.arbre_mesures.erreur("Aucun modèle : ouvrir un projet .pbip.")
            return
        avis: list = []

        def log(ligne=""):
            ligne = str(ligne)
            if ligne.lstrip().startswith("⚠"):
                avis.append(ligne.strip())

        try:
            st = gm.generate(self.project.model_dir, copy.deepcopy(self._config),
                             dry_run=True, remove_orphans=False, log=log,
                             cache_excel=self._cache_excel)
        except SystemExit as e:
            self.arbre_mesures.erreur("Aperçu impossible : " + str(e))
            return
        except Exception as e:          # un config en cours d'écriture
            self.arbre_mesures.erreur(f"Aperçu impossible : {type(e).__name__} : {e}")
            return
        self.arbre_mesures.afficher(st.get("arbre") or [], avis)

    def _load_global(self):
        """Peuple les widgets globaux depuis le config (à l'ouverture de l'onglet)."""
        self._loading = True
        s = self._config.get("settings") or {}
        self.g_sourceTable.setText(s.get("sourceTable", "") or "")
        self.g_sourceFolder.setText(s.get("sourceFolder", "") or "")
        self.g_dateColumn.setText(s.get("dateColumn", "") or "")
        self.g_targetTable.setText(s.get("targetTable", "") or "")
        self.g_folderPattern.setText(s.get("displayFolderPattern", "") or "")
        self.g_branchFolderPattern.setText(s.get("branchFolderPattern", "") or "")
        i = self.g_folderLayout.findData(str(s.get("folderLayout") or "variation").lower())
        self.g_folderLayout.setCurrentIndex(max(i, 0))
        self._on_folder_layout()
        self.g_overwrite.setChecked(bool(s.get("overwriteExisting", True)))
        sym = s.get("deltaSymbols") or {}
        self.g_delta_pos.setText(sym.get("positive", gm.DELTA_SYMBOLS["positive"]))
        self.g_delta_neg.setText(sym.get("negative", gm.DELTA_SYMBOLS["negative"]))
        self.g_delta_zero.setText(sym.get("zero", gm.DELTA_SYMBOLS["zero"]))
        self.g_delta_fallback.setText(
            s.get("deltaFallbackFormat", gm.DELTA_FALLBACK) or "")
        self._refresh_delta_preview()
        self.g_removeOrphans.setChecked(bool(s.get("removeOrphans", False)))
        self.g_dryRun.setChecked(bool(s.get("dryRun", False)))

        hc =self._config.get("hardcodedAttributes") or {}
        td = gm.indicateurs_xlsx(self._config)
        self.g_td_path.setText(td["path"])
        self.g_td_key.setCurrentText(td["keyColumn"])
        self.g_td_fill.setCurrentText(td["fillColumn"])
        self.g_td_text.setCurrentText(td["textColumn"])
        self.g_td_order.setCurrentText(td.get("orderColumn", "") or "")
        self._td_reload_columns()
        self.g_hc_table.setRowCount(0)
        for label, col in (hc.get("tokens") or {}).items():
            self._hc_add_row(label, col)

        self.g_cible_table.setRowCount(0)
        for spec in (self._config.get("kpiMeasureFolders") or []):
            if isinstance(spec, dict):
                self._cible_add_row(spec.get("folder", "") or "",
                                    spec.get("calcul", "") or "Cible")

        self._load_branches()
        self._loading = False

    def _load_branches(self):
        """Liste cochable des variations (cochée = branche) + état des
        restrictions par branche, puis peuple l'éditeur de restriction."""
        self.g_branches.clear()
        branches = self._config.get("branches") or {}
        seen = set()
        for vid in self._variations():
            seen.add(vid)
            item = QListWidgetItem(vid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if vid in branches else Qt.Unchecked)
            item.setData(Qt.UserRole, vid)
            self.g_branches.addItem(item)
        for vid in branches:            # clés orphelines (id absent des variations)
            if vid not in seen:
                item = QListWidgetItem(vid + "  (⚠ variation absente)")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                item.setData(Qt.UserRole, vid)
                self.g_branches.addItem(item)

        # état des exclusions : branche -> set des variations qu'elle écarte.
        # L'ancien format (liste blanche « variations ») se lit avec la même
        # règle que la génération, et sera réécrit en exclusions
        self._branch_exclu = {}
        self._branch_wrap = {
            b: str((bval or {}).get("wrap") or "")
            for b, bval in branches.items() if isinstance(bval, dict)}
        self._branch_subst = {
            b: bool(isinstance(bval, dict) and bval.get("substitution"))
            for b, bval in branches.items()}
        for b, bval in branches.items():
            appliquees = set(gm.variations_de_branche(b, bval, self._variations()))
            self._branch_exclu[b] = set(self._applicable_vars(b)) - appliquees
        self._branch_pick_current = None
        self._reload_branch_pick(list(branches.keys()))

    # ---- restriction d'une branche (quelles variations elle applique) ----------

    def _applicable_vars(self, branch_id) -> list:
        """Variations qu'une branche PEUT appliquer (toutes sauf elle-même),
        dans l'ordre du config."""
        return [v for v in self._variations() if v != branch_id]

    def _checked_branch_ids(self) -> list:
        return [self.g_branches.item(i).data(Qt.UserRole)
                for i in range(self.g_branches.count())
                if self.g_branches.item(i).checkState() == Qt.Checked]

    def _on_branch_toggle(self, *_):
        """Une variation vient d'être (dé)cochée comme branche."""
        if self._loading:
            return
        self._set_dirty(True)
        self._save_branch_restrict()
        branch_ids = self._checked_branch_ids()
        for b in branch_ids:                        # nouvelles : toutes par défaut
            self._branch_exclu.setdefault(b, set())
        for b in list(self._branch_exclu):          # retirées
            if b not in branch_ids:
                del self._branch_exclu[b]
        self._reload_branch_pick(branch_ids)

    def _reload_branch_pick(self, branch_ids):
        self.g_branch_pick.blockSignals(True)
        self.g_branch_pick.clear()
        self.g_branch_pick.addItems(list(branch_ids))
        self.g_branch_pick.blockSignals(False)
        self._branch_pick_current = None
        if branch_ids:
            self._show_branch_restrict(branch_ids[0])
        else:
            self.g_branch_restrict.blockSignals(True)
            self.g_branch_restrict.clear()
            self.g_branch_restrict.blockSignals(False)

    def _show_branch_restrict(self, branch_id):
        self._branch_pick_current = branch_id
        exclues = self._branch_exclu.get(branch_id, set())
        self.g_branch_restrict.blockSignals(True)
        self.g_branch_restrict.clear()
        for v in self._applicable_vars(branch_id):
            it = QListWidgetItem(v)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked if v in exclues else Qt.Checked)
            self.g_branch_restrict.addItem(it)
        self.g_branch_restrict.blockSignals(False)
        self.g_branch_wrap.blockSignals(True)
        self.g_branch_wrap.setText(self._branch_wrap.get(branch_id, ""))
        derive = gm.patron_enveloppe(branch_id, {}, self._config.get("variations") or {})
        self.g_branch_wrap.setPlaceholderText(
            f"vide = tiré du DAX de {branch_id} : {derive}" if derive else
            f"le DAX de {branch_id} ne cite pas {{baseRef}} : écrire le patron, "
            "ex. CALCULATE({variationRef}, DATESYTD({date}))")
        self.g_branch_wrap.blockSignals(False)
        self.g_branch_envelopper.blockSignals(True)
        self.g_branch_envelopper.setChecked(not self._branch_subst.get(branch_id, False))
        self.g_branch_envelopper.blockSignals(False)
        self.g_branch_wrap.setEnabled(self.g_branch_envelopper.isChecked())
        idx = self.g_branch_pick.findText(branch_id)
        if idx >= 0 and self.g_branch_pick.currentIndex() != idx:
            self.g_branch_pick.blockSignals(True)
            self.g_branch_pick.setCurrentIndex(idx)
            self.g_branch_pick.blockSignals(False)

    def _save_branch_restrict(self):
        """Persiste les exclusions affichées dans self._branch_exclu."""
        b = self._branch_pick_current
        if not b:
            return
        self._branch_exclu[b] = {
            self.g_branch_restrict.item(i).text()
            for i in range(self.g_branch_restrict.count())
            if self.g_branch_restrict.item(i).checkState() != Qt.Checked
        }
        self._branch_wrap[b] = self.g_branch_wrap.text().strip()
        self._branch_subst[b] = not self.g_branch_envelopper.isChecked()

    def _on_branch_envelopper(self, *_):
        b = self._branch_pick_current
        if b:
            self._branch_subst[b] = not self.g_branch_envelopper.isChecked()
        self.g_branch_wrap.setEnabled(self.g_branch_envelopper.isChecked())
        self._mark_dirty()

    def _on_branch_wrap_changed(self, *_):
        if self._loading:
            return
        if self._branch_pick_current:
            self._branch_wrap[self._branch_pick_current] =                 self.g_branch_wrap.text().strip()
        self._mark_dirty()

    def _on_branch_pick(self, index):
        if self._loading or index < 0:
            return
        self._save_branch_restrict()
        self._show_branch_restrict(self.g_branch_pick.itemText(index))

    def _on_branch_restrict_changed(self, *_):
        if self._loading:
            return
        self._set_dirty(True)
        self._save_branch_restrict()

    def _commit_global(self):
        """Reporte les widgets globaux dans le config (clés vides retirées ;
        blocs fieldParameter absents non matérialisés s'ils restent
        désactivés — préserve « absent = off »)."""
        s = self._config.setdefault("settings", {})

        def sset(key, val):
            if val:
                s[key] = val
            else:
                s.pop(key, None)

        sset("sourceTable", self.g_sourceTable.text().strip())
        sset("sourceFolder", self.g_sourceFolder.text().strip())
        sset("dateColumn", self.g_dateColumn.text().strip())
        sset("targetTable", self.g_targetTable.text().strip())
        sset("displayFolderPattern", self.g_folderPattern.text().strip())
        sset("branchFolderPattern", self.g_branchFolderPattern.text().strip())
        # « variation » est le défaut : la clé n'est écrite que pour « kpi »
        sset("folderLayout", "" if self.g_folderLayout.currentData() == "variation"
             else self.g_folderLayout.currentData())
        # Excel des indicateurs : bloc unique (on n'écrit que le non-défaut)
        td = {"path": self.g_td_path.text().strip(),
              "keyColumn": self.g_td_key.currentText().strip(),
              "fillColumn": self.g_td_fill.currentText().strip(),
              "textColumn": self.g_td_text.currentText().strip(),
              "orderColumn": self.g_td_order.currentText().strip()}
        if self.project:                    # re-relativiser si possible
            try:
                td["path"] = str(Path(td["path"]).relative_to(self.project.folder))
            except ValueError:
                pass
        td = {k: v for k, v in td.items()
              if v and v != gm.INDICATEURS_DEFAUT.get(k)}
        if td:
            self._config["indicateursXlsx"] = td
        else:
            self._config.pop("indicateursXlsx", None)
        # les anciennes surcharges locales ne sont plus écrites
        for bloc, cle in (("hardcodedAttributes", "xlsx"),
                          ("hardcodedAttributes", "keyColumn"),
                          ("kpiTables", "xlsx"), ("kpiTables", "keyColumn")):
            if isinstance(self._config.get(bloc), dict):
                self._config[bloc].pop(cle, None)
        s["overwriteExisting"] = self.g_overwrite.isChecked()
        s["removeOrphans"] = self.g_removeOrphans.isChecked()
        s["dryRun"] = self.g_dryRun.isChecked()
        # symboles delta : on n'écrit le bloc que s'il s'écarte des défauts
        # (sinon on laisse le config propre). Un symbole VIDE est significatif
        # (« pas de signe »), donc on ne peut pas se contenter d'un `if val`.
        sym = {"positive": self.g_delta_pos.text(),
               "negative": self.g_delta_neg.text(),
               "zero": self.g_delta_zero.text()}
        if sym != gm.DELTA_SYMBOLS:
            s["deltaSymbols"] = sym
        else:
            s.pop("deltaSymbols", None)
        fb = self.g_delta_fallback.text()
        if fb != gm.DELTA_FALLBACK:
            s["deltaFallbackFormat"] = fb
        else:
            s.pop("deltaFallbackFormat", None)

        # la mesure Switch n'est plus générée (cf. generate_measures) : un
        # bloc « switch » resté d'une version précédente part à l'enregistrement
        self._config.pop("switch", None)

        # attributs codés en dur
        tokens = {}
        for r in range(self.g_hc_table.rowCount()):
            item = self.g_hc_table.item(r, 0)
            combo = self.g_hc_table.cellWidget(r, 1)
            label = nom_attribut(item.text()) if item else ""
            col = combo.currentText().strip() if combo else ""
            if label and col:
                tokens[label] = col
        if tokens or "hardcodedAttributes" in self._config:
            hcd = self._config.setdefault("hardcodedAttributes", {})
            if tokens:
                hcd["tokens"] = tokens
            else:
                hcd.pop("tokens", None)
            if not hcd:                              # tout vide -> pas de bloc
                self._config.pop("hardcodedAttributes", None)

        # mesures cibles (dossier dédié)
        cibles = []
        for r in range(self.g_cible_table.rowCount()):
            fi = self.g_cible_table.item(r, 0)
            ci = self.g_cible_table.item(r, 1)
            folder = fi.text().strip() if fi else ""
            calcul = ci.text().strip() if ci else ""
            if folder:                               # dossier vide -> rangée ignorée
                cibles.append({"folder": folder, "calcul": calcul or "Cible"})
        if cibles:
            self._config["kpiMeasureFolders"] = cibles
        else:
            self._config.pop("kpiMeasureFolders", None)

        self._save_branch_restrict()                 # persiste la restriction affichée
        old = self._config.get("branches") or {}
        new_branches = {}
        for i in range(self.g_branches.count()):
            item = self.g_branches.item(i)
            if item.checkState() != Qt.Checked:
                continue
            b = item.data(Qt.UserRole)
            value = dict(old.get(b) or {}) if isinstance(old.get(b), dict) else {}
            applicable = self._applicable_vars(b)    # ordre du config
            exclues = self._branch_exclu.get(b, set())
            enveloppe = (self._branch_wrap.get(b) or "").strip()
            if enveloppe:
                value["wrap"] = enveloppe
            else:
                value.pop("wrap", None)          # vide = patron tiré du DAX de la branche
            # l'enveloppe est le défaut : seule la substitution s'écrit
            if self._branch_subst.get(b):
                value["substitution"] = True
            else:
                value.pop("substitution", None)
            # des EXCLUSIONS, jamais une liste blanche : une variation ajoutée
            # plus tard est appliquée d'office (l'ancienne clé est migrée)
            value.pop("variations", None)
            excl = [v for v in applicable if v in exclues]
            if excl:
                value["excludeVariations"] = excl
            else:
                value.pop("excludeVariations", None)
            new_branches[b] = value
        if new_branches:
            self._config["branches"] = new_branches
        else:
            self._config.pop("branches", None)

    def _fp_vocabulaire(self) -> dict:
        """Ce que les filtres d'une table paramètre proposent : les KPI du
        modèle, les variations au paramètre (hors branches), les branches."""
        branches = list((self._config.get("branches") or {}).keys())
        variations = [vid for vid, tpl in (self._config.get("variations") or {}).items()
                      if isinstance(tpl, dict) and tpl.get("inFieldParameter")
                      and vid not in branches]
        kpis: list = []
        if self.project:
            try:
                _, kpis = gm.read_measures(self.project.model_dir, self._config)
            except Exception:
                kpis = []
        return {"kpis": kpis, "variations": variations, "branches": branches}

    def _mark_dirty(self, *_):
        if self._loading:
            return
        self._set_dirty(True)

    # ---- attributs codés en dur (table label/colonne) --------------------------

    def _hc_columns(self) -> list:
        return self._td_entetes()          # même cache, même classeur

    def _hc_make_combo(self, current):
        c = QComboBox()
        c.setEditable(True)
        c.setInsertPolicy(QComboBox.NoInsert)
        items = list(self._hc_columns())
        if current and current not in items:
            items.append(current)
        c.addItems(items)
        c.setCurrentText(current or "")
        c.currentTextChanged.connect(self._mark_dirty)
        return c

    def _hc_add_row(self, label, column):
        r = self.g_hc_table.rowCount()
        self.g_hc_table.insertRow(r)
        self.g_hc_table.setItem(r, 0, QTableWidgetItem(f"<<{label}>>" if label else ""))
        self.g_hc_table.setCellWidget(r, 1, self._hc_make_combo(column))
        self._mark_dirty()

    def _hc_del_row(self):
        r = self.g_hc_table.currentRow()
        if r >= 0:
            self.g_hc_table.removeRow(r)
            self._mark_dirty()




    def _cible_add_row(self, folder, calcul):
        r = self.g_cible_table.rowCount()
        self.g_cible_table.insertRow(r)
        self.g_cible_table.setItem(r, 0, QTableWidgetItem(folder or ""))
        self.g_cible_table.setItem(r, 1, QTableWidgetItem(calcul or "Cible"))
        self._mark_dirty()

    def _cible_del_row(self):
        r = self.g_cible_table.currentRow()
        if r >= 0:
            self.g_cible_table.removeRow(r)
            self._mark_dirty()

    def _hc_reload_columns(self):
        cols = list(self._hc_columns())
        for r in range(self.g_hc_table.rowCount()):
            combo = self.g_hc_table.cellWidget(r, 1)
            if combo is None:
                continue
            cur = combo.currentText().strip()
            items = list(cols)
            if cur and cur not in items:
                items.append(cur)
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(items)
            combo.setCurrentText(cur)
            combo.blockSignals(False)

    # ---- projet ------------------------------------------------------------

    def set_project(self, project):
        self.project = project
        self.model_panel.set_project(project)   # panneau de génération
        # la bibliothèque ne suit PAS le projet : on ré-affiche le même chemin
        self._refresh_biblio_label()
        path = project.config_json
        if not path.exists():
            self._config = {}
            self._current = None
            self.lst.clear()
            self.ed_raw.blockSignals(True)
            self.ed_raw.setPlainText("")
            self.ed_raw.blockSignals(False)
            self.lbl_hint.setText(
                "Aucun measures_config.json chargé, attendu : " + str(path)
                + "\nCliquer sur le bouton 📄 du config, sous la barre du projet, pour choisir celui de "
                  "CE rapport (au travail il peut vivre dans un autre dossier).")
            self.lbl_hint.show()
            for w in (self.inner, self.btn_save, self.btn_reload):
                w.setEnabled(False)
            self._set_dirty(False)
            return
        self.lbl_hint.hide()
        for w in (self.inner, self.btn_save, self.btn_reload):
            w.setEnabled(True)
        self._load_from_disk()

    def _load_from_disk(self):
        try:
            self._config = json.loads(self.project.config_json.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "measures_config.json",
                                 f"Illisible : {e}\nLe corriger dans le sous-onglet JSON brut.")
            self._config = {}
        self._populate_list()
        self.ed_raw.blockSignals(True)
        self.ed_raw.setPlainText(json.dumps(self._config, indent=2, ensure_ascii=False))
        self.ed_raw.blockSignals(False)
        # revient toujours à « Variations » après un (re)chargement : les widgets
        # globaux se rechargeront à la prochaine ouverture de leur onglet
        self.inner.blockSignals(True)
        self.inner.setCurrentIndex(IDX_VARIATIONS)
        self.inner.blockSignals(False)
        self._inner_prev = IDX_VARIATIONS
        self._set_dirty(False)
        self.vue_changee.emit()          # le changement était silencieux

    def _reload(self):
        if self.project:
            self._load_from_disk()

    def reload(self):
        """« ↻ Tout recharger » : relit TOUTES les sources de cet onglet.

        Le cache des en-têtes de TD_Indicateurs est d'abord invalidé — c'est
        précisément ce qu'on vient changer quand on ajoute une colonne dans
        l'Excel. Les modifications non enregistrées sont perdues : l'app
        demande avant d'arriver ici (cf. app._reload_all)."""
        if not self.project:
            return
        self._td_entetes_src = ""          # force la relecture de l'Excel
        self._load_from_disk()
        self._td_reload_columns(force=True)
        self._refresh_biblio_label()
        self.model_panel.set_project(self.project)   # son récap, à jour

    # ---- liste des variations -----------------------------------------------

    CLE_BIBLIO = "biblio_path"

    def _chemin_biblio(self) -> str:
        """Fichier de bibliothèque, mémorisé pour TOUTE L'APPLICATION — pas par
        projet, et pas relatif au projet courant : c'est justement le fichier
        qu'on partage entre rapports, et il ne bouge pas quand on change de
        rapport. Une fois choisi, il est retrouvé à chaque lancement.

        À défaut, celui du dossier des projets Power BI (cf. chemins) : c'est
        une donnée qu'on partage entre rapports, pas une pièce de l'outil."""
        import chemins
        defaut = str(chemins.PROJETS / gm.BIBLIO_DEFAUT)
        return str(lire_reglage(self.CLE_BIBLIO, defaut) or defaut)

    def _memoriser_biblio(self, chemin):
        """Un chemin VIDE n'écrase rien (cf. ecrire_reglage) : refermer le
        dialogue sans rien choisir ne doit pas défaire le réglage."""
        ecrire_reglage(self.CLE_BIBLIO, chemin)
        self._refresh_biblio_label()

    def _refresh_biblio_label(self):
        """Affiche le fichier retenu, et dit qu'il l'est. Sans ça, rien ne
        montrait que le chemin survit au changement de projet — on pouvait
        croire qu'il fallait le redonner chaque fois."""
        chemin = self._chemin_biblio()
        existe = Path(chemin).exists() if chemin else False
        self.lbl_biblio.setText(
            ("Bibliothèque : " if existe else "⚠ Bibliothèque introuvable : ")
            + chemin
            + ("  (mémorisée pour tous les projets)" if existe
               else ", cliquer sur « Bibliothèque… » pour en choisir une"))
        self.lbl_biblio.setStyleSheet(
            f"color:{TEXT_DIM};" if existe else f"color:{YELLOW};")

    def _ouvrir_biblio(self):
        """Pioche des variations dans la bibliothèque globale, ou y publie les
        siennes. Ce qui est importé entre DANS le config du rapport."""
        from tabs.dialog_catalogue import CatalogueDialog
        dlg = CatalogueDialog(self._config, self._chemin_biblio(), self)
        dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        self._memoriser_biblio(dlg.chemin())
        if dlg.modifie:
            self._mark_dirty()
            self._populate_list(select=self._current)

    def _refresh_catalogue_label(self):
        n = len(self._variations())
        self.lbl_catalogue.setText(
            f"{n} variation(s) dans ce rapport"
            + ("" if n else ", cliquer sur « Bibliothèque… » pour en importer"))

    def _variations(self) -> dict:
        return self._config.setdefault("variations", {})

    def _populate_list(self, select: str | None = None):
        self._loading = True
        self._current = None
        self.lst.clear()
        for vid in self._variations():
            self.lst.addItem(QListWidgetItem(vid))
        self._loading = False
        self._refresh_catalogue_label()
        if self.lst.count():
            names = [self.lst.item(i).text() for i in range(self.lst.count())]
            target = select if select in names else names[0]
            self.lst.setCurrentRow(names.index(target))

    def _on_select(self, vid: str):
        if self._loading:
            return
        self._commit_form()          # garde les édits de la variation quittée
        self._current = vid or None
        self._load_form()

    # ---- formulaire <-> config ------------------------------------------------

    def _rebuild_folder_var(self, selected: str):
        """Choix du dossier hôte : « son propre dossier » + les AUTRES
        variations ; une valeur orpheline (id disparu) est gardée, marquée."""
        self.cmb_folder_var.clear()
        self.cmb_folder_var.addItem("(son propre dossier)", "")
        for vid in self._variations():
            if vid != self._current:
                self.cmb_folder_var.addItem(vid, vid)
        idx = self.cmb_folder_var.findData(selected)
        if idx < 0 and selected:
            self.cmb_folder_var.addItem(selected + "  (⚠ variation absente)", selected)
            idx = self.cmb_folder_var.count() - 1
        self.cmb_folder_var.setCurrentIndex(max(idx, 0))

    def _load_form(self):
        v = self._variations().get(self._current)
        self._loading = True
        if v is None:
            for ed in (self.ed_name, self.ed_desc, self.ed_folder):
                ed.setText("")
            self.cmb_format.setCurrentText("")
            self._rebuild_folder_var("")
            self.cmb_datacat.setCurrentText("")
            self.chk_infp.setChecked(False)
            self.chk_kpi.setChecked(True)
            self.chk_wrap.setChecked(True)
            self.chk_cible.setChecked(False)
            self.ed_dax.setPlainText("")
        else:
            self.ed_name.setText(v.get("namePattern", ""))
            self.ed_desc.setText(v.get("description", ""))
            self.cmb_format.setCurrentText(v.get("formatString", ""))
            self.ed_folder.setText(v.get("displayFolder", ""))
            self._rebuild_folder_var(v.get("folderVariation", ""))
            self.cmb_datacat.setCurrentText(v.get("dataCategory", ""))
            self.chk_infp.setChecked(bool(v.get("inFieldParameter", False)))
            self.chk_kpi.setChecked(bool(v.get("appliesToKpi", True)))
            self.chk_cible.setChecked(bool(v.get("appliesToCibles", False)))
            self.chk_wrap.setChecked(gm.enveloppable(v))
            self._refresh_kind_items(v.get("appliesToFormats") or None)
            self.ed_exclude.setText(
                ", ".join(v.get("excludeNameContains") or []))
            self.ed_include.setText(
                ", ".join(v.get("includeNameContains") or []))
            self.ed_dax.setPlainText(dax_to_text(v.get("dax")))
        self._loading = False
        self.explorateur_jetons.set_variation(self._current or "")
        self._refresh_lint_preview()

    def _commit_form(self):
        """Reporte le formulaire dans le config (variation affichée). Les clés
        vides optionnelles sont retirées ; les clés inconnues sont préservées."""
        v = self._variations().get(self._current)
        if v is None:
            return
        self._form_vers(v)

    def _form_vers(self, v: dict) -> None:
        """Écrit le formulaire dans la variation `v` — celle du config, ou
        celle d'une COPIE (l'aperçu des noms générés)."""

        def put(key, value, keep_empty=False):
            if value or keep_empty:
                v[key] = value
            else:
                v.pop(key, None)

        put("namePattern", self.ed_name.text(), keep_empty=True)
        put("description", self.ed_desc.text())
        put("formatString", self.cmb_format.currentText().strip())
        put("displayFolder", self.ed_folder.text())
        put("folderVariation", self.cmb_folder_var.currentData() or "")
        put("dataCategory", self.cmb_datacat.currentText().strip())
        v["inFieldParameter"] = self.chk_infp.isChecked()
        # portée : on n'écrit que le NON-défaut (appliesToKpi défaut True,
        # appliesToCibles défaut False) — garde les configs existantes propres
        # envelopper est le défaut : seule la sortie s'écrit (et l'ancien
        # « wrapInBranch: true » disparaît en passant)
        if self.chk_wrap.isChecked():
            v.pop("wrapInBranch", None)
        else:
            v["wrapInBranch"] = False
        if self.chk_kpi.isChecked():
            v.pop("appliesToKpi", None)
        else:
            v["appliesToKpi"] = False
        if self.chk_cible.isChecked():
            v["appliesToCibles"] = True
        else:
            v.pop("appliesToCibles", None)
        # « tous » = aucun filtre : rien n'est alors écrit dans le config
        if self.cmb_kinds.all_checked():
            v.pop("appliesToFormats", None)
        else:
            v["appliesToFormats"] = self.cmb_kinds.checked()
        motifs = [x.strip() for x in self.ed_exclude.text().split(",") if x.strip()]
        if motifs:
            v["excludeNameContains"] = motifs
        else:
            v.pop("excludeNameContains", None)
        gardes = [x.strip() for x in self.ed_include.text().split(",") if x.strip()]
        if gardes:
            v["includeNameContains"] = gardes
        else:
            v.pop("includeNameContains", None)
        v["dax"] = text_to_dax(self.ed_dax.toPlainText())

    # ---- boutons variations ----------------------------------------------------

    def _ask_id(self, title: str, default: str = "") -> str | None:
        vid, ok = QInputDialog.getText(self, title, "Identifiant de la variation :",
                                       text=default)
        vid = (vid or "").strip()
        if not ok or not vid:
            return None
        if vid in self._variations():
            QMessageBox.warning(self, title, f"« {vid} » existe déjà.")
            return None
        return vid

    def _add(self):
        vid = self._ask_id("Ajouter une variation")
        if vid:
            self._variations()[vid] = dict(NEW_VARIATION)
            self._set_dirty(True)
            self._populate_list(select=vid)

    def _duplicate(self):
        if not self._current:
            return
        self._commit_form()
        vid = self._ask_id("Dupliquer la variation", self._current + " copie")
        if vid:
            self._variations()[vid] = json.loads(
                json.dumps(self._variations()[self._current]))
            self._set_dirty(True)
            self._populate_list(select=vid)

    def _rename(self):
        if not self._current:
            return
        self._commit_form()
        vid = self._ask_id("Renommer la variation", self._current)
        if vid:
            old = self._current
            # reconstruit le dict en conservant l'ordre des variations
            self._config["variations"] = {
                (vid if k == old else k): v for k, v in self._variations().items()
            }
            self._current = vid
            self._set_dirty(True)
            self._populate_list(select=vid)

    def _move(self, delta: int):
        """Déplace la variation courante d'un cran (l'ordre du dict = l'ordre
        de génération et de tri dans le paramètre de champ)."""
        if not self._current:
            return
        self._commit_form()
        old = self._variations()
        vids = list(old.keys())
        i = vids.index(self._current)
        j = i + delta
        if j < 0 or j >= len(vids):
            return
        vids[i], vids[j] = vids[j], vids[i]
        self._config["variations"] = {v: old[v] for v in vids}
        self._set_dirty(True)
        self._populate_list(select=self._current)

    def _delete(self):
        if not self._current:
            return
        if QMessageBox.question(
            self, "Supprimer",
            f"Supprimer la variation « {self._current} » du config ?\n"
            "(À la prochaine génération, removeOrphans supprimera ses mesures.)",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        ) != QMessageBox.Yes:
            return
        self._variations().pop(self._current, None)
        self._current = None
        self._set_dirty(True)
        self._populate_list()

    # ---- lint + aperçu ----------------------------------------------------------

    def _chevrons_connus(self) -> set:
        """Les <<labels>> déclarés dans « Attributs codés en dur » (config
        en mémoire — une déclaration fraîche compte sans enregistrer)."""
        hc = self._config.get("hardcodedAttributes") or {}
        return set((hc.get("tokens") or {}) if isinstance(hc, dict) else ())

    def _refresh_lint_preview(self):
        texts = [self.ed_name.text(), self.ed_folder.text(),
                 self.ed_desc.text(), self.ed_dax.toPlainText()]
        # le MÊME repérage que la coloration : ce qui est rouge dans
        # l'éditeur est exactement ce que cette ligne signale
        chevrons = set(JETONS_PORTEE) | self._chevrons_connus()
        # recolorer touche le document : ce n'est pas une modification
        self.ed_dax.blockSignals(True)
        self.surligneur.definir_chevrons(self._chevrons_connus())
        self.ed_dax.blockSignals(False)
        inconnus_acc, inconnus_chev = set(), set()
        for t in texts:
            for d, f, genre, connu in reperer_jetons(
                    t, KNOWN_PLACEHOLDERS, chevrons)[0]:
                if not connu and genre == "accolade":
                    inconnus_acc.add(t[d:f])
                elif not connu and genre == "chevron":
                    inconnus_chev.add(t[d:f])
        avertissements = []
        if inconnus_acc:
            avertissements.append(
                "⚠ Placeholder(s) inconnu(s) : " + ", ".join(sorted(inconnus_acc))
                + ", connus : " + ", ".join(sorted(KNOWN_PLACEHOLDERS)))
        if inconnus_chev:
            avertissements.append(
                "⚠ Attribut(s) inconnu(s) : " + ", ".join(sorted(inconnus_chev))
                + ", à déclarer dans ⚙ Réglages → Excel des "
                  "indicateurs (connus : " + (", ".join("<<%s>>" % c for c in sorted(chevrons))
                                     or "aucun") + ").")
        # Double backslash dans un format : presque toujours une correction de
        # trop. Le JSON brut AFFICHE « \\ » là où le format n'en contient qu'un
        # (échappement JSON) ; en retaper deux ici donne un backslash LITTÉRAL
        # à l'écran dans Power BI, et le format « ne marche plus ».
        fmt_txt = self.cmb_format.currentText()
        if "\\\\" in fmt_txt:
            avertissements.append(
                "⚠ formatString : « \\\\ » (double backslash) affichera un vrai "
                "backslash. Un seul suffit pour échapper un caractère, et le "
                "JSON brut en montre toujours deux, c'est normal.")
        if '"' in fmt_txt or "\\ " in fmt_txt:
            avertissements.append(
                "⚠ formatString : une espace n'a besoin de RIEN, ni "
                "guillemets, ni backslash. Écrire « #,0.00 $ ». "
                "(espace, + - $ ( ) s'affichent d'eux-mêmes ; seules les "
                "lettres et symboles demandent un backslash, ex. \\p\\t\\s.)")
        self.lbl_lint.setText("\n".join(avertissements))

        # aperçu des noms générés : reproduit l'expansion du générateur —
        # {base} = la base traitée + suffixe de branche, {kpi} = KPI racine
        # (sans branche), {variation} = id de la variation, {branch} = branche.
        # L'aperçu suit la PORTÉE cochée : une variation « aux cibles » seulement
        # doit montrer les cibles (« Weight cible »), pas les KPI.
        pattern = self.ed_name.text() or "{base}"
        vid = self._current or ""
        roots: list = []                 # (base racine, KPI racine, portée)
        notes: list = []
        kinds = None if self.cmb_kinds.all_checked() else self.cmb_kinds.checked()
        # l'aperçu applique le MÊME arbitrage que la génération
        tpl_ex = {
            "excludeNameContains": [x.strip() for x in
                                    self.ed_exclude.text().split(",") if x.strip()],
            "includeNameContains": [x.strip() for x in
                                    self.ed_include.text().split(",") if x.strip()],
        }
        if self.chk_kpi.isChecked():
            roots += [(k, k, "KPI") for k in self._preview_kpis(kinds, tpl_ex)
                      if not gm.name_excluded(tpl_ex, k)
                      or gm.name_included(tpl_ex, k)]
        if self.chk_cible.isChecked():
            cibles = self._preview_cibles()
            roots += [(c, k, "cible") for c, k in cibles
                      if not gm.name_excluded(tpl_ex, c, k)
                      or gm.name_included(tpl_ex, c, k)]
            if not cibles:
                notes.append("(aucune cible trouvée, vérifier le dossier des "
                             "cibles dans ⚙ Réglages)")
        if not roots:
            self._ecrire_apercu([[(
                "Portée vide : cocher « générer pour les KPI » et/ou « générer "
                "pour les cibles »,\nsinon cette variation n'est générée nulle part."
                + ("\n" + "\n".join(notes) if notes else ""), "etiquette")]])
            return

        variations = self._config.get("variations") or {}
        cfg_branches = self._config.get("branches") or {}

        def branche_applique(b) -> bool:
            # la MÊME règle que la génération (branch_variation_ids) : une
            # branche ne s'applique jamais à elle-même (« Weight YTD YTD »
            # s'affichait ici sans jamais être généré), et une branche
            # restreinte n'applique que les variations qu'elle liste
            return vid in gm.variations_de_branche(b, cfg_branches.get(b), variations)

        branches = [b for b in cfg_branches if branche_applique(b)]
        lignes = []
        for b in [""] + branches:
            for root, kpi, scope in roots:
                base = [(root, "racine")]
                if b:
                    # nom de la base EN BRANCHE : via le namePattern réel de la
                    # branche (« {base} YTD »…), pas un suffixe supposé
                    bpat = ((variations.get(b) or {}).get("namePattern")
                            or ("{base} " + b))
                    base = segments_nom(bpat, base, {
                        "kpi": (kpi, "racine"), "variation": (b, "branche"),
                        "branch": (b, "branche")}, "branche")
                nom = segments_nom(pattern, base, {
                    "kpi": (kpi, "racine"), "variation": (vid, "variation"),
                    "branch": (b, "branche")}, "variation")
                lignes.append([(f"[{'Réel' if not b else b} · {scope}] ",
                                "etiquette")] + nom)
        self._ecrire_apercu(lignes + [[(n, "etiquette")] for n in notes])

    def _ecrire_apercu(self, lignes: list) -> None:
        """Une ligne par nom, chaque segment dans sa couleur (cf.
        COULEURS_APERCU). Une ligne qui NOMME une mesure (elle a d'autres
        segments que son étiquette) se déplie sur son DAX et ses attributs,
        posés par _details_apercu."""
        a = self.arbre_apercu
        a.setUpdatesEnabled(False)
        a.blockSignals(True)
        a.clear()
        for segments in lignes:
            texte = "".join(t for t, _ in segments)
            it = QTreeWidgetItem([texte])
            it.setData(0, ROLE_HTML, "".join(
                f"<span style='color:{COULEURS_APERCU[st]}; white-space:pre'>"
                + t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                + "</span>" for t, st in segments))
            it.setData(0, Qt.UserRole + 9, list(segments))
            nom = "".join(t for t, st in segments if st != "etiquette")
            if nom:
                it.setData(0, Qt.UserRole, nom)
                it.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            a.addTopLevelItem(it)
        a.blockSignals(False)
        a.setUpdatesEnabled(True)
        self._minuterie_apercu.start()

    def texte_apercu(self) -> str:
        """Les lignes de l'aperçu (étiquette comprise), une par nom — sans
        les détails dépliés."""
        a = self.arbre_apercu
        return "\n".join(a.topLevelItem(i).text(0) for i in range(a.topLevelItemCount()))

    def _on_apercu_deplie(self, it) -> None:
        self._apercu_ouverts.add(it.data(0, Qt.UserRole))
        # déplié avant que les détails n'arrivent : on ne fait pas attendre
        if self._minuterie_apercu.isActive():
            self._minuterie_apercu.stop()
            self._details_apercu()

    def _rafraichir_jetons(self) -> None:
        """Les valeurs de l'explorateur de jetons : la génération à blanc,
        sur une copie du config (cf. generate_measures.apercu_jetons)."""
        ex = self.explorateur_jetons
        if not self.project or not self.project.model_dir.exists():
            ex.erreur("Ouvrir un projet .pbip pour voir ce que valent les jetons.")
            return
        try:
            donnees = gm.apercu_jetons(self.project.model_dir, self._config,
                                       self._current or "",
                                       cache_excel=self._cache_excel)
        except SystemExit as e:
            ex.erreur("Aperçu impossible : " + str(e))
            return
        except Exception as e:              # un config en cours d'écriture
            ex.erreur(f"Aperçu impossible : {type(e).__name__} : {e}")
            return
        fp = self._config.get("fieldParameter") or {}
        ex.afficher(donnees, fp.get("noBranchLabel") or "Réel")

    def _inserer_jeton(self, jeton: str) -> None:
        self.ed_dax.insertPlainText(jeton)
        self.ed_dax.setFocus()

    # ---- attributs de TD_Indicateurs, édités dans la fenêtre des jetons ------
    # La même liste que ⚙ Réglages → Excel des indicateurs : le config en
    # mémoire, que la fenêtre des Réglages relit à chaque ouverture.

    def _jetons_attributs(self) -> dict:
        return self._config.setdefault("hardcodedAttributes", {}).setdefault("tokens", {})

    def _excel_attributs(self) -> tuple:
        td = gm.indicateurs_xlsx(self._config, self.project.folder)
        bloc = self._config.get("hardcodedAttributes") or {}
        xlsx = Path(bloc.get("xlsx") or td["path"])
        if not xlsx.is_absolute():
            xlsx = self.project.folder / xlsx
        return xlsx, bloc.get("keyColumn") or td["keyColumn"]

    def _ecrire_excel(self, action, resume) -> bool:
        """`action(sauvegarde)` écrit l'Excel ; le classeur est sauvegardé
        avant. Un échec se dit dans la fenêtre, sans boîte de dialogue."""
        ex = self.explorateur_jetons
        xlsx = self._excel_attributs()[0]
        session = br.BackupSession(br.backup_root(self.project.folder, "_indicateurs_backups"),
                                   "Excel des indicateurs", self.project.folder)
        try:
            action(session.save)
        except PermissionError:
            br.abandonner(session)
            ex.message(f"{xlsx.name} est ouvert dans Excel : le fermer et réessayer.", True)
            return False
        except (OSError, ValueError) as e:
            br.abandonner(session)
            ex.message(str(e), True)
            return False
        session.close(resume)
        self._td_entetes(force=True)
        return True

    def _colonne_excel(self, colonne, valeurs=None):
        """Le vrai nom de `colonne` dans l'Excel, en la créant au besoin ;
        None si la création échoue."""
        xlsx, cle = self._excel_attributs()
        lignes = xl.lire_lignes(xlsx, max_rows=1) if xlsx.exists() else []
        for h in (lignes[0] if lignes else ()):
            if h is not None and str(h).strip().lower() == colonne.lower():
                return str(h).strip()
        if not self._ecrire_excel(
                lambda sauve: xl.ajouter_colonne(xlsx, cle, colonne, valeurs, sauve),
                f"colonne « {colonne} » ajoutée"):
            return None
        return colonne

    def _attributs_changes(self, texte, sale) -> None:
        """Après un changement de la liste : enregistre le config, sauf s'il
        portait déjà des modifications, qui restent à sauvegarder."""
        bloc = self._config.get("hardcodedAttributes")
        if isinstance(bloc, dict) and not bloc.get("tokens"):
            bloc.pop("tokens", None)
            if not bloc:
                self._config.pop("hardcodedAttributes", None)
        if sale:
            self._set_dirty(True)
            texte += " À sauvegarder avec le reste du config."
        else:
            self._save()
        self._refresh_lint_preview()
        self._rafraichir_jetons()
        self.explorateur_jetons.message(texte)

    @staticmethod
    def _nom_attribut_invalide(nom) -> bool:
        return not nom or any(c in nom for c in "<>{}")

    def _attribut_ajoute(self, label, colonne, valeur, kpi) -> None:
        ex = self.explorateur_jetons
        if not self.project:
            return
        colonne = colonne or label
        if self._nom_attribut_invalide(label) or self._nom_attribut_invalide(colonne):
            ex.message("Donner un nom de jeton, sans < > ni { }.", True)
            return
        jetons = self._jetons_attributs()
        if label in jetons:
            ex.message(f"Le jeton <<{label}>> existe déjà.", True)
            return
        sale = self._dirty
        v = xl.valeur_cellule(valeur)
        vraie = self._colonne_excel(colonne, {kpi: v} if v is not None and kpi else None)
        if vraie is None:
            self._rafraichir_jetons()
            return
        if v is not None and kpi and vraie != colonne:     # colonne déjà là
            xlsx, cle = self._excel_attributs()
            if not self._ecrire_excel(
                    lambda sauve: xl.ecrire_cellule(xlsx, cle, kpi, vraie, v, sauve),
                    f"{kpi} · {vraie}"):
                return
        jetons[label] = vraie
        ex.vider_ajout()
        self._attributs_changes(f"<<{label}>> est prêt à utiliser.", sale)

    def _attribut_renomme(self, ancien, nouveau) -> None:
        ex = self.explorateur_jetons
        jetons = self._jetons_attributs()
        if self._nom_attribut_invalide(nouveau) or nouveau in jetons or ancien not in jetons:
            ex.message(f"Impossible de renommer en « {nouveau} » : nom vide, "
                       "déjà pris ou avec < > { }.", True)
            self._rafraichir_jetons()
            return
        sale = self._dirty
        bloc = self._config["hardcodedAttributes"]
        bloc["tokens"] = {(nouveau if k == ancien else k): v for k, v in jetons.items()}
        self._attributs_changes(f"<<{ancien}>> s'appelle maintenant <<{nouveau}>>. "
                                "Le DAX qui citait l'ancien nom est à corriger.", sale)

    def _attribut_colonne(self, label, colonne) -> None:
        ex = self.explorateur_jetons
        jetons = self._jetons_attributs()
        if label not in jetons or self._nom_attribut_invalide(colonne):
            ex.message("Nom de colonne invalide.", True)
            self._rafraichir_jetons()
            return
        sale = self._dirty
        vraie = self._colonne_excel(colonne)
        if vraie is None:
            self._rafraichir_jetons()
            return
        jetons[label] = vraie
        self._attributs_changes(f"<<{label}>> lit maintenant la colonne {vraie}.", sale)

    def _attribut_valeur(self, label, colonne, kpi, valeur) -> None:
        xlsx, cle = self._excel_attributs()
        v = xl.valeur_cellule(valeur)
        if self._ecrire_excel(lambda sauve: xl.ecrire_cellule(xlsx, cle, kpi, colonne, v, sauve),
                              f"{kpi} · {colonne}"):
            self.explorateur_jetons.message(f"{kpi} : {colonne} mis à jour dans {xlsx.name}.")
        self._rafraichir_jetons()

    def _attribut_retire(self, label) -> None:
        sale = self._dirty
        self._jetons_attributs().pop(label, None)
        self._attributs_changes(f"<<{label}>> est retiré. La colonne reste dans l'Excel.", sale)

    def _details_apercu(self) -> None:
        """Le DAX et les attributs de chaque nom de l'aperçu, tirés du
        GÉNÉRATEUR en aperçu sur le config en mémoire + le formulaire en
        cours (sur une copie : rien n'est écrit, rien n'est committé). C'est
        ce qui garantit que le DAX montré est celui que « Générer » écrira,
        jetons développés, enveloppe de branche comprise."""
        import copy
        a = self.arbre_apercu
        items = [a.topLevelItem(i) for i in range(a.topLevelItemCount())
                 if a.topLevelItem(i).data(0, Qt.UserRole)]
        if not items:
            return
        noeuds, avis, erreur = {}, [], ""
        if not self.project or not self.project.model_dir.exists():
            erreur = "ouvrir un projet .pbip pour voir le DAX généré"
        else:
            cfg = copy.deepcopy(self._config)
            v = (cfg.get("variations") or {}).get(self._current)
            if v is not None:
                self._form_vers(v)

            def log(ligne=""):
                ligne = str(ligne).strip()
                if ligne.startswith("⚠"):
                    avis.append(ligne)
            try:
                st = gm.generate(self.project.model_dir, cfg, dry_run=True,
                                 remove_orphans=False, log=log,
                                 cache_excel=self._cache_excel)
                noeuds = {n["name"]: n for n in st.get("arbre") or []}
            except SystemExit as e:
                erreur = "aperçu impossible : " + str(e)
            except Exception as e:          # un config en cours d'écriture
                erreur = f"aperçu impossible : {type(e).__name__} : {e}"
        a.setUpdatesEnabled(False)
        for it in items:
            nom = it.data(0, Qt.UserRole)
            if erreur:
                ajouter_attributs(it, None, [erreur])
            else:
                ajouter_attributs(it, noeuds.get(nom),
                                  [x for x in avis if nom in x],
                                  self._apercu_ouverts, nom)
            a.blockSignals(True)
            it.setExpanded(nom in self._apercu_ouverts)
            a.blockSignals(False)
        a.setUpdatesEnabled(True)

    def _refresh_delta_preview(self):
        """Aperçu sur UNE ligne : ce que « delta » donnera à l'écran pour les
        trois cas qui comptent — base chiffrée, base en %, base sans format."""
        sym = {"positive": self.g_delta_pos.text(),
               "negative": self.g_delta_neg.text(),
               "zero": self.g_delta_zero.text()}
        fb = self.g_delta_fallback.text()

        def montre(section, val):
            """Rendu approximatif d'une section. Un littéral s'écrit
            « "X" » ou « \\X » : les DEUX doivent rendre X, sinon l'aperçu
            afficherait un backslash là où Power BI met une espace."""
            out, i = [], 0
            while i < len(section):
                c = section[i]
                if c == "\\" and i + 1 < len(section):
                    out.append(section[i + 1])       # \X -> X
                    i += 2
                else:
                    if c != chr(34):                 # "X" -> X
                        out.append(c)
                    i += 1
            txt = "".join(out)
            # le 1er groupe de codes numériques devient la valeur d'exemple
            a = 0
            while a < len(txt) and txt[a] not in "#0":
                a += 1
            b = a
            while b < len(txt) and txt[b] in "#0.,":
                b += 1
            return txt[:a] + val + txt[b:] if a < len(txt) else txt

        lignes = []
        for base_fmt, label in ((r"#,0", "#,0"),
                                ("0.0" + chr(92) + " %", "%"),
                                (None, "sans format")):
            f = gm.resolve_format("delta", base_fmt, sym, fb)
            if not f:
                lignes.append(label + " → aucun format")
                continue
            pos, neg, zero = (f.split(";") + ["", ""])[:3]
            lignes.append(label + " → " + montre(pos, "12,3")
                          + " / " + montre(neg, "12,3")
                          + " / " + montre(zero, "0"))
        self.lbl_delta_preview.setText("   ·   ".join(lignes))

    def _td_combo(self, defaut):
        """Combo éditable de colonnes de l'Excel (saisie libre permise)."""
        c = QComboBox()
        c.setEditable(True)
        c.setMinimumWidth(150)
        c.setCurrentText(defaut)
        c.currentTextChanged.connect(self._mark_dirty)
        return c

    def _td_path_resolu(self):
        """Chemin absolu de l'Excel, tel que le générateur le résoudra."""
        p = Path(self.g_td_path.text().strip() or "TD_Indicateurs.xlsx")
        if not p.is_absolute() and self.project:
            p = self.project.folder / p
        return p

    def _td_browse(self):
        depart = str(self._td_path_resolu().parent if self.project
                     else Path.home())
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Choisir l'Excel des indicateurs", depart, "Excel (*.xlsx)")
        if not chemin:
            return
        p = Path(chemin)
        # on garde un chemin RELATIF quand c'est possible : le config
        # voyage alors d'un rapport à l'autre sans retouche
        if self.project:
            try:
                p = p.relative_to(self.project.folder)
            except ValueError:
                pass
        self.g_td_path.setText(str(p))
        self._td_reload_columns()

    def _td_entetes(self, force=False) -> list:
        """En-têtes du classeur, LUS UNE FOIS puis gardés en mémoire.

        Le classeur n'est plus touché que lors d'une action explicite : au
        premier besoin, quand le chemin change, et sur « ↻ ». Rouvrir
        « ⚙ Réglages » ou passer d'un onglet à l'autre ne l'ouvre plus —
        on peut donc travailler dans Excel avec l'outil ouvert à côté.

        Les EXÉCUTIONS (génération, couleurs), elles, relisent toujours le
        disque : ce qu'on vient d'enregistrer dans Excel est pris en compte,
        sans rien avoir à rafraîchir ici."""
        chemin = str(self._td_path_resolu())
        if force or chemin != self._td_entetes_src:
            lus = model_reader.excel_headers(chemin)
            if lus:                      # fichier illisible : on garde l'ancien
                self._td_entetes_cache = lus
                self._td_entetes_src = chemin
        return self._td_entetes_cache

    def _td_reload_columns(self, force=False):
        """Peuple les combos avec les en-têtes du classeur (cf. _td_entetes)."""
        entetes = self._td_entetes(force=force)
        if not entetes:
            return
        for combo in (self.g_td_key, self.g_td_fill, self.g_td_text,
                      self.g_td_order):
            courant = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            # l'ordre est FACULTATIF : sans entrée vide, on ne pourrait plus
            # revenir au tri alphabétique une fois une colonne choisie
            combo.addItems(([""] if combo is self.g_td_order else []) + entetes)
            combo.setCurrentText(courant)
            combo.blockSignals(False)
        self._hc_reload_columns()        # les attributs déjà listés aussi

    def _kind_vocabulary(self) -> list:
        """Types proposés : ceux que le formatString permet de déduire."""
        return list(gm.FORMAT_KINDS)

    def _refresh_kind_items(self, checked=None):
        self.cmb_kinds.blockSignals(True)
        self.cmb_kinds.set_items(self._kind_vocabulary(), checked)
        self.cmb_kinds.blockSignals(False)

    def _preview_kpis(self, kinds=None, tpl_ex=None) -> list:
        """KPI du modèle, filtrés par TYPE de format si `kinds` est donné :
        l'aperçu montre alors exactement les bases qui recevront la
        variation, et aucune autre."""
        if not self.project:
            return ["KPI"]
        try:
            noms = model_reader.kpis(self.project)
        except Exception:
            return ["KPI"]
        if kinds:
            try:
                ex, _ = gm.read_measures(self.project.model_dir, self._config)
                noms = [n for n in noms
                        if gm.format_kind((ex.get(n) or {}).get("format")) in kinds
                        or gm.name_included(tpl_ex or {}, n)]
            except Exception:
                pass
        return noms[:6]

    def _preview_cibles(self) -> list:
        """[(cible racine, KPI)] — via generate_measures.scan_cibles, donc
        exactement ce que la génération déclinera."""
        if not self.project:
            return [("KPI cible", "KPI")]
        try:
            return gm.scan_cibles(self.project.model_dir, self._config)[:6]
        except Exception:
            return []

    # ---- synchronisation des deux vues ------------------------------------------

    def showEvent(self, event):
        # l'onglet Mesures est à l'écran : son bouton « Générer » aussi, en
        # tête du journal
        super().showEvent(event)
        self.model_panel.show()

    def hideEvent(self, event):
        # ailleurs, générer n'a pas de sens : le journal reste un journal
        super().hideEvent(event)
        self.model_panel.hide()

    def occupe_la_colonne(self) -> bool:
        """La vue courante a-t-elle sa propre colonne de droite ? Oui pour
        « Variations » (DAX + aperçu) : la fenêtre y masque le journal —
        sauf si l'usager l'y a voulu (bouton « 🚀 Lancements »)."""
        return self.inner.currentIndex() in (IDX_VARIATIONS, IDX_PARAM)

    def _on_view_switch(self, index: int):
        # 1) committer / valider l'onglet que l'on QUITTE
        prev = self._inner_prev
        if prev == IDX_VARIATIONS:
            self._commit_form()
        elif prev == IDX_PARAM:
            self._commit_fp()
        elif prev == IDX_RAW:
            try:
                self._config = json.loads(self.ed_raw.toPlainText())
            except ValueError as e:
                QMessageBox.warning(self, "JSON invalide",
                                    f"{e}\n\nCorriger le JSON brut avant de changer de vue.")
                self.inner.blockSignals(True)
                self.inner.setCurrentIndex(IDX_RAW)
                self.inner.blockSignals(False)
                self._inner_prev = IDX_RAW
                return
        # 2) charger l'onglet que l'on OUVRE (depuis le config en mémoire)
        if index == IDX_VARIATIONS:
            self._populate_list(select=self._current)
        elif index == IDX_ARBRE:
            self._rafraichir_arbre()
        elif index == IDX_PARAM:
            self._load_fp()
            self._rafraichir_parametres()
        elif index == IDX_RAW:
            self.ed_raw.blockSignals(True)
            self.ed_raw.setPlainText(json.dumps(self._config, indent=2, ensure_ascii=False))
            self.ed_raw.blockSignals(False)
        self._inner_prev = index
        self.vue_changee.emit()

    def _validate_raw(self):
        try:
            json.loads(self.ed_raw.toPlainText())
        except ValueError as e:
            QMessageBox.warning(self, "JSON invalide", str(e))
            return
        QMessageBox.information(self, "JSON", "JSON valide. ✔")

    # ---- état / sauvegarde --------------------------------------------------------

    def _on_edit(self, *args):
        if self._loading:
            return
        self._set_dirty(True)
        self._refresh_lint_preview()

    def _set_dirty(self, dirty: bool):
        """L'état « non sauvegardé » s'affiche EN ALLUMANT le bouton, plutôt
        que dans un voyant posé à côté : un seul endroit à regarder, et il se
        trouve être celui sur lequel cliquer."""
        self._dirty = dirty
        # le générateur lit le FICHIER : son panneau le signale en continu
        self.model_panel.set_unsaved(dirty)
        if dirty:
            # un « ✔ écrit » resté affiché ne serait plus vrai
            self.lbl_dirty.setText("")
        bouton_en_attente(
            self.btn_save, dirty,
            en_attente="Modifications NON sauvegardées, écrit le "
                       "measures_config.json (backup .bak).",
            au_repos="Écrit le measures_config.json (backup .bak).")

    def save_all(self):
        """« Enregistrer puis recharger » de l'app : écrit si nécessaire."""
        if self._dirty:
            self._save()

    def _save(self, *_) -> bool:
        """Écrit le config ; rend True si c'est fait (le panneau de
        génération s'en sert pour « Enregistrer puis générer »)."""
        if not self.project:
            return False
        path = self.project.config_json
        idx = self.inner.currentIndex()
        if idx == IDX_RAW:                   # vue JSON brut : parser d'abord
            try:
                self._config = json.loads(self.ed_raw.toPlainText())
            except ValueError as e:
                QMessageBox.critical(self, "JSON invalide", f"Rien écrit : {e}")
                return False
        elif idx == IDX_VARIATIONS:
            self._commit_form()
        elif idx == IDX_PARAM:
            self._commit_fp()

        try:
            if path.exists():
                shutil.copy2(str(path), str(path) + ".bak")
            path.write_text(json.dumps(self._config, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, "Erreur d'écriture", str(e))
            return False
        self._set_dirty(False)
        self.model_panel.set_project(self.project)   # son récap, relu du disque
        # pas de popup : confirmation dans le bandeau d'état
        self.lbl_dirty.setText(f"✔ {path.name} écrit (backup .bak), "
                               "« Générer les mesures » en tête du journal")
        self.journal.info(f"✔ {path.name} écrit (backup .bak)")
        return True
