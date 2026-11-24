"""Les captures des articles 2 à 4 : ⚙ Réglages, Variations et ses jetons,
l'Arbre des mesures, les Paramètres de champ et l'onglet Rapport.

    py docs\\ressources\\sources\\capture_articles.py [section ...]

Sections : reglages, variations, arbre, parametres, rapport ; aucune = toutes.
Les articles 5 et 6 ont leurs scripts (capture_sources.py,
capture_radiographie.py), la vue d'ensemble aussi (capture_vue.py).

Chaque section travaille sur sa propre COPIE du projet de démonstration, sous
C:\\Users\\Public\\PBIdouille_demo (un chemin neutre, si jamais il paraît),
avec un magasin de réglages jetable : rien n'est écrit dans le projet ni dans
les réglages de l'usager. Les chemins des fichiers que lit le modèle sont
remplacés par C:\\Donnees\\ dans la copie.

Les situations montrées (une variation MoM %, des cibles, des jetons, une
table YTD seule…) sont construites ici, en mémoire ou dans la copie : ce sont
celles que décrivent les articles."""
import copy
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
os.environ.pop("PBIDOUILLE_DEV", None)
ICI = Path(__file__).resolve().parent
OUTIL = ICI.parents[2]                               # PBIdouille/
IMAGES = ICI.parent / "images"
BASE = Path(r"C:\Users\Public\PBIdouille_demo")
sys.path[:0] = [str(OUTIL), str(OUTIL / "bidouille"), str(OUTIL / "bidouille" / "moteurs"),
                str(OUTIL / "tests")]
import chemins                                       # noqa: E402
from _fixture import ajouter_cibles, reglages_jetables   # noqa: E402

reglages_jetables("capture_articles")
from core import edition                             # noqa: E402
edition.MARQUEUR_DEV = BASE / "pas_de_dev_ici"       # captures en PRODUCTION

import generate_measures as gm                       # noqa: E402
import openpyxl                                      # noqa: E402
from qtpy.QtWidgets import QApplication              # noqa: E402

app = QApplication.instance() or QApplication([])
from core.theme import neon_stylesheet               # noqa: E402
app.setStyleSheet(neon_stylesheet())
import tabs.tab_config as tc                         # noqa: E402
from core.project import Project                     # noqa: E402

PBI = chemins.PROJETS
P = chemins.PROJET_DEMO


def tour(n=4):
    for _ in range(n):
        app.processEvents()


def effacer(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, x, e: (os.chmod(x, stat.S_IWRITE), f(x)))


def copie(nom) -> Path:
    """Une copie fraîche du projet de démonstration, chemins neutres."""
    c = BASE / nom
    effacer(c)
    c.mkdir(parents=True)
    for s in (".SemanticModel", ".Report"):
        shutil.copytree(PBI / (P + s), c / (P + s),
                        ignore=shutil.ignore_patterns(".pbi", "cache.abf"))
    for f in (P + ".pbip", "measures_config.json", "TD_Indicateurs.xlsx", "propagation.json",
              "catalogue_variations.json"):
        if (PBI / f).exists():
            shutil.copy2(PBI / f, c / f)
    for t in (c / (P + ".SemanticModel") / "definition").rglob("*.tmdl"):
        s = t.read_text(encoding="utf-8")
        n = re.sub(r'C:\\\\?[^"\r\n]*?([^\\"\r\n]+\.(?:xlsx|csv|json|xml|txt))',
                   lambda m: "C:\\Donnees\\" + m.group(1), s)
        if n != s:
            t.write_text(n, encoding="utf-8")
    return c


def modele(c) -> Path:
    return c / (P + ".SemanticModel")


def config(c) -> dict:
    return json.loads((c / "measures_config.json").read_text(encoding="utf-8"))


def ecrire_config(c, conf):
    (c / "measures_config.json").write_text(json.dumps(conf, ensure_ascii=False, indent=2),
                                            encoding="utf-8")


