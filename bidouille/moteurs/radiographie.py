# -*- coding: utf-8 -*-
"""Radiographie d'un rapport : ses KPI, leurs variations, et ce que chaque
visuel affiche. Lecture seule.

Le but est de comprendre vite un rapport qu'on n'a pas fait. Rien ici ne
suppose que PBIdouille l'a généré : ni config, ni TD_Indicateurs, ni
annotation. Tout se déduit du DAX, des noms et des visual.json.

LES VISUELS
  Les champs se lisent dans la requête de chaque visuel, par leur LIAISON
  (field) et non par leur queryRef : Power BI garde le queryRef d'un champ
  renommé, qui passerait alors pour cassé. Un visuel affiche une mesure s'il
  la nomme, ou s'il nomme la colonne principale d'un PARAMÈTRE DE CHAMP qui
  la propose (NAMEOF) ; un segment sur ce paramètre la CHOISIT.

CE QUI FILTRE UN VISUEL
  Ses filtres (volet des filtres), ceux de sa page et du rapport, et les
  segments de sa page qui ont une sélection, sauf ceux dont l'interaction
  vers lui est coupée (visualInteractions NoFilter).

À QUOI MÈNE UNE MESURE
  Ses mesures de base, au bout de ses références (celles qui n'en
  référencent plus aucune), et les colonnes qu'elles lisent.

LES COLONNES
  Chaque colonne utilisée, et partout où elle sert : visuel, segment (avec
  sa sélection), filtre de visuel, de page ou de rapport (avec sa valeur),
  mesure qui la lit.

FAMILLES
  · par le DAX : une mesure qui RÉFÉRENCE une autre mesure dont le nom est
    CONTENU dans le sien en est une variation (« Weight YTD » utilise
    [Weight]). La base retenue est la plus longue, donc « Weight YTD 7d avg »
    descend de « Weight YTD », qui descend de « Weight » : la racine est le
    KPI, et le patron de la variation est son nom où la racine devient
    « … » (« … YTD 7d avg ») ;
  · par le nom : parmi les mesures restées seules, celles qui commencent par
    les mêmes mots (« Lean Mass (Current) », « Lean Mass Δ (1M) »). Moins sûr :
    aucune ne référence l'autre, d'où leur marque à part. Un premier mot
    générique (« Total », « Average »…) ne suffit pas à faire une famille.

BRIQUES
  Les mesures que d'autres mesures utilisent, hors de leur propre famille
  (« Weight MA1 », que cinq calculs reprennent). Souvent invisibles dans les
  visuels, et pourtant ce qu'il faut lire en premier.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_measures as gm                  # noqa: E402
import unused_measures as um                    # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import report_reader as rr            # noqa: E402

DAX, NOM = "dax", "nom"

# un premier mot qui, seul, ne dit rien d'un KPI : il en faut un second pour
# fonder une famille par le nom (« Total Sales » et « Total Cost » ne sont
# pas parentes)
GENERIQUES = {
    "total", "totals", "average", "avg", "moyenne", "moy", "nb", "nbre",
    "nombre", "count", "sum", "somme", "max", "min", "taux", "rate", "ratio",
    "pct", "%", "#", "cumul", "cumulative", "cumulé", "ytd", "mtd", "qtd",
    "py", "last", "first", "dernier", "dernière", "premier", "première",
    "calc", "measure", "mesure", "kpi", "new", "old", "test", "temp", "tmp",
    "the", "le", "la", "les", "de", "du", "des",
}

SEGMENTS = {"slicer", "advancedSlicerVisual", "listSlicer", "textSlicer"}

TYPES = {
    "cardVisual": "Carte", "card": "Carte", "multiRowCard": "Carte multiligne",
    "kpi": "KPI", "gauge": "Jauge",
    "lineChart": "Courbes", "areaChart": "Aires", "stackedAreaChart": "Aires empilées",
    "ribbonChart": "Ruban", "columnChart": "Histogramme",
    "clusteredColumnChart": "Histogramme groupé", "stackedColumnChart": "Histogramme empilé",
    "barChart": "Barres", "clusteredBarChart": "Barres groupées",
    "stackedBarChart": "Barres empilées", "lineClusteredColumnComboChart": "Courbes et histogramme",
    "lineStackedColumnComboChart": "Courbes et histogramme empilé",
    "pieChart": "Secteurs", "donutChart": "Anneau", "treemap": "Compartimentage",
    "waterfallChart": "Cascade", "funnel": "Entonnoir", "scatterChart": "Nuage de points",
    "tableEx": "Table", "pivotTable": "Matrice",
    "slicer": "Segment", "advancedSlicerVisual": "Segment", "listSlicer": "Segment",
    "textSlicer": "Segment", "map": "Carte géographique", "filledMap": "Carte choroplèthe",
    "image": "Image", "textbox": "Zone de texte", "shape": "Forme",
    "actionButton": "Bouton", "pageNavigator": "Navigation",
}

NAMEOF_RE = re.compile(r"nameof\(\s*(?:'(?:[^']|'')*'|[^\[\s()]*)\s*\[((?:[^\]]|\]\])+)\]\s*\)",
                       re.I)
AGREGAT_RE = re.compile(r"^(\w+)\((.+)\)$")
AGREGATS = {"sum": "Somme", "avg": "Moyenne", "average": "Moyenne", "min": "Min",
            "max": "Max", "count": "Nombre", "countnonnull": "Nombre",
            "distinctcount": "Nombre distinct", "median": "Médiane"}


CHAINE_RE = re.compile(r'"(?:[^"]|"")*"')
CROCHET_RE = re.compile(r"\[(?:[^\]]|\]\])*\]")
COMMENTAIRE_RE = re.compile(r"/\*.*?\*/|//[^\n]*|--[^\n]*", re.S)


def code_dax(dax: str) -> str:
    """Le DAX sans ses chaînes ni ses commentaires, crochets GARDÉS : une
    mesure citée dans un commentaire ou un libellé ne compte pas comme
    utilisée. (um.strip_dax_noise retire aussi les crochets : il cherche des
    tables, pas des mesures.) Les crochets sont mis de côté le temps de
    retirer les commentaires, pour qu'un nom comme [Taux -- net] survive."""
    gardes = []

    def garder(m):
        gardes.append(m.group(0))
        return f"\x00{len(gardes) - 1}\x00"

    s = CROCHET_RE.sub(garder, CHAINE_RE.sub(" ", dax or ""))
    s = COMMENTAIRE_RE.sub(" ", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: gardes[int(m.group(1))], s)


