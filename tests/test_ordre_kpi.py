# -*- coding: utf-8 -*-
"""Ordre des KPI dans les tables parametre, pilote par TD_Indicateurs.

    py tests\\test_ordre_kpi.py

Par defaut les KPI sortent dans l'ordre ALPHABETIQUE de Power BI. Une colonne
de TD_Indicateurs peut prendre la main : sa valeur devient la colonne Ordre
des tables parametre, donc l'ordre du slicer (sortByColumn).

Le fixture est choisi pour prouver les trois choses d'un coup :

  · l'ordre voulu n'a RIEN a voir avec l'alphabetique ;
  · 9 passe avant 10 (comparaison numerique — un tri texte ferait l'inverse,
    c'est la premiere deception de toute colonne d'ordre) ;
  · le KPI que la colonne ne mentionne pas part a la FIN, pas en tete.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
FIT = Path(__file__).resolve().parent.parent
# les projets Power BI vivent HORS de l'outil (cf. moteurs/chemins.py)
PBI = FIT.parent / "PowerBI"
if os.environ.get("PBIDOUILLE_PROJETS", "").strip():
    PBI = Path(os.environ["PBIDOUILLE_PROJETS"].strip())
sys.path.insert(0, str(FIT))
sys.path.insert(0, str(FIT / "bidouille"))
sys.path.insert(0, str(FIT / "bidouille" / "moteurs"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import exiger_projet, PROJET_DEMO   # noqa: E402

exiger_projet(PBI, PROJET_DEMO, "TD_Indicateurs.xlsx", "measures_config.json")

import generate_measures as gm                    # noqa: E402

PROJ = PROJET_DEMO
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


# l'ordre VOULU, et ce qu'il doit produire
ORDRES = {
    "Average Steps": 9,           # 9 avant 10 : preuve du tri numerique
    "Weight": 10,
    "Total Steps": 20,
    "Body Fat %": 30,
    # « Average Sleep Duration » : volontairement absent -> a la fin
}
ATTENDU = ["Average Steps", "Weight", "Total Steps", "Body Fat %",
           "Average Sleep Duration"]
ALPHABETIQUE = ["Average Sleep Duration", "Average Steps", "Body Fat %",
                "Total Steps", "Weight"]

c = Path(tempfile.gettempdir()) / "pbidouille_ordre"
rmtree(c)
c.mkdir(parents=True)
for suffixe in (".Report", ".SemanticModel"):
    shutil.copytree(PBI / (PROJ + suffixe), c / (PROJ + suffixe))
for f in ((PROJ + ".pbip"), "TD_Indicateurs.xlsx", "measures_config.json"):
    shutil.copy2(PBI / f, c / f)

# on ajoute la colonne d'ordre a la COPIE de l'Excel
import openpyxl                                   # noqa: E402

wb = openpyxl.load_workbook(c / "TD_Indicateurs.xlsx")
ws = wb.worksheets[0]
entetes = [str(cell.value).strip().lower() if cell.value else ""
           for cell in ws[1]]
col_ordre = len(entetes) + 1
col_mesure = entetes.index("mesure") + 1
ws.cell(row=1, column=col_ordre, value="ordre")
for r in range(2, ws.max_row + 1):
    mesure = ws.cell(row=r, column=col_mesure).value
    if mesure in ORDRES:
        ws.cell(row=r, column=col_ordre, value=ORDRES[mesure])
wb.save(c / "TD_Indicateurs.xlsx")
wb.close()

# ===================================================================== 1
print("1. le reglage existe et se transporte")
d = gm.indicateurs_xlsx({})
check("aucune colonne d'ordre par defaut (= tri alphabetique)",
      d.get("orderColumn", "") == "")
d = gm.indicateurs_xlsx({"indicateursXlsx": {"orderColumn": "ordre"}})
check("le config la declare", d["orderColumn"] == "ordre")
check("… sans toucher au reste", d["keyColumn"] == "mesure")

# ===================================================================== 2
print("2. la cle de tri : nombres d'abord, et comme des NOMBRES")
check("9 avant 10 (un tri texte ferait l'inverse)",
      gm._cle_ordre(9) < gm._cle_ordre(10))
check("2 avant 10", gm._cle_ordre("2") < gm._cle_ordre("10"))
check("la virgule decimale passe", gm._cle_ordre("1,5") < gm._cle_ordre("2"))
check("le texte se range APRES les nombres",
      gm._cle_ordre(999999) < gm._cle_ordre("a"))
check("deux textes se departagent alphabetiquement",
      gm._cle_ordre("Alpha") < gm._cle_ordre("beta"))
check("un KPI sans ordre passe apres tout le monde",
      gm._cle_ordre("zzz") < gm.ORDRE_ABSENT)

# ===================================================================== 3
print("3. kpi_ranks")
bases = sorted(ORDRES) + ["Average Sleep Duration"]
sans = gm.kpi_ranks(bases, {}, lambda *_: None)
check("sans colonne : tri alphabetique de Power BI",
      sorted(sans, key=sans.get) == ALPHABETIQUE)

journal = []
avec = gm.kpi_ranks(bases, ORDRES, journal.append)
check("avec colonne : c'est elle qui commande",
      sorted(avec, key=avec.get) == ATTENDU)
check("les rangs sont 0..n-1, sans trou",
      sorted(avec.values()) == list(range(len(bases))))
check("le journal nomme le KPI sans ordre",
      any("Average Sleep Duration" in l and "fin" in l for l in journal))
check("le journal montre l'ordre obtenu",
      any(l.startswith("Ordre des ICP :") for l in journal))

# ex aequo : l'alphabetique departage, et surtout de facon STABLE
exaequo = gm.kpi_ranks(["Weight", "Total Steps"],
                       {"Weight": 5, "Total Steps": 5}, lambda *_: None)
check("deux ex aequo : departages alphabetiquement",
      sorted(exaequo, key=exaequo.get) == ["Total Steps", "Weight"])
check("… et de facon stable (relancer ne rebrasse rien)",
      gm.kpi_ranks(["Total Steps", "Weight"],
                   {"Weight": 5, "Total Steps": 5}, lambda *_: None) == exaequo)

# ===================================================================== 4
print("4. lecture de la colonne")
td = gm.indicateurs_xlsx({"indicateursXlsx": {"orderColumn": "ordre"}}, c)
lu = gm.read_kpi_order(td, lambda *_: None)
check("les valeurs de l'Excel sont lues",
      {k: str(v) for k, v in lu.items()} == {k: str(v) for k, v in ORDRES.items()})
check("sans colonne configuree : rien, et pas une erreur",
      gm.read_kpi_order(gm.indicateurs_xlsx({}, c), lambda *_: None) == {})
journal = []
absente = gm.read_kpi_order(
    gm.indicateurs_xlsx({"indicateursXlsx": {"orderColumn": "pasla"}}, c),
    journal.append)
check("colonne inexistante : ignoree, jamais fatale", absente == {})
check("… et dite au journal", any("pasla" in l for l in journal))

# ===================================================================== 5
print("5. de bout en bout : la table parametre ecrite sur le disque")


def ordre_des_kpi(tmdl: Path) -> list:
    """Les KPI de la table parametre, dans l'ordre de leur colonne Ordre."""
    txt = tmdl.read_text(encoding="utf-8")
    vus = {}
    for m in re.finditer(r'NAMEOF\(.*?\)\s*,\s*(\d+)\s*,\s*"([^"]+)"', txt):
        rang, kpi = int(m.group(1)), m.group(2)
        if kpi not in vus or rang < vus[kpi]:
            vus[kpi] = rang
    return sorted(vus, key=vus.get)


