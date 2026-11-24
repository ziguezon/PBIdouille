# -*- coding: utf-8 -*-
"""Onglet « Sources de données » : le lineage du rapport ouvert.

    py tests\\test_lineage.py

Vérifie :
  1. la lecture M (moteurs/lineage.py) : connecteurs imbriqués fusionnés,
     arguments de premier niveau, options [..] et null ignorés, paramètres M
     résolus depuis expressions.tmdl ;
  2. le projet de démonstration : ses sources (Excel, ODBC, CSV), ses tables
     calculées, et que rien n'est écrit dans le projet ;
  3. une connexion live et un fichier local disparu ;
  4. l'onglet : une liste à plat (fichier, feuille ou table lue), pastilles
     par type, ⚠ fichier introuvable, filtre, tri, export CSV ;
  5. le lineage dans le modèle : les tables que lit une table calculée, et
     « Reprise par » sur chaque table qu'elles lisent.

Travaille sur une COPIE du projet de démonstration.
"""

from __future__ import annotations

import csv
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
reglages_jetables("lineage")

import lineage as lg                                             # noqa: E402

PROJ = PROJET_DEMO
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


# ---------------------------------------------------------------------------
print("1. la lecture M")
check("Excel.Workbook(File.Contents(…)) : UNE source, avec le chemin",
      lg.connectors_in('Excel.Workbook(File.Contents("C:\\\\d\\\\x.xlsx"), null, true)')
      == [("Excel.Workbook", "C:\\\\d\\\\x.xlsx", "")])
check("les options [Delimiter=\";\"] ne passent pas pour un détail",
      lg.connectors_in('Csv.Document(File.Contents("a.csv"),[Delimiter=";"])')
      == [("Csv.Document", "a.csv", "")])
check("serveur et base, une requête SQL en option ignorée",
      lg.connectors_in('Sql.Database("srv", "db", [Query="SELECT f(1,2)"])')
      == [("Sql.Database", "srv", "db")])
check("un paramètre suivi d'un littéral garde son rang",
      lg.connectors_in('Sql.Database(Serveur, "db")') == [("Sql.Database", "Serveur", "db")])
check("#\"Nom\" est un nom, pas une valeur",
      lg.connectors_in('Sql.Database(#"Mon serveur", #"Base")')
      == [("Sql.Database", "Mon serveur", "Base")])
check("ce qui n'est pas un connecteur est ignoré",
      lg.connectors_in('Table.TransformColumnTypes(Source, {{"a", type text}})') == [])
check("élément lu : la feuille d'un classeur",
      lg.objets_lus('S = Excel.Workbook(x), F = S{[Item="Feuil1",Kind="Sheet"]}[Data]',
                    "Excel.Workbook") == "Feuil1 (feuille)")
check("élément lu : la table d'une base, avec son schéma",
      lg.objets_lus('S = Sql.Database("s", "d"), T = S{[Schema="dbo",Item="Ventes"]}[Data]',
                    "Sql.Database") == "dbo.Ventes")
check("élément lu : la navigation hiérarchique ODBC garde le schéma",
      lg.objets_lus('S = Odbc.DataSource("dsn=x"), a = S{[Name="db",Kind="Database"]}[Data], '
                    'b = a{[Name="dbo",Kind="Schema"]}[Data], '
                    'c = b{[Name="steps",Kind="Table"]}[Data]', "Odbc.DataSource") == "dbo.steps")
check("élément lu : une requête SQL écrite à la main",
      lg.objets_lus('S = Sql.Database("s", "d", [Query="SELECT 1"])', "Sql.Database")
      == lg.REQUETE_SQL
      and lg.objets_lus('S = Odbc.Query("dsn=x", "SELECT 1")', "Odbc.Query") == lg.REQUETE_SQL)
check("élément lu : rien pour un CSV lu entier",
      lg.objets_lus('S = Csv.Document(File.Contents("a.csv"),[Delimiter=";"])',
                    "Csv.Document") == "")
