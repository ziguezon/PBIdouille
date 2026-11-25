# -*- coding: utf-8 -*-
"""La PORTÉE d'une propagation : tout le rapport par défaut, ou une page, ou
un seul visuel d'une page.

    py tests\\test_portee_propagation.py

Ce que ce fichier vérifie, sur une COPIE du projet de démonstration (le
vrai n'est jamais touché) :

  1. le moteur : dans_portee / visuels_de_la_portee / decrire_portee ;
  2. une PAGE : ses visuels reçoivent le formatage, les autres pages restent
     identiques à l'octet près ;
  3. un VISUEL : lui seul change, même sur sa propre page ;
  4. sans portée, tout le rapport, comme avant ;
  5. une portée qui ne garde plus rien (page disparue) : rien n'est écrit,
     et le journal le dit ;
  6. les pertes annoncées (retraits_prevus) ne comptent que la portée ;
  7. l'onglet Rapport : la liste des pages, celle des visuels de la page,
     et ce qui part au moteur.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

FIT = Path(__file__).resolve().parent.parent
PBI = FIT.parent / "PowerBI"
if os.environ.get("PBIDOUILLE_PROJETS", "").strip():
    PBI = Path(os.environ["PBIDOUILLE_PROJETS"].strip())
sys.path.insert(0, str(FIT / "bidouille"))
sys.path.insert(0, str(FIT / "bidouille" / "moteurs"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import exiger_projet, PROJET_DEMO, reglages_jetables   # noqa: E402

exiger_projet(PBI, PROJET_DEMO, "measures_config.json")

import propagate_cf as pc                         # noqa: E402

PROJ = PROJET_DEMO
ENT = "_mesures"
FP = "P_Indicateurs_parCalcul"
CFG = json.loads((PBI / "measures_config.json").read_text(encoding="utf-8"))
VARIATIONS = pc.variations_du_config(CFG)
MARQUEUR = "porteeTest"
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


COPIE = Path(tempfile.gettempdir()) / "pbid_portee"


def preparer():
    """Une copie fraîche, et le marqueur posé sur le gabarit de base dans
    trois visuels : deux sur une page, un sur une autre."""
    rmtree(COPIE)
    COPIE.mkdir(parents=True)
    for s in (".Report", ".SemanticModel"):
        shutil.copytree(PBI / (PROJ + s), COPIE / (PROJ + s))
    for f in (PROJ + ".pbip", "measures_config.json", "TD_Indicateurs.xlsx"):
        if (PBI / f).exists():
            shutil.copy2(PBI / f, COPIE / f)
    R = COPIE / (PROJ + ".Report")
    for vj in CHOISIS:
        vj = R / vj
        data = json.loads(vj.read_text(encoding="utf-8"))
        objets = data.setdefault("visual", {}).setdefault("objects", {})
        objets.setdefault("dataPoint", []).append(
            {"properties": {MARQUEUR: {"expr": {"Literal": {"Value": "1D"}}}},
             "selector": {"metadata": f"{ENT}.{BASE}",
                          "data": [{"dataViewWildcard": {"matchingOption": 0}}]}})
        vj.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    return R


def visuels(R):
    return sorted(R.glob("definition/pages/*/visuals/*/visual.json"))


def etat(R) -> dict:
    return {pc.cle_visuel(vj): vj.read_bytes() for vj in visuels(R)}


def porteurs(vj) -> set:
    """Les KPI qui portent le marqueur dans ce visuel."""
    out = set()
    objets = (json.loads(vj.read_text(encoding="utf-8")).get("visual") or {}).get("objects") or {}
    for liste in objets.values():
        for e in liste if isinstance(liste, list) else []:
            props = e.get("properties") if isinstance(e, dict) else None
            if isinstance(props, dict) and MARQUEUR in props:
                out.add((pc.entry_metadata(e) or "")[len(ENT) + 1:])
    return out


def propager(R, journal=None, **kw):
    return pc.propagate_regles(R, {"base": BASE}, field_parameter=FP,
                               variations=VARIATIONS, branches=["YTD"],
                               toutes_branches=["YTD"],
                               log=(journal.append if journal is not None
                                    else (lambda *_: None)), **kw)


M = PBI / (PROJ + ".SemanticModel")
KPIS = pc.kpis_from_parameter(M, FP)
BASE = KPIS[1] if len(KPIS) > 1 else KPIS[0]

# trois visuels hors groupe : deux sur la première page qui en a deux, un
# sur une autre page
R0 = PBI / (PROJ + ".Report")
par_page: dict = {}
for vj in visuels(R0):
    d = json.loads(vj.read_text(encoding="utf-8"))
    if "visualGroup" in d:
        continue
    par_page.setdefault(vj.parents[2].name, []).append(vj.relative_to(R0))
pages = [p for p, vs in par_page.items() if len(vs) >= 2]
autres = [p for p in par_page if p != (pages[0] if pages else None)]
if not pages or not autres:
    print("Le projet de démonstration n'a pas deux pages avec des visuels : "
          "test sauté.")
    sys.exit(0)
P1, P2 = pages[0], autres[0]
A, B = par_page[P1][0], par_page[P1][1]
C = par_page[P2][0]
CHOISIS = [A, B, C]
KA, KB, KC = (pc.cle_visuel(x) for x in (A, B, C))
AUTRES_KPI = {k for k in KPIS if k != BASE}

# ---------------------------------------------------------------------------
print("1. le moteur")
check("sans portée : tout est dedans", pc.dans_portee(R0 / A, None)
      and pc.dans_portee(R0 / C, []))
check("une page garde ses visuels, et seulement eux",
      pc.dans_portee(R0 / A, {P1}) and pc.dans_portee(R0 / B, {P1})
      and not pc.dans_portee(R0 / C, {P1}))
check("un visuel ne garde que lui", pc.dans_portee(R0 / A, {KA})
      and not pc.dans_portee(R0 / B, {KA}))
check("visuels_de_la_portee suit dans_portee",
      {pc.cle_visuel(v) for v in pc.visuels_de_la_portee(R0, {P1})}
      == {pc.cle_visuel(v) for v in visuels(R0) if v.parents[2].name == P1})
nom_p1 = json.loads((R0 / "definition" / "pages" / P1 / "page.json")
                    .read_text(encoding="utf-8")).get("displayName") or P1
mots = pc.decrire_portee(R0, [KA])
check(f"la portée se dit avec les noms de Power BI ({mots})",
      mots.startswith("visuel ") and mots.endswith(f"page « {nom_p1} »"))
check("tout le rapport, en mots", pc.decrire_portee(R0, None) == "tout le rapport")

# ---------------------------------------------------------------------------
print("2. une page")
R = preparer()
avant = etat(R)
journal: list = []
n = propager(R, journal, portee=[P1])
apres = etat(R)
check(f"des entrées écrites ({n})", n > 0)
check("ses deux visuels reçoivent le formatage de la base",
      porteurs(R / A) >= AUTRES_KPI and porteurs(R / B) >= AUTRES_KPI)
check("l'autre page n'a pas bougé d'un octet",
      all(apres[k] == avant[k] for k in avant if not k.startswith(P1 + "/")))
check("… même le visuel qui porte le marqueur",
      porteurs(R / C) == {BASE})
check("le journal dit la portée", any(l.startswith("Portée") for l in journal))

# ---------------------------------------------------------------------------
print("3. un visuel")
R = preparer()
avant = etat(R)
n = propager(R, portee=[KB])
apres = etat(R)
check("lui seul change",
      [k for k in avant if apres[k] != avant[k]] == [KB])
check("… et reçoit le formatage", porteurs(R / B) >= AUTRES_KPI)
check("son voisin de page garde son marqueur seul", porteurs(R / A) == {BASE})
check("une portée en texte simple vaut une liste d'un élément",
      pc._portee(KB) == {KB} and pc._portee(None) is None and pc._portee([]) is None)

# ---------------------------------------------------------------------------
print("4. sans portée, tout le rapport")
R = preparer()
propager(R)
check("les trois visuels reçoivent le formatage",
      all(porteurs(R / x) >= AUTRES_KPI for x in CHOISIS))

# ---------------------------------------------------------------------------
print("5. une page qui n'existe plus")
R = preparer()
avant = etat(R)
journal = []
n = propager(R, journal, portee=["pageDisparue"])
check("rien n'est écrit", n == 0 and etat(R) == avant)
check("le journal le dit", any("aucun visuel" in l for l in journal))
check("pas de sauvegarde vide déposée",
      not any((COPIE / "_backupsPBIdouille").rglob("*.json"))
      if (COPIE / "_backupsPBIdouille").exists() else True)

# ---------------------------------------------------------------------------
print("6. les pertes annoncées ne comptent que la portée")


class _Grille:
    """Une grille minimale : tout le monde copie la base."""
    kpis = KPIS

    def source(self, k, v):
        return BASE

    def gabarits_par_dessus(self):
        return []

    def sous_couche(self, s, v):
        return None

    def _rang(self, v):
        return 0


analyse = {"reglages": {(BASE, "Réel"): {KA: 1},
                        (KPIS[0] if KPIS[0] != BASE else KPIS[-1], "X"): {KA: 2, KC: 3}}}
tout = pc.retraits_prevus(analyse, _Grille())
sur_p2 = pc.retraits_prevus(analyse, _Grille(), [P2])
check(f"sans portée, la perte est comptée ({tout})", tout and tout[0][3] == 2)
check(f"bornée à l'autre page, la base n'y pilote rien : aucune perte ({sur_p2})",
      sur_p2 == [])

# ---------------------------------------------------------------------------
print("7. l'onglet Rapport")
reglages_jetables("portee_propagation")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qtpy.QtWidgets import QApplication                          # noqa: E402
app = QApplication.instance() or QApplication([])
from core.project import Project                                 # noqa: E402
import tabs.tab_report as tr                                     # noqa: E402

R = preparer()
onglet = tr.ReportTab()
onglet.set_project(Project(COPIE / (PROJ + ".pbip")))
check("par défaut : tout le rapport, rien à choisir dans les visuels",
      onglet.cmb_page.currentText() == onglet.TOUT_LE_RAPPORT
      and not onglet.cmb_visuel.isEnabled() and onglet.portee() is None)
ids_pages = [onglet.cmb_page.itemData(i) for i in range(1, onglet.cmb_page.count())]
check("chaque page du rapport est proposée, par son nom",
      set(ids_pages) == {p.name for p in (R / "definition" / "pages").iterdir()
                         if p.is_dir()}
      and all(onglet.cmb_page.itemText(i) for i in range(onglet.cmb_page.count())))
onglet.cmb_page.setCurrentIndex(onglet.cmb_page.findData(P1))
ids_vis = [onglet.cmb_visuel.itemData(i) for i in range(1, onglet.cmb_visuel.count())]
check("choisir une page liste ses visuels",
      onglet.cmb_visuel.isEnabled()
      and {KA.split("/")[1], KB.split("/")[1]} <= set(ids_vis))
check("… sans les groupes", all(
    "visualGroup" not in json.loads((R / "definition" / "pages" / P1 / "visuals" / v
                                     / "visual.json").read_text(encoding="utf-8"))
    for v in ids_vis))
check("… ni deux libellés pareils",
      len({onglet.cmb_visuel.itemText(i) for i in range(onglet.cmb_visuel.count())})
      == onglet.cmb_visuel.count())
check("la page seule part au moteur", onglet.portee() == [P1])
check("… et la confirmation la nomme",
      "la page « " in onglet.portee_en_mots())
onglet.cmb_visuel.setCurrentIndex(onglet.cmb_visuel.findData(KB.split("/")[1]))
check("un visuel : « page/visuel »", onglet.portee() == [KB])
pas = onglet._propagate_step()
check("l'étape de propagation emporte la portée", pas[1]["portee"] == [KB])
onglet.reload()
check("« Tout recharger » garde le choix", onglet.portee() == [KB])
onglet.set_project(Project(COPIE / (PROJ + ".pbip")))
check("un projet (ré)ouvert repart sur tout le rapport", onglet.portee() is None)
check("un libellé sans titre dit le type", tr.ReportTab.libelle_visuel(
    {"type": "card", "title": "", "hidden": True}) == "card  [masqué]")

rmtree(COPIE)
print()
print("RESULTAT : tout est bon" if _ok else "DES ECHECS")
sys.exit(0 if _ok else 1)
