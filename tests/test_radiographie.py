# -*- coding: utf-8 -*-
"""Onglet « Radiographie 🩻 » : les KPI, les variations et les visuels d'un
rapport qu'on n'a pas fait.

    py tests\\test_radiographie.py

Vérifie :
  1. la lecture du DAX : commentaires et chaînes ignorés, crochets gardés ;
  2. les familles par le nom : tige commune, casse, premier mot générique ;
  3. le projet de démonstration, PRIVÉ de ce que PBIdouille y met
     (annotations MeasureVariation, measures_config.json) : les six KPI et
     leurs variations se retrouvent quand même, par le DAX seul ;
  4. les visuels : leurs champs lus par la liaison et non par un queryRef
     périmé, une mesure « affichée » via un paramètre de champ et « choisie »
     par un segment, ce qui filtre chaque visuel (filtres du volet, de page,
     segments, interactions coupées), à quoi mène une mesure, les colonnes
     utilisées et où, un champ absent du modèle ;
  5. l'onglet : ses trois vues, filtre, fiches, navigation par les liens ;
  6. rien n'est écrit dans le projet.

Travaille sur une COPIE du projet de démonstration.
"""

from __future__ import annotations

import hashlib
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
PBI = FIT.parent / "PowerBI"
if os.environ.get("PBIDOUILLE_PROJETS", "").strip():
    PBI = Path(os.environ["PBIDOUILLE_PROJETS"].strip())
