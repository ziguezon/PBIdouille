# -*- coding: utf-8 -*-
"""Panneau « Génération des mesures » : génère les mesures/variations/branches,
et les tables paramètre de champ DIRECTEMENT dans les fichiers
TMDL, sans passer par Power BI (generate_measures.py). Desktop peut rester
ouvert ; après une écriture réelle, le fermer SANS enregistrer et rouvrir le
.pbip. Backup automatique.

Il n'a plus d'onglet à lui : il se pose EN TÊTE DU JOURNAL (colonne de droite)
quand l'onglet Mesures est affiché — le bouton est au-dessus du fil, et le run
qu'il lance apparaît juste en dessous, puisque le plus récent est en haut. Il
est donc étroit : le récapitulatif tient en une ligne, le détail est en
infobulle."""

from __future__ import annotations

import json

from qtpy.QtCore import Signal
from qtpy.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import model_reader
from core.journal import Journal
from core.runner import ToolRunner
from core.theme import TEXT_DIM, YELLOW

import generate_measures


class ModelTab(QWidget):
    # emis apres une generation qui a REELLEMENT ecrit : les onglets qui
    # lisent le modele doivent relire la liste des KPI
    modele_genere = Signal()

    def __init__(self, journal=None):
        super().__init__()
        # le journal de l'app (colonne de droite) ; construit seul, ce
        # panneau s'en fabrique un pour rester utilisable en test
        self.journal = journal or Journal()
        self.project = None
        self._runner = None
        self._failed = False
        self._non_sauve = False
        # posé par l'onglet Mesures : écrit le config, rend True si c'est fait.
        # Sert à « Enregistrer puis générer » (cf. _run).
        self.sauver = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        box = QGroupBox("Génération des mesures")
        v = QVBoxLayout(box)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(f"color:{YELLOW};")
        self.lbl_hint.hide()
        v.addWidget(self.lbl_hint)

        # affiché tant que le config a des modifs non sauvées : le générateur
        # lit le FICHIER, pas l'éditeur
        self.lbl_unsaved = QLabel("⚠ Config modifié, pas encore enregistré, "
                                  "le générateur lit le fichier.")
        self.lbl_unsaved.setWordWrap(True)
        self.lbl_unsaved.setStyleSheet(f"color:{YELLOW};")
        self.lbl_unsaved.hide()
        v.addWidget(self.lbl_unsaved)

        # une ligne ; le récapitulatif complet est dans l'infobulle
        self.lbl_recap = QLabel("")
        self.lbl_recap.setWordWrap(True)
        self.lbl_recap.setStyleSheet(f"color:{TEXT_DIM};")
        v.addWidget(self.lbl_recap)

        opts = QHBoxLayout()
        self.chk_dry = QCheckBox("Aperçu (dry-run)")
        self.chk_dry.setChecked(True)
        self.chk_dry.setToolTip("Calcule et liste tout sans RIEN écrire.")
        opts.addWidget(self.chk_dry)
        self.chk_orphans = QCheckBox("Supprimer les orphelines")
        self.chk_orphans.setToolTip(
            "removeOrphans : mesures générées qui ne correspondent plus au\n"
            "config (variation retirée...) : supprimées du modèle.")
        opts.addWidget(self.chk_orphans)
        opts.addStretch()
        v.addLayout(opts)

        self.btn_generate = QPushButton("Générer les mesures")
        self.btn_generate.clicked.connect(self._run)
        v.addWidget(self.btn_generate)
        root.addWidget(box)

    # ---- projet ----------------------------------------------------------------

    def set_project(self, project):
        self.project = project
        cfg_path = project.config_json
        if not cfg_path.exists():
            self.lbl_hint.setText(
                "Aucun measures_config.json chargé, attendu : " + str(cfg_path)
                + "\nCliquer sur « Config… » dans la barre du haut pour choisir celui de CE rapport.")
            self.lbl_hint.show()
            self.btn_generate.setEnabled(False)
            self.lbl_recap.setText("")
            self.lbl_recap.setToolTip("")
            return
        self.lbl_hint.hide()
        self.btn_generate.setEnabled(project.valid)

        cfg = model_reader.read_config(project)
        settings = cfg.get("settings") or {}
        variations = cfg.get("variations") or {}
        branches = list((cfg.get("branches") or {}).keys())
        fp = cfg.get("fieldParameter") or {}
        tables = generate_measures.fp_table_names(fp)
        self.chk_orphans.setChecked(bool(settings.get("removeOrphans", False)))
        self.lbl_recap.setText(
            f"{len(variations)} variation(s) · branches : "
            f"{', '.join(branches) or 'aucune'}  ⓘ")
        self.lbl_recap.setToolTip(
            f"Config : {cfg_path.name}\n"
            f"bases = mesures de '{settings.get('sourceTable', '_mesures')}' "
            f"(dossier '{settings.get('sourceFolder', '')}')\n"
            f"{len(variations)} variation(s) · branches : {', '.join(branches) or 'aucune'}\n"
            f"tables paramètre : {', '.join(tables) or 'aucune'}\n\n"
            f"Écriture réelle : backup automatique sous\n"
            f"_backupsPBIdouille\\_tmdl_backups\\, puis rouvrir le .pbip.")

    # ---- exécution ---------------------------------------------------------------

    def _run(self):
        if self._runner is not None or not self.project or self.project.model_dir is None:
            return
        if self._non_sauve and not self._resoudre_non_sauve():
            return
        dry = self.chk_dry.isChecked()
        if not dry:
            if QMessageBox.question(
                self, "Écriture réelle",
                "Les fichiers TMDL du modèle vont être MODIFIÉS.\n\n"
                "Un backup sera créé sous _backupsPBIdouille\\_tmdl_backups\\. Continuer ?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
            ) != QMessageBox.Yes:
                return

        try:
            config = json.loads(self.project.config_json.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            self.journal.info("⚠ Config illisible : " + str(e))
            return

        self._failed = False
        self.journal.lancement("Génération des mesures", apercu=dry)
        r = ToolRunner(generate_measures.generate,
                       model_dir=str(self.project.model_dir),
                       config=config,
                       dry_run=dry,
                       remove_orphans=self.chk_orphans.isChecked())
        r.line.connect(self.journal.ligne)
        r.fail.connect(self._on_fail)
        r.ok.connect(self._apres_succes)
        r.finished.connect(self._done)
        self._ecriture = not dry
        self._runner = r
        self.btn_generate.setEnabled(False)
        r.start()

    def _resoudre_non_sauve(self) -> bool:
        """Le config a des modifications non enregistrées, et le générateur
        lit le FICHIER : il générerait l'ancienne version sans rien dire.

        Le bouton vit maintenant à côté de l'éditeur (plus d'onglet à
        traverser, qui enregistrait la vue au passage) : l'oubli est devenu
        facile, on le rattrape ici. Rend True s'il faut générer."""
        box = QMessageBox(self)
        box.setWindowTitle("Config non enregistré")
        box.setText("Le config a des modifications non enregistrées.\n\n"
                    "Le générateur lit le FICHIER : sans enregistrer, il "
                    "générerait l'ancienne version.")
        b_sauver = (box.addButton("Enregistrer puis générer",
                                  QMessageBox.AcceptRole)
                    if self.sauver else None)
        b_ancien = box.addButton("Générer l'ancienne version",
                                 QMessageBox.DestructiveRole)
        box.addButton("Annuler", QMessageBox.RejectRole)
        box.setDefaultButton(b_sauver or b_ancien)
        box.exec_() if hasattr(box, "exec_") else box.exec()
        clic = box.clickedButton()
        if b_sauver is not None and clic is b_sauver:
            return bool(self.sauver())
        return clic is b_ancien

    def _apres_succes(self, _resultat):
        """Génération terminée SANS erreur. Si elle a réellement écrit, le
        modèle a changé : on prévient l'application pour que les onglets qui
        lisent le modèle revoient la liste des KPI. Sans ça, propager juste
        après générait sur une liste périmée — il fallait recharger le rapport
        à la main pour voir un KPI tout neuf."""
        if getattr(self, "_ecriture", False):
            self.modele_genere.emit()

    def _on_fail(self, msg):
        self._failed = True
        self.journal.erreur(msg)

    def _done(self):
        self._runner = None
        self.journal.fin(echec=self._failed)
        self.btn_generate.setEnabled(True)

    def set_unsaved(self, unsaved: bool):
        """L'onglet Mesures signale ici, en continu, que le config a des
        modifications non enregistrées."""
        self._non_sauve = bool(unsaved)
        self.lbl_unsaved.setVisible(self._non_sauve)
