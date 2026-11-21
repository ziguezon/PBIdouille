# -*- coding: utf-8 -*-
"""Le journal unique (colonne de droite) et les editeurs de code.

    py tests\\test_journal.py

Ce qui est verifie, et pourquoi :

  1. LE VOCABULAIRE. Les couleurs ne sont pas decoratives : elles disent la
     nature de la ligne. Les cas testes sont des lignes REELLES des moteurs
     (copiees de propagate_cf / generate_measures), pas des exemples inventes —
     si un moteur change sa forme, le test doit tomber.
  2. L'HORODATAGE, et le verdict ecrit SUR la banniere du run.
  3. LE PLUS RECENT EN HAUT — par entree : les runs s'empilent du plus recent
     au plus ancien, mais un run se lit toujours de haut en bas. Un trait
     separe un run de ses voisins ; les messages restent groupes sans trait.
  4. LA MISE EN PAGE. Les lignes vides des moteurs deviennent de la marge (pas
     des trous), et le retrait de tete devient une marge gauche.
  5. LA LECTURE EN COURS n'est pas bousculee par ce qui arrive en haut.
  6. LA PLACE. Un seul journal, a droite ; la vue « Variations » lui prend sa
     colonne (pour le DAX et l'apercu) — le choix de l'usager est retenu PAR
     VUE, et un rechargement silencieux est suivi aussi.
  7. LES EDITEURS DE CODE : TAB = une tabulation (4 caracteres de large),
     Debut s'arrete apres le retrait.
  8. SOUS LE VRAI THEME : le DAX est en chasse fixe. Le QSS de l'app ecrasait
     tout setFont() — l'editeur etait en Segoe UI depuis toujours, et aucun
     test ne le voyait parce qu'aucun n'appliquait le theme.
  9. LES POIGNEES de volets : un trait d'un pixel, de l'air de chaque cote.
 10. LA GENERATION n'a plus d'onglet : un bouton en tete du journal, qui
     rattrape un config non enregistre au lieu de generer l'ancien.
 11. L'APERCU DES NOMS en couleur : ce que la branche et la variation
     AJOUTENT a la racine — et le texte reste celui que la generation
     produira, verifie contre le plan du generateur lui-meme.
 12. LES JETONS DU DAX surlignes a la frappe : connus en couleur,
     inconnus en rouge — y compris les <<attributs>> declares.
 13. LES « CLE : VALEUR » DU JOURNAL EN TABLEAU : cle grisee, valeurs
     alignees dans une colonne, une enumeration = une valeur par rangee.
 14. LA PRESENTATION : titres DANS le cadre, coche fine, aides des
     Reglages globaux, fiche Excel de l'onglet Rapport, journal large.
 15. LA FENETRE ⚙ REGLAGES : Annuler oublie, Enregistrer ecrit.
 16. LES TIROIRS : un run bavard se replie sur sa banniere ; un clic
     l'ouvre ou le referme.
"""

from __future__ import annotations

import os
import re
import sys
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

from _fixture import exiger_projet, PROJET_DEMO
exiger_projet(PBI, PROJET_DEMO, "measures_config.json")

from qtpy.QtCore import QEvent, QPoint, Qt                        # noqa: E402
from qtpy.QtGui import QKeyEvent, QTextCursor                     # noqa: E402
from qtpy.QtWidgets import QApplication, QPlainTextEdit, QSplitter  # noqa: E402

from core import journal as jm                                    # noqa: E402
from core.theme import (ACCENT, ACCENT_DIM, BLUE, GREEN, ORANGE, RED, TEXT,
                        TEXT_DIM, TEXT_MUTED, YELLOW)             # noqa: E402

# --- magasin de reglages JETABLE : la fenetre y ecrit la largeur et la
#     visibilite du journal, les projets recents… rien de tout ca ne doit
#     atterrir dans les reglages reels de l'usager (cf. test_reglages) -----
import core.project as prj                                        # noqa: E402
prj.APP_REGLAGES = "BIdouille_TEST_journal"
prj.reglages().clear()

app = QApplication.instance() or QApplication([])
_ok = True
HEURE = re.compile(r"\b\d{2}:\d{2}:\d{2}\b")


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def tour():
    """Un tour de boucle d'evenements : referme le groupe de messages."""
    app.processEvents()


def blocs(j):
    """Ce qui est REELLEMENT rendu, bloc par bloc : texte, couleur et graisse
    du DERNIER fragment (le texte lui-meme, apres une eventuelle heure),
    couleur du premier, marges, et s'il s'agit d'un trait."""
    out = []
    b = j.vue.document().begin()
    while b.isValid():
        plages = list(b.textFormats()) if hasattr(b, "textFormats") else []
        dernier = plages[-1].format if plages else None
        premier = plages[0].format if plages else None
        bf = b.blockFormat()
        fond = bf.background()
        trait = (not b.text() and fond.style() != Qt.NoBrush
                 and fond.color().name().upper() == jm.REGLE.upper())
        out.append(dict(
            texte=b.text(),
            couleur=dernier.foreground().color().name().upper() if dernier else None,
            gras=bool(dernier and dernier.fontWeight() > 50),
            couleur_debut=premier.foreground().color().name().upper() if premier else None,
            haut=bf.topMargin(), gauche=bf.leftMargin(), trait=trait))
        b = b.next()
    return out


def textes(j):
    return ["—" if b["trait"] else b["texte"] for b in blocs(j)]


# ===================================================================== 1
print("1. le vocabulaire des moteurs -> une couleur")
CAS = [
    # (ligne copiee d'un moteur, couleur attendue, gras attendu)
    ("⚠ branche 'YTD' : variation inconnue 'PY'.",                YELLOW, False),
    ("      ⚠ meme indente, un avertissement reste un avertissement", YELLOW, False),
    ("ERREUR : Traceback (most recent call last)",                RED, True),
    ("*** DRY_RUN : aucun fichier modifié (aperçu seulement) ***", BLUE, True),
    ("--- groupe « Sommeil » ---",                                ACCENT_DIM, True),
    ("— groupe « Vide » : aucun KPI — passe sautée.",              ACCENT_DIM, True),
    ("Terminé : 12 entrée(s) écrites.",                           GREEN, True),
    ("  + Weight YTD PY",                                         GREEN, False),
    ("  ~ Weight YTD MTD",                                        BLUE, False),
    ("      - Weight cible / fill : retiré (sans équivalent)",     ORANGE, False),
    ("  = Weight titre",                                          TEXT_MUTED, False),
    ("  ∅ Sleep Efficiency : PY, YoY %",                          TEXT_MUTED, False),
    ("  (si l'une d'elles DEVRAIT avoir une variante…)",           TEXT_DIM, False),
    ("Aucun changement.",                                         TEXT_DIM, False),
    ("KPI template : Total Steps",                                TEXT_DIM, False),
    ("  page 1 / visuel abc123 : 3 entrée(s)",                    TEXT_DIM, False),
]
for ligne, couleur, gras in CAS:
    obtenu = jm.classer(ligne)
    check(f"{ligne[:44]:<46} -> {couleur}", obtenu == (couleur, gras))
    if obtenu != (couleur, gras):
        print("      obtenu :", obtenu)
check("une ligne vide ne casse pas le classement", jm.classer("") == (TEXT, False))
check("le retrait se compte par crans de 2 espaces",
      (jm.niveau("x"), jm.niveau("  x"), jm.niveau("      x")) == (0, 1, 3))

# ===================================================================== 2
print("2. la couleur arrive dans le document ; l'heure, le verdict")
j = jm.Journal()
j.lancement("essai")
j.ligne("⚠ un avertissement")
j.ligne("  + une création")
r = blocs(j)
check("le jaune de l'avertissement est pose", r[1]["couleur"] == YELLOW.upper())
check("le vert de la creation est pose", r[2]["couleur"] == GREEN.upper())
j.fin()
tour()
j.info("⚠ un message horodaté")
m = blocs(j)[0]
check("un message porte son heure en tete, grisee",
      HEURE.match(m["texte"]) and m["couleur_debut"] == TEXT_MUTED.upper())
check("… et garde SA couleur apres l'heure", m["couleur"] == YELLOW.upper())

j = jm.Journal()
check("au repos, l'entete ne pretend rien",
      j.lbl_run.text() == "Dernier lancement : aucun")
