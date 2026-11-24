# -*- coding: utf-8 -*-
"""Onglet « Rapport » : lance la propagation du formatage conditionnel et la
coloration des matrices par KPI, avec plus d'options que les scripts en CLI.
Chaque outil tourne dans un thread (core.runner) ; le journal est commun."""

from __future__ import annotations

import html
import json
from pathlib import Path

from qtpy.QtCore import Qt, QTimer, Signal
from qtpy.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import model_reader
from core.journal import Journal
from core.runner import ToolRunner
from tabs.dialog_guide import bouton_schema
from core.theme import (TEXT, TEXT_DIM, TEXT_MUTED, YELLOW,
                        checkable_list_stylesheet)

import propagate_cf
import color_matrix_by_kpi
import generate_measures



class ReportTab(QWidget):
    # le lien « Se règle dans ⚙ Réglages » de la fiche Excel : la fenêtre
    # ouvre les réglages (l'onglet ne connaît pas les autres onglets)
    ouvrir_reglages = Signal()

    def __init__(self, journal=None):
        super().__init__()
        # le journal est celui de l'app (colonne de droite). Un onglet
        # construit seul — un test — s'en fait un pour lui : aucun appelant
        # n'a donc à vérifier qu'il existe.
        self.journal = journal or Journal()
        self.project = None
        self._kpis = []          # KPI du modèle (paramètre de champ)
        self._runner = None
        self._queue = []
        self._failed = False

        root = QVBoxLayout(self)
        root.addWidget(self._build_propagation_group())
        root.addWidget(self._build_colors_group())

        chain_bar = QHBoxLayout()
        self.btn_chain = QPushButton("Propager puis colorer")
        self.btn_chain.clicked.connect(self._run_chain)
        chain_bar.addStretch()
        chain_bar.addWidget(self.btn_chain)
        root.addLayout(chain_bar)
        root.addStretch(1)      # le journal a sa colonne : rien à étirer ici

        self._action_buttons = [self.btn_propagate, self.btn_colorize, self.btn_chain]
        self._set_enabled(False)

    # ---- construction de l'UI -------------------------------------------------

    def _build_propagation_group(self) -> QGroupBox:
        box = QGroupBox("Propagation des attributs (formatage conditionnel)")
        grid = QGridLayout(box)

        # --- d'où vient le formatage : la GRILLE DES SOURCES ---
        # Le gabarit de base et ses exceptions vivent dans propagation.json,
        # partagé par les versions du rapport (cf. propagate_cf.Sources) :
        # ici, un résumé et le bouton qui ouvre la grille. Plus de gabarit ni
        # de cibles à choisir dans l'onglet — deux endroits pour dire la même
        # chose finissaient par se contredire.
        grid.addWidget(QLabel("Sources :"), 0, 0, Qt.AlignTop)
        self.lbl_sources = QLabel("")
        self.lbl_sources.setWordWrap(True)
        grid.addWidget(self.lbl_sources, 0, 1)
        ligne = QHBoxLayout()
        self.btn_sources = QPushButton("Grille des sources…")
        self.btn_sources.setToolTip(
            "De quel ICP chaque ICP copie le formatage de chaque variation :\n"
            "le gabarit de base pour tout le monde, un gabarit par groupe\n"
            "d'ICP, un gabarit par variation, et des règles case par case.")
        self.btn_sources.clicked.connect(self._open_sources_dialog)
        ligne.addWidget(self.btn_sources)
        ligne.addWidget(bouton_schema(self, "propagation"))
        ligne.addStretch()
        grid.addLayout(ligne, 1, 1)

        grid.addWidget(QLabel("Branches :"), 2, 0, Qt.AlignTop)
        self.lst_branches = QListWidget()
        self.lst_branches.setStyleSheet(checkable_list_stylesheet())
        self.lst_branches.setMaximumHeight(70)
        grid.addWidget(self.lst_branches, 2, 1)

        opts = QHBoxLayout()
        self.chk_prop_dry = QCheckBox("Aperçu (dry-run)")
        self.chk_prop_dry.setChecked(True)
        self.chk_prop_verbose = QCheckBox("Verbeux")
        opts.addWidget(self.chk_prop_dry)
        opts.addWidget(self.chk_prop_verbose)
        opts.addStretch()
        self.btn_propagate = QPushButton("Propager")
        self.btn_propagate.setToolTip(
            "Aligne chaque case de la grille sur sa source : ce que la source "
            "porte est recopié, ce qu'elle ne porte PLUS est retiré.\n"
            "Chaque visuel modifié est copié dans _backupsPBIdouille\\_propagate_backups\\ avant "
            "écriture. Laisser « Aperçu » coché pour voir le détail sans rien "
            "changer.")
        self.btn_propagate.clicked.connect(self._run_propagate)
        opts.addWidget(self.btn_propagate)
        grid.addLayout(opts, 3, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        return box

    def _build_colors_group(self) -> QGroupBox:
        box = QGroupBox("Couleurs des matrices par ICP")
        grid = QGridLayout(box)

        # L'Excel des indicateurs est défini UNE fois, dans le config
        # (⚙ Réglages). Cet onglet ne fait que le lire :
        # deux champs séparés finissaient par diverger.
        # Présenté en FICHE — libellés grisés, valeurs en clair — plutôt
        # qu'en paragraphe : trois lignes de texte de même couleur se
        # lisaient comme un bloc. Le chemin complet est en infobulle.
        fiche = QGridLayout()
        fiche.setHorizontalSpacing(12)
        fiche.setVerticalSpacing(4)
        self.lbl_td = QLabel("")                  # le fichier
        self.lbl_td_colonnes = QLabel("")         # les colonnes lues
        for r, (cle, valeur) in enumerate((("Excel", self.lbl_td),
                                           ("Colonnes", self.lbl_td_colonnes))):
            k = QLabel(cle)
            k.setStyleSheet(f"color:{TEXT_MUTED};")
            fiche.addWidget(k, r, 0)
            fiche.addWidget(valeur, r, 1)
        self.lbl_td_reglage = QLabel(
            f"<a href='reglages' style='color:{TEXT_MUTED};'>"
            "Se règle dans ⚙ Réglages</a>")
        self.lbl_td_reglage.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.lbl_td_reglage.setToolTip(
            "L'Excel est défini UNE fois, dans le config, cet onglet ne fait\n"
            "que le lire. Cliquer pour aller le régler.")
        self.lbl_td_reglage.linkActivated.connect(
            lambda _lien: self.ouvrir_reglages.emit())
        fiche.addWidget(self.lbl_td_reglage, 2, 1)
        fiche.setColumnStretch(1, 1)
        grid.addLayout(fiche, 0, 0, 1, 3)

        opts = QHBoxLayout()
        self.chk_col_dry = QCheckBox("Aperçu (dry-run)")
        self.chk_col_dry.setChecked(True)
        opts.addWidget(self.chk_col_dry)
        btn_palette = QPushButton("Aperçu && édition des couleurs…")
        btn_palette.setToolTip("Voir chaque ICP avec ses couleurs fond/texte, les\n"
                               "éditer au sélecteur de couleurs, et réécrire l'Excel\n"
                               "(les colonnes manquantes sont créées).")
        btn_palette.clicked.connect(self._open_colors_dialog)
        opts.addWidget(btn_palette)
        opts.addStretch()
        self.btn_colorize = QPushButton("Colorer")
        self.btn_colorize.setToolTip(
            "Donne à chaque colonne d'ICP d'une matrice la couleur de son ICP, "
            "lue dans l'Excel. Une couleur posée à la main sur une autre colonne "
            "reste.\n"
            "Chaque matrice modifiée est copiée dans _backupsPBIdouille\\_propagate_backups\\ "
            "avant écriture. Laisser « Aperçu » coché pour voir le détail sans rien "
            "changer.")
        self.btn_colorize.clicked.connect(self._run_colorize)
        opts.addWidget(self.btn_colorize)
        grid.addLayout(opts, 2, 0, 1, 3)
        return box

    def _td_spec(self) -> dict:
        """Définition de l'Excel des indicateurs, lue dans le config du
        projet — même source que le générateur. Relue à chaque usage :
        une modification enregistrée dans l'onglet Mesures est donc prise
        en compte sans relancer l'app."""
        cfg = {}
        if self.project:
            try:
                cfg = json.loads(
                    self.project.config_json.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cfg = {}
        return generate_measures.indicateurs_xlsx(
            cfg, self.project.folder if self.project else None)

    def _cible_folders(self) -> list:
        """Dossiers des mesures CIBLES, lus dans le config (kpiMeasureFolders).

        Sert à la propagation pour savoir ce qui est PROPRE à un KPI : une
        mesure de ce dossier ne part pas sur un KPI qui n'a pas la sienne. Le
        dossier est la déclaration la plus fiable — les cibles ne figurent pas
        toujours dans le paramètre de champ."""
        cfg = {}
        if self.project:
            try:
                cfg = json.loads(
                    self.project.config_json.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cfg = {}
        return [str(s.get("folder")).strip()
                for s in (cfg.get("kpiMeasureFolders") or [])
                if isinstance(s, dict) and str(s.get("folder") or "").strip()]

    # ---- la grille des sources --------------------------------------------

    def _sources_path(self) -> Path:
        """Le fichier LU pour ce rapport : propagation.json, partagé par les
        rapports du dossier (ou, faute de lui, l'ancien fichier propre à ce
        rapport — cf. propagate_cf.groupes_a_lire)."""
        return propagate_cf.groupes_a_lire(self.project.report_dir)

    def _variations_config(self) -> list:
        """[(id, suffixe)] des variations du config : c'est ce qui range une
        mesure hors paramètre de champ (sparkline, CF…) dans sa colonne."""
        return propagate_cf.variations_du_config(
            model_reader.read_config(self.project))

    def _refresh_sources_label(self):
        if not self.project:
            self.lbl_sources.setText("")
            return
        chemin = self._sources_path()
        regles = propagate_cf.lire_regles(chemin)
        self.lbl_sources.setToolTip(str(chemin))
        if not regles:
            self.lbl_sources.setText(
                "Aucune : " + chemin.name + " absent. Ouvrir la grille pour "
                "choisir le gabarit de base : c'est lui qui formate tout le "
                "monde.")
            self.lbl_sources.setStyleSheet(f"color:{YELLOW};")
            return
        grille = propagate_cf.Sources.depuis_regles(regles, self._kpis)
        erreurs, _avert = grille.problemes()
        texte = grille.resume_court()
        texte = texte[:1].upper() + texte[1:] + "."
        # d'où viennent ces règles : le fichier partagé, ou un ancien fichier
        # propre à ce rapport (plusieurs dans le dossier : pas de partage
        # deviné, cf. propagate_cf.migrer_groupes)
        if chemin.name == propagate_cf.GROUPES_FICHIER:
            texte += "\nFichier : propagation.json, partagé par les rapports du dossier."
        else:
            texte += (f"\nFichier : « {chemin.name} », propre à ce rapport, "
                      "enregistrer la grille pour la partager via "
                      "propagation.json.")
        if erreurs:
            texte = "Problème : " + erreurs[0] + "\n" + texte
        self.lbl_sources.setText(texte)
        self.lbl_sources.setStyleSheet(
            f"color:{YELLOW if erreurs else TEXT_DIM};")

    def _analyse(self) -> dict:
        """Ce que la grille doit savoir du modèle et du rapport (colonnes,
        mesures existantes, formatage en place). Un modèle illisible ne ferme
        pas la porte : la grille s'ouvre avec ce qu'elle a."""
        try:
            return propagate_cf.analyser(
                self.project.report_dir,
                entity=model_reader.entity(self.project),
                field_parameter=model_reader.field_parameter(self.project),
                branches=model_reader.branches(self.project),
                variations=self._variations_config(),
                cible_folders=self._cible_folders(),
                kpis=self._kpis or None)
        except (SystemExit, Exception) as e:     # noqa: BLE001 — on informe
            self.journal.info("⚠ Analyse du rapport incomplète : " + str(e))
            return {}

    def _open_sources_dialog(self):
        if not self.project:
            return
        from tabs.dialog_sources import SourcesDialog
        # lu là où il est (partagé, ou ancien fichier de ce rapport), ÉCRIT
        # toujours dans le fichier partagé : enregistrer la grille d'une
        # version la donne à toutes. L'analyse lit le modèle et le rapport :
        # au premier passage, ça peut prendre un moment — on le montre.
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dlg = SourcesDialog(
                propagate_cf.groupes_path(self.project.report_dir),
                self._kpis, self, source=self._sources_path(),
                analyse=self._analyse())
        finally:
            QApplication.restoreOverrideCursor()
        dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        if dlg.enregistre:
            self.journal.info("Grille des sources enregistrée dans "
                              + propagate_cf.GROUPES_FICHIER + ".")
        self._refresh_sources_label()

    def _refresh_td_label(self):
        """Rappelle, dans l'onglet Rapport, ce que le config a décidé."""
        td = self._td_spec()
        chemin = Path(td["path"])
        existe = chemin.exists()
        self.lbl_td.setText(chemin.name + ("" if existe
                                           else "   ⚠ introuvable"))
        self.lbl_td.setStyleSheet(f"color:{TEXT if existe else YELLOW};")
        self.lbl_td.setToolTip(str(chemin))
        gris = f"color:{TEXT_MUTED};"
        self.lbl_td_colonnes.setText(
            f"<span style='{gris}'>&nbsp;&nbsp;·&nbsp;&nbsp;</span>".join(
                f"<span style='{gris}'>{cle}</span>&nbsp;"
                f"<span style='color:{TEXT};'>{html.escape(str(valeur))}</span>"
                for cle, valeur in (("clé", td["keyColumn"]),
                                    ("fond", td["fillColumn"]),
                                    ("texte", td["textColumn"]))))

    def _open_colors_dialog(self):
        from tabs.dialog_couleurs import CouleursDialog
        if not self.project:
            return
        try:
            kpis = model_reader.kpis(self.project)
        except Exception:
            kpis = []
        td = self._td_spec()
        dlg = CouleursDialog(
            td["path"],
            key_col=td["keyColumn"],
            fill_col=td["fillColumn"],
            text_col=td["textColumn"],
            model_kpis=kpis,
            project_root=self.project.folder,
            parent=self,
        )
        dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
        self._refresh_td_label()

    # ---- projet ---------------------------------------------------------------

    def set_project(self, project):
        """Repeuple l'onglet pour un nouveau projet (appelé par app.py)."""
        self.project = project
        self._refresh_td_label()

        self._kpis = self._lire_kpis()
        self._fill_checklist(self.lst_branches, model_reader.branches(project), checked=True)
        # un ancien fichier <rapport>.propagation.json SEUL dans le dossier
        # devient propagation.json, partagé par toutes les versions du rapport
        propagate_cf.migrer_groupes(project.folder, log=self.journal.info)
        self._refresh_sources_label()

        self._set_enabled(project.valid)
        if not project.valid:
            self.journal.info("⚠ Projet invalide : dossiers .Report/.SemanticModel introuvables.")
        self.prechauffer()

    # La grille des sources lit TOUT le modèle et TOUS les visuels. Dans un
    # dossier synchronisé sous antivirus, ouvrir un fichier coûte cher : c'était l'attente
    # à l'ouverture de la grille. propagate_cf.lire_texte garde chaque texte
    # tant que son fichier ne change pas ; on le remplit ici, par bouchées de
    # quelques fichiers, quand l'app n'a rien d'autre à faire — dans le fil
    # principal, entre deux événements : rien ne bloque longtemps, et rien ne
    # lit pendant qu'une écriture se fait.
    PRECHAUFFAGE_DELAI = 400        # ms avant la 1re bouchée
    PRECHAUFFAGE_BOUCHEE = 6        # fichiers par bouchée

    def prechauffer(self):
        """Lance (ou relance) le préchauffage du projet courant ; un
        changement de projet abandonne le précédent."""
        self._prechauffage = getattr(self, "_prechauffage", 0) + 1
        self.prechauffage_fini = False
        p = self.project
        if p is None or not p.valid:
            return
        jeton = self._prechauffage
        try:
            fichiers = (sorted((p.model_dir / "definition" / "tables").glob("*.tmdl"))
                        + sorted(p.report_dir.glob(
                            "definition/pages/*/visuals/*/visual.json")))
        except OSError:
            return
        lus = [0]

        def bouchee():
            if jeton != self._prechauffage:
                return                  # un autre projet depuis : abandon
            debut = lus[0]
            for f in fichiers[debut:debut + self.PRECHAUFFAGE_BOUCHEE]:
                try:
                    propagate_cf.lire_texte(f)
                except OSError:
                    pass                # disparu entre-temps : tant pis
            lus[0] = debut + self.PRECHAUFFAGE_BOUCHEE
            if lus[0] < len(fichiers):
                QTimer.singleShot(10, bouchee)
            else:
                self.prechauffage_fini = True

        QTimer.singleShot(self.PRECHAUFFAGE_DELAI, bouchee)

    def _lire_kpis(self) -> list:
        try:
            return model_reader.kpis(self.project)
        except Exception as e:      # RuntimeError (tmdl absent) ou autre
            self.journal.info("⚠ ICP illisibles : " + str(e))
            return []

    def reload(self):
        """« ↻ Tout recharger » : relit le modèle (KPI, branches), l'Excel des
        indicateurs et la grille des sources, sans défaire les choix en cours
        (cf. refresh_model)."""
        if not self.project:
            return
        self.refresh_model()
        self._refresh_td_label()
        self._refresh_sources_label()

    def refresh_model(self):
        """Relit KPI et branches APRÈS une génération, sans défaire les choix
        en cours : les branches déjà décochées le restent, les nouvelles
        arrivent cochées. Un KPI tout neuf suit la base de la grille — rien à
        faire pour qu'il reçoive le formatage.

        Sans ça, il fallait recharger le rapport à la main pour qu'un KPI
        fraîchement généré soit connu de l'onglet."""
        if not self.project:
            return
        kpis = self._lire_kpis()
        nouveaux = [k for k in kpis if k not in self._kpis]
        self._kpis = kpis

        branches = model_reader.branches(self.project)
        b_avant = set(self._checked(self.lst_branches))
        b_connus = {self.lst_branches.item(i).text()
                    for i in range(self.lst_branches.count())}
        self._fill_checklist(self.lst_branches, branches, checked=True)
        for i in range(self.lst_branches.count()):
            it = self.lst_branches.item(i)
            if it.text() in b_connus and it.text() not in b_avant:
                it.setCheckState(Qt.Unchecked)

        if nouveaux:
            self.journal.info(
                "Liste des ICP rafraîchie, nouveau(x) : " + ", ".join(nouveaux)
                + " (ils suivent la base de la grille des sources).")
        self._refresh_sources_label()

    # ---- helpers listes cochables --------------------------------------------

    @staticmethod
    def _fill_checklist(widget, items, checked=True):
        widget.clear()
        for it in items:
            item = QListWidgetItem(it)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            widget.addItem(item)

    @staticmethod
    def _checked(widget):
        return [widget.item(i).text() for i in range(widget.count())
                if widget.item(i).checkState() == Qt.Checked]

    def _propagate_step(self):
        # UN seul step, quelle que soit la grille : la file lance chaque step
        # dans son propre ToolRunner, donc N steps ne pourraient pas partager
        # une sauvegarde — et une erreur à la 2e source laisserait la 1re
        # écrite. Un seul appel = une confirmation, une sauvegarde, tout ou
        # rien à la validation.
        dry = self.chk_prop_dry.isChecked()
        kwargs = dict(
            report_dir=str(self.project.report_dir),
            regles_json=str(self._sources_path()),
            branches=self._checked(self.lst_branches),
            toutes_branches=model_reader.branches(self.project),
            variations=self._variations_config(),
            entity=model_reader.entity(self.project),
            field_parameter=model_reader.field_parameter(self.project),
            dry_run=dry,
            verbose=self.chk_prop_verbose.isChecked(),
            cible_folders=self._cible_folders(),
        )
        return (propagate_cf.propagate_regles, kwargs, not dry,
                "Propagation des attributs")

    def _colorize_step(self):
        dry = self.chk_col_dry.isChecked()
        td = self._td_spec()          # relu au moment de l'exécution
        kwargs = dict(
            report_dir=str(self.project.report_dir),
            model_dir=str(self.project.model_dir),
            xlsx=td["path"],
            key_col=td["keyColumn"],
            fill_col=td["fillColumn"],
            text_col=td["textColumn"],
            entity=model_reader.entity(self.project),
            dry_run=dry,
        )
        return (color_matrix_by_kpi.colorize, kwargs, not dry, "Couleurs des matrices")

    # ---- lancement (file d'attente d'étapes) ---------------------------------

    def _sources_pretes(self) -> bool:
        """La grille dit-elle quelque chose ? Sinon, pas de propagation : on
        ne choisit pas de gabarit à la place de l'usager."""
        if propagate_cf.lire_regles(self._sources_path()):
            return True
        self.journal.info("⚠ Aucune source de formatage : ouvrir « Grille des "
                          "sources… » et choisir au moins le gabarit de base.")
        return False

    def _run_propagate(self):
        if self._sources_pretes():
            self._enqueue([self._propagate_step()])

    def _run_colorize(self):
        self._enqueue([self._colorize_step()])

    def _run_chain(self):
        if self._sources_pretes():
            self._enqueue([self._propagate_step(), self._colorize_step()])

    def _enqueue(self, steps):
        if self._runner is not None:
            return  # un run à la fois
        writes = any(w for _, _, w, _ in steps)
        if writes and not self._confirm_write():
            return
        self._queue = list(steps)
        self._failed = False
        self._set_busy(True)
        self._start_next()

    def _start_next(self):
        if self._failed or not self._queue:
            self._queue = []
            self._runner = None
            self._set_busy(False)
            return
        func, kwargs, writes, title = self._queue.pop(0)
        self.journal.lancement(title, apercu=not writes)
        r = ToolRunner(func, **kwargs)
        r.line.connect(self._log)
        r.fail.connect(self._on_fail)
        r.finished.connect(self._on_step_finished)
        self._runner = r
        r.start()

    def _confirm_write(self) -> bool:
        return QMessageBox.question(
            self, "Confirmer l'écriture",
            "Des fichiers du rapport vont être modifiés.\n\n"
            "Continuer ?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        ) == QMessageBox.Yes

    def _log(self, line):
        self.journal.ligne(line)

    def _on_fail(self, msg):
        self._failed = True
        self.journal.erreur(msg)

    def _on_step_finished(self):
        # une étape = un run : sa durée est ce qui dit si elle a travaillé, et
        # dans une chaîne « propager puis colorer » on veut les deux séparément
        self._runner = None
        self.journal.fin(echec=self._failed)
        if self._failed or not self._queue:
            self._queue = []
            self._set_busy(False)
        else:
            self._start_next()

    # ---- état des boutons -----------------------------------------------------

    def _set_busy(self, busy):
        self._busy = busy
        for b in self._action_buttons:
            b.setEnabled(not busy and bool(self.project and self.project.valid))

    def _set_enabled(self, enabled):
        for b in self._action_buttons:
            b.setEnabled(enabled)
