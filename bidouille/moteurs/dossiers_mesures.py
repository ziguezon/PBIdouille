"""Comparaison des dossiers TMDL des mesures cibles."""
from __future__ import annotations

import re


def folder_matches(mfolder, cfolder) -> bool:
    """Le displayFolder `mfolder` correspond-il au dossier de cibles `cfolder` ?
    Match si chemin complet identique OU si le dossier FEUILLE est le même — un
    dossier imbriqué (« _indicateurs\\_cibles ») matche donc la config
    « _cibles », sans avoir à écrire le chemin complet."""
    mf = (mfolder or "").strip().lower()
    cf = (cfolder or "").strip().lower()
    if not mf or not cf:
        return False
    return mf == cf or re.split(r"[\\/]", mf)[-1] == cf