j.lancement("Propagation des attributs", apercu=True)
entete = j.lbl_run.text()
heure = HEURE.search(entete)
check("l'entete porte une heure hh:mm:ss", bool(heure))
check("… le titre du run et le fait que c'est un apercu",
      "Propagation des attributs" in entete and "(aperçu)" in entete)
ban = blocs(j)[0]
check("la banniere est en tete, reperable (▶ + accent gras)",
      ban["texte"].startswith(jm.FLECHE_OUVERT) and ban["couleur"] == ACCENT.upper()
      and ban["gras"])
check("elle porte la MEME heure que l'entete",
      bool(heure) and heure.group(0) in ban["texte"])
j.ligne("KPI template : Total Steps")
j.fin()
ban = blocs(j)[0]
check("le verdict s'inscrit SUR la banniere (lisible sans descendre)",
      "✔ terminé en" in ban["texte"] and ban["couleur"] == GREEN.upper())
check("… avec une duree en secondes",
      re.search(r"terminé en \d+,\d s", ban["texte"]) is not None)
check("… et pas en bas du run, ou il faudrait aller le chercher",
      not any("terminé en" in b["texte"] for b in blocs(j)[1:]))
check("l'entete dit aussi la duree, et garde l'heure de depart",
      re.search(r"terminé en \d+,\d s", j.lbl_run.text()) is not None
      and bool(heure) and heure.group(0) in j.lbl_run.text())

j = jm.Journal()
j.lancement("Génération des mesures")
j.erreur("Traceback (most recent call last):\n  File \"gm.py\", line 3\nValueError: x")
j.fin(echec=True)
r = blocs(j)
check("un echec se dit en rouge SUR la banniere",
      "✖ échec" in r[0]["texte"] and r[0]["couleur"] == RED.upper())
check("… et la trace est dans le run, rouge en ENTIER (ligne indentee comprise)",
      len(r) == 4 and all(b["couleur"] == RED.upper() for b in r[1:]))
check("le mot echec est dans l'entete", "échec" in j.lbl_run.text())

# ===================================================================== 3
print("3. le plus recent EN HAUT — mais un run se lit de haut en bas")
j = jm.Journal()
j.lancement("A")
j.ligne("A1")
j.ligne("A2")
j.fin()
tour()
j.lancement("B")
j.ligne("B1")
j.ligne("B2")
j.fin()
t = textes(j)
check("le run le plus recent est en haut",
      t[0].startswith(jm.FLECHE_OUVERT) and " B" in t[0])
check("DANS le run, l'ordre de lecture est garde", t[1:3] == ["B1", "B2"])
check("un trait separe les deux runs", t[3] == "—")
check("le plus ancien suit, intact",
      " A" in t[4] and t[5:] == ["A1", "A2"])

print("   les messages : groupes sans trait, le plus recent en haut")
j = jm.Journal()
j.info("m1")
tour()
j.info("m2")
tour()
t = textes(j)
check("deux messages, le plus recent d'abord",
      t[0].endswith("m2") and t[1].endswith("m1"))
check("… sans trait entre eux (une rafale ne devient pas une echelle)",
      "—" not in t)
j.lancement("R")
j.fin()
tour()
check("un run qui arrive est separe des messages par un trait",
      textes(j)[1] == "—")
j.info("m3")
tour()
check("… et un message qui suit un run aussi", textes(j)[1] == "—")

print("   ce qu'un clic ecrit d'un coup = UNE entree, dans l'ordre")
j = jm.Journal()
j.info("Tables supprimées : x")
j.info("Mesures supprimées : y")
j.info("Fichiers modifiés : z")
tour()
t = textes(j)
check("les trois lignes restent dans leur ordre",
      [x.split("  ", 1)[-1] for x in t]
      == ["Tables supprimées : x", "Mesures supprimées : y",
          "Fichiers modifiés : z"])
check("seule la premiere est horodatee",
      HEURE.match(t[0]) and not HEURE.match(t[1]) and not HEURE.match(t[2]))

print("   un message PENDANT un run va au-dessus ; le run se complete chez lui")
j = jm.Journal()
j.lancement("Long run")
j.ligne("ligne 1")
tour()
j.info("message pendant le run")
j.ligne("ligne 2")
j.fin()
t = textes(j)
check("le message est en haut (il est plus recent que le debut du run)",
      t[0].endswith("message pendant le run"))
check("la suite du run est restee SOUS sa banniere",
      "Long run" in t[2] and t[3:] == ["ligne 1", "ligne 2"])
check("le verdict est sur la banniere du run, pas sur le message",
      "terminé" in t[2] and "terminé" not in t[0])

# ===================================================================== 4
print("4. mise en page : marges plutot que trous et espaces")
j = jm.Journal()
j.lancement("x")
j.ligne("Aucun changement.")
j.ligne("")                       # separateur des moteurs
j.ligne("Rouvre le .pbip dans Power BI Desktop.")
j.ligne("  + Weight YTD PY")
j.ligne("      candidat  Weight PY        ok")
r = blocs(j)[1:]                  # sans la banniere
check("la ligne vide ne cree PAS de bloc vide",
      [b["texte"] for b in r] == ["Aucun changement.",
                                  "Rouvre le .pbip dans Power BI Desktop.",
                                  "+ Weight YTD PY",
                                  "candidat  Weight PY        ok"])
check("… elle devient la marge du bloc suivant",
      r[1]["haut"] == jm.MARGE_SECTION and r[0]["haut"] == jm.MARGE_LIGNE)
check("le retrait de tete devient une marge GAUCHE",
      r[2]["gauche"] == jm.RETRAIT and not r[2]["texte"].startswith(" "))
check("un detail est colle a son titre (marge fine)",
      r[2]["haut"] == jm.MARGE_DETAIL)
check("les colonnes INTERNES sont preservees (mode verbeux)",
      r[3]["texte"] == "candidat  Weight PY        ok")

# ===================================================================== 5
print("5. la lecture en cours n'est pas bousculee")
j = jm.Journal()
j.resize(320, 260)
j.show()
for i in range(40):
    j.lancement(f"run {i}")
    j.ligne(f"ligne du run {i}")
    j.fin()
    tour()
barre = j.vue.verticalScrollBar()
check("il y a de quoi defiler (sinon ce qui suit ne prouverait rien)",
      barre.maximum() > 200)
barre.setValue(0)
j.lancement("tout neuf")
j.fin()
tour()
check("en haut, on y reste : le neuf est sous les yeux",
      barre.value() == 0 and "tout neuf" in textes(j)[0])


def repere():
    bloc = j.vue.cursorForPosition(QPoint(0, 0)).block()
    mise = j.vue.document().documentLayout()
    return bloc.text(), mise.blockBoundingRect(bloc).top() - barre.value()


