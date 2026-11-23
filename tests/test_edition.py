# -*- coding: utf-8 -*-
"""Édition production / dev : ce que la version partagée n'offre pas.

    py tests\\test_edition.py

En PRODUCTION (le défaut : pas de fichier .dev à côté de app.py) :
  · Wireframe en lecture seule — boutons d'écriture masqués, éléments non
    déplaçables, et chaque méthode qui écrit refuse même appelée directement ;
  · ChopChop sans suppression — bouton masqué, méthode inerte.
En DEV (.dev présent, ou PBIDOUILLE_DEV=1) tout reste offert.

Travaille sur une COPIE du projet de démonstration, avec un magasin de
réglages jetable : ni le vrai rapport ni les réglages de l'usager ne sont
touchés.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("PBIDOUILLE_DEV", None)
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

exiger_projet(PBI, PROJET_DEMO)

PROJ = PROJET_DEMO
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


def empreinte(dossier: Path) -> dict:
    """Chemin relatif -> hash de chaque fichier : toute écriture se voit."""
    return {str(f.relative_to(dossier)): hashlib.md5(f.read_bytes()).hexdigest()
            for f in sorted(dossier.rglob("*")) if f.is_file()}


c = Path(tempfile.gettempdir()) / "pbid_edition"
rmtree(c)
c.mkdir(parents=True)
for s in (".Report", ".SemanticModel"):
    shutil.copytree(PBI / (PROJ + s), c / (PROJ + s))
shutil.copy2(PBI / (PROJ + ".pbip"), c / (PROJ + ".pbip"))

from qtpy.QtCore import QSettings                    # noqa: E402
from qtpy.QtWidgets import QApplication, QGraphicsItem  # noqa: E402
from core import edition                             # noqa: E402
from core import project as prj                      # noqa: E402

prj.ORG_REGLAGES = "ChopChop"
prj.APP_REGLAGES = "BIdouille_TEST_EDITION"
prj._ANCIEN_MAGASIN = ("PBIdouille_TEST_EDITION", "PBIdouille_TEST_EDITION")
prj.reglages().clear()
QSettings(*prj._ANCIEN_MAGASIN).clear()

qapp = QApplication.instance() or QApplication([])

# le marqueur du VRAI dossier (s'il existe) ne doit pas décider pour le test
VRAI_MARQUEUR = edition.MARQUEUR_DEV
ABSENT = c / "pas_de_marqueur" / ".dev"
PRESENT = c / ".dev"
PRESENT.write_text("dev", encoding="utf-8")

# ===================================================================== 1
print("1. qui décide de l'édition")
edition.MARQUEUR_DEV = ABSENT
check("sans marqueur ni variable : production", edition.production())
check("le titre n'affiche que la version", edition.libelle() == edition.VERSION)
os.environ["PBIDOUILLE_DEV"] = "1"
check("PBIDOUILLE_DEV=1 : dev", edition.dev())
os.environ["PBIDOUILLE_DEV"] = "0"
check("PBIDOUILLE_DEV=0 : reste production", edition.production())
os.environ.pop("PBIDOUILLE_DEV")
edition.MARQUEUR_DEV = PRESENT
check("fichier .dev présent : dev", edition.dev())
check("le titre le dit", edition.libelle().endswith("(dev)"))
check("le marqueur est cherché à côté de app.py",
      VRAI_MARQUEUR == FIT / ".dev")

from tabs.tab_wireframe import WireframeTab          # noqa: E402
from tabs.tab_chopchop import ChopChopTab            # noqa: E402
import backup_restore as br                          # noqa: E402
br.migrate_legacy = lambda *a, **k: []
br.prune_all = lambda *a, **k: []
projet = prj.Project(c / (PROJ + ".pbip"))


def ouvrir_wireframe():
    w = WireframeTab()
    w.set_project(projet)
    qapp.processEvents()
    return w


def deplacables(w):
    return [v for v, it in w._id_to_item.items()
            if it.flags() & QGraphicsItem.ItemIsMovable]


ECRITURE = ("btn_cancel", "btn_save", "btn_group", "btn_ungroup",
            "btn_distribute", "grp_tpl")

# ===================================================================== 2
print("2. Wireframe en production : lecture seule")
edition.MARQUEUR_DEV = ABSENT
w = ouvrir_wireframe()
check("la page est bien chargée (des éléments à l'écran)", len(w._id_to_item) > 0)
check("lecture_seule posée", w.lecture_seule)
check("aucun bouton d'écriture offert",
      all(getattr(w, n).isHidden() for n in ECRITURE))
check("navigation gardée (Ouvrir visual.json, Entrer dans le groupe)",
      not w.btn_open.isHidden() and not w.btn_enter.isHidden())
check("aucun élément déplaçable (donc pas de redimensionnement non plus)",
      deplacables(w) == [])
check("aucune poignée de bordure", w._dividers == [])
avant = empreinte(c)
# forcer chaque chemin d'écriture, comme si un raccourci y menait quand même
w._dirty = set(list(w._id_to_item)[:1])
w._multi_ids = list(w._id_to_item)[:2]
w._selected_id = next((v for v, d in w._data.items() if d["is_group"]), None)
for m in ("_save_positions", "_group_selection", "_ungroup_selection",
          "_distribute", "_tpl_import", "_undo_last"):
    getattr(w, m)()
qapp.processEvents()
check("les six méthodes qui écrivent n'ont rien écrit", empreinte(c) == avant)
check("pas de dossier de sauvegarde créé",
      not (c / "_backupsPBIdouille").exists())

# ===================================================================== 3
print("3. Wireframe en dev : tout reste offert")
edition.MARQUEUR_DEV = PRESENT
w2 = ouvrir_wireframe()
check("pas en lecture seule", not w2.lecture_seule)
check("les boutons d'écriture sont là",
      not any(getattr(w2, n).isHidden() for n in ECRITURE))
check("les éléments du niveau actif se déplacent", len(deplacables(w2)) > 0)

# ===================================================================== 4
print("4. ChopChop : la suppression n'existe qu'en dev")
edition.MARQUEUR_DEV = ABSENT
k = ChopChopTab()
check("production : bouton Supprimer masqué", k.panel.btn_delete.isHidden())
avant = empreinte(c)
k.panel.result = {"measures": {}, "referencers": {}, "columns": {},
                  "column_referencers": {}}
k.panel._delete_checked()
check("production : _delete_checked n'écrit rien", empreinte(c) == avant)
edition.MARQUEUR_DEV = PRESENT
k2 = ChopChopTab()
check("dev : bouton Supprimer présent", not k2.panel.btn_delete.isHidden())

# ===================================================================== 5
print("5. la fenêtre : pas d'onglet Wireframe en production")
import app as application                            # noqa: E402
import propagate_cf as _pcf                          # noqa: E402
_pcf.migrer_groupes = lambda *a, **k: None
# la fenêtre rouvre le « dernier projet » : la COPIE, jamais le vrai dossier
prj.reglages().setValue("last_pbip", str(c / (PROJ + ".pbip")))


def onglets():
    f = application.BidouilleWindow()
    t = [f.tabs.tabText(i) for i in range(f.tabs.count())]
    n = len(f._tabs)
    f.close()
    return t, n


edition.MARQUEUR_DEV = ABSENT
t, n = onglets()
check("production : Mesures, Rapport, Radiographie, ChopChop",
      t == ["Mesures", "Rapport", "Radiographie 🩻", "ChopChop 🪓"])
check("production : « Tout recharger » ne parcourt que ces quatre-là", n == 4)
edition.MARQUEUR_DEV = PRESENT
t, n = onglets()
check("dev : le Wireframe est là, après la Radiographie",
      "Wireframe" in t and n == 5 and t.index("Wireframe") == t.index("Radiographie 🩻") + 1)

edition.MARQUEUR_DEV = VRAI_MARQUEUR
prj.reglages().clear()
QSettings(*prj._ANCIEN_MAGASIN).clear()
rmtree(c)
print()
print("TOUT OK" if _ok else "DES ECHECS")
sys.exit(0 if _ok else 1)