NOMS = ["Sales", "dim Date", "Date", "weight obs", "Q"]
check("tables citées en DAX : 'cité', nu, sans les variables ni les fonctions",
      lg.tables_citees("VAR Sales = 1 -- 'Q' en commentaire\nRETURN ADDCOLUMNS ( "
                       "CALENDAR ( MIN ( 'dim Date'[Date] ), DATE ( 2020, 1, 1 ) ), "
                       "\"Q\", [Date] + Sales )", NOMS) == ["dim Date"])
check("tables citées en DAX : dans l'ordre, une fois chacune, sans elle-même",
      lg.tables_citees("SUMMARIZE ( Sales, Sales[Region], 'weight obs'[x], Q )", NOMS, soi="Q")
      == ["Sales", "weight obs"])
check("requêtes citées en M : #\"…\" et noms nus",
      lg.tables_citees('let S = #"weight obs", t = Table.Join(S, Q, "Sales") in t', NOMS, "m")
      == ["weight obs", "Q"])
check("le DAX d'une partition calculée, sans ce qui suit",
      lg.source_calculee("\tpartition X = calculated\n\t\tmode: import\n\t\tsource = ```"
                         "\n\t\t\t\tSales\n\t\t\t\t```\n\n\tannotation A = Q\n")
      .split() == ["```", "Sales", "```"])
chaine = [{"table": "C", "partition": "C", "genre": lg.CALCULEE, "lit": ["B"]},
          {"table": "B", "partition": "B", "genre": lg.CALCULEE, "lit": ["A"]},
          {"table": "A", "partition": "A", "genre": lg.SOURCE, "lit": []}]
check("reprise par : directement ou par une autre table",
      lg.reprises(chaine) == {"A": ["B", "C"], "B": ["C"]})
check("au bout de la chaîne : la table à source externe",
      lg.sources_au_bout(chaine) == {"C": ["A"], "B": ["A"]})
check("famille lisible", lg.famille("Odbc.DataSource") == "ODBC"
      and lg.famille("Excel.Workbook") == "Excel")
check("paramètres M de expressions.tmdl",
      lg.parametres_m('expression Serveur = "srv01" meta [IsParameterQuery=true, '
                      'Type="Text"]\n\tlineageTag: x\n\nexpression \'Ma Base\' = "db" '
                      'meta [IsParameterQuery=true]\n')
      == {"Serveur": "srv01", "Ma Base": "db"})

# ---------------------------------------------------------------------------
copie = Path(tempfile.gettempdir()) / "pbid_lineage"
rmtree(copie)
copie.mkdir(parents=True)
for s in (".SemanticModel", ".Report"):
    shutil.copytree(PBI / (PROJ + s), copie / (PROJ + s))
shutil.copy2(PBI / (PROJ + ".pbip"), copie / (PROJ + ".pbip"))
MODELE = copie / (PROJ + ".SemanticModel")
PBIP = copie / (PROJ + ".pbip")

print("2. le projet de démonstration")
mtimes = {p: p.stat().st_mtime_ns for p in copie.rglob("*") if p.is_file()}
res = lg.scan_projet(PBIP)
check("pas d'erreur, modèle local", not res["erreur"] and not res["live"]
      and res["modele"] == PROJ + ".SemanticModel")
tables_tmdl = len(list((MODELE / "definition" / "tables").glob("*.tmdl")))
tables_vues = {l["table"] for l in res["lignes"]}
check(f"chaque table du modèle est vue ({len(tables_vues)} / {tables_tmdl})",
      len(tables_vues) == tables_tmdl)
srcs = lg.sources(res["lignes"])
familles = {s["famille"] for s in srcs}
check(f"des sources lues : {sorted(familles)}", familles and None not in familles)
calc = [l for l in res["lignes"] if l["genre"] == lg.CALCULEE]
check(f"les tables calculées sont reconnues ({len(calc)})",
      calc and all(l["connecteur"].startswith("DAX") for l in calc))
