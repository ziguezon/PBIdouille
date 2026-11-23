# -*- coding: utf-8 -*-
"""TD_Indicateurs doit rester enregistrable depuis Excel apres chaque lecture.

    py tests\\test_verrou_xlsx.py

Symptome corrige : apres avoir lance l'option couleurs, Excel refusait
d'enregistrer TD_Indicateurs.xlsx. `read_kpi_colors` ouvrait le classeur en
mode `read_only` — qui ne charge RIEN en memoire et garde le fichier ouvert —
sans jamais appeler close(). Les objets openpyxl se referencant en cycle, le
compteur de references ne les liberait pas : il fallait attendre un passage du
ramasse-miettes. D'ou un verrou qui semblait aleatoire alors qu'il etait
systematique.

La sonde rejoue ce que fait Excel quand il enregistre : ecrire un temporaire,
puis le SUBSTITUER au fichier (os.replace). Sous Windows ca echoue tant qu'un
autre processus tient le fichier — c'est litteralement le geste de l'usager.

La section 1 verifie d'abord que la sonde MORD : sans elle, une suite qui
repond « OK » partout ne prouverait rien du tout.
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
from _fixture import exiger_projet, PROJET_DEMO   # noqa: E402

exiger_projet(PBI, PROJET_DEMO, "TD_Indicateurs.xlsx", "measures_config.json")

import openpyxl                                   # noqa: E402
import color_matrix_by_kpi as cmx                 # noqa: E402
import generate_measures as gm                    # noqa: E402
from core import model_reader as mr               # noqa: E402

PROJ = PROJET_DEMO
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


c = Path(tempfile.gettempdir()) / "pbidouille_verrou"
rmtree(c)
c.mkdir(parents=True)
for suffixe in (".Report", ".SemanticModel"):
    shutil.copytree(PBI / (PROJ + suffixe), c / (PROJ + suffixe))
for f in ((PROJ + ".pbip"), "TD_Indicateurs.xlsx", "measures_config.json"):
    shutil.copy2(PBI / f, c / f)
XLSX = c / "TD_Indicateurs.xlsx"

# un classeur réel porte des colonnes de couleurs ; celui de demo non
wb = openpyxl.load_workbook(XLSX)
ws = wb.worksheets[0]
entetes = [str(x.value).strip().lower() if x.value else "" for x in ws[1]]
for nom, valeur in (("couleur_fill", "#123456"), ("couleur_text", "#FFFFFF"),
                    ("ordre", None)):
    if nom in entetes:
        continue
    col = ws.max_column + 1
    ws.cell(row=1, column=col, value=nom)
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=col,
                value=valeur if valeur is not None else (r - 1) * 10)
wb.save(XLSX)
wb.close()


def enregistrable() -> bool:
    """Le geste exact d'Excel : ecrire a cote, puis substituer."""
    tmp = XLSX.with_suffix(".excel_tmp")
    shutil.copy2(XLSX, tmp)
    try:
        os.replace(tmp, XLSX)
        return True
    except PermissionError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


# ===================================================================== 1
print("1. la sonde mord-elle ? (sinon tout le reste ne prouve rien)")
check("classeur au repos : enregistrable", enregistrable())
tenu = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
list(tenu.worksheets[0].iter_rows(max_row=1, values_only=True))
check("classeur tenu ouvert : la sonde le DETECTE", not enregistrable())
tenu.close()
check("refermé : de nouveau enregistrable", enregistrable())

# ===================================================================== 2
print("2. l'option couleurs")
cmx.read_kpi_colors(XLSX, None, "mesure", "couleur_fill", "couleur_text")
check("read_kpi_colors relache le fichier", enregistrable())

try:
    cmx.read_kpi_colors(XLSX, None, "mesure", "pas_une_colonne", "couleur_text")
    check("colonne absente = erreur", False)
except SystemExit:
    check("colonne absente = erreur", True)
check("… et le fichier est relache MEME sur ce chemin d'erreur", enregistrable())

logs = []
cmx.colorize(c / (PROJ + ".Report"), c / (PROJ + ".SemanticModel"), XLSX,
             sheet=None, key_col="mesure", fill_col="couleur_fill",
             text_col="couleur_text", dry_run=True, log=logs.append)
check("colorize (ce que lance l'onglet Rapport) relache le fichier",
      enregistrable())
check("… et a bien travaille", any("Couleurs par KPI" in l for l in logs))

# une fuite par appel se verrait sur une rafale
for _ in range(25):
    cmx.read_kpi_colors(XLSX, None, "mesure", "couleur_fill", "couleur_text")
check("25 lectures d'affilee : toujours enregistrable", enregistrable())

# ===================================================================== 3
print("3. les lectures du generateur")
gm.read_attribute_map(XLSX, "mesure", "libelle_indicateur")
check("read_attribute_map (jetons <<…>>, portee) relache", enregistrable())

td = gm.indicateurs_xlsx({"indicateursXlsx": {"orderColumn": "ordre"}}, c)
ordres = gm.read_kpi_order(td, lambda *_: None)
check("read_kpi_order a bien lu la colonne", len(ordres) >= 3)
check("… et relache le fichier", enregistrable())

conf = json.loads((c / "measures_config.json").read_text(encoding="utf-8"))
conf["indicateursXlsx"] = {"orderColumn": "ordre"}
gm.generate(c / (PROJ + ".SemanticModel"), conf, dry_run=True,
            log=lambda *_: None)
check("une generation complete relache le fichier", enregistrable())

# ===================================================================== 4
print("4. les menus de colonnes de l'onglet Mesures")
check("excel_headers lit bien les en-tetes",
      "couleur_fill" in mr.excel_headers(XLSX))
check("… et relache le fichier", enregistrable())
check("fichier absent : liste vide, pas d'erreur",
      mr.excel_headers(c / "nexiste_pas.xlsx") == [])

from PySide6.QtWidgets import QApplication                    # noqa: E402
from core.project import Project                              # noqa: E402
import tabs.tab_config as tc                                  # noqa: E402
from tabs.dialog_couleurs import CouleursDialog               # noqa: E402

app = QApplication.instance() or QApplication([])
onglet = tc.ConfigTab()
onglet.set_project(Project(c / (PROJ + ".pbip")))
onglet._load_global()
for _ in range(5):
    onglet._td_reload_columns()      # a chaque ouverture de « Reglages globaux »
check("repeupler les menus de colonnes relache le fichier", enregistrable())

# ===================================================================== 5
print("5. le dialogue des couleurs (qui, lui, ECRIT dans le classeur)")
dlg = CouleursDialog(XLSX, "mesure", "couleur_fill", "couleur_text",
                     model_kpis=[], parent=onglet)
check("le dialogue a lu les KPI", len(dlg.state) >= 3)
check("l'ouvrir relache le fichier", enregistrable())

premier = next(iter(dlg.state))
dlg.state[premier]["fill"] = "#ABCDEF"
import tabs.dialog_couleurs as dc                             # noqa: E402
dc.QMessageBox.information = staticmethod(lambda *a, **k: None)
dlg._save()
check("enregistrer relache le fichier", enregistrable())
relu = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
lignes = list(relu.worksheets[0].iter_rows(values_only=True))
relu.close()
check("… et a vraiment ecrit la couleur",
      any("#ABCDEF" == str(v) for r in lignes for v in r if v))

dlg.deleteLater()
onglet.deleteLater()
app.processEvents()
rmtree(c)

print("\n" + ("TOUT OK" if _ok else "*** DES ECHECS ***"))
sys.exit(0 if _ok else 1)
