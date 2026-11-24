# -*- coding: utf-8 -*-
"""Les attributs d'une mesure générée, son DAX surtout, tels que « Générer »
les écrira. Deux façons de les montrer, sur la même liste :

- `ajouter_attributs(item, noeud)` les pose en ENFANTS d'une ligne d'arbre
  (Variations, aperçu des noms générés : on déplie un nom) ;
- `FicheMesure` est un panneau qui montre la mesure choisie (Arbre des
  mesures : ses lignes ont déjà des enfants, les mesures dérivées).

Le `noeud` est une entrée de stats["arbre"] du générateur en aperçu : nom,
type, DAX DÉJÀ DÉVELOPPÉ (jetons remplacés), format, dossier... Rien n'est
recalculé ici, et c'est ce qui garantit que l'on voit ce qui sera écrit.

Le DAX est COLORÉ comme dans l'éditeur : ce qui a remplacé un {jeton} en
bleu, un <<jeton>> en vert. Le générateur rend aussi le DAX d'avant
développement (« dax_modele ») ; segments_dax() aligne les deux pour
retrouver ce que chaque jeton est devenu.
"""

from __future__ import annotations

import re

from qtpy.QtCore import QRectF, QSize, Qt
from qtpy.QtGui import (QAbstractTextDocumentLayout, QBrush, QColor, QFont,
                        QPalette, QTextCharFormat, QTextCursor, QTextDocument)
from qtpy.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.theme import (ACCENT, BLUE, ORANGE, TEXT, TEXT_DIM, TEXT_MUTED, YELLOW,
                        police_code)

import generate_measures as gm

# rôle de donnée d'une ligne écrite en HTML (segments colorés) : peinte par
# DelegueRiche ; son texte brut reste dans DisplayRole (recherche, tests)
ROLE_HTML = Qt.UserRole + 7
# rôle qui marque une ligne d'ATTRIBUT (enfant d'aperçu), pour la distinguer
# d'une mesure
ROLE_ATTRIBUT = Qt.UserRole + 8

TYPES = {"base": "base (écrite à la main)", "cible": "cible racine (écrite à la main)",
         "variation": "variation", "branche": "branche (devient une base)"}
# la couleur de ce qu'est devenu un jeton : celles de l'éditeur DAX
COULEUR_JETON = {"accolade": BLUE, "chevron": ACCENT}
_JETON = re.compile(r"<<.*?>>|\{[A-Za-z_][A-Za-z0-9_]*\}", re.S)


def attributs(n: dict) -> list:
    """[(libellé, valeur)] d'un nœud, DAX exclu. La valeur est un texte, sauf
    pour « paramètres » : la LISTE des tables (chaque vue la déroule à sa
    façon). Seul ce qui a une valeur est rendu."""
    out = [("type", TYPES.get(n.get("type"), n.get("type") or ""))]
    if n.get("type") in ("variation", "branche") and n.get("kpi"):
        out.append(("ICP", n["kpi"] + (" (cible)" if n.get("cible") else "")))
    if n.get("variation") and n.get("type") != "branche":
        out.append(("variation", n["variation"]))
    if n.get("branche"):
        out.append(("branche", n["branche"]))
        if n.get("type") == "variation":
            out.append(("en branche", "enveloppe la variation Réel" if n.get("enveloppe")
                        else "DAX recopié (substitution)"))
    for cle, lib in (("format", "format"), ("dossier", "dossier"),
                     ("description", "description"), ("dataCategory", "catégorie")):
        if n.get(cle):
            out.append((lib, str(n[cle])))
    out.append(("paramètres", list(n.get("tables") or [])))
    if n.get("etat"):
        out.append(("génération", n["etat"]))
    return out