locf = next(l for l in calc if l["table"] == "Weight LOCF")
check(f"Weight LOCF lit weight obs et dim_Date ({locf['lit']})",
      set(locf["lit"]) == {"weight obs", "dim_Date"})
check("weight obs est reprise par Weight LOCF",
      lg.reprises(res["lignes"]).get("weight obs") == ["Weight LOCF"])
check("une source = une clé (connecteur, détails) distincte",
      len({(s["connecteur"], s["detail1"], s["detail2"]) for s in srcs}) == len(srcs))
check("lecture seule : rien n'a bougé dans le projet",
      {p: p.stat().st_mtime_ns for p in copie.rglob("*") if p.is_file()} == mtimes)

print("3. paramètres, fichier disparu, connexion live")
expr = MODELE / "definition" / "expressions.tmdl"
expr.write_text('expression Serveur = "srv-prod" meta [IsParameterQuery=true, Type="Text", '
                'IsParameterQueryRequired=true]\n\tlineageTag: a\n\n'
                'expression Partagee =\n\t\tlet\n\t\t    Source = Sql.Database(Serveur, "ventes")\n'
                '\t\tin\n\t\t    Source\n\tlineageTag: b\n', encoding="utf-8")
manquant = str(copie / "disparu.xlsx")
t = MODELE / "definition" / "tables" / "zz_test.tmdl"
t.write_text("table zz_test\n\tlineageTag: z\n\n\tpartition zz_test = m\n\t\tmode: import\n"
             "\t\tsource =\n\t\t\t\tlet\n\t\t\t\t    Source = Excel.Workbook(File.Contents(\""
             + manquant + "\"), null, true)\n\t\t\t\tin\n\t\t\t\t    Source\n", encoding="utf-8")
res = lg.scan_projet(PBIP)
check("le paramètre M est lu", res["parametres"] == {"Serveur": "srv-prod"})
part = [l for l in res["lignes"] if l["table"] == lg.EXPRESSIONS]
check("une requête partagée montre la valeur de son paramètre",
      part and part[0]["detail1"] == "Serveur = srv-prod" and part[0]["detail2"] == "ventes")
check("le paramètre lui-même n'est pas une source",
      not any(l["partition"] == "Serveur" for l in res["lignes"]))
check("un fichier local disparu est repéré",
      any(l["detail1"] == manquant for l in res["lignes"])
      and lg.chemin_local(manquant) is not None and not Path(manquant).exists())
check("un chemin réseau n'est pas testé", lg.chemin_local("\\\\srv\\partage\\x.xlsx") is None)

# une requête qui en lit une autre : la chaîne ne se coupe pas
chaine_m = copie / "chaine_m" / "M.SemanticModel" / "definition"
(chaine_m / "tables").mkdir(parents=True)
(chaine_m / "expressions.tmdl").write_text(
    'expression Brut =\n\t\tlet\n\t\t    Source = Sql.Database("srv", "db")\n\t\tin\n'
    '\t\t    Source\n\tlineageTag: a\n\n'
    'expression Propre =\n\t\tlet\n\t\t    Source = Brut,\n'
    '\t\t    F = Table.SelectRows(Source, each true)\n\t\tin\n\t\t    F\n\tlineageTag: b\n\n'
    'expression fnCharger =\n\t\t(x) => let\n\t\t    Source = Csv.Document(File.Contents('
    '"c:\\\\d\\\\" & x))\n\t\tin\n\t\t    Source\n\tlineageTag: c\n', encoding="utf-8")
for nom_t, m_t in (("Ventes", "Propre"), ("Stock", 'fnCharger("stock.csv")')):
    (chaine_m / "tables" / f"{nom_t}.tmdl").write_text(
        f"table {nom_t}\n\tlineageTag: z\n\n\tpartition {nom_t} = m\n\t\tmode: import\n"
        f"\t\tsource =\n\t\t\t\tlet\n\t\t\t\t    Source = {m_t}\n\t\t\t\tin\n"
        "\t\t\t\t    Source\n", encoding="utf-8")
