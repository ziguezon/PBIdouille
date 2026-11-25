# -*- coding: utf-8 -*-
"""Mesures → « Arbre des mesures » : ce que la génération produira, en arbre.

    py tests\\test_arbre_mesures.py

Vérifie :
  1. le générateur rend l'arbre : base -> variations, base -> mesure de
     branche -> variations en branche, KPI -> cible racine -> ses variations ;
  2. le marqueur des paramètres de champ suit les tables ET leurs filtres ;
  3. l'état (nouvelle / modifiée / inchangée) est celui que « Générer »
     annoncerait, et l'aperçu n'écrit rien ;
  4. la vue : un KPI par racine, le marqueur ◆, le filtre texte, le filtre
     « ◆ seulement », et le config EN MÉMOIRE (sans enregistrer) ;
  5. les attributs de chaque nœud (DAX développé, format, dossier) et la
     FICHE de la mesure choisie ;
  6. le rangement « par variation », mémorisé ;
  7. Variations → aperçu des noms : un nom se déplie sur son DAX, celui du
     formulaire EN COURS (pas encore committé ni enregistré).

Travaille sur une COPIE du projet de démonstration, magasin de réglages jetable.
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
# les projets Power BI vivent HORS de l'outil (cf. moteurs/chemins.py)
PBI = FIT.parent / "PowerBI"
if os.environ.get("PBIDOUILLE_PROJETS", "").strip():
    PBI = Path(os.environ["PBIDOUILLE_PROJETS"].strip())
sys.path.insert(0, str(FIT))
sys.path.insert(0, str(FIT / "bidouille"))
sys.path.insert(0, str(FIT / "bidouille" / "moteurs"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import (exiger_projet, ajouter_cibles, reglages_jetables,   # noqa: E402
                      PROJET_DEMO)

exiger_projet(PBI, PROJET_DEMO, "measures_config.json")
reglages_jetables("arbre")

import generate_measures as gm                                   # noqa: E402

PROJ = PROJET_DEMO
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


copie = Path(tempfile.gettempdir()) / "pbid_arbre_mesures"
rmtree(copie)
copie.mkdir(parents=True)
for s in (".SemanticModel", ".Report"):
    shutil.copytree(PBI / (PROJ + s), copie / (PROJ + s))
for f in (PROJ + ".pbip", "TD_Indicateurs.xlsx"):
    if (PBI / f).exists():
        shutil.copy2(PBI / f, copie / f)
MODELE = copie / (PROJ + ".SemanticModel")

conf = json.loads((PBI / "measures_config.json").read_text(encoding="utf-8"))
_, bases = gm.read_measures(MODELE, conf)
K = bases[0]
ajouter_cibles(MODELE, [K])
conf["kpiMeasureFolders"] = [{"folder": "_cibles", "calcul": "Cible"}]
branches = list((conf.get("branches") or {}).keys())
B = branches[0]
vars_fp = [v for v, t in conf["variations"].items()
           if t.get("inFieldParameter") and v not in branches]
V = vars_fp[0]
# la démo n'applique aucune variation aux cibles : on en donne une
conf["variations"][V]["appliesToCibles"] = True
# et une mesure « ICP choisi », pour que son rangement soit testé quel que
# soit l'état du projet de démonstration
conf["variations"][V]["selectedKpiMeasure"] = True
conf["fieldParameter"] = dict(conf["fieldParameter"])
conf["fieldParameter"]["tables"] = [
    {"name": "P_tout"},
    {"name": "P_sans_" + V.replace(" ", "_"), "excludeVariations": [V]},
]
for k in ("tableNames", "tableNamesByKpi", "tableNamesKpiBase"):
    conf["fieldParameter"].pop(k, None)
(copie / "measures_config.json").write_text(json.dumps(conf, ensure_ascii=False, indent=2),
                                            encoding="utf-8")

# ---------------------------------------------------------------------------
print("1. le générateur rend l'arbre")
mtimes = {p: p.stat().st_mtime_ns for p in MODELE.rglob("*") if p.is_file()}
st = gm.generate(MODELE, json.loads(json.dumps(conf)), dry_run=True, log=lambda *a: None)
check("l'aperçu n'a rien écrit dans le modèle",
      {p: p.stat().st_mtime_ns for p in MODELE.rglob("*") if p.is_file()} == mtimes)
arbre = {n["name"]: n for n in st["arbre"]}
aiguillages = [n for n in st["arbre"] if n["type"] == "aiguillage"]
racines = [n for n in st["arbre"] if n["parent"] is None and n["type"] != "aiguillage"]
check(f"une racine par KPI ({len(bases)})",
      sorted(n["name"] for n in racines) == sorted(bases)
      and all(n["type"] == "base" for n in racines))
check(f"les mesures « ICP choisi » n'ont pas de KPI parent ({len(aiguillages)})",
      aiguillages and all(n["parent"] is None for n in aiguillages))
var_k = [n for n in st["arbre"] if n["parent"] == K and n["type"] == "variation"]
check(f"{K} -> ses variations", var_k and all(n["variation"] for n in var_k))
br_k = [n for n in st["arbre"] if n["parent"] == K and n["type"] == "branche"]
check(f"{K} -> sa mesure de branche {B}", len(br_k) >= 1 and br_k[0]["branche"] == B)
sous_br = [n for n in st["arbre"] if n["parent"] == br_k[0]["name"]]
check(f"la mesure de branche -> ses variations en branche ({len(sous_br)})",
      sous_br and all(n["branche"] == B and n["type"] == "variation" for n in sous_br))
# celle de K : le projet de démonstration peut avoir les siennes
cible = [n for n in st["arbre"] if n["type"] == "cible" and n["kpi"] == K]
check(f"la cible racine est sous son KPI ({K})",
      len(cible) == 1 and cible[0]["parent"] == K)
check("… et les variations de la cible sont sous elle",
      any(n["parent"] == cible[0]["name"] for n in st["arbre"]))
check("chaque parent existe dans l'arbre",
      all(n["parent"] is None or n["parent"] in arbre for n in st["arbre"]))

print("2. le marqueur suit les tables et leurs filtres")
check("la base est dans les deux tables", arbre[K]["tables"] == ["P_tout", conf["fieldParameter"]["tables"][1]["name"]])
nv = next(n for n in var_k if n["variation"] == V)
check(f"« {nv['name']} » seulement dans P_tout (l'autre l'écarte)", nv["tables"] == ["P_tout"])
hors = [n for n in st["arbre"] if not n["tables"] and n["type"] != "aiguillage"]
check(f"sans table = variation hors paramètre ({len(hors)} : sparkline, CF…)",
      hors and all(n["type"] == "variation"
                   and not conf["variations"][n["variation"]].get("inFieldParameter")
                   for n in hors))

print("3. l'état est celui de « Générer »")
check("nouvelle / modifiée / inchangée, ou « à la main » pour les racines",
      {n["etat"] for n in st["arbre"]} <= {"nouvelle", "modifiée", "inchangée", "à la main"}
      and all(n["etat"] == "à la main" for n in st["arbre"] if n["type"] in ("base", "cible")))
check("les comptes collent à ceux du générateur",
      sum(n["etat"] == "nouvelle" for n in st["arbre"]) == len(st["created"])
      and sum(n["etat"] == "modifiée" for n in st["arbre"]) == len(st["updated"]))
gm.generate(MODELE, json.loads(json.dumps(conf)), dry_run=False, remove_orphans=True,
            log=lambda *a: None)
st2 = gm.generate(MODELE, json.loads(json.dumps(conf)), dry_run=True, log=lambda *a: None)
check("après une vraie génération, tout ce qui est généré est « inchangée »",
      all(n["etat"] == "inchangée" for n in st2["arbre"]
          if n["type"] in ("variation", "branche")))

# ---------------------------------------------------------------------------
print("4. la vue")
from qtpy.QtWidgets import QApplication                          # noqa: E402
app = QApplication.instance() or QApplication([])
import tabs.tab_config as tc                                     # noqa: E402
from tabs.arbre_mesures import MARQUEUR, ROLE_GROUPE                         # noqa: E402
from core.project import Project                                 # noqa: E402

ct = tc.ConfigTab()
ct.set_project(Project(copie / (PROJ + ".pbip")))
ct.inner.setCurrentIndex(tc.IDX_ARBRE)
app.processEvents()
vue = ct.arbre_mesures
check("l'onglet s'appelle « Arbre des mesures »",
      ct.inner.tabText(tc.IDX_ARBRE) == "Arbre des mesures")
def racines_vue():
    return [vue.arbre.topLevelItem(i) for i in range(vue.arbre.topLevelItemCount())]


def un_kpi_par_racine():
    """Un KPI par racine, plus UN groupe qui tient les mesures « ICP choisi »."""
    rs = racines_vue()
    kpis = [r for r in rs if not r.data(0, ROLE_GROUPE)]
    groupes = [r for r in rs if r.data(0, ROLE_GROUPE)]
    return (sorted(r.text(0) for r in kpis) == sorted(bases)
            and len(groupes) == 1
            and sorted(groupes[0].child(i).text(0) for i in range(groupes[0].childCount()))
            == sorted(n["name"] for n in aiguillages))


check(f"un KPI par racine, et un groupe « ICP choisi » ({vue.arbre.topLevelItemCount()})",
      un_kpi_par_racine())
it_k = vue.element(K)
check("la base porte le marqueur ◆", it_k is not None and it_k.text(1).startswith(MARQUEUR))
check("… et l'infobulle dit dans quelles tables", "P_tout" in it_k.toolTip(1))
it_br = vue.element(br_k[0]["name"])
check("la mesure de branche est enfant de son KPI", it_br is not None and it_br.parent() is it_k)
check("le résumé compte les ICP", f"{len(bases)} ICP" in vue.lbl_resume.text())

vue.ed_filtre.setText(B)
visibles = [vue.element(n["name"]) for n in sous_br]
check(f"filtre « {B} » : les variations en branche restent visibles",
      all(not i.isHidden() for i in visibles))
check("… une variation hors branche est cachée",
      next(vue.element(n["name"]) for n in var_k).isHidden())
vue.ed_filtre.setText("")
vue.chk_param.setChecked(True)
check("« ◆ seulement » : plus aucune ligne visible sans marqueur",
      all(vue.element(n["name"]).isHidden() for n in hors) if hors else True)
check("… les mesures marquées restent visibles", not vue.element(nv["name"]).isHidden())
vue.chk_param.setChecked(False)

print("   le config en mémoire, sans enregistrer")
ct._config["variations"][V]["inFieldParameter"] = False
ct._rafraichir_vue()
app.processEvents()
check(f"« {nv['name']} » perd son marqueur aussitôt",
      vue.element(nv["name"]) is not None and vue.element(nv["name"]).text(1) == "")
check("rien n'a été enregistré",
      json.loads((copie / "measures_config.json").read_text(encoding="utf-8"))
      ["variations"][V].get("inFieldParameter") is True)

# ---------------------------------------------------------------------------
print("5. les attributs, et la fiche")
check("chaque mesure a son DAX", all(n.get("dax") for n in st["arbre"]))
check("le DAX d'une variation est DÉVELOPPÉ (plus aucun jeton {…})",
      all("{baseRef}" not in n["dax"] and "{date}" not in n["dax"]
          for n in st["arbre"] if n["type"] != "base"))
check(f"le DAX de la base vient du TMDL, sur ses lignes (« {K} »)",
      arbre[K]["dax"] and "\t\t\t" not in arbre[K]["dax"])
check("format et dossier suivent, pour la base comme pour une variation",
      arbre[K]["dossier"] and nv.get("dossier") and "format" in nv)
sb = [n for n in st["arbre"] if n["branche"] == B and n["type"] == "variation"]
check(f"une variation en {B} dit si elle enveloppe sa variation Réel",
      sb and all(isinstance(n.get("enveloppe"), bool) for n in sb)
      and any(n["enveloppe"] for n in sb))
env = next(n for n in sb if n["enveloppe"])
reel = next(n for n in st["arbre"] if n["variation"] == env["variation"]
            and n["kpi"] == env["kpi"] and not n["branche"] and n["cible"] == env["cible"])
check(f"… et son DAX cite la mesure Réel (« {reel['name']} »)",
      "[" + reel["name"] + "]" in env["dax"])

nom_v = next(n["name"] for n in var_k)
check("rien de choisi : la fiche invite à choisir", not vue.fiche.ed_dax.isVisible()
      and "Choisir" in vue.fiche.lbl_nom.text())


def ct_arbre(nom):
    """Le nœud qu'affiche la vue (config en mémoire)."""
    return {n["name"]: n for n in vue._noeuds}[nom]