modele = c / (PROJ + ".SemanticModel")
tables = modele / "definition" / "tables"
conf = json.loads((c / "measures_config.json").read_text(encoding="utf-8"))

# d'abord SANS colonne d'ordre : on veut voir l'alphabetique, pour que la
# difference ensuite ne puisse pas venir d'ailleurs
gm.generate(modele, conf, dry_run=False, log=lambda *_: None)
par_calcul = tables / "P_Indicateurs_parCalcul.tmdl"
par_kpi = tables / "P_Indicateurs_parKPI.tmdl"
check("sans colonne : la table sort dans l'ordre alphabetique",
      ordre_des_kpi(par_calcul) == ALPHABETIQUE)

conf["indicateursXlsx"] = {"orderColumn": "ordre"}
logs = []
gm.generate(modele, conf, dry_run=False, log=logs.append)
check("avec colonne : la table suit l'ordre voulu",
      ordre_des_kpi(par_calcul) == ATTENDU)
check("la table « par KPI » suit le meme ordre",
      ordre_des_kpi(par_kpi) == ATTENDU)
check("le journal de generation annonce l'ordre",
      any(l.startswith("Ordre des ICP :") for l in logs))
check("… et signale le KPI laisse de cote",
      any("Average Sleep Duration" in l and "fin" in l for l in logs))