lignes_m, _p = lg.scan_model(chaine_m.parent)
par_nom = {lg.nom_noeud(l): l for l in lignes_m}
check("une requête partagée sans connecteur reste dans le lineage",
      "Propre" in par_nom and par_nom["Propre"]["lit"] == ["Brut"]
      and par_nom["Propre"]["genre"] == lg.AUCUN)
check("Ventes lit Propre, qui lit Brut : Sql.Database est au bout",
      par_nom["Ventes"]["lit"] == ["Propre"]
      and lg.sources_au_bout(lignes_m).get("Ventes") == ["Brut"])
check("appeler une requête-fonction, c'est la lire", par_nom["Stock"]["lit"] == ["fnCharger"])
check("une fonction de M (Table.SelectRows) n'est pas une requête",
      "Table" not in par_nom["Propre"]["lit"] and "SelectRows" not in par_nom["Propre"]["lit"])
shutil.rmtree(chaine_m.parents[1])

live = copie / "live"
(live / "Live.Report").mkdir(parents=True)
(live / "Live.pbip").write_text(json.dumps({"artifacts": [{"report": {"path": "Live.Report"}}]}),
                                encoding="utf-8")
(live / "Live.Report" / "definition.pbir").write_text(json.dumps({"datasetReference": {
    "byConnection": {"connectionString": "Data Source=powerbi://api/x;Initial Catalog=Ventes",
                     "pbiModelDatabaseName": "Ventes"}}}), encoding="utf-8")
rl = lg.scan_projet(live / "Live.pbip")
check("connexion live : dite, avec sa chaîne",
      rl["live"].startswith("Data Source=") and rl["modele"] == "Ventes"
      and rl["lignes"][0]["genre"] == lg.LIVE)

# ---------------------------------------------------------------------------
print("4. l'onglet")
from qtpy.QtCore import Qt                                       # noqa: E402
from qtpy.QtWidgets import QApplication, QFileDialog              # noqa: E402
app = QApplication.instance() or QApplication([])
from core.project import Project                                 # noqa: E402
import tabs.tab_lineage as tl                                    # noqa: E402

tab = tl.LineageTab()
tab.set_project(Project(PBIP))
check("analyse différée tant que l'onglet n'est pas visible", tab.arbre.topLevelItemCount() == 0)
tab.show()
app.processEvents()
rangs_vus = [tab.arbre.topLevelItem(i) for i in range(tab.arbre.topLevelItemCount())]


def visibles():
    return [it for it in rangs_vus if not it.isHidden()]


def ligne(table):
    return next(it for it in rangs_vus if it.text(tl.COL_TABLE) == table)


tables_m = {l["table"] for l in tab.lignes() if l["table"] != lg.EXPRESSIONS}
check(f"une liste à plat : une ligne par table et par source ({len(rangs_vus)})",
      all(it.childCount() == 0 for it in rangs_vus)
      and {it.text(tl.COL_TABLE) for it in rangs_vus} >= tables_m)
z = ligne("zz_test")
check("un fichier se lit par son nom, son dossier va dans l'emplacement",
      z.text(tl.COL_SOURCE) == "⚠ disparu.xlsx" and z.text(tl.COL_LIEU) == str(copie)
      and z.text(tl.COL_TYPE) == "Excel")
check("la source disparue est marquée ⚠, et l'avis le dit",
      "introuvable" in tab.lbl_avis.text() and not tab.lbl_avis.isHidden())
td = ligne("TD_KPI")
check("ce que la table prend dans le classeur : son tableau",
      td.text(tl.COL_OBJET) == "Table1 (tableau)")
check("ce que la table prend dans la base ODBC : sa table",
      ligne("steps").text(tl.COL_OBJET) == "steps")
check("une source lue par plusieurs tables le dit au survol",
      "Lue par 2 tables" in td.toolTip(tl.COL_SOURCE))
check("la requête partagée a sa ligne", any("(requête partagée)" in it.text(tl.COL_TABLE)
                                           for it in rangs_vus))