def colonnes_td(c, colonnes):
    """Ajoute à l'Excel des indicateurs des colonnes {en-tête: {mesure: valeur}}
    (ou une valeur pour toutes les lignes)."""
    wb = openpyxl.load_workbook(c / "TD_Indicateurs.xlsx")
    ws = wb.worksheets[0]
    entetes = [x.value for x in ws[1]]
    cle = entetes.index("mesure") + 1
    for j, (h, valeurs) in enumerate(colonnes.items()):
        k = len(entetes) + 1 + j
        ws.cell(1, k, h)
        for r in range(2, ws.max_row + 1):
            v = valeurs.get(ws.cell(r, cle).value) if isinstance(valeurs, dict) else valeurs
            if v is not None:
                ws.cell(r, k, v)
    wb.save(c / "TD_Indicateurs.xlsx")
    wb.close()


def sauver(widget, nom):
    tour()
    widget.grab().save(str(IMAGES / f"{nom}.png"))
    print("capture", nom, widget.width(), "x", widget.height())


def onglet_config(c, largeur, hauteur):
    ct = tc.ConfigTab()
    ct.resize(largeur, hauteur)
    ct.show()
    ct.set_project(Project(c / (P + ".pbip")))
    tour()
    return ct


def fermer(ct):
    ct._set_dirty(False)
    ct.close()


MOM = {"namePattern": "{base} MoM %", "inFieldParameter": True,
       "formatString": "+#,0.0 %;-#,0.0 %;0.0 %",
       "description": "Variation de {base} par rapport au mois précédent",
       "dax": ["VAR Actuel = {baseRef}",
               "VAR Precedent = CALCULATE({baseRef}, DATEADD({date}, -1, MONTH))",
               "RETURN DIVIDE(Actuel - Precedent, Precedent)"]}
ECART_CIBLE = {"namePattern": "{base} écart", "appliesToKpi": False, "appliesToCibles": True,
               "formatString": "delta", "dax": "{kpiRef} - {baseRef}"}


# ---------------------------------------------------------------- 2. Réglages
def reglages():
    c = copie("reglages")
    colonnes_td(c, {"couleur_fill": "#1E5B4F", "couleur_text": "#D8F3E8", "unite": "kg",
                    "objectif": 180,
                    "ordre": {"Weight": 10, "Total Steps": 20, "Average Steps": 30,
                              "Body Fat %": 40, "Average Sleep Duration": 50}})
    conf = config(c)
    conf["hardcodedAttributes"] = {"tokens": {"unite": "unite", "objectif": "objectif"}}
    conf["variations"]["Écart"] = {"namePattern": "{base} écart", "formatString": "delta",
                                   "dax": "{baseRef} - 1"}
    ecrire_config(c, conf)
    gm.generate(modele(c), copy.deepcopy(conf), dry_run=False, remove_orphans=False,
                log=lambda *a: None)
    ct = onglet_config(c, 1300, 900)
    dlg = ct._dlg_reglages
    ct._committer_vue()
    ct._load_global()
    ct.lbl_reglages_fichier.setText("measures_config.json")
    dlg.resize(1120, 720)
    dlg.show()
    tour()
    for cle, _nom in ct.PAGES_REGLAGES:
        ct.aller_reglages(cle)
        sauver(dlg, f"reglages_{cle}")
    dlg.hide()
    fermer(ct)


