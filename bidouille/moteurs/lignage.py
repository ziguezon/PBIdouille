# -*- coding: utf-8 -*-
"""Le lignage complet d'un rapport : de la source de données au visuel.

Un graphe orienté, de gauche à droite, en bandes :

    sources -> requêtes Power Query -> tables calculées -> mesures (une boîte par
    famille) -> paramètres de champ -> filtres et segments -> visuels

Une flèche A -> B dit « B a besoin de A » :
  · une source alimente les requêtes qui la lisent ; une requête ou une table
    alimente les tables calculées (DAX) et les requêtes (M) qui la citent ;
  · une table alimente les mesures dont le DAX la cite, les filtres et les
    segments posés sur ses colonnes, et les visuels qui affichent une de ses
    colonnes ;
  · une famille de mesures alimente les familles qui reprennent ses mesures,
    les paramètres de champ qui les proposent, les filtres sur mesure et les
    visuels qui les affichent ;
  · un filtre alimente les visuels qu'il filtre (le sien, ceux de sa page, ou
    tout le rapport) ; un segment, les visuels de sa page qu'il filtre.

Les mesures sont regroupées par FAMILLE (radiographie.famille_de) : un KPI et
ses variations font une seule boîte, sinon un rapport de 300 mesures serait
illisible. Une mesure hors famille est sa propre boîte.

Chaque nœud dit s'il est UTILISÉ, c'est-à-dire s'il mène à au moins un visuel
ou un segment : ce qui n'y mène pas (une table chargée pour rien, une mesure
jamais affichée) se montre à part. Les colonnes (couches) se calculent par le
plus long chemin, à l'intérieur de chaque bande : une table calculée qui en lit
une autre se place une colonne plus loin.

Lecture seule : tout vient de radiographie.analyser() et de
lineage.scan_projet().
"""

from __future__ import annotations

import ntpath

import lineage as lg

# l'ordre des bandes, de gauche à droite
BANDES = ("source", "requete", "calculee", "mesures", "parametre", "filtre", "visuel")
TITRES = {"source": "Sources", "requete": "Power Query", "calculee": "Tables calculées",
          "mesures": "Mesures", "parametre": "Paramètres de champ",
          "filtre": "Filtres et segments", "visuel": "Visuels"}
# le genre d'un nœud -> sa bande (un segment est un filtre qu'on voit)
BANDE = {"source": "source", "requete": "requete", "calculee": "calculee",
         "mesures": "mesures", "parametre": "parametre", "filtre": "filtre",
         "segment": "filtre", "visuel": "visuel"}
TERMINAUX = ("visuel", "segment")


def _nom_court(detail: str) -> str:
    """Un chemin de fichier par son nom ; le reste tel quel."""
    if detail and "://" not in detail and ("\\" in detail or "/" in detail):
        return ntpath.basename(detail.rstrip("\\/")) or detail
    return detail


def _texte_filtre(f) -> str:
    champ = (f"[{f['nom']}]" if f["genre"] == "Measure"
             else f"'{f['table']}'[{f['nom']}]" if f["table"] else f["nom"])
    return f"{champ} {f['texte']}"


