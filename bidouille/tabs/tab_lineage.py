# -*- coding: utf-8 -*-
"""Vue « Par source » de la Radiographie : d'où vient chaque table du rapport
ouvert, et ce qui dépend d'elle dans le rapport.

Une seule liste, une ligne par table et par source : son type (Excel, CSV,
ODBC…), la source (le fichier, le serveur, le DSN), ce que la table y prend
(la feuille, le tableau, la table SQL), son mode et l'emplacement du fichier.
Les colonnes se trient : trier par Source range ensemble les tables qui lisent
le même fichier. Les pastilles du haut ne gardent qu'un type de source, les
tables calculées (DAX), ou les fichiers introuvables sur ce poste.

Une table calculée a pour source les tables du modèle que son DAX lit, et
chaque table dit dans « Reprise par » quelles tables calculées la lisent,
directement ou par une autre : une table qu'aucun visuel n'affiche peut
ainsi rester indispensable.

Dans la Radiographie (integre=True), la liste reçoit aussi ce qui dépend de
chaque table : colonnes calculées, mesures, filtres et segments, visuels
(radiographie.dependants). Un clic sur une ligne émet `choisi`, et la fiche de
la Radiographie détaille ces dépendances. Seule, sans Radiographie, la vue
garde son filtre et son bouton Relire, et n'a pas ces colonnes.

Un fichier LOCAL cité par une source qui n'existe plus est signalé ⚠ : c'est
ce qui casse une actualisation sur un autre poste. Lecture seule : l'onglet
lit les .tmdl du modèle (moteurs/lineage.py) et n'écrit rien dans le projet ;
« Exporter CSV… » écrit seulement là où on le lui dit.
"""

from __future__ import annotations

import ntpath
import subprocess
from pathlib import Path

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QBrush, QColor, QGuiApplication
from qtpy.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import lineage as lg
from core.journal import Journal
from core.puces import Puces
from core.theme import TEXT_DIM, TEXT_MUTED, YELLOW

# les comptes juste après la source : ce qu'on vient y chercher doit se voir
# sans faire défiler la liste
(COL_TABLE, COL_TYPE, COL_SOURCE, COL_MESURES, COL_FILTRES, COL_VISUELS, COL_CCALC,
 COL_OBJET, COL_REPRISE, COL_MODE, COL_LIEU) = range(11)
ENTETES = ["Table", "Type", "Source", "Mesures", "Filtres", "Visuels", "Calculées",
           "Élément lu", "Reprise par", "Mode", "Emplacement"]
# ce qui dépend de la table dans le rapport : des comptes, le détail dans la
# fiche de la Radiographie
COMPTES = (COL_CCALC, COL_MESURES, COL_FILTRES, COL_VISUELS)
AIDE_COMPTES = {
    COL_CCALC: "Les tables calculées qui la reprennent, et les colonnes calculées qui la "
               "lisent ou vivent dans une de ces tables",
    COL_MESURES: "Les mesures qui dépendent de la table : celles qui la lisent, et celles "
                 "qui reprennent ces mesures",
    COL_FILTRES: "Les filtres du volet (avec une valeur) et les segments posés sur ses "
                 "colonnes",
    COL_VISUELS: "Les visuels qui affichent une de ses colonnes ou une mesure qui en dépend",
}
TOUT, CALCULEES, MANQUANTS = "tout", "calculees", "manquants"
TYPE_CALCULEE = "Calculée (DAX)"
TYPE_AUCUN = "Sans connecteur"
TYPE_LIVE = "Connexion live"
# l'ordre des lignes par défaut : la connexion live, les sources, puis ce qui
# ne lit rien de l'extérieur
RANG = {lg.LIVE: 0, lg.SOURCE: 1, lg.AUCUN: 2, lg.CALCULEE: 3}


def _fichier_manquant(detail: str) -> bool:
    p = lg.chemin_local(detail)
    return p is not None and not p.exists()


def _est_chemin(detail: str) -> bool:
    return bool(detail) and "://" not in detail and ("\\" in detail or "/" in detail)


def source_et_lieu(l) -> tuple:
    """(source, emplacement) d'une ligne : un fichier se lit par son NOM, son
    dossier va dans l'emplacement ; un serveur, un DSN ou une URL se lisent
    tels quels."""
    d1, d2 = l["detail1"], l["detail2"]
    if _est_chemin(d1):
        dossier, nom = ntpath.split(d1.rstrip("\\/"))
        return " · ".join(x for x in (nom or d1, d2) if x), dossier
    return " · ".join(x for x in (d1, d2) if x), ""


