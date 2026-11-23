# -*- coding: utf-8 -*-
"""La GRILLE DES SOURCES : un gabarit de base pour tout le monde, des
exceptions case par case (KPI x variation).

    py tests\\test_sources_propagation.py

Ce que ce fichier verifie :

  1. LE CLASSEMENT : chaque mesure tombe dans SA colonne — le parametre de
     champ d'abord, la branche mise de cote, le suffixe le plus long.
  2. LA LECTURE : le format actuel, l'ancien (groupes) converti tel quel,
     la tolerance, la source d'une exception comprise d'office.
  3. LES REFUS : source inconnue, case a deux sources, copie de copie — et
     rien n'est ecrit.
  4. LA PRECEDENCE : case > ligne > colonne > base ; un gabarit de groupe
     se pose PAR-DESSUS « Tous les KPI » et la base (sauf groupe
     independant).
  5. LA BASE COUVRE TOUT LE MONDE, sauf les exceptions — le KPI source d'une
     exception recoit la base pour le reste. C'est la demande : « le PY une
     fois, pour tous », et les petites exceptions a part.
  6. A LA MAIN, et une variation pour tous venue d'ailleurs.
  7. L'ORDRE DES PASSES NE COMPTE PAS : un visuel n'est « pilote » par une
     source que par SES cases.
  8. IDEMPOTENCE, et UNE sauvegarde qui defait tout.
  9. LES PERTES ANNONCEES : une case qui copie une source sans rien pour elle
     perd son formatage — c'est dit AVANT d'ecrire, et c'est exact.
 10. L'EDITION de la grille (ce que fait la fenetre) : une source est
     toujours sa propre source, les copieurs suivent, ce que l'usager pose
     reste pose.
 11. LES GROUPES : une famille qui copie son gabarit ; « Tous les KPI »
     lui arrive PAR son gabarit, qui le recoit dessous. Independant : non.
 12. UN GROUPE DANS LE RAPPORT : il propage entre ses KPI, et a eux seuls.
 13. LES CIBLES : une base a part entiere. Leurs variations — hors
     parametre de champ — ont leurs colonnes (« Cible ecart »), lues dans
     les NOMS des mesures : un KPI qui a une cible les a toutes.
 14. LES CARTES : une entree appartient a la variation qu'elle MONTRE —
     l'etiquette de reference « PY » (titre et detail compris), l'image
     sparkline —, pas a la mesure de son selector, qui est celle du KPI.
     Sinon, sur une page de cartes, seul le gabarit de base propageait.
 15. PAR-DESSUS : la base passe sous le gabarit d'un groupe, propriete par
     propriete — ce que le gabarit regle l'emporte, le reste vient de la
     base, et ses KPI copient le tout. Un changement de la base y descend
     (la MEMOIRE de ce qu'on a pose), une retouche du gabarit reste a lui.
 16. LES FACES de branche suivent leur Reel, meme quand il gagne ou perd une
     propriete : plus de doublon a l'ancienne valeur sur les faces YTD.
 17. LE DETAIL d'une etiquette de carte a sa colonne (« PY — détail ») : il
     se propage — ou reste a la main — sans emporter l'etiquette, et
     reciproquement. Sans regle a lui, il suit son etiquette.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

FIT = Path(__file__).resolve().parent.parent
# les projets Power BI vivent HORS de l'outil (cf. moteurs/chemins.py)
PBI = FIT.parent / "PowerBI"
if os.environ.get("PBIDOUILLE_PROJETS", "").strip():
    PBI = Path(os.environ["PBIDOUILLE_PROJETS"].strip())
sys.path.insert(0, str(FIT / "bidouille"))
sys.path.insert(0, str(FIT / "bidouille" / "moteurs"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import exiger_projet, PROJET_DEMO, ajouter_cibles   # noqa: E402

exiger_projet(PBI, PROJET_DEMO, "measures_config.json")

import backup_restore as br                       # noqa: E402
import propagate_cf as pc                         # noqa: E402

PROJ = PROJET_DEMO
ENT = "_mesures"
FP = "P_Indicateurs_parCalcul"
CFG = json.loads((PBI / "measures_config.json").read_text(encoding="utf-8"))
VARIATIONS = pc.variations_du_config(CFG)
_ok = True


def check(label, cond):
    global _ok
    _ok = _ok and bool(cond)
    print(("  ok   " if cond else "  ECHEC ") + label)


def rmtree(p):
    if p.exists():
        shutil.rmtree(p, onerror=lambda f, path, e: (os.chmod(path, stat.S_IWRITE), f(path)))


def copie(nom):
    c = Path(tempfile.gettempdir()) / ("pbid_src_" + nom)
    rmtree(c)
    c.mkdir(parents=True)
    for s in (".Report", ".SemanticModel"):
        shutil.copytree(PBI / (PROJ + s), c / (PROJ + s))
    return c


def visuels(R):
    return sorted(R.glob("definition/pages/*/visuals/*/visual.json"))


def lire(vj):
    return json.loads(vj.read_text(encoding="utf-8"))


def ecrire(vj, data):
    vj.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8")


def entree(md, marqueur):
    """Une entree reconnaissable : son nom de propriete sert de marqueur."""
    return {"properties": {marqueur: {"expr": {"Literal": {"Value": "1D"}}}},
            "selector": {"metadata": ENT + "." + md,
                         "data": [{"dataViewWildcard": {"matchingOption": 0}}]}}


def ou_poser(R, kpi, sauf=()):
    """(visuel, cle) du 1er visuel qui porte deja des entrees de ce KPI."""
    for vj in visuels(R):
        if vj in sauf:
            continue
        objets = (lire(vj).get("visual") or {}).get("objects") or {}
        for cle, liste in objets.items():
            if isinstance(liste, list) and any(
                    (pc.entry_metadata(e) or "").startswith(ENT + "." + kpi)
                    for e in liste):
                return vj, cle
    return None, None


def poser(vj, cle, *entrees):
    data = lire(vj)
    data["visual"]["objects"][cle].extend(entrees)
    ecrire(vj, data)


def porteurs(R, marqueur, vj_seul=None) -> set:
    """Les metadata des entrees qui portent ce marqueur."""
    out = set()
    for vj in ([vj_seul] if vj_seul else visuels(R)):
        objets = (lire(vj).get("visual") or {}).get("objects") or {}
        for liste in objets.values():
            for e in liste if isinstance(liste, list) else []:
                props = e.get("properties") if isinstance(e, dict) else None
                if isinstance(props, dict) and marqueur in props:
                    out.add(pc.entry_metadata(e))
    return out


def etat(R) -> dict:
    return {str(p.relative_to(R)): p.read_text(encoding="utf-8")
            for p in visuels(R)}


def propager(R, regles=None, log=None, **kw):
    return pc.propagate_regles(R, regles, field_parameter=FP,
                               variations=VARIATIONS, branches=["YTD"],
                               toutes_branches=["YTD"],
                               log=log or (lambda *_: None), **kw)


M = PBI / (PROJ + ".SemanticModel")
KPIS = pc.kpis_from_parameter(M, FP)
print("   KPI du modele :", KPIS)
SLEEP, BASE, FAT, TOTAL, WEIGHT = KPIS      # ordre du parametre de champ
check("le modele a les cinq KPI attendus",
      KPIS == ["Average Sleep Duration", "Average Steps", "Body Fat %",
               "Total Steps", "Weight"])

# ===================================================================== 1
print("1. le classement : chaque mesure dans SA colonne")
fwd, rev = pc.read_fp_maps(M, FP)
cl = pc.classeur(branches=["YTD"], fp_reverse=rev, variations=VARIATIONS)
for md, attendu, pourquoi in (
        ("Weight", "Réel", "la mesure du KPI"),
        ("Weight YTD", "Réel", "sa face de branche"),
        ("Weight PY", "PY", "une variation du parametre"),
        ("Weight YTD PY", "PY", "la meme, sur la branche"),
        ("Weight CF YoY %", "CF YoY %", "le suffixe le plus long d'abord"),
        ("Weight YTD CF YoY %", "CF YoY %", "… aussi sur la branche"),
        ("Weight sparkline", "sparkline", "une variation hors parametre"),
        ("Weight PY ecart", "PY", "une mesure derivee suit sa variation"),
        ("Weight titre", "Réel", "une mesure propre au KPI : son Reel")):
    check(f"{md:22} -> {attendu:10} ({pourquoi})",
          cl(ENT + "." + md, WEIGHT) == attendu)
cl_sans = pc.classeur(branches=[], fp_reverse=rev, variations=VARIATIONS)
check("classer SANS les branches du modele se trompe, hors parametre de "
      "champ (« YTD CF YoY % » -> YTD) — d'ou toutes_branches",
      cl_sans(ENT + ".Weight YTD CF YoY %", WEIGHT) == "YTD")
cl_emboite = pc.classeur(branches=["YTD"], variations=[
    ("YoY %", "YoY %"), ("YoY % CF", "YoY % CF")])
check("deux suffixes emboites : le plus LONG l'emporte",
      cl_emboite(ENT + ".Weight YoY % CF", WEIGHT) == "YoY % CF"
      and cl_emboite(ENT + ".Weight YoY %", WEIGHT) == "YoY %")
cl_cibles = pc.classeur(branches=["YTD"], fp_reverse=rev, variations=VARIATIONS,
                        cibles={"Weight cible", "Weight cible YTD"})
check("une cible (dossier dedie) a sa colonne « Cible », branche comprise",
      cl_cibles(ENT + ".Weight cible", WEIGHT) == "Cible"
      and cl_cibles(ENT + ".Weight cible YTD", WEIGHT) == "Cible")
check("… et une mesure derivee de la cible, la sienne",
      cl_cibles(ENT + ".Weight cible ecartCF", WEIGHT) == "Cible ecartCF")
check("le KPI le plus LONG gagne (« Total Steps Goal » n'est pas du Total "
      "Steps)", pc.kpi_de(ENT + ".Total Steps Goal PY",
                          ["Total Steps Goal", "Total Steps"]) == "Total Steps Goal")
check("le Reel porte le nom que lui donne le parametre de champ",
      pc.libelle_reel(rev) == "Réel")
colonnes = pc.analyser(PBI / (PROJ + ".Report"), field_parameter=FP,
                       branches=["YTD"], variations=VARIATIONS)["variations"]
print("   colonnes de la grille :", colonnes)
check("la grille montre TOUTES les variations du config, dans le parametre "
      "de champ ou non", {"sparkline", "CF Δ 30d", "CF YoY %"} <= set(colonnes)
      and {"PY", "YoY %", "MTD"} <= set(colonnes))
check("… dans l'ordre du config, le Reel en tete — le detail d'une "
      "etiquette de carte juste apres elle",
      [v for v in colonnes if not pc.etiquette_du_detail(v)]
      == ["Réel"] + [v for v, _s in VARIATIONS if v != "YTD"]
      and all(colonnes[colonnes.index(v) - 1] == pc.etiquette_du_detail(v)
              for v in colonnes if pc.etiquette_du_detail(v)))
check("… une BRANCHE n'est pas une colonne : chaque colonne couvre sa face YTD",
      "YTD" not in colonnes)
check("une variation au nom hors motif « {base} … » a sa colonne quand meme",
      ("Mix", None) in pc.variations_du_config({"variations": {
          "Mix": {"namePattern": "Écart {base}"}}}))

# ===================================================================== 2
print("2. la lecture du fichier")
tmp = Path(tempfile.gettempdir()) / "pbid_src_fichiers"
rmtree(tmp)
tmp.mkdir(parents=True)
check("absent = None (rien a propager, rien a deviner)",
      pc.lire_regles(tmp / "rien.json") is None)
(tmp / "casse.json").write_text("{pas du json", encoding="utf-8")
check("JSON casse = None, pas d'exception", pc.lire_regles(tmp / "casse.json") is None)
(tmp / "vide.json").write_text("{}", encoding="utf-8")
check("vide = None", pc.lire_regles(tmp / "vide.json") is None)
(tmp / "v2.json").write_text(json.dumps({
    "version": 2, "base": "A", "colonnes": {"PY": "B"},
    "exceptions": [{"source": "C", "kpis": ["D"], "variations": ["YoY %"]},
                   {"source": pc.CHACUN, "kpis": ["E"]},
                   {"kpis": ["F"]}]}), encoding="utf-8")
r = pc.lire_regles(tmp / "v2.json")
check("le format actuel est lu", r["base"] == "A" and r["colonnes"] == {"PY": "B"})
check("… une exception sans source est laissee de cote", len(r["exceptions"]) == 2)
(tmp / "ancien.json").write_text(json.dumps({"groupes": [
    {"nom": "g1", "gabarit": "A", "kpis": []},
    {"nom": "g2", "gabarit": "C", "kpis": ["C", "D"]}]}), encoding="utf-8")
r = pc.lire_regles(tmp / "ancien.json")
check("l'ancien format : le groupe par defaut devient la base", r["base"] == "A")
check("… un groupe reste un GROUPE, avec son gabarit — INDEPENDANT, comme "
      "avant : il ne recoit rien de la base",
      r["groupes"] == [{"nom": "g2", "kpis": ["C", "D"], "base": "C",
                        "colonnes": {}, "independant": True}]
      and r["exceptions"] == [])
g = pc.Sources.depuis_regles(pc.regles_depuis_groupes([
    {"nom": "g1", "gabarit": "A", "kpis": []},
    {"nom": "seul", "gabarit": "C", "kpis": ["C"]}]), ["A", "C"], ["Réel"])
g.menage()
check("… et un groupe d'UN seul KPI garde son formatage : c'est son gabarit",
      g.source("C", "Réel") == "C" and g.gabarit("C", "Réel"))
(tmp / "manuel.json").write_text(json.dumps({"version": 2, "base": "A",
    "exceptions": [{"source": "(chacun le sien)", "kpis": ["B"],
                    "variations": ["PY"]}]}), encoding="utf-8")
check("l'ancien mot « (chacun le sien) » se lit « à la main »",
      pc.lire_regles(tmp / "manuel.json")["exceptions"][0]["source"]
      == pc.MANUEL)
check("… et les passes gardent l'ordre des groupes", r["ordre"] == ["A", "C"])
check("… meme quand le groupe par defaut est le DERNIER (resultat identique "
      "au caractere a l'ancien moteur)",
      pc.Sources.depuis_regles(pc.regles_depuis_groupes([
          {"nom": "g", "gabarit": "C", "kpis": ["C", "D"]},
          {"nom": "d", "gabarit": "A", "kpis": []}]),
          ["A", "B", "C", "D", "E"]).sources() == ["C", "A"])
rmtree(tmp)

CONNUS = ["A", "B", "C", "D", "E"]
V3 = ["Réel", "PY", "YoY %"]
g = pc.Sources.depuis_regles({"base": "A", "exceptions": [
    {"source": "C", "kpis": ["D"], "variations": ["YoY %"]}]}, CONNUS, V3)
check("la source d'une exception GARDE sa variation, d'office",
      g.source("C", "YoY %") == "C")
check("… et la donne a ses copieurs", g.source("D", "YoY %") == "C")
check("… sans rien changer ailleurs : la base pour le reste, source comprise",
      g.source("D", "PY") == "A" and g.source("C", "PY") == "A")
g = pc.Sources.depuis_regles({"base": "A", "exceptions": [
    {"source": "C", "kpis": ["D", "ZZZ"], "variations": ["PY"]}]}, CONNUS, V3)
check("un KPI absent du modele est signale et ignore",
      any("ZZZ" in a for a in g.problemes()[1]) and not g.problemes()[0])
g = pc.Sources.depuis_regles({"exceptions": [
    {"source": "C", "kpis": ["C", "D"]}]}, CONNUS, V3)
check("sans base, les KPI sans regle sont signales non propages",
      any("non propagé" in a and "A" in a for a in g.problemes()[1]))
check("… et ne sont la source d'aucune passe", g.sources() == ["C"])

# ===================================================================== 3
print("3. les refus : on ne devine pas")


def erreurs_de(regles):
    return pc.Sources.depuis_regles(regles, CONNUS, V3).problemes()[0]


check("une source inconnue", any("introuvable" in e for e in erreurs_de(
    {"base": "A", "exceptions": [{"source": "ZZZ", "kpis": ["B"],
                                  "variations": ["PY"]}]})))
check("une base inconnue", any("base introuvable" in e
                               for e in erreurs_de({"base": "ZZZ"})))
check("une case a deux sources", any("deux sources" in e for e in erreurs_de(
    {"base": "A", "exceptions": [
        {"source": "B", "kpis": ["D"], "variations": ["PY"]},
        {"source": "C", "kpis": ["D"], "variations": ["PY"]}]})))
check("la base qui copie un autre KPI, alors que sa colonne la suit",
      any("gabarit de base" in e for e in erreurs_de(
          {"base": "A", "exceptions": [{"source": "B", "kpis": ["A"],
                                        "variations": ["PY"]}]})))
check("une copie de copie", any("copie de copie" in e for e in erreurs_de(
    {"base": "A", "colonnes": {"PY": "B"},
     "exceptions": [{"source": "C", "kpis": ["B"], "variations": ["PY"]}]})))
check("un KPI dans deux groupes", any("deux groupes" in e for e in erreurs_de(
    {"base": "A", "groupes": [{"nom": "G1", "kpis": ["B", "C"]},
                              {"nom": "G2", "kpis": ["C", "D"]}]})))
check("le gabarit de base dans un groupe", any("ne peut pas être dans un groupe"
      in e for e in erreurs_de({"base": "A", "groupes": [
          {"nom": "G", "kpis": ["A", "B"], "base": "B"}]})))
check("un gabarit de groupe inconnu", any("introuvable" in e for e in erreurs_de(
    {"base": "A", "groupes": [{"nom": "G", "kpis": ["B"], "base": "ZZZ"}]})))

c = copie("refus")
R = c / (PROJ + ".Report")
avant = etat(R)
pc.ecrire_regles(c / "propagation.json", {"base": BASE, "exceptions": [
    {"source": WEIGHT, "kpis": [BASE], "variations": ["PY"]}]})
try:
    propager(R)
    check("des regles fautives sont refusees", False)
except SystemExit as e:
    check("des regles fautives : refus AVANT d'ecrire, message qui explique",
          "gabarit de base" in str(e) and "rien n'a été écrit" in str(e))
check("… le rapport n'a pas bouge d'un octet", etat(R) == avant)
check("… et aucune sauvegarde n'a ete creee",
      br.sessions_of(br.backup_root(c, "_propagate_backups")) == [])
(c / "propagation.json").unlink()
try:
    propager(R)
    check("sans fichier, pas de propagation", False)
except SystemExit as e:
    check("sans fichier, pas de propagation — et on dit quoi faire",
          "propagation.json" in str(e) and "gabarit de base" in str(e))
rmtree(c)

# ===================================================================== 4
print("4. la priorite : case > groupe (variation) > tous > ligne > gabarit "
      "du groupe > base")
g = pc.Sources.depuis_regles({
    "base": "A",
    "colonnes": {"PY": "B", "YoY %": "A"},
    "groupes": [{"nom": "G", "kpis": ["C", "D"], "base": "C",
                 "colonnes": {"YoY %": "E"}}],
    "exceptions": [{"source": "A", "kpis": ["D"], "variations": ["YoY %"]},
                   {"source": "C", "kpis": ["E"]}]},
    CONNUS, V3)
check("aucune erreur", not g.problemes()[0])
check("la base, par defaut", g.source("B", "Réel") == "A"
      and g.niveau("B", "Réel")[0] == "base")
check("le gabarit du groupe l'emporte sur la base",
      g.source("D", "Réel") == "C" and g.niveau("D", "Réel")[0] == "gabarit_groupe")
check("une ligne (toutes variations) l'emporte sur la base",
      g.source("E", "Réel") == "C" and g.niveau("E", "Réel")[0] == "ligne")
check("« Tous les KPI » l'emporte sur une ligne",
      g.source("E", "PY") == "B" and g.niveau("E", "PY")[0] == "tous")
check("« Tous les KPI » passe SOUS le gabarit du groupe : ses KPI copient "
      "leur gabarit, qui recoit d'abord le PY de B — le PY de tout le monde "
      "se regle toujours une fois", g.source("D", "PY") == "C"
      and g.niveau("D", "PY")[0] == "gabarit_groupe"
      and g.source("C", "PY") == "C" and g.sous_couche("C", "PY") == "B")
check("… et la base passe sous lui pour le reste — sous LUI seul",
      g.sous_couche("C", "Réel") == "A" and g.sous_couche("D", "Réel") is None)
check("… rien sous le gabarit la ou le groupe a sa regle pour la variation",
      g.sous_couche("C", "YoY %") is None)
check("les passes par-dessous : A sous C, B sous C",
      g.couches() == {"A": ["C"], "B": ["C"]})
gi = pc.Sources.depuis_regles({
    "base": "A", "colonnes": {"PY": "B"},
    "groupes": [{"nom": "G", "kpis": ["C", "D"], "base": "C",
                 "independant": True}]}, CONNUS, V3)
check("un groupe INDEPENDANT : « Tous les KPI » passe avant son gabarit, et "
      "rien ne passe dessous", gi.source("C", "PY") == "B"
      and gi.source("D", "PY") == "B" and gi.source("D", "Réel") == "C"
      and gi.sous_couche("C", "Réel") is None and not gi.couches())
check("« Tous les KPI » a la main reste a la main pour tous, groupes compris",
      pc.Sources.depuis_regles({"base": "A", "colonnes": {"PY": pc.MANUEL},
                                "groupes": [{"nom": "G", "kpis": ["C", "D"],
                                             "base": "C"}]}, CONNUS, V3
                               ).source("D", "PY") == "D")
check("le groupe, pour une variation, l'emporte sur « Tous les KPI »",
      g.source("C", "YoY %") == "E" and g.niveau("C", "YoY %")[0] == "groupe")
check("la case l'emporte sur le groupe",
      g.source("D", "YoY %") == "A" and g.niveau("D", "YoY %")[0] == "case")
check("la source d'un gabarit par variation garde cette variation, d'office",
      g.source("E", "YoY %") == "E")

# ===================================================================== 5
print("5. la BASE couvre tout le monde, sauf les exceptions")
c = copie("base")
R = c / (PROJ + ".Report")
V1, CLE = ou_poser(R, BASE)
check("un visuel porte des entrees de la base", V1 is not None)
poser(V1, CLE,
      entree(BASE, "bReel"), entree(BASE + " PY", "bPY"),
      entree(BASE + " YoY %", "bYoY"),
      entree(WEIGHT + " YoY %", "wYoY"), entree(WEIGHT + " PY", "wPY"),
      entree(SLEEP, "dReel"), entree(SLEEP + " PY", "dPY"),
      entree(FAT + " YoY %", "cYoY"))
avant = etat(R)
REGLES = {"base": BASE, "exceptions": [
    {"source": WEIGHT, "kpis": [FAT], "variations": ["YoY %"]},
    {"source": pc.CHACUN, "kpis": [SLEEP], "variations": ["Réel"]}]}
journal: list = []
n1 = propager(R, REGLES, log=journal.append)
check(f"la propagation ecrit ({n1} entree(s))", n1 > 0)
check("le PY de la base est chez TOUS les KPI — sources d'exceptions comprises",
      {ENT + "." + k + " PY" for k in KPIS} <= porteurs(R, "bPY"))
check("… le PY propre de Weight et de Sleep a cede la place",
      not porteurs(R, "wPY") and not porteurs(R, "dPY"))
check("YoY % : Body Fat % copie Weight, qui garde le sien",
      {ENT + "." + FAT + " YoY %", ENT + "." + WEIGHT + " YoY %"}
      <= porteurs(R, "wYoY"))
check("… plus rien du YoY % de la base chez eux, ni de l'ancien",
      not ({ENT + "." + FAT + " YoY %", ENT + "." + WEIGHT + " YoY %"}
           & porteurs(R, "bYoY")) and not porteurs(R, "cYoY"))
check("… les autres ont le YoY % de la base, et pas celui de Weight",
      {ENT + "." + k + " YoY %" for k in (BASE, SLEEP, TOTAL)}
      <= porteurs(R, "bYoY")
      and not ({ENT + "." + k + " YoY %" for k in (BASE, SLEEP, TOTAL)}
               & porteurs(R, "wYoY")))
check("Sleep garde son Reel (a la main), et sa face YTD le suit",
      {ENT + "." + SLEEP, ENT + "." + SLEEP + " YTD"} <= porteurs(R, "dReel")
      and ENT + "." + SLEEP not in porteurs(R, "bReel"))
check("… les autres ont le Reel de la base",
      {ENT + "." + k for k in (BASE, FAT, TOTAL, WEIGHT)} <= porteurs(R, "bReel"))
check("le journal dit le plan, regle par regle",
      any(l.strip() == f"{WEIGHT} → YoY % : {FAT}" for l in journal)
      and any(l.strip() == f"Réel à la main : {SLEEP}" for l in journal))
check("… et nomme chaque passe par sa source",
      any(f"--- source « {BASE} » (base)" in l for l in journal)
      and any(f"--- source « {WEIGHT} »" in l for l in journal))

print("   8. idempotence, et une seule sauvegarde qui defait tout")
apres1 = etat(R)
n2 = propager(R, REGLES)
check(f"2e passe = 0 changement (obtenu {n2})", n2 == 0)
check("… fichiers identiques au caractere", etat(R) == apres1)
sessions = br.sessions_of(br.backup_root(c, "_propagate_backups"))
check(f"UNE session de sauvegarde pour toutes les sources (obtenu {len(sessions)})",
      len(sessions) == 1)
info = br.session_info(sessions[0], c)
check("… son resume nomme les sources", BASE in info["resume"]
      and WEIGHT in info["resume"])
br.restore_session(sessions[0], c)
check("… la restaurer remet le rapport d'avant, toutes sources confondues",
      etat(R) == avant)
rmtree(c)

# ===================================================================== 6
print("6. a la main, et une variation pour tous venue d'ailleurs")
for nom, regles, attendu in (
        ("colonne", {"base": BASE, "colonnes": {"YoY %": WEIGHT}}, "Weight"),
        ("chacun", {"base": BASE, "colonnes": {"YoY %": pc.CHACUN}}, "chacun")):
    c = copie(nom)
    R = c / (PROJ + ".Report")
    V1, CLE = ou_poser(R, BASE)
    poser(V1, CLE, entree(BASE + " YoY %", "bYoY"),
          entree(WEIGHT + " YoY %", "wYoY"), entree(FAT + " YoY %", "cYoY"))
    propager(R, regles)
    tous = {ENT + "." + k + " YoY %" for k in KPIS}
    if attendu == "Weight":
        check("toute la colonne vient de Weight — la base comprise",
              tous <= porteurs(R, "wYoY"))
        check("… le YoY % de la base et l'ancien ont disparu",
              not porteurs(R, "bYoY") and not porteurs(R, "cYoY"))
    else:
        check("« Tous les KPI » a la main : chacun garde le sien, rien ne passe",
              ENT + "." + BASE + " YoY %" in porteurs(R, "bYoY")
              and ENT + "." + WEIGHT + " YoY %" in porteurs(R, "wYoY")
              and ENT + "." + FAT + " YoY %" in porteurs(R, "cYoY")
              and not (porteurs(R, "bYoY") & {ENT + "." + k + " YoY %"
                                              for k in KPIS if k != BASE}))
    rmtree(c)

# ===================================================================== 7
print("7. l'ordre des passes ne compte pas")
# Le piege : Weight, source d'une exception YoY %, n'a AUCUNE entree dans un
# second visuel ; la base, elle, y en a. La passe de base y pose donc des
# entrees de Weight (son Reel, son PY : des cases de la base). Si « pilote »
# se jugeait sur TOUTES les entrees de Weight, sa passe nettoierait ce visuel
# ou non selon qu'elle passe apres la base ou avant — deux resultats pour
# une meme grille.
etats = {}
for nom, ordre in (("base_dabord", [BASE, WEIGHT]), ("source_dabord", [WEIGHT, BASE])):
    c = copie(nom)
    R = c / (PROJ + ".Report")
    V1, CLE = ou_poser(R, BASE)
    V2, CLE2 = ou_poser(R, BASE, sauf=(V1,))
    data = lire(V2)
    for cle, liste in data["visual"]["objects"].items():
        if isinstance(liste, list):
            liste[:] = [e for e in liste if not (pc.entry_metadata(e) or "")
                        .startswith(ENT + "." + WEIGHT)]
    ecrire(V2, data)
    poser(V1, CLE, entree(WEIGHT + " YoY %", "wYoY"))
    poser(V2, CLE2, entree(BASE + " PY", "bPY2"), entree(FAT + " YoY %", "cYoY2"))
    regles = {"base": BASE, "ordre": ordre, "exceptions": [
        {"source": WEIGHT, "kpis": [FAT], "variations": ["YoY %"]}]}
    propager(R, regles)
    check(f"[{nom}] Weight ne pilote pas le 2e visuel : le YoY % de Body Fat % "
          "y reste", ENT + "." + FAT + " YoY %" in porteurs(R, "cYoY2", V2))
    check(f"[{nom}] … alors que la base y a bien pose le PY de Weight",
          ENT + "." + WEIGHT + " PY" in porteurs(R, "bPY2", V2))
    n2 = propager(R, regles)
    check(f"[{nom}] 2e passe = 0 changement (obtenu {n2})", n2 == 0)
    etats[nom] = etat(R)
    rmtree(c)
check("les deux ordres donnent le MEME rapport, au caractere",
      etats["base_dabord"] == etats["source_dabord"])

# ===================================================================== 9
print("9. les pertes annoncees, avant d'ecrire")
c = copie("pertes")
R = c / (PROJ + ".Report")
# le graphique en ligne : la base y trace son Reel (sa case propre, donc elle
# pilote le visuel) ; on lui retire son PY -> les PY des autres, qui la
# copient, n'ont plus de source dans ce visuel
cible_vj = None
for vj in visuels(R):
    if (lire(vj).get("visual") or {}).get("visualType") == "lineChart":
        cible_vj = vj
        break
check("le rapport a un graphique en ligne", cible_vj is not None)
analyse0 = pc.analyser(R, field_parameter=FP, branches=["YTD"],
                       variations=VARIATIONS)
cl0 = analyse0["classer"]
tries = sorted(KPIS, key=len, reverse=True)


def entrees_py(vj, qui):
    out = []
    objets = (lire(vj).get("visual") or {}).get("objects") or {}
    for cle, liste in objets.items():
        for e in liste if isinstance(liste, list) else []:
            md = pc.entry_metadata(e)
            k = pc.kpi_de(md, tries, ENT)
            if (k and qui(k) and not pc.owned_by_color_matrix(cle, e)
                    and cl0(md, k) == "PY"):
                out.append(md)
    return out


data = lire(cible_vj)
for liste in data["visual"]["objects"].values():
    if isinstance(liste, list):
        liste[:] = [e for e in liste
                    if not (pc.kpi_de(pc.entry_metadata(e), tries, ENT) == BASE
                            and cl0(pc.entry_metadata(e), BASE) == "PY")]
ecrire(cible_vj, data)
condamnees = entrees_py(cible_vj, lambda k: k != BASE)
check(f"les autres KPI y ont du PY ({len(condamnees)} entree(s))", condamnees)
regles = {"base": BASE}
analyse = pc.analyser(R, field_parameter=FP, branches=["YTD"], variations=VARIATIONS)
grille = pc.Sources.depuis_regles(regles, KPIS, analyse["variations"])
prevus = pc.retraits_prevus(analyse, grille)
check("la perte est annoncee, case par case",
      prevus and all(v == "PY" and s == BASE for _k, v, s, _n in prevus))
check("… au compte exact des entrees", sum(n for *_x, n in prevus) == len(condamnees))
journal = []
propager(R, regles, log=journal.append)
debut_passes = next(i for i, l in enumerate(journal) if l.startswith("--- source"))
check("… dans le journal, AVANT la premiere passe",
      any("retiré" in l and "PY" in l for l in journal[:debut_passes]))
check("… et c'est bien ce qui arrive", not entrees_py(cible_vj, lambda k: k != BASE))
rmtree(c)

# ===================================================================== 10
print("10. l'edition de la grille (ce que fait la fenetre)")
g = pc.Sources(CONNUS, V3, base="A")
notes = g.appliquer([("B", "PY")], "C")
check("une case prend C : C devient la source de PY (sa propre case)",
      g.source("B", "PY") == "C" and g.source("C", "PY") == "C"
      and not g.problemes()[0])
notes = g.appliquer([("C", "PY")], None)
check("C revient a sa colonne : ceux qui le copiaient suivent (la base)",
      g.source("B", "PY") == "A" and any("copie maintenant « A »" in n
                                         for n in notes))
check("… et rien d'inutile ne reste ecrit", g.cases == {} and g.colonnes == {})
notes = g.appliquer([("A", "PY")], "B")
check("la case de la BASE prend B : ceux qui la suivaient suivent",
      g.colonnes == {"PY": "B"} and all(g.source(k, "PY") == "B" for k in CONNUS)
      and any("copie maintenant « B »" in n for n in notes))
g.appliquer([(None, "PY")], None)
check("la ligne « toute la colonne » revient a la base",
      g.colonnes == {} and all(g.source(k, "PY") == "A" for k in CONNUS))
g.appliquer([("D", "Réel")], pc.CHACUN)
check("a la main : la case garde son formatage", g.source("D", "Réel") == "D")
g.appliquer([("E", "YoY %"), ("B", "YoY %")], "C")
regles = g.vers_regles()
check("ecriture en RECTANGLES ; la source n'y figure pas, elle est comprise",
      {"source": "C", "kpis": ["B", "E"], "variations": ["YoY %"]}
      in regles["exceptions"]
      and {"source": pc.CHACUN, "kpis": ["D"], "variations": ["Réel"]}
      in regles["exceptions"]
      and not any("C" in x["kpis"] for x in regles["exceptions"]))
relu = pc.Sources.depuis_regles(json.loads(json.dumps(regles)), CONNUS, V3)
check("relire ce qu'on a ecrit donne la MEME grille",
      all(relu.source(k, v) == g.source(k, v) for k in CONNUS for v in V3))
g.appliquer([("B", "YoY %"), ("E", "YoY %")], None)
check("le DERNIER copieur parti, la source revient a sa colonne",
      g.source("C", "YoY %") == "A" and ("C", "YoY %") not in g.cases)
relu.appliquer([("C", "YoY %")], pc.MANUEL)          # voulu
relu.appliquer([("B", "YoY %"), ("E", "YoY %")], None)
check("… mais un « a la main » VOULU survit a ses copieurs",
      relu.source("C", "YoY %") == "C")
check("… y compris ecrit puis relu",
      pc.Sources.depuis_regles(relu.vers_regles(), CONNUS, V3)
      .source("C", "YoY %") == "C")

g2 = pc.Sources.depuis_regles({"base": "A", "exceptions": [
    {"source": "C", "kpis": ["C", "D"]}]}, CONNUS, V3)
g2.appliquer([("D", "PY")], None)
check("une LIGNE se deplie quand on change une de ses cases",
      "D" not in g2.lignes and g2.source("D", "PY") == "A"
      and g2.source("D", "Réel") == "C" and g2.source("D", "YoY %") == "C")
check("… et l'original de la ligne reste une ligne",
      g2.lignes.get("C") == pc.CHACUN)

g4 = pc.Sources.depuis_regles(pc.regles_depuis_groupes([
    {"nom": "d", "gabarit": "A", "kpis": []},
    {"nom": "g", "gabarit": "C", "kpis": ["C", "D"]}]), CONNUS, V3)
g4.appliquer([("D", v) for v in V3], None)
check("« retirer la regle » sur un membre : il suit son groupe",
      all(g4.source("D", v) == "C" for v in V3))
g4.appliquer([(None, "PY")], "A")
check("… et « Tous les KPI » PY = la base : le groupe entier suit",
      g4.source("D", "PY") == "A" and g4.source("C", "PY") == "A")

g3 = pc.Sources.depuis_regles({"base": "A", "exceptions": [
    {"source": "C", "kpis": ["B"], "variations": ["PY"]}]}, CONNUS, V3)
notes = g3.changer_base("B")
check("changer de base : la nouvelle base ne copie plus personne",
      g3.source("B", "PY") == "B"
      and any("devient le gabarit de base" in n for n in notes))
check("… et la grille reste sans copie de copie", not g3.problemes()[0])
g3.appliquer([("C", "PY")], "E")
check("repeindre une source emmene ses copieurs",
      g3.source("C", "PY") == "E" and not g3.problemes()[0])

# ===================================================================== 11
print("11. les groupes : une famille qui copie son gabarit")
g = pc.Sources(CONNUS, V3, base="A")
g.creer_groupe("Fam", ["C", "D"])
check("un groupe neuf : son gabarit est le 1er de ses KPI, que les autres "
      "copient", g.groupes["Fam"]["base"] == "C" and g.source("D", "Réel") == "C"
      and g.gabarit("C", "Réel"))
check("… hors du groupe, rien ne change", g.source("B", "Réel") == "A"
      and g.source("E", "PY") == "A")
g.appliquer([(None, "PY")], "A")
check("« Tous les KPI » PY = la base : le groupe le prend PAR son gabarit, "
      "qui le recoit dessous", g.source("D", "PY") == "C"
      and g.source("C", "PY") == "C" and g.sous_couche("C", "PY") == "A")
check("… et la regle reste posee, meme si elle ressemble a la base",
      g.colonnes.get("PY") == "A")
g.appliquer([(("groupe", "Fam"), "YoY %")], "E")
check("un gabarit par variation pour le groupe, pris hors du groupe",
      g.source("C", "YoY %") == "E" and g.source("D", "YoY %") == "E")
check("… sa source le garde (elle le donne)", g.source("E", "YoY %") == "E"
      and not g.problemes()[0])
notes = g.appliquer([("A", "Réel")], "B")
check("la base copie son Reel ailleurs : ceux qui la suivaient suivent",
      g.source("E", "Réel") == "B" and any("copie maintenant « B »" in n
                                           for n in notes))
check("… et le groupe, qui suivait SON gabarit, n'a pas bouge",
      g.source("C", "Réel") == "C" and g.source("D", "Réel") == "C"
      and not g.problemes()[0])
gi = pc.Sources(CONNUS, V3, base="A")
gi.creer_groupe("Fam", ["C", "D"])
gi.rendre_independant("Fam")
gi.appliquer([("A", "Réel")], "B")
check("… un groupe INDEPENDANT, que « Tous les KPI » emporterait, est "
      "epingle a son gabarit", gi.source("C", "Réel") == "C"
      and gi.source("D", "Réel") == "C" and gi.source("E", "Réel") == "B"
      and not gi.problemes()[0])
g.mettre_dans("Fam", ["E"])
check("un KPI qui entre dans le groupe copie son gabarit",
      g.source("E", "Réel") == "C")
check("… sauf ce qu'il donne : il reste la source du YoY % du groupe",
      g.source("E", "YoY %") == "E" and g.source("D", "YoY %") == "E")
notes = g.sortir_du_groupe(["C"])
check("le gabarit quitte son groupe : le groupe n'a plus de gabarit, et on "
      "le dit", g.groupes["Fam"]["base"] is None
      and any("n'a plus de gabarit" in n for n in notes))
check("… ses KPI suivent alors les regles generales : le Reel de la base, "
      "qu'elle copie de B", g.source("D", "Réel") == "B"
      and g.source("C", "Réel") == "B" and not g.problemes()[0])
g.changer_gabarit_groupe("Fam", "D")
check("un nouveau gabarit de groupe : ce qu'aucune regle plus precise ne "
      "decide vient de lui", g.groupes["Fam"]["base"] == "D"
      and g.source("E", pc.AUTRE) == "D" and not g.problemes()[0])
g.renommer_groupe("Fam", "Famille")
check("renommer un groupe garde tout", "Famille" in g.groupes
      and "Fam" not in g.groupes and g.groupe_de["D"] == "Famille")
notes = g.changer_base("D")
check("un KPI d'un groupe qui devient la base quitte son groupe",
      g.base == "D" and "D" not in g.groupe_de
      and any("quitte le groupe" in n for n in notes))
check("… sans copie de copie", not g.problemes()[0])
notes = g.supprimer_groupe("Famille")
check("supprimer le groupe : ses KPI suivent les regles generales",
      not g.groupes and not g.groupe_de and not g.problemes()[0])
relu = pc.Sources.depuis_regles(json.loads(json.dumps(g.vers_regles())),
                                CONNUS, V3)
check("relire ce qu'on a ecrit donne la meme grille",
      all(relu.source(k, v) == g.source(k, v) for k in CONNUS for v in V3))
g6 = pc.Sources(CONNUS, V3, base="A")
g6.appliquer([(None, "PY")], "A")
check("une regle « Tous les KPI » egale a la base, posee AVANT tout groupe, "
      "reste posee", g6.colonnes.get("PY") == "A")
g6.creer_groupe("Tard", ["C", "D"])
check("… et tient quand un groupe apparait : le PY de la base passe sous "
      "le gabarit du groupe, que ses KPI copient", g6.colonnes.get("PY") == "A"
      and g6.source("D", "PY") == "C" and g6.sous_couche("C", "PY") == "A"
      and g6.source("D", "Réel") == "C")
g8 = pc.Sources(CONNUS, V3, base="A")
g8.appliquer([(None, "PY")], "B")
g8.creer_groupe("Fam", ["C", "D"])
check("un groupe neuf se pose PAR-DESSUS la base",
      not g8.groupes["Fam"]["independant"] and g8.sous_couche("C", "Réel") == "A"
      and g8.sous_couche("C", "PY") == "B" and g8.source("D", "PY") == "C")
notes = g8.rendre_independant("Fam")
check("rendu independant : son gabarit ne recoit plus rien, et « Tous les "
      "KPI » passe avant lui", g8.sous_couche("C", "Réel") is None
      and g8.source("D", "PY") == "B" and g8.source("D", "Réel") == "C"
      and any("indépendant" in n for n in notes) and not g8.problemes()[0])
relu = pc.Sources.depuis_regles(json.loads(json.dumps(g8.vers_regles())),
                                CONNUS, V3)
check("… ca s'ecrit, et ca se relit", relu.groupes["Fam"]["independant"]
      and relu.source("D", "PY") == "B")
g8.rendre_independant("Fam", False)
check("… et ca se defait", g8.sous_couche("C", "Réel") == "A"
      and g8.source("D", "PY") == "C" and not g8.problemes()[0]
      and "independant" not in json.dumps(g8.vers_regles()))
g7 = pc.Sources.depuis_regles({"base": "A", "groupes": [
    {"nom": "G", "kpis": ["D"], "base": "C"}]}, CONNUS, V3)
check("le gabarit d'un groupe en est membre, meme absent de sa liste",
      g7.groupe_de.get("C") == "G" and g7.source("D", "Réel") == "C"
      and not g7.problemes()[0])
g5 = pc.Sources(CONNUS, V3, base="A")
check("on ne met pas le gabarit de base dans un groupe",
      any("gabarit de base" in n for n in g5.creer_groupe("X", ["A", "B"]))
      and g5.groupe_de == {"B": "X"})
check("… et deux groupes ne portent pas le meme nom",
      any("déjà" in n for n in g5.creer_groupe("X", ["C"])))

# ===================================================================== 12
print("12. un groupe propage entre ses KPI, dans le rapport")
c = copie("groupe")
R = c / (PROJ + ".Report")
V1, CLE = ou_poser(R, BASE)
poser(V1, CLE, entree(BASE + " PY", "bPY"), entree(BASE + " YoY %", "bYoY"),
      entree(SLEEP + " YoY %", "sYoY"), entree(SLEEP + " PY", "sPY"),
      entree(FAT + " YoY %", "fYoY"))
REGLES = {"base": BASE, "colonnes": {"PY": BASE},
          "groupes": [{"nom": "Sommeil", "kpis": [SLEEP, FAT], "base": SLEEP}]}
journal = []
propager(R, REGLES, log=journal.append)
check("le gabarit du groupe donne a ses membres, et remplace leur ancien",
      ENT + "." + FAT + " YoY %" in porteurs(R, "sYoY")
      and not porteurs(R, "fYoY"))
check("… a eux seuls", not ({ENT + "." + k + " YoY %" for k in
                             (BASE, TOTAL, WEIGHT)} & porteurs(R, "sYoY")))
check("les autres ont le YoY % de la base",
      {ENT + "." + k + " YoY %" for k in (TOTAL, WEIGHT)} <= porteurs(R, "bYoY"))
check("… et le groupe AUSSI, sous le sien : la base passe sous son gabarit",
      {ENT + "." + k + " YoY %" for k in (SLEEP, FAT)} <= porteurs(R, "bYoY")
      and {ENT + "." + k + " YoY %" for k in (SLEEP, FAT)} <= porteurs(R, "sYoY"))
check("le PY « Tous les KPI » arrive a tout le monde — au groupe par son "
      "gabarit, qui garde le sien par-dessus",
      {ENT + "." + k + " PY" for k in KPIS} <= porteurs(R, "bPY")
      and {m for m in porteurs(R, "sPY") if " YTD " not in m}
      == {ENT + "." + k + " PY" for k in (SLEEP, FAT)})
check("le journal dit le groupe, son gabarit, et qu'il se pose par-dessus "
      "la base", any(l.strip().startswith(
          f"Groupe Sommeil ← {SLEEP}, par-dessus la base :") for l in journal))
n2 = propager(R, REGLES)
check(f"2e passe = 0 changement (obtenu {n2})", n2 == 0)
rmtree(c)

# ===================================================================== 13
print("13. les cibles : leurs variations ont leurs colonnes")
c = copie("cibles")
R = c / (PROJ + ".Report")
M2 = c / (PROJ + ".SemanticModel")
AVEC_CIBLE = (WEIGHT, FAT)                    # deux KPI sur cinq
ajouter_cibles(M2, AVEC_CIBLE, FP)
VAR_CIBLES = VARIATIONS + [("écart", "écart"), ("écart %", "écart %")]
a = pc.analyser(R, field_parameter=FP, branches=["YTD"], variations=VAR_CIBLES,
                cible_folders=["_cibles"])
col = a["variations"]
print("   colonnes :", col)
check("chaque cible a ses colonnes : « Cible », puis ses variations",
      col[-3:] == ["Cible", "Cible écart", "Cible écart %"])
check("… une variation reservee aux cibles n'a pas de colonne vide a son nom",
      "écart" not in col and "écart %" not in col)
check("un KPI qui a une cible a TOUTES ses variations — hors parametre de "
      "champ comprises", {(k, v) for k in AVEC_CIBLE
                          for v in ("Cible", "Cible écart", "Cible écart %")}
      <= a["mesures"])
check("… un KPI sans cible n'en a aucune (pas de mesure)",
      not any((k, v) in a["mesures"] for k in (BASE, SLEEP, TOTAL)
              for v in ("Cible", "Cible écart")))
cl = a["classer"]
check("la face YTD d'une variation de cible est cette variation",
      cl(ENT + "." + WEIGHT + " cible YTD écart", WEIGHT) == "Cible écart"
      and cl(ENT + "." + WEIGHT + " cible YTD", WEIGHT) == "Cible")
check("… et « écart % » n'est pas pris pour « écart » (le plus long d'abord)",
      cl(ENT + "." + WEIGHT + " cible écart %", WEIGHT) == "Cible écart %")
a2 = pc.analyser(R, field_parameter=FP, branches=["YTD"], variations=VAR_CIBLES)
check("sans dossier des cibles configure, le parametre de champ suffit a "
      "reconnaitre une cible", (WEIGHT, "Cible écart") in a2["mesures"]
      and "Cible écart" in a2["variations"])

V1, CLE = ou_poser(R, BASE)
poser(V1, CLE, entree(WEIGHT + " cible écart", "wCE"), entree(BASE, "bReel"))
REGLES = {"base": BASE, "colonnes": {"Cible": WEIGHT, "Cible écart": WEIGHT,
                                     "Cible écart %": WEIGHT}}
journal = []
pc.propagate_regles(R, REGLES, field_parameter=FP, variations=VAR_CIBLES,
                    branches=["YTD"], toutes_branches=["YTD"],
                    cible_folders=["_cibles"], log=journal.append)
check("la « Cible écart » de Weight descend sur l'autre KPI qui a une cible, "
      "branches comprises", porteurs(R, "wCE") == {
          ENT + "." + k + suffixe for k in AVEC_CIBLE
          for suffixe in (" cible écart", " cible YTD écart")})
check("… et sur aucun KPI sans cible",
      not any(ENT + "." + k in m for m in porteurs(R, "wCE")
              for k in (BASE, SLEEP, TOTAL)))
check("le Reel de la base, lui, va a tout le monde",
      {ENT + "." + k for k in KPIS} <= porteurs(R, "bReel"))
check("le journal nomme la colonne de la cible",
      any(l.strip() == f"{WEIGHT} → Cible, Cible écart, Cible écart % : "
          "tous les KPI" for l in journal))
rmtree(c)

# ===================================================================== 14
print("14. les cartes : une entree appartient a la variation qu'elle montre")
c = copie("cartes")
R = c / (PROJ + ".Report")
carte = next(vj for vj in visuels(R)
             if (lire(vj).get("visual") or {}).get("visualType") == "cardVisual")
a = pc.analyser(R, field_parameter=FP, branches=["YTD"], variations=VARIATIONS)
cl, tries = a["classer"], sorted(KPIS, key=len, reverse=True)
objets = lire(carte)["visual"]["objects"]
emp = pc.emplacements_de(objets, cl, tries, ENT)
PY_ID = next(i for i, v in emp.items() if v == "PY")
DELTA_ID = next(i for i, v in emp.items() if v == "Δ 30d")
check("chaque etiquette de reference de la carte a la variation de sa valeur",
      sorted(emp.values()) == ["PY", "Δ 30d"])


def variation_de(cle, ident=None, avec=None):
    for e in objets.get(cle) or []:
        sel = e.get("selector") or {}
        if sel.get("id") == ident and (avec is None or avec in e.get("properties", {})):
            return pc.variation_entree(e, WEIGHT, cl, emp, ENT, cle)


check("… son titre la suit (meme id) ; son DETAIL a sa colonne, a cote",
      variation_de("referenceLabelTitle", PY_ID) == "PY"
      and variation_de("referenceLabelDetail", PY_ID) == "PY — détail")
check("le reglage de la carte entiere (sans id) reste au Reel",
      variation_de("referenceLabelDetail", None) == "Réel")
check("l'image de la carte est de la variation qu'elle affiche (sparkline)",
      variation_de("cardImage", None, "imageData") == "sparkline")
check("la grille compte ainsi le formatage de la carte, variation par variation",
      {v for (k, v) in a["reglages"] if k == WEIGHT} >= {"PY", "Δ 30d", "sparkline"})

# Un cas réel : un gabarit de base qui porte toute la carte, et un
# gabarit par variation pour le PY. Avant, tout tombait au Reel : la base
# propageait tout, le gabarit du PY n'avait rien a donner.
propager(R, {"base": WEIGHT})                 # chaque KPI a la carte de Weight


def entrees(cle, ident, kpi):
    out = []
    for e in lire(carte)["visual"]["objects"].get(cle) or []:
        sel = e.get("selector") or {}
        if sel.get("id") == ident and pc.entry_metadata(e) == ENT + "." + kpi:
            out.append(e)
    return out


check("au depart, la carte de Weight est chez tous les KPI",
      all(entrees("referenceLabelTitle", PY_ID, k) for k in KPIS))
REF_SHOW = next(e["properties"]["show"] for e in
                entrees("referenceLabelDetail", DELTA_ID, WEIGHT)
                if "show" in e.get("properties", {}))
AUTRE_SHOW = {"expr": {"Literal": {"Value": "false" if "true" in
                                   json.dumps(REF_SHOW) else "true"}}}
data = lire(carte)
for cle, ident, prop, valeur in (
        ("referenceLabelTitle", PY_ID, "titleText",
         {"expr": {"Literal": {"Value": "'PY de BF'"}}}),
        ("referenceLabelDetail", DELTA_ID, "show", AUTRE_SHOW)):
    for e in data["visual"]["objects"][cle]:
        sel = e.get("selector") or {}
        if (sel.get("id") == ident and pc.entry_metadata(e) == ENT + "." + FAT
                and prop in e.get("properties", {})):
            e["properties"][prop] = valeur
ecrire(carte, data)
REGLES = {"base": WEIGHT, "colonnes": {"PY": FAT}}
n = propager(R, REGLES)
titres = {k: [e["properties"].get("titleText") for e in
              entrees("referenceLabelTitle", PY_ID, k)] for k in KPIS}
check("le gabarit du PY (Body Fat %) donne son etiquette PY a TOUS les KPI — "
      "le gabarit de base compris", n > 0 and all(
          any(t and "PY de BF" in json.dumps(t, ensure_ascii=False) for t in ts)
          for ts in titres.values()))
details = [e["properties"].get("show") for e in entrees("referenceLabelDetail",
                                                        DELTA_ID, FAT)
           if "show" in e.get("properties", {})]
check("… et le Δ 30d de Body Fat %, que rien ne lui donne, revient a la base",
      details and all(d == REF_SHOW for d in details))
n2 = propager(R, REGLES)
check(f"2e passe = 0 changement (obtenu {n2})", n2 == 0)
rmtree(c)

# ===================================================================== 15
print("15. par-dessus : la base passe sous le gabarit d'un groupe, propriete "
      "par propriete")


def entree_props(md, props):
    """Une entree a plusieurs proprietes (q…), valeurs litterales."""
    return {"properties": {p: {"expr": {"Literal": {"Value": v}}}
                           for p, v in props.items()},
            "selector": {"metadata": ENT + "." + md,
                         "data": [{"dataViewWildcard": {"matchingOption": 0}}]}}


def props_de(vj, md):
    """({propriete q…: valeur}, nombre d'entrees q…) de ce metadata."""
    out, n = {}, 0
    for liste in lire(vj)["visual"]["objects"].values():
        for e in liste if isinstance(liste, list) else []:
            props = e.get("properties") or {}
            if (pc.entry_metadata(e) == ENT + "." + md
                    and any(p.startswith("q") for p in props)):
                n += 1
                for p, v in props.items():
                    out[p] = v["expr"]["Literal"]["Value"]
    return out, n


def retoucher(vj, md, **props):
    """Change (valeur) ou retire (None) des proprietes q… de ce metadata —
    ce que l'usager ferait dans Desktop."""
    data = lire(vj)
    for liste in data["visual"]["objects"].values():
        for e in liste if isinstance(liste, list) else []:
            if pc.entry_metadata(e) == ENT + "." + md:
                for p, v in props.items():
                    if v is None:
                        (e.get("properties") or {}).pop(p, None)
                    elif p in (e.get("properties") or {}) or any(
                            q.startswith("q") for q in e.get("properties") or {}):
                        e["properties"][p] = {"expr": {"Literal": {"Value": v}}}
    ecrire(vj, data)


c = copie("dessus")
R = c / (PROJ + ".Report")
V1, CLE = ou_poser(R, BASE)
poser(V1, CLE, entree_props(BASE + " PY", {"qa": "'1'", "qb": "'2'"}),
      entree_props(SLEEP + " PY", {"qa": "'9'"}),
      entree_props(FAT + " PY", {"qz": "'0'"}),
      entree_props(BASE + " YoY %", {"qy": "'1'"}),
      entree_props(FAT + " YoY %", {"qx": "'2'"}))
REGLES = {"base": BASE, "groupes": [{"nom": "Sommeil", "kpis": [SLEEP, FAT],
                                     "base": SLEEP}]}
analyse = pc.analyser(R, field_parameter=FP, branches=["YTD"],
                      variations=VARIATIONS)
grille = pc.Sources.depuis_regles(REGLES, analyse["kpis"], analyse["variations"])
check("les pertes annoncees : rien pour le YoY % du groupe — son gabarit n'a "
      "rien, mais il recevra celui de la base",
      not [r for r in pc.retraits_prevus(analyse, grille)
           if r[0] == FAT and r[1] == "YoY %"])
journal = []
n = propager(R, REGLES, log=journal.append)
check("le gabarit garde le sien (qa) et recoit de la base ce qu'il n'a pas "
      "(qb) — en UNE entree", props_de(V1, SLEEP + " PY")
      == ({"qa": "'9'", "qb": "'2'"}, 1))
check("ses KPI copient le tout (et perdent leur ancien)",
      props_de(V1, FAT + " PY") == ({"qa": "'9'", "qb": "'2'"}, 1))
check("hors du groupe : la base, telle quelle",
      props_de(V1, TOTAL + " PY") == ({"qa": "'1'", "qb": "'2'"}, 1))
check("le YoY % du groupe : celui de la base, par son gabarit",
      props_de(V1, SLEEP + " YoY %") == ({"qy": "'1'"}, 1)
      and props_de(V1, FAT + " YoY %") == ({"qy": "'1'"}, 1))
check("les faces YTD du groupe suivent son Reel — une entree, pas deux",
      props_de(V1, SLEEP + " YTD PY") == ({"qa": "'9'", "qb": "'2'"}, 1)
      and props_de(V1, FAT + " YTD PY") == ({"qa": "'9'", "qb": "'2'"}, 1))
check("le journal dit la passe par-dessous",
      any("d'abord, sous le gabarit de groupe" in l and SLEEP in l
          for l in journal))
memo = pc.memoire_path(R)
texte_memo = memo.read_text(encoding="utf-8") if memo.exists() else ""
check("la memoire retient ce qu'on a pose (qb), pas ce qui est au gabarit "
      "(qa)", memo.exists() and '"qb"' in texte_memo
      and '"qa"' not in texte_memo and memo.parent.parent.name
      == br.PARENT)
n2 = propager(R, REGLES)
check(f"2e passe = 0 changement (obtenu {n2})", n2 == 0)

retoucher(V1, BASE + " PY", qb="'3'")
propager(R, REGLES)
check("la base change qb : le gabarit SUIT (on l'y avait pose), ses KPI aussi",
      props_de(V1, SLEEP + " PY")[0] == {"qa": "'9'", "qb": "'3'"}
      and props_de(V1, FAT + " PY")[0] == {"qa": "'9'", "qb": "'3'"}
      and props_de(V1, TOTAL + " PY")[0] == {"qa": "'1'", "qb": "'3'"})
retoucher(V1, SLEEP + " PY", qb="'7'")
propager(R, REGLES)
check("l'usager retouche qb sur le gabarit : la retouche est a lui, ses KPI "
      "la prennent", props_de(V1, SLEEP + " PY")[0] == {"qa": "'9'", "qb": "'7'"}
      and props_de(V1, FAT + " PY")[0] == {"qa": "'9'", "qb": "'7'"})
retoucher(V1, BASE + " PY", qb="'4'", qa="'6'")
propager(R, REGLES)
check("… et la base peut bien changer qb et qa : le gabarit garde les siens",
      props_de(V1, SLEEP + " PY")[0] == {"qa": "'9'", "qb": "'7'"}
      and props_de(V1, TOTAL + " PY")[0] == {"qa": "'6'", "qb": "'4'"})
retoucher(V1, BASE + " PY", qc="'5'")
propager(R, REGLES)
check("la base gagne qc : le gabarit et ses KPI le recoivent",
      props_de(V1, SLEEP + " PY")[0].get("qc") == "'5'"
      and props_de(V1, FAT + " PY")[0].get("qc") == "'5'")
retoucher(V1, BASE + " PY", qc=None)
memo_avant = memo.read_text(encoding="utf-8")
etat_avant = etat(R)
propager(R, REGLES, dry_run=True)
check("a blanc : ni rapport ni memoire ecrits", etat(R) == etat_avant
      and memo.read_text(encoding="utf-8") == memo_avant)
propager(R, REGLES)
check("la base perd qc : il s'en va du gabarit (on l'y avait pose), de ses "
      "KPI et des autres", "qc" not in props_de(V1, SLEEP + " PY")[0]
      and "qc" not in props_de(V1, FAT + " PY")[0]
      and "qc" not in props_de(V1, TOTAL + " PY")[0])
racine = br.backup_root(c, "_propagate_backups")
derniere = br.sessions_of(racine)[0]
br.restore_session(derniere, c)
check("restaurer la derniere sauvegarde remet le rapport ET la memoire",
      etat(R) == etat_avant and memo.read_text(encoding="utf-8") == memo_avant)
REGLES_T = {"base": BASE, "colonnes": {"PY": WEIGHT},
            "groupes": REGLES["groupes"]}
retoucher(V1, WEIGHT + " PY", qa="'1'", qb=None, qc=None, qw="'8'")
propager(R, REGLES_T)
check("le PY change de maitre (« Tous les KPI » = Weight) : ce qu'on avait "
      "pose depuis la base s'en va, le sien reste, Weight passe dessous",
      props_de(V1, SLEEP + " PY")[0] == {"qa": "'9'", "qb": "'7'", "qw": "'8'"}
      and props_de(V1, FAT + " PY")[0] == {"qa": "'9'", "qb": "'7'", "qw": "'8'"}
      and props_de(V1, TOTAL + " PY")[0] == {"qa": "'1'", "qw": "'8'"})
n2 = propager(R, REGLES_T)
check(f"2e passe = 0 changement (obtenu {n2})", n2 == 0)
rmtree(c)

c = copie("dessous_indep")
R = c / (PROJ + ".Report")
V1, CLE = ou_poser(R, BASE)
poser(V1, CLE, entree_props(BASE + " PY", {"qa": "'1'", "qb": "'2'"}),
      entree_props(SLEEP + " PY", {"qa": "'9'"}))
INDEP = {"base": BASE, "groupes": [{"nom": "Sommeil", "kpis": [SLEEP, FAT],
                                    "base": SLEEP, "independant": True}]}
propager(R, INDEP)
check("un groupe INDEPENDANT : son gabarit ne recoit rien de la base, ses "
      "KPI copient le sien seul", props_de(V1, SLEEP + " PY")[0] == {"qa": "'9'"}
      and props_de(V1, FAT + " PY")[0] == {"qa": "'9'"}
      and not pc.memoire_path(R).exists())
rmtree(c)

# ===================================================================== 16
print("16. une face de branche suit son Reel, meme quand il change")
c = copie("faces")
R = c / (PROJ + ".Report")
V1, CLE = ou_poser(R, BASE)
poser(V1, CLE, entree_props(BASE + " PY", {"qa": "'1'"}))
propager(R, {"base": BASE})
retoucher(V1, BASE + " PY", qb="'2'")
propager(R, {"base": BASE})
check("le Reel gagne une propriete : chaque face YTD a UNE entree, a jour "
      "(avant : l'ancienne restait a cote, et se propageait)",
      all(props_de(V1, k + " YTD PY") == ({"qa": "'1'", "qb": "'2'"}, 1)
          for k in KPIS))
retoucher(V1, BASE + " PY", qa=None)
propager(R, {"base": BASE})
check("… il en perd une : les faces la perdent aussi",
      all(props_de(V1, k + " YTD PY") == ({"qb": "'2'"}, 1) for k in KPIS))
n2 = propager(R, {"base": BASE})
check(f"2e passe = 0 changement (obtenu {n2})", n2 == 0)
rmtree(c)

# ===================================================================== 17
print("17. le detail d'une etiquette a sa colonne : il se regle a part")
c = copie("detail")
R = c / (PROJ + ".Report")
carte = next(vj for vj in visuels(R)
             if (lire(vj).get("visual") or {}).get("visualType") == "cardVisual")
propager(R, {"base": WEIGHT})                 # chaque KPI a la carte de Weight


def du_py(cle, kpi, prop):
    """L'entree `cle` de l'etiquette PY de ce KPI qui porte `prop`."""
    for e in lire(carte)["visual"]["objects"].get(cle) or []:
        if ((e.get("selector") or {}).get("id") == PY_ID
                and pc.entry_metadata(e) == ENT + "." + kpi
                and prop in (e.get("properties") or {})):
            return e


def detail_de(kpi):
    """La mesure que montre le detail de l'etiquette PY de ce KPI."""
    e = du_py("referenceLabelDetail", kpi, "detailValue")
    return pc._premiere_mesure(e["properties"]["detailValue"]) if e else None


def titre_de(kpi):
    e = du_py("referenceLabelTitle", kpi, "titleText")
    return e["properties"]["titleText"]["expr"]["Literal"]["Value"] if e else None


def retoucher_carte(kpi, titre=None, detail=None):
    """Ce que l'usager ferait dans Desktop : le titre de l'etiquette PY, la
    mesure de son detail (un ecart en valeur plutot qu'en %)."""
    data = lire(carte)
    objets = data["visual"]["objects"]
    for e in objets["referenceLabelTitle"]:
        if (titre and (e.get("selector") or {}).get("id") == PY_ID
                and pc.entry_metadata(e) == ENT + "." + kpi
                and "titleText" in e.get("properties", {})):
            e["properties"]["titleText"] = {"expr": {"Literal": {"Value": titre}}}
    for e in objets["referenceLabelDetail"]:
        if (detail and (e.get("selector") or {}).get("id") == PY_ID
                and pc.entry_metadata(e) == ENT + "." + kpi
                and "detailValue" in e.get("properties", {})):
            e["properties"]["detailValue"]["expr"]["Measure"]["Property"] = detail
    ecrire(carte, data)


check("au depart, le detail du PY montre le YoY % de chacun",
      detail_de(FAT) == FAT + " YoY %" and detail_de(TOTAL) == TOTAL + " YoY %")
retoucher_carte(FAT, titre="'PY de BF'", detail=FAT + " Δ 30d")
a = pc.analyser(R, field_parameter=FP, branches=["YTD"], variations=VARIATIONS)
check("la grille a une colonne « PY — détail », juste apres « PY »",
      "PY — détail" in a["variations"] and a["variations"].index("PY — détail")
      == a["variations"].index("PY") + 1)
check("… chaque KPI qui a le PY a son detail (pas « pas de mesure »)",
      all((k, "PY — détail") in a["mesures"] for k in KPIS))
g = pc.Sources.depuis_regles({"base": WEIGHT, "colonnes": {"PY": TOTAL}},
                             KPIS, a["variations"])
check("sans regle a lui, le detail suit son etiquette (ici, le PY de "
      "Total Steps)", all(g.source(k, "PY — détail") == g.source(k, "PY")
                          for k in KPIS)
      and g.source(FAT, "PY — détail") == TOTAL
      and g.suit_son_etiquette(FAT, "PY — détail")
      and not g.suit_son_etiquette(FAT, "PY") and not g.problemes()[0])

# l'etiquette du PY depuis Weight, mais chacun garde SON detail
REGLES = {"base": WEIGHT, "colonnes": {"PY": WEIGHT, "PY — détail": pc.MANUEL}}
propager(R, REGLES)
check("l'etiquette se propage (le titre de Weight chez Body Fat %)…",
      titre_de(FAT) == titre_de(WEIGHT) and titre_de(FAT) != "'PY de BF'")
check("… sans emporter le detail : Body Fat % garde son Δ 30d",
      detail_de(FAT) == FAT + " Δ 30d" and detail_de(TOTAL) == TOTAL + " YoY %")
n2 = propager(R, REGLES)
check(f"2e passe = 0 changement (obtenu {n2})", n2 == 0)

# l'inverse : l'etiquette a la main, le detail depuis Body Fat %
retoucher_carte(FAT, titre="'PY de BF'")
REGLES = {"base": WEIGHT, "colonnes": {"PY — détail": FAT},
          "exceptions": [{"source": pc.MANUEL, "kpis": [FAT],
                          "variations": ["PY"]}]}
g = pc.Sources.depuis_regles(REGLES, KPIS, a["variations"])
check("une regle sur le detail ne touche pas l'etiquette",
      g.source(TOTAL, "PY") == WEIGHT and g.source(TOTAL, "PY — détail") == FAT
      and g.source(FAT, "PY") == FAT and not g.problemes()[0])
propager(R, REGLES)
check("le detail se propage depuis Body Fat % (un Δ 30d chez tous)…",
      detail_de(TOTAL) == TOTAL + " Δ 30d" and detail_de(WEIGHT) == WEIGHT + " Δ 30d")
check("… et Body Fat % garde son etiquette, a la main",
      titre_de(FAT) == "'PY de BF'" and titre_de(TOTAL) == titre_de(WEIGHT))
n2 = propager(R, REGLES)
check(f"2e passe = 0 changement (obtenu {n2})", n2 == 0)
g.appliquer([(None, "PY")], TOTAL)
check("repeindre l'etiquette repare aussi son detail : aucune copie de copie",
      not g.problemes()[0])
rmtree(c)

print("\n" + ("TOUT OK" if _ok else "*** DES ECHECS ***"))
sys.exit(0 if _ok else 1)