barre.setValue(barre.maximum() // 2)
avant = repere()
j.lancement("arrive pendant la lecture")
j.ligne("avec une ligne")
j.fin()
tour()
apres_texte, apres_decalage = repere()
check("descendu lire : la MEME ligne reste au meme endroit",
      apres_texte == avant[0] and abs(apres_decalage - avant[1]) <= 2)
check("… parce que la vue a suivi ce qui s'est insere au-dessus",
      barre.value() > barre.maximum() // 2 - 5)

j.lancement("run ouvert en haut")
tour()
barre.setValue(barre.maximum() // 2)
avant = repere()
for k in range(5):
    j.ligne(f"ligne {k} du run ouvert")
apres = repere()
check("… meme quand c'est le run ouvert qui grandit au-dessus",
      apres[0] == avant[0] and abs(apres[1] - avant[1]) <= 2)
j.fin()
j.vider()
check("vider efface tout", j.texte().strip() == "")
j.hide()

# ===================================================================== 6
print("6. la place : UN journal a droite, que la vue Variations reprend")
import app as application                                         # noqa: E402

# la fenetre charge le vrai projet, et l'ouvrir range/nettoie ses
# sauvegardes : une suite de tests n'a pas a y toucher (cf. test_sauvegardes)
application.br.migrate_legacy = lambda *a, **k: []
import propagate_cf as _pcf_isole                          # noqa: E402
# ouvrir un projet renomme son ancien <rapport>.propagation.json : sur le VRAI
# dossier, ce serait a l'usager de le declencher, pas a une suite de tests
_pcf_isole.migrer_groupes = lambda *a, **k: None
application.br.prune_all = lambda *a, **k: []
fen = application.BidouilleWindow()
fen.show()
app.processEvents()
voulu_avant = fen.settings.value("journal_visible", "1")
check("la fenetre s'ouvre sur Mesures -> Variations",
      fen.tabs.currentWidget() is fen.tab_config
      and fen.tab_config.occupe_la_colonne())
check("… et le journal lui cede sa colonne", fen.journal.isHidden())
check("le bouton s'appelle « 🚀 Lancements » et dit comment la faire revenir",
      fen.btn_journal.text() == "◂ 🚀 Lancements")
check("ce retrait n'ecrase PAS le choix memorise de l'usager",
      fen.settings.value("journal_visible", "1") == voulu_avant)

sp = fen.tab_config.inner.widget(0).findChild(QSplitter)
check("Variations a trois volets : liste | formulaire | DAX",
      sp is not None and sp.count() == 3)
check("le DAX et l'apercu sont dans le volet de DROITE",
      sp.widget(2).isAncestorOf(fen.tab_config.ed_dax)
      and sp.widget(2).isAncestorOf(fen.tab_config.arbre_apercu))
check("… le formulaire au milieu",
      sp.widget(1).isAncestorOf(fen.tab_config.ed_name)
      and not sp.widget(1).isAncestorOf(fen.tab_config.ed_dax))
check("l'apercu n'est plus plafonne a 110 px",
      fen.tab_config.arbre_apercu.maximumHeight() > 1000)

inner = fen.tab_config.inner
from tabs.tab_config import IDX_RAW as _IDX_RAW                  # noqa: E402
check("Mesures : Variations, Arbre, Parametres de champ et JSON brut (ni Generer, ni Reglages)",
      [inner.tabText(i) for i in range(inner.count())]
      == ["Variations", "Arbre des mesures", "Paramètres de champ", "JSON brut"])
inner.setCurrentIndex(_IDX_RAW)                # « JSON brut »
app.processEvents()
check("JSON brut : le journal revient", not fen.journal.isHidden())
inner.setCurrentIndex(0)
app.processEvents()
check("retour a Variations : il se retire a nouveau", fen.journal.isHidden())

print("   Variations : l'y ouvrir l'y garde ouvert, sans rien changer ailleurs")
fen.btn_journal.click()
app.processEvents()
check("le bouton l'ouvre DANS Variations", not fen.journal.isHidden())
check("… choix retenu pour Variations",
      fen.settings.value("journal_visible_variations") in ("1", 1))
check("… sans toucher au choix d'ailleurs",
      fen.settings.value("journal_visible", "1") == voulu_avant)
fen.tabs.setCurrentWidget(fen.tab_report)
app.processEvents()
fen.tabs.setCurrentWidget(fen.tab_config)
app.processEvents()
check("de retour dans Variations, il y est toujours", not fen.journal.isHidden())
fen.btn_journal.click()
app.processEvents()
check("le refermer dans Variations le referme LA", fen.journal.isHidden())

inner.setCurrentIndex(_IDX_RAW)                # JSON brut : journal visible
app.processEvents()
fen.tab_config._reload()     # revient sur Variations SIGNAUX BLOQUES
app.processEvents()
check("un rechargement qui ramene a Variations y replie le journal",
      inner.currentIndex() == 0 and fen.journal.isHidden())
fen.tabs.setCurrentWidget(fen.tab_report)
app.processEvents()
check("onglet Rapport : le journal est la", not fen.journal.isHidden())

check("il est le volet de DROITE de la fenetre",
      fen.split.widget(1) is fen.journal)
check("il occupe toute la hauteur",
      fen.journal.height() >= fen.split.widget(0).height() - 4)


def largeur_journal():
    """0 si le journal n'est pas un volet du splitter : un temoin qui le
    remet sous les onglets doit echouer, pas planter la suite."""
    tailles = fen.split.sizes()
    return tailles[1] if len(tailles) > 1 else 0


largeur_avant = largeur_journal()
fen.resize(fen.width() + 300, fen.height())
app.processEvents()
check("l'agrandissement va au travail, pas au journal",
      largeur_avant and abs(largeur_journal() - largeur_avant) <= 2)
check("il ne peut pas etre reduit a rien par megarde",
      not fen.split.childrenCollapsible()
      and fen.journal.minimumWidth() == application.JOURNAL_MINI)

print("   tous les onglets ecrivent dans CE journal")
for nom in ("tab_report", "tab_wireframe", "tab_chopchop"):
    check(nom + " partage le journal de la fenetre",
          getattr(fen, nom).journal is fen.journal)
check("le panneau « Générer » aussi",
      fen.tab_config.model_panel.journal is fen.journal)
for nom in ("tab_report", "tab_wireframe"):
    check(nom + " n'a plus de bande de log", not hasattr(getattr(fen, nom), "log"))
check("« Générer » non plus", not hasattr(fen.tab_config.model_panel, "log"))
fen.tab_chopchop.panel.log.appendPlainText("Projet : essai")
tour()
check("ce qu'ecrit ChopChop arrive dans le journal, en MESSAGE horodate",
      HEURE.match(textes(fen.journal)[0])
      and textes(fen.journal)[0].endswith("Projet : essai"))

print("   le bouton, un run, un message")
avant = largeur_journal()
fen.btn_journal.click()
app.processEvents()
check("un clic masque le journal", fen.journal.isHidden())
check("… et c'est un CHOIX memorise",
      fen.settings.value("journal_visible") in ("0", 0))
fen.btn_journal.click()
app.processEvents()
check("un second clic le rouvre a la MEME largeur",
      not fen.journal.isHidden() and abs(largeur_journal() - avant) <= 2)
fen.btn_journal.click()
app.processEvents()
fen.journal.lancement("Couleurs des matrices")
fen.journal.fin()
app.processEvents()
check("un run le remontre (on ne laisse pas un outil ecrire a l'aveugle)",
      not fen.journal.isHidden())
check("… sans changer le choix memorise",
      fen.settings.value("journal_visible") in ("0", 0))
fen.btn_journal.click()     # re-masque (le choix reste « masque »)
fen.btn_journal.click()     # puis re-montre : choix « montre »
app.processEvents()
fen.btn_journal.click()
app.processEvents()
fen.journal.info("un simple message")
app.processEvents()
check("un simple message, lui, ne force pas la main", fen.journal.isHidden())
fen.btn_journal.click()
app.processEvents()

import tabs.tab_report as tr                                      # noqa: E402
seul = tr.ReportTab()
seul.journal.info("sans fenetre")
check("un onglet construit seul se fait un journal a lui",
      "sans fenetre" in seul.journal.texte())
seul.deleteLater()

# ===================================================================== 7
print("7. les editeurs de code")
import tabs.tab_config as tc                                      # noqa: E402

ed = tc.DaxEdit()
check("c'est bien un editeur de texte", isinstance(ed, QPlainTextEdit))
check("TAB n'echappe pas au champ", not ed.tabChangesFocus())


def frappe(widget, key, mods=Qt.NoModifier):
    """La frappe porte SON texte (\\t pour TAB) : sans lui, un editeur qui
    ne ferait rien de special passerait pour un editeur qui pose des
    espaces, faute d'avoir rien insere du tout."""
    texte = chr(9) if key in (Qt.Key_Tab, Qt.Key_Backtab) else ""
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, mods, texte))


ed.setPlainText("CALCULATE(")
ed.moveCursor(QTextCursor.End)
frappe(ed, Qt.Key_Return)
frappe(ed, Qt.Key_Tab)
ed.insertPlainText("[Weight],")
lignes = ed.toPlainText().split("\n")
check("TAB pose une TABULATION", lignes[1] == "\t[Weight],")
check("… pas des espaces", " " not in lignes[1])

ed.setPlainText("CALCULATE(\n\t\t[Weight]")
ed.moveCursor(QTextCursor.End)
frappe(ed, Qt.Key_Backtab, Qt.ShiftModifier)
check("Maj+TAB retire UNE tabulation",
      ed.toPlainText().split("\n")[1] == "\t[Weight]")
frappe(ed, Qt.Key_Backtab, Qt.ShiftModifier)
frappe(ed, Qt.Key_Backtab, Qt.ShiftModifier)
check("… jusqu'a la marge, et pas au-dela",
      ed.toPlainText().split("\n")[1] == "[Weight]")
ed.setPlainText("CALCULATE(\n" + " " * (tc.INDENT_DAX * 2) + "[Weight]")
ed.moveCursor(QTextCursor.End)
frappe(ed, Qt.Key_Backtab, Qt.ShiftModifier)
check("un ancien retrait en ESPACES se defait aussi, un cran a la fois",
      ed.toPlainText().split("\n")[1] == " " * tc.INDENT_DAX + "[Weight]")

print("   Debut s'arrete apres le retrait (et Maj+Debut ne prend pas le retrait)")
RET = " " * tc.INDENT_DAX
ed.setPlainText("CALCULATE(\n" + RET + "[Weight],\n)")
c = ed.textCursor()
c.setPosition(len("CALCULATE(\n" + RET + "[Weight],"))     # fin de la 2e ligne
ed.setTextCursor(c)
frappe(ed, Qt.Key_Home, Qt.ShiftModifier)
check("Maj+Debut depuis la fin : selectionne « [Weight], » SANS le retrait",
      ed.textCursor().selectedText() == "[Weight],")
frappe(ed, Qt.Key_Home, Qt.ShiftModifier)
check("un second Maj+Debut etend jusqu'a la colonne 0 (retrait compris)",
      ed.textCursor().selectedText() == RET + "[Weight],")
frappe(ed, Qt.Key_End)
frappe(ed, Qt.Key_Home)
check("Debut seul : curseur juste apres le retrait",
      ed.textCursor().positionInBlock() == tc.INDENT_DAX
      and not ed.textCursor().hasSelection())
frappe(ed, Qt.Key_Home)
check("… un second appui : colonne 0", ed.textCursor().positionInBlock() == 0)
frappe(ed, Qt.Key_Home)
check("… un troisieme : de nouveau apres le retrait",
      ed.textCursor().positionInBlock() == tc.INDENT_DAX)
c = ed.textCursor()
c.movePosition(QTextCursor.Start)
ed.setTextCursor(c)
frappe(ed, Qt.Key_End, Qt.NoModifier)
frappe(ed, Qt.Key_Home, Qt.ShiftModifier)
check("ligne sans retrait : Maj+Debut prend toute la ligne, comme avant",
      ed.textCursor().selectedText() == "CALCULATE(")
frappe(ed, Qt.Key_End, Qt.ControlModifier)
frappe(ed, Qt.Key_Home, Qt.ControlModifier)
check("Ctrl+Debut garde son sens : debut du texte",
      ed.textCursor().position() == 0)
ed.setPlainText("CALCULATE(\n\t[Weight],\n)")
c = ed.textCursor()
c.setPosition(len("CALCULATE(\n\t[Weight],"))
ed.setTextCursor(c)
frappe(ed, Qt.Key_Home, Qt.ShiftModifier)
check("retrait en TABULATION : Maj+Debut ne la prend pas non plus",
      ed.textCursor().selectedText() == "[Weight],")

check("l'editeur DAX de l'onglet est un DaxEdit",
      isinstance(fen.tab_config.ed_dax, tc.DaxEdit))
check("le JSON brut aussi (memes gestes)",
      isinstance(fen.tab_config.ed_raw, tc.DaxEdit))

# ===================================================================== 8
print("8. sous le VRAI theme de l'app : le code est en chasse fixe")
from core.theme import apply_app_theme                            # noqa: E402
from qtpy.QtGui import QFontDatabase                              # noqa: E402

for f in ("consola.ttf", "segoeui.ttf", "bahnschrift.ttf"):  # l'offscreen n'a pas de polices
    QFontDatabase.addApplicationFont(str(Path(r"C:\Windows\Fonts") / f))
apply_app_theme(app, "x", "Essai.Journal")
ed = tc.DaxEdit()
ed.show()
app.processEvents()
fm = ed.fontMetrics()
check("l'editeur DAX est en Consolas", ed.fontInfo().family() == "Consolas")
check("… donc un i est aussi large qu'un M (chasse fixe)",
      fm.horizontalAdvance("iiii") == fm.horizontalAdvance("MMMM"))
check("le cran de TAB vaut 4 espaces de la police AFFICHEE",
      abs(ed.tabStopDistance() - fm.horizontalAdvance(" " * tc.INDENT_DAX)) < 1)
onglet = tc.ConfigTab()
onglet.show()
app.processEvents()
check("l'apercu des noms aussi",
      onglet.arbre_apercu.fontInfo().family() == "Consolas")
from qtpy.QtWidgets import QLabel                                 # noqa: E402
from tabs.explorateur_jetons import POLICE_CODE                  # noqa: E402
check("les jetons de l'explorateur aussi", POLICE_CODE.family() == "Consolas")
from qtpy.QtWidgets import QGroupBox                              # noqa: E402
gb_dax = [g for g in onglet.findChildren(QGroupBox) if g.title() == "DAX"][0]
from core.theme import TITRE_POLICE                              # noqa: E402
check("les titres de groupe ont LEUR police (" + TITRE_POLICE + ")",
      gb_dax.fontInfo().family().startswith("Bahnschrift"))
check("… et sont plus grands que le texte",
      gb_dax.fontInfo().pointSizeF() > onglet.lbl_lint.fontInfo().pointSizeF())
check("… sans changer ce qu'ils contiennent (enfant direct, et plus bas)",
      all(w.fontInfo().family() == "Segoe UI" and not w.fontInfo().bold()
          for w in (onglet.lbl_lint, onglet.ed_name, onglet.cmb_kinds)))
onglet.hide()
ed.hide()

# ===================================================================== 9
print("9. les poignees de volets : un trait fin, de l'air de chaque cote")
from core.theme import Separateur, TRAIT                          # noqa: E402

fen.tabs.setCurrentWidget(fen.tab_report)
app.processEvents()


def trait_seul(sep):
    """La poignee n'allume QUE son pixel central, de la couleur TRAIT."""
    h = sep.handle(1)
    img = h.grab().toImage()
    if sep.orientation() == Qt.Horizontal:
        y = img.height() // 2
        allumes = [x for x in range(img.width())
                   if img.pixelColor(x, y).name().upper() == TRAIT.upper()]
        return h.width(), allumes == [img.width() // 2]
    x = img.width() // 2
    allumes = [y for y in range(img.height())
               if img.pixelColor(x, y).name().upper() == TRAIT.upper()]
    return h.height(), allumes == [img.height() // 2]


fen.tabs.setCurrentWidget(fen.tab_config)
inner.setCurrentIndex(0)
fen.btn_journal.click()             # journal visible dans Variations
app.processEvents()
droite = sp.widget(2)
for nom, sep in (("fenetre | journal", fen.split),
                 ("liste | formulaire | DAX", sp),
                 ("DAX | apercu", droite)):
    epaisseur, fin = trait_seul(sep)
    check(nom + " : un Separateur", isinstance(sep, Separateur))
    check(f"… prise de {Separateur.LARGEUR} px, un seul pixel dessine au centre",
          epaisseur == Separateur.LARGEUR and fin)

# ===================================================================== 10
print("10. la generation : un bouton en tete du journal, plus d'onglet")
import tabs.tab_model as tm                                       # noqa: E402

mp = fen.tab_config.model_panel
check("le panneau est pose DANS le journal", fen.journal.isAncestorOf(mp))
check("onglet Mesures : le bouton Generer est a l'ecran",
      mp.btn_generate.isVisible())
check("il est AU-DESSUS du fil : le run lance s'affiche juste dessous",
      mp.mapTo(fen.journal, QPoint(0, 0)).y()
      < fen.journal.vue.mapTo(fen.journal, QPoint(0, 0)).y())
fen.btn_journal.click()             # referme dans Variations
fen.tabs.setCurrentWidget(fen.tab_report)
app.processEvents()
check("ailleurs, le journal reste mais le bouton Generer s'efface",
      not fen.journal.isHidden() and not mp.isVisible())

fen.tab_config._set_dirty(True)
check("config modifie : le panneau le signale en continu",
      mp._non_sauve and not mp.lbl_unsaved.isHidden())
fen.tab_config._set_dirty(False)
check("… et plus rien une fois enregistre",
      not mp._non_sauve and mp.lbl_unsaved.isHidden())

print("   generer avec un config NON enregistre")


class FausseBoite:
    """Remplace la boite de dialogue : « clique » le bouton nomme `choix`."""
    AcceptRole, DestructiveRole, RejectRole = 0, 1, 2
    choix = ""
    proposes = []

    def __init__(self, parent=None):
        self._boutons, self._clic = [], None

    def setWindowTitle(self, _):
        pass

    def setText(self, _):
        pass

    def addButton(self, texte, _role):
        b = object()
        self._boutons.append((texte, b))
        FausseBoite.proposes.append(texte)
        return b

    def setDefaultButton(self, _):
        pass

    def exec_(self):
        for texte, b in self._boutons:
            if texte == FausseBoite.choix:
                self._clic = b
        return 0

    exec = exec_

    def clickedButton(self):
        return self._clic


m = tm.ModelTab()
appels = []
vraie = tm.QMessageBox
tm.QMessageBox = FausseBoite
try:
    m.sauver = lambda: appels.append("sauve") or True
    FausseBoite.choix = "Enregistrer puis générer"
    check("« Enregistrer puis generer » : enregistre, puis genere",
          m._resoudre_non_sauve() is True and appels == ["sauve"])
    m.sauver = lambda: False
    check("… et si l'enregistrement echoue, ne genere PAS",
          m._resoudre_non_sauve() is False)
    appels.clear()
    m.sauver = lambda: appels.append("sauve") or True
    FausseBoite.choix = "Générer l'ancienne version"
    check("« Generer l'ancienne version » : genere sans enregistrer",
          m._resoudre_non_sauve() is True and appels == [])
    FausseBoite.choix = "Annuler"
    check("« Annuler » : rien", m._resoudre_non_sauve() is False)
    m.sauver = None
    FausseBoite.proposes = []
    m._resoudre_non_sauve()
    check("sans moyen d'enregistrer, ce choix n'est pas propose",
          "Enregistrer puis générer" not in FausseBoite.proposes)
finally:
    tm.QMessageBox = vraie


class FauxProjet:
    config_json = Path("introuvable_pour_le_test.json")
    model_dir = Path("introuvable_pour_le_test.SemanticModel")


demandes = []
m2 = tm.ModelTab()
m2.project = FauxProjet()
m2._resoudre_non_sauve = lambda: demandes.append(1) or False
m2.set_unsaved(True)
m2._run()
check("generer avec des modifs non enregistrees DEMANDE d'abord",
      demandes == [1] and m2._runner is None)
demandes.clear()
m2.set_unsaved(False)
m2._run()                   # apercu coche + config introuvable : rien ne part
check("… et ne demande rien quand tout est enregistre", demandes == [])

print("   l'onglet Mesures fournit l'enregistrement, et dit s'il a reussi")
import shutil                                                     # noqa: E402
import tempfile                                                   # noqa: E402
from core.project import Project                                  # noqa: E402

copie = Path(tempfile.gettempdir()) / "pbid_journal_sauver"
shutil.rmtree(copie, ignore_errors=True)
copie.mkdir(parents=True)
shutil.copy2(PBI / "measures_config.json", copie / "measures_config.json")
ct = tc.ConfigTab()
ct.set_project(Project(copie / "Essai.pbip"))
check("le panneau de generation sait enregistrer (Enregistrer puis generer)",
      ct.model_panel.sauver == ct._save)
ct._set_dirty(True)
check("_save rend True quand il a ecrit", ct._save() is True)
check("… et le config n'est plus « non enregistre »",
      not ct.model_panel._non_sauve)
ct.project = None
check("_save rend False quand il n'a rien pu ecrire", ct._save() is False)
ct.deleteLater()
shutil.rmtree(copie, ignore_errors=True)

# ===================================================================== 11
print("11. l'apercu des noms : ce que chaque niveau AJOUTE, en couleur")
sn = tc.segments_nom
RAC = [("Weight", "racine")]
check("suffixe : la racine telle quelle, le reste a la variation",
      sn("{base} 7d avg", RAC, {}, "variation")
      == [("Weight", "racine"), (" 7d avg", "variation")])
check("un prefixe aussi",
      sn("CF {base}", RAC, {}, "variation")
      == [("CF ", "variation"), ("Weight", "racine")])
check("{kpi} prend la couleur de ce qu'il designe : la racine",
      sn("{base} vs {kpi}", RAC, {"kpi": ("Weight", "racine")}, "variation")
      == [("Weight", "racine"), (" vs ", "variation"), ("Weight", "racine")])
check("un jeton vide ne laisse rien",
      sn("{base}{branch}", RAC, {"branch": ("", "branche")}, "variation")
      == [("Weight", "racine")])
en_branche = sn("{base} YTD", RAC, {}, "branche")
check("en branche : racine, puis ce que la BRANCHE ajoute, puis la variation",
      sn("{base} PY", en_branche, {}, "variation")
      == [("Weight", "racine"), (" YTD", "branche"), (" PY", "variation")])


def fragments(arbre):
    """[(texte, couleur)] par ligne, tels que REELLEMENT rendus : lus dans
    le HTML que le délégué peint (un <span> coloré par segment)."""
    import re as _re
    out = []
    for i in range(arbre.topLevelItemCount()):
        html = arbre.topLevelItem(i).data(0, tc_ROLE_HTML) or ""
        out.append([(t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"),
                     c.upper())
                    for c, t in _re.findall(r"color:(#[0-9A-Fa-f]{6})[^>]*>(.*?)</span>",
                                            html)])
    return out


from tabs.fiche_mesure import ROLE_HTML as tc_ROLE_HTML           # noqa: E402


fen.tabs.setCurrentWidget(fen.tab_config)
fen.tab_config.inner.setCurrentIndex(0)
fen.tab_config._populate_list(select="Δ 7d")
app.processEvents()
lignes = fragments(fen.tab_config.arbre_apercu)
reel = next((l for l in lignes if l and l[0][0].startswith("[Réel")), [])
ytd = next((l for l in lignes if l and l[0][0].startswith("[YTD")), [])
check("Reel : etiquette grisee, racine, puis « Δ 7d » en vert",
      [c for _, c in reel] == [TEXT_MUTED.upper(), TEXT_DIM.upper(),
                               ACCENT.upper()]
      and reel[2][0] == " Δ 7d")
check("YTD : racine, « YTD » en bleu, puis « Δ 7d » en vert",
      [c for _, c in ytd] == [TEXT_MUTED.upper(), TEXT_DIM.upper(),
                              BLUE.upper(), ACCENT.upper()]
      and ytd[2][0] == " YTD" and ytd[3][0] == " Δ 7d")
from qtpy.QtWidgets import QLabel as _QLabel                      # noqa: E402
check("une legende dit ce que veut dire chaque couleur",
      any("+ branche" in l.text() and "+ variation" in l.text()
          for l in fen.tab_config.findChildren(_QLabel)))

print("   l'apercu applique les branches comme la generation")
ct_ = fen.tab_config
avant_branches = dict(ct_._config.get("branches") or {})
try:
    ct_._config["branches"] = {"YTD": {"variations": ["PY"]}}   # restreinte
    ct_._populate_list(select="Δ 7d")
    app.processEvents()
    check("branche restreinte : pas de ligne YTD pour une variation qu'elle "
          "n'applique pas",
          not any(l.startswith("[YTD") for l in
                  ct_.texte_apercu().splitlines()))
    ct_._populate_list(select="PY")
    app.processEvents()
    check("… mais bien pour celle qu'elle liste",
          any(l.startswith("[YTD") for l in
              ct_.texte_apercu().splitlines()))
finally:
    ct_._config["branches"] = avant_branches
ct_._populate_list(select="YTD")
app.processEvents()
check("une branche ne s'applique pas a elle-meme (plus de « Weight YTD YTD »)",
      not any(l.startswith("[YTD") for l in
              ct_.texte_apercu().splitlines()))

print("   la couleur ne change pas le NOM : c'est celui que le generateur prevoit")
import generate_measures as _gm                                   # noqa: E402

plan = _gm.generate(fen.project.model_dir, fen.tab_config._config,
                    dry_run=True, log=lambda *_: None)   # lecture seule
prevus = set(plan["created"]) | set(plan["updated"]) | set(plan["unchanged"])
ecarts = []
for vid in fen.tab_config._config.get("variations") or {}:
    fen.tab_config._populate_list(select=vid)
    for ligne in fen.tab_config.texte_apercu().splitlines():
        if ligne.startswith("[") and "] " in ligne:
            nom = ligne.split("] ", 1)[1]
            if nom not in prevus:
                ecarts.append((vid, nom))
check("chaque nom de l'apercu, pour chaque variation, est un nom que la "
      "generation produira", not ecarts)
if ecarts:
    print("      ecarts :", ecarts[:5])

# ===================================================================== 12
print("12. les jetons du DAX : connus en couleur, inconnus en rouge")
K = tc.KNOWN_PLACEHOLDERS


def jetons(texte, declares=(), dans_each=False):
    spans, etat = tc.reperer_jetons(texte, K,
                                    set(tc.JETONS_PORTEE) | set(declares),
                                    dans_each)
    return [(texte[d:f], g, c) for d, f, g, c in sorted(spans)], etat


check("{connu} / {faute de frappe}",
      jetons("({baseRef}, {dat})")[0]
      == [("{baseRef}", "accolade", True), ("{dat}", "accolade", False)])
check("les jetons de portee sont connus d'office (<<allTables>>…)",
      jetons("<<allTables>>")[0] == [("<<allTables>>", "chevron", True)])
check("un <<attribut>> n'est connu que DECLARE (attributs codes en dur)",
      jetons("<<tolerance>>")[0][0][2] is False
      and jetons("<<tolerance>>", {"tolerance"})[0][0][2] is True)
check("{table} est connu DANS <<each …>>, et seulement la",
      ("{table}", "accolade", True) in
      jetons("<<each ALLSELECTED({table})>>")[0]
      and jetons("RETURN {table}")[0] == [("{table}", "accolade", False)])
check("un constructeur de table « { 1, 2 } » n'est pas un jeton",
      jetons("VAR t = { 1, 2 }")[0] == [])
ouvert = jetons("CALCULATE(<<each ALL(")
suite = jetons("\t{table})>>)", dans_each=True)
check("un <<each ouvert se poursuit a la ligne suivante",
      ouvert[1] is True and suite[1] is False
      and ("{table}", "accolade", True) in suite[0]
      and (">>", "each", True) in suite[0])

print("   dans l'editeur, a la frappe")
ct = fen.tab_config
ct._config.setdefault("hardcodedAttributes", {})["tokens"] = {"tolerance": "col"}
ct._populate_list(select="PY")
ct.ed_dax.setPlainText("CALCULATE({baseRef}, {dat}) + <<tolerance>> + <<seuil>>")
app.processEvents()


def surligne(ed):
    """{texte: (couleur, souligne ?)} tel que pose par le surligneur."""
    b = ed.document().firstBlock()
    return {b.text()[r.start:r.start + r.length]:
            (r.format.foreground().color().name().upper(),
             r.format.underlineStyle() != 0)
            for r in b.layout().formats()}


cs = surligne(ct.ed_dax)
check("{baseRef} en bleu", cs.get("{baseRef}", ("", 0))[0] == BLUE.upper())
check("<<tolerance>> (declare) en vert",
      cs.get("<<tolerance>>", ("", 0))[0] == ACCENT.upper())
check("{dat} et <<seuil>> en ROUGE et soulignes",
      all(cs.get(t, ("", False)) == (RED.upper(), True)
          for t in ("{dat}", "<<seuil>>")))
check("l'avertissement nomme exactement les memes",
      "Placeholder(s) inconnu(s) : {dat}" in ct.lbl_lint.text()
      and "Attribut(s) inconnu(s) : <<seuil>>" in ct.lbl_lint.text())

ct._config["hardcodedAttributes"]["tokens"]["seuil"] = "col2"
ct._refresh_lint_preview()
app.processEvents()
check("declarer l'attribut le fait passer au vert, sans enregistrer",
      surligne(ct.ed_dax).get("<<seuil>>", ("", 0))[0] == ACCENT.upper()
      and "<<seuil>> —" not in ct.lbl_lint.text()
      and "Attribut(s) inconnu(s)" not in ct.lbl_lint.text())

ct.ed_dax.setPlainText("CALCULATE({baseRef}, <<each ALLSELECTED({table})>>)")
app.processEvents()
check("{table} dans <<each …>> n'est plus signale a tort",
      ct.lbl_lint.text() == "")
ct._config.pop("hardcodedAttributes", None)

# ===================================================================== 13
print("13. les « cle : valeur » du journal, en tableau")
cv = jm.cle_valeur
check("une ligne « cle : valeur » se reconnait",
      cv("Modèle : 131 mesure(s) connues") == ("Modèle", ["131 mesure(s) connues"]))
check("une enumeration donne une valeur par element",
      cv("KPI cibles   : Body Fat %, Total Steps, Weight")
      == ("KPI cibles", ["Body Fat %", "Total Steps", "Weight"]))
check("… coupee aux virgules de PREMIER niveau seulement",
      cv("Ordre des KPI : colonne « ordre » (3 KPI sans valeur, placés à la fin)")[1]
      == ["colonne « ordre » (3 KPI sans valeur, placés à la fin)"])
check("la PREMIERE « : » separe la cle",
      cv("Paramètre : P_x : 80 rangées") == ("Paramètre", ["P_x : 80 rangées"]))
check("une longue liste reste d'un bloc (pas 42 rangees)",
      len(cv("Bases : " + ", ".join("K%d" % i for i in range(42)))[1]) == 1)
check("un marqueur (⚠, ∅, ·) n'est pas une cle",
      cv("⚠ branche YTD : inconnue") is None
      and cv("  ∅ Calories : PY, YoY %") is None
      and cv("  · x — y : a, b") is None)
check("une phrase sans « : » non plus",
      cv("Rouvre le .pbip dans Power BI Desktop.") is None)

j = jm.Journal()
j.resize(440, 400)
j.show()
j.lancement("Propagation")
j.ligne("KPI template : Average Steps")
j.ligne("KPI cibles   : Body Fat %, Total Steps, Weight")
j.ligne("Modèle : 131 mesure(s) connues (référence vérifiée avant écriture, "
        "sur le modèle entier et toutes ses tables).")
j.ligne("⚠ branche 'YTD' : variation inconnue.")
j.ligne("Terminé : 1 entrée(s) écrites.")
app.processEvents()
r = blocs(j)[1:]
check("la cle et sa valeur sur une rangee (tabulation entre les deux)",
      r[0]["texte"] == "KPI template\tAverage Steps")
check("… la cle grisee, la valeur en texte courant",
      r[0]["couleur_debut"] == TEXT_MUTED.upper()
      and r[0]["couleur"] == TEXT_DIM.upper())
check("une enumeration : trois rangees",
      [b["texte"] for b in r[1:4]] == ["KPI cibles\tBody Fat %", "Total Steps",
                                       "Weight"])


def x_valeur(bloc):
    """Abscisse du debut de la VALEUR dans ce bloc."""
    lay = bloc.layout()
    t = bloc.text()
    if "\t" in t:
        return lay.lineAt(0).cursorToX(t.index("\t") + 1)[0]
    return lay.lineAt(0).x()


b = j.vue.document().begin().next()          # apres la banniere
xs = []
while b.isValid() and len(xs) < 5:
    xs.append(x_valeur(b))
    b = b.next()
check("toutes les valeurs commencent a la MEME colonne",
      max(xs[:5]) - min(xs[:5]) < 1.5 and abs(xs[0] - jm.COL_CLE) < 1.5)
modele = j.vue.document().begin()
while modele.isValid() and not modele.text().startswith("Modèle"):
    modele = modele.next()
lay = modele.layout()
check("une valeur trop longue revient a la ligne DANS sa colonne",
      lay.lineCount() > 1
      and abs(lay.lineAt(1).x() - jm.COL_CLE) < 1.5)
check("un ⚠ garde sa ligne et sa couleur",
      any(x["texte"].startswith("⚠") and x["couleur"] == YELLOW.upper()
          for x in r))
check("le verdict « Terminé » aussi (vert, pas en tableau)",
      any(x["texte"].startswith("Terminé") and "\t" not in x["texte"]
          and x["couleur"] == GREEN.upper() for x in r))
j.hide()

print("   le resume des groupes de propagation se lit en tableau")
import propagate_cf as _pcf                                       # noqa: E402
lignes_resume = []
_pcf_propagate = _pcf.propagate
try:
    _pcf.propagate = lambda *a, **k: 0          # seul le RESUME nous interesse
    import tempfile as _tf                                         # noqa: E402
    gfich = Path(_tf.gettempdir()) / "groupes_test.propagation.json"
    import json as _json                                           # noqa: E402
    gfich.write_text(_json.dumps({"groupes": [
        {"nom": "sommeil", "gabarit": "Average Sleep Duration",
         "kpis": ["Average Sleep Duration"]},
        {"nom": "pas", "gabarit": "Average Steps", "kpis": []}]}),
        encoding="utf-8")
    _pcf.propagate_groupes(str(fen.project.report_dir), groupes_json=str(gfich),
                           dry_run=True, log=lignes_resume.append)
finally:
    _pcf.propagate = _pcf_propagate
    gfich.unlink()
rangee = [l for l in lignes_resume if l.strip().startswith("pas :")]
check("« groupe : gabarit (gabarit), KPI, KPI… » — le gabarit en tete",
      rangee and cv(rangee[0])[0] == "pas"
      and cv(rangee[0])[1][0] == "Average Steps (gabarit)"
      and len(cv(rangee[0])[1]) > 1)

print("   le plan de la grille des sources se lit en tableau")
lignes_plan = []
try:
    _pcf.propagate = lambda *a, **k: 0          # seul le PLAN nous interesse
    _pcf.propagate_regles(
        str(fen.project.report_dir),
        {"base": "Average Steps", "colonnes": {"PY": "Average Steps"},
         "groupes": [{"nom": "Poids", "kpis": ["Weight", "Body Fat %"],
                      "base": "Weight"}],
         "exceptions": [
            {"source": "Weight", "kpis": ["Total Steps"],
             "variations": ["YoY %"]},
            {"source": _pcf.MANUEL, "kpis": ["Average Sleep Duration"],
             "variations": ["Réel"]}]},
        dry_run=True, variations=[], log=lignes_plan.append)
finally:
    _pcf.propagate = _pcf_propagate


def plan(debut):
    return next((cv(l) for l in lignes_plan if l.strip().startswith(debut)),
                None)


check("« source → variation : copieurs » — un copieur par rangee",
      plan("Weight →") == ("Weight → YoY %", ["Total Steps"]))
check("« variation à la main : KPI » — ceux qui gardent le leur, en mots",
      plan("Réel à la main") == ("Réel à la main", ["Average Sleep Duration"]))
check("un gabarit par variation pour tous",
      plan("Average Steps → PY") == ("Average Steps → PY", ["tous les KPI"]))
check("un groupe, son gabarit, ses KPI — un par rangee",
      plan("Groupe Poids") == ("Groupe Poids ← Weight, par-dessus la base",
                               ["Weight", "Body Fat %"]))
check("la base, d'un bloc (pas coupee a une virgule)",
      plan("Average Steps :") == ("Average Steps",
                                  ["gabarit de base (tout le reste)"]))
check("aucun symbole dans le plan",
      not any(ch in l for l in lignes_plan for ch in "★✋·∅"))

# ===================================================================== 14
print("14. la presentation")
from core import theme as _th                                     # noqa: E402
from qtpy.QtGui import QImage                                     # noqa: E402
from qtpy.QtWidgets import QToolButton, QScrollArea               # noqa: E402

print("   les titres de groupe DANS le cadre")
gb_dax.show()
app.processEvents()
img = gb_dax.grab().toImage()


def verdatre(c):
    return c.green() > c.red() + 40 and c.green() > c.blue()


bord = next((y for y in range(img.height())
             if img.pixelColor(img.width() // 2, y).name().upper()
             == _th.BORDER.upper()), None)
titre_y = [y for y in range(min(40, img.height())) for x in range(8, 80)
           if verdatre(img.pixelColor(x, y))]
check("le trait du haut du cadre est bien la (sinon ce qui suit ne prouve rien)",
      bord is not None and bord < 4)
check("le titre est tout ENTIER sous le trait — plus a cheval dessus",
      titre_y and min(titre_y) > bord + 2)

print("   une coche plus fine et plus petite")
import pathlib as _pl                                             # noqa: E402
import tempfile as _tf2                                           # noqa: E402
# un @2x d'une execution precedente ne doit pas faire passer le test
(_pl.Path(_tf2.gettempdir()) / "bidouille_check@2x.png").unlink(missing_ok=True)
c1, d1 = _th._write_indicator_icons()
ic = QImage(c1)
encre = sum(1 for x in range(ic.width()) for y in range(ic.height())
            if ic.pixelColor(x, y).alpha() > 128)
check("la coche marque bien moins de pixels que l'ancienne (33)", 0 < encre <= 22)
import pathlib as _pl                                             # noqa: E402
double = _pl.Path(c1).with_name(_pl.Path(c1).stem + "@2x.png")
check("une version @2x existe pour les ecrans a echelle",
      double.exists() and QImage(str(double)).width() == 30)
check("la case est moins arrondie (rayon 3 px)",
      "border-radius: 3px" in _th._indicator_qss("QCheckBox::indicator"))

print("   les Reglages globaux s'expliquent")
glob = onglet._dlg_reglages                     # la fenetre ⚙ Reglages
# Paramètres de champ (leur onglet, plus une page des Réglages) : 1 ⓘ (la
# case) + 8 réglages communs ; les réglages PAR TABLE sont dans l'éditeur de
# liste, avec leurs infobulles
for ou, titre, n_min in ((onglet.inner.widget(tc.IDX_PARAM), "Paramètres de champ", 9),
                         (glob, "Génération (settings)", 9)):
    gbx = [g for g in ou.findChildren(QGroupBox) if g.title() == titre]
    aides = [b for b in gbx[0].findChildren(QToolButton)
             if b.text() == "ⓘ" and len(b.toolTip()) > 15] if gbx else []
    resumes = [l for l in gbx[0].findChildren(QLabel)
               if l.wordWrap() and len(l.text()) > 60] if gbx else []
    check(f"« {titre} » : un ⓘ par reglage ({len(aides)}/{n_min})",
          len(aides) >= n_min)
    check(f"… et une phrase qui dit a quoi sert le groupe", bool(resumes))
check("dryRun ne renvoie plus a un « onglet Modèle » disparu",
      "Modèle" not in onglet.g_dryRun.text())

print("   la fiche Excel de l'onglet Rapport")
fr = fen.tab_report
fr._refresh_td_label()
check("le FICHIER seul, le chemin complet en infobulle",
      fr.lbl_td.text() == _pl.Path(fr._td_spec()["path"]).name
      and fr.lbl_td.toolTip().endswith(fr.lbl_td.text()))
check("les trois colonnes lues, chacune nommee",
      all(x in fr.lbl_td_colonnes.text()
          for x in ("clé", "fond", "texte", fr._td_spec()["keyColumn"])))
appels_reglages = []
vrai_ouvrir = fen.tab_config.ouvrir_reglages
fen.tab_config.ouvrir_reglages = lambda page="": appels_reglages.append(page or 1) or False
fr.lbl_td_reglage.linkActivated.emit("reglages")
app.processEvents()
check("le lien de la fiche ouvre la fenetre ⚙ Reglages, sur la page de l'Excel",
      appels_reglages == ["excel"])
from qtpy.QtWidgets import QPushButton as _QPB2                  # noqa: E402
engrenage = [b for b in fen.findChildren(_QPB2) if b.text() == "⚙ Réglages"]
if engrenage:
    engrenage[0].click()
check("le bouton ⚙ Reglages de la barre aussi (sur la derniere page vue)",
      appels_reglages == ["excel", 1])
fen.tab_config.ouvrir_reglages = vrai_ouvrir

print("   un journal plus large")
check("largeur par defaut : 440 px", application.JOURNAL_LARGEUR == 440)
prj.reglages().setValue("journal_largeur", 311)
prj.reglages().remove("journal_largeur_revue")
f2 = application.BidouilleWindow()
check("une largeur retenue plus etroite est elargie, UNE fois",
      int(f2.settings.value("journal_largeur")) == 440)
f2.close()
prj.reglages().setValue("journal_largeur", 300)
f3 = application.BidouilleWindow()
check("… ensuite, la largeur choisie a la poignee est respectee",
      int(f3.settings.value("journal_largeur")) == 300)
f3.close()
# la barre projet imposait ~1600 px a elle seule (chemin complet du projet)
check("la barre projet n'impose plus une fenetre geante (< 1000 px)",
      fen.split.widget(0).layout().itemAt(0).minimumSize().width() < 1000)

# ===================================================================== 15
print("15. la fenetre ⚙ Reglages : Annuler oublie, Enregistrer ecrit")
from qtpy.QtWidgets import QDialog as _QDialog                    # noqa: E402
import shutil as _sh                                              # noqa: E402
import tempfile as _tf3                                           # noqa: E402
import json as _js                                                # noqa: E402
from core.project import Project as _Projet                       # noqa: E402

copie_r = Path(_tf3.gettempdir()) / "pbid_reglages_fenetre"
_sh.rmtree(copie_r, ignore_errors=True)
copie_r.mkdir(parents=True)
_sh.copy2(PBI / "measures_config.json", copie_r / "measures_config.json")
ct = tc.ConfigTab()
ct.set_project(_Projet(copie_r / "Essai.pbip"))
dlg = ct._dlg_reglages


def fenetre(reponse, geste=None):
    """Remplace l'attente modale : fait `geste` « dans » la fenetre, puis
    repond Accepted / Rejected."""
    def faux_exec():
        if geste:
            geste()
        return reponse
    dlg.exec_ = faux_exec
    dlg.exec = faux_exec


def sur_disque(cle):
    return (_js.loads((copie_r / "measures_config.json").read_text(
        encoding="utf-8")).get("settings") or {}).get(cle)


avant = sur_disque("sourceTable")
ct._set_dirty(False)
fenetre(_QDialog.Rejected, lambda: ct.g_sourceTable.setText("_touchee"))
ecrit = ct.ouvrir_reglages()
check("Annuler : rien d'ecrit", ecrit is False and sur_disque("sourceTable") == avant)
check("… le config en memoire n'a pas bouge",
      (ct._config.get("settings") or {}).get("sourceTable") == avant)
check("… et l'orange allume dans la fenetre s'eteint", ct._dirty is False)

fenetre(_QDialog.Accepted, lambda: ct.g_sourceTable.setText("_mesures_bis"))
check("Enregistrer : le config est ecrit, avec le reglage change",
      ct.ouvrir_reglages() is True and sur_disque("sourceTable") == "_mesures_bis")
check("… et le bouton Sauvegarder ne reste pas allume", ct._dirty is False)

print("   depuis le JSON brut : le texte a l'ecran ne reecrit pas l'ancien reglage")
ct.inner.setCurrentIndex(tc.IDX_RAW)                 # JSON brut
app.processEvents()
fenetre(_QDialog.Accepted, lambda: ct.g_sourceTable.setText("_depuis_le_brut"))
ct.ouvrir_reglages()
check("le reglage de la fenetre est bien celui ecrit",
      sur_disque("sourceTable") == "_depuis_le_brut")
check("… et le JSON brut affiche le config a jour",
      '"_depuis_le_brut"' in ct.ed_raw.toPlainText())

appels_exec = []
fenetre(_QDialog.Accepted, lambda: appels_exec.append(1))
ct.ed_raw.setPlainText("{ pas du json")
import tabs.tab_config as _tcm                                    # noqa: E402
_vrai_warning = _tcm.QMessageBox.warning
_tcm.QMessageBox.warning = staticmethod(lambda *a, **k: None)
try:
    refuse = ct.ouvrir_reglages()
finally:
    _tcm.QMessageBox.warning = _vrai_warning
check("un JSON brut invalide empeche d'ouvrir (on n'irait pas plus loin sur un "
      "config faux)", refuse is False and appels_exec == [])
ct.deleteLater()
_sh.rmtree(copie_r, ignore_errors=True)

# ===================================================================== 16
print("16. les tiroirs : un run bavard se replie, un clic l'ouvre")
from qtpy.QtGui import QMouseEvent                                # noqa: E402
from qtpy.QtCore import QPointF                                   # noqa: E402

j = jm.Journal()
j.resize(440, 500)
j.show()
app.processEvents()
j.lancement("court")
for i in range(jm.PLI_SEUIL):
    j.ligne(f"ligne {i}")
j.fin()
tour()
court = j.vue.document().begin()
check(f"un run de {jm.PLI_SEUIL} lignes reste ouvert (rien a cacher)",
      not j.est_replie(court) and court.next().isVisible())

hauteur_avant = j.vue.document().documentLayout().documentSize().height()
j.lancement("bavard")
for i in range(12):
    j.ligne(f"KPI {i} : valeur {i}")
j.ligne("⚠ une chose a voir")
j.fin()
tour()
ban = j.vue.document().begin()
details = j._details(ban)
check("un run bavard se replie sur sa banniere",
      j.est_replie(ban) and details and not any(b.isVisible() for b in details))
check("… la fleche dit qu'il est replie",
      ban.text().startswith(jm.FLECHE_REPLIE))
check("… la banniere dit combien de lignes elle cache",
      f"{len(details)} lignes" in ban.text())
check("… et qu'il y a un ⚠ dedans", "⚠ 1" in ban.text())
check("replie, il ne prend presque plus de place",
      j.vue.document().documentLayout().documentSize().height()
      < hauteur_avant + 60)
check("le texte reste la (copier, chercher)",
      "KPI 11" in j.texte() and "une chose a voir" in j.texte())

def banniere_de(titre):
    """La banniere d'un run, cherchee a NOUVEAU dans le document : une
    poignee de bloc gardee d'avant une insertion en tete designe ensuite
    la NOUVELLE premiere ligne (Qt coupe le premier bloc pour inserer)."""
    b = j.vue.document().begin()
    while b.isValid():
        if (b.blockFormat().property(jm.ROLE) == "banniere"
                and "  " + titre in b.text()):
            return b
        b = b.next()
    return None


check("le run plus ancien, court, est reste ouvert",
      banniere_de("court") is not None
      and not j.est_replie(banniere_de("court")))


def clic(bloc):
    r = j.vue.document().documentLayout().blockBoundingRect(bloc)
    y = r.center().y() - j.vue.verticalScrollBar().value()
    p = QPointF(r.left() + 20, y)
    for t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        ev = QMouseEvent(t, p, p, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(j.vue.viewport(), ev)
    app.processEvents()


clic(ban)
check("un clic sur la banniere ouvre le tiroir",
      not j.est_replie(ban) and all(b.isVisible() for b in details)
      and ban.text().startswith(jm.FLECHE_OUVERT))
texte_ligne = details[3].text()
clic(details[3])
check("un clic sur une ligne du tiroir ne change RIEN : banniere ouverte,",
      not j.est_replie(ban))
check("… toutes les lignes visibles,", all(b.isVisible() for b in details))
check("… et la ligne cliquee intacte (pas de fleche ecrite dedans)",
      details[3].text() == texte_ligne)
clic(ban)
check("un second clic sur la banniere le referme", j.est_replie(ban))

j.lancement("en cours")
for i in range(12):
    j.ligne(f"ligne {i}")
en_cours = j.vue.document().begin()
j.basculer(en_cours)
check("le run EN COURS ne se replie pas (ses lignes arrivent encore)",
      not j.est_replie(en_cours) and en_cours.next().isVisible())
j.fin()
tour()
check("… il se replie a la fin, s'il a ete bavard", j.est_replie(en_cours))
check("un nouveau run en haut n'ouvre pas les tiroirs du dessous",
      banniere_de("bavard") is not None
      and j.est_replie(banniere_de("bavard"))
      and banniere_de("bavard").position() != banniere_de("en cours").position())

j.lancement("echec")
for i in range(12):
    j.ligne(f"ligne {i}")
j.erreur("Traceback …\nValueError: x")
j.fin(echec=True)
tour()
echec = j.vue.document().begin()
check("un ECHEC reste ouvert, meme bavard : il faut le lire",
      not j.est_replie(echec) and echec.next().isVisible())
j.hide()

fen.close()
prj.reglages().clear()
print("\n" + ("TOUT OK" if _ok else "*** DES ECHECS ***"))
sys.exit(0 if _ok else 1)
