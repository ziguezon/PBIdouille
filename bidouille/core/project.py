# -*- coding: utf-8 -*-
"""Résolution d'un projet Power BI (.pbip) et mémoire des projets récents.

Un dossier PBIP contient « <nom>.pbip », « <nom>.Report\\ » et
« <nom>.SemanticModel\\ » ; les fichiers partagés du pipeline
(measures_config.json, TD_Indicateurs.xlsx) sont à la racine du dossier."""

from __future__ import annotations

from pathlib import Path

from moteurs import chemins


class Project:
    """Chemins dérivés d'un .pbip. Ne touche pas au disque (sauf `valid`)."""

    def __init__(self, pbip_path, config_override=None):
        self.pbip = Path(pbip_path)
        self.folder = self.pbip.parent
        self.name = self.pbip.stem
        # measures_config.json choisi explicitement (bouton 📄 du config) —
        # None = convention : <dossier du .pbip>\measures_config.json
        self.config_override = Path(config_override) if config_override else None

    @property
    def report_dir(self) -> Path:
        return chemins.dossier_rapport(self.pbip)

    @property
    def model_dir(self) -> Path | None:
        try:
            return chemins.modele_du_rapport(self.report_dir)[0]
        except (ValueError, OSError, TypeError, AttributeError):
            return None

    @property
    def config_json(self) -> Path:
        if self.config_override:
            return self.config_override
        return self.folder / "measures_config.json"

    @property
    def td_xlsx(self) -> Path:
        return self.folder / "TD_Indicateurs.xlsx"

    @property
    def valid(self) -> bool:
        modele = self.model_dir
        return modele is not None and modele.is_dir() and self.report_dir.is_dir()

    def __str__(self) -> str:
        return str(self.pbip)


# --- réglages mémorisés -----------------------------------------------------
# UN seul magasin pour toute l'app. Il y en avait deux (« ChopChop/BIdouille »
# pour les projets récents, « PBIdouille/PBIdouille » pour la bibliothèque) :
# deux endroits où chercher, et un réglage qui semblait se perdre.
ORG_REGLAGES = "ChopChop"
APP_REGLAGES = "BIdouille"      # nom interne d'origine : les clés déjà là restent lues
_ANCIEN_MAGASIN = ("PBIdouille", "PBIdouille")


def reglages():
    """L'unique magasin de réglages (registre Windows via QSettings).

    Volontairement HORS du dossier de l'app : un nouveau zip dézippé ailleurs
    retrouve les réglages, alors qu'un fichier posé à côté de app.py serait
    perdu à chaque mise à jour."""
    from qtpy.QtCore import QSettings
    return QSettings(ORG_REGLAGES, APP_REGLAGES)


def lire_reglage(cle, defaut=""):
    """Réglage GLOBAL (pas lié à un projet). Reprend au besoin la valeur
    laissée dans l'ancien magasin, pour ne pas perdre ce qui y était."""
    from qtpy.QtCore import QSettings
    s = reglages()
    valeur = s.value(cle, None)
    if valeur in (None, ""):
        ancien = QSettings(*_ANCIEN_MAGASIN).value(cle, None)
        if ancien not in (None, ""):
            s.setValue(cle, ancien)       # rapatrié une fois pour toutes
            return ancien
        return defaut
    return valeur


def ecrire_reglage(cle, valeur) -> None:
    """Mémorise un réglage global. Une valeur VIDE est ignorée : sans ce
    garde-fou, refermer une boîte de dialogue sans rien choisir effaçait le
    chemin retenu — et le réglage avait l'air de se réinitialiser tout seul."""
    if valeur in (None, ""):
        return
    reglages().setValue(cle, str(valeur))


# --- projets récents (QSettings) -------------------------------------------
RECENTS_KEY = "recent_pbips"
MAX_RECENTS = 8


def load_recents(settings) -> list:
    """Liste des .pbip récents encore présents sur le disque (plus récent
    d'abord)."""
    raw = settings.value(RECENTS_KEY, [])
    if isinstance(raw, str):          # QSettings peut aplatir une liste d'un seul
        raw = [raw]
    return [p for p in (raw or []) if Path(p).exists()]


def push_recent(settings, pbip_path) -> None:
    """Place ce .pbip en tête des récents (dédupliqué, tronqué)."""
    pbip_path = str(pbip_path)
    recents = [p for p in load_recents(settings) if p != pbip_path]
    recents.insert(0, pbip_path)
    settings.setValue(RECENTS_KEY, recents[:MAX_RECENTS])
