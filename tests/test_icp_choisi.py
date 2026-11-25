# -*- coding: utf-8 -*-
"""Variations → « aussi une mesure ICP choisi » : une mesure qui renvoie celle
de l'ICP choisi, pour les règles de couleur qui ne visent aucune série.

    py tests\\test_icp_choisi.py

Cas rapporté : un graphique combiné, une seule série en colonne. Desktop
écrit sa règle de couleur « pour toutes les catégories », sans mesure dans le
selector : elle garde la mesure CF de l'ICP sur lequel on l'a posée, et
Power BI ignore une copie rattachée à une série (vérifié dans Desktop). Il
faut UNE règle dont la mesure change avec l'ICP. L'ancienne mesure Switch
appliquait une formule à la valeur du switch : un seul sens pour tous les
ICP. Celle-ci renvoie la mesure de chaque ICP, qui garde son propre sens.

Vérifie :
  1. le DAX : SELECTEDVALUE en cascade sur les colonnes, un cas par ICP (nom
     et libellé), un ICP en double écarté ;
  2. sur une copie du projet : la mesure renvoie, pour chaque ICP, SA mesure,
     donc son propre sens (<<direction>> de l'Excel des indicateurs) ;
  3. une par Calcul et par branche, cibles comprises ;
  4. les colonnes : par défaut celles des tables paramètre, sinon celles des
     réglages ; une colonne absente du modèle est écartée, jamais écrite ;
  5. un préfixe qui commencerait par un ICP est refusé ;
  6. écrite, la génération suivante la trouve inchangée ; la case décochée,
     elle devient une orpheline ;
  7. la propagation ne la prend pour la mesure d'aucun ICP.

Travaille sur une COPIE du projet de démonstration.
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
from _fixture import (exiger_projet, ajouter_cibles, reglages_jetables,   # noqa: E402
                      PROJET_DEMO)

exiger_projet(PBI, PROJET_DEMO, "measures_config.json", "TD_Indicateurs.xlsx")
reglages_jetables("icp_choisi")

import generate_measures as gm                                   # noqa: E402
import propagate_cf as pc                                        # noqa: E402

PROJ = PROJET_DEMO
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


# ===================================================================== 1
print("1. le DAX")
dax, doublons = gm.dax_icp_choisi(
    ["'P_a'[Indicateur]", "'TD_KPI'[mesure]"],
    [("Weight", "Weight CF", "#,0"), ("Body Fat %", "Body Fat % CF", "#,0"),
     ("Weight", "Weight cible 2 CF", "#,0")],
    {"Weight": "Poids", "Body Fat %": "body fat %"})
check("SELECTEDVALUE en cascade, la 1re colonne d'abord",
      "SELECTEDVALUE('P_a'[Indicateur], SELECTEDVALUE('TD_KPI'[mesure]))" in dax)
check("un cas par ICP, vers SA mesure",
      '"Weight", [Weight CF],' in dax and '"Body Fat %", [Body Fat % CF],' in dax)
check("le libellé aussi, quand il diffère du nom", '"Poids", [Weight CF],' in dax)
check("… mais pas un libellé qui ne diffère que par la casse (DAX l'ignore)",
      '"body fat %"' not in dax)
check("un 2e membre pour le même ICP est écarté, et signalé",
      "Weight cible 2 CF" not in dax and doublons == [("Weight", "Weight cible 2 CF")])
check("BLANK() quand aucun ICP n'est choisi", dax.rstrip().endswith("BLANK()\n    )"))
d1, _ = gm.dax_icp_choisi(["'P_a'[Indicateur]"], [("A", "A CF", None)])
check("une seule colonne : un SELECTEDVALUE simple",
      "VAR _icp = SELECTEDVALUE('P_a'[Indicateur])\n" in d1)
d2, _ = gm.dax_icp_choisi(["'P'[I]"], [('Le "grand" ICP', "X]Y", None)])
check("guillemets et crochets échappés",
      '"Le ""grand"" ICP", [X]]Y],' in d2)
check("colonne_de_dax lit les deux écritures",
      gm.colonne_de_dax("'P_Indicateurs 2'[Indicateur]") == ("P_Indicateurs 2", "Indicateur")
      and gm.colonne_de_dax("TD_KPI[mesure]") == ("TD_KPI", "mesure")
      and gm.colonne_de_dax("'L''ICP'[a]]b]") == ("L'ICP", "a]b")
      and gm.colonne_de_dax("TD_KPI") is None and gm.colonne_de_dax("[mesure]") is None)

# ===================================================================== 2
print("2. sur une copie : chaque ICP garde SA mesure, donc son sens")
copie = Path(tempfile.gettempdir()) / "pbid_icp_choisi"
rmtree(copie)
copie.mkdir(parents=True)
for s in (".SemanticModel", ".Report"):
    shutil.copytree(PBI / (PROJ + s), copie / (PROJ + s))
for f in (PROJ + ".pbip", "TD_Indicateurs.xlsx"):
    shutil.copy2(PBI / f, copie / f)
MODELE = copie / (PROJ + ".SemanticModel")
TABLES = MODELE / "definition" / "tables"

conf = json.loads((PBI / "measures_config.json").read_text(encoding="utf-8"))
_, bases = gm.read_measures(MODELE, conf)
check("la démo a un ICP au sens inversé (Body Fat %, direction -1)",
      "Body Fat %" in bases and "Weight" in bases)
ajouter_cibles(MODELE, ["Weight", "Body Fat %"])
conf["kpiMeasureFolders"] = [{"folder": "_cibles", "calcul": "Cible"}]
conf["hardcodedAttributes"] = {"tokens": {"direction": "direction"}}
V = "CF sens"
conf["variations"][V] = {
    "namePattern": "{base} CF sens",
    "dax": ["VAR V = ([{kpiRef}] - {baseRef}) * <<direction>>",
            "RETURN IF(V > 0, \"#2E7D32\", \"#C62828\")"],
    "inFieldParameter": False, "appliesToCibles": True,
    gm.CLE_ICP_CHOISI: True}
# {kpiRef} est déjà entre crochets
conf["variations"][V]["dax"][0] = "VAR V = ({kpiRef} - {baseRef}) * <<direction>>"
conf["fieldParameter"] = dict(conf["fieldParameter"])
conf["fieldParameter"]["tables"] = [{"name": "P_un"}, {"name": "P_deux"}]
for k in ("tableNames", "tableNamesByKpi", "tableNamesKpiBase"):
    conf["fieldParameter"].pop(k, None)
fp_col = conf["fieldParameter"].get("kpiColumn") or "Indicateur"

journal: list = []
st = gm.generate(MODELE, json.loads(json.dumps(conf)), dry_run=True, log=journal.append)
arbre = {n["name"]: n for n in st["arbre"]}
NOM = "ICP choisi CF sens"
ic = arbre.get(NOM)
check(f"« {NOM} » est générée", ic is not None and ic["type"] == "aiguillage")
check("… rangée dans « _ICP choisi », hors des dossiers des ICP",
      ic and ic["dossier"] == "_ICP choisi" and ic["parent"] is None)
for k in bases:
    mesure = f"{k} CF sens"
    if mesure in arbre:
        check(f"« {k} » renvoie SA mesure ({mesure})",
              f'"{k}", [{mesure}],' in ic["dax"])
check("Body Fat % garde son sens (-1), Weight le sien (1)",
      "* -1\n" in arbre["Body Fat % CF sens"]["dax"]
      and "* 1\n" in arbre["Weight CF sens"]["dax"])
check("la mesure ICP choisi ne recalcule rien : aucune formule de couleur",
      "#2E7D32" not in ic["dax"] and "<<" not in ic["dax"])
check("par défaut, l'ICP choisi se lit dans les tables paramètre, en cascade",
      f"SELECTEDVALUE('P_un'[{fp_col}], SELECTEDVALUE('P_deux'[{fp_col}]))" in ic["dax"])
check("le journal dit combien, et selon quoi",
      any("ICP choisi : " in l and "mesure(s) d'aiguillage" in l for l in journal))

# ===================================================================== 3
print("3. une par Calcul et par branche, cibles comprises")
branches = list((conf.get("branches") or {}).keys())
B = branches[0]
if f"Weight {B} CF sens" in arbre:
    nb = f"ICP choisi CF sens {B}"
    check(f"« {nb} » renvoie les mesures de la branche",
          nb in arbre and f"[Weight {B} CF sens]" in arbre[nb]["dax"]
          and "[Weight CF sens]" not in arbre[nb]["dax"])
nc = "ICP choisi Cible CF sens"
check(f"« {nc} » pour les cibles, à part de celles des ICP",
      nc in arbre and "[Weight cible CF sens]" in arbre[nc]["dax"]
      and "[Weight CF sens]" not in arbre[nc]["dax"])
check("… avec les seuls ICP qui ont une cible",
      nc in arbre and "[Total Steps" not in arbre[nc]["dax"])
check("les variations sans la case n'en ont pas",
      not any(n.startswith("ICP choisi CF YoY") for n in arbre))

# ===================================================================== 4
print("4. les colonnes")
c2 = json.loads(json.dumps(conf))
c2["selectedKpi"] = {"columns": ["'TD_KPI'[mesure]", "'Absente'[x]", "pas une colonne",
                                 "'TD_KPI'[colonne_absente]"]}
j2: list = []
st2 = gm.generate(MODELE, c2, dry_run=True, log=j2.append)
d2 = {n["name"]: n for n in st2["arbre"]}[NOM]["dax"]
check("une colonne des réglages remplace les tables paramètre",
      "VAR _icp = SELECTEDVALUE('TD_KPI'[mesure])\n" in d2)
check("une table absente : écartée et signalée",
      "Absente" not in d2 and any("'Absente'[x] est introuvable" in l for l in j2))
check("une colonne absente d'une table présente : écartée",
      "colonne_absente" not in d2 and any("colonne_absente" in l and "introuvable" in l
                                          for l in j2))
check("ce qui n'est pas une colonne : écarté",
      any("« pas une colonne » n'est pas une colonne" in l for l in j2))
c3 = json.loads(json.dumps(c2))
c3["selectedKpi"]["columns"] = ["'Absente'[x]"]
c3["fieldParameter"]["tables"] = [{"name": "P_un"}]
j3: list = []
st3 = gm.generate(MODELE, c3, dry_run=True, log=j3.append)
check("aucune colonne valide : rien n'est généré, et c'est dit",
      not any(n["type"] == "aiguillage" for n in st3["arbre"])
      and any("aucune colonne ne dit quel ICP" in l for l in j3))

# ===================================================================== 5
print("5. le préfixe")
c4 = json.loads(json.dumps(conf))
c4["selectedKpi"] = {"prefix": "Weight choisi"}
j4: list = []
st4 = gm.generate(MODELE, c4, dry_run=True, log=j4.append)
check("un préfixe qui commence par un ICP est refusé",
      not any(n["type"] == "aiguillage" for n in st4["arbre"])
      and any("commence par l'ICP « Weight »" in l for l in j4))
c5 = json.loads(json.dumps(conf))
c5["selectedKpi"] = {"prefix": "Choix", "displayFolder": "_aiguillages"}
st5 = gm.generate(MODELE, c5, dry_run=True, log=lambda *a: None)
n5 = {n["name"]: n for n in st5["arbre"]}.get("Choix CF sens")
check("préfixe et dossier réglables", n5 and n5["dossier"] == "_aiguillages")

# ===================================================================== 6
print("6. écrite, puis relue")
gm.generate(MODELE, json.loads(json.dumps(conf)), dry_run=False, log=lambda *a: None)
texte = (TABLES / "_mesures.tmdl").read_text(encoding="utf-8")
check("le bloc TMDL est écrit, avec son annotation",
      f"\tmeasure '{NOM}' =" in texte
      and f"annotation MeasureVariation = {NOM}|{V}" in texte)
st6 = gm.generate(MODELE, json.loads(json.dumps(conf)), dry_run=True, log=lambda *a: None)
check("la génération suivante la trouve inchangée",
      NOM in st6["unchanged"] and NOM not in st6["updated"])
c7 = json.loads(json.dumps(conf))
c7["variations"][V].pop(gm.CLE_ICP_CHOISI)
st7 = gm.generate(MODELE, c7, dry_run=True, remove_orphans=True, log=lambda *a: None)
check("la case décochée : une orpheline, retirée avec les orphelines",
      NOM in st7["removed"])
# une mesure écrite à la main du même nom n'est jamais écrasée : on retire
# l'annotation du bloc écrit, ce qui en fait une mesure « à la main »
blocs = texte.split(f"\tmeasure '{NOM}' =")
fin = blocs[1].index("annotation MeasureVariation")
fin_ligne = blocs[1].index("\n", fin)
(TABLES / "_mesures.tmdl").write_text(
    blocs[0] + f"\tmeasure '{NOM}' =" + blocs[1][:fin].rstrip("\t") + blocs[1][fin_ligne + 1:],
    encoding="utf-8")
j8: list = []
st8 = gm.generate(MODELE, json.loads(json.dumps(conf)), dry_run=True, log=j8.append)
check("une mesure écrite à la main du même nom est laissée telle quelle",
      NOM in st8["skipped"] and any(f"'{NOM}' existe mais n'est pas générée" in l
                                    for l in j8))

# ===================================================================== 7
print("7. la propagation")
check("elle n'est la mesure d'aucun ICP",
      pc.kpi_de(f"_mesures.{NOM}", sorted(bases, key=len, reverse=True)) is None)

# ===================================================================== 8
print("8. l'interface : la case de la variation, les réglages")
from qtpy.QtWidgets import QApplication                     # noqa: E402
from core.project import Project                            # noqa: E402
import tabs.tab_config as tc                                # noqa: E402
import tabs.fiche_mesure as fm                              # noqa: E402

(copie / "measures_config.json").write_text(
    json.dumps(conf, ensure_ascii=False, indent=2), encoding="utf-8")
app = QApplication.instance() or QApplication([])
onglet = tc.ConfigTab()
onglet.set_project(Project(copie / (PROJ + ".pbip")))
onglet._populate_list(select=V)
check("une variation qui l'a : la case est cochée", onglet.chk_icp.isChecked())
onglet._populate_list(select="PY")
check("une variation qui ne l'a pas : décochée", not onglet.chk_icp.isChecked())
onglet.chk_icp.setChecked(True)
onglet._commit_form()
check("cocher l'écrit dans la variation",
      onglet._config["variations"]["PY"].get(gm.CLE_ICP_CHOISI) is True)
onglet.chk_icp.setChecked(False)
onglet._commit_form()
check("décocher retire la clé", gm.CLE_ICP_CHOISI not in onglet._config["variations"]["PY"])
onglet._load_fp()
check("réglages vides par défaut, préfixe montré en filigrane",
      onglet.g_icp_colonnes.text() == "" and onglet.g_icp_prefixe.text() == ""
      and onglet.g_icp_prefixe.placeholderText() == gm.ICP_CHOISI_DEFAUT)
onglet.g_icp_colonnes.setText(" 'TD_KPI'[mesure] ;'P_un'[Indicateur]; ")
onglet.g_icp_prefixe.setText("Choix")
onglet._commit_fp()
check("les colonnes s'écrivent en liste, le préfixe tel quel",
      onglet._config.get("selectedKpi") == {
          "columns": ["'TD_KPI'[mesure]", "'P_un'[Indicateur]"], "prefix": "Choix"})
onglet._load_fp()
check("… et se relisent", onglet.g_icp_colonnes.text() == "'TD_KPI'[mesure]; 'P_un'[Indicateur]")
onglet.g_icp_colonnes.setText("")
onglet.g_icp_prefixe.setText("")
onglet._commit_fp()
check("vides : le bloc disparaît du config", "selectedKpi" not in onglet._config)
check("la fiche dit ce que la mesure renvoie",
      any(lib == "renvoie" and "Weight CF sens" in val for lib, val in fm.attributs(ic))
      and fm.attributs(ic)[0][1].startswith("ICP choisi"))
onglet.deleteLater()
app.processEvents()

rmtree(copie)
print()
print("RESULTAT :", "tout est bon" if _ok else "ECHECS")
sys.exit(0 if _ok else 1)