# --------------------------------------------------- 3.1 Variations, 3.2 Jetons
def variations():
    c = copie("variations")
    colonnes_td(c, {"unite": {"Weight": "kg", "Total Steps": "pas", "Body Fat %": "%"},
                    "agregat": {"Weight": "AVERAGEX(VALUES({date}), {baseRef})",
                                "Total Steps": "SUMX(VALUES({date}), {baseRef})"},
                    "filtres": {"Weight": "ALLSELECTED('Weight LOCF')",
                                "Total Steps": "ALLSELECTED('steps'), ALLSELECTED('dim_Date')"}})
    M = modele(c)
    conf = config(c)
    ajouter_cibles(M, ["Weight", "Total Steps"], variations=(), branches=())
    conf["kpiMeasureFolders"] = [{"folder": "_cibles", "calcul": "Cible"}]
    conf["variations"]["YTD"]["appliesToCibles"] = True
    conf["hardcodedAttributes"] = {"tokens": {"unite": "unite", "agregat": "agregat",
                                              "filtres": "filtres"}}
    conf["variations"]["MoM %"] = copy.deepcopy(MOM)
    conf["variations"]["Part du total"] = {
        "namePattern": "{base} part du total", "formatString": "0.0 %",
        "dax": "DIVIDE({baseRef}, CALCULATE({baseRef}, <<filtres>>))"}
    conf["variations"]["Écart cible"] = copy.deepcopy(ECART_CIBLE)
    conf["variations"]["Libellé"] = {
        "namePattern": "{base} libellé", "formatString": "text",
        "dax": "FORMAT({baseRef}, {baseFormatString}) & \" <<unite>>\""}
    ecrire_config(c, conf)
    gm.generate(M, copy.deepcopy(conf), dry_run=False, remove_orphans=True, log=lambda *a: None)
    ct = onglet_config(c, 1560, 1000)
    ct._populate_list(select="MoM %")
    tour()
    ct.lbl_biblio.setText("Bibliothèque : catalogue_variations.json  "
                          "(mémorisée pour tous les projets)")
    ct._details_apercu()
    ap = ct.arbre_apercu
    for i in range(ap.topLevelItemCount()):
        if ap.topLevelItem(i).text(0).endswith("Weight MoM %"):
            ap.expandItem(ap.topLevelItem(i))
    sauver(ct, "variations_formulaire")
    f = ct.fenetre_jetons
    f.resize(1120, 780)
    f.montrer()
    tour()
    ct._rafraichir_jetons()
    tour()
    ct.explorateur_jetons.choisir("Weight cible", "YTD")
    sauver(f, "jetons_explorateur_cible")
    f.hide()
    fermer(ct)


# ---------------------------------------------------- 3.3 Arbre des mesures
def arbre():
    c = copie("arbre")
    M = modele(c)
    conf = config(c)
    ajouter_cibles(M, ["Weight", "Total Steps"], variations=(), branches=())
    conf["kpiMeasureFolders"] = [{"folder": "_cibles", "calcul": "Cible"}]
    conf["variations"]["YTD"]["appliesToCibles"] = True
    conf["variations"]["MoM %"] = copy.deepcopy(MOM)
    conf["variations"]["Écart cible"] = copy.deepcopy(ECART_CIBLE)
    ecrire_config(c, conf)
    gm.generate(M, copy.deepcopy(conf), dry_run=False, remove_orphans=True, log=lambda *a: None)
    ct = onglet_config(c, 1420, 960)
    # en mémoire seulement : une variation modifiée, une nouvelle
    ct._config["variations"]["MoM %"]["description"] = "Évolution de {base} sur un mois"
    ct._config["variations"]["Mois précédent"] = {
        "namePattern": "{base} mois précédent", "formatString": "inherit",
        "dax": "CALCULATE({baseRef}, DATEADD({date}, -1, MONTH))"}
    ct.inner.setCurrentIndex(tc.IDX_ARBRE)
    tour()
    ct._rafraichir_arbre()
    tour()
    v = ct.arbre_mesures

    def montrer(*noms):
        v._tout(False)
        for nom in noms:
            i = v.element(nom)
            while i is not None:
                i.setExpanded(True)
                i = i.parent()

    montrer("Weight YTD", "Weight cible")
    v.choisir("Weight YTD MoM %")
    tour()
    v.split.setSizes([520, 300])
    sauver(v, "arbre_par_kpi")
    from tabs.arbre_mesures import COL_NOM
    v.cmb_rangement.setCurrentIndex(v.cmb_rangement.findData("variation"))
    tour()
    v._tout(False)
    for i in range(v.arbre.topLevelItemCount()):
        g = v.arbre.topLevelItem(i)
        if g.text(COL_NOM) in ("MoM %", "YTD"):
            g.setExpanded(True)
            for j in range(g.childCount()):
                if g.child(j).text(COL_NOM) == "YTD › MoM %":
                    g.child(j).setExpanded(True)
    v.choisir("Total Steps MoM %")
    sauver(v, "arbre_par_variation")
    fermer(ct)