def type_visuel(t: str) -> str:
    return TYPES.get(t, t or "?")


def _mots(nom: str) -> list:
    return nom.split()


def _famille_dax(noms, uses) -> dict:
    """mesure -> sa base directe (la plus longue mesure qu'elle référence et
    dont le nom est contenu, en mots entiers, dans le sien)."""
    base_of = {}
    for m in noms:
        cands = [b for b in uses[m] if len(b) < len(m)
                 and re.search(r"(?:^|(?<=\W))" + re.escape(b) + r"(?=$|\W)", m)]
        if cands:
            base_of[m] = max(cands, key=lambda b: (len(b), b))
    return base_of


def _racine(m, base_of) -> str:
    vus = {m}
    while m in base_of and base_of[m] not in vus:
        m = base_of[m]
        vus.add(m)
    return m


def patron(nom: str, base: str, jeton: str = "…") -> str:
    """Le nom d'une variation, sa base remplacée par « … » : « Weight YTD
    7d avg » sous « Weight » donne « … YTD 7d avg »."""
    return re.sub(r"(?:^|(?<=\W))" + re.escape(base) + r"(?=$|\W)",
                  lambda _m: jeton, nom, count=1, flags=re.I)


def _tige_commune(membres) -> str:
    """Le plus long début en mots entiers commun à tous les membres (sans
    tenir compte de la casse), écrit avec la casse la plus fréquente parmi
    eux, la majuscule l'emportant à égalité : « lean mass avg » et « Lean
    Mass Δ (1M) » donnent « Lean Mass »."""
    listes = [_mots(m) for m in membres]
    n = 0
    while all(len(l) > n for l in listes) and len({l[n].lower() for l in listes}) == 1:
        n += 1
    formes = Counter(" ".join(l[:n]) for l in listes)
    return max(formes, key=lambda f: (formes[f], f[:1].isupper(), f))