check(f"choisir « {nom_v} » : la fiche montre son DAX", vue.choisir(nom_v)
      and vue.fiche.texte_dax() == ct_arbre(nom_v)["dax"])
check("… et ses attributs (format, dossier, paramètres)",
      "dossier" in vue.fiche.lbl_attributs.text()
      and "paramètres" in vue.fiche.lbl_attributs.text())

# ---------------------------------------------------------------------------
print("6. le rangement par variation")
from tabs.arbre_mesures import CLE_RANGEMENT, ROLE_GROUPE        # noqa: E402
from core.project import lire_reglage                             # noqa: E402
vue.cmb_rangement.setCurrentIndex(vue.cmb_rangement.findData("variation"))
app.processEvents()
haut = [vue.arbre.topLevelItem(i) for i in range(vue.arbre.topLevelItemCount())]
check("les racines sont des GROUPES, la 1re tient les mesures écrites à la main",
      haut and all(g.data(0, ROLE_GROUPE) for g in haut)
      and vue.element(K).parent() is haut[0])
it_v = vue.element(nv["name"])
check(f"« {nv['name']} » est dans le groupe « {V} »",
      it_v is not None and it_v.parent().text(0) == V and it_v.parent().parent() is None)
it_b = vue.element(br_k[0]["name"])
check(f"la mesure de branche est dans le groupe « {B} »",
      it_b is not None and it_b.parent().text(0) == B)