# ------------------------------------------------- 3.4 Paramètres de champ
def parametres():
    c = copie("parametres")
    gm.generate(modele(c), config(c), dry_run=False, remove_orphans=False, log=lambda *a: None)
    ct = onglet_config(c, 1420, 1040)
    ct.inner.setCurrentIndex(tc.IDX_PARAM)
    tour()
    ct._rafraichir_parametres()
    tour()
    ed, ap = ct.g_fp_tables, ct.apercu_fp

    def choisir(nom):
        for i in range(ed.liste.count()):
            if ed.liste.item(i).text() == nom:
                ed.liste.setCurrentRow(i)
        tour()

    choisir("P_Indicateurs_parCalcul")
    ap.montrer_table("P_Indicateurs_parCalcul", "Weight")
    page = ct.inner.currentWidget()
    page.setSizes([430, 560])
    sauver(page, "parametres_onglet")
    # une table neuve : YTD seulement, sans les cibles
    ed._specs.append(dict(copy.deepcopy(gm.FP_TABLE_DEFAUT), name="P_YTD_seul"))
    ed._rafraichir_liste(len(ed._specs) - 1)
    ed.changed.emit()
    ed.chk_cibles.setChecked(False)
    from tabs.fp_tables import HORS_BRANCHE
    ed.cmb_branches.set_items([HORS_BRANCHE] + ed._vocab["branches"], ["YTD"])
    ed._edite()
    tour()
    ct._rafraichir_parametres()
    tour()
    sauver(page, "parametres_ytd")
    fermer(ct)


# ---------------------------------------------------------------- 4. Rapport
def rapport():
    c = copie("rapport")
    colonnes_td(c, {"couleur_fill": {"Average Sleep Duration": "#1F3A5F",
                                     "Average Steps": "#1E5B4F", "Body Fat %": "#6B2D4A",
                                     "Total Steps": "#7A4B12", "Weight": "#3F3A73"},
                    "couleur_text": {"Average Sleep Duration": "#DCE9F7",
                                     "Average Steps": "#D8F3E8", "Body Fat %": "#F8DDE9",
                                     "Total Steps": "#FDEBD0", "Weight": "#E4E1FA"}})
    gm.generate(modele(c), config(c), dry_run=False, remove_orphans=False, log=lambda *a: None)
    import propagate_cf as pc
    from tabs.dialog_couleurs import CouleursDialog
    from tabs.dialog_sources import SourcesDialog
    from tabs.tab_report import ReportTab
    proj = Project(c / (P + ".pbip"))
    rt = ReportTab()
    rt.resize(1200, 620)
    rt.show()
    rt.set_project(proj)
    sauver(rt, "rapport_onglet")
    d = SourcesDialog(pc.groupes_path(proj.report_dir), rt._kpis, rt,
                      source=rt._sources_path(), analyse=rt._analyse())
    d.resize(1500, 760)
    d.show()
    sauver(d, "rapport_grille")
    d.reject()
    td = rt._td_spec()
    d = CouleursDialog(td["path"], key_col=td["keyColumn"], fill_col=td["fillColumn"],
                       text_col=td["textColumn"], model_kpis=rt._kpis, parent=rt)
    d.resize(900, 460)
    d.show()
    sauver(d, "rapport_couleurs")
    d.reject()
    rt.close()


SECTIONS = {"reglages": reglages, "variations": variations, "arbre": arbre,
            "parametres": parametres, "rapport": rapport}

if __name__ == "__main__":
    voulues = sys.argv[1:] or list(SECTIONS)
    try:
        for s in voulues:
            print("==", s)
            SECTIONS[s]()
    finally:
        effacer(BASE)
        print("copies supprimées :", not BASE.exists())