def _familles_nom(restants) -> dict:
    """tige -> [mesures] pour les mesures qui partagent leurs premiers mots.
    Chaque mesure va à la PLUS COURTE tige qualifiée qu'elle partage avec une
    autre (« Lean Mass (Current) » et « Lean Mass Δ (1M) » ensemble, plutôt
    que la seconde sous « Lean Mass Δ »), puis la tige du groupe s'allonge
    jusqu'à tout ce que ses membres ont en commun."""
    def prefixes(nom):
        mots = _mots(nom)
        out = []
        for k in range(1, len(mots) + 1):
            if k == 1 and mots[0].lower() in GENERIQUES:
                continue
            tige = " ".join(mots[:k])
            if len(tige) >= 3:
                out.append(tige)
        return out

    compte = Counter()
    for m in restants:
        for t in {p.lower() for p in prefixes(m)}:
            compte[t] += 1
    groupes: dict = {}
    for m in sorted(restants, key=str.lower):
        tige = next((p for p in prefixes(m) if compte[p.lower()] >= 2), None)
        if tige:
            cle = tige.lower()
            groupes.setdefault(cle, {"tige": tige, "membres": []})["membres"].append(m)
    return {_tige_commune(g["membres"]): g["membres"]
            for g in groupes.values() if len(g["membres"]) >= 2}


def _parametres_de_champ(colinfo, noms) -> dict:
    """table -> {colonne: colonne principale, mesures: [proposées, dans l'ordre]}"""
    bas = {n.lower(): n for n in noms}
    out = {}
    for t, txt in colinfo["table_text"].items():
        if "parametermetadata" not in txt:
            continue
        mesures = []
        for ref in NAMEOF_RE.findall(txt):
            n = bas.get(ref.replace("]]", "]"))
            if n and n not in mesures:
                mesures.append(n)
        principale = next((c["name"] for (tt, _), c in colinfo["columns"].items()
                           if tt == t and (c.get("source_column") or "").lower() == "[value1]"),
                          t)
        out[t] = {"colonne": principale, "mesures": mesures}
    return out


def _champ(ref: str, noms, colonnes, fps) -> dict:
    """Un queryRef (« Table.Champ », ou « Sum(Table.Champ) ») décrit."""
    agr = None
    m = AGREGAT_RE.match(ref)
    if m and "." in m.group(2):
        agr, ref = m.group(1), m.group(2)
    ent, _, prop = ref.partition(".")
    if prop in noms and not agr:
        return {"genre": "mesure", "ref": ref, "table": ent, "nom": prop}
    if ent in fps and prop == fps[ent]["colonne"]:
        return {"genre": "parametre", "ref": ref, "table": ent, "nom": prop,
                "mesures": list(fps[ent]["mesures"])}
    # « connue » : la colonne existe dans le modèle. Sinon le champ est cassé
    # (mesure ou colonne renommée, supprimée) : le visuel s'affiche en erreur
    return {"genre": "colonne", "ref": ref, "table": ent, "nom": prop,
            "agregat": AGREGATS.get((agr or "").lower(), agr),
            "connue": (ent, prop) in colonnes or prop in noms}


# Fonctions d'agrégation d'une projection (QueryAggregateFunction)
FONCTIONS = {0: "Somme", 1: "Moyenne", 2: "Nombre", 3: "Min", 4: "Max", 5: "Nombre",
             6: "Médiane", 7: "Écart type", 8: "Variance"}


def projections(data) -> list:
    """Les champs d'un visuel, tels que sa requête les LIE (field), rôle par
    rôle. Pas le queryRef : c'est une clé stable que Power BI GARDE quand un
    champ est renommé (« weight.weight obs avg » pour la mesure « Last
    Weight »), donc la lire ferait passer un champ vivant pour cassé."""
    qs = ((data.get("visual") or {}).get("query") or {}).get("queryState") or {}
    out, vus = [], set()
    for bloc in qs.values():
        for p in (bloc or {}).get("projections") or []:
            f = p.get("field") if isinstance(p, dict) else None
            cle = json.dumps(f, sort_keys=True) if f else None
            if cle and cle not in vus:
                vus.add(cle)
                out.append(f)
    return out


