# -*- coding: utf-8 -*-
"""Wireframe : « Aligner les bords » (core/alignement.py et le bouton).

    py tests\\test_alignement.py

1. Le module seul, sur des mises en page inventées : bords presque collés,
   presque alignés, près du bord de page ; gouttières et marges ; ce qui ne
   doit PAS bouger (une gouttière voulue, un trait de séparation, un grand
   vide) ; des entiers ; un deuxième passage qui ne change rien.
2. L'onglet, sur une COPIE du projet de démonstration, avec un magasin de
   réglages jetable : décaler des visuels de quelques pixels, aligner,
   retrouver une page propre, des groupes qui épousent encore leur contenu,
   des fichiers en entiers, et Ctrl+Z.
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

from core import alignement as al                                     # noqa: E402

_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def entiers(boites):
    return all(float(v).is_integer() for b in boites.values() for v in b)


print("1. le module")
PAGE = (0, 0, 900, 420)
b = {"A": (2, 3, 300, 200), "B": (303, 0, 600, 198), "C": (603.4, 1, 898, 201)}
out, _n = al.aligner(b, cadre=PAGE, tolerance=5)
check("presque collés : collés", out["A"][2] == out["B"][0] and out["B"][2] == out["C"][0])
check("près du bord de page : sur le bord",
      out["A"][0] == 0 and out["A"][1] == 0 and out["C"][2] == 900)
check("presque alignés : alignés",
      len({o[1] for o in out.values()}) == 1 and len({o[3] for o in out.values()}) == 1)
check("tout en entiers", entiers(out))
check("un deuxième passage ne change rien", al.aligner(out, cadre=PAGE)[0] == out)

# gouttières 10, 12, 10, et une deuxième rangée alignée sur B et C
b = {"A": (0, 0, 200, 100), "B": (210, 0, 400, 100), "C": (412, 0, 600, 100),
     "D": (610, 0, 900, 100), "E": (412, 110, 600, 300)}
out, n = al.aligner(b, cadre=PAGE, tolerance=5)
gout = [out["B"][0] - out["A"][2], out["C"][0] - out["B"][2], out["D"][0] - out["C"][2]]
check(f"gouttières presque égales : égales ({gout})", gout == [10, 10, 10] and n >= 1)
check("ce qui était aligné sur la ligne déplacée la suit",
      out["E"][0] == out["C"][0] and out["E"][2] == out["C"][2])

b = {"A": (0, 0, 300, 100), "B": (316, 0, 600, 100), "C": (610, 0, 900, 100)}
out, _n = al.aligner(b, cadre=PAGE, tolerance=5)
check("une gouttière bien différente (16 contre 10) reste",
      out["B"][0] - out["A"][2] == 16 and out["C"][0] - out["B"][2] == 10)

b = {"A": (0, 0, 440, 200), "B": (452, 0, 900, 200),
     "C": (0, 212, 440, 411), "D": (452, 212, 900, 411)}
out, _n = al.aligner(b, cadre=PAGE, tolerance=5)
check("une marge ne prend pas la valeur des gouttières (9 reste 9)",
      PAGE[3] - out["C"][3] == 9 and out["C"][1] - out["A"][3] == 12)

b = {"A": (10, 10, 300, 100), "T": (10, 104, 300, 105.5), "B": (10, 109, 300, 200)}
out, _n = al.aligner(b, cadre=PAGE, tolerance=5)
check("un trait de séparation garde son épaisseur",
      out["T"][3] - out["T"][1] >= 1)

b = {"A": (0, 0, 300, 100), "B": (400, 0, 700, 100)}
out, _n = al.aligner(b, cadre=PAGE, tolerance=5)
check("un grand vide n'est pas une gouttière", out["B"][0] == 400)

out, _n = al.aligner({"A": (3, 2, 297, 98)}, fixes=[(300, 0, 600, 100)],
                     cadre=None, tolerance=5)
check("un appui fixe attire sans bouger, et un bord sans appui suit l'autre",
      out["A"] == (6, 0, 300, 100))
out, _n = al.aligner({"A": (3, 2, 297, 98)}, fixes=[(300, 0, 600, 100)],
                     cadre=None, tolerance=1)
check("la tolérance borne l'attraction", out["A"] == (3, 2, 297, 98))

# ---------------------------------------------------------------------------
print("2. l'onglet")
PBI_OK = exiger_projet(PBI, PROJET_DEMO)
reglages_jetables("alignement")
from qtpy.QtWidgets import QApplication                               # noqa: E402

qapp = QApplication.instance() or QApplication([])
from core import report_reader                                        # noqa: E402
from core.project import Project                                      # noqa: E402
from tabs.tab_wireframe import WireframeTab                           # noqa: E402

PROJ = PROJET_DEMO
c = Path(tempfile.mkdtemp(prefix="pbid_align_"))
for s in (".SemanticModel", ".Report"):
    shutil.copytree(PBI / (PROJ + s), c / (PROJ + s),
                    ignore=shutil.ignore_patterns(".pbi", "cache.abf"))
shutil.copy2(PBI / (PROJ + ".pbip"), c / (PROJ + ".pbip"))
RAPPORT = c / (PROJ + ".Report")

w = WireframeTab()
w.set_project(Project(c / (PROJ + ".pbip")))
qapp.processEvents()
w.spn_tol.setValue(5)

# la page qui a le plus de groupes
compte = []
for i in range(w.cmb_pages.count()):
    w.cmb_pages.setCurrentIndex(i)
    qapp.processEvents()
    compte.append(sum(d["is_group"] for d in w._data.values()))
w.cmb_pages.setCurrentIndex(compte.index(max(compte)))
qapp.processEvents()
groupes = [k for k, d in w._data.items() if d["is_group"]]
feuilles = [k for k, d in w._data.items() if not d["is_group"]]
check("une page de la démo a des groupes", groupes and len(feuilles) >= 2)


def boite(d):
    return (d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"])


def epouse(gid):
    kids = [w._data[k] for k in w._children_of.get(gid, [])]
    u = (min(k["x"] for k in kids), min(k["y"] for k in kids),
         max(k["x"] + k["w"] for k in kids), max(k["y"] + k["h"] for k in kids))
    return max(abs(a - b) for a, b in zip(boite(w._data[gid]), u)) < 1e-6


# premier passage : la démo a des positions fractionnaires
w._select(None, False)
w._aligner()
propre = {k: boite(d) for k, d in w._data.items()}
check("la page finit en entiers", entiers(propre))
check("les groupes épousent encore leur contenu", all(epouse(g) for g in groupes))
check("les positions relatives suivent", all(
    abs((d["x"] - d["parent_x"]) - (d["x"] - w._data[d["parent"]]["x"])) < 1e-9
    for d in w._data.values() if d.get("parent") in w._data))

# décaler UN visuel de quelques pixels, aligner, retrouver la page propre.
# Seulement un visuel dont chaque bord est partagé (avec un autre visuel ou
# le bord de page) : un bord que rien ne partage n'a pas de « bonne place ».
W_, H_ = w._page_size()


def partages(k):
    b = propre[k]
    xs = [0.0, W_] + [v for j in feuilles if j != k for v in (propre[j][0], propre[j][2])]
    ys = [0.0, H_] + [v for j in feuilles if j != k for v in (propre[j][1], propre[j][3])]
    return b[0] in xs and b[2] in xs and b[1] in ys and b[3] in ys


eligibles = [k for k in feuilles if partages(k)]
check(f"des visuels à bords partagés ({len(eligibles)})", len(eligibles) >= 3)
revenus = []
for k, (dx, dy) in zip(eligibles, [(2.6, -1.7), (-2.2, 3.1), (1.4, 2.3), (-3.3, -0.6)] * 9):
    w._push_undo_geom()
    d = w._data[k]
    d["x"] += dx
    d["y"] += dy
    d["w"] -= dx / 2
    w._apply_geometry(k)
    w._select(None, False)
    w._aligner()
    apres = {j: boite(e) for j, e in w._data.items()}
    revenus.append(apres == propre)
    if apres != propre:
        for j in apres:
            if apres[j] != propre[j]:
                print("   ", j[:6], propre[j], "->", apres[j])
        break                   # la suite partirait d'une page fausse
check(f"chaque visuel décalé revient en place, et rien d'autre ne bouge "
      f"({sum(revenus)}/{len(revenus)})", all(revenus))

n_avant = len(w._undo)
w._aligner()
check("un passage de plus ne trouve rien à faire",
      len(w._undo) == n_avant and "Rien à aligner" in w.lbl_status.text())

# dans un groupe, un seul visuel sélectionné : il s'aligne sur le cadre du
# groupe et sur ses voisins, qui ne bougent pas
g = next(g for g in groupes
         if sum(not w._data[k]["is_group"] for k in w._children_of[g]) >= 2)
k = next(k for k in w._children_of[g] if not w._data[k]["is_group"])
w._set_scope(g)
w._push_undo_geom()
d = w._data[k]
d["x"] += 2
d["y"] += 1
w._apply_geometry(k)
w._select(k, False)
check("le bouton vise l'élément sélectionné", w._aligner_cible()[0] == [k])
w._aligner()
check("un élément sélectionné revient seul en place",
      {j: boite(e) for j, e in w._data.items()} == propre)
w._set_scope(None)

print("3. enregistrer, relire, annuler")
w._save_positions()
relu = {v["id"]: v for v in report_reader.visuals(RAPPORT, w._page_id)}
check("les fichiers relus donnent la page alignée",
      all(boite(relu[k]) == propre[k] for k in propre))
locales = []
for v in relu.values():
    pos = json.loads(Path(v["path"]).read_text(encoding="utf-8"))["position"]
    locales += [pos["x"], pos["y"], pos["width"], pos["height"]]
check("les visual.json portent des entiers", all(float(x).is_integer() for x in locales))
w._undo_last()
qapp.processEvents()
relu = {v["id"]: v for v in report_reader.visuals(RAPPORT, w._page_id)}
check("Ctrl+Z remet les fichiers d'avant", any(
    not float(x).is_integer() for v in relu.values() for x in boite(v)))

w.close()
shutil.rmtree(c, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
print("TOUT OK" if _ok else "DES ECHECS")
sys.exit(0 if _ok else 1)
