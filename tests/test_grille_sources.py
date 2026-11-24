# -*- coding: utf-8 -*-
"""La FENETRE de la grille des sources, et l'onglet Rapport qui l'ouvre.

    py tests\\test_grille_sources.py

  1. L'ONGLET RAPPORT : un resume de la grille et un bouton. Sans grille, pas
     de propagation (on ne choisit pas le gabarit a la place de l'usager) ;
     avec, UN seul step, par la grille.
  2. LA GRILLE LIT l'ancien fichier (groupes) tel quel — et elle parle en
     MOTS : « Gabarit », « À la main », le nom du KPI copie. Aucun symbole.
  3. PEINDRE : une selection copie un KPI, passe a la main, retire sa regle ;
     la ligne « Tous les KPI » ; la case de la base emmene ses copieurs.
  4. LES GROUPES : creer, changer de gabarit, une regle de groupe par
     variation, renommer, sortir un KPI, supprimer.
  5. ENREGISTRER ecrit le format actuel ; rouvrir redonne la meme grille.
     Fermer avec des changements : on demande.
  6. LES PERTES se voient AVANT : coin orange sur les cases, et le verdict.
  7. DES REGLES FAUTIVES : le verdict le dit, Enregistrer est grise.
  8. CHANGER DE BASE : les en-tetes suivent.
  9. LES CIBLES : leurs colonnes, « pas de mesure » pour les KPI sans
     cible, et un avertissement quand la source n'a pas la mesure.
 10. PAR-DESSUS : le gabarit d'un groupe neuf se pose par-dessus la base —
     ses cases le disent ; un groupe de l'ancien fichier est independant,
     et le menu bascule l'un a l'autre.
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
from _fixture import exiger_projet, PROJET_DEMO, ajouter_cibles   # noqa: E402

exiger_projet(PBI, PROJET_DEMO, "TD_Indicateurs.xlsx", "measures_config.json")

PROJ = PROJET_DEMO
ENT = "_mesures"
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


c = Path(tempfile.gettempdir()) / "pbid_grille_ui"
rmtree(c)
c.mkdir(parents=True)
for s in (".Report", ".SemanticModel"):
    shutil.copytree(PBI / (PROJ + s), c / (PROJ + s))
for f in (PROJ + ".pbip", "TD_Indicateurs.xlsx", "measures_config.json"):
    shutil.copy2(PBI / f, c / f)
# la grille est d'abord vérifiée sans cible (elles arrivent plus bas) : celles
# que le projet de démonstration déclare n'y ont pas leur place
_conf = json.loads((c / "measures_config.json").read_text(encoding="utf-8"))
_conf.pop("kpiMeasureFolders", None)
(c / "measures_config.json").write_text(json.dumps(_conf, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
R = c / (PROJ + ".Report")

from qtpy.QtWidgets import QApplication, QMessageBox          # noqa: E402
import core.project as prj                                    # noqa: E402
# magasin de reglages JETABLE (cf. test_reglages)
prj.APP_REGLAGES = "BIdouille_TEST_grille"
prj.reglages().clear()
app = QApplication.instance() or QApplication([])

from core.project import Project                              # noqa: E402
import propagate_cf as pc                                     # noqa: E402
import tabs.tab_report as tr                                  # noqa: E402
import tabs.dialog_sources as ds                              # noqa: E402

KPIS = pc.kpis_from_parameter(c / (PROJ + ".SemanticModel"), "P_Indicateurs_parCalcul")
SLEEP, BASE, FAT, TOTAL, WEIGHT = KPIS
SYMBOLES = re.compile("[★✋·∅⚠▾▸›]")

# ===================================================================== 1
print("1. l'onglet Rapport : un resume, un bouton")
onglet = tr.ReportTab()
onglet.set_project(Project(c / (PROJ + ".pbip")))
check("plus de gabarit, de cibles ni de groupes a cocher dans l'onglet",
      not any(hasattr(onglet, n) for n in ("cmb_template", "lst_targets",
                                           "chk_groupes", "lbl_groupes")))
check("la grille s'ouvre par un bouton",
      onglet.btn_sources.text() == "Grille des sources…")
check("sans grille : l'onglet le dit, et dit quoi faire",
      "Aucune" in onglet.lbl_sources.text()
      and "gabarit de base" in onglet.lbl_sources.text())
lances = []
onglet._enqueue = lambda steps: lances.append(steps)
onglet._run_propagate()
onglet._run_chain()
check("… et ni Propager ni « propager puis colorer » ne lancent quoi que ce soit",
      lances == [] and "Aucune source de formatage" in onglet.journal.texte())

(c / "propagation.json").write_text(json.dumps({"groupes": [
    {"nom": "groupe 1", "gabarit": BASE, "kpis": []},
    {"nom": "groupe 2", "gabarit": SLEEP, "kpis": [SLEEP]}]},
    ensure_ascii=False), encoding="utf-8")
onglet._refresh_sources_label()
check("avec l'ancien fichier : le gabarit de base et le groupe sont dits",
      BASE in onglet.lbl_sources.text() and "1 groupe" in onglet.lbl_sources.text()
      and "partagé par les rapports du dossier" in onglet.lbl_sources.text())
onglet._run_propagate()
check("Propager lance UN step, par la grille",
      len(lances) == 1 and len(lances[0]) == 1
      and lances[0][0][0] is pc.propagate_regles)
kw = lances[0][0][1]
check("… avec le fichier, TOUTES les branches (pour classer) et les "
      "variations du config", kw["regles_json"].endswith("propagation.json")
      and kw["toutes_branches"] == ["YTD"] and ("PY", "PY") in kw["variations"])
onglet._run_chain()
check("… « propager puis colorer » : la grille, puis les couleurs",
      len(lances) == 2 and lances[1][0][0] is pc.propagate_regles
      and len(lances[1]) == 2)

print("   le prechauffage : la grille s'ouvre sans relire le disque")
import time as _temps                                         # noqa: E402
fin = _temps.time() + 15
while not getattr(onglet, "prechauffage_fini", False) and _temps.time() < fin:
    app.processEvents()
    _temps.sleep(0.02)
vus = set(pc._TEXTES)
check("a l'ouverture du projet, le modele et les visuels sont lus d'avance, "
      "quand l'app ne fait rien", getattr(onglet, "prechauffage_fini", False)
      and all(str(v) in vus for v in R.glob("definition/pages/*/visuals/*/visual.json"))
      and all(str(t) in vus for t in (c / (PROJ + ".SemanticModel") / "definition"
                                      / "tables").glob("*.tmdl")))
essai = c / "essai_cache.txt"
essai.write_text("un", encoding="utf-8")
premier = pc.lire_texte(essai)
essai.write_text("deux", encoding="utf-8")
check("un fichier qui change est relu, jamais servi perime",
      premier == "un" and pc.lire_texte(essai) == "deux")
avant_ecriture = essai.stat()
pc.ecrire_texte(essai, "troi")
# un disque a dates grossieres : meme taille, meme date qu'avant l'ecriture
os.utime(essai, ns=(avant_ecriture.st_atime_ns, avant_ecriture.st_mtime_ns))
check("… et ce qu'on ecrit soi-meme n'est jamais servi a l'ancienne, meme a "
      "taille et date egales", pc.lire_texte(essai) == "troi")
essai.unlink()

# ===================================================================== 2
print("2. la grille lit l'ancien fichier, et parle en mots")


def ouvrir():
    d = ds.SourcesDialog(pc.groupes_path(R), onglet._kpis, onglet,
                         source=onglet._sources_path(),
                         analyse=onglet._analyse())
    d.confirmer_fermeture = False
    d.show()
    app.processEvents()
    return d


dlg = ouvrir()


def item(quoi, qui, v):
    return dlg.table.item(dlg.rang_de(quoi, qui), dlg.grille.variations.index(v))


def texte(k, v):
    return item("kpi", k, v).text()


def gras(k, v):
    return bool(item("kpi", k, v).data(ds.ROLE_GRAS))


def entete(quoi, qui=None):
    return dlg.table.verticalHeaderItem(dlg.rang_de(quoi, qui)).text()


def choisir(*cases):
    dlg.table.clearSelection()
    for quoi, qui, v in cases:
        item(quoi, qui, v).setSelected(True)


def tout_le_texte():
    t = dlg.table
    return ([t.item(r, col).text() for r in range(t.rowCount())
             for col in range(t.columnCount())]
            + [t.verticalHeaderItem(r).text() for r in range(t.rowCount())])


V = dlg.grille.variations
print("   colonnes :", V)
check("les colonnes : le Reel, puis toutes les variations du config — "
      "celles hors parametre de champ comprises",
      V[0] == "Réel" and {"PY", "YoY %", "sparkline", "CF YoY %"} <= set(V)
      and "YTD" not in V)
check("… une variation hors parametre se regle comme les autres",
      texte(WEIGHT, "sparkline") == BASE and texte(BASE, "CF YoY %") == ds.GABARIT)
check("les lignes : Tous les KPI, le groupe et ses KPI, puis les autres",
      [q for q, _ in dlg._rangs] == ["tous", "groupe", "kpi", "sans_groupe",
                                     "kpi", "kpi", "kpi", "kpi"])
check("… en-tetes en clair : « Tous les ICP », le groupe, « Sans groupe »",
      entete("tous") == "Tous les ICP"
      and entete("groupe", "groupe 2") == "groupe 2, indépendant"
      and entete("sans_groupe") == "Sans groupe")
check("… le gabarit du groupe et le gabarit de base sont nommes comme tels",
      entete("kpi", SLEEP).strip() == SLEEP + " (gabarit du groupe)"
      and entete("kpi", BASE) == BASE + " (gabarit de base)")
check("la base est choisie", dlg.cmb_base.currentText() == BASE)
check("ses cases disent « Gabarit »", all(texte(BASE, v) == ds.GABARIT for v in V))
check("le gabarit du groupe aussi", all(texte(SLEEP, v) == ds.GABARIT for v in V))
check("les autres disent QUI ils copient, en toutes lettres",
      all(texte(k, v) == BASE for k in (FAT, TOTAL, WEIGHT) for v in V))
check("… sans gras : ils suivent une regle plus large",
      not any(gras(k, v) for k in (FAT, TOTAL, WEIGHT) for v in V))
check("les lignes Tous les KPI et groupe sont vides : aucune regle posee",
      all(item("tous", None, v).text() == "" for v in V)
      and all(item("groupe", "groupe 2", v).text() == "" for v in V))
check("AUCUN symbole dans la grille : que des mots",
      not any(SYMBOLES.search(x) for x in tout_le_texte()))
check("la ligne « Sans groupe » n'est pas une case a peindre",
      not (item("sans_groupe", None, "PY").flags() & ds.Qt.ItemIsSelectable))
check("rien n'est modifie a l'ouverture", not dlg.modifie())
check("sans selection, les boutons d'action sont grises",
      not dlg.btn_appliquer.isEnabled())

# ===================================================================== 3
print("3. peindre la grille")
choisir(("tous", None, "PY"))
check("une selection active les boutons", dlg.btn_appliquer.isEnabled())
dlg.cmb_source.setCurrentText(BASE)
dlg.btn_appliquer.click()
check("Tous les KPI · PY = la base : la regle se lit sur sa ligne",
      item("tous", None, "PY").text() == BASE)
check("… et le gabarit du groupe PREND ce PY (la regle par variation passe "
      "avant)", texte(SLEEP, "PY") == BASE and texte(SLEEP, "Réel") == ds.GABARIT)
choisir(("kpi", FAT, "YoY %"))
dlg.cmb_source.setCurrentText(WEIGHT)
dlg.btn_appliquer.click()
check("« Copier depuis » : la case dit sa source, en gras (regle posee ici)",
      texte(FAT, "YoY %") == WEIGHT and gras(FAT, "YoY %"))
check("… Weight devient le gabarit de cette variation",
      texte(WEIGHT, "YoY %") == ds.GABARIT)
check("… et son infobulle dit qui le copie",
      f"Copié par : {FAT}." in item("kpi", WEIGHT, "YoY %").toolTip())
check("… une couleur par source : copieur et gabarit en partagent une",
      item("kpi", FAT, "YoY %").data(ds.ROLE_FOND)
      == item("kpi", WEIGHT, "YoY %").data(ds.ROLE_FOND))
check("… et la legende des couleurs nomme Weight",
      WEIGHT in dlg.lbl_couleurs.text())
choisir(("kpi", TOTAL, "Réel"))
dlg.btn_main.click()
check("« À la main » : la case le dit, en gras",
      texte(TOTAL, "Réel") == ds.A_LA_MAIN and gras(TOTAL, "Réel"))
dlg.btn_retirer.click()
check("« Retirer la regle » : elle copie de nouveau la base",
      texte(TOTAL, "Réel") == BASE and not gras(TOTAL, "Réel"))
choisir(("kpi", BASE, "Δ 7d"))
dlg.cmb_source.setCurrentText(WEIGHT)
dlg.btn_appliquer.click()
check("la case de la BASE copie Weight : ceux qui la suivaient suivent, et "
      "on le dit", texte(TOTAL, "Δ 7d") == WEIGHT
      and "copie maintenant « Weight »" in dlg.lbl_notes.text())
check("… le gabarit du groupe, lui, n'a pas bouge",
      texte(SLEEP, "Δ 7d") == ds.GABARIT)
check("la grille est coherente apres tout ca", not dlg.grille.problemes()[0]
      and dlg.btn_save.isEnabled())
check("… et elle se sait modifiee", dlg.modifie())

# ===================================================================== 4
print("4. les groupes")
choisir(("kpi", FAT, "Réel"), ("kpi", TOTAL, "Réel"))
check("les KPI selectionnes", dlg.kpis_selectionnes() == [FAT, TOTAL])
dlg.nouveau_groupe("Famille")
check("un groupe neuf : sa ligne, puis ses KPI",
      [x for x in dlg._rangs if x[0] in ("groupe", "sans_groupe")]
      == [("groupe", "groupe 2"), ("groupe", "Famille"), ("sans_groupe", None)]
      and dlg.rang_de("kpi", FAT) == dlg.rang_de("groupe", "Famille") + 1)
check("… son gabarit : le premier de ses KPI, posé par-dessus la base, "
      "que l'autre copie", texte(FAT, "Réel") == ds.SUR_LA_BASE
      and texte(TOTAL, "Réel") == FAT)
check("… l'infobulle dit ce que ca veut dire",
      "par-dessus « " + BASE + " »" in item("kpi", FAT, "Réel").toolTip()
      and "l'emporte" in item("kpi", FAT, "Réel").toolTip()
      and "se pose par-dessus" in item("kpi", TOTAL, "Réel").toolTip())
check("… mais une regle posee sur la case reste (le YoY % de Weight)",
      texte(FAT, "YoY %") == WEIGHT)
dlg.changer_gabarit_groupe("Famille", TOTAL)
check("changer le gabarit du groupe", texte(TOTAL, "Réel") == ds.SUR_LA_BASE
      and texte(FAT, "Réel") == TOTAL
      and entete("kpi", TOTAL).strip() == TOTAL + " (gabarit du groupe)")
choisir(("groupe", "Famille", "MTD"))
dlg.cmb_source.setCurrentText(WEIGHT)
dlg.btn_appliquer.click()
check("une regle du groupe pour une variation : sa ligne la montre, ses KPI "
      "la suivent", item("groupe", "Famille", "MTD").text() == WEIGHT
      and texte(TOTAL, "MTD") == WEIGHT and texte(FAT, "MTD") == WEIGHT
      and not gras(TOTAL, "MTD"))
check("… en couleur pale : ils heritent",
      item("kpi", TOTAL, "MTD").data(ds.ROLE_FOND)
      != item("kpi", WEIGHT, "MTD").data(ds.ROLE_FOND))
menu = ds.QMenu()
dlg._remplir_menu_groupes(menu)
libelles = [a.text() for a in menu.actions()]
check("le menu Groupes, en mots", "Nouveau groupe avec les ICP sélectionnés…"
      in libelles and "Groupe Famille" in libelles
      and not any(SYMBOLES.search(x) for x in libelles))
dlg.renommer_groupe("Famille", "Activité")
check("renommer : l'en-tete suit", entete("groupe", "Activité") == "Groupe Activité")
choisir(("kpi", FAT, "Réel"))
dlg.retirer_du_groupe()
check("sortir un KPI de son groupe : il retourne « Sans groupe »",
      dlg.rang_de("kpi", FAT) > dlg.rang_de("sans_groupe")
      and texte(FAT, "Réel") == BASE)
dlg.supprimer_groupe("Activité")
check("supprimer le groupe : ses KPI suivent la base",
      ("groupe", "Activité") not in dlg._rangs and texte(TOTAL, "Réel") == BASE
      and "supprimé" in dlg.lbl_notes.text())
check("toujours aucun symbole", not any(SYMBOLES.search(x) for x in tout_le_texte()))

# ===================================================================== 5
print("5. enregistrer, rouvrir")
avant = {(q, v): dlg.table.item(dlg.rang_de(*q), V.index(v)).text()
         for q in dlg._rangs if q[0] != "sans_groupe" for v in V}
dlg.btn_save.click()
app.processEvents()
check("Enregistrer ferme la fenetre", dlg.enregistre and not dlg.isVisible())
ecrit = json.loads((c / "propagation.json").read_text(encoding="utf-8"))
check("le fichier est au format actuel, avec ses groupes",
      ecrit.get("version") == 2 and ecrit["base"] == BASE
      and ecrit["groupes"][0]["nom"] == "groupe 2"
      and ecrit["colonnes"].get("PY") == BASE)
check("… et la regle de Body Fat % en rectangle",
      {"source": WEIGHT, "kpis": [FAT], "variations": ["YoY %"]}
      in ecrit["exceptions"])
onglet._refresh_sources_label()
check("l'onglet resume la nouvelle grille",
      "2 gabarits par variation" in onglet.lbl_sources.text()
      and "1 groupe" in onglet.lbl_sources.text())
dlg = ouvrir()
check("rouvrir redonne la MEME grille, case par case",
      {(q, v): dlg.table.item(dlg.rang_de(*q), V.index(v)).text()
       for q in dlg._rangs if q[0] != "sans_groupe" for v in V} == avant)

choisir(("kpi", TOTAL, "PY"))
dlg.btn_main.click()
repondu = []


def repondre(reponse):
    def question(*a, **k):
        repondu.append(True)
        return reponse
    return question


dlg.confirmer_fermeture = True
ds.QMessageBox.question = repondre(QMessageBox.No)
dlg.reject()
app.processEvents()
check("fermer avec des changements : on demande, « Non » garde la fenetre",
      repondu and dlg.isVisible())
ds.QMessageBox.question = repondre(QMessageBox.Yes)
dlg.reject()
app.processEvents()
check("… « Oui » ferme sans rien ecrire",
      not dlg.isVisible() and json.loads((c / "propagation.json")
                                         .read_text(encoding="utf-8")) == ecrit)

# ===================================================================== 6
print("6. les pertes se voient avant d'ecrire")
pc.ecrire_regles(c / "propagation.json", {"version": 2, "base": BASE})
lignes = None
for vj in sorted(R.glob("definition/pages/*/visuals/*/visual.json")):
    data = json.loads(vj.read_text(encoding="utf-8"))
    if (data.get("visual") or {}).get("visualType") == "lineChart":
        lignes = vj
        break
data = json.loads(lignes.read_text(encoding="utf-8"))
for liste in data["visual"]["objects"].values():
    if isinstance(liste, list):
        liste[:] = [e for e in liste if pc.entry_metadata(e)
                    not in (ENT + "." + BASE + " PY", ENT + "." + BASE + " YTD PY")]
lignes.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8")
dlg = ouvrir()
check("la base n'a plus de PY dans le graphique : les PY qui la copient ont "
      "le coin orange", item("kpi", WEIGHT, "PY").data(ds.ROLE_PERTE)
      and item("kpi", FAT, "PY").data(ds.ROLE_PERTE))
check("… pas la base elle-meme : elle est sa propre source",
      not item("kpi", BASE, "PY").data(ds.ROLE_PERTE))
check("… le verdict le chiffre", "seraient retirés" in dlg.lbl_verdict.text())
check("… l'infobulle dit pourquoi", "n'en porte aucun"
      in item("kpi", WEIGHT, "PY").toolTip())
choisir(("tous", None, "PY"))
dlg.btn_main.click()
check("PY « à la main » pour tous : plus aucune perte annoncee",
      not any(item("kpi", k, "PY").data(ds.ROLE_PERTE) for k in KPIS)
      and "seraient retirés" not in dlg.lbl_verdict.text())
dlg.reject()

# ===================================================================== 7
print("7. des regles fautives")
pc.ecrire_regles(c / "propagation.json", {"version": 2, "base": BASE,
                                          "exceptions": [{"source": WEIGHT,
                                                          "kpis": [BASE],
                                                          "variations": ["PY"]}]})
dlg = ouvrir()
check("le verdict dit le probleme, en clair",
      "Problème" in dlg.lbl_verdict.text()
      and "gabarit de base" in dlg.lbl_verdict.text())
check("… et Enregistrer est grise", not dlg.btn_save.isEnabled())
onglet._refresh_sources_label()
check("l'onglet Rapport le dit aussi, en mots",
      onglet.lbl_sources.text().startswith("Problème :"))
dlg.reject()

# ===================================================================== 8
print("8. changer de base")
pc.ecrire_regles(c / "propagation.json", {"version": 2, "base": BASE})
dlg = ouvrir()
dlg.cmb_base.setCurrentText(TOTAL)
check("l'en-tete marque la nouvelle base, et elle seule",
      entete("kpi", TOTAL).endswith("(gabarit de base)")
      and not entete("kpi", BASE).endswith("(gabarit de base)"))
check("la nouvelle base est le gabarit, l'ancienne la copie",
      texte(TOTAL, "Réel") == ds.GABARIT and texte(BASE, "Réel") == TOTAL)
dlg.cmb_base.setCurrentText(ds.AUCUN)
check("« (aucun) » : plus de base, les cases ne sont pas propagees",
      texte(FAT, "Réel") == ds.NON_PROPAGE and dlg.grille.base is None)
dlg.reject()

# ===================================================================== 9
print("9. les cibles")
ajouter_cibles(c / (PROJ + ".SemanticModel"), (WEIGHT, FAT))
conf = json.loads((c / "measures_config.json").read_text(encoding="utf-8"))
for vid in ("écart", "écart %"):
    conf["variations"][vid] = {"namePattern": "{base} " + vid, "dax": "0",
                               "appliesToKpi": False, "appliesToCibles": True}
conf["kpiMeasureFolders"] = [{"folder": "_cibles", "calcul": "Cible"}]
(c / "measures_config.json").write_text(
    json.dumps(conf, indent=2, ensure_ascii=False), encoding="utf-8")
pc.ecrire_regles(c / "propagation.json", {"version": 2, "base": BASE})
onglet.reload()
dlg = ouvrir()
V = dlg.grille.variations
check("les colonnes des cibles, lues dans les noms des mesures",
      {"Cible", "Cible écart", "Cible écart %"} <= set(V)
      and "écart" not in V)
check("un KPI sans cible : « pas de mesure » dans les colonnes de cible",
      texte(BASE, "Cible écart") == ds.PAS_DE_MESURE
      and texte(TOTAL, "Cible écart") == ds.PAS_DE_MESURE)
check("un KPI qui a une cible : sa case dit ce qu'elle copie",
      texte(WEIGHT, "Cible écart") == BASE)
check("… en retrait, car la base n'a pas de cible — rien ne serait copie",
      item("kpi", WEIGHT, "Cible écart").data(ds.ROLE_ITALIQUE)
      and "n'a pas de mesure « Cible écart »"
      in item("kpi", WEIGHT, "Cible écart").toolTip())
check("… et le verdict le dit, colonne par colonne",
      "« Cible écart », 2 ICP copient « " + BASE + " », qui n'a pas cette "
      "mesure" in dlg.lbl_verdict.text())
choisir(("tous", None, "Cible écart"))
dlg.cmb_source.setCurrentText(WEIGHT)
dlg.btn_appliquer.click()
check("« Tous les KPI » · Cible écart = Weight : Weight en est le gabarit, "
      "Body Fat % le copie", texte(WEIGHT, "Cible écart") == ds.GABARIT
      and texte(FAT, "Cible écart") == WEIGHT)
check("… les KPI sans cible restent « pas de mesure »",
      texte(BASE, "Cible écart") == ds.PAS_DE_MESURE)
check("… et l'avertissement de cette colonne s'en va",
      "« Cible écart » —" not in dlg.lbl_verdict.text())
dlg.reject()

# ===================================================================== 10
print("10. par-dessus la base : le groupe neuf, l'ancien, la bascule")
pc.ecrire_regles(c / "propagation.json", {
    "version": 2, "base": BASE, "colonnes": {"PY": WEIGHT},
    "groupes": [{"nom": "Sommeil", "kpis": [SLEEP, FAT], "base": SLEEP}]})
dlg = ouvrir()
V = dlg.grille.variations
check("le gabarit d'un groupe dit sur QUOI il se pose : la base…",
      texte(SLEEP, "Réel") == ds.SUR_LA_BASE)
check("… ou le gabarit de « Tous les KPI » pour cette variation",
      texte(SLEEP, "PY") == ds.GABARIT + " sur " + WEIGHT)
check("ses KPI copient leur gabarit, PY compris",
      texte(FAT, "PY") == SLEEP and texte(FAT, "Réel") == SLEEP)
check("… les autres prennent le PY de Weight", texte(TOTAL, "PY") == WEIGHT)
check("l'en-tete du groupe ne dit rien de plus : il se pose par-dessus, "
      "c'est le defaut", entete("groupe", "Sommeil") == "Groupe Sommeil")
menu = ds.QMenu()
dlg._remplir_menu_groupes(menu)
sous = next(m for m in menu.findChildren(ds.QMenu)
            if m.title() == "Groupe Sommeil")
bascule = next(a for a in sous.actions() if "par-dessus la base" in a.text())
check("le menu du groupe : « posé par-dessus la base », coche",
      bascule.isCheckable() and bascule.isChecked())
bascule.trigger()
check("decocher : le groupe devient independant — l'en-tete le dit, le PY "
      "de Weight passe avant son gabarit", entete("groupe", "Sommeil")
      == "Groupe Sommeil, indépendant" and texte(SLEEP, "Réel") == ds.GABARIT
      and texte(FAT, "PY") == WEIGHT and texte(SLEEP, "PY") == WEIGHT
      and "indépendant" in dlg.lbl_notes.text())
check("… sans aucun symbole", not any(SYMBOLES.search(x) for x in tout_le_texte()))
check("la legende des couleurs ne nomme que les sources qui colorent une case",
      WEIGHT in dlg.lbl_couleurs.text() and BASE in dlg.lbl_couleurs.text()
      and TOTAL not in dlg.lbl_couleurs.text())
dlg.rendre_independant("Sommeil", False)
check("… et recocher le remet par-dessus", texte(SLEEP, "Réel") == ds.SUR_LA_BASE
      and texte(FAT, "PY") == SLEEP)

print("   le detail d'une etiquette de carte")
check("sa colonne, juste apres celle de l'etiquette",
      "PY — détail" in V and V.index("PY — détail") == V.index("PY") + 1)
check("sans regle a lui, il suit son etiquette — et l'infobulle le dit",
      texte(TOTAL, "PY — détail") == texte(TOTAL, "PY") == WEIGHT
      and "le détail suit son étiquette" in item("kpi", TOTAL, "PY — détail").toolTip()
      and not gras(TOTAL, "PY — détail"))
check("… la ligne « Tous les KPI » aussi",
      "le détail suit son étiquette" in item("tous", None, "PY — détail").toolTip())
choisir(("tous", None, "PY — détail"))
dlg.btn_main.click()
check("« Tous les KPI » · PY — détail a la main : chacun garde son detail, "
      "l'etiquette suit toujours Weight",
      texte(TOTAL, "PY — détail") == ds.A_LA_MAIN and texte(TOTAL, "PY") == WEIGHT
      and texte(FAT, "PY — détail") == ds.A_LA_MAIN and texte(FAT, "PY") == SLEEP
      and not dlg.grille.problemes()[0])
dlg.reject()

onglet.deleteLater()
app.processEvents()
prj.reglages().clear()
rmtree(c)
print("\n" + ("TOUT OK" if _ok else "*** DES ECHECS ***"))
sys.exit(0 if _ok else 1)