def _champ_projection(field, noms, colonnes, fps) -> dict | None:
    """Une projection décrite comme _champ décrit un queryRef."""
    table, prop, genre = champ_de(field)
    if not prop:
        return None
    ref = f"{table}.{prop}"
    if genre == "Measure":
        if prop in noms:
            return {"genre": "mesure", "ref": ref, "table": table, "nom": prop}
        return {"genre": "colonne", "ref": ref, "table": table, "nom": prop, "agregat": None,
                "connue": False, "mesure": True}
    if table in fps and prop == fps[table]["colonne"]:
        return {"genre": "parametre", "ref": ref, "table": table, "nom": prop,
                "mesures": list(fps[table]["mesures"])}
    agr = None
    if isinstance(field, dict) and "Aggregation" in field:
        agr = FONCTIONS.get((field["Aggregation"] or {}).get("Function"), "Agrégat")
    return {"genre": "colonne", "ref": ref, "table": table, "nom": prop, "agregat": agr,
            # un niveau de hiérarchie n'a pas de colonne à son nom
            "connue": genre == "Hierarchy" or (table, prop) in colonnes}



# ---- filtres ----------------------------------------------------------------
# Un filtre de visuel, de page ou de rapport est écrit dans filterConfig ; la
# sélection d'un segment dans visual.objects.general[].properties.filter. Les
# deux portent le même objet de requête : From (alias -> table) et Where
# (conditions In, Not, Comparison, And, Or).

COMPARAISONS = {0: "=", 1: ">", 2: "≥", 3: "<", 4: "≤"}
MAX_VALEURS = 8


def _litteral(v) -> str:
    """'YoY %' -> YoY %, 2024L -> 2024, datetime'2024-01-01T00:00:00' -> 2024-01-01."""
    s = str(v)
    if s.startswith("datetime'"):
        return s[9:-1].split("T")[0]
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if re.match(r"^-?\d+(?:\.\d+)?[LDM]$", s):
        return s[:-1]
    return s


def champ_de(expr) -> tuple:
    """(table, nom, genre) d'une expression de champ : Column, Measure,
    Aggregation, HierarchyLevel. ("", "", "") pour une forme inconnue."""
    if not isinstance(expr, dict):
        return "", "", ""
    for genre in ("Column", "Measure"):
        if genre in expr:
            e = expr[genre]
            src = (e.get("Expression") or {}).get("SourceRef") or {}
            return src.get("Entity") or src.get("Source") or "", e.get("Property") or "", genre
    if "Aggregation" in expr:
        return champ_de((expr["Aggregation"] or {}).get("Expression"))
    if "HierarchyLevel" in expr:
        h = expr["HierarchyLevel"]
        hier = (h.get("Expression") or {}).get("Hierarchy") or {}
        src = (hier.get("Expression") or {}).get("SourceRef") or {}
        return (src.get("Entity") or "",
                f'{hier.get("Hierarchy", "")} {h.get("Level", "")}'.strip(), "Hierarchy")
    # GroupRef (un groupe de valeurs, « 1 month » sur Date) et toute autre
    # forme qui porte une table et une propriété : lue comme une colonne
    # plutôt que perdue
    for v in expr.values():
        if isinstance(v, dict) and "Property" in v:
            src = (v.get("Expression") or {}).get("SourceRef") or {}
            if src.get("Entity"):
                return src["Entity"], v["Property"], "Column"
    return "", "", ""


