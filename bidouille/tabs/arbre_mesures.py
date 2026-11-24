# -*- coding: utf-8 -*-
"""Onglet Mesures → « Arbre des mesures » : tout ce que la génération
produira, rangé comme cela se dérive.

    Weight                       (base, écrite à la main)
      Weight 7d avg              variation
      Weight YTD                 branche — devient une base
        Weight YTD 7d avg        variation en branche
      Weight cible               cible racine
        Weight cible écart       variation de la cible

L'arbre vient du générateur lui-même (generate_measures.generate en APERÇU,
qui n'écrit rien) : il ne peut pas montrer autre chose que ce que « Générer »
fera. Il suit le config EN MÉMOIRE — une variation ajoutée ou une table
paramètre filtrée s'y voit avant même d'enregistrer.

Le marqueur ◆ dit qu'une mesure est dans au moins une table paramètre de
champ ; l'infobulle dit lesquelles.

Deux rangements, au choix (mémorisé) :
- PAR KPI (ci-dessus) : chaque mesure sous celle dont elle dérive ;
- PAR VARIATION : un groupe par variation (« 7d avg » : Weight 7d avg,
  Steps 7d avg…), un par branche, qui tient ses mesures de branche puis un
  sous-groupe par variation en branche. C'est la question « qu'est-ce que
  7d avg produit, partout ? ».

Sous l'arbre, la FICHE de la mesure choisie : son DAX tel qu'il sera écrit
(jetons développés) et ses attributs.
"""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtGui import QBrush, QColor, QFont
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.project import ecrire_reglage, lire_reglage
from core.theme import ACCENT, BLUE, ORANGE, TEXT_DIM, TEXT_MUTED, YELLOW
from tabs.fiche_mesure import TYPES, FicheMesure

COL_NOM, COL_PARAM, COL_ETAT = 0, 1, 2
MARQUEUR = "◆"
COULEUR_ETAT = {"nouvelle": ACCENT, "modifiée": YELLOW}
# rangements de la vue : (clé mémorisée, libellé)
RANGEMENTS = (("kpi", "par ICP"), ("variation", "par variation"))
CLE_RANGEMENT = "arbre_mesures/rangement"
# un GROUPE (rangement par variation) n'est pas une mesure : sa clé de
# pliage est préfixée « groupe| », et element() l'ignore
ROLE_GROUPE = Qt.UserRole + 1


