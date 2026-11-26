# -*- coding: utf-8 -*-
"""Propager VERS LES BRANCHES seulement : chaque ICP est sa propre source,
son Réel descend sur ses branches (YTD), rien ne passe d'un ICP à un autre.

    py tests\\test_propagation_branches.py

C'est le cas des visuels montés un par ICP : chacun a son formatage, réglé à
la main sur le Réel, et aucun gabarit n'a de sens. Sur une COPIE du projet de
démonstration (le vrai n'est jamais touché) :

  1. deux ICP, deux réglages différents sur leur Réel : chacun arrive sur SA
     face YTD, avec SA valeur, une variation (PY) comprise, et aucun autre ICP
     ne reçoit rien ;
  2. relancer ne change rien ; changer le Réel met la face à jour ;
  3. la grille des sources n'est pas lue : un propagation.json qui dit autre
     chose ne change rien ;
  4. la portée est respectée ;
  5. l'aperçu n'écrit rien, une sauvegarde couvre l'action ;
  6. sans branche cochée, rien n'est écrit et l'erreur le dit ;
  7. l'onglet Rapport : le bouton, et ce qui part au moteur.
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
from _fixture import exiger_projet, PROJET_DEMO, reglages_jetables   # noqa: E402

exiger_projet(PBI, PROJET_DEMO, "measures_config.json")
reglages_jetables("test_propagation_branches")

import propagate_cf as pc                         # noqa: E402

PROJ = PROJET_DEMO
ENT = "_mesures"
FP = "P_Indicateurs_parCalcul"
MARQUEUR = "branchesTest"
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


COPIE = Path(tempfile.gettempdir()) / "pbid_branches"
M0 = PBI / (PROJ + ".SemanticModel")
KPIS = pc.kpis_from_parameter(M0, FP)
X, Y = KPIS[0], KPIS[-1]
R0 = PBI / (PROJ + ".Report")
VISUELS = sorted(R0.glob("definition/pages/*/visuals/*/visual.json"))
seuls = [vj for vj in VISUELS
         if "visualGroup" not in json.loads(vj.read_text(encoding="utf-8"))]
par_page: dict = {}
for vj in seuls:
    par_page.setdefault(vj.parents[2].name, []).append(vj.relative_to(R0))
if len(par_page) < 2:
    print("Le projet de démonstration n'a pas deux pages avec des visuels : "
          "test sauté.")
    sys.exit(0)
P1, P2 = list(par_page)[:2]
A = par_page[P1][0]          # le visuel de X
B = par_page[P2][0]          # le visuel de Y, sur une autre page


def marque(valeur, mesure):
    return {"properties": {MARQUEUR: {"expr": {"Literal": {"Value": valeur}}}},
            "selector": {"metadata": f"{ENT}.{mesure}",
                         "data": [{"dataViewWildcard": {"matchingOption": 0}}]}}


def poser(vj, *entrees):
    data = json.loads(vj.read_text(encoding="utf-8"))
    objets = data.setdefault("visual", {}).setdefault("objects", {})
    objets.setdefault("dataPoint", []).extend(entrees)
    vj.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8")


def preparer():
    rmtree(COPIE)
    COPIE.mkdir(parents=True)
    for s in (".Report", ".SemanticModel"):
        shutil.copytree(PBI / (PROJ + s), COPIE / (PROJ + s),
                        ignore=shutil.ignore_patterns(".pbi", "cache.abf"))
    for f in (PROJ + ".pbip", "measures_config.json"):
        shutil.copy2(PBI / f, COPIE / f)
    R = COPIE / (PROJ + ".Report")
    poser(R / A, marque("'1D'", X), marque("'3D'", f"{X} PY"))
    poser(R / B, marque("'2D'", Y))
    return R


def marques(vj) -> dict:
    """mesure -> valeur du marqueur, dans ce visuel."""
    out = {}
    objets = (json.loads(vj.read_text(encoding="utf-8")).get("visual") or {}).get("objects") or {}
    for liste in objets.values():
        for e in liste if isinstance(liste, list) else []:
            props = e.get("properties") if isinstance(e, dict) else None
            if isinstance(props, dict) and MARQUEUR in props:
                out[(pc.entry_metadata(e) or "")[len(ENT) + 1:]] = \
                    props[MARQUEUR]["expr"]["Literal"]["Value"]
    return out


def etat(R) -> dict:
    return {pc.cle_visuel(vj): vj.read_bytes()
            for vj in R.glob("definition/pages/*/visuals/*/visual.json")}


def propager(R, journal=None, **kw):
    kw.setdefault("branches", ["YTD"])
    return pc.propagate_branches(R, field_parameter=FP,
                                 log=(journal.append if journal is not None
                                      else (lambda *_: None)), **kw)


# ---------------------------------------------------------------------------
print("1. chaque ICP vers sa face YTD")
R = preparer()
avant = etat(R)
journal: list = []
n = propager(R, journal)
check(f"des entrées écrites ({n})", n > 0)
check(f"{X} : son Réel et son PY descendent sur YTD, avec SES valeurs",
      marques(R / A) == {X: "'1D'", f"{X} PY": "'3D'",
                         f"{X} YTD": "'1D'", f"{X} YTD PY": "'3D'"})
check(f"{Y} : son Réel descend sur YTD, avec SA valeur",
      marques(R / B) == {Y: "'2D'", f"{Y} YTD": "'2D'"})
check("le journal dit le mode", any("Vers les branches seulement" in l
                                    for l in journal))

# ---------------------------------------------------------------------------
print("2. idempotent, et une face suit son Réel")
avant = etat(R)
check("relancer : rien ne change", propager(R) == 0 and etat(R) == avant)
vj = R / A
vj.write_text(vj.read_text(encoding="utf-8").replace("'1D'", "'5D'"),
              encoding="utf-8")
propager(R)
check("le Réel change : sa face YTD suit",
      marques(vj).get(f"{X} YTD") == "'5D'" and marques(vj).get(X) == "'5D'")

# ---------------------------------------------------------------------------
print("3. la grille des sources n'est pas lue")
R = preparer()
pc.ecrire_regles(pc.groupes_path(R), {"base": Y})
propager(R)
check(f"un propagation.json qui dit « base {Y} » ne change rien",
      set(marques(R / A)) == {X, f"{X} PY", f"{X} YTD", f"{X} YTD PY"}
      and marques(R / A)[f"{X} YTD"] == "'1D'")

# ---------------------------------------------------------------------------
print("4. la portée")
R = preparer()
avant = etat(R)
propager(R, portee=[P1])
apres = etat(R)
check("seule la page choisie change",
      [k for k in avant if apres[k] != avant[k]] == [pc.cle_visuel(R / A)])
check("l'autre page garde son Réel seul", marques(R / B) == {Y: "'2D'"})

# ---------------------------------------------------------------------------
print("5. l'aperçu, la sauvegarde")
R = preparer()
avant = etat(R)
n = propager(R, dry_run=True)
check(f"l'aperçu compte ({n}) sans rien écrire", n > 0 and etat(R) == avant)
racine = COPIE / "_backupsPBIdouille" / "_propagate_backups"
avant_sauv = set(racine.glob("*")) if racine.exists() else set()
propager(R)
sessions = [d for d in racine.glob("*") if d not in avant_sauv]
copies = sorted(f.name for f in sessions[0].glob("*.json")
                if f.name != "manifeste.json") if len(sessions) == 1 else []
check(f"une seule sauvegarde, les deux visuels dedans ({len(copies)})",
      len(sessions) == 1 and len([c for c in copies if not c.startswith("_")]) >= 2)

# ---------------------------------------------------------------------------
print("6. sans branche")
R = preparer()
avant = etat(R)
try:
    propager(R, branches=[])
    refus = ""
except SystemExit as exc:
    refus = str(exc)
check("refusé, avec un message", "branche" in refus and etat(R) == avant)

# ---------------------------------------------------------------------------
print("7. l'onglet Rapport")
from qtpy.QtWidgets import QApplication              # noqa: E402
from qtpy.QtCore import Qt                           # noqa: E402
qapp = QApplication.instance() or QApplication([])
from core.project import Project                     # noqa: E402
from tabs.tab_report import ReportTab                # noqa: E402

R = preparer()
t = ReportTab()
t.set_project(Project(COPIE / (PROJ + ".pbip")))
qapp.processEvents()
check("le bouton est là et actif", t.btn_branches.isEnabled())
f, kw, ecrit, titre = t._branches_step()
check("il appelle propagate_branches avec les branches cochées",
      f is pc.propagate_branches and kw["branches"] == t._checked(t.lst_branches)
      and not ecrit and kw["dry_run"])
for i in range(t.lst_branches.count()):
    t.lst_branches.item(i).setCheckState(Qt.Unchecked)
lances = []
t._enqueue = lambda steps: lances.append(steps)
t._run_branches()
check("aucune branche cochée : rien n'est lancé", not lances)
t.close()
rmtree(COPIE)

print()
print("OK" if _ok else "ECHEC")
sys.exit(0 if _ok else 1)
