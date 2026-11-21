# -*- coding: utf-8 -*-
"""PBIdouille — cockpit unique des outils Power BI du pipeline Fitbit.

Lancement   : py app.py  (à la racine du dossier de l'app)
Dépendances : qtpy + (PySide6 à la maison / PyQt5 au travail) ; openpyxl ou
              pandas pour les couleurs. Les scripts racine (propagate_cf,
              color_matrix_by_kpi) restent utilisables en CLI comme avant."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# app.py est au 1er niveau ; le reste du code vit dans bidouille\ :
#   bidouille\          -> core, tabs
#   bidouille\moteurs\  -> les moteurs d'écriture PBIP
# Les deux sur le path, quel que soit le répertoire de lancement.
_RACINE = Path(__file__).resolve().parent
_APP_DIR = _RACINE / "bidouille"
_MOTEURS = _APP_DIR / "moteurs"
for _p in (str(_APP_DIR), str(_MOTEURS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import chemins  # noqa: E402
# point de départ des boîtes de dialogue, et endroit où l'on cherche un projet
# à défaut d'en avoir mémorisé un : le dossier des projets Power BI, FRÈRE
# de celui de l'outil (cf. moteurs/chemins.py) — plus jamais l'outil lui-même
_DOSSIER_PARENT = chemins.PROJETS

from qtpy.QtCore import Qt  # noqa: E402
from qtpy.QtWidgets import (  # noqa: E402
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.journal import Journal  # noqa: E402
from core.project import (Project, load_recents, push_recent,  # noqa: E402
                          reglages)
from core.theme import TEXT_DIM, YELLOW, Separateur, apply_app_theme  # noqa: E402
from core import edition  # noqa: E402  (production / dev)

import backup_restore as br  # noqa: E402  (rangement des sauvegardes)
from tabs.tab_report import ReportTab  # noqa: E402
from tabs.dialog_guide import ouvrir_guide  # noqa: E402
from tabs.tab_wireframe import WireframeTab  # noqa: E402
from tabs.tab_config import ConfigTab  # noqa: E402
from tabs.tab_chopchop import ChopChopTab  # noqa: E402
from tabs.tab_lineage import LineageTab  # noqa: E402
from tabs.tab_radiographie import RadiographieTab  # noqa: E402

APP_NAME = "PBIdouille"          # PBI + bidouille ; réglages QSettings gardés sous « BIdouille »
APP_EMOJI = "🔧"
DEFAULT_PBIP = chemins.PROJET_DEMO + ".pbip"
# colonne du journal : largeur de départ et plancher (en dessous, une ligne de
# log revient à la ligne tous les trois mots et ne se lit plus)
JOURNAL_LARGEUR, JOURNAL_MINI = 440, 240
# le choix « journal visible », PAR VUE : clé de réglage et défaut. Dans
# l'éditeur de variations la colonne sert d'abord au DAX.
CHOIX_JOURNAL = {"ailleurs": ("journal_visible", "1"),
                 "variations": ("journal_visible_variations", "0")}


def _chemin_court(chemin) -> str:
    r"""…\dossier\fichier — de quoi reconnaître le projet sans que le libellé
    impose la largeur de la fenêtre (le chemin complet est en infobulle)."""
    p = Path(chemin)
    return str(p) if len(str(p)) <= 48 else "…\\" + p.parent.name + "\\" + p.name


class BidouilleWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = reglages()      # magasin unique (cf. core/project.py)
        self.project = None
        self.resize(1340, 800)
        # la version (et « (dev) » hors production) dans le titre : la
        # première chose à demander quand quelqu'un signale un problème
        self.setWindowTitle(APP_NAME + " " + edition.libelle())

        # Le journal est construit AVANT les onglets : chacun le reçoit et
        # écrit dedans, aucun n'a plus sa propre bande de log en bas
        # (cf. core/journal.py).
        self.journal = Journal()
        # un run qui démarre rouvre la colonne : sinon un outil écrirait dans
        # les fichiers sans qu'on voie une ligne de ce qu'il fait
        self.journal.demarre.connect(
            lambda: self._afficher_journal(True, memoriser=False))

        central = QWidget()
        self.setCentralWidget(central)
        # à gauche le travail, à droite le journal sur toute la hauteur ; la
        # poignée reste déplaçable et la largeur est retenue d'une fois à
        # l'autre
        self.split = Separateur(Qt.Horizontal)   # un trait fin, de l'air autour
        self.split.setChildrenCollapsible(False)
        dehors = QHBoxLayout(central)
        dehors.setContentsMargins(6, 6, 6, 6)
        dehors.addWidget(self.split)

        gauche = QWidget()
        v = QVBoxLayout(gauche)
        v.setContentsMargins(0, 0, 0, 0)

        # ---- le ruban (partagé par tous les onglets) : UNE ligne ----
        # À gauche, ce sur quoi on travaille : le rapport et son config. À
        # droite, ce qui vaut pour tout l'outil.
        bar = QHBoxLayout()
        bar.setSpacing(6)
        # le RAPPORT : un seul bouton qui le nomme et, au clic, propose les
        # récents et d'en ouvrir un autre. Il remplace une étiquette, une liste
        # « Récents… » et un bouton « Changer de rapport… », trois endroits
        # pour une seule chose. Le chemin complet est en infobulle : c'est la
        # barre, donc la largeur minimale de la FENÊTRE, qui en dépend.
        self.btn_projet = QToolButton()
        self.btn_projet.setObjectName("btnProjet")
        self.btn_projet.setPopupMode(QToolButton.InstantPopup)
        self.btn_projet.setText("📂 Choisir un rapport  ▾")
        self.menu_projet = QMenu(self.btn_projet)
        self.menu_projet.setToolTipsVisible(True)
        self.menu_projet.aboutToShow.connect(self._remplir_menu_projet)
        self.btn_projet.setMenu(self.menu_projet)
        # le config du rapport, juste à côté : il en fait partie (cf.
        # _update_config_label). Un bouton discret : on le change rarement.
        self.btn_config = QPushButton("")
        self.btn_config.setObjectName("btnConfig")
        self.btn_config.clicked.connect(self._choose_config)
        # les sauvegardes de TOUS les outils (mesures, propagation, wireframe,
        # ChopChop, Excel des indicateurs) : elles vivaient dans ChopChop, où
        # personne n'allait les chercher après une propagation
        # « Restaurer », pas « Sauvegardes » : une disquette se lisait comme
        # « enregistrer ». L'horloge le distingue aussi du ↻ de Tout recharger.
        self.btn_sauvegardes = QPushButton("🕘 Restaurer une sauvegarde…")
        self.btn_sauvegardes.setToolTip(
            "Revenir en arrière, avec les copies que chaque outil fait avant\n"
            "d'écrire dans ce rapport :\n"
            "mesures, propagation, wireframe, ChopChop, Excel des indicateurs.\n"
            "Restaurer en remet une ; l'état actuel est sauvegardé avant, donc\n"
            "une restauration s'annule aussi.")
        self.btn_sauvegardes.setEnabled(False)
        self.btn_sauvegardes.clicked.connect(self._ouvrir_sauvegardes)
        # pas de « Tout enregistrer » : il doublait les boutons des onglets
        # (« Sauvegarder » des Mesures, « Enregistrer » du Wireframe), qui
        # s'allument en ORANGE quand il reste quelque chose à écrire — un
        # bouton qui ne s'allume jamais n'apprenait rien
        # ⚙ Réglages : les réglages globaux du config, pour TOUS les onglets
        # (l'Excel des indicateurs sert au Rapport, les dossiers au générateur…)
        btn_reglages = QPushButton("⚙ Réglages")
        btn_reglages.setToolTip(
            "Les réglages globaux du measures_config.json de ce rapport :\n"
            "Excel des indicateurs, génération, paramètres de champ,\n"
            "attributs, branches… : ce qui sert à plusieurs onglets.")
        btn_reglages.clicked.connect(lambda: self._ouvrir_reglages())
        # les schémas du guide, dans l'app (fenêtre non modale : on la
        # garde ouverte à côté) — aussi ouverts par les liens « ▣ Schéma »
        btn_guide = QPushButton("Guide")
        btn_guide.setToolTip(
            "Les schémas du guide : comment les variations se ramifient,\n"
            "les paramètres de champ, les jetons du DAX, la propagation\n"
            "du formatage.")
        btn_guide.clicked.connect(lambda: ouvrir_guide(self))
        btn_reload_all = QPushButton("↻ Tout recharger")
        btn_reload_all.setToolTip(
            "Relit TOUTES les sources sans fermer l'app :\n"
            "  · le modèle (KPI, branches, paramètres de champ) ;\n"
            "  · measures_config.json ;\n"
            "  · TD_Indicateurs.xlsx (colonnes comprises) ;\n"
            "  · le fichier de groupes de propagation ;\n"
            "  · le rapport (pages et visuels du wireframe).\n\n"
            "À utiliser après avoir généré des mesures, modifié l'Excel, ou\n"
            "touché au modèle dans Desktop. Les modifications en attente sont\n"
            "signalées avant de recharger.")
        btn_reload_all.clicked.connect(self._reload_all)
        # le journal occupe une colonne : de quoi la rendre au travail quand on
        # n'en a pas besoin. Le libellé dit ce que le clic FERA — le thème ne
        # style pas l'état « enfoncé » d'un bouton, donc une case cochée ne se
        # verrait pas.
        self.btn_journal = QPushButton("")
        self.btn_journal.clicked.connect(
            lambda: self._afficher_journal(self.journal.isHidden()))
        bar.addWidget(self.btn_projet)
        bar.addWidget(self.btn_config)
        bar.addStretch(1)
        bar.addWidget(btn_reglages)
        bar.addWidget(self.btn_sauvegardes)
        bar.addWidget(btn_reload_all)
        bar.addWidget(btn_guide)
        bar.addSpacing(10)
        bar.addWidget(self.btn_journal)
        v.addLayout(bar)

        # ---- onglets ----
        # « Mesures » en tête : c'est par là que commence le travail (écrire
        # les mesures), le reste s'appuie sur ce qu'il a produit. Leur style
        # (cf. theme) les distingue des sous-onglets de Mesures.
        self.tabs = QTabWidget()
        self.tabs.setObjectName("ongletsPrincipaux")
        self.tab_config = ConfigTab(self.journal)   # « Mesures » : config + génération
        self.tabs.addTab(self.tab_config, "Mesures")
        self.tab_report = ReportTab(self.journal)
        self.tabs.addTab(self.tab_report, "Rapport")
        # d'où vient chaque table : lecture seule, donc aussi en production
        self.tab_lineage = LineageTab(self.journal)
        self.tabs.addTab(self.tab_lineage, "Sources de données")
        # ce que contient un rapport qu'on n'a pas fait : KPI, variations,
        # visuels. Lecture seule, donc aussi en production
        self.tab_radio = RadiographieTab(self.journal)
        self.tabs.addTab(self.tab_radio, "Radiographie 🩻")
        self.tab_wireframe = WireframeTab(self.journal)
        # PRODUCTION : pas d'onglet Wireframe du tout — pas encore utilisable
        # pour un usager (cf. core/edition.py). L'objet existe quand même : il
        # ne lit rien tant qu'on ne lui donne pas de projet, et le reste de
        # la fenêtre n'a pas à se demander s'il est là.
        if edition.dev():
            self.tabs.addTab(self.tab_wireframe, "Wireframe")
        self.tab_chopchop = ChopChopTab(self.journal)
        self.tabs.addTab(self.tab_chopchop, "ChopChop 🪓")
        v.addWidget(self.tabs, 1)

        self.split.addWidget(gauche)
        self.split.addWidget(self.journal)
        self.split.setStretchFactor(0, 1)   # tout l'agrandissement va au travail
        self.split.setStretchFactor(1, 0)
        self.journal.setMinimumWidth(JOURNAL_MINI)
        self._largeur_posee = False         # cf. showEvent
        # ce que l'usager a choisi au bouton, retenu PAR VUE : dans l'éditeur
        # de variations la colonne sert au DAX (journal masqué par défaut),
        # ailleurs au journal. Ouvrir le journal dans Variations l'y garde
        # ouvert, sans rien changer ailleurs.
        # une fois : une largeur retenue plus étroite que la nouvelle largeur
        # par défaut est élargie — le journal était trop étroit à l'usage.
        # Ensuite, la largeur que l'usager règle à la poignée est respectée.
        if self.settings.value("journal_largeur_revue", "") != "440":
            if self._reglage_int("journal_largeur", JOURNAL_LARGEUR) < JOURNAL_LARGEUR:
                self.settings.setValue("journal_largeur", JOURNAL_LARGEUR)
            self.settings.setValue("journal_largeur_revue", "440")
        self._voulu = {
            vue: self.settings.value(cle, defaut) not in ("0", 0, False)
            for vue, (cle, defaut) in CHOIX_JOURNAL.items()}
        self._afficher_journal(self._voulu["ailleurs"], memoriser=False)
        self.tabs.currentChanged.connect(self._colonne_selon_la_vue)
        # vue_changee plutôt que inner.currentChanged : un rechargement revient
        # sur Variations SANS signal, et le journal doit suivre quand même
        self.tab_config.vue_changee.connect(self._colonne_selon_la_vue)

        # une generation qui ecrit change le modele : les onglets qui le
        # lisent doivent revoir la liste des KPI, sans rechargement manuel
        self.tab_config.model_panel.modele_genere.connect(self._apres_generation)
        # le lien de la fiche Excel (onglet Rapport) mène là où elle se règle
        # le lien de la fiche Excel ouvre la fenêtre SUR la page de l'Excel
        self.tab_report.ouvrir_reglages.connect(lambda: self._ouvrir_reglages("excel"))

        self._tabs = [self.tab_config, self.tab_report, self.tab_lineage, self.tab_radio,
                      self.tab_chopchop]
        if edition.dev():
            self._tabs.insert(4, self.tab_wireframe)
        self._load_initial_project()
        self._colonne_selon_la_vue()

    # ---- journal (colonne de droite) ------------------------------------------

    def _reglage_int(self, cle, defaut):
        """QSettings rend des chaînes avec PyQt5 et des int avec PySide6 :
        on ne fait confiance à ni l'un ni l'autre."""
        try:
            return max(JOURNAL_MINI, int(self.settings.value(cle, defaut)))
        except (TypeError, ValueError):
            return defaut

    def showEvent(self, event):
        """La largeur du journal ne peut être posée qu'ICI : avant l'affichage,
        le splitter ne connaît pas encore la sienne et Qt ramène les tailles
        demandées à l'échelle de ce qu'il croit avoir — le journal naissait à
        170 px au lieu de 340."""
        super().showEvent(event)
        if not self._largeur_posee:
            self._largeur_posee = True
            if not self.journal.isHidden():
                self._poser_largeur_journal()

    def _poser_largeur_journal(self):
        largeur = self._reglage_int("journal_largeur", JOURNAL_LARGEUR)
        total = self.split.width() or self.width()
        self.split.setSizes([max(300, total - largeur), largeur])

    def _afficher_journal(self, montrer: bool, memoriser: bool = True):
        """Montre/masque la colonne de droite en gardant sa largeur : la
        rouvrir la retrouve telle quelle.

        `memoriser` : vrai pour le BOUTON (le choix de l'usager POUR LA VUE
        COURANTE, retenu d'une session à l'autre), faux quand c'est un
        changement de vue ou un run qui décide pour un moment."""
        if not montrer and not self.journal.isHidden():
            tailles = self.split.sizes()
            if len(tailles) > 1 and tailles[1] > 0:
                self.settings.setValue("journal_largeur", tailles[1])
        self.journal.setVisible(montrer)
        if montrer and self._largeur_posee:
            self._poser_largeur_journal()
        self.btn_journal.setText("🚀 Lancements ▸" if montrer
                                 else "◂ 🚀 Lancements")
        self.btn_journal.setToolTip(
            ("Masquer la colonne des lancements et rendre sa largeur au "
             "travail." if montrer else
             "Montrer la colonne des lancements : le journal de ce qui a\n"
             "tourné, et, dans l'onglet Mesures, le bouton de génération.")
            + "\nRetenu séparément pour l'éditeur de variations et pour le"
              "\nreste, comme la largeur de la colonne.")
        if memoriser:
            vue = self._vue()
            self._voulu[vue] = montrer
            self.settings.setValue(CHOIX_JOURNAL[vue][0],
                                   "1" if montrer else "0")

    def _vue(self) -> str:
        """« variations » quand l'éditeur de variations est à l'écran (sa
        colonne de droite porte le DAX), « ailleurs » sinon."""
        prise = (self.tabs.currentWidget() is self.tab_config
                 and self.tab_config.occupe_la_colonne())
        return "variations" if prise else "ailleurs"

    def _colonne_selon_la_vue(self, *_):
        """Chaque vue retrouve SON choix : dans « Mesures → Variations » le
        journal cède sa colonne au DAX et à l'aperçu — sauf si l'usager l'y a
        rouvert ; ailleurs il est là, sauf si l'usager l'a fermé."""
        self._afficher_journal(self._voulu[self._vue()], memoriser=False)

    def closeEvent(self, event):
        """Retient la largeur du journal telle qu'elle est à la fermeture."""
        tailles = self.split.sizes()
        if self.journal.isVisible() and len(tailles) > 1 and tailles[1] > 0:
            self.settings.setValue("journal_largeur", tailles[1])
        super().closeEvent(event)

    def _ouvrir_reglages(self, page=""):
        """⚙ Réglages — depuis la barre, ou le lien de la fiche Excel du
        Rapport (`page` = "excel"). Enregistrés, ils changent ce que le
        Rapport lit : sa fiche et ses groupes se relisent."""
        if self.tab_config.ouvrir_reglages(page):
            self.tab_report._refresh_td_label()

    def _save_all(self):
        """Chaque onglet qui a des modifications en attente les écrit
        (backups automatiques) — pour « Enregistrer puis recharger ». Plus
        de bouton pour ça : chaque onglet a le sien, qui s'allume."""
        for t in self._tabs:
            fn = getattr(t, "save_all", None)
            if fn:
                fn()

    def _en_attente(self) -> list:
        """Ce qui n'est pas encore écrit, onglet par onglet. Recharger relit le
        DISQUE : il faut donc le dire avant, pas après."""
        quoi = []
        if getattr(self.tab_config, "_dirty", False):
            quoi.append("Mesures : le config a des modifications non "
                        "enregistrées")
        n = len(getattr(self.tab_wireframe, "_dirty", ()) or ())
        if n:
            quoi.append(f"Wireframe : {n} élément(s) déplacé(s) non écrit(s)")
        return quoi

    def _reload_all(self):
        """« ↻ Tout recharger » : chaque onglet relit ses sources.

        Le besoin : après une génération, une colonne ajoutée dans
        TD_Indicateurs ou une retouche du modèle dans Desktop, l'outil
        travaillait sur des données périmées et il fallait le relancer.

        On ne rappelle PAS _set_project : ça repousserait le projet dans les
        récents, relancerait le rangement des sauvegardes et remettrait les
        listes de l'onglet Rapport à zéro. Chaque onglet sait relire ce qui lui
        appartient en gardant les choix en cours (cf. ses `reload`)."""
        if not self.project:
            return
        attente = self._en_attente()
        if attente:
            box = QMessageBox(self)
            box.setWindowTitle("Modifications non enregistrées")
            box.setText("Recharger relit les fichiers sur le disque, donc ce "
                        "qui n'est pas écrit sera perdu :\n\n· "
                        + "\n· ".join(attente))
            b_save = box.addButton("Enregistrer puis recharger",
                                   QMessageBox.AcceptRole)
            b_jeter = box.addButton("Recharger quand même",
                                    QMessageBox.DestructiveRole)
            box.addButton("Annuler", QMessageBox.RejectRole)
            box.setDefaultButton(b_save)
            box.exec_() if hasattr(box, "exec_") else box.exec()
            clic = box.clickedButton()
            if clic is b_save:
                self._save_all()
                if self._en_attente():
                    return
            elif clic is not b_jeter:
                return

        for t in self._tabs:
            fn = getattr(t, "reload", None)
            if fn:
                fn()
        self._update_config_label()
        self.journal.info(
            "↻ Tout rechargé : modèle, config, Excel des indicateurs, groupes "
            "et rapport relus depuis le disque.")

    # ---- projet ---------------------------------------------------------------

    def _apres_generation(self):
        """Une generation vient d'ECRIRE dans le modele. Les onglets qui le
        lisent doivent revoir la liste des KPI — sinon propager juste apres
        travaillait sur une liste perimee, et il fallait recharger le rapport
        a la main pour voir un KPI tout neuf.

        On ne rappelle PAS set_project : ca reinitialiserait les choix en cours
        (KPI template, cases cochees) et, pour l'onglet Mesures, ca ecraserait
        un config pas encore enregistre."""
        if not self.project:
            return
        self.tab_report.refresh_model()
        self.tab_chopchop.set_project(self.project)   # reanalyse differee
        self.tab_radio.reload()                       # idem

    def _set_project(self, pbip):
        project = Project(pbip)
        # config mémorisé pour CE projet (si toujours présent sur le disque)
        override = self.settings.value("config::" + str(project.pbip), "")
        if override and Path(override).exists():
            project.config_override = Path(override)
        self.project = project
        # les sauvegardes d'avant le regroupement traînent à la racine du
        # projet : on les range sous _backupsPBIdouille\ une bonne fois, pour
        # qu'il n'y ait qu'un seul endroit où chercher (rien n'est fusionné de
        # force, rien n'est supprimé — cf. backup_restore.migrate_legacy).
        # Puis le ménage, pour que la règle vaille dès l'ouverture et pas
        # seulement à la prochaine écriture.
        br.migrate_legacy(project.folder)
        br.prune_all(project.folder)
        push_recent(self.settings, pbip)
        self.settings.setValue("last_pbip", str(pbip))
        # le NOM seulement (le chemin est en infobulle) : c'est la barre, donc
        # la largeur minimale de la fenêtre, qui cède ainsi de la place au
        # journal
        # le FICHIER, extension comprise : on voit que c'est un .pbip qu'on
        # choisit, comme le 📄 du config à côté
        self.btn_projet.setText("📂 " + project.pbip.name + "  ▾")
        self.btn_projet.setToolTip(str(project.pbip) + "\n\nCliquer pour ouvrir un "
                                   "rapport récent ou un autre.")
        self.btn_sauvegardes.setEnabled(True)
        self.setWindowTitle(APP_NAME + " " + edition.libelle() + " · " + project.name)
        self._update_config_label()
        for t in self._tabs:
            t.set_project(project)

    def _choose_config(self):
        """Choisit le measures_config.json du projet courant (mémorisé)."""
        if not self.project:
            return
        start = str(self.project.config_json.parent if self.project.config_json.exists()
                    else self.project.folder)
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir le measures_config.json", start, "Config JSON (*.json)")
        if not path:
            return
        self.project.config_override = Path(path)
        self.settings.setValue("config::" + str(self.project.pbip), path)
        self._update_config_label()
        for t in self._tabs:            # re-peuple KPI/branches/éditeur
            t.set_project(self.project)

    def _update_config_label(self):
        p = self.project.config_json
        aide = ("\n\nCliquer pour choisir un autre fichier (par défaut : celui à "
                "côté du .pbip).\nLe choix est mémorisé pour ce rapport.")
        # le nom seul quand le config est à côté du .pbip (le cas courant) ;
        # ailleurs, de quoi voir qu'il vient d'un autre dossier
        nom = p.name if p.parent == self.project.folder else _chemin_court(p)
        if p.exists():
            self.btn_config.setText("📄 " + nom)
            self.btn_config.setToolTip("Config des mesures :\n" + str(p) + aide)
            couleur = TEXT_DIM
        else:
            self.btn_config.setText("⚠ measures_config.json introuvable, "
                                    "cliquer pour le choisir")
            self.btn_config.setToolTip("Attendu :\n" + str(p) + aide)
            couleur = YELLOW
        self.btn_config.setStyleSheet(f"QPushButton#btnConfig {{ color: {couleur}; }}")

    def _load_initial_project(self):
        last = self.settings.value("last_pbip", "")
        default = _DOSSIER_PARENT / DEFAULT_PBIP
        for cand in (last, str(default)):
            if cand and Path(cand).exists():
                self._set_project(cand)
                return
        self.btn_projet.setToolTip("Aucun rapport ouvert : cliquer pour en choisir un.")
        self.btn_config.hide()

    def _choose_project(self):
        start = str(self.project.folder) if self.project else str(_DOSSIER_PARENT)
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir un projet Power BI", start, "Projet Power BI (*.pbip)")
        if path:
            self._set_project(path)

    def _remplir_menu_projet(self):
        """Le menu du bouton de projet, refait à chaque ouverture : les récents
        (celui qui est ouvert est coché), puis ouvrir un autre rapport."""
        m = self.menu_projet
        m.clear()
        recents = load_recents(self.settings)
        courant = str(self.project.pbip) if self.project else ""
        if recents:
            titre = m.addAction("Rapports récents")
            titre.setEnabled(False)
            # deux versions d'un rapport portent souvent le même nom : leur
            # dossier les distingue
            noms = [Path(p).name for p in recents]
            for p, nom in zip(recents, noms):
                libelle = nom + (f"   ·  {Path(p).parent.name}" if noms.count(nom) > 1 else "")
                a = m.addAction(libelle)
                a.setCheckable(True)
                a.setChecked(p == courant)
                a.setToolTip(p)
                a.triggered.connect(lambda _=False, p=p: self._ouvrir_recent(p))
            m.addSeparator()
        m.addAction("Ouvrir un autre rapport…", self._choose_project)
        if self.project:
            m.addAction("Afficher le dossier dans l'Explorateur",
                        lambda: os.startfile(str(self.project.folder)))

    def _ouvrir_recent(self, pbip):
        if not self.project or str(self.project.pbip) != str(pbip):
            self._set_project(pbip)

    def _ouvrir_sauvegardes(self):
        """Les sauvegardes de tous les outils, pour le rapport ouvert."""
        if not self.project:
            return
        from tabs.dialog_backups import BackupsDialog
        dlg = BackupsDialog(self.project.folder, self, on_restored=self._apres_restauration)
        dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()

    def _apres_restauration(self, rep):
        """Des fichiers viennent d'être remis : chaque onglet les relit, comme
        « ↻ Tout recharger » (qui demande d'abord quoi faire de ce qui n'est
        pas encore écrit)."""
        n = len(rep.get("restaurés") or [])
        avant = rep.get("sauvegarde_avant")
        self.journal.info(f"Restauré : {n} fichier(s)"
                          + (f" (état précédent sous {Path(avant).name})" if avant else ""))
        self._reload_all()


def main():
    app = QApplication(sys.argv)
    apply_app_theme(app, APP_EMOJI, "ChopChop.BIdouille")
    win = BidouilleWindow()
    win.show()
    # exec_ (PyQt5) / exec (PySide6/Qt6)
    sys.exit(app.exec_() if hasattr(app, "exec_") else app.exec())


if __name__ == "__main__":
    main()
