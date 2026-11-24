"""La vue d'ensemble numérotée de la documentation (docs/README.md) : la
fenêtre de l'app, et sur chaque élément le numéro de son article.

    py docs\\ressources\\sources\\capture_vue.py

Sur une COPIE du projet de démonstration, avec un magasin de réglages jetable,
en édition de développement pour que l'onglet Wireframe (7) y soit. Les
numéros sont posés d'après la position réelle des widgets : un bouton qui
bouge emmène son numéro."""
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
OUTIL = ICI.parents[2]                               # PBIdouille/
SORTIE = ICI.parent / "images" / "vue_d_ensemble.png"
sys.path[:0] = [str(OUTIL), str(OUTIL / "bidouille"), str(OUTIL / "bidouille" / "moteurs"),
                str(OUTIL / "tests")]
import chemins                                       # noqa: E402

PBI = chemins.PROJETS
NOM = chemins.PROJET_DEMO
c = Path(tempfile.mkdtemp(prefix="pbid_vue_"))
for s in (".SemanticModel", ".Report"):
    shutil.copytree(PBI / (NOM + s), c / (NOM + s), ignore=shutil.ignore_patterns(".pbi", "cache.abf"))
for f in (NOM + ".pbip", "measures_config.json", "TD_Indicateurs.xlsx", "propagation.json",
          "catalogue_variations.json"):
    if (PBI / f).exists():
        shutil.copy2(PBI / f, c / f)
os.environ["PBIDOUILLE_PROJETS"] = str(c)
os.environ["PBIDOUILLE_DEV"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
chemins.PROJETS = c

from _fixture import reglages_jetables              # noqa: E402
reglages_jetables("vue_d_ensemble")
from core.project import reglages                    # noqa: E402
reglages().setValue("last_pbip", str(c / (NOM + ".pbip")))
reglages().setValue("biblio_path", str(c / "catalogue_variations.json"))

from PIL import Image, ImageDraw, ImageFont          # noqa: E402
from qtpy.QtCore import QPoint                       # noqa: E402
from qtpy.QtWidgets import QApplication, QPushButton  # noqa: E402
import app as appmod                                 # noqa: E402

qa = QApplication.instance() or QApplication([])
appmod.apply_app_theme(qa, appmod.APP_EMOJI, "PBIdouille.Vue")
w = appmod.BidouilleWindow()
w.resize(1500, 860)
w.show()
for _ in range(8):
    qa.processEvents()
# le chemin de la bibliothèque est celui de la copie temporaire, qui nomme le
# dossier de l'usager : la capture montre le nom du fichier seul
w.tab_config.lbl_biblio.setText("Bibliothèque : catalogue_variations.json  "
                                "(mémorisée pour tous les projets)")
w.tab_config.lbl_biblio.setStyleSheet("")
qa.processEvents()
brut = Path(tempfile.gettempdir()) / "pbid_vue_brute.png"
w.grab().save(str(brut))


def coin(widget, rect=None):
    """Le coin haut-droit d'un widget (ou d'un rectangle dans lui), dans la fenêtre."""
    r = rect if rect is not None else widget.rect()
    p = widget.mapTo(w, QPoint(r.right(), r.top()))
    return p.x(), p.y()


cfg = w.tab_config
barre, sous = w.tabs.tabBar(), cfg.inner.tabBar()
reglages_btn = next(b for b in w.findChildren(QPushButton) if "Réglages" in b.text())
onglet = {w.tabs.tabText(i).split()[0]: i for i in range(w.tabs.count())}
sous_onglet = {cfg.inner.tabText(i): i for i in range(cfg.inner.count())}
reperes = [
    ("1", coin(w.btn_projet)),
    ("2", coin(reglages_btn)),
    ("3", coin(barre, barre.tabRect(onglet["Mesures"]))),
    ("3.1", coin(sous, sous.tabRect(sous_onglet["Variations"]))),
    ("3.2", coin(cfg.btn_jetons)),
    ("3.3", coin(sous, sous.tabRect(sous_onglet["Arbre des mesures"]))),
    ("3.4", coin(sous, sous.tabRect(sous_onglet["Paramètres de champ"]))),
    ("3.5", coin(sous, sous.tabRect(sous_onglet["JSON brut"]))),
    ("4", coin(barre, barre.tabRect(onglet["Rapport"]))),
    # les sources sont la vue Par source de la Radiographie : un seul onglet
    ("5 · 6", coin(barre, barre.tabRect(onglet["Radiographie"]))),
    ("7", coin(barre, barre.tabRect(onglet["Wireframe"]))),
    ("8", coin(barre, barre.tabRect(onglet["ChopChop"]))),
]
w.close()

# la capture, avec une marge pour les numéros qui débordent du bord
MARGE = 16
img = Image.open(brut).convert("RGB")
toile = Image.new("RGB", (img.width + 2 * MARGE, img.height + 2 * MARGE), (15, 22, 41))
toile.paste(img, (MARGE, MARGE))
d = ImageDraw.Draw(toile)
police = ImageFont.truetype("C:/Windows/Fonts/seguisb.ttf", 15)
# un orange vif : le vert du thème s'y confondait (même valeur que le
# REPERE de build_deck.py)
REPERE, FONCE = (255, 138, 31), (11, 17, 32)
for texte, (x, y) in reperes:
    l = d.textlength(texte, font=police)
    larg, haut = max(26, l + 14), 26
    cx, cy = x + MARGE + 3, y + MARGE - 1
    boite = (cx - larg / 2, cy - haut / 2, cx + larg / 2, cy + haut / 2)
    d.rounded_rectangle(boite, radius=haut / 2, fill=REPERE, outline=FONCE, width=2)
    d.text((cx, cy), texte, font=police, fill=FONCE, anchor="mm")
toile.save(SORTIE)
print("écrit :", SORTIE.relative_to(OUTIL), toile.size, "·", len(reperes), "repères")
shutil.rmtree(c, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