def construire(res, lignes) -> dict:
    """{"noeuds": {id: noeud}, "liens": [(id_amont, id_aval)]}

    noeud = {"id", "genre", "bande", "libelle", "detail", "cible", "page",
             "couche", "utilise"} ; `cible` est (genre, clé) pour la fiche."""
    noeuds: dict = {}
    liens: set = set()
    params = set(res.get("parametres") or {})

    def noeud(nid, genre, libelle, detail="", cible=None, page=""):
        if nid not in noeuds:
            noeuds[nid] = {"id": nid, "genre": genre, "bande": BANDE[genre],
                           "libelle": libelle, "detail": detail, "cible": cible,
                           "page": page}
        return nid

    def de_table(t):
        """Le nœud d'une table : un paramètre de champ a le sien."""
        return ("parametre", t) if t in params else ("table", t)

    # ---- sources, requêtes, tables calculées -------------------------------
    for l in lignes:
        if l["genre"] == lg.LIVE:
            noeud(("source", "live"), "source", "Connexion live", l["detail1"],
                  ("source", l))
            continue
        t = lg.nom_noeud(l)
        if l["genre"] == lg.CALCULEE:
            if t not in params:
                noeud(("table", t), "calculee", t, "table calculée (DAX)", ("table", l))
        else:
            partagee = l["table"] == lg.EXPRESSIONS
            noeud(("table", t), "requete", t,
                  "requête partagée" if partagee else (l.get("objet") or l["mode"] or ""),
                  ("table", l))
            if l["genre"] == lg.SOURCE:
                sid = ("source", (l["connecteur"], l["detail1"], l["detail2"]))
                nom = " · ".join(x for x in (_nom_court(l["detail1"]), l["detail2"]) if x)
                noeud(sid, "source", nom or l["connecteur"], l["famille"] or l["connecteur"],
                      ("source", l))
                liens.add((sid, ("table", t)))
        for x in l.get("lit") or []:
            liens.add((de_table(x), de_table(t)))

    # ---- mesures, par famille ----------------------------------------------
    familles: dict = {}
    for m in res["mesures"]:
        familles.setdefault(res["famille_de"].get(m, m), []).append(m)

    def unite(m):
        return ("mesures", res["famille_de"].get(m, m))

    for kpi, membres in familles.items():
        cible = ("mesure", kpi) if kpi in res["mesures"] else ("famille", kpi)
        noeud(("mesures", kpi), "mesures", kpi,
              f"{len(membres)} mesures" if len(membres) > 1 else "mesure", cible)
        noeuds[("mesures", kpi)]["membres"] = sorted(membres, key=str.lower)
    tables = [nid[1] for nid in noeuds if nid[0] == "table"] + sorted(params)
    for m, info in res["mesures"].items():
        u = unite(m)
        for t in lg.tables_citees(info.get("dax") or "", tables):
            liens.add((de_table(t), u))
        for b in res["uses"].get(m, []):
            if unite(b) != u:
                liens.add((unite(b), u))

    # ---- paramètres de champ -------------------------------------------------
    for t, fp in (res.get("parametres") or {}).items():
        pid = noeud(("parametre", t), "parametre", t,
                    f"{len(fp['mesures'])} mesure(s) au choix", ("parametre", t))
        for m in fp["mesures"]:
            if m in res["mesures"]:
                liens.add((unite(m), pid))

    # ---- visuels et segments ----------------------------------------------------
    def source_filtre(f):
        if f["genre"] == "Measure":
            return unite(f["nom"]) if f["nom"] in res["mesures"] else None
        return de_table(f["table"]) if f["table"] else None

    def filtre(f, nid, cibles):
        src = source_filtre(f)
        noeud(nid, "filtre", _texte_filtre(f), f"filtre de {f['niveau']}", ("filtre", nid))
        if src:
            liens.add((src, nid))
        for c in cibles:
            liens.add((nid, c))

    for v in res["visuels"]:
        cle = (v["page_id"], v["id"])
        vid = noeud(("visuel", cle), "segment" if v["segment"] else "visuel", v["libelle"],
                    (v["selection"] or "aucune sélection") if v["segment"] else v["page"],
                    ("visuel", cle), v["page"])
        for c in v["champs"]:
            if c["genre"] == "mesure" and c["nom"] in res["mesures"]:
                liens.add((unite(c["nom"]), vid))
            elif c["genre"] == "parametre":
                liens.add((("parametre", c["table"]), vid))
            elif c["genre"] == "colonne" and c.get("table") and not c.get("mesure"):
                liens.add((de_table(c["table"]), vid))
        # un segment qui en filtre un autre n'apprend rien sur le lignage, et
        # chaînerait les segments d'une page sur dix colonnes
        for s in (v.get("segments") or []) if not v["segment"] else []:
            liens.add((("visuel", (s["page_id"], s["id"])), vid))
        for i, f in enumerate(v["filtres"]):
            if f["actif"]:
                filtre(f, ("filtre", "visuel", cle, i), [vid])
    for p in res["pages"]:
        vis = [("visuel", (v["page_id"], v["id"])) for v in p["visuels"] if not v["segment"]]
        for i, f in enumerate(p["filtres"]):
            if f["actif"]:
                filtre(f, ("filtre", "page", p["id"], i), vis)
    tous = [("visuel", (v["page_id"], v["id"])) for v in res["visuels"] if not v["segment"]]
    for i, f in enumerate(res.get("filtres_rapport") or []):
        if f["actif"]:
            filtre(f, ("filtre", "rapport", None, i), tous)

    # un lien vers un nœud qui n'existe pas (table inconnue, champ cassé) tombe
    liens = sorted((a, b) for a, b in liens if a in noeuds and b in noeuds and a != b)
    _utilises(noeuds, liens)
    _couches(noeuds, liens)
    return {"noeuds": noeuds, "liens": liens}


def _utilises(noeuds, liens):
    """Marque ce qui mène à un visuel ou à un segment."""
    amont: dict = {}
    for a, b in liens:
        amont.setdefault(b, []).append(a)
    vus = {n for n, x in noeuds.items() if x["genre"] in TERMINAUX}
    pile = list(vus)
    while pile:
        for a in amont.get(pile.pop(), []):
            if a not in vus:
                vus.add(a)
                pile.append(a)
    for n, x in noeuds.items():
        x["utilise"] = n in vus


