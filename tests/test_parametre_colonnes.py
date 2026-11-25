# -*- coding: utf-8 -*-
"""Une table paramètre créée dans DESKTOP : ses colonnes ICP, Calcul et
Branche prennent les noms du config, et sa colonne ICP est reliée à la table
des libellés.

    py tests\\test_parametre_colonnes.py

Desktop ne crée que trois colonnes (Value1 à Value3). Les rangées de
PBIdouille en ont six : sans déclaration, Desktop ajoutait les trois
dernières sous les noms Value4, Value5 et Value6, à renommer à la main.

Ce que ce fichier vérifie, sur une COPIE du projet de démonstration :

  1. colonnes_icp : les colonnes absentes sont déclarées avant la
     partition ; « Value4 » est renommée si rien ne la cite, signalée sinon ;
     un nom choisi par l'utilisateur est gardé ; deux passes = une ;
  2. colonne_citee : un visuel, une mesure, une relation comptent ;
  3. relation_presente / bloc_relation ;
  4. la génération : une table « Desktop » ressort avec ses trois colonnes
     nommées, une relation vers TD_Indicateurs[mesure], et relancer n'écrit
     plus rien ;
  5. une colonne Value4 déjà utilisée : signalée, pas renommée, et pas de
     relation vers un nom qui n'existe pas encore ;
  6. une colonne déjà reliée (même à une autre table) : rien d'ajouté ;
  7. la case décochée : aucune relation ;
  8. l'onglet : la case se lit et s'écrit (coché = défaut, rien d'écrit).
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


NOMS = {"Value4": "Indicateur", "Value5": "Calcul", "Value6": "Branche"}


def table_desktop(nom, en_plus=""):
    """Une table paramètre comme Desktop l'écrit : trois colonnes, sans
    dataType, et `en_plus` (des colonnes déjà ajoutées) avant la partition."""
    return (f"table {nom}\n"
            "\tlineageTag: 11111111-2222-3333-4444-555555555555\n\n"
            f"\tcolumn {nom}\n"
            "\t\tlineageTag: 11111111-2222-3333-4444-000000000001\n"
            "\t\tsummarizeBy: none\n"
            "\t\tsourceColumn: [Value1]\n"
            f"\t\tsortByColumn: '{nom} Order'\n\n"
            "\t\trelatedColumnDetails\n"
            f"\t\t\tgroupByColumn: '{nom} Fields'\n\n"
            "\t\tannotation SummarizationSetBy = Automatic\n\n"
            f"\tcolumn '{nom} Fields'\n"
            "\t\tisHidden\n"
            "\t\tlineageTag: 11111111-2222-3333-4444-000000000002\n"
            "\t\tsummarizeBy: none\n"
            "\t\tsourceColumn: [Value2]\n"
            f"\t\tsortByColumn: '{nom} Order'\n\n"
            "\t\textendedProperty ParameterMetadata =\n"
            "\t\t\t\t{\n"
            '\t\t\t\t  "version": 3,\n'
            '\t\t\t\t  "kind": 2\n'
            "\t\t\t\t}\n\n"
            "\t\tannotation SummarizationSetBy = Automatic\n\n"
            f"\tcolumn '{nom} Order'\n"
            "\t\tisHidden\n"
            "\t\tformatString: 0\n"
            "\t\tlineageTag: 11111111-2222-3333-4444-000000000003\n"
            "\t\tsummarizeBy: sum\n"
            "\t\tsourceColumn: [Value3]\n\n"
            "\t\tannotation SummarizationSetBy = Automatic\n\n"
            + en_plus
            + f"\tpartition {nom} = calculated\n"
            "\t\tmode: import\n"
            "\t\tsource =\n"
            "\t\t\t\t{\n"
            '\t\t\t\t    ("Weight", NAMEOF(\'_mesures\'[Weight]), 0)\n'
            "\t\t\t\t}\n\n"
            "\tannotation PBI_Id = abc\n")


def colonne_value(n, nom=None):
    nom = nom or f"Value{n}"
    return (f"\tcolumn {gm.quote_tmdl(nom)}\n"
            f"\t\tlineageTag: 11111111-2222-3333-4444-00000000010{n}\n"
            "\t\tsummarizeBy: none\n"
            f"\t\tsourceColumn: [Value{n}]\n\n"
            "\t\tannotation SummarizationSetBy = Automatic\n\n")


def colonnes_de(texte):
    """{sourceColumn: nom} des colonnes d'un texte de table."""
    out = {}
    for _genre, bloc in gm.split_members(texte):
        src = gm.re.search(r"^\t\tsourceColumn: \[(Value\d)\]", bloc or "", gm.re.M)
        tete = gm.COLONNE_TETE_RE.match(bloc or "")
        if src and tete:
            out[src.group(1)] = gm._nom_tmdl(tete.group(1))
    return out


