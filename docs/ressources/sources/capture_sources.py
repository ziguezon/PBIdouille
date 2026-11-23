"""Les captures de l'article 5 (Sources de données) : la vue Par source de la
Radiographie, une pastille, une table calculée et les tables qu'elle lit,
puis la fiche de ce qui dépend d'une table.

    py docs\\ressources\\sources\\capture_sources.py

Sur une COPIE du projet de démonstration, avec un magasin de réglages jetable.
Les chemins des fichiers lus par le modèle sont remplacés par C:\\Donnees\\ dans
la copie, et seul l'onglet est capturé, journal masqué : aucun chemin de
l'usager ne paraît dans les images."""
import os
import re
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
c = Path(tempfile.mkdtemp(prefix="pbid_sources_"))
for s in (".SemanticModel", ".Report"):
    shutil.copytree(PBI / (NOM + s), c / (NOM + s), ignore=shutil.ignore_patterns(".pbi", "cache.abf"))
for f in (NOM + ".pbip", "measures_config.json", "TD_Indicateurs.xlsx", "propagation.json"):
    if (PBI / f).exists():
        shutil.copy2(PBI / f, c / f)

# File.Contents("C:\…\x.xlsx") -> File.Contents("C:\Donnees\x.xlsx")
CHEMIN_RE = re.compile(r'File\.Contents\("[A-Za-z]:\\[^"]*\\([^"\\]+)"')
for t in (c / (NOM + ".SemanticModel") / "definition").rglob("*.tmdl"):
    texte = t.read_text(encoding="utf-8")
    neuf = CHEMIN_RE.sub(lambda m: 'File.Contents("C:\\Donnees\\' + m.group(1) + '"', texte)
    if neuf != texte:
        t.write_text(neuf, encoding="utf-8")

os.environ["PBIDOUILLE_PROJETS"] = str(c)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
chemins.PROJETS = c

from _fixture import reglages_jetables              # noqa: E402
reglages_jetables("capture_sources")
from core.project import reglages                    # noqa: E402
reglages().setValue("last_pbip", str(c / (NOM + ".pbip")))

from qtpy.QtWidgets import QApplication, QMessageBox  # noqa: E402
import app as appmod                                 # noqa: E402

QMessageBox.exec = QMessageBox.exec_ = lambda *a, **k: 0
qa = QApplication.instance() or QApplication([])
appmod.apply_app_theme(qa, appmod.APP_EMOJI, "PBIdouille.Sources")
w = appmod.BidouilleWindow()
w.resize(1400, 700)
w.show()
w._afficher_journal(False, memoriser=False)
w.tabs.setCurrentWidget(w.tab_radio)
radio = w.tab_radio
radio.vues.setCurrentWidget(radio.vue_sources)
t = radio.vue_sources


def attendre():
    for _ in range(6):
        qa.processEvents()


def capturer(nom):
    attendre()
    radio.grab().save(str(IMAGES / nom))
    print("écrit :", (IMAGES / nom).relative_to(OUTIL))


attendre()
capturer("sources_onglet.png")
t.puces.choisir("type:ODBC")
capturer("sources_odbc.png")
t.puces.choisir("tout")
radio.ed_filtre.setText("Weight LOCF")
capturer("sources_calculees.png")
radio.ed_filtre.clear()
for i in range(t.arbre.topLevelItemCount()):
    if t.arbre.topLevelItem(i).text(0) == "weight obs":
        t.arbre.setCurrentItem(t.arbre.topLevelItem(i))
capturer("sources_dependances.png")

w.close()
shutil.rmtree(c, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
