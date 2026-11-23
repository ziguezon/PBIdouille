# -*- coding: utf-8 -*-
"""Rangement et menage des sauvegardes, plus le bouton qui s'allume.

    py tests\\test_sauvegardes.py

Trois choses tenues ensemble ici :

  1. tout est range sous _backupsPBIdouille\\ (un seul endroit ou chercher) ;
  2. chaque outil ne garde que ses MAX_SESSIONS plus recentes ;
  3. l'etat « non sauvegarde » s'affiche EN ALLUMANT le bouton Sauvegarder.

Le piege du lot est au point 2 : restaurer ECRIT d'abord l'etat courant dans
le meme dossier, ce qui declenche le menage — lequel ne doit surtout pas
emporter la sauvegarde qu'on est en train de relire. C'est le test « la
sauvegarde en cours de restauration survit au menage ».
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import time
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
from _fixture import exiger_projet, reglages_jetables, PROJET_DEMO   # noqa: E402

exiger_projet(PBI, PROJET_DEMO, "measures_config.json")
reglages_jetables('sauvegardes')   # jamais les reglages reels

import backup_restore as br                       # noqa: E402

PROJ = PROJET_DEMO
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


def faux_projet(nom):
    """Un dossier de projet minimal : assez pour que les chemins relatifs du
    manifeste aient un sens."""
    c = Path(tempfile.gettempdir()) / nom
    rmtree(c)
    (c / "cible").mkdir(parents=True)
    return c


def session_bidon(root, stamp, contenu="{}"):
    """Ecrit une session A LA MAIN (sans BackupSession) : sert a peupler un
    dossier pour tester le menage, sans declencher le menage."""
    d = Path(root) / stamp
    d.mkdir(parents=True, exist_ok=True)
    (d / "x.json").write_text(contenu, encoding="utf-8")
    return d


# ===================================================================== 1
print("1. tout sous un seul dossier parent")
c = faux_projet("pbid_sauv_1")
root = br.backup_root(c, "_tmdl_backups")
check("le dossier d'outil vit sous le parent",
      root == c / "_backupsPBIdouille" / "_tmdl_backups")
check("le nom du parent est celui annonce", br.PARENT == "_backupsPBIdouille")

# une vraie session : le manifeste doit pointer le PROJET, pas le parent
fichier = c / "cible" / "a.json"
fichier.write_text('{"v": 1}', encoding="utf-8")
s = br.BackupSession(root, "Test", c)
s.save(fichier)
d = s.close("un fichier")
man = json.loads((d / br.MANIFEST).read_text(encoding="utf-8"))
check("la copie est bien sous le parent", br.PARENT in str(d))
check("le manifeste vise le PROJET, pas le dossier parent",
      Path(man["racine"]) == c)
check("la cible est relative au projet",
      man["fichiers"][0]["cible"] == "cible/a.json")
check("project_of remonte les deux crans", br.project_of(root) == c)
check("… et un seul pour un ancien dossier a la racine",
      br.project_of(c / "_tmdl_backups") == c)

# ===================================================================== 2
print("2. menage : on ne garde que les MAX_SESSIONS plus recentes")
c2 = faux_projet("pbid_sauv_2")
r2 = br.backup_root(c2, "_propagate_backups")
for i in range(1, 15):
    session_bidon(r2, "202601%02d_120000_000000" % i)
check("14 sessions posees", len(br.sessions_of(r2)) == 14)
efface = br.prune(r2)
restantes = [d.name for d in br.sessions_of(r2)]
check(f"il en reste {br.MAX_SESSIONS}", len(restantes) == br.MAX_SESSIONS)
check("ce sont les PLUS RECENTES", restantes[0].startswith("20260114"))
check("les plus vieilles sont parties", len(efface) == 4)
check("la plus vieille effacee est bien la premiere",
      "20260101_120000_000000" in efface)

# un dossier qui n'est pas une sauvegarde n'est jamais touche
(r2 / "notes a moi").mkdir()
br.prune(r2, keep=1)
check("un dossier etranger n'est pas efface", (r2 / "notes a moi").is_dir())
check("… et il ne compte pas comme une sauvegarde", len(br.sessions_of(r2)) == 1)

# les anciens noms (a la seconde) et les nouveaux (microseconde) se trient
c3 = faux_projet("pbid_sauv_3")
r3 = br.backup_root(c3, "_wireframe_backups")
session_bidon(r3, "20260101_120000")            # ancien format
session_bidon(r3, "20260301_120000_123456")     # nouveau
session_bidon(r3, "20260201_120000")
ordre = [d.name for d in br.sessions_of(r3)]
check("tri du plus recent au plus ancien, formats melanges",
      ordre == ["20260301_120000_123456", "20260201_120000", "20260101_120000"])

# close() fait le menage tout seul
c4 = faux_projet("pbid_sauv_4")
r4 = br.backup_root(c4, "_tmdl_backups")
for i in range(1, 13):
    session_bidon(r4, "202601%02d_120000_000000" % i)
f4 = c4 / "cible" / "b.json"
f4.write_text("{}", encoding="utf-8")
s4 = br.BackupSession(r4, "Test", c4)
s4.save(f4)
neuve = s4.close("")
check("close() a fait le menage", len(br.sessions_of(r4)) == br.MAX_SESSIONS)
check("la session qu'on vient d'ecrire est gardee", neuve.exists())

# ===================================================================== 3
print("3. LE PIEGE : restaurer declenche le menage du meme dossier")
c5 = faux_projet("pbid_sauv_5")
r5 = br.backup_root(c5, "_tmdl_backups")
vise = c5 / "cible" / "important.json"
vise.write_text('{"version": "ORIGINALE"}', encoding="utf-8")
# la sauvegarde qu'on voudra restaurer... puis 12 autres par-dessus, si bien
# qu'elle sort largement des MAX_SESSIONS plus recentes
s5 = br.BackupSession(r5, "Test", c5)
s5.save(vise)
a_restaurer = s5.close("etat d'origine")
time.sleep(0.01)
for i in range(1, 13):
    session_bidon(r5, "209901%02d_120000_000000" % i)   # toutes plus recentes
vise.write_text('{"version": "ABIMEE"}', encoding="utf-8")

rep = br.restore_session(a_restaurer, c5)
check("le fichier est revenu a son etat d'origine",
      json.loads(vise.read_text(encoding="utf-8"))["version"] == "ORIGINALE")
check("la sauvegarde restauree n'a pas ete emportee par le menage",
      a_restaurer.exists())
check("l'etat courant a bien ete sauvegarde avant (annulable)",
      rep["sauvegarde_avant"] and Path(rep["sauvegarde_avant"]).exists())

# et l'annulation de cette restauration marche encore
br.restore_session(rep["sauvegarde_avant"], c5)
check("annuler la restauration remet l'etat abime",
      json.loads(vise.read_text(encoding="utf-8"))["version"] == "ABIMEE")

# ===================================================================== 3bis
print("3bis. un fichier touche DEUX fois n'est sauvegarde qu'une fois")
# Une session decrit l'etat d'AVANT l'operation. Si une operation en plusieurs
# passes (une propagation par groupes) touche deux fois le meme fichier, la 2e
# copie serait l'etat INTERMEDIAIRE — et comme la restauration applique le
# manifeste dans l'ordre, annuler rendait le milieu de l'operation.
c5b = faux_projet("pbid_sauv_5b")
r5b = br.backup_root(c5b, "_tmdl_backups")
f5b = c5b / "cible" / "deux_passes.json"
f5b.write_text("AVANT", encoding="utf-8")
s5b = br.BackupSession(r5b, "Deux passes", c5b)
copie1 = s5b.save(f5b)
f5b.write_text("APRES PASSE 1", encoding="utf-8")
copie2 = s5b.save(f5b)                      # 2e passe sur le meme fichier
f5b.write_text("APRES PASSE 2", encoding="utf-8")
d5b = s5b.close("deux passes")
man = json.loads((d5b / br.MANIFEST).read_text(encoding="utf-8"))
check("une seule entree au manifeste", len(man["fichiers"]) == 1)
check("le 2e save rend la copie DEJA faite", copie1 == copie2)
check("la copie gardee est celle d'AVANT l'operation",
      copie1.read_text(encoding="utf-8") == "AVANT")
br.restore_session(d5b, c5b)
check("restaurer rend l'etat du DEBUT, pas celui du milieu",
      f5b.read_text(encoding="utf-8") == "AVANT")
# un fichier different garde bien sa propre copie
autre = c5b / "cible" / "autre.json"
autre.write_text("x", encoding="utf-8")
s5c = br.BackupSession(r5b, "Deux fichiers", c5b)
s5c.save(f5b)
s5c.save(autre)
check("deux fichiers distincts donnent deux entrees",
      len(s5c.entries) == 2)
rmtree(c5b)

# ===================================================================== 4
print("4. rangement des anciennes sauvegardes")
c6 = faux_projet("pbid_sauv_6")
for folder in ("_tmdl_backups", "_wireframe_backups"):
    for stamp in ("20260101_120000", "20260102_120000"):
        session_bidon(c6 / folder, stamp)
# une session deja rangee, de meme nom : ne doit PAS etre ecrasee
deja = session_bidon(c6 / br.PARENT / "_tmdl_backups", "20260101_120000",
                     contenu='{"garde": "moi"}')
journal = []
bouge = br.migrate_legacy(c6, journal.append)
check("trois sessions rangees (la quatrieme entrerait en collision)",
      len(bouge) == 3)
check("la session homonyme deja rangee est intacte",
      json.loads((deja / "x.json").read_text(encoding="utf-8")) == {"garde": "moi"})
check("la collision est dite, pas tue", any("existe" in l for l in journal))
check("_wireframe_backups a disparu de la racine",
      not (c6 / "_wireframe_backups").exists())
check("… et se retrouve sous le parent",
      (c6 / br.PARENT / "_wireframe_backups").is_dir())

# rien ne se perd : les anciennes restent listables meme sans rangement
c7 = faux_projet("pbid_sauv_7")
session_bidon(c7 / "_tmdl_backups", "20260101_120000")          # a l'ancienne
session_bidon(br.backup_root(c7, "_propagate_backups"), "20260202_120000")
noms = [s["horodatage"] for s in br.list_sessions(c7)]
check("list_sessions voit l'ancienne ET la nouvelle disposition",
      noms == ["20260202_120000", "20260101_120000"])

# le menage global, celui du chargement de projet
c8 = faux_projet("pbid_sauv_8")
for i in range(1, 14):
    session_bidon(br.backup_root(c8, "_tmdl_backups"), "202601%02d_120000" % i)
for i in range(1, 14):
    session_bidon(br.backup_root(c8, "_wireframe_backups"), "202601%02d_120000" % i)
br.prune_all(c8)
check("le menage global taille CHAQUE outil a MAX_SESSIONS",
      len(br.sessions_of(br.backup_root(c8, "_tmdl_backups"))) == br.MAX_SESSIONS
      and len(br.sessions_of(br.backup_root(c8, "_wireframe_backups")))
      == br.MAX_SESSIONS)

# ===================================================================== 5
print("5. l'etat non sauvegarde s'allume sur le bouton")
c9 = Path(tempfile.gettempdir()) / "pbid_sauv_ui"
rmtree(c9)
c9.mkdir(parents=True)
for suffixe in (".Report", ".SemanticModel"):
    shutil.copytree(PBI / (PROJ + suffixe), c9 / (PROJ + suffixe))
for f in ((PROJ + ".pbip"), "measures_config.json"):
    shutil.copy2(PBI / f, c9 / f)

from PySide6.QtWidgets import QApplication                    # noqa: E402
from core.project import Project                              # noqa: E402
from core.theme import ORANGE                                 # noqa: E402
import tabs.tab_config as tc                                  # noqa: E402
import tabs.tab_wireframe as tw                               # noqa: E402

app = QApplication.instance() or QApplication([])
projet = Project(c9 / (PROJ + ".pbip"))

onglet = tc.ConfigTab()
onglet.set_project(projet)
check("au repos, le bouton Sauvegarder n'est pas allume",
      ORANGE.lower() not in onglet.btn_save.styleSheet().lower())
onglet._set_dirty(True)
check("modifie : le bouton passe en orange",
      ORANGE.lower() in onglet.btn_save.styleSheet().lower())
check("l'infobulle dit ce que le voyant disait",
      "NON sauvegard" in onglet.btn_save.toolTip())
onglet.lbl_dirty.setText("✔ un vieux message de confirmation")
onglet._set_dirty(True)
check("un « ✔ ecrit » perime est efface (il n'est plus vrai)",
      onglet.lbl_dirty.text() == "")
onglet._set_dirty(False)
check("sauvegarde : le bouton s'eteint",
      ORANGE.lower() not in onglet.btn_save.styleSheet().lower())

wf = tw.WireframeTab()
wf.set_project(projet)
check("wireframe au repos : bouton eteint et desactive",
      not wf.btn_save.isEnabled()
      and ORANGE.lower() not in wf.btn_save.styleSheet().lower())
vid = next(iter(wf._data), None)
check("la page de demo a des elements", vid is not None)
if vid:
    wf._mark_dirty(vid)
    check("un element deplace allume le bouton",
          ORANGE.lower() in wf.btn_save.styleSheet().lower())
    check("le compte a migre du voyant VERS le bouton",
          wf.btn_save.text() == "💾 Enregistrer (1)")
    check("plus de voyant separe", not hasattr(wf, "lbl_dirty"))

# ===================================================================== 6
print("6. l'onglet Mesures est le premier")
import app as application                                     # noqa: E402
# la fenetre charge le DERNIER projet ouvert — le vrai. Ouvrir un projet
# range et fait le menage : hors de question qu'une suite de tests efface
# les sauvegardes de quelqu'un. On neutralise, ce n'est pas le sujet ici
# (le rangement et le menage sont eprouves plus haut, sur des copies).
application.br.migrate_legacy = lambda *a, **k: []
import propagate_cf as _pcf_isole                          # noqa: E402
# ouvrir un projet renomme son ancien <rapport>.propagation.json : sur le VRAI
# dossier, ce serait a l'usager de le declencher, pas a une suite de tests
_pcf_isole.migrer_groupes = lambda *a, **k: None
application.br.prune_all = lambda *a, **k: []
fen = application.BidouilleWindow()
titres = [fen.tabs.tabText(i) for i in range(fen.tabs.count())]
print("   onglets :", titres)
check("Mesures en tete", titres[0] == "Mesures")
# le Wireframe n'existe qu'en edition dev (cf. core/edition.py)
_dev = application.edition.dev()
attendus = (["Rapport", "Radiographie 🩻", "Wireframe", "ChopChop 🪓"]
            if _dev else ["Rapport", "Radiographie 🩻", "ChopChop 🪓"])
check("les autres suivent dans le meme ordre qu'avant",
      titres[1:] == attendus)
check("« Enregistrer puis recharger » touche tous les onglets affiches",
      len(fen._tabs) == len(titres) and fen._tabs[0] is fen.tab_config)
from qtpy.QtWidgets import QPushButton as _QPB                 # noqa: E402
check("plus de bouton « Tout enregistrer » : chaque onglet a le sien",
      not any("Tout enregistrer" in b.text()
              for b in fen.findChildren(_QPB)))

# ===================================================================== 7
print("7. la generation ECRIT vraiment, et sa sauvegarde est restaurable")
# les autres suites generent en dry-run : le chemin d'ecriture — celui qui
# fabrique la sauvegarde — n'y passe jamais. On l'exerce ici, sur la copie.
import generate_measures as gm                                # noqa: E402

modele = c9 / (PROJ + ".SemanticModel")
conf = json.loads((c9 / "measures_config.json").read_text(encoding="utf-8"))
mesures_tmdl = modele / "definition" / "tables" / "_mesures.tmdl"
avant = mesures_tmdl.read_text(encoding="utf-8")
stats = gm.generate(modele, conf, dry_run=False, log=lambda *_: None)
check("des mesures ont ete ecrites",
      mesures_tmdl.read_text(encoding="utf-8") != avant)

tmdl_root = br.backup_root(c9, "_tmdl_backups")
sessions = br.sessions_of(tmdl_root)
check("une sauvegarde a ete deposee sous le parent", len(sessions) == 1)
info = br.session_info(sessions[0], c9)
check("elle porte un manifeste (donc restaurable d'un clic)", info["manifeste"])
check("l'outil se nomme dans la liste", info["outil"] == "Mesures générées")
check("aucun fichier sans cible", info["n_orphelins"] == 0)
check("les cibles sont relatives au projet",
      all(not Path(e["cible"]).is_absolute() for e in info["fichiers"]))

br.restore_session(sessions[0], c9)
check("restaurer remet le modele d'avant la generation",
      mesures_tmdl.read_text(encoding="utf-8") == avant)
check("la generation avait bien cree quelque chose",
      bool(stats["created"]) or bool(stats["updated"]))

# ===================================================================== 8
print("8. le wireframe ecrit au bon endroit, avec la bonne racine")
# meme classe de piege : BackupSession deduisait le projet en remontant d'UN
# cran depuis le dossier de l'outil. Avec le dossier parent, ca tombait sur
# _backupsPBIdouille\ et le manifeste pointait a cote.
from core import report_reader                                # noqa: E402

vj = next(iter((c9 / (PROJ + ".Report")).glob(
    "definition/pages/*/visuals/*/visual.json")), None)
check("la copie a des visuels", vj is not None)
if vj:
    origine = vj.read_text(encoding="utf-8")
    wf_root = br.backup_root(c9, "_wireframe_backups")
    n, dossier = report_reader.write_positions(
        {str(vj): (11.0, 22.0, 33.0, 44.0)}, wf_root)
    check("une position ecrite", n == 1)
    check("la sauvegarde est sous le parent", br.PARENT in str(dossier))
    info_wf = br.session_info(dossier, c9)
    check("le manifeste vise le projet, pas le dossier parent",
          Path(info_wf["racine"]) == c9)
    cible = info_wf["fichiers"][0]["cible"]
    check("la cible relative retombe sur le bon visual.json",
          not Path(cible).is_absolute() and (c9 / cible).resolve() == vj.resolve())
    check("la position a bien change",
          json.loads(vj.read_text(encoding="utf-8"))["position"]["x"] == 11.0)
    br.restore_session(dossier, c9)
    check("restaurer remet le visuel d'origine",
          vj.read_text(encoding="utf-8") == origine)

fen.deleteLater()
wf.deleteLater()
onglet.deleteLater()
app.processEvents()
for d in ("pbid_sauv_1", "pbid_sauv_2", "pbid_sauv_3", "pbid_sauv_4",
          "pbid_sauv_5", "pbid_sauv_6", "pbid_sauv_7", "pbid_sauv_8",
          "pbid_sauv_ui", "pbid_mig_probe"):
    rmtree(Path(tempfile.gettempdir()) / d)

print("\n" + ("TOUT OK" if _ok else "*** DES ECHECS ***"))
sys.exit(0 if _ok else 1)