it_sb = vue.element(sb[0]["name"])
check(f"une variation en branche est dans « {B} › {sb[0]['variation']} », sous « {B} »",
      it_sb is not None and it_sb.parent().text(0) == B + " › " + sb[0]["variation"]
      and it_sb.parent().parent() is it_b.parent())
check("le groupe compte ses mesures, sous-groupes compris",
      it_b.parent().text(2) == f"{sum(1 for n in st['arbre'] if n['branche'] == B)} mesures")
check("chaque mesure de l'arbre y est, une fois",
      all(vue.element(n["name"]) is not None for n in st["arbre"]))
check("la fiche est restée sur la mesure choisie", vue.fiche.lbl_nom.text() == nom_v)
check("le rangement est mémorisé", lire_reglage(CLE_RANGEMENT, "") == "variation")
vue.ed_filtre.setText(nv["name"])
check("un filtre cache les groupes qui n'ont plus rien à montrer",
      not it_v.parent().isHidden() and it_b.parent().isHidden())
vue.ed_filtre.setText("")
vue.arbre.setCurrentItem(it_b.parent())
check("choisir un groupe : la fiche le résume, sans DAX",
      B in vue.fiche.lbl_nom.text() and not vue.fiche.ed_dax.isVisible())
vue.cmb_rangement.setCurrentIndex(vue.cmb_rangement.findData("kpi"))
check("retour par KPI : un KPI par racine", un_kpi_par_racine())