# ---------------------------------------------------------------------------
print("1. colonnes_icp")
t0 = table_desktop("P_desk")
t1, faites, refus = gm.colonnes_icp(t0, NOMS)
check("les trois colonnes manquantes sont déclarées avec leurs noms",
      colonnes_de(t1) == {"Value1": "P_desk", "Value2": "P_desk Fields",
                          "Value3": "P_desk Order", "Value4": "Indicateur",
                          "Value5": "Calcul", "Value6": "Branche"})
check("… avant la partition, et le reste n'a pas bougé",
      t1.index("column Indicateur") < t1.index("partition P_desk")
      and t1.replace(t1[t1.index("\tcolumn Indicateur"):t1.index("\tpartition")], "") == t0)
check("… et le journal le dit", faites == ["colonnes Indicateur, Calcul, Branche déclarées"]
      and refus == [])
check("deux passes = une", gm.colonnes_icp(t1, NOMS) == (t1, [], []))

t0 = table_desktop("P_desk", colonne_value(4) + colonne_value(5) + colonne_value(6))
t1, faites, refus = gm.colonnes_icp(t0, NOMS)
check("Value4…6 ajoutées par Desktop : renommées",
      colonnes_de(t1)["Value4"] == "Indicateur" and colonnes_de(t1)["Value6"] == "Branche"
      and len(faites) == 3 and not refus)
check("… sans rien toucher d'autre que l'en-tête",
      t1.replace("column Indicateur", "column Value4").replace(
          "column Calcul", "column Value5").replace("column Branche", "column Value6") == t0)

t0 = table_desktop("P_desk", colonne_value(4) + colonne_value(5, "Mon calcul"))
t1, faites, refus = gm.colonnes_icp(t0, NOMS, utilisee=lambda col: col == "Value4")
check("Value4 utilisée : pas renommée, et signalée",
      colonnes_de(t1)["Value4"] == "Value4"
      and any("Value4" in r and "Desktop" in r for r in refus))
check("un nom choisi par l'utilisateur est gardé",
      colonnes_de(t1)["Value5"] == "Mon calcul")
check("la colonne absente est déclarée quand même", colonnes_de(t1)["Value6"] == "Branche")
t0 = table_desktop("P_desk", colonne_value(4) + colonne_value(5, "Indicateur"))
t1, _f, refus = gm.colonnes_icp(t0, NOMS)
check("un nom déjà pris par une autre colonne : rien, et c'est dit",
      colonnes_de(t1)["Value4"] == "Value4" and refus)
check("un nom avec espace est quoté", "\tcolumn 'Mon ICP'\n" in gm.colonnes_icp(
    table_desktop("P_desk"), {"Value4": "Mon ICP"})[0])

# ---------------------------------------------------------------------------
print("2. colonne_citee")
COPIE = Path(tempfile.gettempdir()) / "pbid_parametre_colonnes"


def preparer():
    rmtree(COPIE)
    COPIE.mkdir(parents=True)
    for s in (".Report", ".SemanticModel"):
        shutil.copytree(PBI / (PROJ + s), COPIE / (PROJ + s))
    for f in (PROJ + ".pbip", "measures_config.json", "TD_Indicateurs.xlsx"):
        if (PBI / f).exists():
            shutil.copy2(PBI / f, COPIE / f)
    return COPIE / (PROJ + ".SemanticModel")


MODELE = preparer()
TABLES = MODELE / "definition" / "tables"
RAPPORT = COPIE / (PROJ + ".Report")
vj = next(RAPPORT.glob("definition/pages/*/visuals/*/visual.json"))
check("une colonne que rien ne cite", not gm.colonne_citee(MODELE, "P_desk", "Value4"))
texte_vj = vj.read_text(encoding="utf-8")
vj.write_text(texte_vj.replace("{", '{"x_test": {"Column": {"Expression": {"SourceRef": '
                               '{"Entity": "P_desk"}}, "Property": "Value4"}},', 1),
              encoding="utf-8")
check("citée par un visuel", gm.colonne_citee(MODELE, "P_desk", "Value4"))
vj.write_text(texte_vj, encoding="utf-8")
mes = TABLES / "_mesures.tmdl"
texte_mes = mes.read_text(encoding="utf-8")
mes.write_text(texte_mes + "\n\tmeasure x_test = COUNTROWS(VALUES('P_desk'[Value4]))\n",
               encoding="utf-8")
check("citée par une mesure", gm.colonne_citee(MODELE, "P_desk", "Value4"))
mes.write_text(texte_mes, encoding="utf-8")

# ---------------------------------------------------------------------------
print("3. les relations")
rel = ("relationship a\n\tfromColumn: P_x.Indicateur\n\ttoColumn: TD_KPI.indicateur\n\n"
       "relationship b\n\tfromColumn: 'P y'.Autre\n\ttoColumn: TD_Indicateurs.mesure\n\n")
