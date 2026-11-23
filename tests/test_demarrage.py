# -*- coding: utf-8 -*-
"""Un rapport sans measures_config.json : les fichiers de départ.

    py tests\\test_demarrage.py

Vérifie :
  1. ce que moteurs/demarrage.py devine du modèle : la table des mesures, la
     colonne de dates (même celle d'une table calculée, qui ne déclare pas son
     type), les mesures de base ;
  2. l'écriture : un config que le générateur sait lire, un TD_Indicateurs.xlsx
     en tableau Excel, et jamais rien d'écrasé ;
  3. l'onglet Mesures : le bouton n'apparaît que sans config, crée les deux
     fichiers, et toute la fenêtre relit le projet sans erreur.

Travaille sur une COPIE du projet de démonstration, PRIVÉE de son config et de
son TD_Indicateurs.xlsx, avec un magasin de réglages jetable.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
FIT = Path(__file__).resolve().parent.parent
PBI = FIT.parent / "PowerBI"
if os.environ.get("PBIDOUILLE_PROJETS", "").strip():
    PBI = Path(os.environ["PBIDOUILLE_PROJETS"].strip())
sys.path.insert(0, str(FIT))
sys.path.insert(0, str(FIT / "bidouille"))
sys.path.insert(0, str(FIT / "bidouille" / "moteurs"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import exiger_projet, reglages_jetables, PROJET_DEMO   # noqa: E402

exiger_projet(PBI, PROJET_DEMO)
reglages_jetables("demarrage")

import demarrage                                                 # noqa: E402

PROJ = PROJET_DEMO
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


copie = Path(tempfile.mkdtemp(prefix="pbid_demarrage_"))
for s in (".SemanticModel", ".Report"):
    shutil.copytree(PBI / (PROJ + s), copie / (PROJ + s),
                    ignore=shutil.ignore_patterns(".pbi", "cache.abf"))
shutil.copy2(PBI / (PROJ + ".pbip"), copie / (PROJ + ".pbip"))
MODELE = copie / (PROJ + ".SemanticModel")
PBIP = copie / (PROJ + ".pbip")

print("1. ce qui est deviné")
config, notes, bases = demarrage.config_de_depart(MODELE)
s = config["settings"]
check(f"la table des mesures : celle qui en porte le plus ({s['sourceTable']})",
      s["sourceTable"] == "_mesures" and s["targetTable"] == "_mesures")
check(f"la colonne de dates d'une table calculée ({s['dateColumn']})",
      s["dateColumn"] == "'dim_Date'[Date]")
check(f"les mesures de base, sans les mesures générées ({len(bases)})",
      "Weight" in bases and not any(b.endswith(" YTD") for b in bases))
check("rien à générer tant qu'on n'a rien choisi",
      config["variations"] == {} and not config["fieldParameter"]["enabled"]
      and not config["switch"]["enabled"])
check("les notes disent ce qui a été deviné", any("_mesures" in n for n in notes)
      and any("dim_Date" in n for n in notes))

print("2. l'écriture")
essai = Path(tempfile.mkdtemp(prefix="pbid_demarrage_essai_"))
demarrage.ecrire_config(essai / "measures_config.json", config)
check("le config se relit tel quel",
      json.loads((essai / "measures_config.json").read_text(encoding="utf-8")) == config)
try:
    demarrage.ecrire_config(essai / "measures_config.json", {})
    refuse = False
except FileExistsError:
    refuse = True
check("un config existant n'est jamais écrasé", refuse)
import openpyxl                                                  # noqa: E402
demarrage.ecrire_td(essai / "TD_Indicateurs.xlsx", bases)
wb = openpyxl.load_workbook(essai / "TD_Indicateurs.xlsx")
ws = wb.active
lignes = [[c.value for c in r] for r in ws.iter_rows()]
check("TD_Indicateurs : les colonnes que l'outil lit, une ligne par mesure",
      lignes[0] == list(demarrage.COLONNES_TD) and [r[0] for r in lignes[1:]] == bases)
check("TD_Indicateurs est un tableau Excel, prêt à importer",
      list(ws.tables) == [demarrage.FEUILLE_TD])
wb.close()
import generate_measures as gm                                   # noqa: E402
existantes, bases_gm = gm.read_measures(MODELE, config)
check("le générateur trouve les mêmes mesures de base avec ce config",
      bases_gm == bases)

print("3. l'onglet Mesures")
from qtpy.QtWidgets import QApplication, QMessageBox             # noqa: E402
QMessageBox.exec = QMessageBox.exec_ = lambda *a, **k: 0
qa = QApplication.instance() or QApplication([])
from core.project import reglages                                # noqa: E402
reglages().setValue("last_pbip", str(PBIP))
import app as appmod                                             # noqa: E402
w = appmod.BidouilleWindow()
w.show()
qa.processEvents()
tc = w.tab_config
check("sans config : le bouton Créer est là", tc.btn_creer.isVisibleTo(tc)
      and not tc.inner.isEnabled())
ecrits = tc.creer_depart(avec_td=True)
qa.processEvents()
check("Créer : le config et le TD sont écrits à côté du .pbip",
      {p.name for p in ecrits} == {"measures_config.json", "TD_Indicateurs.xlsx"}
      and (copie / "measures_config.json").exists() and (copie / "TD_Indicateurs.xlsx").exists())
check("la fenêtre relit le projet : l'éditeur s'ouvre, le bouton disparaît",
      tc.inner.isEnabled() and not tc.btn_creer.isVisibleTo(tc)
      and w.btn_config.text().startswith("📄"))
check("Créer une seconde fois n'écrase rien", tc.creer_depart(avec_td=True) == [])
w.close()

shutil.rmtree(copie, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
shutil.rmtree(essai, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
print()
print("TOUT OK" if _ok else "DES ECHECS")
sys.exit(0 if _ok else 1)