class ArbreMesures(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._noeuds: list = []
        self._par_nom: dict = {}
        self._replies: set = set()      # mesures et groupes repliés par l'usager

        v = QVBoxLayout(self)
        haut = QHBoxLayout()
        self.cmb_rangement = QComboBox()
        for cle, lib in RANGEMENTS:
            self.cmb_rangement.addItem(lib, cle)
        self.cmb_rangement.setToolTip(
            "par ICP : chaque mesure sous celle dont elle dérive.\n"
            "par variation : un groupe par variation et par branche,\n"
            "tout ce qu'une variation produit, d'un coup d'œil.")
        i = self.cmb_rangement.findData(lire_reglage(CLE_RANGEMENT, "kpi"))
        self.cmb_rangement.setCurrentIndex(max(0, i))
        self.cmb_rangement.currentIndexChanged.connect(self._on_rangement)
        self.ed_filtre = QLineEdit()
        self.ed_filtre.setPlaceholderText("Filtrer (nom, variation, branche…)")
        self.ed_filtre.setClearButtonEnabled(True)
        self.ed_filtre.textChanged.connect(self._filtrer)
        self.chk_param = QCheckBox(MARQUEUR + " seulement")
        self.chk_param.setToolTip("Ne montrer que les mesures présentes dans au moins "
                                  "une table paramètre de champ.")
        self.chk_param.stateChanged.connect(self._filtrer)
        b_deplier = QPushButton("Tout déplier")
        b_deplier.clicked.connect(lambda: self._tout(True))
        b_replier = QPushButton("Tout replier")
        b_replier.clicked.connect(lambda: self._tout(False))
        haut.addWidget(self.cmb_rangement)
        haut.addWidget(self.ed_filtre, 1)
        haut.addWidget(self.chk_param)
        haut.addWidget(b_deplier)
        haut.addWidget(b_replier)
        v.addLayout(haut)

        self.lbl_resume = QLabel("")
        self.lbl_resume.setWordWrap(True)
        self.lbl_resume.setStyleSheet(f"color:{TEXT_DIM};")
        v.addWidget(self.lbl_resume)

        self.arbre = QTreeWidget()
        self.arbre.setColumnCount(3)
        self.arbre.setHeaderLabels(["Mesure", "Paramètres", "À la génération"])
        self.arbre.setUniformRowHeights(True)
        self.arbre.setAlternatingRowColors(False)
        h = self.arbre.header()
        h.setSectionResizeMode(COL_NOM, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_PARAM, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_ETAT, QHeaderView.ResizeToContents)
        h.setStretchLastSection(False)
        self.arbre.itemCollapsed.connect(lambda it: self._replies.add(it.data(0, Qt.UserRole)))
        self.arbre.itemExpanded.connect(lambda it: self._replies.discard(it.data(0, Qt.UserRole)))
        self.arbre.currentItemChanged.connect(self._on_choix)

        # l'arbre en haut, la fiche de la mesure choisie en bas
        self.fiche = FicheMesure()
        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self.arbre)
        self.split.addWidget(self.fiche)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        v.addWidget(self.split, 1)

        self.lbl_avis = QLabel("")
        self.lbl_avis.setWordWrap(True)
        self.lbl_avis.setStyleSheet(f"color:{YELLOW};")
        self.lbl_avis.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.lbl_avis)

    # ---- API ---------------------------------------------------------------

    def afficher(self, noeuds, avis=None) -> None:
        """`noeuds` : stats["arbre"] du générateur. `avis` : ses ⚠ éventuels."""
        self._noeuds = list(noeuds or [])
        self._construire()
        avis = [a for a in (avis or []) if a]
        self.lbl_avis.setText("\n".join(avis[:6]) + ("\n…" if len(avis) > 6 else ""))
        self.lbl_avis.setVisible(bool(avis))

    def erreur(self, texte: str) -> None:
        self._noeuds = []
        self._par_nom = {}
        self.arbre.clear()
        self.fiche.vider()
        self.lbl_resume.setText("")
        self.lbl_avis.setText(texte)
        self.lbl_avis.setVisible(True)

    def element(self, nom):
        """L'élément de l'arbre d'une mesure (tests, navigation) — jamais un
        groupe du rangement par variation."""
        trouves = self.arbre.findItems(nom, Qt.MatchExactly | Qt.MatchRecursive, COL_NOM)
        trouves = [t for t in trouves if not t.data(0, ROLE_GROUPE)]
        return trouves[0] if trouves else None

    def rangement(self) -> str:
        return self.cmb_rangement.currentData() or "kpi"

    def choisir(self, nom) -> bool:
        """Sélectionne une mesure : la fiche la montre."""
        it = self.element(nom)
        if it is not None:
            self.arbre.setCurrentItem(it)
            self.arbre.scrollToItem(it)
        return it is not None

    # ---- construction ----------------------------------------------------------

    def _on_rangement(self, *_) -> None:
        ecrire_reglage(CLE_RANGEMENT, self.rangement())
        self._construire()

    def _construire(self) -> None:
        courant = self.arbre.currentItem()
        choisi = courant.data(0, Qt.UserRole) if courant is not None else None
        self._par_nom = {n["name"]: n for n in self._noeuds}
        self.arbre.setUpdatesEnabled(False)
        self.arbre.blockSignals(True)
        self.arbre.clear()
        if self.rangement() == "variation":
            self._construire_par_variation()
        else:
            self._construire_par_kpi()
        self.arbre.blockSignals(False)
        self.arbre.setUpdatesEnabled(True)
        # la fiche reste sur la même mesure à travers un rafraîchissement ou
        # un changement de rangement
        it = self.element(choisi) if choisi else None
        if it is not None:
            self.arbre.setCurrentItem(it)
            self.arbre.scrollToItem(it)
        self._on_choix(it)
        self._filtrer()
        self._resumer()

    def _ligne(self, n) -> QTreeWidgetItem:
        """La ligne d'une mesure, la même dans les deux rangements."""
        it = QTreeWidgetItem([n["name"], "", n.get("etat") or ""])
        it.setData(0, Qt.UserRole, n["name"])
        typ = n.get("type")
        details = [TYPES.get(typ, typ or "")]
        if n.get("variation") and typ != "branche":
            details.append("variation : " + n["variation"])
        if n.get("branche"):
            details.append("branche : " + n["branche"])
        if n.get("cible") and typ != "cible":
            details.append("de la cible")
        tables = n.get("tables") or []
        if tables:
            it.setText(COL_PARAM, MARQUEUR + (f" {len(tables)}" if len(tables) > 1 else ""))
            it.setForeground(COL_PARAM, QBrush(QColor(ACCENT)))
            it.setToolTip(COL_PARAM, "Dans les tables paramètre :\n  "
                          + "\n  ".join(tables))
            details.append("paramètres : " + ", ".join(tables))
        else:
            it.setToolTip(COL_PARAM, "Dans aucune table paramètre de champ.")
        it.setToolTip(COL_NOM, n["name"] + "\n" + "\n".join(details))
        if typ in ("base", "cible"):
            f = QFont(it.font(COL_NOM))
            f.setBold(True)
            it.setFont(COL_NOM, f)
        if typ == "branche":
            it.setForeground(COL_NOM, QBrush(QColor(BLUE)))
        elif typ == "cible":
            it.setForeground(COL_NOM, QBrush(QColor(ORANGE)))
        couleur = COULEUR_ETAT.get(n.get("etat"))
        it.setForeground(COL_ETAT, QBrush(QColor(couleur or TEXT_DIM)))
        return it

    def _construire_par_kpi(self) -> None:
        enfants: dict = {}
        noms = {n["name"] for n in self._noeuds}
        for n in self._noeuds:
            parent = n.get("parent")
            enfants.setdefault(parent if parent in noms else None, []).append(n)

        def ajouter(parent_item, n):
            it = self._ligne(n)
            if parent_item is None:
                self.arbre.addTopLevelItem(it)
            else:
                parent_item.addChild(it)
            for e in enfants.get(n["name"], []):
                ajouter(it, e)
            it.setExpanded(n["name"] not in self._replies)

        for n in enfants.get(None, []):
            ajouter(None, n)

    def _groupe(self, parent_item, cle, texte, couleur=None) -> QTreeWidgetItem:
        g = QTreeWidgetItem([texte, "", ""])
        g.setData(0, Qt.UserRole, "groupe|" + cle)
        g.setData(0, ROLE_GROUPE, True)
        f = QFont(g.font(COL_NOM))
        f.setBold(True)
        g.setFont(COL_NOM, f)
        g.setForeground(COL_NOM, QBrush(QColor(couleur or TEXT_DIM)))
        g.setForeground(COL_ETAT, QBrush(QColor(TEXT_MUTED)))
        if parent_item is None:
            self.arbre.addTopLevelItem(g)
        else:
            parent_item.addChild(g)
        return g

    def _construire_par_variation(self) -> None:
        """Un groupe par variation, dans l'ordre où la génération les produit
        (celui du config) ; un par branche, qui tient ses mesures de branche
        puis un sous-groupe par variation en branche. Les mesures écrites à
        la main (KPI, cibles racines) ouvrent la liste."""
        racines: list = []
        groupes: dict = {}      # clé -> [libellé, couleur, nœuds, {variation: nœuds}]
        for n in self._noeuds:
            typ = n.get("type")
            if typ in ("base", "cible"):
                racines.append(n)
                continue
            br = n.get("branche")
            if br:
                g = groupes.setdefault("b|" + br, [br, BLUE, [], {}])
                if typ == "branche":
                    g[2].append(n)
                else:
                    g[3].setdefault(n.get("variation") or "?", []).append(n)
            else:
                groupes.setdefault("v|" + (n.get("variation") or "?"),
                                   [n.get("variation") or "?", None, [], {}])[2].append(n)

        def compte(g, total):
            g.setText(COL_ETAT, f"{total} mesure{'s' if total > 1 else ''}")
            g.setExpanded(g.data(0, Qt.UserRole) not in self._replies)

        def remplir(g, noeuds):
            for n in noeuds:
                g.addChild(self._ligne(n))
            compte(g, len(noeuds))

        if racines:
            remplir(self._groupe(None, "racines", "Mesures écrites à la main"), racines)
        for cle, (lib, couleur, noeuds, sous) in groupes.items():
            g = self._groupe(None, cle, lib, couleur)
            remplir(g, noeuds)
            for vid, ns in sous.items():
                remplir(self._groupe(g, cle + "|" + vid, lib + " › " + vid), ns)
            compte(g, len(noeuds) + sum(len(ns) for ns in sous.values()))

    def _resumer(self) -> None:
        ns = self._noeuds
        bases = sum(1 for n in ns if n.get("type") == "base")
        gen = [n for n in ns if n.get("type") in ("variation", "branche")]
        par = {}
        for n in gen:
            par[n.get("etat")] = par.get(n.get("etat"), 0) + 1
        dans = sum(1 for n in ns if n.get("tables"))
        morceaux = [f"{bases} ICP", f"{len(gen)} mesures générées"]
        detail = ", ".join(f"{par[k]} {k}{'s' if par[k] > 1 else ''}"
                           for k in ("nouvelle", "modifiée", "inchangée") if par.get(k))
        if detail:
            morceaux[-1] += f" ({detail})"
        morceaux.append(f"{dans} dans les paramètres de champ ({MARQUEUR})")
        self.lbl_resume.setText(" · ".join(morceaux)
                                + ". Aperçu du config en mémoire, rien n'est écrit.")

    # ---- sélection ---------------------------------------------------------------

    def _on_choix(self, courant, _precedent=None) -> None:
        if courant is None:
            self.fiche.vider()
            return
        if courant.data(0, ROLE_GROUPE):
            self.fiche.vider(f"{courant.text(COL_NOM)} : {courant.text(COL_ETAT)}. "
                             "Choisir une mesure pour voir son DAX et ses attributs.")
            return
        n = self._par_nom.get(courant.data(0, Qt.UserRole))
        if n is None:
            self.fiche.vider()
        else:
            self.fiche.montrer(n)

    # ---- filtre / pliage -------------------------------------------------------

    def _filtrer(self, *_) -> None:
        txt = self.ed_filtre.text().strip().lower()
        seul_param = self.chk_param.isChecked()

        def visite(it) -> bool:
            n_vis = 0
            for i in range(it.childCount()):
                n_vis += visite(it.child(i))
            if it.data(0, ROLE_GROUPE):
                # un groupe se montre s'il a quelque chose à montrer
                it.setHidden(n_vis == 0)
                return n_vis > 0
            nom = it.text(COL_NOM).lower()
            texte = (nom + " " + it.toolTip(COL_NOM).lower()) if txt else ""
            moi = ((not txt or txt in texte)
                   and (not seul_param or bool(it.text(COL_PARAM))))
            visible = moi or n_vis > 0
            it.setHidden(not visible)
            return visible

        for i in range(self.arbre.topLevelItemCount()):
            visite(self.arbre.topLevelItem(i))

    def _tout(self, ouvrir: bool) -> None:
        if ouvrir:
            self._replies.clear()
            self.arbre.expandAll()
            return
        self.arbre.collapseAll()
        self._replies = set()

        def noter(it):
            self._replies.add(it.data(0, Qt.UserRole))
            for i in range(it.childCount()):
                noter(it.child(i))
        for i in range(self.arbre.topLevelItemCount()):
            noter(self.arbre.topLevelItem(i))