check("une colonne déjà reliée, même à une autre table",
      gm.relation_presente(rel, "P_x", "Indicateur", "TD_Indicateurs"))
check("deux tables déjà reliées par une autre colonne",
      gm.relation_presente(rel, "P y", "Indicateur", "TD_Indicateurs"))
check("sinon, rien", not gm.relation_presente(rel, "P_z", "Indicateur", "TD_Indicateurs"))
b = gm.bloc_relation("P z", "Indicateur", "TD_Indicateurs", "mesure")
check("le bloc : de la table paramètre vers TD, noms quotés au besoin",
      "\tfromColumn: 'P z'.Indicateur\n\ttoColumn: TD_Indicateurs.mesure\n" in b
      and b.startswith("relationship ") and b.endswith("\n\n"))

# ---------------------------------------------------------------------------
print("4. la génération, sur une table créée dans Desktop")
conf = json.loads((PBI / "measures_config.json").read_text(encoding="utf-8"))
conf["fieldParameter"] = dict(conf.get("fieldParameter") or {})
for k in ("tableNames", "tableNamesByKpi", "tableNamesKpiBase", "tableName"):
    conf["fieldParameter"].pop(k, None)
conf["fieldParameter"]["enabled"] = True
conf["fieldParameter"]["tables"] = [{"name": "P_desk"}]
conf["fieldParameter"]["kpiLabelLookup"] = {"table": "TD_Indicateurs", "keyColumn": "mesure",
                                            "labelColumn": "libelle_indicateur"}
for k, v in (("kpiColumn", "Indicateur"), ("calcColumn", "Calcul"), ("branchColumn", "Branche")):
    conf["fieldParameter"][k] = v
(TABLES / "P_desk.tmdl").write_text(table_desktop("P_desk"), encoding="utf-8")
REL = MODELE / "definition" / "relationships.tmdl"
rel_avant = REL.read_text(encoding="utf-8")


def generer(c, dry_run=False):
    journal = []
    st = gm.generate(MODELE, json.loads(json.dumps(c)), dry_run=dry_run, log=journal.append)
    return st, journal


st, journal = generer(conf, dry_run=True)
check("l'aperçu annonce les colonnes et la relation, sans rien écrire",
      any("Indicateur, Calcul, Branche déclarées" in s for s in st["fp_statuses"])
      and any("relation Indicateur → TD_Indicateurs[mesure] créée" in s
              for s in st["fp_statuses"])
      and (TABLES / "P_desk.tmdl").read_text(encoding="utf-8") == table_desktop("P_desk")
      and REL.read_text(encoding="utf-8") == rel_avant)
st, journal = generer(conf)
t = (TABLES / "P_desk.tmdl").read_text(encoding="utf-8")
check("la table a ses trois colonnes nommées",
      {"Value4": "Indicateur", "Value5": "Calcul", "Value6": "Branche"}.items()
      <= colonnes_de(t).items())
rel_apres = REL.read_text(encoding="utf-8")
check("la relation est ajoutée à la fin, le reste du fichier intact",
      rel_apres.startswith(rel_avant.rstrip("\n"))
      and "\tfromColumn: P_desk.Indicateur\n\ttoColumn: TD_Indicateurs.mesure\n" in rel_apres)
check("une sauvegarde couvre le fichier des relations",
      any(p.name == "relationships.tmdl"
          for p in (COPIE / "_backupsPBIdouille").rglob("*.tmdl")))
st, journal = generer(conf)
check("relancer n'écrit plus rien",
      any("Rien à écrire" in l for l in journal)
      and REL.read_text(encoding="utf-8") == rel_apres)
check("… et une seule relation pour la table",
      rel_apres.count("fromColumn: P_desk.Indicateur") == 1)

# ---------------------------------------------------------------------------
print("5. une colonne Value4 déjà utilisée")
MODELE = preparer()
TABLES = MODELE / "definition" / "tables"
REL = MODELE / "definition" / "relationships.tmdl"
rel_avant = REL.read_text(encoding="utf-8")
(TABLES / "P_desk.tmdl").write_text(
    table_desktop("P_desk", colonne_value(4) + colonne_value(5) + colonne_value(6)),
    encoding="utf-8")
mes = TABLES / "_mesures.tmdl"
mes.write_text(mes.read_text(encoding="utf-8")
               + "\n\tmeasure x_test = COUNTROWS(VALUES('P_desk'[Value4]))\n",
               encoding="utf-8")
st, journal = generer(conf)
t = (TABLES / "P_desk.tmdl").read_text(encoding="utf-8")
check("Value4 garde son nom, les deux autres sont renommées",
      colonnes_de(t)["Value4"] == "Value4" and colonnes_de(t)["Value5"] == "Calcul"
      and colonnes_de(t)["Value6"] == "Branche")
