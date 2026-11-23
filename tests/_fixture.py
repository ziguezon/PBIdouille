# -*- coding: utf-8 -*-
"""Projet de démonstration exigé par les tests.

Les suites travaillent sur une COPIE d'un vrai projet PBIP — c'est ce qui leur
donne leur valeur : elles lisent du TMDL et des visual.json authentiques plutôt
que des fixtures inventées. Ce projet n'est PAS versionné (le dépôt ne contient
que l'outil), donc un clone frais ne l'a pas.

Plutôt que de planter avec une trace illisible, les tests s'arrêtent alors
proprement en disant ce qui manque et comment le fournir.
"""

from __future__ import annotations

import sys
from pathlib import Path

# le dossier des projets Power BI, frère de l'outil (cf. moteurs/chemins.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bidouille" / "moteurs"))
import chemins                                      # noqa: E402

PROJETS = chemins.PROJETS
PROJET_DEMO = chemins.PROJET_DEMO


def exiger_projet(racine, nom: str = PROJET_DEMO, *fichiers):
    """Vérifie que le projet de démo est là ; sinon, sort en code 0 (test
    ignoré, pas échoué) avec un message actionnable."""
    racine = Path(racine)
    manque = [nom + s for s in (".pbip", ".Report", ".SemanticModel")
              if not (racine / (nom + s)).exists()]
    manque += [f for f in fichiers if not (racine / f).exists()]
    if not manque:
        return True
    print("IGNORE : le projet de demonstration est absent de " + str(racine))
    print("   manque : " + ", ".join(manque))
    print("   Ces suites travaillent sur une COPIE d'un projet PBIP reel ; il")
    print("   n'est pas versionne (le depot ne porte que l'outil). Pose un")
    print("   projet PBIP dans " + str(PROJETS) + ", nomme « " + nom + " »,")
    print("   ou lance les tests depuis ton dossier de travail.")
    sys.exit(0)


def ajouter_cibles(semantic_dir, kpis, field_parameter="P_Indicateurs_parCalcul",
                   dossier="_cibles", calcul="Cible",
                   variations=("écart", "écart %"), branches=("YTD",)):
    """Donne des CIBLES à quelques KPI d'une COPIE du modèle, comme dans un
    vrai rapport : la cible racine (« Weight cible ») dans son dossier dédié et au
    paramètre de champ (Calcul « Cible »), ses faces de branche au paramètre
    aussi — mais ses VARIATIONS (« Weight cible écart »…) seulement dans le
    modèle, hors paramètre de champ. Rend les noms de mesures créés."""
    import re
    tables = Path(semantic_dir) / "definition" / "tables"
    tmdl = tables / "_mesures.tmdl"
    texte = tmdl.read_text(encoding="utf-8")
    ajouts, lignes, crees = [], [], []
    ordre = 900
    for k in kpis:
        racine = f"{k} {calcul.lower()}"
        noms = [(racine, dossier)]
        noms += [(f"{racine} {b}", None) for b in branches]
        for v in variations:
            noms.append((f"{racine} {v}", None))
            noms += [(f"{racine} {b} {v}", None) for b in branches]
        for nom, dos in noms:
            if f"\tmeasure '{nom}' =" in texte:     # le projet l'a déjà
                continue
            ajouts.append(f"\tmeasure '{nom}' = 0\n"
                          + (f"\t\tdisplayFolder: {dos}\n" if dos else "")
                          + f"\t\tlineageTag: cible-{len(ajouts)}\n\n")
            crees.append(nom)
        for nom, branche in [(racine, "Réel")] + [(f"{racine} {b}", b)
                                                  for b in branches]:
            lignes.append(f'\t\t\t\t    ("{calcul}", NAMEOF([{nom}]), {ordre}, '
                          f'"{k}", "{calcul}", "{branche}")')
            ordre += 1
    coupe = texte.find("\tpartition ")
    tmdl.write_text(texte[:coupe] + "".join(ajouts) + texte[coupe:],
                    encoding="utf-8")
    fp = tables / (field_parameter + ".tmdl")
    ftexte = fp.read_text(encoding="utf-8")
    m = list(re.finditer(r"^\t{4}\}\s*$", ftexte, re.M))[-1]
    fp.write_text(ftexte[:m.start()] + ",\n" + ",\n".join(lignes) + "\n"
                  + ftexte[m.start():], encoding="utf-8")
    return crees


def reglages_jetables(nom: str):
    """Pointe l'app sur un magasin de réglages JETABLE, vidé avant et après.

    À appeler avant de construire la fenêtre : ouvrir un projet l'inscrit dans
    les récents et comme « dernier projet ». Sans ça, une suite qui ouvre la
    copie temporaire d'un projet laissait l'app de l'usager rouvrir ce dossier
    temporaire (disparu) au lancement suivant."""
    import atexit
    from qtpy.QtCore import QSettings
    from core import project as prj
    prj.ORG_REGLAGES = "ChopChop"
    prj.APP_REGLAGES = "BIdouille_TEST_" + nom
    prj._ANCIEN_MAGASIN = ("PBIdouille_TEST_" + nom,) * 2

    def vider():
        prj.reglages().clear()
        QSettings(*prj._ANCIEN_MAGASIN).clear()
    vider()
    atexit.register(vider)