def _condition(c) -> str:
    if not isinstance(c, dict):
        return ""
    if "In" in c:
        vals = [_litteral(x["Literal"]["Value"]) for ligne in c["In"].get("Values") or []
                for x in ligne if isinstance(x, dict) and "Literal" in x]
        if not vals:
            return "dans une liste calculée"
        reste = len(vals) - MAX_VALEURS
        return "= " + ", ".join(vals[:MAX_VALEURS]) + (f" … (+{reste})" if reste > 0 else "")
    if "Not" in c:
        dedans = _condition((c["Not"] or {}).get("Expression"))
        return "≠ " + dedans[2:] if dedans.startswith("= ") else f"pas ({dedans})"
    if "Comparison" in c:
        k = c["Comparison"]
        droite = (k.get("Right") or {}).get("Literal") or {}
        return f'{COMPARAISONS.get(k.get("ComparisonKind"), "?")} {_litteral(droite.get("Value", "?"))}'
    for op, mot in (("And", " et "), ("Or", " ou ")):
        if op in c:
            return _condition(c[op].get("Left")) + mot + _condition(c[op].get("Right"))
    if "Between" in c:
        b = c["Between"]
        bas = ((b.get("LowerBound") or {}).get("Literal") or {}).get("Value", "?")
        haut = ((b.get("UpperBound") or {}).get("Literal") or {}).get("Value", "?")
        return f"entre {_litteral(bas)} et {_litteral(haut)}"
    return "condition"


def decrire_requete(q) -> str:
    """Le texte des conditions d'un objet filtre ("" s'il ne filtre rien)."""
    if not isinstance(q, dict):
        return ""
    return " et ".join(t for t in (_condition(w.get("Condition")) for w in q.get("Where") or [])
                       if t)


TYPES_FILTRE = {"TopN": "Top N", "RelativeDate": "date relative",
                "RelativeTime": "heure relative", "Advanced": "avancé",
                "Categorical": "", "Include": "inclus", "Exclude": "exclus"}


def filtres_de(conf, niveau: str) -> list:
    """Les filtres d'un filterConfig : [{niveau, table, nom, genre, texte,
    actif}]. Un champ posé dans le volet sans valeur choisie ne filtre rien :
    il est rendu inactif plutôt qu'omis, pour qu'on sache qu'il est là."""
    out = []
    for f in (conf or {}).get("filters") or []:
        table, nom, genre = champ_de(f.get("field"))
        texte = decrire_requete(f.get("filter"))
        genre_f = TYPES_FILTRE.get(f.get("type") or "", f.get("type") or "")
        if genre_f and texte:
            texte = f"{genre_f} : {texte}"
        out.append({"niveau": niveau, "table": table, "nom": nom, "genre": genre,
                    "texte": texte or genre_f, "actif": bool(texte)})
    return out


def selection_segment(data) -> str:
    """Ce qu'un segment a de sélectionné ("" : rien, il ne filtre pas)."""
    objets = (data.get("visual") or {}).get("objects") or {}
    for g in objets.get("general") or []:
        flt = ((g or {}).get("properties") or {}).get("filter") or {}
        texte = decrire_requete(flt.get("filter"))
        if texte:
            return texte
    return ""


def _lire_json(p) -> dict:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# 'Table'[Colonne] ou Table[Colonne] dans le DAX d'une mesure
COLONNE_DAX_RE = re.compile(r"(?:'((?:[^']|'')+)'|\b([A-Za-z_][\w]*))\s*\[((?:[^\]]|\]\])+)\]")


