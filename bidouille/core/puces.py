# -*- coding: utf-8 -*-
"""Une rangée de pastilles de filtre : « Tout 17 · Excel 2 · CSV 1… ».

Deux usages :
  · EXCLUSIVE : un seul choix à la fois (le type de source à montrer) ;
  · CUMULATIVE : chaque pastille allume ou éteint une catégorie (ce que la
    Radiographie montre sous un visuel : mesures, filtres, segments…).

Le style vient du thème (QPushButton[puce="true"]).
"""

from __future__ import annotations

from qtpy.QtCore import Signal
from qtpy.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QWidget

from core.theme import TEXT_MUTED


class Puces(QWidget):
    """Émet `change` quand le choix change. `valeur()` donne la clé choisie
    (exclusive), `valeurs()` l'ensemble des clés allumées (cumulative)."""

    change = Signal()

    def __init__(self, titre: str = "", exclusive: bool = True, parent=None):
        super().__init__(parent)
        self.exclusive = exclusive
        self._boutons: dict = {}
        self._groupe = QButtonGroup(self)
        self._groupe.setExclusive(exclusive)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(6)
        if titre:
            lbl = QLabel(titre)
            lbl.setStyleSheet(f"color:{TEXT_MUTED};")
            self._lay.addWidget(lbl)
        self._lay.addStretch(1)

    def remplir(self, choix, actives=None) -> None:
        """`choix` : [(clé, libellé, infobulle)]. `actives` : la clé allumée
        (exclusive) ou les clés allumées (cumulative). Un choix exclusif
        disparu revient au premier."""
        avant = self.valeur() if self.exclusive else None
        for b in self._boutons.values():
            self._groupe.removeButton(b)
            b.deleteLater()
        self._boutons = {}
        for cle, libelle, aide in choix:
            b = QPushButton(libelle)
            b.setProperty("puce", True)
            b.setCheckable(True)
            if aide:
                b.setToolTip(aide)
            b.toggled.connect(self._bascule)
            self._groupe.addButton(b)
            self._lay.insertWidget(self._lay.count() - 1, b)
            self._boutons[cle] = b
        if self.exclusive:
            cle = actives if actives in self._boutons else avant
            if cle not in self._boutons and self._boutons:
                cle = next(iter(self._boutons))
            if cle in self._boutons:
                self._boutons[cle].blockSignals(True)
                self._boutons[cle].setChecked(True)
                self._boutons[cle].blockSignals(False)
        else:
            for cle, b in self._boutons.items():
                b.blockSignals(True)
                b.setChecked(actives is None or cle in actives)
                b.blockSignals(False)

    def _bascule(self, allume: bool) -> None:
        # en exclusif, un changement éteint l'un et allume l'autre : un seul signal
        if self.exclusive and not allume:
            return
        self.change.emit()

    def bouton(self, cle):
        return self._boutons.get(cle)

    def choisir(self, cle) -> None:
        if cle in self._boutons:
            self._boutons[cle].setChecked(True)

    def valeur(self):
        return next((c for c, b in self._boutons.items() if b.isChecked()), None)

    def valeurs(self) -> set:
        return {c for c, b in self._boutons.items() if b.isChecked()}
