# -*- coding: utf-8 -*-
"""Éditeur des tables paramètre de champ (onglet Mesures → Paramètres de champ).

Une LISTE de tables, chacune avec ses réglages : ce qu'affichent ses rangées,
ce qu'affiche sa rangée de base, si le KPI paraît sous son libellé, si elle
garde la base et les cibles, et quels KPI / variations / branches elle écarte.
La forme du config est celle de generate_measures.fp_table_specs ; ce widget
ne fait que l'éditer.

Les filtres se présentent en cases COCHÉES = gardé, mais s'écrivent en
exclusions : ce qui sera ajouté plus tard au modèle (un KPI, une variation)
entre de lui-même dans chaque table. Une exclusion dont l'objet n'est pas
dans le vocabulaire du moment (KPI renommé, modèle pas encore lu) est
conservée telle quelle, jamais perdue en silence.
"""

from __future__ import annotations

import copy

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.theme import TEXT_DIM

import generate_measures as gm

HORS_BRANCHE = "(hors branche)"      # libellé à l'écran de la clé ""


def _base_neuve(nom: str) -> dict:
    return dict(copy.deepcopy(gm.FP_TABLE_DEFAUT), name=nom)


class EditeurTablesParametre(QWidget):
    """Liste des tables à gauche, réglages de la table choisie à droite."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # CheckCombo vit dans tab_config, qui importe ce module : import tardif
        from tabs.tab_config import CheckCombo

        self._specs: list = []
        self._vocab = {"kpis": [], "variations": [], "branches": []}
        self._base_label = "Réel"
        self._loading = False
        self._courant = -1

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)

        # -- gauche : la liste ------------------------------------------------
        gauche = QVBoxLayout()
        self.liste = QListWidget()
        self.liste.setMaximumWidth(260)
        self.liste.setMinimumHeight(150)
        self.liste.currentRowChanged.connect(self._choisir)
        gauche.addWidget(self.liste, 1)
        boutons = QHBoxLayout()
        self.b_ajouter = QPushButton("Ajouter")
        self.b_ajouter.setToolTip("Une nouvelle table, aux réglages par défaut.")
        self.b_ajouter.clicked.connect(self._ajouter)
        self.b_dupliquer = QPushButton("Dupliquer")
        self.b_dupliquer.setToolTip(
            "Une copie de la table choisie, sous un autre nom, pour deux\n"
            "sélections indépendantes sur une même page.")
        self.b_dupliquer.clicked.connect(self._dupliquer)
        self.b_retirer = QPushButton("Retirer")
        self.b_retirer.setToolTip(
            "Le générateur n'y touche plus. La table RESTE dans le modèle :\n"
            "la supprimer dans Power BI Desktop si plus aucun visuel ne s'en sert.")
        self.b_retirer.clicked.connect(self._retirer)
        for b in (self.b_ajouter, self.b_dupliquer, self.b_retirer):
            boutons.addWidget(b)
        gauche.addLayout(boutons)
        h.addLayout(gauche)

        # -- droite : la table choisie ------------------------------------------
        self.detail = QWidget()
        g = QGridLayout(self.detail)
        g.setContentsMargins(8, 0, 0, 0)
        r = 0

        self.ed_nom = QLineEdit()
        self.ed_nom.setToolTip(
            "Nom de la table dans le modèle.\n"
            "Renommer = le générateur crée une NOUVELLE table ; l'ancienne\n"
            "reste dans le modèle, avec les visuels qui s'en servent.")
        self.ed_nom.editingFinished.connect(self._renommer)
        g.addWidget(QLabel("Nom :"), r, 0)
        g.addWidget(self.ed_nom, r, 1)
        r += 1

        self.cmb_rows = QComboBox()
        self.cmb_rows.addItem("le calcul (Réel, 7d avg, PY…)", "calcul")
        self.cmb_rows.addItem("l'ICP", "kpi")
        self.cmb_rows.setToolTip(
            "« le calcul » : on y choisit un CALCUL. Usage : UN ICP × plusieurs\n"
            "calculs : l'ICP vient d'un segment sur TD_KPI, relié à la colonne\n"
            "Indicateur.\n\n"
            "« l'ICP » : on y choisit un ICP. Usage : UN calcul × plusieurs ICP :\n"
            "le calcul vient d'un segment sur la colonne Calcul.")
        self.cmb_rows.currentIndexChanged.connect(self._edite)
        g.addWidget(QLabel("Chaque rangée affiche :"), r, 0)
        g.addWidget(self.cmb_rows, r, 1)
        r += 1

        self.cmb_base = QComboBox()
        self.cmb_base.addItem("", "calcul")          # libellé fixé par set_base_label
        self.cmb_base.addItem("l'ICP", "kpi")
        self.cmb_base.setToolTip(
            "La rangée de la mesure de BASE (l'ICP tel quel) peut afficher\n"
            "l'ICP au lieu du libellé de base : un segment UNIQUE où l'on choisit\n"
            "à la fois l'ICP et ses calculs (« Poids », 7d avg, PY…).\n"
            "Les variations, elles, affichent toujours leur calcul.")
        self.cmb_base.currentIndexChanged.connect(self._edite)
        self.lbl_base = QLabel("La rangée de base affiche :")
        g.addWidget(self.lbl_base, r, 0)
        g.addWidget(self.cmb_base, r, 1)
        r += 1

        self.chk_libelle = QCheckBox(
            "Afficher l'ICP sous son libellé (« Poids ») plutôt que sa mesure (« Weight »)")
        self.chk_libelle.setToolTip(
            "Le libellé vient de la table de correspondance (réglages communs,\n"
            "plus bas). Si elle manque au modèle, on retombe sur le nom de la\n"
            "mesure, et le journal le dit.")
        self.chk_libelle.stateChanged.connect(self._edite)
        g.addWidget(self.chk_libelle, r, 0, 1, 2)
        r += 1

        garde = QHBoxLayout()
        self.chk_base = QCheckBox("la rangée de base")
        self.chk_base.setToolTip(
            "Décoché : seules les variations de l'ICP y figurent (la mesure de\n"
            "base d'une BRANCHE, « YTD », reste : c'est un calcul de la branche).")
        self.chk_base.stateChanged.connect(self._edite)
        self.chk_cibles = QCheckBox("les cibles")
        self.chk_cibles.setToolTip(
            "Les rangées des mesures cibles (Calcul « Cible », « Cible 7d avg »…).")
        self.chk_cibles.stateChanged.connect(self._edite)
        garde.addWidget(self.chk_base)
        garde.addWidget(self.chk_cibles)
        garde.addStretch()
        g.addWidget(QLabel("Garder :"), r, 0)
        g.addLayout(garde, r, 1)
        r += 1

        self.cmb_kpis = CheckCombo()
        self.cmb_vars = CheckCombo()
        self.cmb_branches = CheckCombo()
        for cmb, lib, tip in (
                (self.cmb_kpis, "ICP :", "Les ICP de la table. Un ICP ajouté plus tard au modèle y entre\n"
                                         "de lui-même, sauf à le décocher ici."),
                (self.cmb_vars, "Variations :", "Les variations de la table (celles marquées « au paramètre »).\n"
                                                "En décocher une l'écarte aussi de ses branches."),
                (self.cmb_branches, "Branches :", "« (hors branche) » : le Réel et ses variations. Le décocher pour\n"
                                                  "une table qui ne montre que YTD, par exemple.")):
            cmb.setToolTip(tip)
            cmb.changed.connect(self._edite)
            g.addWidget(QLabel(lib), r, 0)
            g.addWidget(cmb, r, 1)
            r += 1

        self.lbl_usage = QLabel("")
        self.lbl_usage.setWordWrap(True)
        self.lbl_usage.setStyleSheet(f"color:{TEXT_DIM};")
        g.addWidget(self.lbl_usage, r, 0, 1, 2)
        r += 1
        g.setColumnStretch(1, 1)
        g.setRowStretch(r, 1)
        h.addWidget(self.detail, 1)

        self.lbl_vide = QLabel("Aucune table paramètre : cliquer sur « Ajouter ».")
        self.lbl_vide.setStyleSheet(f"color:{TEXT_DIM};")
        h.addWidget(self.lbl_vide, 1)
        self.set_base_label("")
        self._rafraichir_liste()

    # ---- API ---------------------------------------------------------------

    def set_vocab(self, kpis=None, variations=None, branches=None) -> None:
        """Ce que les filtres proposent : KPI du modèle, variations au
        paramètre, branches du config."""
        self._vocab = {"kpis": list(kpis or []), "variations": list(variations or []),
                       "branches": list(branches or [])}
        self._afficher(self._courant)

    def set_base_label(self, texte: str) -> None:
        self._base_label = texte or "Base"
        self.cmb_base.setItemText(0, "« " + self._base_label + " »")
        self._maj_usage()

    def load(self, specs) -> None:
        self._specs = [copy.deepcopy(s) for s in specs]
        self._courant = -1
        self._rafraichir_liste(0 if self._specs else -1)

    def specs(self) -> list:
        """Les tables telles qu'éditées (forme normalisée de fp_table_specs)."""
        return gm.fp_table_specs({"tables": copy.deepcopy(self._specs)})

    # ---- liste ---------------------------------------------------------------

    def _rafraichir_liste(self, select=None) -> None:
        self._loading = True
        self.liste.clear()
        for s in self._specs:
            self.liste.addItem(s["name"])
        self._loading = False
        vide = not self._specs
        self.detail.setVisible(not vide)
        self.lbl_vide.setVisible(vide)
        self.b_dupliquer.setEnabled(not vide)
        self.b_retirer.setEnabled(not vide)
        if select is None:
            select = min(self._courant, len(self._specs) - 1)
        self._courant = -1
        if select >= 0:
            self.liste.setCurrentRow(select)      # -> _choisir
            if self._courant != select:           # ligne déjà courante
                self._afficher(select)
        else:
            self._afficher(-1)

    def _choisir(self, i) -> None:
        if self._loading:
            return
        self._afficher(i)

    def _nom_libre(self, souhait: str) -> str:
        pris = {s["name"].lower() for s in self._specs}
        if souhait.lower() not in pris:
            return souhait
        k = 2
        while f"{souhait}_{k}".lower() in pris:
            k += 1
        return f"{souhait}_{k}"

    def _demander_nom(self, titre, propose) -> str:
        nom, ok = QInputDialog.getText(self, titre, "Nom de la table :", text=propose)
        nom = (nom or "").strip()
        if not ok or not nom:
            return ""
        if nom.lower() in {s["name"].lower() for s in self._specs}:
            QMessageBox.warning(self, titre, f"« {nom} » existe déjà dans la liste.")
            return ""
        return nom

    def _ajouter(self) -> None:
        nom = self._demander_nom("Nouvelle table paramètre",
                                 self._nom_libre("P_Indicateurs"))
        if not nom:
            return
        self._specs.append(_base_neuve(nom))
        self._rafraichir_liste(len(self._specs) - 1)
        self.changed.emit()

    def _dupliquer(self) -> None:
        if self._courant < 0:
            return
        src = self._specs[self._courant]
        nom = self._demander_nom("Dupliquer « " + src["name"] + " »",
                                 self._nom_libre(src["name"]))
        if not nom:
            return
        self._specs.insert(self._courant + 1, dict(copy.deepcopy(src), name=nom))
        self._rafraichir_liste(self._courant + 1)
        self.changed.emit()

    def _retirer(self) -> None:
        if self._courant < 0:
            return
        nom = self._specs[self._courant]["name"]
        rep = QMessageBox.question(
            self, "Retirer une table",
            f"Retirer « {nom} » de la liste ?\n\n"
            "Le générateur n'y touchera plus, mais la table RESTE dans le\n"
            "modèle : la supprimer dans Power BI Desktop si plus aucun visuel\n"
            "ne s'en sert.")
        if rep != QMessageBox.Yes:
            return
        i = self._courant
        del self._specs[i]
        self._courant = -1
        self._rafraichir_liste(min(i, len(self._specs) - 1))
        self.changed.emit()

    def _renommer(self) -> None:
        if self._loading or self._courant < 0:
            return
        s = self._specs[self._courant]
        nom = self.ed_nom.text().strip()
        if not nom or nom == s["name"]:
            self.ed_nom.setText(s["name"])
            return
        if nom.lower() in {t["name"].lower() for j, t in enumerate(self._specs)
                           if j != self._courant}:
            QMessageBox.warning(self, "Renommer", f"« {nom} » existe déjà dans la liste.")
            self.ed_nom.setText(s["name"])
            return
        s["name"] = nom
        self.liste.item(self._courant).setText(nom)
        self.changed.emit()

    # ---- détail --------------------------------------------------------------

    @staticmethod
    def _items_et_coches(vocab, exclus, affiche=lambda x: x):
        items = [affiche(x) for x in vocab]
        coches = [affiche(x) for x in vocab if x not in exclus]
        return items, coches

    def _afficher(self, i) -> None:
        self._courant = i
        if i < 0 or i >= len(self._specs):
            return
        s = gm.fp_table_specs({"tables": [self._specs[i]]})[0]
        self._loading = True
        self.ed_nom.setText(s["name"])
        self.cmb_rows.setCurrentIndex(1 if s["rows"] == "kpi" else 0)
        self.cmb_base.setCurrentIndex(1 if s["baseRow"] == "kpi" else 0)
        self.chk_libelle.setChecked(s["kpiLabel"])
        self.chk_base.setChecked(s["includeBase"])
        self.chk_cibles.setChecked(s["includeTargets"])
        v = self._vocab
        self.cmb_kpis.set_items(*self._items_et_coches(v["kpis"], s["excludeKpis"]))
        self.cmb_vars.set_items(*self._items_et_coches(v["variations"], s["excludeVariations"]))
        self.cmb_branches.set_items(*self._items_et_coches(
            [""] + v["branches"], s["excludeBranches"],
            lambda b: b or HORS_BRANCHE))
        self._loading = False
        self._maj_etats()

    @staticmethod
    def _exclusions(cmb, vocab, avant, depuis_ecran=lambda x: x) -> list:
        """Décochés du vocabulaire + anciennes exclusions hors vocabulaire."""
        coches = {depuis_ecran(x) for x in cmb.checked()}
        exclus = [x for x in vocab if x not in coches]
        exclus += [x for x in avant if x not in vocab and x not in exclus]
        return exclus

    def _edite(self, *_) -> None:
        if self._loading or self._courant < 0:
            return
        s = self._specs[self._courant]
        avant = gm.fp_table_specs({"tables": [s]})[0]
        v = self._vocab
        s["rows"] = self.cmb_rows.currentData()
        s["baseRow"] = self.cmb_base.currentData()
        s["kpiLabel"] = self.chk_libelle.isChecked()
        s["includeBase"] = self.chk_base.isChecked()
        s["includeTargets"] = self.chk_cibles.isChecked()
        s["excludeKpis"] = self._exclusions(self.cmb_kpis, v["kpis"], avant["excludeKpis"])
        s["excludeVariations"] = self._exclusions(
            self.cmb_vars, v["variations"], avant["excludeVariations"])
        s["excludeBranches"] = self._exclusions(
            self.cmb_branches, [""] + v["branches"], avant["excludeBranches"],
            lambda b: "" if b == HORS_BRANCHE else b)
        self._maj_etats()
        self.changed.emit()

    def _maj_etats(self) -> None:
        par_kpi = self.cmb_rows.currentData() == "kpi"
        # en « par KPI », toutes les rangées montrent déjà le KPI
        self.cmb_base.setEnabled(not par_kpi)
        self.lbl_base.setEnabled(not par_kpi)
        self.chk_libelle.setEnabled(par_kpi or self.cmb_base.currentData() == "kpi")
        self._maj_usage()

    def _maj_usage(self) -> None:
        if self._courant < 0:
            self.lbl_usage.setText("")
            return
        if self.cmb_rows.currentData() == "kpi":
            t = ("On y choisit un ICP : UN calcul × plusieurs ICP, le calcul venant "
                 "d'un segment sur la colonne Calcul.")
        elif self.cmb_base.currentData() == "kpi":
            t = ("On y choisit l'ICP ET ses calculs dans un même segment : la base "
                 "affiche l'ICP, les variations leur calcul.")
        else:
            t = (f"On y choisit un calcul ({self._base_label}, 7d avg, PY…) : UN ICP × "
                 "plusieurs calculs, l'ICP venant d'un segment relié à Indicateur.")
        self.lbl_usage.setText(t)