sys.path.insert(0, str(FIT))
sys.path.insert(0, str(FIT / "bidouille"))
sys.path.insert(0, str(FIT / "bidouille" / "moteurs"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import exiger_projet, reglages_jetables, PROJET_DEMO   # noqa: E402

exiger_projet(PBI, PROJET_DEMO)
reglages_jetables("radiographie")

import radiographie as rg                                        # noqa: E402

PROJ = PROJET_DEMO
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


def empreinte(dossier: Path) -> str:
    h = hashlib.sha1()
    for f in sorted(dossier.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(dossier)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
print("1. la lecture du DAX")
code = rg.code_dax('CALCULATE([A], "[B]") // [C]\n-- [D]\n/* [E] */ + [Taux -- net]')
check("une mesure dans une chaîne ou un commentaire ne compte pas",
      "[a]" in code.lower() and not any(x in code for x in ("[B]", "[C]", "[D]", "[E]")))
check("un nom de mesure qui contient -- survit", "[Taux -- net]" in code)
check("patron : le KPI devient « … », en mot entier",
      rg.patron("Weight YTD 7d avg", "Weight YTD") == "… 7d avg"
      and rg.patron("Weighted", "Weight") == "Weighted")
check("patron : sans tenir compte de la casse",
      rg.patron("lean mass avg", "Lean Mass", "…") == "… avg")

# ---------------------------------------------------------------------------
print("2. les familles par le nom")
f = rg._familles_nom(["Lean Mass (Current)", "lean mass avg", "Lean Mass Δ (1M)",
                      "Lean Mass Δ (12M)", "Recomp rate", "Recomp (1D)",
                      "Total Sales", "Total Cost", "Seule"])
check("« Lean Mass » regroupe les quatre, Δ compris", sorted(f.get("Lean Mass", [])) ==
      sorted(["Lean Mass (Current)", "lean mass avg", "Lean Mass Δ (1M)", "Lean Mass Δ (12M)"]))
check("la casse la plus fréquente l'emporte", "Lean Mass" in f and "lean mass" not in f)
check("« Recomp » : deux mesures suffisent", sorted(f.get("Recomp", [])) ==
      ["Recomp (1D)", "Recomp rate"])
check("« Total » seul ne fait pas une famille",
      not any("Total Sales" in m for m in f.values()))
check("une mesure sans parente reste seule", not any("Seule" in m for m in f.values()))

# ---------------------------------------------------------------------------
print("3. le projet de démonstration, sans ce que PBIdouille y met")
TMP = Path(tempfile.mkdtemp(prefix="pbid_radio_"))
for s in (".SemanticModel", ".Report"):
    shutil.copytree(PBI / (PROJ + s), TMP / (PROJ + s),
                    ignore=shutil.ignore_patterns(".pbi", "cache.abf"))
shutil.copy2(PBI / (PROJ + ".pbip"), TMP / (PROJ + ".pbip"))
retirees = 0
for t in (TMP / (PROJ + ".SemanticModel") / "definition" / "tables").glob("*.tmdl"):
    texte = t.read_text(encoding="utf-8")
    net, n = re.subn(r"^\t\tannotation MeasureVariation = .*\n", "", texte, flags=re.M)
    if n:
        t.write_text(net, encoding="utf-8")
        retirees += n
check("la copie n'a plus d'annotation PBIdouille, ni de config",
      retirees > 50 and not (TMP / "measures_config.json").exists())

avant = empreinte(TMP)
r = rg.analyser(TMP / (PROJ + ".pbip"))
kpis = {k["kpi"]: k for k in r["kpis"]}
attendus = {"Weight", "Body Fat %", "Average Steps", "Total Steps", "Average Sleep Duration"}
check("les cinq KPI du rapport sont des familles DAX",
      attendus <= {k for k, f in kpis.items() if f["genre"] == rg.DAX})
w = {x["nom"]: x for x in kpis["Weight"]["membres"]}
check("Weight YTD 7d avg descend de Weight YTD, patron « … YTD 7d avg »",
      w["Weight YTD 7d avg"]["base"] == "Weight YTD"
      and w["Weight YTD 7d avg"]["patron"] == "… YTD 7d avg"
      and w["Weight YTD 7d avg"]["par"] == rg.DAX)
check("chaque patron courant est trouvé sur au moins cinq KPI",
      all(n >= 5 for p, n in r["patrons"]
          if p in ("… 7d avg", "… YTD", "… PY")))
check("les KPI sont triés par nombre de visuels",
      [k["visuels"] for k in r["kpis"]] == sorted((k["visuels"] for k in r["kpis"]),
                                                   reverse=True))
check("Weight YTD utilise [Weight], et [Weight] le sait",
      "Weight" in r["uses"]["Weight YTD"] and "Weight YTD" in r["used_by"]["Weight"])
check("le DAX est gardé tel qu'écrit, sur ses lignes",
      "\n" in r["mesures"]["Weight 7d avg"]["dax"])

# ---------------------------------------------------------------------------
print("4. paramètres de champ et visuels")
fp = r["parametres"].get("P_Indicateurs")
check("P_Indicateurs : sa colonne principale et les mesures qu'il propose",
      fp and fp["colonne"] == "P_Indicateurs" and "Weight" in fp["mesures"])
check("Weight se sait proposée par P_Indicateurs", "P_Indicateurs" in r["proposee_par"]["Weight"])
check("une agrégation implicite est lue",
      rg._champ_projection({"Aggregation": {"Expression": {"Column": {
          "Expression": {"SourceRef": {"Entity": "steps"}}, "Property": "value"}},
          "Function": 0}}, set(), {("steps", "value"): {}}, {})["agregat"] == "Somme")
check("un groupe de valeurs (GroupRef) est lu comme une colonne",
      rg.champ_de({"GroupRef": {"Expression": {"SourceRef": {"Entity": "dim_Date"}},
                                "Property": "1 month"}}) == ("dim_Date", "1 month", "Column"))
check("un filtre se lit : valeurs, exclusion, comparaisons",
      rg.decrire_requete({"Where": [{"Condition": {"In": {"Values": [
          [{"Literal": {"Value": "'YoY %'"}}], [{"Literal": {"Value": "2024L"}}]]}}}]})
      == "= YoY %, 2024"
      and rg.decrire_requete({"Where": [{"Condition": {"Not": {"Expression": {"In": {
          "Values": [[{"Literal": {"Value": "'x'"}}]]}}}}}]}) == "≠ x"
      and rg.decrire_requete({"Where": [{"Condition": {"And": {
          "Left": {"Comparison": {"ComparisonKind": 2, "Right": {"Literal": {
              "Value": "datetime'2024-01-01T00:00:00'"}}}},
          "Right": {"Comparison": {"ComparisonKind": 3, "Right": {"Literal": {
              "Value": "datetime'2025-01-01T00:00:00'"}}}}}}}]})
      == "≥ 2024-01-01 et < 2025-01-01")
check("Weight YTD 7d avg mène à Weight, qui lit 'Weight LOCF'[weight]",
      r["bases"]["Weight YTD 7d avg"] == ["Weight"]
      and ("Weight LOCF", "weight") in r["colonnes"]["Weight"]
      and r["bases"]["Weight"] == [])


def champ_col(table, prop, genre="Column"):
    return {genre: {"Expression": {"SourceRef": {"Entity": table}}, "Property": prop}}


def lire(vj):
    return json.loads(vj.read_text(encoding="utf-8"))


def ecrire(vj, d):
    vj.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def projections_de(d):
    qs = ((d.get("visual") or {}).get("query") or {}).get("queryState") or {}
    return [p for b in qs.values() for p in b.get("projections") or []]


pages_dir = TMP / (PROJ + ".Report") / "definition" / "pages"
vjs = sorted(pages_dir.glob("*/visuals/*/visual.json"))

# 1. un visuel passe par le paramètre de champ, en GARDANT son ancien queryRef :
#    c'est le field qui compte, comme après un renommage dans Desktop
def mesures_projetees(vj):
    # des mesures qui EXISTENT : le visuel au champ cassé doit rester cassé
    return [p for p in projections_de(lire(vj)) if "Measure" in p["field"]
            and p["field"]["Measure"]["Property"] in r["mesures"]]


def a_un_segment(vj):
    return any(lire(x).get("visual", {}).get("visualType") == "slicer"
               for x in vj.parent.parent.glob("*/visual.json"))


cible = next(v for v in vjs if mesures_projetees(v) and a_un_segment(v))
d = lire(cible)
p0 = next(p for p in projections_de(d) if "Measure" in p["field"]
          and p["field"]["Measure"]["Property"] in r["mesures"])
ancien_ref = p0.get("queryRef")
p0["field"] = champ_col("P_Indicateurs", "P_Indicateurs")
p0["queryRef"] = ancien_ref                 # l'ancien queryRef reste, comme dans Desktop
ecrire(cible, d)

# 2. un segment sur le paramètre, avec une sélection
seg = next(v for v in vjs if lire(v).get("visual", {}).get("visualType") == "slicer"
           and v.parent.parent == cible.parent.parent)
d = lire(seg)
projections_de(d)[0]["field"] = champ_col("P_Indicateurs", "P_Indicateurs")
d["visual"].setdefault("objects", {})["general"] = [{"properties": {"filter": {"filter": {
    "Version": 2, "From": [{"Name": "p", "Entity": "P_Indicateurs", "Type": 0}],
    "Where": [{"Condition": {"In": {"Expressions": [], "Values": [
        [{"Literal": {"Value": "'Total Steps'"}}]]}}}]}}}}]
ecrire(seg, d)

# 3. sur cette page : un filtre de page, et l'interaction du segment coupée
#    vers UN autre visuel
page_json = cible.parent.parent.parent / "page.json"
pj = lire(page_json)
autre = next(v for v in sorted((cible.parent.parent).glob("*/visual.json"))
             if v not in (cible, seg) and projections_de(lire(v))
             and lire(v)["visual"].get("visualType") != "slicer")
pj["filterConfig"] = {"filters": [{"name": "f1", "field": champ_col("dim_Date", "Date"),
                                   "type": "Advanced", "filter": {"Version": 2, "Where": [
    {"Condition": {"Comparison": {"ComparisonKind": 2, "Right": {"Literal": {
        "Value": "datetime'2024-01-01T00:00:00'"}}}}}]}}]}
pj["visualInteractions"] = [{"source": lire(seg)["name"], "target": lire(autre)["name"],
                             "type": "NoFilter"}]
ecrire(page_json, pj)

avant = empreinte(TMP)
r = rg.analyser(TMP / (PROJ + ".pbip"))
vis = {(v["page_id"], v["id"]): v for v in r["visuels"]}


def v_de(vj):
    return vis[(vj.parent.parent.parent.name, lire(vj)["name"])]


via = [x for _v, x in r["affichee"]["Total Steps"]]
check("Total Steps est affichée VIA P_Indicateurs, malgré l'ancien queryRef",
      "P_Indicateurs" in via)
check("… et choisie par le segment, sans compter comme affichée par lui",
      any(v["segment"] for v, _ in r["choisie"]["Total Steps"])
      and not any(v["segment"] for v, _ in r["affichee"]["Total Steps"]))
check("la sélection du segment est lue", v_de(seg)["selection"] == "= Total Steps")
check("le segment filtre les visuels de sa page…",
      any(s is v_de(seg) for s in v_de(cible)["segments"]))
check("… sauf celui dont l'interaction est coupée",
      not any(s is v_de(seg) for s in v_de(autre)["segments"]))
filtres_page = next(p for p in r["pages"] if p["id"] == cible.parent.parent.parent.name)["filtres"]
check("le filtre de page est lu",
      [(f["nom"], f["texte"], f["actif"]) for f in filtres_page]
      == [("Date", "avancé : ≥ 2024-01-01", True)])
check("un filtre de visuel est lu (Calcul = YoY %)",
      any(f["actif"] and f["texte"] == "= YoY %" for v in r["visuels"] for f in v["filtres"]))
casses = [(v["libelle"], c["ref"]) for v in r["visuels"] for c in v["champs"]
          if c["genre"] == "colonne" and not c["connue"]]
check("le champ absent du modèle (weight obs.lean mass avg) est signalé, et lui seul",
      [ref for _l, ref in casses] == ["weight obs.lean mass avg"])
check("un visuel sans titre est nommé par son premier champ",
      any(v["libelle"].startswith("Segment · ") for v in r["visuels"]))

cols = {(c["table"], c["nom"]): c for c in r["colonnes_utilisees"]}
date = cols.get(("dim_Date", "Date"))
check("Par colonne : 'dim_Date'[Date] sert au filtre de page, avec sa valeur",
      date and any(u["genre"] == "filtre de page" and "2024-01-01" in u["texte"]
                   for u in date["usages"]))
check("… et aux mesures qui la lisent",
      date and any(u["genre"] == "mesure" for u in date["usages"]))
p_ind = cols.get(("P_Indicateurs", "P_Indicateurs"))
check("la colonne du segment porte sa sélection",
      p_ind and any(u["genre"] == "segment" and u["texte"] == "= Total Steps"
                    for u in p_ind["usages"]))
check("la casse du DAX est ramenée à celle du modèle",
      not any(t == "Weight LOCF" and c == "date" for t, c in cols))
check("la colonne absente du modèle est signalée",
      cols.get(("weight obs", "lean mass avg")) is None
      or not cols[("weight obs", "lean mass avg")]["connue"])

# ---------------------------------------------------------------------------
print("5. l'onglet")
from qtpy.QtWidgets import QApplication                          # noqa: E402
from tabs.tab_radiographie import RadiographieTab                # noqa: E402
from core.project import Project                                 # noqa: E402

qa = QApplication.instance() or QApplication([])
tab = RadiographieTab()
tab.set_project(Project(TMP / (PROJ + ".pbip")))
check("l'analyse attend que l'onglet soit visible", not tab.res)
tab.resize(1200, 700)
tab.show()
qa.processEvents()
ensemble = tab.fiche.toPlainText()
check("sans choix, la fiche est la vue d'ensemble du rapport, page par page",
      "Vue d'ensemble du rapport" in ensemble and "KPI affichés" in ensemble
      and all(pg["nom"] in ensemble for pg in r["pages"]))
check("la vue d'ensemble dit ce que chaque visuel affiche, et par quoi",
      all(x in ensemble for x in ("Visuel", "Affiche", "Par"))
      and any(v["libelle"] in ensemble for v in r["visuels"] if not v["segment"]))
a = tab.arbre_kpi
tops = [a.topLevelItem(i).text(0) for i in range(a.topLevelItemCount())]
check("vue Par KPI : les familles, puis briques, jamais affichées et patrons",
      "Weight" in tops and any(t.startswith("Briques") for t in tops)
      and any(t.startswith("Variations repérées") for t in tops))
tab.aller_a("mesure", "Weight YTD")
cur = a.currentItem()
check("aller à une mesure la sélectionne dans sa famille",
      cur is not None and cur.text(0) == "Weight YTD" and cur.parent().text(0) == "Weight")
fiche = tab.fiche.toPlainText()
check("sa fiche : variation de Weight, ce qu'elle utilise, son DAX",
      "Variation de Weight" in fiche and "Utilise" in fiche and "DATESYTD" in fiche)
n_liens = len(tab._liens)
from qtpy.QtCore import QUrl                                      # noqa: E402
i_weight = next(i for i, l in enumerate(tab._liens) if l == ("mesure", "Weight"))
tab._lien(QUrl(f"#{i_weight}"))
check("un lien de la fiche mène à la mesure", a.currentItem().text(0) == "Weight"
      and n_liens > 0)
tab.ed_filtre.setText("sleep duration ytd 7d")
visibles = []


def parcourir(it):
    if not it.isHidden():
        visibles.append(it.text(0))
    for i in range(it.childCount()):
        parcourir(it.child(i))


for i in range(a.topLevelItemCount()):
    parcourir(a.topLevelItem(i))
check("le filtre ne garde que ce qui correspond, et ses parents",
      "Average Sleep Duration YTD 7d avg" in visibles and "Weight" not in visibles)
tab.ed_filtre.clear()
p = tab.arbre_pages
check("vue Par page : une ligne par page", p.topLevelItemCount() == len(r["pages"]))
ac = tab.arbre_cols
tables_vues = [ac.topLevelItem(i).text(0) for i in range(ac.topLevelItemCount())]
check("vue Par colonne : une ligne par table utilisée",
      tables_vues == sorted({c["table"] for c in r["colonnes_utilisees"]}, key=str.lower))
dim = ac.topLevelItem(tables_vues.index("dim_Date"))
ligne_date = next(dim.child(i) for i in range(dim.childCount()) if dim.child(i).text(0) == "Date")
ac.setCurrentItem(ligne_date)
check("la fiche d'une colonne liste ses segments, filtres et mesures",
      all(x in tab.fiche.toPlainText() for x in ("Filtres de page", "Mesures qui la lisent")))
page_lien = next((i for i, l in enumerate(tab._liens) if l[0] == "page"), None)
from qtpy.QtCore import QUrl as _QUrl                              # noqa: E402
if page_lien is not None:
    tab._lien(_QUrl(f"#{page_lien}"))
check("un lien vers une page ouvre sa fiche", "KPI affichés" in tab.fiche.toPlainText())
visuel = next(v for v in r["visuels"] if any(c["genre"] == "parametre" for c in v["champs"]))
tab.aller_a("visuel", (visuel["page_id"], visuel["id"]))
check("la fiche d'un visuel nomme son paramètre de champ",
      "paramètre de champ" in tab.fiche.toPlainText() and tab.vues.currentWidget() is p)

# les rôles, les familles et les pastilles « Afficher »
check("chaque champ d'un visuel a son rôle dans le visuel",
      all("role" in c for v in r["visuels"] for c in v["champs"])
      and rg.libelle_role("Category") == "Axe" and rg.libelle_role("Values", True) == "Champ")
riche = max((v for v in r["visuels"] if not v["segment"]),
            key=lambda v: sum(c["genre"] == "mesure" for c in v["champs"]))
it_riche = tab._item_visuel[(riche["page_id"], riche["id"])]


def descendants(it):
    for i in range(it.childCount()):
        yield it.child(i)
        yield from descendants(it.child(i))


textes = [d.text(0) for d in descendants(it_riche)]
check("les champs se rangent par rôle (Axe, Valeurs…)",
      any(t.startswith(("Axe", "Valeurs", "Lignes")) for t in textes))
n_mes = sum(c["genre"] == "mesure" for c in riche["champs"])
familles = [d for d in descendants(it_riche) if d.text(0).endswith(" mesures")
            and " · " in d.text(0)]
check(f"les variations d'un KPI tiennent sur une ligne à déplier ({n_mes} mesures)",
      familles and familles[0].childCount() >= 2 and not familles[0].isExpanded())
tab.aller_a("visuel", (riche["page_id"], riche["id"]))
check("la fiche du visuel : ses rôles et d'où viennent ses chiffres",
      "D'où viennent les chiffres" in tab.fiche.toPlainText())

tab.puces_pages.bouton("mesures").setChecked(False)
tab.puces_pages.bouton("colonnes").setChecked(False)
from tabs.tab_radiographie import CATEGORIE                       # noqa: E402


def vu(it):
    """Visible à l'écran : lui et tous ses parents."""
    while it is not None:
        if it.isHidden():
            return False
        it = it.parent()
    return True


cats = {d.data(0, CATEGORIE) for d in descendants(it_riche) if vu(d)}
check("pastilles Mesures et Colonnes éteintes : il ne reste que les filtres",
      cats <= {"filtres"} and not it_riche.isHidden())
tab.puces_pages.bouton("segments").setChecked(False)
segs = [tab._item_visuel[(v["page_id"], v["id"])] for v in r["visuels"] if v["segment"]]
check("pastille Segments éteinte : les segments disparaissent de la liste",
      segs and not any(vu(s) for s in segs))
for k in ("mesures", "colonnes", "segments"):
    tab.puces_pages.bouton(k).setChecked(True)
check("tout rallumé : tout revient", vu(it_riche) and all(vu(s) for s in segs))
tab.vues.setCurrentWidget(ac)
check("chaque vue a ses pastilles : Par colonne montre les siennes",
      tab.puces_cols.isVisibleTo(tab) and not tab.puces_pages.isVisibleTo(tab))
tab.puces_cols.bouton("mesures").setChecked(False)
lignes_date = [d for d in descendants(dim) if d.text(0) == "Date"]
check("Par colonne, pastille Mesures éteinte : une colonne lue seulement par des "
      "mesures disparaît", lignes_date and all(not vu(d) for d in lignes_date)
      == all(u["genre"] == "mesure" for c in r["colonnes_utilisees"]
             if c["table"] == "dim_Date" and c["nom"] == "Date" for u in c["usages"]))
tab.puces_cols.bouton("mesures").setChecked(True)

# la lisibilité : bandeaux, rôles en gris, Déplier qui garde les familles fermées
from tabs.tab_radiographie import PREFIXE, SUFFIXE                # noqa: E402
tab.vues.setCurrentWidget(p)
page1 = p.topLevelItem(p.topLevelItemCount() - len(r["pages"]))
check("chaque page est un bandeau sur toute la largeur",
      all(page1.background(c).color().name() != "#000000" for c in range(4))
      and page1.font(0).pointSize() > p.font().pointSize())
check("le rôle d'un champ seul est en gris devant lui (« Axe : »)",
      any(d.data(0, PREFIXE) and d.text(0).startswith(d.data(0, PREFIXE))
          for d in descendants(it_riche)))
check("le compte d'une famille est en gris derrière elle",
      familles and familles[0].data(0, SUFFIXE) == familles[0].text(0)[len(
          familles[0].text(0).split(" · ")[0]):])
check("un visuel est en gras, son type en gris",
      it_riche.font(0).bold() and it_riche.data(0, PREFIXE) == riche["libelle_type"] + " · ")
tab._deplier(True)
check("Déplier ouvre les visuels mais laisse les familles fermées",
      it_riche.isExpanded() and familles and not familles[0].isExpanded())
tab._deplier(False)
check("Replier revient aux pages", not it_riche.isExpanded() and page1.isExpanded())
enfants = [familles[0].child(i) for i in range(familles[0].childCount())]
check("dans une famille, Mène à et Table ne se répètent pas sous la famille",
      all(e.text(1) != familles[0].text(1) or not e.text(1) for e in enfants))
tab.btn_ensemble.click()
check("le bouton Vue d'ensemble y ramène la fiche",
      "Vue d'ensemble du rapport" in tab.fiche.toPlainText())

# Par source : d'où vient chaque table, et ce qui en dépend
import lineage as lg                                              # noqa: E402
import tabs.tab_lineage as tl                                     # noqa: E402
vs = tab.vue_sources
check("la vue Par source est une vue de la Radiographie",
      tab.vues.indexOf(vs) >= 0 and tab.vues.tabText(tab.vues.indexOf(vs)) == "Par source")
imp = tab.impacts
cc = lg.colonnes_calculees(tab.lineage["modele_dir"])
check(f"les colonnes calculées du modèle sont lues ({len(cc)})",
      cc and all(c["dax"] for c in cc))
check("weight obs : reprise par Weight LOCF, des mesures et des visuels en dépendent",
      imp["weight obs"]["tables_calculees"] == ["Weight LOCF"]
      and imp["weight obs"]["mesures_directes"] and imp["weight obs"]["visuels"]
      and set(imp["weight obs"]["mesures_directes"]) <= set(imp["weight obs"]["mesures"]))
check("une table calculée vit avec ses colonnes calculées",
      len(imp["dim_Date"]["colonnes_calculees"]) == sum(1 for c in cc if c["table"] == "dim_Date"))
tot = rg.cumuler(imp, ["sleep", "steps", "weight obs"])
check("toute une source : chaque élément compté une fois",
      len(tot["mesures"]) == len(set(tot["mesures"]))
      and len(tot["visuels"]) <= sum(len(imp[t]["visuels"]) for t in ("sleep", "steps",
                                                                         "weight obs")))
tab.vues.setCurrentWidget(vs)
qa.processEvents()
check("Par source : ni pastilles Afficher ni Déplier",
      not tab.puces_pages.isVisibleTo(tab) and not tab.btn_deplier.isVisibleTo(tab))
lignes_vs = [vs.arbre.topLevelItem(i) for i in range(vs.arbre.topLevelItemCount())]
wo = next(it for it in lignes_vs if it.text(tl.COL_TABLE) == "weight obs")
check("les comptes : mesures et visuels de weight obs",
      wo.text(tl.COL_MESURES) == str(len(imp["weight obs"]["mesures"]))
      and wo.text(tl.COL_VISUELS) == str(len(imp["weight obs"]["visuels"]))
      and not vs.arbre.isColumnHidden(tl.COL_MESURES))
vs.arbre.setCurrentItem(wo)
fiche = tab.fiche.toPlainText()
check("la fiche d'une table : ce qui en dépend, visuels d'abord, et toute sa source",
      "Ce qui en dépend" in fiche and "Visuels" in fiche and "Weight LOCF" in fiche
      and fiche.index("Visuels") < fiche.index("Mesures") and "Toute la source" in fiche)
tab.ed_filtre.setText("weight obs")
check("le filtre de la Radiographie filtre aussi la vue Par source",
      not wo.isHidden() and any(it.isHidden() for it in lignes_vs))
tab.ed_filtre.clear()

# l'ordre des vues, du plus large au plus fin
check("les vues : Lignage, Par source, Par page, Par colonne, Par KPI",
      [tab.vues.tabText(i) for i in range(tab.vues.count())]
      == ["Lignage", "Par source", "Par page", "Par colonne", "Par KPI"])

# Par colonne : ce qui dépend de chaque colonne
deps = rg.dependants_colonnes(r)
i_date = next(i for i, c in enumerate(r["colonnes_utilisees"])
              if (c["table"], c["nom"]) == ("dim_Date", "Date"))
dd = deps[i_date]
check(f"dim_Date[Date] : {len(dd['mesures_directes'])} mesures la lisent, "
      f"{len(dd['mesures'])} en dépendent",
      dd["mesures_directes"] and len(dd["mesures"]) > len(dd["mesures_directes"])
      and set(dd["mesures_directes"]) <= set(dd["mesures"]))
ligne_d = next(ac.topLevelItem(k).child(j) for k in range(ac.topLevelItemCount())
               for j in range(ac.topLevelItem(k).childCount())
               if ac.topLevelItem(k).child(j).data(0, 256) == ("colonne_rapport", i_date))
check("Par colonne : les comptes de mesures, filtres et visuels",
      ligne_d.text(1) == str(len(dd["mesures"])) and ligne_d.text(3) == str(len(dd["visuels"])))
enfants_d = [ligne_d.child(k).text(0) for k in range(ligne_d.childCount())]
check("102 mesures qui la lisent tiennent sur une ligne repliée, par famille",
      any(t.startswith("Lue par") for t in enfants_d) and len(enfants_d) < 10
      and any(t.startswith("Reprise par") for t in enfants_d))
tab.vues.setCurrentWidget(ac)
ac.setCurrentItem(None)             # déjà choisie plus haut : la re-choisir
ac.setCurrentItem(ligne_d)
fiche_d = tab.fiche.toPlainText()
check("la fiche d'une colonne : le résumé, puis les mesures par famille",
      f"{len(dd['mesures'])} mesure(s)" in fiche_d and "Mesures qui les reprennent" in fiche_d)

# la fiche se replie : les premières lignes, un lien pour le reste
plis = [i for i, l in enumerate(tab._liens) if l[0] == "plier"]
check("une longue liste de la fiche ne montre que ses premières lignes",
      plis and "afficher les" in fiche_d)
longueur_pliee = len(fiche_d)
tab._lien(QUrl(f"#{plis[0]}"))
check("un clic l'affiche en entier, au même endroit",
      len(tab.fiche.toPlainText()) > longueur_pliee and "replier" in tab.fiche.toPlainText())
tab.aller_a("mesure", "Weight YTD")
check("changer de fiche replie tout", "replier" not in tab.fiche.toPlainText()
      or all(l[0] != "plier" for l in tab._liens))
check("la vue Par KPI dit comment elle range ses familles",
      tab.lbl_kpi.isVisibleTo(tab) and "DAX" in tab.lbl_kpi.text())

# Lignage : de la source au visuel
import lignage as lgn                                             # noqa: E402
g = tab.graphe
N = g["noeuds"]
src = next(n for n in N if n[0] == "source" and "FitbitDB" in str(n[1]))
courbes = next(n for n, x in N.items() if x["libelle"].startswith("Courbes"))
aval = lgn.chaine_sens(g["liens"], src, amont=False)
check("de la source ODBC au visuel : weight obs, Weight LOCF, la famille Body Fat %",
      {("table", "weight obs"), ("table", "Weight LOCF"), ("mesures", "Body Fat %"),
       courbes} <= aval)
check("en amont du visuel : ses sources, ses filtres et ses segments",
      src in lgn.chaine_sens(g["liens"], courbes, amont=True)
      and any(N[n]["genre"] in ("filtre", "segment")
              for n in lgn.chaine_sens(g["liens"], courbes, amont=True)))
ordre_b = {b: i for i, b in enumerate(lgn.BANDES)}
check("les colonnes suivent les bandes, de la source au visuel",
      all(N[a]["couche"] < N[b]["couche"] for a, b in g["liens"]
          if ordre_b[N[a]["bande"]] < ordre_b[N[b]["bande"]]))
check("une table calculée qui en lit une autre se place plus loin",
      N[("table", "Weight LOCF")]["couche"] > N[("table", "dim_Date")]["couche"])
check("ce qui ne mène à aucun visuel est marqué : TD_Indicateurs, Switch KPI",
      not N[("table", "TD_Indicateurs")]["utilise"] and not N[("mesures", "Switch KPI")]["utilise"]
      and N[("table", "weight obs")]["utilise"])
vl = tab.vue_lignage
tab.vues.setCurrentWidget(vl)
qa.processEvents()
check("la vue Lignage dessine ce qui est utilisé",
      set(vl.boites) == {n for n, x in N.items() if x["utilise"]})
vl.cb_tout.setChecked(True)
check("la case montre aussi le reste", set(vl.boites) == set(N))
vl.cb_tout.setChecked(False)
vl.choisir(src)
qa.processEvents()
allumees = {n for n, b in vl.boites.items() if b.opacity() == 1}
check("choisir la source allume sa chaîne et éteint le reste",
      allumees == lgn.chaine(g["liens"], src) & set(vl.boites) and len(allumees) < len(vl.boites))
fiche_l = tab.fiche.toPlainText()
check("la fiche d'une source : ce à quoi elle mène, et tout ce qui en dépend",
      "Mène à" in fiche_l and "Lue par 3 table(s)" in fiche_l and "Visuels" in fiche_l)
vl.cb_chaine.setChecked(True)
check("Seulement la chaîne : le graphe ne garde qu'elle",
      set(vl.boites) == lgn.chaine(g["liens"], src) & {n for n, x in N.items() if x["utilise"]})
vl.choisir(None)
check("un clic dans le vide efface le choix et redessine tout",
      not vl.cb_chaine.isChecked() and len(vl.boites) == sum(x["utilise"] for x in N.values()))

# l'amont en vert, l'aval en orange, et le sens qui ne garde que l'un
import tabs.vue_lignage as tvl                                    # noqa: E402
fam = ("mesures", "Average Sleep Duration")
vl.choisir(fam)
couleurs = {(a, b): t.pen().color().name().lower() for a, b, t, _o in vl.liens}
check("les liens de l'amont sont verts, ceux de l'aval orange",
      couleurs[(("table", "sleep"), fam)] == tvl.AMONT_C.lower()
      and any(c == tvl.AVAL_C.lower() for (a, b), c in couleurs.items() if a == fam))
vl.puces_sens.choisir("amont")
allumees = {n for n, b in vl.boites.items() if b.opacity() == 1}
check("Sens Amont : seulement ce dont la famille vient",
      allumees == lgn.chaine_sens(g["liens"], fam, amont=True) & set(vl.boites)
      and courbes not in allumees)
lignes_amont = vl.lignes_export()
check("l'export suit le sens : ni aval, mais la famille mesure par mesure",
      {x["Sens"] for x in lignes_amont} == {"amont", "choisi"}
      and sum(x["Sens"] == "choisi" for x in lignes_amont) == len(N[fam]["membres"]))
vl.puces_sens.choisir("deux")
lignes_deux = vl.lignes_export()
sortie = TMP / "chaine.csv"
lgn.ecrire_csv(lignes_deux, sortie)
import csv as _csv                                                # noqa: E402
with sortie.open(encoding="utf-8-sig") as f:
    rangs = list(_csv.reader(f, delimiter=";"))
sortie.unlink()
check("l'export CSV : une colonne Sens (amont, choisi, aval) et la distance",
      rangs[0] == lgn.COLONNES_EXPORT and {r[0] for r in rangs[1:]} == {"amont", "choisi", "aval"}
      and all(r[1].isdigit() for r in rangs[1:]))

# un lien qui saute une colonne passe entre les boîtes, pas à travers
lien = next(o for a, b, t, o in vl.liens if (a, b) == (("table", "sleep"), fam))
pts = vl._trajet(("table", "sleep"), fam, {d: (bx.pos().x(), bx.pos().y())
                                           for d, bx in vl.boites.items()})
sautees = range(vl._col_de[("table", "sleep")] + 1, vl._col_de[fam])
check("un lien qui saute une colonne la traverse par un passage libre",
      len(pts) == 2 + 2 * len(sautees) and sautees
      and all(not any(debut < pts[1 + 2 * j][1] < fin for debut, fin in vl._cols[k][1])
              for j, k in enumerate(sautees)))

# une bande se replie en une boîte, et ses liens passent par elle
vl.choisir(None)
vl.basculer_bande("filtre")
check("une bande repliée tient en une boîte",
      ("bande", "filtre") in vl.boites
      and not any(N[d]["bande"] == "filtre" for d in vl.boites if d in N)
      and any(b == ("bande", "filtre") or a == ("bande", "filtre") for a, b, _t, _o in vl.liens))
vl._clic(vl.boites[("bande", "filtre")])
check("un clic sur la boîte d'une bande la déplie", ("bande", "filtre") not in vl.boites)

# de haut en bas : les sources au-dessus des visuels
vl.puces_dispo.choisir("vertical")
y_src = vl.boites[src].pos().y()
y_vis = vl.boites[courbes].pos().y()
check("Haut → bas : les bandes en rangées, les sources en haut", y_src < y_vis)
vl.puces_dispo.choisir("horizontal")

# la fiche se ferme, et le choix est retenu
tab._montrer_fiche(False)
from core.project import lire_reglage                             # noqa: E402
check("la fiche se cache, et le réglage le retient",
      not tab.fiche.isVisibleTo(tab) and lire_reglage("radiographie_fiche") == "0"
      and tab.btn_fiche.text() == "Afficher la fiche")
tab.btn_ensemble.click()
check("Vue d'ensemble rouvre la fiche", tab.fiche.isVisibleTo(tab))
tab.close()

# ---------------------------------------------------------------------------
print("6. lecture seule")
check("rien n'a été écrit dans le projet", empreinte(TMP) == avant)

rmtree(TMP)
print("\nTOUT OK" if _ok else "\nDES ECHECS")
sys.exit(0 if _ok else 1)
