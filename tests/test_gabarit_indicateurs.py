# -*- coding: utf-8 -*-
"""Wireframe : importer un gabarit en changeant ses indicateurs.

    py tests\\test_gabarit_indicateurs.py

Un gabarit vient d'un autre rapport : ses visuels citent SES indicateurs,
que le rapport cible n'a en général pas.
1. Le remplacement seul, sur un visual.json inventé : mesures, queryRef,
   nativeQueryRef, filtre ; et ce qui ne doit pas bouger (une COLONNE du même
   nom, un titre, un ICP dont le nom en prolonge un autre), plus l'échange
   de deux ICP.
2. La nomenclature : les habits lus dans un config, la racine d'un nom.
3. L'onglet, sur une COPIE du projet de démonstration qui sert aussi de
   gabarit : les indicateurs du modèle sont proposés, l'aperçu suit,
   l'import les remplace, le manifeste le dit, Ctrl+Z défait l'import.
4. Un gabarit SANS modèle local dont l'indicateur n'existe nulle part :
   la nomenclature le trouve quand même.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PBIDOUILLE_DEV"] = "1"          # l'onglet n'écrit qu'en édition dev
FIT = Path(__file__).resolve().parent.parent
PBI = FIT.parent / "PowerBI"
if os.environ.get("PBIDOUILLE_PROJETS", "").strip():
    PBI = Path(os.environ["PBIDOUILLE_PROJETS"].strip())
sys.path.insert(0, str(FIT))
sys.path.insert(0, str(FIT / "bidouille"))
sys.path.insert(0, str(FIT / "bidouille" / "moteurs"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import exiger_projet, reglages_jetables, PROJET_DEMO   # noqa: E402

from core import template_import as ti                                # noqa: E402

_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def mesure(nom):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_mesures"}},
                        "Property": nom}}


def colonne(table, nom):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}},
                       "Property": nom}}


def litteral(texte):
    return {"Literal": {"Value": "'" + texte.replace("'", "''") + "'"}}


VISUEL = {
    "name": "abc",
    "visual": {
        "query": {"queryState": {"Values": {"projections": [
            {"field": mesure("Body Fat % 30d avg"),
             "queryRef": "_mesures.Body Fat % 30d avg",
             "nativeQueryRef": "Body Fat % 30d avg"},
            {"field": mesure("Body Fat"),
             "queryRef": "_mesures.Body Fat", "nativeQueryRef": "Body Fat"},
            {"field": colonne("dim", "Body Fat %"),
             "queryRef": "dim.Body Fat %", "nativeQueryRef": "Body Fat %"},
            {"field": colonne("dim", "Body Fat"), "queryRef": "dim.Body Fat"},
        ]}}},
        "visualContainerObjects": {"title": [{"properties": {
            "text": {"expr": litteral("Évolution de Body Fat %")}}}]},
    },
    "filterConfig": {"filters": [{"name": "f1", "filter": {"Where": [
        {"Condition": {"In": {"Values": [[litteral("Body Fat %")]]}}}]}}]},
}

print("1. le remplacement")
v = copy.deepcopy(VISUEL)
n = ti.remplacer_indicateurs(v, {"Body Fat %": "Weight"})
proj = v["visual"]["query"]["queryState"]["Values"]["projections"]
check("la mesure citée change de nom",
      proj[0]["field"]["Measure"]["Property"] == "Weight 30d avg")
check("queryRef et nativeQueryRef suivent",
      proj[0]["queryRef"] == "_mesures.Weight 30d avg"
      and proj[0]["nativeQueryRef"] == "Weight 30d avg")
check("le filtre sur l'indicateur suit",
      v["filterConfig"]["filters"][0]["filter"]["Where"][0]["Condition"]["In"]
      ["Values"][0][0]["Literal"]["Value"] == "'Weight'")
check("un ICP plus court (« Body Fat ») ne bouge pas",
      proj[1]["field"]["Measure"]["Property"] == "Body Fat"
      and proj[1]["queryRef"] == "_mesures.Body Fat")
check("une COLONNE du même nom ne bouge pas",
      proj[2]["field"]["Column"]["Property"] == "Body Fat %"
      and proj[2]["queryRef"] == "dim.Body Fat %"
      and proj[2]["nativeQueryRef"] == "Body Fat %")
check("le titre ne bouge pas",
      v["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"]
      ["expr"]["Literal"]["Value"] == "'Évolution de Body Fat %'")
check(f"le compte des remplacements ({n})", n == 4)

v = copy.deepcopy(VISUEL)
ti.remplacer_indicateurs(v, {"Body Fat %": "Body Fat", "Body Fat": "Body Fat %"})
proj = v["visual"]["query"]["queryState"]["Values"]["projections"]
check("un échange de deux ICP ne se défait pas",
      proj[0]["field"]["Measure"]["Property"] == "Body Fat 30d avg"
      and proj[1]["field"]["Measure"]["Property"] == "Body Fat %"
      and proj[1]["queryRef"] == "_mesures.Body Fat %")
check("dans l'échange, la colonne dim.Body Fat ne bouge pas",
      proj[3]["queryRef"] == "dim.Body Fat")
check("sans remplacement, rien ne change",
      ti.remplacer_indicateurs(copy.deepcopy(VISUEL), {}) == 0)
v = copy.deepcopy(VISUEL)
ti.remplacer_indicateurs(v, {"Body Fat %": "Body Fat %"})
check("un ICP gardé tel quel ne change rien", v == VISUEL)

v = copy.deepcopy(VISUEL)
ti.remplacer_indicateurs(v, {"Fat %": "Mass"})
proj = v["visual"]["query"]["queryState"]["Values"]["projections"]
check("un bout de nom suffit (sous-chaîne)",
      proj[0]["field"]["Measure"]["Property"] == "Body Mass 30d avg")

print("2. la nomenclature")
CONFIG = {"variations": {"7d avg": {"namePattern": "{base} 7d avg"},
                         "PY": {"namePattern": "{base} PY"},
                         "Écart": {"namePattern": "Écart de {base}"},
                         "brut": {}},
          "branches": {"YTD": {}}}
motifs = ti.motifs_de_noms(CONFIG)
check("les habits du config", {("", " 7d avg"), ("", " PY"), ("Écart de ", ""),
                               ("", " brut"), ("", " YTD")} <= set(motifs))
check("la racine d'un nom habillé deux fois",
      ti.racine("Masse grasse YTD PY", motifs) == "Masse grasse")
check("un préfixe aussi", ti.racine("Écart de Masse grasse", motifs) == "Masse grasse")
check("un nom sans habit reste lui-même", ti.racine("Masse grasse", motifs) == "Masse grasse")
check("on ne dépouille pas jusqu'au vide", ti.racine(" PY", motifs) == " PY")

# ---------------------------------------------------------------------------
print("3. l'onglet")
exiger_projet(PBI, PROJET_DEMO)
reglages_jetables("gabarit_indicateurs")
from qtpy.QtWidgets import QApplication                               # noqa: E402

qapp = QApplication.instance() or QApplication([])
from core.project import Project                                      # noqa: E402
from tabs.tab_wireframe import WireframeTab                           # noqa: E402

PROJ = PROJET_DEMO
c = Path(tempfile.mkdtemp(prefix="pbid_gabarit_"))
for s in (".SemanticModel", ".Report"):
    shutil.copytree(PBI / (PROJ + s), c / (PROJ + s),
                    ignore=shutil.ignore_patterns(".pbi", "cache.abf"))
shutil.copy2(PBI / (PROJ + ".pbip"), c / (PROJ + ".pbip"))
if (PBI / "measures_config.json").exists():
    shutil.copy2(PBI / "measures_config.json", c / "measures_config.json")
PBIP = c / (PROJ + ".pbip")

w = WireframeTab()
w.set_project(Project(PBIP))
w._tpl_set(str(PBIP))                       # le rapport sert de gabarit à lui-même
qapp.processEvents()
check("les ICP du gabarit sont lus", "Body Fat %" in w._tpl_bases
      and "Weight" in w._tpl_bases)

# le modèle qui ne cite que « Body Fat % »
cible = None
for m in w._tpl_models:
    if ti.indicateurs_du_modele(w._tpl_project.report_dir, m["page_id"],
                                m["root_id"], w._tpl_bases) == ["Body Fat %"] \
            and m["kind"] != "groupe":
        cible = m
        break
check("un modèle de la démo ne cite que Body Fat %", cible is not None)
w.cmb_tpl_pages.setCurrentIndex(w.cmb_tpl_pages.findData(cible["page_id"]))
qapp.processEvents()
for i in range(w.lst_models.count()):
    if w.lst_models.item(i).data(0x0100) == cible["root_id"]:     # Qt.UserRole
        w.lst_models.setCurrentRow(i)
qapp.processEvents()
check("une rangée par indicateur du modèle",
      [r[0].text() for r in w._icp_rangees] == ["Body Fat %"])
ed, cmb, _w = w._icp_rangees[0]
check("par défaut, un indicateur que ce rapport a se garde",
      cmb.currentText() == "Body Fat %" and not w._tpl_remplacements())
check("l'aperçu : toutes les mesures présentes",
      w._tpl_apercu() and all(e for _a, _n, e in w._tpl_apercu()))
cmb.setEditText("Weight")
check("choisir Weight", w._tpl_remplacements() == {"Body Fat %": "Weight"})
check("l'aperçu suit", all(n.startswith("Weight") and e
                           for _a, n, e in w._tpl_apercu()))
cmb.setEditText("Poids")
check("un indicateur absent : l'aperçu le signale",
      not any(e for _a, _n, e in w._tpl_apercu())
      and "absente" in w.lbl_apercu.text())
cmb.setEditText("Weight")

avant = set(w._data)
w._tpl_import()
qapp.processEvents()
nouveaux = [d for k, d in w._data.items() if k not in avant]
check("le modèle est importé", len(nouveaux) == 1)
ecrit = json.loads(Path(nouveaux[0]["path"]).read_text(encoding="utf-8"))
citees = ti._mesures_citees(ecrit, [])
check(f"il cite les mesures de Weight ({len(citees)})",
      citees and all(n == "Weight" or n.startswith("Weight ") for n in citees))
check("plus aucune trace de Body Fat % dans ses mesures",
      "Body Fat %" not in json.dumps(ti._mesures_citees(ecrit, []), ensure_ascii=False))
check("toutes existent dans le rapport",
      not ti.mesures_absentes([nouveaux[0]["path"]], w.project.model_dir))
check("le bandeau le dit", "« Body Fat % » → « Weight »" in w.lbl_status.text())
manifestes = sorted(c.rglob("import_manifest.txt"))
check("le manifeste le dit", manifestes and "# indicateur : Body Fat % -> Weight"
      in manifestes[-1].read_text(encoding="utf-8"))
w._undo_last()
qapp.processEvents()
check("Ctrl+Z défait l'import", set(w._data) == avant
      and not Path(nouveaux[0]["path"]).exists())

print("4. un gabarit sans modèle, un indicateur inconnu partout")
# le gabarit : une copie du RAPPORT seul (pas de modèle à lire), où
# « Body Fat % » s'appelle « Masse grasse », que ni lui ni la cible n'ont
g = Path(tempfile.mkdtemp(prefix="pbid_gabarit_mince_"))
shutil.copytree(c / (PROJ + ".Report"), g / (PROJ + ".Report"),
                ignore=shutil.ignore_patterns(".pbi"))
shutil.copy2(PBIP, g / (PROJ + ".pbip"))
for vj in (g / (PROJ + ".Report")).rglob("visual.json"):
    vj.write_text(vj.read_text(encoding="utf-8").replace("Body Fat %", "Masse grasse"),
                  encoding="utf-8")
w._tpl_set(str(g / (PROJ + ".pbip")))
qapp.processEvents()
check("le gabarit n'a pas d'ICP lisibles", w._tpl_project is not None
      and "Masse grasse" not in w._tpl_bases)
w.cmb_tpl_pages.setCurrentIndex(w.cmb_tpl_pages.findData(cible["page_id"]))
qapp.processEvents()
for i in range(w.lst_models.count()):
    if w.lst_models.item(i).data(0x0100) == cible["root_id"]:
        w.lst_models.setCurrentRow(i)
qapp.processEvents()
check("la nomenclature trouve « Masse grasse »",
      [r[0].text() for r in w._icp_rangees] == ["Masse grasse"])
ed, cmb, _w = w._icp_rangees[0]
check("absent d'ici : rien de choisi d'avance", cmb.currentText() == ""
      and not w._tpl_remplacements())
check("l'aperçu signale tout", not any(e for _a, _n, e in w._tpl_apercu()))
cmb.setEditText("Weight")
check("Weight choisi : tout est là", all(e for _a, _n, e in w._tpl_apercu()))
w._tpl_ajouter_rangee("", "")
check("une rangée vide ne compte pas", w._tpl_remplacements() == {"Masse grasse": "Weight"})
w._tpl_retirer_rangee(w._icp_rangees[-1])
check("et se retire", len(w._icp_rangees) == 1)
avant = set(w._data)
w._tpl_import()
qapp.processEvents()
nouveaux = [d for k, d in w._data.items() if k not in avant]
ecrit = json.loads(Path(nouveaux[0]["path"]).read_text(encoding="utf-8"))
citees = ti._mesures_citees(ecrit, [])
check(f"importé avec les mesures de Weight ({len(citees)})", len(nouveaux) == 1
      and citees and all(n == "Weight" or n.startswith("Weight ") for n in citees)
      and not ti.mesures_absentes([nouveaux[0]["path"]], w.project.model_dir))
w._undo_last()
qapp.processEvents()
shutil.rmtree(g, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))

print("5. une mesure absente")
inconnu = c / "inconnu.json"
inconnu.write_text(json.dumps({"visual": mesure("Nulle part 7d avg")}), encoding="utf-8")
check("mesures_absentes voit une mesure inconnue",
      ti.mesures_absentes([inconnu], w.project.model_dir) == ["Nulle part 7d avg"])

w.close()
shutil.rmtree(c, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
print("TOUT OK" if _ok else "DES ECHECS")
sys.exit(0 if _ok else 1)
