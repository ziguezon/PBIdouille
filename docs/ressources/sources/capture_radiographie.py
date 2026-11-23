"""Les captures de l'article 6 (Radiographie) : la vue d'ensemble et les trois
vues de l'onglet.

    py docs\\ressources\\sources\\capture_radiographie.py

Sur une COPIE du projet de démonstration, avec un magasin de réglages jetable.
Seul l'onglet est capturé, journal masqué : aucun chemin de l'usager ne
paraît dans les images."""
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
OUTIL = ICI.parents[2]                               # PBIdouille/
IMAGES = ICI.parent / "images"
sys.path[:0] = [str(OUTIL), str(OUTIL / "bidouille"), str(OUTIL / "bidouille" / "moteurs"),
                str(OUTIL / "tests")]
import chemins                                       # noqa: E402

PBI = chemins.PROJETS
NOM = chemins.PROJET_DEMO
c = Path(tempfile.mkdtemp(prefix="pbid_radio_"))
for s in (".SemanticModel", ".Report"):
    shutil.copytree(PBI / (NOM + s), c / (NOM + s), ignore=shutil.ignore_patterns(".pbi", "cache.abf"))
for f in (NOM + ".pbip", "measures_config.json", "TD_Indicateurs.xlsx", "propagation.json"):
    if (PBI / f).exists():
        shutil.copy2(PBI / f, c / f)
os.environ["PBIDOUILLE_PROJETS"] = str(c)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
chemins.PROJETS = c

from _fixture import reglages_jetables              # noqa: E402
reglages_jetables("capture_radiographie")
from core.project import reglages                    # noqa: E402
reglages().setValue("last_pbip", str(c / (NOM + ".pbip")))

from qtpy.QtWidgets import QApplication, QMessageBox  # noqa: E402
import app as appmod                                 # noqa: E402

QMessageBox.exec = QMessageBox.exec_ = lambda *a, **k: 0
qa = QApplication.instance() or QApplication([])
appmod.apply_app_theme(qa, appmod.APP_EMOJI, "PBIdouille.Radiographie")
w = appmod.BidouilleWindow()
w.resize(1400, 820)
w.show()
w._afficher_journal(False, memoriser=False)
w.tabs.setCurrentWidget(w.tab_radio)
t = w.tab_radio


def attendre():
    for _ in range(6):
        qa.processEvents()


def capturer(nom):
    attendre()
    t.grab().save(str(IMAGES / nom))
    print("écrit :", (IMAGES / nom).relative_to(OUTIL))


attendre()
r = t.res

# 0. La vue d'ensemble : la fiche, avant tout choix
t.vues.setCurrentWidget(t.arbre_pages)
capturer("radiographie_ensemble.png")

# 0b. Le lignage : une source choisie, sa chaîne allumée jusqu'aux visuels
t.vues.setCurrentWidget(t.vue_lignage)
w.resize(1900, 820)              # le graphe a besoin de largeur
attendre()
t._split.setSizes([1400, 480])
vl = t.vue_lignage
vl.ajuster(largeur_seule=True)
source = next(n for n, x in vl.graphe["noeuds"].items()
              if x["genre"] == "source" and x["detail"] == "ODBC")
vl.choisir(source)
capturer("radiographie_lignage.png")
# … et la chaîne seule d'un visuel, de ses sources à lui
visuel = next(n for n, x in vl.graphe["noeuds"].items() if x["libelle"].startswith("Courbes"))
vl.choisir(visuel)
vl.cb_chaine.setChecked(True)
vl.ajuster()                     # la chaîne entière, de la source au visuel
capturer("radiographie_lignage_chaine.png")
vl.choisir(None)
w.resize(1400, 820)
attendre()
t._split.setSizes([t.width() * 3 // 5, t.width() * 2 // 5])

# 1. Par page : un visuel filtré, déplié (champs, mène à, filtré par)
v = max((v for v in r["visuels"] if not v["segment"]),
        key=lambda v: (sum(f["actif"] for f in v["filtres"]) + len(v["segments"]),
                       sum(c["genre"] == "mesure" for c in v["champs"])))
t.aller_a("visuel", (v["page_id"], v["id"]))
it = t.arbre_pages.currentItem()
it.setExpanded(True)
for i in range(it.childCount()):
    if it.child(i).text(0).startswith("Filtré par"):
        it.child(i).setExpanded(True)
capturer("radiographie_pages.png")

# 1b. Par page, seulement ce qui filtre : Mesures et Colonnes éteintes, tout déplié
for cle in ("mesures", "colonnes"):
    t.puces_pages.bouton(cle).setChecked(False)
t._deplier(True)
t.arbre_pages.scrollToTop()
capturer("radiographie_filtres.png")
for cle in ("mesures", "colonnes"):
    t.puces_pages.bouton(cle).setChecked(True)
t._deplier(False)

# 2. Par KPI : une variation affichée, dans sa famille
nom = next(x["nom"] for f in r["kpis"] for x in f["membres"] if x["visuels"] and x["par"] == "dax")
t.aller_a("mesure", nom)
capturer("radiographie_kpi.png")

# 3. Par colonne : celle qui sert au plus de façons différentes
i, col = max(enumerate(r["colonnes_utilisees"]),
             key=lambda ic: (len({u["genre"] for u in ic[1]["usages"]}), len(ic[1]["usages"])))
a = t.arbre_cols
t.vues.setCurrentWidget(a)
for k in range(a.topLevelItemCount()):
    top = a.topLevelItem(k)
    for j in range(top.childCount()):
        if top.child(j).data(0, 256) == ("colonne_rapport", i):
            top.child(j).setExpanded(True)
            a.setCurrentItem(top.child(j))
            a.scrollToItem(top.child(j))
capturer("radiographie_colonnes.png")

w.close()
shutil.rmtree(c, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