def segments_dax(n: dict) -> tuple:
    """(segments, substitutions) du DAX d'un nœud. `segments` : [(texte,
    genre)] où genre vaut None (texte écrit tel quel), « accolade » ou
    « chevron » (ce qu'un jeton est devenu) ; `substitutions` : [(jeton(s),
    valeur)]. Faute de modèle, ou s'il ne s'aligne pas, tout le DAX est un
    seul segment neutre : on ne colore jamais au hasard."""
    dax = n.get("dax") or ""
    modele = n.get("dax_modele") or ""
    if not dax or not modele or n.get("type") in ("base", "cible"):
        return [(dax, None)], []
    # {branch} s'efface avec son espace hors branche : on applique la même
    # règle au modèle, et il n'y reste qu'en branche (où il devient « YTD »)
    modele = gm.remplacer_branche(modele, n.get("branche") or "")
    morceaux: list = []          # [(littéral | None, [jetons])]
    pos = 0
    for m in _JETON.finditer(modele):
        if m.start() > pos:
            morceaux.append((modele[pos:m.start()], []))
        if morceaux and morceaux[-1][0] is None:
            morceaux[-1][1].append(m.group(0))     # jetons collés : un seul groupe
        else:
            morceaux.append((None, [m.group(0)]))
        pos = m.end()
    if pos < len(modele):
        morceaux.append((modele[pos:], []))
    if not any(lit is None for lit, _ in morceaux):
        return [(dax, None)], []
    motif = "".join(re.escape(lit) if lit is not None else "(.*?)" for lit, _ in morceaux)
    try:
        m = re.fullmatch(motif, dax, re.S)
    except re.error:
        m = None
    if m is None:
        return [(dax, None)], []
    segments, subs, g = [], [], 0
    for lit, jetons in morceaux:
        if lit is not None:
            segments.append((lit, None))
            continue
        g += 1
        val = m.group(g)
        genre = "chevron" if any(j.startswith("<<") for j in jetons) else "accolade"
        if val:
            segments.append((val, genre))
        subs.append(("".join(jetons), val))
    return segments, subs


def html_dax(segments) -> str:
    """Le DAX en HTML, chaque remplacement dans sa couleur, lignes et
    retraits gardés."""
    out = []
    for texte, genre in segments:
        t = _html(texte).replace("\n", "<br>")
        if genre:
            out.append(f"<span style='color:{COULEUR_JETON[genre]}; font-weight:bold'>{t}</span>")
        else:
            out.append(t)
    return f"<span style='color:{TEXT}; white-space:pre'>{''.join(out)}</span>"


def infobulle_dax(dax, subs) -> str:
    if not subs:
        return dax
    vus, lignes = set(), []
    for jeton, val in subs:
        if (jeton, val) not in vus:
            vus.add((jeton, val))
            lignes.append(f"{jeton}  →  {val or '(rien)'}")
    return "Jetons remplacés :\n" + "\n".join(lignes)


def ajouter_attributs(item: QTreeWidgetItem, n: dict | None, avis=(),
                      ouverts=(), cle: str = "") -> None:
    """Remplace les enfants de `item` par les attributs de `n` : le DAX en
    premier (c'est ce qu'on vient voir), puis une ligne par attribut,
    libellés alignés (la vue est en chasse fixe). Les paramètres de champ
    sont une ligne REPLIABLE (« paramètres  4 tables »), une table par
    enfant. `ouverts` / `cle` : les lignes repliables à rouvrir, connues par
    la clé « <cle>|paramètres ». Sans nœud : la ou les raisons, tirées des
    ⚠ du générateur qui nomment la mesure."""
    item.takeChildren()

    def enfant(texte, couleur=None, tip="", parent=None):
        e = QTreeWidgetItem([texte])
        e.setData(0, ROLE_ATTRIBUT, True)
        e.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        if couleur:
            e.setForeground(0, QBrush(QColor(couleur)))
        if tip:
            e.setToolTip(0, tip)
        (parent or item).addChild(e)
        return e

    if n is None:
        raisons = list(avis) or ["pas dans l'aperçu de la génération : un "
                                 "conflit de nom ou un jeton sans valeur ; "
                                 "le journal de « Générer » le dira"]
        for r in raisons:
            enfant(r, YELLOW)
        return
    dax = n.get("dax") or "(pas de DAX)"
    segments, subs = segments_dax(n)
    e_dax = enfant(dax, TEXT, infobulle_dax(dax, subs))
    e_dax.setData(0, ROLE_HTML, html_dax(segments))
    lignes = attributs(n)
    large = max(len(lib) for lib, _ in lignes)
    for lib, val in lignes:
        if isinstance(val, list):
            if not val:
                enfant(f"{lib.ljust(large)}  aucun", TEXT_MUTED)
                continue
            e = enfant(f"{lib.ljust(large)}  {len(val)} table{'s' if len(val) > 1 else ''}",
                       TEXT_MUTED, "\n".join(val))
            e.setData(0, Qt.UserRole, f"{cle}|{lib}")
            for t in val:
                enfant(t, TEXT_DIM, parent=e)
            e.setExpanded(f"{cle}|{lib}" in ouverts)
        else:
            enfant(f"{lib.ljust(large)}  {val}", TEXT_MUTED, val)


