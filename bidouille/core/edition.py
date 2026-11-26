# -*- coding: utf-8 -*-
"""Édition de l'app : « production » (la version partagée) ou « dev ».

En production, les fonctions qui ne sont pas encore assez éprouvées pour
être confiées à d'autres sont masquées — le code reste, il n'est simplement
pas offert :

  · Wireframe : lecture seule (plan des pages, structure, détails d'un
    visuel). Ni déplacement, ni redimensionnement, ni groupement, ni import
    de gabarit, ni enregistrement.

La suppression de ChopChop n'en fait plus partie : elle sert dans la version
partagée, et chaque suppression est sauvegardée avant d'écrire.

LA PRODUCTION EST LE DÉFAUT. L'édition dev ne s'obtient qu'en posant un
fichier « .dev » à côté de app.py (ou PBIDOUILLE_DEV=1 dans
l'environnement). Un zip partagé ne contient pas ce fichier : impossible
de distribuer la version dev par mégarde, alors que l'inverse — oublier de
« passer en production » avant de zipper — l'aurait fait.
"""

from __future__ import annotations

import os
from pathlib import Path

VERSION = "1.0"

# app.py est au premier niveau, ce fichier dans bidouille\core\
RACINE = Path(__file__).resolve().parents[2]
MARQUEUR_DEV = RACINE / ".dev"


def dev() -> bool:
    """Vrai seulement si on l'a demandé explicitement."""
    if os.environ.get("PBIDOUILLE_DEV", "").strip() in ("1", "oui", "yes", "true"):
        return True
    return MARQUEUR_DEV.exists()


def production() -> bool:
    return not dev()


def libelle() -> str:
    """Pour le titre de la fenêtre : « 1.0 » ou « 1.0 (dev) »."""
    return VERSION + ("" if production() else " (dev)")