check("le journal dit de la renommer dans Desktop",
      any("Value4" in s and "Desktop" in s for s in st["fp_statuses"]))
check("pas de relation vers une colonne Indicateur qui n'existe pas encore",
      REL.read_text(encoding="utf-8") == rel_avant)

# ---------------------------------------------------------------------------
print("6. une colonne déjà reliée")
MODELE = preparer()
TABLES = MODELE / "definition" / "tables"
REL = MODELE / "definition" / "relationships.tmdl"
conf6 = json.loads(json.dumps(conf))
conf6["fieldParameter"]["tables"] = [{"name": "P_Indicateurs_parCalcul"}]
rel_avant = REL.read_text(encoding="utf-8")
generer(conf6)
check("la relation posée à la main (vers TD_KPI) est gardée, rien d'ajouté",
      REL.read_text(encoding="utf-8") == rel_avant)

# ---------------------------------------------------------------------------
print("7. la case décochée")
MODELE = preparer()
TABLES = MODELE / "definition" / "tables"
REL = MODELE / "definition" / "relationships.tmdl"
rel_avant = REL.read_text(encoding="utf-8")
(TABLES / "P_desk.tmdl").write_text(table_desktop("P_desk"), encoding="utf-8")
conf7 = json.loads(json.dumps(conf))
conf7["fieldParameter"]["relateKpiColumn"] = False
st, _j = generer(conf7)
check("les colonnes sont nommées quand même",
      colonnes_de((TABLES / "P_desk.tmdl").read_text(encoding="utf-8"))["Value4"]
      == "Indicateur")
check("mais aucune relation", REL.read_text(encoding="utf-8") == rel_avant)
conf7["fieldParameter"]["tables"] = [{"name": "P_neuve"}]
st, _j = generer(conf7)
check("… et une table neuve rappelle de la créer dans Desktop",
      any("P_neuve : CRÉÉE" in s and "Desktop" in s for s in st["fp_statuses"]))

# ---------------------------------------------------------------------------
print("7b. une clé répétée dans l'Excel")
import openpyxl                                                  # noqa: E402
MODELE = preparer()
TABLES = MODELE / "definition" / "tables"
REL = MODELE / "definition" / "relationships.tmdl"
rel_avant = REL.read_text(encoding="utf-8")
(TABLES / "P_desk.tmdl").write_text(table_desktop("P_desk"), encoding="utf-8")
wb = openpyxl.Workbook()
ws = wb.active
for ligne in (("mesure", "libelle_indicateur"), ("Weight", "Poids"),
              ("Total Steps", "Pas"), ("weight", "Poids bis")):
    ws.append(ligne)
xlsx = COPIE / "td_doublon.xlsx"
wb.save(xlsx)
check("doublons_excel : à la casse près, comme Power BI",
      gm.doublons_excel(xlsx, "mesure") == ["weight"])
check("… None quand l'Excel n'a pas la colonne, ou n'existe pas",
      gm.doublons_excel(xlsx, "autre") is None
      and gm.doublons_excel(COPIE / "absent.xlsx", "mesure") is None)
conf7b = json.loads(json.dumps(conf))
conf7b["indicateursXlsx"] = dict(conf7b.get("indicateursXlsx") or {}, path=str(xlsx))
conf7b.pop("hardcodedAttributes", None)
conf7b.pop("kpiTables", None)
st, _j = generer(conf7b, dry_run=True)
check("la relation n'est pas créée, et le journal nomme le doublon",
      any("doublons" in s and "weight" in s for s in st["fp_statuses"])
      and not any("relation Indicateur →" in s for s in st["fp_statuses"]))

# ---------------------------------------------------------------------------
print("8. l'onglet")
reglages_jetables("parametre_colonnes")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qtpy.QtWidgets import QApplication                          # noqa: E402
app = QApplication.instance() or QApplication([])
import tabs.tab_config as tc                                     # noqa: E402

ct = tc.ConfigTab()
ct._config = json.loads(json.dumps(conf))
ct._load_fp()
check("absent du config : coché (le défaut)", ct.g_fp_relier.isChecked())
ct.g_fp_relier.setChecked(False)
c = json.loads(json.dumps(conf))
ct._fp_vers(c)
check("décoché : « relateKpiColumn »: false", c["fieldParameter"].get("relateKpiColumn") is False)
ct._config = c
ct._load_fp()
check("… relu décoché", not ct.g_fp_relier.isChecked())
ct.g_fp_relier.setChecked(True)
ct._fp_vers(c)
check("recoché : la clé disparaît (rien d'écrit pour le défaut)",
      "relateKpiColumn" not in c["fieldParameter"])

rmtree(COPIE)
print()
print("RESULTAT : tout est bon" if _ok else "DES ECHECS")
sys.exit(0 if _ok else 1)