def type_de(l) -> str:
    if l["genre"] == lg.CALCULEE:
        return TYPE_CALCULEE
    if l["genre"] == lg.AUCUN:
        return TYPE_AUCUN
    if l["genre"] == lg.LIVE:
        return TYPE_LIVE
    return l["famille"] or l["connecteur"]


class _Ligne(QTreeWidgetItem):
    """Une ligne qui se trie sur une clé, pas sur son texte affiché : le ⚠
    d'un fichier manquant ne doit pas le faire passer en tête, et à égalité
    les lignes gardent l'ordre type, source, table."""

    def __init__(self, textes, cles, base):
        super().__init__([str(t) for t in textes])
        self.cles = cles
        self.base = base
        # la ligne du moteur, en attribut : PyQt5 convertirait un dict rangé
        # dans setData en QVariantMap
        self.ligne: dict = {}

    def __lt__(self, autre):
        c = self.treeWidget().sortColumn() if self.treeWidget() else COL_TYPE
        if c == COL_TYPE:
            return self.base < autre.base
        a, b = self.cles[c], autre.cles[c]
        # les cases vides en dernier, quel que soit le sens
        return ((not a, a, self.base) < (not b, b, autre.base))


class LineageTab(QWidget):
    choisi = Signal(object)             # la ligne du moteur (dict) de la ligne choisie

    def __init__(self, journal=None, integre=False):
        super().__init__()
        self.journal = journal or Journal()
        self.integre = integre
        self._pbip = None
        self._pending = False           # analyse à faire à la prochaine visite
        self._res: dict = {}
        self._impacts: dict | None = None

        v = QVBoxLayout(self)
        if integre:
            v.setContentsMargins(0, 4, 0, 0)
        haut = QHBoxLayout()
        self.ed_filtre = QLineEdit(self)
        self.ed_filtre.setPlaceholderText("Filtrer (table, fichier, feuille, serveur, "
                                          "connecteur…)")
        self.ed_filtre.setClearButtonEnabled(True)
        self.ed_filtre.textChanged.connect(self._filtrer)
        self.btn_export = QPushButton("Exporter CSV…")
        self.btn_export.setToolTip("Une ligne par partition et par connecteur "
                                   "(séparateur ;), comme scan_lineage.py.")
        self.btn_export.clicked.connect(self._exporter)
        b_relire = QPushButton("↻ Relire")
        b_relire.setToolTip("Relit les fichiers du modèle.")
        b_relire.clicked.connect(self.reload)
        self.puces = Puces("Type :")
        self.puces.change.connect(self._filtrer)
        if integre:
            # dans la Radiographie, son filtre et son Relire servent aussi ici
            self.ed_filtre.hide()
            b_relire.hide()
            rang = QHBoxLayout()
            rang.addWidget(self.puces, 1)
            rang.addWidget(self.btn_export)
            v.addLayout(rang)
        else:
            haut.addWidget(self.ed_filtre, 1)
            haut.addWidget(self.btn_export)
            haut.addWidget(b_relire)
            v.addLayout(haut)
            v.addWidget(self.puces)

        self.lbl_resume = QLabel("")
        self.lbl_resume.setWordWrap(True)
        self.lbl_resume.setStyleSheet(f"color:{TEXT_DIM};")
        self.lbl_resume.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.lbl_resume)

        self.arbre = QTreeWidget()
        self.arbre.setColumnCount(len(ENTETES))
        self.arbre.setHeaderLabels(ENTETES)
        self.arbre.setRootIsDecorated(False)
        self.arbre.setUniformRowHeights(True)
        self.arbre.setAlternatingRowColors(True)
        self.arbre.setSortingEnabled(True)
        h = self.arbre.header()
        for c in (COL_TYPE, COL_OBJET, COL_MODE) + COMPTES:
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        for c in (COL_TABLE, COL_SOURCE, COL_REPRISE):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
        h.setSectionResizeMode(COL_LIEU, QHeaderView.Stretch)
        h.setStretchLastSection(False)
        self.arbre.setColumnWidth(COL_TABLE, 170 if integre else 240)
        self.arbre.setColumnWidth(COL_SOURCE, 170 if integre else 260)
        self.arbre.setColumnWidth(COL_REPRISE, 160 if integre else 200)
        for c, aide in AIDE_COMPTES.items():
            self.arbre.headerItem().setToolTip(c, aide)
            self.arbre.setColumnHidden(c, True)      # sans Radiographie, rien à compter
        self.arbre.headerItem().setToolTip(
            COL_REPRISE, "Les tables calculées (ou requêtes) qui lisent cette table, "
                         "directement ou par une autre : la supprimer les casserait.")
        self.arbre.sortByColumn(COL_TYPE, Qt.AscendingOrder)
        self.arbre.setContextMenuPolicy(Qt.CustomContextMenu)
        self.arbre.customContextMenuRequested.connect(self._menu)
        self.arbre.currentItemChanged.connect(
            lambda cur, _prev: self.choisi.emit(cur.ligne) if cur is not None else None)
        v.addWidget(self.arbre, 1)

        self.lbl_avis = QLabel("")
        self.lbl_avis.setWordWrap(True)
        self.lbl_avis.setStyleSheet(f"color:{YELLOW};")
        self.lbl_avis.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_avis.hide()
        v.addWidget(self.lbl_avis)

    # ---- projet (différé comme ChopChop : changer de projet reste instantané) --

    def set_project(self, project):
        self._pbip = str(project.pbip)
        if self.integre:                # la Radiographie lit et appelle afficher()
            return
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
        if self._pending and not self.integre:
            self._analyser()

    def afficher(self, res: dict, impacts: dict | None = None):
        """Montre un lineage déjà lu (lineage.scan_projet), avec, si on les a,
        ce qui dépend de chaque table (radiographie.dependants)."""
        self._pending = False
        self._res = res or {}
        self._impacts = impacts
        for c in COMPTES:
            self.arbre.setColumnHidden(c, impacts is None)
        self._construire()

    def filtrer_texte(self, texte: str):
        self.ed_filtre.setText(texte)

    def _analyser(self):
        self._pending = False
        try:
            self._res = lg.scan_projet(self._pbip)
        except (OSError, UnicodeDecodeError) as e:
            self._res = {"lignes": [], "erreur": f"lecture impossible : {e}"}
        self._construire()

    # ---- construction ----------------------------------------------------------

    def lignes(self) -> list:
        return list(self._res.get("lignes") or [])

    def lignes_affichees(self) -> list:
        """Les lignes de l'onglet : une par table et par source. Les partitions
        d'une même table qui lisent la même source (actualisation
        incrémentielle) n'en font qu'une, avec leur nombre."""
        vues: dict = {}
        for l in self.lignes():
            cle = (l["table"], l["partition"] if l["table"] == lg.EXPRESSIONS else "",
                   l["genre"], l["connecteur"], l["detail1"], l["detail2"], l.get("objet", ""))
            if cle in vues:
                vues[cle]["partitions"].append(l["partition"])
            else:
                vues[cle] = dict(l, partitions=[l["partition"]])
        return list(vues.values())

    def _construire(self):
        self.arbre.setUpdatesEnabled(False)
        self.arbre.setSortingEnabled(False)
        self.arbre.clear()
        lignes = self.lignes_affichees()

        # qui lit quoi : « lue par 3 tables » sur chaque source partagée
        lecteurs: dict = {}
        for l in lignes:
            if l["genre"] == lg.SOURCE:
                lecteurs.setdefault((l["connecteur"], l["detail1"], l["detail2"]),
                                    set()).add(self._nom_table(l))

        # le lineage DANS le modèle : ce que lit chaque table calculée, et qui
        # reprend chaque table
        self._reprises = lg.reprises(self.lignes())
        self._directes = lg.dependances(self.lignes())
        self._au_bout = lg.sources_au_bout(self.lignes())
        self._par_nom: dict = {}
        for l in lignes:
            self._par_nom.setdefault(lg.nom_noeud(l), []).append(l)

        manquants = 0                   # lignes, pour la pastille
        fichiers_manquants = set()      # fichiers, pour l'avis
        comptes: dict = {}
        for l in lignes:
            typ = type_de(l)
            source, lieu = source_et_lieu(l)
            if l["genre"] in (lg.CALCULEE, lg.AUCUN) and l.get("lit"):
                source = ", ".join(l["lit"])
            reprise = ", ".join(self._reprises.get(lg.nom_noeud(l), []))
            imp = (self._impacts or {}).get(lg.nom_noeud(l), {})
            n_cc = (len(imp.get("tables_calculees", []))
                    + len(imp.get("colonnes_calculees", [])))
            n_mes = len(imp.get("mesures", []))
            n_flt = len(imp.get("filtres", [])) + len(imp.get("segments", []))
            n_vis = len(imp.get("visuels", []))
            manque = _fichier_manquant(l["detail1"])
            manquants += manque
            if manque:
                fichiers_manquants.add(l["detail1"].lower())
            table = self._nom_table(l)
            if len(l["partitions"]) > 1:
                table += f"  ({len(l['partitions'])} partitions)"
            nombres = [n_mes, n_flt, n_vis, n_cc]
            textes = ([table, typ, ("⚠ " if manque else "") + source]
                      + [str(n) if n else "·" for n in nombres]
                      + [l.get("objet", ""), reprise, l["mode"], lieu])
            # les comptes se trient du plus grand au plus petit au premier clic
            cles = ([t.lower() for t in (table, typ, source)] + [-n for n in nombres]
                    + [t.lower() for t in (l.get("objet", ""), reprise, l["mode"], lieu)])
            # parmi les tables calculées, celles qui lisent une autre table d'abord
            it = _Ligne(textes, cles, (RANG.get(l["genre"], 9), typ.lower(), not source,
                                       source.lower(), table.lower()))
            it.ligne = l
            it.setData(COL_TYPE, Qt.UserRole, self._cle_type(l))
            it.setData(COL_SOURCE, Qt.UserRole, manque)
            self._infobulles(it, l, textes, lecteurs, manque)
            self._infobulles_comptes(it, imp)
            for c in COMPTES:
                it.setTextAlignment(c, int(Qt.AlignRight | Qt.AlignVCenter))
                if textes[c] == "·":
                    it.setForeground(c, QBrush(QColor(TEXT_MUTED)))
            if l["genre"] in (lg.CALCULEE, lg.AUCUN):
                # grisée si elle ne touche à aucune autre table ; sinon seuls son
                # type et son mode le sont
                isolee = not source and not reprise
                for c in range(len(ENTETES)):
                    if isolee or c in (COL_TYPE, COL_MODE):
                        it.setForeground(c, QBrush(QColor(TEXT_MUTED)))
            if manque:
                it.setForeground(COL_SOURCE, QBrush(QColor(YELLOW)))
                it.setForeground(COL_LIEU, QBrush(QColor(YELLOW)))
            self.arbre.addTopLevelItem(it)
            t, n = comptes.get(self._cle_type(l), (typ, 0))
            comptes[self._cle_type(l)] = (t, n + 1)

        self._remplir_puces(comptes, len(lignes), manquants)
        self.arbre.setSortingEnabled(True)
        self.arbre.setUpdatesEnabled(True)
        self._resumer(len(fichiers_manquants))
        self._filtrer()

    @staticmethod
    def _nom_table(l) -> str:
        if l["table"] == lg.EXPRESSIONS:
            return f'{l["partition"]}  (requête partagée)'
        return l["table"] or "(rapport)"

    @staticmethod
    def _cle_type(l) -> str:
        if l["genre"] in (lg.CALCULEE, lg.AUCUN):
            return CALCULEES
        return "type:" + type_de(l)

    def _infobulles(self, it, l, textes, lecteurs, manque):
        for c, t in enumerate(textes):
            if t:
                it.setToolTip(c, str(t))
        parts = [p for p in l["partitions"] if p and p != l["table"]]
        if l["table"] == lg.EXPRESSIONS:
            it.setToolTip(COL_TABLE, f'Requête partagée « {l["partition"]} » '
                                     "(expressions.tmdl) : d'autres tables la reprennent.")
        elif parts:
            it.setToolTip(COL_TABLE, l["table"] + "\n\nPartitions :\n" + "\n".join(parts))
        if l["genre"] == lg.CALCULEE:
            it.setToolTip(COL_TYPE, "Calculée par le modèle en DAX (paramètre de champ, "
                                    "calendrier, table de mesures…) : elle ne lit rien de "
                                    "l'extérieur, seulement d'autres tables du modèle.")
        elif l["connecteur"]:
            it.setToolTip(COL_TYPE, f"Connecteur M : {l['connecteur']}")
        detail = " · ".join(d for d in (l["detail1"], l["detail2"]) if d)
        if detail:
            tip = detail
            autres = lecteurs.get((l["connecteur"], l["detail1"], l["detail2"]), set())
            if len(autres) > 1:
                tip += (f"\n\nLue par {len(autres)} tables :\n"
                        + "\n".join(sorted(autres, key=str.lower)))
            if manque:
                tip += "\n\n⚠ Fichier introuvable sur ce poste : l'actualisation échouera ici."
            it.setToolTip(COL_SOURCE, tip)
            if textes[COL_LIEU]:
                it.setToolTip(COL_LIEU, tip)
        if l.get("lit") and l["genre"] in (lg.CALCULEE, lg.AUCUN):
            it.setToolTip(COL_SOURCE, self._infobulle_lit(l))
        nom = lg.nom_noeud(l)
        if self._reprises.get(nom):
            it.setToolTip(COL_REPRISE, "\n".join(
                [f"« {nom} » est lue par :"]
                + [f"  {t}" + ("" if nom in self._directes.get(t, []) else
                               "  (par une autre table)") for t in self._reprises[nom]]
                + ["", "La supprimer casserait ces tables."]))
        if l.get("objet") == lg.REQUETE_SQL:
            it.setToolTip(COL_OBJET, "La requête SQL est écrite dans Power Query : le "
                                     "détail est dans l'éditeur de requêtes de Power BI.")

    @staticmethod
    def _infobulles_comptes(it, imp):
        if not imp:
            return
        dir_ = len(imp["mesures_directes"])
        n = len(imp["mesures"])
        if n:
            it.setToolTip(COL_MESURES, f"{n} mesure(s) en dépendent : {dir_} lisent la table, "
                                       f"{n - dir_} reprennent ces mesures.\nLe détail est "
                                       "dans la fiche.")
        nf, ns = len(imp["filtres"]), len(imp["segments"])
        if nf or ns:
            it.setToolTip(COL_FILTRES, f"{nf} filtre(s) du volet avec une valeur, "
                                       f"{ns} segment(s), sur ses colonnes.")
        if imp["visuels"]:
            it.setToolTip(COL_VISUELS, f"{len(imp['visuels'])} visuel(s) sur "
                                       f"{imp['pages']} page(s) :\n"
                          + "\n".join(f"{v['page']} › {v['libelle']}" for v in imp["visuels"][:25]))
        calc = ([f"table {t}" for t in imp["tables_calculees"]]
                + [f"colonne '{t}'[{c}]" for t, c in imp["colonnes_calculees"]])
        if calc:
            it.setToolTip(COL_CCALC, "\n".join(calc))

    def _infobulle_lit(self, l) -> str:
        """Ce que lit une table calculée, chaque table avec sa propre source,
        puis les sources externes au bout de la chaîne."""
        lignes = [f"« {lg.nom_noeud(l)} » est calculée à partir de :"]
        for t in l["lit"]:
            siennes = self._par_nom.get(t, [])
            src = [x for x in siennes if x["genre"] == lg.SOURCE]
            if src:
                s, _lieu = source_et_lieu(src[0])
                lignes.append(f"  {t} : {type_de(src[0])}, {s}")
            elif siennes:
                lignes.append(f"  {t} : {type_de(siennes[0]).lower()}")
            else:
                lignes.append(f"  {t}")
        bout = self._au_bout.get(lg.nom_noeud(l), [])
        if [t for t in bout if t not in l["lit"]]:
            lignes += ["", "Au bout de la chaîne, elle dépend de :"] + [f"  {t}" for t in bout]
        return "\n".join(lignes)

    def _remplir_puces(self, comptes: dict, total: int, manquants: int):
        choix = [(TOUT, f"Tout  {total}", "Toutes les tables")]
        types = sorted(((k, t, n) for k, (t, n) in comptes.items() if k != CALCULEES),
                       key=lambda x: (-x[2], x[1].lower()))
        choix += [(k, f"{t}  {n}", f"Les tables qui lisent une source {t}") for k, t, n in types]
        if CALCULEES in comptes:
            choix.append((CALCULEES, f"Calculées (DAX)  {comptes[CALCULEES][1]}",
                          "Les tables calculées par le modèle : elles ne lisent rien de "
                          "l'extérieur."))
        if manquants:
            choix.append((MANQUANTS, f"⚠ Introuvables  {manquants}",
                          "Les sources dont le fichier local n'existe pas sur ce poste."))
        self.puces.remplir(choix)

    def _resumer(self, manquants: int):
        res = self._res
        lignes = self.lignes()
        if res.get("erreur"):
            self.lbl_resume.setText("")
            self.lbl_avis.setText(res["erreur"])
            self.lbl_avis.show()
            return
        if res.get("live"):
            self.lbl_resume.setText(f"Connexion LIVE au modèle « {res.get('modele')} », "
                                    "ses sources sont dans le modèle publié, pas dans ce projet.")
        else:
            n_src = len(lg.sources(lignes))
            tables = {l["table"] for l in lignes if l["table"] and l["table"] != lg.EXPRESSIONS}
            calc = {l["table"] for l in lignes if l["genre"] in (lg.CALCULEE, lg.AUCUN)}
            liees = {l["table"] for l in lignes if l["genre"] in (lg.CALCULEE, lg.AUCUN)
                     and l.get("lit")}
            morceaux = [f"Modèle local : {res.get('modele')}",
                        f"{n_src} source{'s' if n_src > 1 else ''}",
                        f"{len(tables)} tables dont {len(calc)} calculées"
                        + (f" ({len(liees)} lisent d'autres tables)" if liees else "")]
            params = res.get("parametres") or {}
            if params:
                morceaux.append(f"{len(params)} paramètre{'s' if len(params) > 1 else ''} M")
            self.lbl_resume.setText(" · ".join(morceaux) + ", lecture seule.")
        avis = []
        if manquants:
            avis.append(f"⚠ {manquants} fichiers locaux introuvables sur ce poste"
                        if manquants > 1 else "⚠ 1 fichier local introuvable sur ce poste")
            avis[-1] += (" : l'actualisation échouera ici (pastille ⚠ Introuvables pour les "
                         "voir, survol de la source pour le chemin).")
        self.lbl_avis.setText("\n".join(avis))
        self.lbl_avis.setVisible(bool(avis))

    # ---- filtre ----------------------------------------------------------------

    def _filtrer(self, *_):
        txt = self.ed_filtre.text().strip().lower()
        choix = self.puces.valeur() or TOUT
        for i in range(self.arbre.topLevelItemCount()):
            it = self.arbre.topLevelItem(i)
            l = getattr(it, "ligne", {})
            if choix == MANQUANTS:
                garde = bool(it.data(COL_SOURCE, Qt.UserRole))
            else:
                garde = choix in (TOUT, "") or it.data(COL_TYPE, Qt.UserRole) == choix
            if garde and txt:
                texte = " ".join([it.text(c) for c in range(self.arbre.columnCount())]
                                 + [l.get("connecteur", ""), l.get("detail1", ""),
                                    l.get("detail2", "")] + list(l.get("partitions", [])))
                garde = txt in texte.lower()
            it.setHidden(not garde)

    # ---- actions ---------------------------------------------------------------

    def _menu(self, pos):
        it = self.arbre.itemAt(pos)
        if it is None:
            return
        l = getattr(it, "ligne", {})
        detail = " · ".join(d for d in (l.get("detail1"), l.get("detail2")) if d)
        table = l.get("table") if l.get("table") != lg.EXPRESSIONS else l.get("partition")
        menu = QMenu(self)
        a_detail = menu.addAction("Copier « " + detail[:60] + " »") if detail else None
        a_table = menu.addAction("Copier le nom « " + str(table)[:60] + " »") if table else None
        a_dossier = None
        p = lg.chemin_local(l.get("detail1", ""))
        if p is not None and p.exists():
            a_dossier = menu.addAction("Afficher dans l'Explorateur")
        if menu.isEmpty():
            return
        choix = menu.exec_(self.arbre.viewport().mapToGlobal(pos)) if hasattr(menu, "exec_") \
            else menu.exec(self.arbre.viewport().mapToGlobal(pos))
        if choix is None:
            return
        if choix is a_detail:
            QGuiApplication.clipboard().setText(detail)
        elif choix is a_table:
            QGuiApplication.clipboard().setText(str(table))
        elif choix is a_dossier:
            subprocess.Popen(["explorer", "/select,", str(p)])

    def _exporter(self):
        if not self._pbip:
            return
        defaut = str(Path(self._pbip).with_name(Path(self._pbip).stem + "_lineage.csv"))
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter le lineage", defaut,
                                                "CSV (*.csv)")
        if not chemin:
            return
        try:
            lg.ecrire_csv(self.lignes(), chemin)
        except OSError as e:
            self.journal.erreur(f"Sources de données : export impossible, {e}")
            return
        self.journal.info(f"Sources de données : {len(self.lignes())} lignes exportées "
                          f"vers {chemin}")