calc = [it for it in rangs_vus if it.text(tl.COL_TYPE) == tl.TYPE_CALCULEE]
check("les tables calculées viennent après les sources",
      calc and rangs_vus.index(calc[0]) > rangs_vus.index(ligne("steps")))
check("le résumé compte sources et tables",
      f"{len(lg.sources(tab.lignes()))} sources" in tab.lbl_resume.text()
      and "calculées" in tab.lbl_resume.text())

cles = [tab.puces.bouton(k) for k in (tl.TOUT, "type:Excel", "type:ODBC", tl.CALCULEES,
                                      tl.MANQUANTS)]
check("une pastille par type, plus Tout, Calculées et Introuvables", all(cles))
tab.puces.choisir("type:ODBC")
check("la pastille ODBC ne garde que les tables ODBC",
      visibles() and all(it.text(tl.COL_TYPE) == "ODBC" for it in visibles()))
tab.puces.choisir(tl.MANQUANTS)
check("la pastille Introuvables ne garde que les fichiers manquants",
      visibles() and all(it.text(tl.COL_SOURCE).startswith("⚠") for it in visibles()))
tab.puces.choisir(tl.TOUT)
tab.ed_filtre.setText("disparu")
check(f"filtre « disparu » : une seule ligne visible ({len(visibles())})",
      [it.text(tl.COL_TABLE) for it in visibles()] == ["zz_test"])
tab.ed_filtre.setText("Odbc.DataSource")
check("le filtre cherche aussi dans le connecteur M",
      visibles() and all(it.text(tl.COL_TYPE) == "ODBC" for it in visibles()))
tab.ed_filtre.setText("")
tab.arbre.sortByColumn(tl.COL_SOURCE, Qt.AscendingOrder)
ordre = [tab.arbre.topLevelItem(i).text(tl.COL_SOURCE).lstrip("⚠ ")
         for i in range(tab.arbre.topLevelItemCount())]
pleins = [o for o in ordre if o]
check("trier par source range ensemble les tables d'une même source, les vides à la fin",
      pleins == sorted(pleins, key=str.lower) and ordre[:len(pleins)] == pleins)

print("5. le lineage dans le modèle")
locf = ligne("Weight LOCF")
check("une table calculée a pour source les tables qu'elle lit",
      set(locf.text(tl.COL_SOURCE).split(", ")) == {"weight obs", "dim_Date"})
check("l'infobulle donne la source de chacune",
      "weight obs : ODBC" in locf.toolTip(tl.COL_SOURCE))
check("weight obs dit qu'elle est reprise par Weight LOCF",
      ligne("weight obs").text(tl.COL_REPRISE) == "Weight LOCF"
      and "La supprimer casserait" in ligne("weight obs").toolTip(tl.COL_REPRISE))
check("une table calculée lue par d'autres le dit aussi",
      "Weight LOCF" in ligne("dim_Date").text(tl.COL_REPRISE))
check("le résumé compte les tables calculées qui en lisent d'autres",
      "lisent d'autres tables" in tab.lbl_resume.text())
tab.ed_filtre.setText("Weight LOCF")
check("le filtre trouve aussi les tables qu'une table calculée reprend",
      {it.text(tl.COL_TABLE) for it in visibles()} >= {"Weight LOCF", "weight obs", "dim_Date"})
tab.ed_filtre.setText("")

sortie = copie / "export.csv"
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(sortie), ""))
tab._exporter()
with sortie.open(encoding="utf-8-sig") as f:
    rangs = list(csv.reader(f, delimiter=";"))
check("export CSV : l'en-tête et une ligne par partition / connecteur",
      rangs[0] == lg.COLONNES_CSV and len(rangs) == len(tab.lignes()) + 1)
check("export CSV : les tables lues par une table calculée",
      any(r[0] == "Weight LOCF" and set(r[-1].split(", ")) == {"weight obs", "dim_Date"}
          for r in rangs))

tab.deleteLater()
rmtree(copie)
print()
print("TOUT OK" if _ok else "DES ECHECS")
sys.exit(0 if _ok else 1)