class DelegueRiche(QStyledItemDelegate):
    """Peint en HTML les lignes qui portent ROLE_HTML (un nom aux segments
    colorés, un DAX aux jetons colorés), les autres comme d'habitude. Le
    texte brut reste dans DisplayRole : sélection, filtre et findItems
    l'utilisent."""

    def _document(self, option, html) -> QTextDocument:
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDocumentMargin(0)
        doc.setHtml(html)
        return doc

    def paint(self, painter, option, index):
        html = index.data(ROLE_HTML)
        if not html:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        zone = style.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget)
        doc = self._document(opt, html)
        painter.save()
        painter.translate(zone.left(), zone.top()
                          + max(0, (zone.height() - doc.size().height()) / 2))
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(QPalette.Text, opt.palette.color(QPalette.Text))
        ctx.clip = QRectF(0, 0, zone.width(), zone.height())
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index):
        html = index.data(ROLE_HTML)
        if not html:
            return super().sizeHint(option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        doc = self._document(opt, html)
        base = super().sizeHint(option, index)
        return QSize(int(doc.idealWidth()) + 8, max(base.height(), int(doc.size().height())))


class FicheMesure(QWidget):
    """Le panneau « fiche » d'une mesure : nom et attributs à gauche, le DAX
    à droite, en lecture seule, en chasse fixe, coloré comme dans l'éditeur
    et sélectionnable (copier un bout de DAX est ce qu'on y fait le plus)."""

    VIDE = "Choisir une mesure pour voir son DAX et ses attributs."

    def __init__(self, parent=None):
        super().__init__(parent)
        # empilés, les attributs mangeaient la hauteur et le DAX n'avait plus
        # que deux lignes
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 4, 0, 0)
        gauche = QVBoxLayout()
        self.lbl_nom = QLabel(self.VIDE)
        self.lbl_nom.setWordWrap(True)
        self.lbl_nom.setTextInteractionFlags(Qt.TextSelectableByMouse)
        gauche.addWidget(self.lbl_nom)
        self.lbl_attributs = QLabel("")
        self.lbl_attributs.setWordWrap(True)
        self.lbl_attributs.setTextFormat(Qt.RichText)
        self.lbl_attributs.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_attributs.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        gauche.addWidget(self.lbl_attributs)
        gauche.addStretch()
        h.addLayout(gauche, 2)
        self.ed_dax = QPlainTextEdit()
        self.ed_dax.setReadOnly(True)
        self.ed_dax.setLineWrapMode(QPlainTextEdit.NoWrap)
        police_code(self.ed_dax)
        h.addWidget(self.ed_dax, 3)
        self.vider()

    def vider(self, texte: str = "") -> None:
        self.lbl_nom.setText(texte or self.VIDE)
        self.lbl_nom.setStyleSheet(f"color:{TEXT_DIM};")
        self.lbl_attributs.setText("")
        self.lbl_attributs.setVisible(False)
        self.ed_dax.setPlainText("")
        self.ed_dax.setToolTip("")
        self.ed_dax.setVisible(False)

    def montrer(self, n: dict) -> None:
        couleur = {"branche": BLUE, "cible": ORANGE}.get(n.get("type"), ACCENT)
        self.lbl_nom.setText(n.get("name", ""))
        self.lbl_nom.setStyleSheet(f"color:{couleur}; font-weight:bold;")

        def cellule(val):
            if isinstance(val, list):     # les tables : une par ligne
                return "<br>".join(_html(v) for v in val) or "aucun"
            return _html(val)
        lignes = "".join(
            f"<tr><td style='color:{TEXT_DIM}; padding-right:12px'>{_html(lib)}</td>"
            f"<td>{cellule(val)}</td></tr>" for lib, val in attributs(n))
        self.lbl_attributs.setText(f"<table cellspacing='0'>{lignes}</table>")
        self.lbl_attributs.setVisible(True)
        dax = n.get("dax") or "(pas de DAX)"
        segments, subs = segments_dax(n)
        self.ed_dax.setPlainText(dax)
        if any(g for _, g in segments):
            c = QTextCursor(self.ed_dax.document())
            pos = 0
            for texte, genre in segments:
                if genre:
                    f = QTextCharFormat()
                    f.setForeground(QColor(COULEUR_JETON[genre]))
                    f.setFontWeight(QFont.Bold)
                    c.setPosition(pos)
                    c.setPosition(pos + len(texte), QTextCursor.KeepAnchor)
                    c.mergeCharFormat(f)
                pos += len(texte)
        self.ed_dax.setToolTip(infobulle_dax(dax, subs) if subs else "")
        self.ed_dax.setVisible(True)

    def texte_dax(self) -> str:
        return self.ed_dax.toPlainText()


def _html(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
