"""Captures d'écran de PBIdouille pour le guide — sur une COPIE du projet
Fitbit, avec un magasin de réglages jetable (rien de réel n'est touché)."""
import os, sys, shutil, stat, tempfile
from pathlib import Path

OUTIL = Path(__file__).resolve().parents[3]          # PBIdouille/
SRC = OUTIL.parent / "PowerBI"                        # les projets
OUT = Path(__file__).resolve().parent / "png"
OUT.mkdir(exist_ok=True)
BASE = Path(r"C:\Users\Public\PBIdouille_demo")
shutil.rmtree(BASE, onerror=lambda f, x, e: (os.chmod(x, stat.S_IWRITE), f(x))) if BASE.exists() else None
TMP = BASE / "Fitbit"
TMP.mkdir(parents=True)
NOM = "Fitbit"
for s in (".Report", ".SemanticModel"):
    shutil.copytree(SRC / (NOM + s), TMP / (NOM + s))
for f in (NOM + ".pbip", "measures_config.json", "TD_Indicateurs.xlsx",
          "propagation.json", "catalogue_variations.json"):
    if (SRC / f).exists():
        shutil.copy2(SRC / f, TMP / f)

sys.path.insert(0, str(OUTIL))
sys.path.insert(0, str(OUTIL / "bidouille"))
sys.path.insert(0, str(OUTIL / "bidouille" / "moteurs"))

# la COPIE est générée avec la version actuelle (orphelines supprimées) : plus
# de mesures Switch à l'écran, comme chez un usager qui part de zéro
import json as _json                               # noqa: E402
import generate_measures as _gm                    # noqa: E402
_gm.generate(TMP / (NOM + ".SemanticModel"),
             _json.loads((TMP / "measures_config.json").read_text(encoding="utf-8")),
             dry_run=False, remove_orphans=True, log=lambda *a: None)

from qtpy.QtCore import QSettings, QTimer          # noqa: E402
from qtpy.QtWidgets import QApplication, QDialog   # noqa: E402
from core import project as prj                    # noqa: E402
from core import edition                           # noqa: E402
edition.MARQUEUR_DEV = Path("Z:/aucun/.dev")      # captures en PRODUCTION
os.environ.pop("PBIDOUILLE_DEV", None)

prj.ORG_REGLAGES = "ChopChop"
prj.APP_REGLAGES = "BIdouille_CAPTURES"
prj._ANCIEN_MAGASIN = ("PBIdouille_CAPTURES", "PBIdouille_CAPTURES")
prj.reglages().clear()
QSettings(*prj._ANCIEN_MAGASIN).clear()
prj.reglages().setValue("biblio_path", str(TMP / "catalogue_variations.json"))

import app as appmod                               # noqa: E402
from core.theme import apply_app_theme             # noqa: E402

qapp = QApplication.instance() or QApplication(sys.argv)
apply_app_theme(qapp, appmod.APP_EMOJI, "ChopChop.BIdouille.Captures")


def pump(ms=300):
    end = __import__("time").time() + ms / 1000
    while __import__("time").time() < end:
        qapp.processEvents()


def snap(w, name):
    pump(400)
    w.grab().save(str(OUT / (name + ".png")))
    print("capture", name, w.width(), "x", w.height())


DIALOG_NAMES = []


def fake_exec(self, *a):
    self.resize(max(self.width(), 900), max(self.height(), 600))
    if DIALOG_NAMES:
        nm = DIALOG_NAMES.pop(0)
        w, h = SIZES.get(nm, (self.width(), self.height()))
        self.resize(w, h)
        self.show()
        snap(self, nm)
    self.reject()
    return 0


SIZES = {"reglages": (1100, 860), "grille_sources": (1500, 820),
         "bibliotheque": (1100, 640), "couleurs": (900, 640)}
QDialog.exec = fake_exec
QDialog.exec_ = fake_exec

win = appmod.BidouilleWindow()
win.resize(1700, 960)
win.show()
win._set_project(TMP / (NOM + ".pbip"))
pump(3000)

tabs = win.tabs
# la barre du haut et les onglets, à la largeur que la diapo « Lancer l'app »
# numérote (build_deck.py) ; la même image sert à l'article 1 de la doc
from qtpy.QtCore import QRect                      # noqa: E402
win.resize(1245, 960)
pump(1500)
barre = win.grab(QRect(0, 0, 1245, 84))
barre.save(str(OUT / "barre_ruban.png"))
barre.save(str(OUTIL / "docs" / "ressources" / "images" / "barre_du_haut.png"))
print("capture barre_ruban et barre_du_haut")
win.resize(1700, 960)
pump(1500)
# Rapport : propagation en APERÇU (dry-run coché par défaut, rien d'écrit)
tabs.setCurrentIndex(1)
pump(1500)
win.tab_report._run_propagate()
pump(8000)
snap(win, "onglet_rapport")
tabs.setCurrentWidget(win.tab_chopchop)     # son rang dépend de l'édition
pump(5000)
snap(win, "onglet_chopchop")
tabs.setCurrentIndex(0)
pump(1500)
snap(win, "onglet_mesures")
# Mesures avec la colonne Lancements : génération en APERÇU
win._afficher_journal(True, memoriser=False)
pump(800)
assert win.tab_config.model_panel.chk_dry.isChecked()
win.tab_config.model_panel._run()
pump(10000)
snap(win, "onglet_mesures_generation")
win._afficher_journal(False, memoriser=False)
pump(500)
DIALOG_NAMES[:] = ["reglages"]
win.tab_config.ouvrir_reglages()
DIALOG_NAMES[:] = ["bibliotheque"]
win.tab_config._ouvrir_biblio()
tabs.setCurrentIndex(1)
pump(800)
DIALOG_NAMES[:] = ["grille_sources"]
win.tab_report._open_sources_dialog()
DIALOG_NAMES[:] = ["couleurs"]
win.tab_report._open_colors_dialog()

prj.reglages().clear()
win.close()
pump(500)
shutil.rmtree(BASE, onerror=lambda f, x, e: (os.chmod(x, stat.S_IWRITE), f(x))) if BASE.exists() else None
print("copie supprimee :", not BASE.exists())
