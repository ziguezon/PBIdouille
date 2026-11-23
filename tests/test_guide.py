# -*- coding: utf-8 -*-
"""Les schémas du guide, dans l'app.

    py tests\\test_guide.py

Vérifie :
  1. chaque page a son image, lisible, et la table des pages est celle de
     l'exporteur (docs\\ressources\\sources\\exporter_aide.ps1) — sinon l'un régénérerait
     des images que l'autre ne montre pas ;
  2. les images ne sont pas ignorées par git (le paquet ne prend que les
     fichiers suivis : ignorées, elles manqueraient dans le paquet) ;
  3. une seule fenêtre, non modale ; la rouvrir change de page ;
  4. les liens « ▣ Schéma » sont là où l'on en a besoin et ouvrent la bonne
     page : Mesures (variations, jetons), Rapport (propagation), Réglages
     (paramètres de champ) ; le bouton Guide est dans la barre du haut.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
FIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FIT))
sys.path.insert(0, str(FIT / "bidouille"))
sys.path.insert(0, str(FIT / "bidouille" / "moteurs"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import reglages_jetables                          # noqa: E402

reglages_jetables("guide")

from qtpy.QtWidgets import QApplication, QPushButton, QToolButton  # noqa: E402

app = QApplication.instance() or QApplication([])

import tabs.dialog_guide as dg                                   # noqa: E402

_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


print("1. chaque page a son image, et l'exporteur produit les mêmes")
from qtpy.QtGui import QPixmap                                   # noqa: E402
for cle, titre, f in dg.PAGES:
    pix = QPixmap(str(dg.AIDE / f))
    check(f"{f} lisible ({pix.width()}x{pix.height()})", not pix.isNull()
          and pix.width() >= 1200)
ps1 = (FIT / "docs" / "ressources" / "sources" / "exporter_aide.ps1")
if ps1.exists():
    texte_ps1 = ps1.read_text(encoding="utf-8-sig")
    # deux tables : l'aide de l'app, puis les diapos des articles de docs\
    # (les chemins entre guillemets : ceux du code, pas ceux de l'en-tête)
    aide = texte_ps1[texte_ps1.index('"bidouille\\aide"'):texte_ps1.index('"docs\\ressources\\guide"')]
    guide = texte_ps1[texte_ps1.index('"docs\\ressources\\guide"'):]
    exportes = re.findall(r'"([a-z_]+\.png)"\s*=', aide)
    check("l'exporteur écrit exactement les images des pages",
          sorted(exportes) == sorted(f for _, _, f in dg.PAGES))
    du_guide = set(re.findall(r'"([a-z_-]+\.png)"\s*=', guide))
    citees = {m for md in (FIT / "docs").rglob("*.md")
              for m in re.findall(r"ressources/guide/([a-z_-]+\.png)",
                                  md.read_text(encoding="utf-8"))}
    check(f"chaque diapo citée par la documentation est exportée ({len(citees)})",
          citees and citees <= du_guide)
else:
    print("  (exporteur absent : docs\\ressources\\sources n'est pas dans ce paquet)")

print("2. les images ne sont pas ignorées par git")
r = subprocess.run(["git", "check-ignore"] + [str(dg.AIDE / f) for _, _, f in dg.PAGES],
                   cwd=FIT, capture_output=True, text=True)
if r.returncode == 128:
    print("  (pas de dépôt git ici)")
else:
    check("aucune n'est ignorée", r.stdout.strip() == "")

print("3. une seule fenêtre, non modale")
import app as appmod                                             # noqa: E402
fen = appmod.BidouilleWindow()
d1 = dg.ouvrir_guide(fen, "jetons")
check("ouverte sur la page demandée", d1.liste.currentItem().text() == "Les jetons du DAX")
check("non modale", not d1.isModal())
d2 = dg.ouvrir_guide(fen.tab_report, "propagation")
check("la rouvrir depuis un onglet ramène LA MÊME fenêtre", d2 is d1)
check("… sur la nouvelle page", d1.liste.currentItem().text() == "Le formatage se propage")
check("l'image est affichée", d1.image.pixmap() is not None
      and not d1.image.pixmap().isNull())
d1.close()

print("4. les liens « ▣ Schéma » et le bouton Guide")


def liens(w):
    return [b for b in w.findChildren(QToolButton) if b.text().startswith("▣")]


def page_ouverte_par(b):
    b.click()
    app.processEvents()
    d = getattr(b.window(), "_guide_dialog", None)
    t = d.liste.currentItem().text() if d else None
    if d:
        d.close()
    return t


l_mes = liens(fen.tab_config)
titres = {page_ouverte_par(b) for b in l_mes if b.window() is fen}
check("Mesures : variations, jetons et paramètres de champ (leur onglet)",
      {"Les variations se ramifient", "Les jetons du DAX",
       "Les paramètres de champ"} <= titres)
check("Rapport : propagation",
      [page_ouverte_par(b) for b in liens(fen.tab_report)] == ["Le formatage se propage"])
reg = fen.tab_config._dlg_reglages
check("Réglages : plus de lien vers les paramètres de champ (ils ont quitté la fenêtre)",
      "Les paramètres de champ" not in [page_ouverte_par(b) for b in liens(reg)])
check("le bouton Guide est dans la barre du haut",
      any(b.text() == "Guide" for b in fen.findChildren(QPushButton)))

fen.close()
print()
print("TOUT OK" if _ok else "DES ECHECS")
sys.exit(0 if _ok else 1)