# les rangs restent consecutifs : la colonne Ordre sert de sortByColumn, une
# valeur en double casserait le tri du slicer
txt = par_kpi.read_text(encoding="utf-8")
paires = {(m.group(2), int(m.group(1))) for m in
          re.finditer(r'NAMEOF\(.*?\)\s*,\s*(\d+)\s*,\s*"([^"]+)"', txt)}
check("un seul rang par KPI dans la table « par KPI » "
      "(sinon sortByColumn est invalide)",
      len(paires) == len({k for k, _ in paires}))

# relancer ne doit RIEN rebrasser
avant = par_calcul.read_text(encoding="utf-8")
gm.generate(modele, conf, dry_run=False, log=lambda *_: None)
check("idempotent : relancer ne rebrasse pas la table",
      par_calcul.read_text(encoding="utf-8") == avant)

# ===================================================================== 6
print("6. le reglage dans l'onglet Mesures")
from PySide6.QtWidgets import QApplication                    # noqa: E402
from core.project import Project                              # noqa: E402
import tabs.tab_config as tc                                  # noqa: E402

app = QApplication.instance() or QApplication([])
onglet = tc.ConfigTab()
onglet.set_project(Project(c / (PROJ + ".pbip")))
check("le champ existe", hasattr(onglet, "g_td_order"))
onglet._load_global()          # ce que fait l'ouverture de « Reglages globaux »
check("il est vide quand le config ne dit rien",
      onglet.g_td_order.currentText().strip() == "")
check("la colonne de l'Excel est proposee",
      "ordre" in [onglet.g_td_order.itemText(i)
                  for i in range(onglet.g_td_order.count())])
check("… et une entree VIDE aussi, pour revenir a l'alphabetique",
      "" in [onglet.g_td_order.itemText(i)
             for i in range(onglet.g_td_order.count())])

onglet.g_td_order.setCurrentText("ordre")
onglet._commit_global()
check("choisir la colonne l'ecrit dans le config",
      (onglet._config.get("indicateursXlsx") or {}).get("orderColumn") == "ordre")
onglet._load_global()
check("… et elle revient a l'affichage",
      onglet.g_td_order.currentText().strip() == "ordre")
onglet.g_td_order.setCurrentText("")
onglet._commit_global()
check("la vider retire le reglage (retour a l'alphabetique)",
      "orderColumn" not in (onglet._config.get("indicateursXlsx") or {}))

onglet.deleteLater()
app.processEvents()
rmtree(c)

print("\n" + ("TOUT OK" if _ok else "*** DES ECHECS ***"))
sys.exit(0 if _ok else 1)
