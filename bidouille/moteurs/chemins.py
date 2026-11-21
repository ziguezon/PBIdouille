# -*- coding: utf-8 -*-
"""Où vivent les choses : l'outil d'un côté, les projets Power BI de l'autre.

    <dossier de travail>\\
        PBIdouille\\     l'outil (ce dépôt) : app.py, bidouille\\, tests\\, docs\\
        PowerBI\\        les projets .pbip, TD_Indicateurs.xlsx,
                         measures_config.json, propagation.json, les sauvegardes

Les deux sont frères : l'outil ne range plus rien à côté de lui, et un dossier
de projets ne contient plus de code. Ce module est le SEUL endroit qui connaît
cette disposition — l'app (projet ouvert par défaut, point de départ des
boîtes de dialogue), les lignes de commande des moteurs et les tests passent
tous par lui.

PBIDOUILLE_PROJETS (variable d'environnement) désigne un autre dossier de
projets, pour un poste où ils ne sont pas à côté de l'outil.

Dans un projet, le rapport et son modèle sont ceux que DÉCLARENT le .pbip
(artifacts -> report.path) et le definition.pbir du rapport (byPath, ou
byConnection pour une connexion live), pas ceux que le nom du .pbip laisse
deviner : un rapport peut viser un modèle partagé au nom différent, à côté
d'un modèle homonyme qui n'est pas le sien. La convention <nom>.Report /
<nom>.SemanticModel ne sert que quand rien n'est déclaré. Tous les onglets
et les moteurs passent par dossier_rapport et modele_du_rapport.
"""

from __future__ import annotations

import os
import json
from pathlib import Path

OUTIL = Path(__file__).resolve().parents[2]
PROJETS = Path(os.environ.get("PBIDOUILLE_PROJETS", "").strip()
               or OUTIL.parent / "PowerBI")
# le projet ouvert à défaut d'en avoir mémorisé un, et celui des tests
PROJET_DEMO = "Fitbit"


def dossier_rapport(pbip):
    """Le dossier du rapport que déclare le .pbip ; à défaut, <nom>.Report.
    ValueError si le .pbip est illisible ou déclare un rapport sans chemin."""
    pbip = Path(pbip)
    if pbip.is_file():
        meta = json.loads(pbip.read_text(encoding="utf-8-sig"))
        for art in meta.get("artifacts", []):
            if "report" in art:
                chemin = art["report"].get("path")
                if not isinstance(chemin, str) or not chemin.strip():
                    raise ValueError("Chemin du rapport absent dans le PBIP.")
                return (pbip.parent / chemin).resolve()
    return pbip.with_suffix(".Report")


def modele_du_rapport(rapport):
    """Retourne le modèle local ou les informations de connexion du rapport."""
    rapport = Path(rapport)
    fichier = rapport / "definition.pbir"
    if not fichier.exists():
        return rapport.with_suffix(".SemanticModel"), {}
    ref = json.loads(fichier.read_text(encoding="utf-8-sig")).get("datasetReference")
    if isinstance(ref, dict):
        chemin = (ref.get("byPath") or {}).get("path")
        if isinstance(chemin, str) and chemin.strip():
            return (rapport / chemin).resolve(), {}
        if isinstance(ref.get("byConnection"), dict):
            return None, ref["byConnection"]
    raise ValueError("Référence du modèle absente ou illisible dans definition.pbir.")


def modele_absent(pbip) -> str:
    """Pourquoi le rapport n'a pas de modèle local à lire ni à modifier, en une
    phrase pour l'utilisateur ; "" s'il en a un. Toutes les fenêtres qui ont
    besoin du modèle disent la même chose."""
    try:
        modele, _conn = modele_du_rapport(dossier_rapport(pbip))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return f"Le rapport ne dit pas lisiblement quel modèle il utilise : {exc}"
    if modele is None:
        return ("Ce rapport est en connexion live sur un modèle publié : il n'a pas "
                "de modèle local à lire ni à modifier.")
    if not modele.is_dir():
        return f"Le modèle que déclare le rapport est introuvable : {modele.name}."
    return ""