def analyser(pbip) -> dict:
    """Toute la radiographie d'un projet .pbip. Ne modifie rien."""
    pbip = Path(pbip)
    um.set_project(pbip)
    if um.MODEL_DIR is None or not um.MODEL_DIR.exists():
        raise FileNotFoundError(f"modèle introuvable : {um.MODEL_DIR}")
    measures, _blocs, colinfo = um.parse_model()
    noms = set(measures)

    # ---- chaque mesure : son DAX tel qu'écrit, sa table, son dossier
    textes: dict = {}
    mesures: dict = {}
    for n, info in measures.items():
        f = info["file"]
        if f not in textes:
            textes[f] = Path(f).read_text(encoding="utf-8")
        mi = gm.measure_info(textes[f][info["start"]:info["end"]])
        mesures[n] = {"nom": n, "table": info["table"], "dossier": mi.get("folder") or "",
                      "format": mi.get("format") or "", "dax": mi.get("expression") or "",
                      "generee": info["generated"]}

    # ---- le graphe : qui utilise qui (dans l'EXPRESSION, commentaires et
    # chaînes retirés, pas dans les annotations)
    pat = {n: um.bracket_ref(n).lower() for n in noms}
    code = {n: code_dax(mesures[n]["dax"]).lower() for n in noms}
    uses = {a: sorted((b for b in noms if b != a and pat[b] in code[a]), key=str.lower)
            for a in noms}
    used_by = {n: [] for n in noms}
    for a in sorted(noms, key=str.lower):
        for b in uses[a]:
            used_by[b].append(a)

    # ---- à quoi MÈNE une mesure : les mesures de base au bout de ses
    # références (celles qui n'en référencent plus aucune, donc qui lisent les
    # colonnes), et les colonnes qu'elles lisent. C'est là qu'il faut regarder
    # pour savoir ce qu'un visuel montre vraiment.
    tables = {t.lower(): t for t in colinfo["table_file"]}
    colonnes = {}
    for n in noms:
        vues = []
        for m in COLONNE_DAX_RE.finditer(code_dax(mesures[n]["dax"])):
            nom_table = (m.group(1) or "").replace("''", "'") or m.group(2) or ""
            t = tables.get(nom_table.lower())
            if t:
                c = (t, m.group(3).replace("]]", "]"))
                if c not in vues:
                    vues.append(c)
        colonnes[n] = vues
    memo: dict = {}

    def feuilles(n, pile=()):
        if n in memo:
            return memo[n]
        if not uses[n]:
            return [n]
        out = []
        for u in uses[n]:
            if u in pile:
                continue
            for f in feuilles(u, pile + (n,)):
                if f not in out:
                    out.append(f)
        memo[n] = out
        return out

    bases = {n: [b for b in feuilles(n) if b != n] for n in sorted(noms, key=str.lower)}

    fps = _parametres_de_champ(colinfo, noms)
    proposee_par = {n: [t for t, fp in sorted(fps.items()) if n in fp["mesures"]] for n in noms}

    # ---- les visuels, page par page
    pages, visuels = [], []
    affichee: dict = {n: [] for n in noms}      # mesure -> [(visuel, via)]
    choisie: dict = {n: [] for n in noms}       # mesure -> [visuel] (segments)
    rapport = _lire_json(um.REPORT_DIR / "definition" / "report.json")
    filtres_rapport = filtres_de(rapport.get("filterConfig"), "rapport")
    if um.REPORT_DIR.exists():
        for p in rr.pages(um.REPORT_DIR):
            pj = _lire_json(um.REPORT_DIR / "definition" / "pages" / p["id"] / "page.json")
            # interactions coupées : (source, cible) où la source ne filtre pas la cible
            coupees = {(i.get("source"), i.get("target"))
                       for i in pj.get("visualInteractions") or []
                       if i.get("type") == "NoFilter"}
            pages.append({"id": p["id"], "nom": p["display"], "visuels": [],
                          "filtres": filtres_de(pj.get("filterConfig"), "page"),
                          "coupees": coupees})
            for v in rr.visuals(um.REPORT_DIR, p["id"]):
                if v["is_group"]:
                    continue
                segment = v["type"] in SEGMENTS
                data = _lire_json(v["path"])
                projs = projections(data)
                if projs:
                    champs = [c for c in (_champ_projection(f, noms, colinfo["columns"], fps)
                                          for f in projs) if c]
                else:   # visuel sans queryState : ses queryRef, faute de mieux
                    champs = [_champ(r, noms, colinfo["columns"], fps) for r in v["fields"]]
                vis = {"id": v["id"], "page": p["display"], "page_id": p["id"],
                       "type": v["type"], "libelle_type": type_visuel(v["type"]),
                       "titre": v["title"] or "", "masque": v["hidden"],
                       "segment": segment, "champs": champs,
                       "filtres": filtres_de(data.get("filterConfig"), "visuel"),
                       "selection": selection_segment(data) if segment else ""}
                # sans titre, le premier champ distingue « Ruban · Sleep » de
                # « Ruban · Steps » (et dit sur quoi porte un segment)
                def nom_champ(c):
                    return c["table"] if c["genre"] == "parametre" else c["nom"]
                premier = next((nom_champ(c) for c in champs if c["genre"] != "colonne"),
                               nom_champ(champs[0]) if champs else "")
                vis["libelle"] = (f'{vis["libelle_type"]} « {vis["titre"]} »' if vis["titre"]
                                  else f'{vis["libelle_type"]} · {premier}' if premier
                                  else vis["libelle_type"])
                for c in champs:
                    if c["genre"] == "mesure":
                        (choisie if segment else affichee)[c["nom"]].append((vis, None))
                    elif c["genre"] == "parametre":
                        for n in c["mesures"]:
                            (choisie if segment else affichee)[n].append((vis, c["table"]))
                pages[-1]["visuels"].append(vis)
                visuels.append(vis)

    # ---- ce qui filtre chaque visuel : ses filtres, ceux de sa page et du
    # rapport, et les segments de sa page qui ont une sélection, sauf ceux dont
    # l'interaction vers lui est coupée
    for p in pages:
        segs = [s for s in p["visuels"] if s["segment"] and s["selection"]]
        for v in p["visuels"]:
            v["segments"] = [s for s in segs if s is not v
                             and (s["id"], v["id"]) not in p["coupees"]]
        del p["coupees"]

    # ---- les colonnes, et partout où elles servent : ce qu'il faut regarder
    # quand un chiffre est faux (un segment, un filtre du volet, une mesure)
    usages: dict = {}

    # DAX ignore la casse : 'T'[date] et 'T'[Date] sont la même colonne, écrite
    # comme dans le modèle
    ecriture = {(t.lower(), c.lower()): (t, c) for t, c in colinfo["columns"]}

    def noter(table, col, genre, ou, cible, texte="", connue=True):
        if table and col:
            table, col = ecriture.get((table.lower(), col.lower()), (table, col))
            usages.setdefault((table, col), []).append(
                {"genre": genre, "ou": ou, "cible": cible, "texte": texte,
                 "connue": connue})

    def filtre_connu(f):
        return f["genre"] == "Hierarchy" or (f["table"], f["nom"]) in colinfo["columns"]

    for v in visuels:
        cle = ("visuel", (v["page_id"], v["id"]))
        ou = f'{v["page"]} › {v["libelle"]}'
        for c in v["champs"]:
            if c["genre"] == "colonne" and not c.get("mesure"):
                noter(c["table"], c["nom"], "segment" if v["segment"] else "visuel", ou, cle,
                      v["selection"] if v["segment"] else (c.get("agregat") or ""),
                      c["connue"])
            elif c["genre"] == "parametre":
                noter(c["table"], c["nom"], "segment" if v["segment"] else "visuel", ou, cle,
                      v["selection"] if v["segment"] else "paramètre de champ")
        # un filtre de visuel SANS valeur ne filtre rien : Power BI pose dans
        # le volet chaque champ du visuel, et ces doublons noieraient les vrais
        for f in v["filtres"]:
            if f["genre"] != "Measure" and f["actif"]:
                noter(f["table"], f["nom"], "filtre de visuel", ou, cle, f["texte"],
                      filtre_connu(f))
    for p in pages:
        for f in p["filtres"]:
            if f["genre"] != "Measure":
                noter(f["table"], f["nom"], "filtre de page", p["nom"], ("page", p["id"]),
                      f["texte"] if f["actif"] else "sans valeur choisie", filtre_connu(f))
    for f in filtres_rapport:
        if f["genre"] != "Measure":
            noter(f["table"], f["nom"], "filtre de rapport", "tout le rapport", None,
                  f["texte"] if f["actif"] else "sans valeur choisie", filtre_connu(f))
    for m in sorted(noms, key=str.lower):
        for t, c in colonnes[m]:
            noter(t, c, "mesure", f"[{m}]", ("mesure", m))
    colonnes_utilisees = [
        {"table": t, "nom": c, "usages": u, "connue": all(x["connue"] for x in u)}
        for (t, c), u in sorted(usages.items(), key=lambda kv: (kv[0][0].lower(),
                                                                kv[0][1].lower()))]

    # ---- familles
    base_of = _famille_dax(noms, uses)
    familles: dict = {}
    for m in sorted(noms, key=str.lower):
        r = _racine(m, base_of)
        if r != m:
            familles.setdefault(r, {"kpi": r, "genre": DAX, "reel": True, "membres": []})
            familles[r]["membres"].append({"nom": m, "patron": patron(m, r),
                                           "base": base_of[m], "par": DAX})
    dans_dax = set(familles) | {x["nom"] for f in familles.values() for x in f["membres"]}
    restants = [m for m in noms if m not in dans_dax]

    # une mesure seule dont le nom COMMENCE par une racine DAX la rejoint, par
    # le nom (« Weight cible » sous « Weight ») : sinon la famille par le nom
    # « Weight » qu'elle fonderait prendrait la place de la vraie
    racines = sorted(familles, key=len, reverse=True)
    for m in sorted(restants, key=str.lower):
        r = next((r for r in racines if m.lower().startswith(r.lower() + " ")), None)
        if r:
            familles[r]["membres"].append({"nom": m, "patron": patron(m, r), "base": None,
                                           "par": NOM})
    restants = [m for m in restants
                if not any(m.lower().startswith(r.lower() + " ") for r in racines)]

    for tige, membres in _familles_nom(restants).items():
        # une tige qui est elle-même une mesure du groupe en est la base
        reel = next((m for m in membres if m.lower() == tige.lower()), None)
        cle = reel or tige
        while cle in familles:          # jamais écraser une famille déjà là
            cle += " …"
        familles[cle] = {
            "kpi": reel or tige, "genre": NOM, "reel": bool(reel),
            "membres": [{"nom": m, "patron": patron(m, tige, "…"), "base": None, "par": NOM}
                        for m in membres if m != reel]}

    def vus(ms):
        return {(v["page_id"], v["id"]) for m in ms for v, _ in affichee[m]}

    def pages_de(ms):
        return {pid for pid, _ in vus(ms)}

    en_famille = set()
    kpis = []
    for k, f in familles.items():
        tous = ([k] if f["reel"] else []) + [x["nom"] for x in f["membres"]]
        en_famille.update(tous)
        f["visuels"] = len(vus(tous))
        f["pages"] = len(pages_de(tous))
        for x in f["membres"]:
            x["visuels"] = len(vus([x["nom"]]))
        f["visuels_kpi"] = len(vus([k])) if f["reel"] else 0
        kpis.append(f)
    # une mesure seule mais affichée est un KPI aussi, sans variation
    for m in sorted(noms, key=str.lower):
        if m not in en_famille and affichee[m]:
            kpis.append({"kpi": m, "genre": None, "reel": True, "membres": [],
                         "visuels": len(vus([m])), "pages": len(pages_de([m])),
                         "visuels_kpi": len(vus([m]))})
            en_famille.add(m)
    kpis.sort(key=lambda f: (-f["visuels"], -len(f["membres"]), f["kpi"].lower()))

    famille_de = {}
    for f in kpis:
        if f["reel"]:
            famille_de[f["kpi"]] = f["kpi"]
        for x in f["membres"]:
            famille_de[x["nom"]] = f["kpi"]

    # ---- briques : utilisées par au moins deux mesures HORS de leur famille
    briques = []
    for n in noms:
        dehors = [a for a in used_by[n] if famille_de.get(a) is None
                  or famille_de.get(a) != famille_de.get(n)]
        if len(dehors) >= 2:
            briques.append({"nom": n, "utilisateurs": dehors})
    briques.sort(key=lambda b: (-len(b["utilisateurs"]), b["nom"].lower()))
    les_briques = {b["nom"] for b in briques}

    jamais = sorted((n for n in noms if n not in en_famille and n not in les_briques),
                    key=str.lower)

    patrons = Counter(x["patron"] for f in kpis if f["genre"] == DAX for x in f["membres"])

    return {
        "projet": pbip.stem,
        "mesures": mesures, "uses": uses, "used_by": used_by,
        "parametres": fps, "proposee_par": proposee_par,
        "bases": bases, "colonnes": colonnes, "filtres_rapport": filtres_rapport,
        "colonnes_utilisees": colonnes_utilisees,
        "pages": pages, "visuels": visuels,
        "affichee": affichee, "choisie": choisie,
        "kpis": kpis, "famille_de": famille_de,
        "briques": briques, "jamais": jamais,
        "patrons": patrons.most_common(),
    }