def _couches(noeuds, liens):
    """La colonne de chaque nœud : bande par bande, le plus long chemin parmi
    les liens de la même bande. Une bande commence après la dernière colonne
    de la précédente."""
    amont: dict = {}
    for a, b in liens:
        amont.setdefault(b, []).append(a)
    debut = 0
    for bande in BANDES:
        membres = [n for n, x in noeuds.items() if x["bande"] == bande]
        prof = {n: 0 for n in membres}
        # au plus len(membres) passes : assez pour tout chemin sans boucle
        for _ in range(len(membres)):
            change = False
            for n in membres:
                p = max((prof[a] + 1 for a in amont.get(n, []) if a in prof), default=0)
                if p > prof[n] and p < len(membres):
                    prof[n] = p
                    change = True
            if not change:
                break
        for n in membres:
            noeuds[n]["couche"] = debut + prof[n]
        if membres:
            debut += max(prof.values()) + 1


def chaine_sens(liens, depart, amont: bool) -> set:
    """Tout ce dont un nœud vient (amont) ou tout ce qui en dépend (aval), lui
    compris."""
    voisins: dict = {}
    for a, b in liens:
        if amont:
            voisins.setdefault(b, []).append(a)
        else:
            voisins.setdefault(a, []).append(b)
    vus, pile = {depart}, [depart]
    while pile:
        for x in voisins.get(pile.pop(), []):
            if x not in vus:
                vus.add(x)
                pile.append(x)
    return vus


def chaine(liens, depart) -> set:
    """Tout ce qui est en amont ET en aval d'un nœud, lui compris."""
    amont: dict = {}
    aval: dict = {}
    for a, b in liens:
        aval.setdefault(a, []).append(b)
        amont.setdefault(b, []).append(a)
    vus = {depart}
    for voisins in (amont, aval):
        pile = [depart]
        while pile:
            for x in voisins.get(pile.pop(), []):
                if x not in vus:
                    vus.add(x)
                    pile.append(x)
    return vus


# ---- l'export d'une chaîne --------------------------------------------------

COLONNES_EXPORT = ["Sens", "Distance", "Bande", "Élément", "Détail", "Page", "Famille",
                   "Mène à un visuel"]


def distances(liens, depart, amont: bool) -> dict:
    """{nœud: nombre de pas depuis `depart`}, vers l'amont ou vers l'aval."""
    voisins: dict = {}
    for a, b in liens:
        if amont:
            voisins.setdefault(b, []).append(a)
        else:
            voisins.setdefault(a, []).append(b)
    dist = {depart: 0}
    file = [depart]
    while file:
        n = file.pop(0)
        for x in voisins.get(n, []):
            if x not in dist:
                dist[x] = dist[n] + 1
                file.append(x)
    return dist


def lignes_export(graphe, depart, sens: str = "deux") -> list:
    """Les lignes d'export de la chaîne d'un nœud : ce dont il vient (amont),
    lui (choisi), ce qui en dépend (aval). `sens` : "deux", "amont" ou "aval".
    Une famille de mesures donne une ligne par mesure, sa famille en colonne."""
    noeuds = graphe["noeuds"]
    ordre = {b: i for i, b in enumerate(BANDES)}
    morceaux = [("choisi", {depart: 0})]
    if sens in ("deux", "amont"):
        morceaux.insert(0, ("amont", distances(graphe["liens"], depart, True)))
    if sens in ("deux", "aval"):
        morceaux.append(("aval", distances(graphe["liens"], depart, False)))
    out = []
    for nom_sens, dist in morceaux:
        ids = [n for n in dist if (n == depart) == (nom_sens == "choisi")]
        ids.sort(key=lambda n: (ordre[noeuds[n]["bande"]], noeuds[n]["libelle"].lower()))
        for n in ids:
            x = noeuds[n]
            base = {"Sens": nom_sens, "Distance": dist[n], "Bande": TITRES[x["bande"]],
                    "Détail": x["detail"], "Page": x["page"], "Famille": "",
                    "Mène à un visuel": "oui" if x["utilise"] else "non"}
            if x["genre"] == "mesures" and x.get("membres"):
                for m in x["membres"]:
                    out.append(dict(base, **{"Élément": m, "Détail": "mesure",
                                             "Famille": x["libelle"]}))
            else:
                out.append(dict(base, **{"Élément": x["libelle"]}))
    return out


def ecrire_csv(lignes, chemin) -> None:
    """CSV ; séparé, UTF-8 avec BOM : Excel l'ouvre tel quel."""
    import csv
    from pathlib import Path
    with Path(chemin).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES_EXPORT, delimiter=";")
        w.writeheader()
        for l in lignes:
            w.writerow(l)