# ---------------------------------------------------------------------------
print("7. l'aperçu des noms se déplie sur le DAX du formulaire en cours")
from tabs.fiche_mesure import ROLE_ATTRIBUT                       # noqa: E402
ct.inner.setCurrentIndex(tc.IDX_VARIATIONS)
ct._populate_list(select=V)
app.processEvents()
ap = ct.arbre_apercu
lignes_ap = [ap.topLevelItem(i) for i in range(ap.topLevelItemCount())]
it_ap = next((i for i in lignes_ap if i.data(0, tc.Qt.UserRole) == nv["name"]), None)
check(f"« {nv['name']} » est une ligne de l'aperçu", it_ap is not None)
ct._details_apercu()
dax_vu = it_ap.child(0).text(0) if it_ap.childCount() else ""
check("dépliée : son DAX en premier, celui du générateur",
      it_ap.child(0).data(0, ROLE_ATTRIBUT) and dax_vu == ct_arbre(nv["name"])["dax"])
check("… puis ses attributs (format, dossier…)",
      any(it_ap.child(i).text(0).startswith("dossier") for i in range(it_ap.childCount())))
check("les lignes de l'aperçu restent les noms (texte_apercu)",
      nv["name"] in ct.texte_apercu() and dax_vu not in ct.texte_apercu())
ap.expandItem(it_ap)
ancien = ct.ed_dax.toPlainText()
ct.ed_dax.setPlainText("CALCULATE({baseRef}, ALL('dim_Date')) + 0")
ct._details_apercu()
it_ap = next(ap.topLevelItem(i) for i in range(ap.topLevelItemCount())
             if ap.topLevelItem(i).data(0, tc.Qt.UserRole) == nv["name"])
check("le DAX tapé, PAS ENCORE committé, s'y voit développé",
      it_ap.child(0).text(0) == f"CALCULATE([{K}], ALL('dim_Date')) + 0")
check("… sans toucher le config en mémoire",
      "ALL('dim_Date')" not in json.dumps(ct._config["variations"][V], ensure_ascii=False))
check("la ligne dépliée le reste à la frappe", it_ap.isExpanded())
ct.ed_dax.setPlainText(ancien)
ct._set_dirty(False)

print("8. les jetons gardent leur couleur, les tables se replient")
from tabs.fiche_mesure import segments_dax, ROLE_HTML           # noqa: E402
from core.theme import BLUE                                      # noqa: E402
tous = [n for n in vue._noeuds if n["type"] not in ("base", "cible")]
check(f"chaque DAX généré se recolle à son modèle ({len(tous)} mesures)",
      all("".join(t for t, _ in segments_dax(n)[0]) == n["dax"] for n in tous)
      and all(any(g for _, g in segments_dax(n)[0])
              for n in tous if n["type"] != "aiguillage"))
# une mesure « ICP choisi » n'a pas de modèle à jetons : son DAX est un bloc
check("une mesure « ICP choisi » s'affiche d'un bloc, sans couleur inventée",
      all(segments_dax(n)[0] == [(n["dax"], None)]
          for n in vue._noeuds if n["type"] == "aiguillage"))
seg, subs = segments_dax(ct_arbre(env["name"]))
check(f"une enveloppe colore la mesure Réel qu'elle cite ([{reel['name']}])",
      ("[" + reel["name"] + "]", "accolade") in seg
      and ("{variationRef}", "[" + reel["name"] + "]") in subs)
# la section 4 a sorti V du paramètre : le formulaire l'y remet (sans committer)
ct.chk_infp.setChecked(True)
ct._details_apercu()
it_ap = next(ap.topLevelItem(i) for i in range(ap.topLevelItemCount())
             if ap.topLevelItem(i).data(0, tc.Qt.UserRole) == nv["name"])
check("le DAX de l'aperçu est peint avec la couleur des jetons",
      BLUE.lower() in (it_ap.child(0).data(0, ROLE_HTML) or "").lower())
check("… et son infobulle liste les remplacements",
      "{baseRef}" in it_ap.child(0).toolTip(0))
par = next((it_ap.child(i) for i in range(it_ap.childCount())
            if it_ap.child(i).text(0).startswith("paramètres")), None)
tables_nv = nv["tables"]                 # ceux de la section 1 : P_tout
check(f"« paramètres » : une ligne repliée qui compte les tables ({tables_nv})",
      tables_nv and par is not None and par.childCount() == len(tables_nv)
      and not par.isExpanded() and f"{len(tables_nv)} table" in par.text(0))
if tables_nv:
    ap.expandItem(par)
    ct._details_apercu()
    par = next(it_ap2.child(i) for it_ap2 in [next(
        ap.topLevelItem(i) for i in range(ap.topLevelItemCount())
        if ap.topLevelItem(i).data(0, tc.Qt.UserRole) == nv["name"])]
        for i in range(it_ap2.childCount()) if it_ap2.child(i).text(0).startswith("paramètres"))
    check("… une table par ligne, et dépliée elle le reste à la frappe",
          [par.child(i).text(0) for i in range(par.childCount())] == tables_nv
          and par.isExpanded())
vue.choisir(env["name"])
c = vue.fiche.ed_dax.document().find("[" + reel["name"] + "]")
check("la fiche colore aussi ce qu'un jeton est devenu",
      not c.isNull() and c.charFormat().foreground().color().name().lower() == BLUE.lower())
ct._set_dirty(False)

ct.deleteLater()
rmtree(copie)
print()
print("TOUT OK" if _ok else "DES ECHECS")
sys.exit(0 if _ok else 1)
