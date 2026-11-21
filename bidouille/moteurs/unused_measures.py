# -*- coding: utf-8 -*-
"""
Identifie les mesures inutilisées d'un projet PBIP : ni référencées dans le
rapport (visuels, filtres, tris, formatage conditionnel, signets...), ni par
le modèle (autres mesures, tables calculées — dont les paramètres de champ —,
colonnes calculées), directement ou indirectement.

Logique :
  1. racines « rapport » : toute mesure référencée dans un JSON du .Report ;
  2. racines « modèle »  : toute mesure référencée hors d'une définition de
     mesure (table calculée, colonne calculée, groupe de calcul...) ;
  3. propagation : une mesure référencée par une mesure utilisée est utilisée
     (fermeture transitive) ;
  4. tout le reste est INUTILISÉ, en deux catégories :
     - « aucune référence »  : personne ne la référence ;
     - « used by unused »    : référencée, mais seulement par des mesures
       elles-mêmes inutilisées (la chaîne est montrée — tout part ensemble).

Pour chaque mesure, les référenceurs sont détaillés par type : mesures,
tables calculées, colonnes calculées, fichiers du rapport.

En ligne de commande (py unused_measures.py) : unused_measures.csv, l'état
de toutes les mesures et colonnes (audit complet). La suppression se fait
dans l'app (ChopChop), pas en ligne de commande.

Power Query compte comme une source d'usage à part entière, mais ENTRE
requêtes seulement : si la requête B fusionne/ajoute/joint la requête A, la
table A est vivante (la supprimer casse l'actualisation de B) et les colonnes
de A que B nomme sont protégées. À l'INTÉRIEUR d'une même requête, une mention
(type, renommage, colonne dérivée) ne protège rien : l'étape Table.RemoveColumns
posée par ChopChop est la DERNIÈRE de la requête, donc tout ce qui précède a
déjà produit son résultat.

En module (unused_measures_ui.py) :
  - analyze()          : l'analyse complète, sans rien modifier (les colonnes
    portent une `category` : calc / import / structural ; `spared_tables` dit
    pourquoi une table sans usage visible est malgré tout conservée) ;
  - delete_objects()   : suppression de mesures, colonnes ET tables entières
    dans les TMDL (backup avant écriture ; rouvrir Desktop sans enregistrer). Une colonne importée
    est aussi retirée de sa requête M (étape Table.RemoveColumns) ; une table
    morte (result['dead_tables']) est supprimée fichier + réf model.tmdl ;
  - delete_from_tmdl() : compat (mesures seules) — délègue à delete_objects.

Note : les mesures générées par PBIdouille portent l'annotation
MeasureVariation et sont marquées « générée ». Les supprimer ne sert à rien,
la prochaine génération les recrée : retirer plutôt la variation ou la
branche de measures_config.json (removeOrphans fera le ménage).
"""

from __future__ import annotations  # annotations paresseuses : Python 3.8+

import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# backup_restore.py est le voisin de ce fichier : on garantit sa résolution
# même si le module est importé depuis un autre dossier de travail
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_restore as br
import chemins                    # où sont les projets

# ---------------------------------------------------------------------------
# défauts de la ligne de commande ; l'app appelle set_project()
PBIP_DIR = chemins.PROJETS
PROJECT  = chemins.PROJET_DEMO
# ---------------------------------------------------------------------------

REPORT_DIR  = PBIP_DIR / f"{PROJECT}.Report"
MODEL_DIR   = PBIP_DIR / f"{PROJECT}.SemanticModel"
CSV_PATH    = PBIP_DIR / "unused_measures.csv"
BACKUP_ROOT = br.backup_root(PBIP_DIR, "_tmdl_backups")


def set_project(pbip_path: Path) -> None:
    """Pointe le module vers un autre projet PBIP (utilisé par l'UI pour
    changer de rapport). Recalcule tous les chemins dérivés."""
    global PBIP_DIR, PROJECT, REPORT_DIR, MODEL_DIR, CSV_PATH, BACKUP_ROOT
    pbip_path = Path(pbip_path)
    PBIP_DIR    = pbip_path.parent
    PROJECT     = pbip_path.stem
    REPORT_DIR  = PBIP_DIR / f"{PROJECT}.Report"
    MODEL_DIR   = PBIP_DIR / f"{PROJECT}.SemanticModel"
    CSV_PATH    = PBIP_DIR / "unused_measures.csv"
    BACKUP_ROOT = br.backup_root(PBIP_DIR, "_tmdl_backups")

# fichiers de definition\ qui ne portent NI DAX NI requête M : à ne pas
# scanner comme du code (cf. parse_model)
NON_DAX_FILES = {"model", "database", "relationships", "expressions"}

MEMBER_RE  = re.compile(
    r"^\t(measure|column|partition|hierarchy|calculationGroup|annotation|extendedProperty)\b",
    re.M,
)
# les noms TMDL entre apostrophes échappent l'apostrophe en la DOUBLANT :
# measure 'nbre d''appels' = ...  ->  (?:[^']|'')+ avale les '' internes
MEASURE_NAME_RE   = re.compile(r"^\tmeasure\s+(?:'((?:[^']|'')+)'|([^\s=']+))")
COLUMN_NAME_RE    = re.compile(r"^\tcolumn\s+(?:'((?:[^']|'')+)'|([^\s=']+))")
PARTITION_NAME_RE = re.compile(r"^\tpartition\s+(?:'((?:[^']|'')+)'|([^\s=']+))")
TABLE_NAME_RE     = re.compile(r"^table\s+(?:'((?:[^']|'')+)'|(\S+))", re.M)

# --- colonnes : sources d'usage côté modèle ---------------------------------
# sortByColumn: X  (propriété de colonne, même table)
SORTBY_RE = re.compile(r"^\t+sortByColumn:\s*(?:'((?:[^']|'')+)'|(\S+))", re.M)
# groupByColumn: X  (relatedColumnDetails des paramètres de champ, même table)
GROUPBY_RE = re.compile(r"^\t+groupByColumn:\s*(?:'((?:[^']|'')+)'|(\S+))", re.M)
# column: X  dans les niveaux de hiérarchie (même table)
HIER_LEVEL_COL_RE = re.compile(r"^\t\t+column:\s*(?:'((?:[^']|'')+)'|(\S+))", re.M)
# sourceColumn: X  (nom de la colonne dans la sortie de la requête M ; pour une
# colonne importée c'est le nom M à retirer, cf. ChopChop)
SOURCECOL_RE = re.compile(r"^\t\tsourceColumn:\s*(.+?)\s*$", re.M)
# partition X = <mode>   (m = requête Power Query ; calculated = table DAX)
PARTITION_MODE_RE = re.compile(
    r"^\tpartition\s+(?:'(?:[^']|'')+'|[^\s=']+)\s*=\s*(\S+)", re.M)
# fromColumn/toColumn: Table.Colonne  dans relationships.tmdl
REL_ENDPOINT_RE = re.compile(
    r"^\s*(?:fromColumn|toColumn):\s*"
    r"(?:'((?:[^']|'')+)'|([^.\s']+))\.(?:'((?:[^']|'')+)'|(\S+))",
    re.M,
)


def bracket_ref(name: str) -> str:
    """Référence DAX [Nom] (']' s'échappe en ']]')."""
    return "[" + name.replace("]", "]]") + "]"


# --- Power Query : références d'une requête à une autre ---------------------
M_QUOTED_ID_RE = re.compile(r'#"((?:[^"]|"")*)"')
M_STRING_RE    = re.compile(r'"(?:[^"]|"")*"')
# identifiant M nu ; les points font partie du jeton pour que
# Table.RemoveColumns compte pour UN nom (sinon une table nommée « Table »
# passerait pour référencée par toutes les requêtes du modèle)
M_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def m_query_refs(m_text: str) -> set:
    """Noms de requêtes référencés par une requête M, en minuscules : formes
    `#"nom avec espaces"` ET identifiants nus.

    Les littéraux de chaîne sont retirés d'abord : dans
    `Source{[Name="sleep",Kind="Table"]}`, « sleep » nomme une table de la
    SOURCE (ODBC/SQL/Excel), pas la requête « sleep » du modèle. Sans ce
    filtrage, toute table homonyme d'un objet source passerait pour consommée."""
    refs: set = set()

    def grab(m):
        refs.add(m.group(1).replace('""', '"').lower())
        return " "

    stripped = M_STRING_RE.sub(" ", M_QUOTED_ID_RE.sub(grab, m_text))
    for m in M_IDENT_RE.finditer(stripped):
        refs.add(m.group(0).lower())
    return refs


# --- DAX : références à une TABLE entière -----------------------------------
DAX_STRING_RE  = re.compile(r'"(?:[^"]|"")*"')
DAX_BRACKET_RE = re.compile(r"\[(?:[^\]]|\]\])*\]")


def strip_dax_noise(text: str) -> str:
    """DAX débarrassé de ses littéraux et de ses crochets. Ce qui reste d'une
    référence `'Table'[Col]` ou `Table[Col]`, c'est le nom de table — et une
    mesure `[steps YTD]` ou une chaîne `"steps"` ne peut plus passer pour un
    usage de la table `steps`."""
    return DAX_BRACKET_RE.sub(" ", DAX_STRING_RE.sub(" ", text))


def _table_re(table: str):
    """Référence DAX à une table ENTIÈRE — `'Table'` ou `Table` nu, comme dans
    COUNTROWS(T) / ALL(T) / SUMMARIZE(T, …). À appliquer sur un texte déjà
    passé par strip_dax_noise() et mis en minuscules. Le lookbehind/lookahead
    empêche `dim_client_2` de matcher `dim_client`."""
    t = re.escape(table.lower())
    return re.compile(r"'" + t + r"'|(?<![\w'])" + t + r"(?![\w'])")


def _first_group(match) -> str | None:
    """Nom capturé par les regex TMDL, apostrophes dé-échappées ('' -> ')."""
    if not match:
        return None
    if match.group(1) is not None:
        return match.group(1).replace("''", "'")
    return match.group(2)


def parse_model():
    """Retourne (measures, other_blocks, colinfo) :
    measures     : nom -> {table, block (minuscules), generated, file, start, end}
                   file/start/end = où vit le bloc, pour la suppression TMDL ;
    other_blocks : liste de {kind, label, table, text} pour tout le TMDL hors
                   mesures (kind = « table calculée », « colonne calculée »...)
                   — une référence [mesure] dedans = usage par la structure.
                   Les annotations/extendedProperties sont exclues (faux
                   positifs possibles, aucune sémantique DAX) ;
    colinfo      : tout ce qu'il faut pour l'analyse des COLONNES :
                   columns    : (table, colonne) -> {table, name, calculated, file}
                   sort_refs  : {(table, colonne)} ciblées par un sortByColumn
                   hier_refs  : {(table, colonne)} dans un niveau de hiérarchie
                   table_text : table -> texte COMPLET du .tmdl en minuscules
                                (pour la recherche conservatrice [Col] même table)
                   prop_text  : table -> annotations + extendedProperties en
                                minuscules (les paramètres de champ y citent
                                leurs colonnes techniques en JSON : "X Fields")."""
    measures: dict[str, dict] = {}
    other_blocks: list[dict] = []
    columns: dict = {}
    sort_refs: set = set()
    group_refs: set = set()
    hier_refs: set = set()
    table_text: dict = {}
    prop_text: dict = {}
    partition_mode: dict = {}     # table -> 'm' | 'calculated' | ...
    table_file: dict = {}         # table -> chemin de son .tmdl
    m_source: dict = {}           # table import -> texte de sa requête M (minuscules)

    for tmdl in sorted((MODEL_DIR / "definition").rglob("*.tmdl")):
        if tmdl.parent.name == "cultures":
            continue  # métadonnées linguistiques : faux positifs
        if tmdl.parent.name == "definition" and tmdl.stem.lower() in NON_DAX_FILES:
            # ni DAX ni requête : model.tmdl liste « ref table X » pour CHAQUE
            # table (le scanner comme du DAX rendrait toute table « utilisée »),
            # relationships est lu par relationship_refs(), expressions est du M
            continue
        text = tmdl.read_text(encoding="utf-8")
        tm = TABLE_NAME_RE.search(text)
        table = _first_group(tm) or tmdl.stem
        pm = PARTITION_MODE_RE.search(text)
        if tm and pm:  # mode d'alimentation de la table (import M vs DAX)
            partition_mode[table] = pm.group(1)
        if tm:  # seulement les vraies tables (pas relationships/roles/model)
            table_text[table] = text.lower()
            table_file[table] = str(tmdl)

        members = list(MEMBER_RE.finditer(text))
        pre = text[: members[0].start()] if members else text
        if pre.strip():
            other_blocks.append({"kind": "table", "label": f"'{table}'",
                                 "table": table, "text": pre.lower()})

        for i, m in enumerate(members):
            end = members[i + 1].start() if i + 1 < len(members) else len(text)
            block = text[m.start():end]
            kind = m.group(1)

            # requête M d'une table importée, texte BRUT (la casse compte pour
            # les identifiants M) : sert à repérer les dépendances entre
            # requêtes — fusion, ajout, jointure — invisibles au rapport
            if kind == "partition" and partition_mode.get(table) == "m":
                m_source[table] = m_source.get(table, "") + block
                # PAS dans other_blocks : une requête M n'est pas du DAX. Elle
                # n'appelle aucune mesure, et un accès champ [x] n'y protège
                # pas la colonne x (l'étape RemoveColumns de ChopChop s'ajoute
                # APRÈS toutes les autres). Les dépendances M s'analysent
                # entre requêtes (m_query_refs), pas ici.
                continue

            if kind == "measure":
                name = _first_group(MEASURE_NAME_RE.match(block))
                if name:
                    measures[name] = {
                        "table": table,
                        "block": block.lower(),
                        "generated": "annotation MeasureVariation" in block,
                        "file": str(tmdl),
                        "start": m.start(),
                        "end": end,
                    }
                    continue

            if kind == "column":
                # collecte de la colonne (analyse d'usage) + sortByColumn
                header = COLUMN_NAME_RE.match(block)
                cname = _first_group(header)
                if cname and tm:
                    first_line = block.splitlines()[0]
                    sc = SOURCECOL_RE.search(block)
                    columns[(table, cname)] = {
                        "table": table,
                        "name": cname,
                        # colonne calculée : « column X = <DAX> » en tête
                        "calculated": "=" in first_line[header.end():],
                        # nom M à retirer de la requête (None si absent). Les
                        # crochets [Value1] des tables calculées sont conservés
                        # tels quels : ils signalent une colonne « structurelle ».
                        "source_column": sc.group(1) if sc else None,
                        "file": str(tmdl),
                    }
                for sm in SORTBY_RE.finditer(block):
                    tgt = _first_group(sm)
                    if tgt:
                        sort_refs.add((table, tgt))
                for gm in GROUPBY_RE.finditer(block):
                    tgt = _first_group(gm)
                    if tgt:
                        group_refs.add((table, tgt))

            if kind == "hierarchy":
                for hm in HIER_LEVEL_COL_RE.finditer(block):
                    tgt = _first_group(hm)
                    if tgt:
                        hier_refs.add((table, tgt))
                continue  # pas de DAX pour les mesures

            if kind in ("annotation", "extendedProperty"):
                # pas de DAX, mais les extendedProperties des paramètres de
                # champ citent leurs colonnes (JSON "Property": "X Fields")
                prop_text[table] = prop_text.get(table, "") + block.lower()
                continue

            if kind == "column":
                label = f"'{table}'[{_first_group(COLUMN_NAME_RE.match(block)) or '?'}]"
                kind_label = "colonne calculée"
            elif kind == "partition":
                pname = _first_group(PARTITION_NAME_RE.match(block)) or table
                label = f"'{table}'" + (f" ({pname})" if pname != table else "")
                kind_label = "table calculée" if "= calculated" in block.splitlines()[0] else "partition"
            elif kind == "calculationGroup":
                label = f"'{table}'"
                kind_label = "groupe de calcul"
            else:
                label = f"'{table}'"
                kind_label = kind

            other_blocks.append({"kind": kind_label, "label": label,
                                 "table": table, "text": block.lower()})

    # requêtes M partagées (paramètres, fonctions, requêtes « ne pas charger »)
    # : elles aussi peuvent consommer la requête d'une table
    expr_file = MODEL_DIR / "definition" / "expressions.tmdl"
    if expr_file.exists():
        m_source["(expressions partagées)"] = expr_file.read_text(encoding="utf-8")

    return measures, other_blocks, {
        "columns": columns,
        "sort_refs": sort_refs,
        "group_refs": group_refs,
        "hier_refs": hier_refs,
        "table_text": table_text,
        "prop_text": prop_text,
        "partition_mode": partition_mode,
        "table_file": table_file,
        "m_source": m_source,
    }


def documents_rapport():
    """Chaque JSON du rapport doit être lisible pour conclure sur ses usages."""
    if not REPORT_DIR.is_dir():
        raise SystemExit(f"Analyse incomplète : rapport introuvable ({REPORT_DIR}).")
    def dossier_illisible(exc):
        raise SystemExit(f"Analyse incomplète : parcours du rapport interrompu ({exc}).") from exc

    fichiers = []
    for dossier, _, noms in os.walk(REPORT_DIR, onerror=dossier_illisible):
        fichiers.extend(Path(dossier) / nom for nom in noms if nom.lower().endswith(".json"))
    if not fichiers:
        raise SystemExit(f"Analyse incomplète : aucun fichier JSON dans {REPORT_DIR}.")
    for jf in sorted(fichiers):
        nom = jf.relative_to(REPORT_DIR).as_posix()
        try:
            data = json.loads(jf.read_text(encoding="utf-8-sig"))
        except (ValueError, OSError) as exc:
            raise SystemExit(f"Analyse incomplète : {nom} illisible ({exc}).") from exc
        yield nom, data


def report_used(measure_names: set[str]) -> dict[str, list[str]]:
    """mesure -> fichiers du .Report qui la référencent (visuels, filtres,
    tris, CF, signets, layout mobile...)."""
    refs: dict[str, set[str]] = {}

    def hit(name: str, fname: str):
        refs.setdefault(name, set()).add(fname)

    def walk(node, fname: str):
        if isinstance(node, dict):
            meas = node.get("Measure")
            if isinstance(meas, dict):
                prop = meas.get("Property")
                if prop in measure_names:
                    hit(prop, fname)
            for key, value in node.items():
                if key in ("metadata", "queryRef") and isinstance(value, str) and "." in value:
                    cand = value.split(".", 1)[1]
                    if cand in measure_names:
                        hit(cand, fname)
                walk(value, fname)
        elif isinstance(node, list):
            for x in node:
                walk(x, fname)

    for nom, data in documents_rapport():
        walk(data, nom)

    return {n: sorted(files) for n, files in refs.items()}


def report_used_columns(column_keys, entities_out: set | None = None) -> dict:
    """(table, colonne) -> fichiers du .Report qui la référencent. Matche en
    PAIRE table+colonne (les noms de colonnes se répètent d'une table à
    l'autre) : dicts Column{Property + SourceRef Entity/alias} et chaînes
    metadata/queryRef « table.colonne ». Un alias non résolu retombe sur le
    nom seul (conservateur : marque toutes les tables candidates).

    `entities_out` (optionnel) se remplit au passage des noms de tables citées
    comme `Entity` dans les requêtes du rapport — le « From » d'un visuel. Une
    table qui y figure est utilisée même si aucune de ses colonnes ne l'est."""
    low = {(t.lower(), c.lower()): (t, c) for t, c in column_keys}
    by_name: dict = {}
    for t, c in column_keys:
        by_name.setdefault(c.lower(), set()).add((t, c))

    refs: dict = {}

    def hit(key, fname):
        refs.setdefault(key, set()).add(fname)

    def collect_aliases(node, aliases):
        # entrées « from » : {"Name": "s", "Entity": "steps"} n'importe où
        if isinstance(node, dict):
            name, ent = node.get("Name"), node.get("Entity")
            if isinstance(ent, str):
                if entities_out is not None:
                    entities_out.add(ent.lower())
                if isinstance(name, str):
                    aliases.setdefault(name, ent)
            for v in node.values():
                collect_aliases(v, aliases)
        elif isinstance(node, list):
            for x in node:
                collect_aliases(x, aliases)

    def walk(node, fname, aliases):
        if isinstance(node, dict):
            col = node.get("Column")
            if isinstance(col, dict):
                prop = col.get("Property")
                src = (col.get("Expression") or {}).get("SourceRef") or {}
                ent = src.get("Entity") or aliases.get(src.get("Source"))
                if isinstance(prop, str):
                    if ent:
                        key = low.get((ent.lower(), prop.lower()))
                        if key:
                            hit(key, fname)
                    else:  # alias irrésolu : toutes les tables ayant ce nom
                        for key in by_name.get(prop.lower(), ()):
                            hit(key, fname)
            for k, value in node.items():
                if k in ("metadata", "queryRef") and isinstance(value, str) and "." in value:
                    t, c = value.split(".", 1)
                    key = low.get((t.lower(), c.lower()))
                    if key:
                        hit(key, fname)
                walk(value, fname, aliases)
        elif isinstance(node, list):
            for x in node:
                walk(x, fname, aliases)

    for nom, data in documents_rapport():
        aliases: dict = {}
        collect_aliases(data, aliases)
        walk(data, nom, aliases)

    return {k: sorted(files) for k, files in refs.items()}


def relationship_refs() -> set:
    """{(table, colonne)} aux extrémités des relations (relationships.tmdl)."""
    out: set = set()
    rel = MODEL_DIR / "definition" / "relationships.tmdl"
    if not rel.exists():
        return out
    for m in REL_ENDPOINT_RE.finditer(rel.read_text(encoding="utf-8")):
        t = (m.group(1) or m.group(2) or "").replace("''", "'")
        c = (m.group(3) or m.group(4) or "").replace("''", "'")
        if t and c:
            out.add((t, c))
    return out


def _qualified_res(table: str, column: str):
    """Regex des références DAX qualifiées 'Table'[Col] / Table[Col] (en
    minuscules, ']' échappé en ']]', lookbehind pour éviter les suffixes de
    noms de tables : xdim[c] ne matche pas dim[c])."""
    c = re.escape(column.lower().replace("]", "]]"))
    t = re.escape(table.lower())
    return re.compile(r"(?:'" + t + r"'|(?<![\w'])" + t + r")\s*\[" + c + r"\]")


def analyze() -> dict:
    """Analyse complète, sans rien modifier. Retourne :
    { measures, via, unused, referencers (= meas_refs), report_refs,
      struct_refs,
      columns, column_via, unused_columns, column_chained,
      column_referencers, column_report_refs, column_struct_refs }
    - via          : mesure utilisée -> raison ;
    - referencers  : mesure -> mesures qui la référencent (toutes) ;
    - report_refs  : mesure -> fichiers du rapport qui la référencent ;
    - struct_refs  : mesure -> [(type, objet)] côté modèle hors mesures.
    Côté colonnes (clés d'affichage « 'Table'[Colonne] ») :
    - columns          : clé -> {table, name, calculated} ;
    - column_via       : colonne utilisée -> raison ;
    - unused_columns   : aucune référence ;
    - column_chained   : « used by unused » (référencées seulement par des
                         mesures elles-mêmes inutilisées) ;
    - column_referencers : clé -> mesures qui la référencent ;
    - column_report_refs / column_struct_refs : détail des usages."""
    if not MODEL_DIR.exists() or not REPORT_DIR.exists():
        raise SystemExit(f"Projet introuvable sous {PBIP_DIR} ({PROJECT}).")

    measures, other_blocks, colinfo = parse_model()
    names = set(measures)

    # racines + attribution détaillée
    report_refs = report_used(names)
    pat = {n: bracket_ref(n).lower() for n in names}
    struct_refs: dict[str, list] = {}
    for n in names:
        hits = [(b["kind"], b["label"]) for b in other_blocks if pat[n] in b["text"]]
        if hits:
            struct_refs[n] = hits

    # graphe mesure -> mesures qu'elle référence, et l'inverse
    edges = {a: {b for b in names if b != a and pat[b] in measures[a]["block"]} for a in names}
    referencers = {n: sorted(a for a in names if n in edges[a]) for n in names}

    # fermeture transitive depuis les racines
    via: dict[str, str] = {}
    for n in sorted(report_refs):
        via.setdefault(n, "rapport")
    for n in sorted(struct_refs):
        via.setdefault(n, "modèle : " + struct_refs[n][0][0] + " " + struct_refs[n][0][1])
    queue = list(via)
    while queue:
        cur = queue.pop()
        for nxt in edges[cur]:
            if nxt not in via:
                via[nxt] = f"référencée par [{cur}]"
                queue.append(nxt)

    unused = sorted(n for n in names if n not in via)

    # ------------------------------------------------------------------ colonnes
    # Une colonne est utilisée si : rapport, structure du modèle (relation,
    # sortByColumn, hiérarchie, DAX de table/colonne calculée ou rôle RLS),
    # ou DAX d'une mesure UTILISÉE. Référencée seulement par des mesures
    # inutilisées -> « used by unused ». Sinon -> aucune référence.
    columns = colinfo["columns"]
    rpt_entities: set = set()
    col_report = report_used_columns(set(columns), rpt_entities)
    rel_refs = relationship_refs()

    # ---- Power Query : quelle requête consomme quelle requête ? -------------
    # Une requête M peut en référencer une AUTRE (fusion, ajout, jointure). La
    # table consommée reste vivante même si aucun visuel ne la touche, et ses
    # colonnes ne se retirent pas à l'aveugle : le consommateur peut s'appuyer
    # dessus (clé de jointure, colonne développée). C'est ce que ChopChop
    # ratait — supprimer la table cassait l'actualisation.
    m_src = colinfo["m_source"]
    q_refs = {q: m_query_refs(src) for q, src in m_src.items()}
    query_consumers: dict = {}
    for T in colinfo["table_file"]:
        tl = T.lower()
        for q in sorted(q_refs):
            if q != T and tl in q_refs[q]:
                query_consumers.setdefault(T, []).append(q)
    rel_low = {(t.lower(), c.lower()) for t, c in rel_refs}
    sort_low = {(t.lower(), c.lower()) for t, c in colinfo["sort_refs"]}
    group_low = {(t.lower(), c.lower()) for t, c in colinfo["group_refs"]}
    hier_low = {(t.lower(), c.lower()) for t, c in colinfo["hier_refs"]}

    col_via: dict = {}
    col_struct: dict = {}
    col_meas_refs: dict = {}
    disp = {key: f"'{key[0]}'[{key[1]}]" for key in columns}
    part_mode = colinfo["partition_mode"]

    def column_category(info: dict) -> str:
        """Comment supprimer cette colonne (cf. ChopChop) :
        - 'calc'       : colonne calculée (« column X = <DAX> ») -> bloc TMDL ;
        - 'import'     : colonne d'une table importée (partition = m) -> bloc
                         TMDL + étape Table.RemoveColumns dans la requête M ;
        - 'structural' : colonne d'une table calculée (paramètre de champ,
                         sortie DAX) -> non supprimable automatiquement."""
        if info.get("calculated"):
            return "calc"
        if part_mode.get(info["table"]) == "m":
            return "import"
        return "structural"

    for (t, c), info in columns.items():
        key = (t, c)
        klow = (t.lower(), c.lower())
        qre = _qualified_res(t, c)
        bare = "[" + c.lower().replace("]", "]]") + "]"
        hits: list = []

        if klow in rel_low:
            hits.append(("relation", "relationships.tmdl"))
        if klow in sort_low:
            hits.append(("tri (sortByColumn)", f"'{t}'"))
        if klow in group_low:
            hits.append(("paramètre de champ (groupByColumn)", f"'{t}'"))
        if klow in hier_low:
            hits.append(("hiérarchie", f"'{t}'"))
        # DAX qualifié dans les blocs hors mesures (tables/colonnes calculées,
        # rôles...) + réf non qualifiée dans les blocs de SA table
        for b in other_blocks:
            if qre.search(b["text"]) or (b.get("table") == t and bare in b["text"]):
                hits.append((b["kind"], b["label"]))
        # extendedProperties / annotations de SA table qui citent son nom en
        # JSON ("Property": "X Fields") : la mécanique des paramètres de champ
        quoted = '"' + c.lower() + '"'
        if quoted in colinfo["prop_text"].get(t, ""):
            hits.append(("propriétés (paramètre de champ)", f"'{t}'"))
        # POWER QUERY : seule une AUTRE requête protège la colonne — et dès
        # qu'une autre requête consomme celle de cette table (fusion, ajout,
        # jointure), TOUTES ses colonnes sont protégées.
        # On ne cherchait autrefois que les colonnes CITÉES par le
        # consommateur (clé de jointure, liste d'expansion). Mais trois formes
        # courantes font traverser chaque colonne sans en nommer aucune :
        # Table.Join (jointure à plat), Table.Combine (ajout) et une
        # expansion construite par Table.ColumnNames. La colonne passait pour
        # inutilisée, son retrait ajoutait un Table.RemoveColumns à SA
        # requête, et le consommateur perdait la colonne à l'actualisation
        # suivante. Lire le M pour décider ce qui traverse vraiment n'est pas
        # sûr ; garder toute la table l'est, et c'est la règle de ce fichier :
        # un faux « utilisée » plutôt qu'un faux « inutilisée ».
        # Une mention à l'intérieur de SA PROPRE requête (typage, renommage,
        # calcul d'une autre colonne) n'est toujours PAS un motif : ChopChop
        # ajoute son Table.RemoveColumns en toute FIN de requête, donc toutes
        # les étapes précédentes continuent de fonctionner.
        consommateurs = query_consumers.get(t, [])
        if consommateurs:
            hits.append(("Power Query (table consommée par « "
                         + ", ".join(consommateurs) + " »)",
                         f"'{consommateurs[0]}'"))
        # filet conservateur : réf [Col] quelque part dans le .tmdl de sa
        # table hors mesures (M de partition, annotations...) — mieux vaut un
        # faux « utilisée » qu'un faux « inutilisée »
        if not hits:
            ttext = colinfo["table_text"].get(t, "")
            if colinfo["partition_mode"].get(t) == "m":
                # la requête M de la table ne compte pas (même raison que
                # ci-dessus) — sinon un simple « Type modifié » suffirait à
                # protéger chaque colonne importée
                ttext = ttext.replace(m_src.get(t, "").lower(), " ")
            in_measures = any(m["table"] == t and bare in m["block"] for m in measures.values())
            if bare in ttext and not in_measures:
                hits.append(("propriétés de la table", f"'{t}'"))

        if hits:
            col_struct[key] = hits

        # mesures qui la référencent (qualifié partout, ou non qualifié dans
        # les mesures de SA table)
        mrefs = sorted(
            n for n, m in measures.items()
            if qre.search(m["block"]) or (m["table"] == t and bare in m["block"])
        )
        if mrefs:
            col_meas_refs[key] = mrefs

    unused_columns: list = []
    column_chained: list = []
    for key in sorted(columns, key=lambda k: (k[0].lower(), k[1].lower())):
        d = disp[key]
        if key in col_report:
            col_via[d] = "rapport"
        elif key in col_struct:
            k0, l0 = col_struct[key][0]
            col_via[d] = f"modèle : {k0} {l0}"
        else:
            used_by = [m for m in col_meas_refs.get(key, []) if m in via]
            if used_by:
                col_via[d] = f"mesure [{used_by[0]}]"
            elif col_meas_refs.get(key):
                column_chained.append(d)   # seulement des mesures inutilisées
            else:
                unused_columns.append(d)   # aucune référence

    # ------------------------------------------------------ tables mortes
    # Une table est ENTIÈREMENT inutilisée si RIEN d'EXTERNE ne s'appuie
    # dessus : aucune mesure utilisée dedans, aucune relation, aucune de ses
    # colonnes référencée par le rapport ou par un objet utilisé HORS de la
    # table. Les auto-références internes des paramètres de champ
    # (sortByColumn / groupByColumn / propriétés sur SA propre table :
    # label == "'T'") ne comptent pas — c'est ce qui permet de repérer une
    # variante de paramètre que plus aucun visuel n'utilise. Supprimable en
    # entier (fichier .tmdl + réf model.tmdl ; la table morte n'a par
    # définition aucune relation à nettoyer).
    part_mode = colinfo["partition_mode"]
    tbl_of_measure = {n: m["table"] for n, m in measures.items()}
    all_tables = set(part_mode) | {t for (t, _c) in columns}
    # DAX débarrassé de ses chaînes et de ses crochets : y chercher un nom de
    # table repère les usages de la table ENTIÈRE (COUNTROWS(T), ALL(T),
    # SUMMARIZE(T, …)) qu'aucune référence de colonne ne trahit
    ext_dax = [(b.get("table"), strip_dax_noise(b["text"])) for b in other_blocks]
    meas_dax = {n: strip_dax_noise(measures[n]["block"]) for n in via}
    dead_tables: list = []
    dead_table_info: dict = {}
    spared_tables: dict = {}
    for T in sorted(all_tables, key=str.lower):
        if any(tbl_of_measure.get(n) == T for n in via):
            continue                                   # mesure utilisée dedans
        if any(t == T for (t, _c) in rel_refs):
            continue                                   # relation
        # Consommée par une AUTRE requête M (fusion/ajout/jointure) : vivante,
        # et on retient TOUJOURS la raison — c'est le cas qui cassait
        # l'actualisation, il doit pouvoir s'expliquer même quand la protection
        # par colonne l'aurait de toute façon sauvée.
        if query_consumers.get(T):
            spared_tables[T] = ("consommée par la requête Power Query : "
                                + ", ".join(query_consumers[T]))
            continue
        live = False
        for (t, c) in columns:
            if t != T:
                continue
            if (t, c) in col_report:                   # rapport
                live = True; break
            if any(m in via for m in col_meas_refs.get((t, c), [])):
                live = True; break                     # mesure utilisée externe
            for _kind, label in col_struct.get((t, c), []):
                if label not in (f"'{T}'", "relationships.tmdl"):
                    live = True; break                 # objet d'une AUTRE table
            if live:
                break
        if live:
            continue
        # --- gardes finales : les usages qu'aucune COLONNE ne trahit ---------
        # (heuristiques plus larges : on ne les consigne que si elles changent
        # vraiment l'issue, sinon la liste des épargnées serait du bruit)
        if T.lower() in rpt_entities:
            spared_tables[T] = "citée par une requête du rapport"
            continue
        tre = _table_re(T)
        ext = next((tb for tb, txt in ext_dax if tb != T and tre.search(txt)), None)
        if ext:
            spared_tables[T] = f"référencée en DAX par '{ext}'"
            continue
        mref = next((n for n in meas_dax if tre.search(meas_dax[n])), None)
        if mref:
            spared_tables[T] = f"référencée en DAX par la mesure [{mref}]"
            continue
        n_cols = sum(1 for (t, _c) in columns if t == T)
        n_meas = sum(1 for m in measures.values() if m["table"] == T)
        dead_tables.append(T)
        dead_table_info[T] = {
            "file": colinfo["table_file"].get(T),
            "mode": part_mode.get(T, "?"),
            "n_columns": n_cols,
            "n_measures": n_meas,
        }

    return {
        "report_path": str(REPORT_DIR),
        "measures": measures,
        "via": via,
        "unused": unused,
        "referencers": referencers,
        "report_refs": report_refs,
        "struct_refs": struct_refs,
        # ---- colonnes ----
        "columns": {disp[k]: {**v, "category": column_category(v)}
                    for k, v in columns.items()},
        "column_via": col_via,
        "unused_columns": unused_columns,
        "column_chained": column_chained,
        "column_referencers": {disp[k]: v for k, v in col_meas_refs.items()},
        "column_report_refs": {disp[k]: v for k, v in col_report.items()},
        "column_struct_refs": {disp[k]: v for k, v in col_struct.items()},
        # ---- tables entièrement mortes ----
        "dead_tables": dead_tables,
        "dead_table_info": dead_table_info,
        # tables sans usage visible mais ÉPARGNÉES (table -> pourquoi) :
        # dépendance Power Query, requête du rapport, DAX sur la table entière
        "spared_tables": spared_tables,
        # table -> requêtes M qui la consomment (fusion/ajout/jointure)
        "query_consumers": query_consumers,
    }


RCOLS_STEP = 'Colonnes retirées (ChopChop)'   # nom de l'étape M ajoutée


def _m_str(name: str) -> str:
    """Chaîne M entre guillemets (" -> "")."""
    return '"' + name.replace('"', '""') + '"'


def add_remove_columns_step(text: str, colnames) -> tuple[str, bool]:
    """Ajoute (ou complète) une étape `Table.RemoveColumns` en toute fin de la
    requête M contenue dans `text` (le bloc `partition X = m`), pour retirer
    `colnames` de la sortie. Fonction PURE : renvoie (nouveau_texte, ok).

    - étape ChopChop déjà présente -> fusionne les noms dans sa liste (dédup,
      ordre stable) ;
    - sinon -> insère l'étape juste avant `in`, met une virgule sur l'ancienne
      dernière étape, et repointe `in` vers la nouvelle étape ;
    - `ok=False` (texte inchangé) si la requête n'a pas de `let … in <étape>`
      reconnaissable (source DAX d'une table calculée, M exotique...).
    Idempotent : re-passer les mêmes colonnes ne change rien."""
    colnames = [c for c in colnames if c]
    if not colnames:
        return text, True

    # queue de la requête : `in` puis l'étape de retour (indent capturé)
    tail = re.search(
        r"\n(?P<ind>\t+)in\n(?P=ind)    (?P<ret>#\"(?:[^\"]|\"\")+\"|[A-Za-z_]\w*)"
        r"(?P<after>\s*?)(?=\n\t\t*annotation|\n\t\t*changedProperty|\n\t[a-z]|\Z)",
        text)
    if not tail:
        return text, False
    ind = tail.group("ind")

    # -- étape ChopChop déjà là : fusionner dans sa liste { ... } --------------
    step_ref = '#"' + RCOLS_STEP + '"'
    existing = re.search(
        re.escape(ind) + "    " + re.escape(step_ref)
        + r" = Table\.RemoveColumns\([^,]+,\s*\{(?P<cols>[^}]*)\}"
        + r"(?:\s*,\s*MissingField\.\w+)?\)",
        text)
    if existing:
        current = re.findall(r'"((?:[^"]|"")*)"', existing.group("cols"))
        merged = list(current)
        for c in colnames:
            if c not in merged:
                merged.append(c)
        if merged == current:
            return text, True  # rien de neuf
        new_list = ", ".join(_m_str(c) for c in merged)
        lo, hi = existing.span("cols")
        return text[:lo] + new_list + text[hi:], True

    # -- pas d'étape ChopChop : en créer une en fin de requête ----------------
    ret = tail.group("ret")
    # virgule sur la dernière ligne non vide avant `in` (fin de l'ex-dernière
    # étape, quelle que soit sa longueur)
    before = text[: tail.start()]
    m_last = re.search(r"(?s)(.*\S)(\s*)\Z", before)
    if not m_last:
        return text, False
    comma_pos = m_last.end(1)
    # MissingField.Ignore : si le nom n'existe plus dans la sortie finale
    # (colonne renommée en cours de requête, ou déjà retirée par une étape
    # « Colonnes supprimées » antérieure), Table.RemoveColumns lèverait
    # « La colonne X est introuvable » et casserait l'actualisation.
    new_step = (",\n" + ind + "    " + step_ref + " = Table.RemoveColumns("
                + ret + ", {" + ", ".join(_m_str(c) for c in colnames)
                + "}, MissingField.Ignore)")
    # texte = <avant, sans le \n final> + virgule+étape + queue repointée
    new_tail = "\n" + ind + "in\n" + ind + "    " + step_ref + tail.group("after")
    return before[:comma_pos] + new_step + new_tail + text[tail.end():], True


def _tmdl_name_variants(table: str) -> list[str]:
    """Écritures possibles d'un nom de table en TMDL : nu si identifiant simple,
    sinon quoté (apostrophes doublées). On accepte les deux à la lecture."""
    quoted = "'" + table.replace("'", "''") + "'"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table):
        return [table, quoted]
    return [quoted]


def remove_table_ref(model_text: str, table: str) -> tuple[str, bool]:
    """Retire la ligne « ref table <T> » de model.tmdl (fonction pure).
    Renvoie (texte, ok) ; ok=False si la référence est absente."""
    for variant in _tmdl_name_variants(table):
        pat = re.compile(r"^ref table " + re.escape(variant) + r"[ \t]*\r?\n?",
                         re.M)
        new, n = pat.subn("", model_text, count=1)
        if n:
            return new, True
    return model_text, False


def delete_objects(result: dict, measure_names=(), column_keys=(),
                   table_names=(), *,
                   backup_root: Path | None = None, log=None) -> dict:
    """Supprime des mesures, des colonnes ET des tables entières des fichiers
    TMDL, en un passage par fichier avec un backup horodaté
    commun.

    - tables (table_names) : suppression du fichier `<table>.tmdl` ENTIER +
      retrait de la ligne `ref table` dans model.tmdl (la table morte n'a par
      définition aucune relation à nettoyer). Les mesures/colonnes cochées qui
      vivent dans une table supprimée sont ignorées (elles partent avec) ;
    - mesures : retrait du bloc `measure` ;
    - colonnes 'calc' : retrait du bloc `column` ;
    - colonnes 'import' : retrait du bloc `column` + étape Table.RemoveColumns
      dans la requête M (nom M = source_column) ;
    - colonnes 'structural' : IGNORÉES (non supprimables ici) -> `skipped`.

    Les blocs sont re-localisés à frais sur le texte courant (pas d'offset
    hérité), effacés du bas vers le haut. Retourne un rapport détaillé.
    `result` = sortie d'analyze() (columns/measures/dead_table_info)."""
    if backup_root is None:
        backup_root = BACKUP_ROOT
    log = log or (lambda *_: None)
    columns = result["columns"]
    measures = result["measures"]
    dead_info = result.get("dead_table_info", {})

    # session de sauvegarde : copies horodatées + manifeste (chemin d'origine
    # de chaque fichier) — c'est lui qui rend la restauration mécanique
    session = br.BackupSession(backup_root, "ChopChop", PBIP_DIR)
    backup_dir = session.dir
    report = {"files": [], "measures_deleted": [], "columns_deleted": [],
              "tables_deleted": [], "tables_skipped": [], "m_edits": {},
              "m_skipped": [], "skipped": [], "backup_dir": str(backup_dir)}

    # ---- tables entières d'abord ------------------------------------------
    # filet : une table consommée par une AUTRE requête M n'est jamais
    # supprimable (son .tmdl porte la requête — la retirer casse le
    # consommateur). L'UI ne les propose pas, mais un appel direct le pourrait.
    consumers = result.get("query_consumers", {})
    drop_tables = set()
    for T in table_names:
        if consumers.get(T):
            report["tables_skipped"].append(
                f"{T} (consommée par {', '.join(consumers[T])})")
            log(f"⚠ table {T} conservée : sa requête M est consommée par "
                + ", ".join(consumers[T]))
            continue
        drop_tables.add(T)
    if drop_tables:
        model_tmdl = MODEL_DIR / "definition" / "model.tmdl"
        model_text = model_tmdl.read_text(encoding="utf-8") if model_tmdl.exists() else ""
        model_touched = False
        if model_text:
            session.save(model_tmdl)
        for T in sorted(drop_tables):
            info = dead_info.get(T) or {}
            fpath = info.get("file")
            if fpath and Path(fpath).exists():
                fp = Path(fpath)
                # action=supprimé : la restauration doit RECRÉER le fichier
                session.save(fp, action=br.DELETED)
                fp.unlink()
            model_text, ok = remove_table_ref(model_text, T)
            model_touched = model_touched or ok
            report["tables_deleted"].append(T)
            log(f"table {T} : fichier .tmdl supprimé"
                + (" + réf model.tmdl retirée" if ok else " (réf model.tmdl absente)"))
        if model_touched:
            model_tmdl.write_text(model_text, encoding="utf-8")
            report["files"].append("model.tmdl")

    # regrouper les cibles par fichier (en ignorant celles d'une table supprimée)
    by_file: dict[str, dict] = {}
    skipped: list[str] = []
    for n in measure_names:
        if measures[n]["table"] in drop_tables:
            continue
        f = measures[n]["file"]
        by_file.setdefault(f, {"measures": [], "columns": []})["measures"].append(n)
    for key in column_keys:
        info = columns[key]
        if info["table"] in drop_tables:
            continue                     # part avec la table
        if info["category"] == "structural":
            skipped.append(key)          # garde-fou : jamais touché
            continue
        by_file.setdefault(info["file"], {"measures": [], "columns": []})["columns"].append(key)
    report["skipped"] = skipped

    for file, tgt in sorted(by_file.items()):
        p = Path(file)
        text = p.read_text(encoding="utf-8")
        session.save(p)

        drop_meas = set(tgt["measures"])
        drop_cols = {columns[k]["name"] for k in tgt["columns"]}
        import_cols = [columns[k] for k in tgt["columns"]
                       if columns[k]["category"] == "import"]

        # (a) retrait des blocs measure/column, re-localisés du bas vers le haut
        members = list(MEMBER_RE.finditer(text))
        spans: list[tuple[int, int]] = []
        for i, m in enumerate(members):
            end = members[i + 1].start() if i + 1 < len(members) else len(text)
            block = text[m.start():end]
            if m.group(1) == "measure":
                nm = _first_group(MEASURE_NAME_RE.match(block))
                if nm in drop_meas:
                    spans.append((m.start(), end))
            elif m.group(1) == "column":
                nm = _first_group(COLUMN_NAME_RE.match(block))
                if nm in drop_cols:
                    spans.append((m.start(), end))
        for lo, hi in sorted(spans, reverse=True):
            text = text[:lo] + text[hi:]

        # (b) édition de la requête M pour les colonnes importées de ce fichier
        if import_cols:
            table = import_cols[0]["table"]
            mnames = [c.get("source_column") or c["name"] for c in import_cols]
            new_text, ok = add_remove_columns_step(text, mnames)
            if ok:
                text = new_text
                report["m_edits"][table] = mnames
            else:
                report["m_skipped"].append(table)
                log(f"⚠ {table} : requête M non reconnue, colonnes retirées du "
                    "modèle mais l'import continue (modifier Power Query à la main).")

        p.write_text(text, encoding="utf-8")
        report["files"].append(p.name)
        report["measures_deleted"].extend(sorted(drop_meas))
        report["columns_deleted"].extend(sorted(tgt["columns"]))
        log(f"{p.name} : {len(drop_meas)} mesure(s), {len(tgt['columns'])} colonne(s)"
            + (f", étape M ({len(import_cols)} col.)" if import_cols else ""))

    # manifeste : ce qui a été touché et d'où ça venait (cf. backup_restore)
    bits = []
    for n, label in ((len(report["tables_deleted"]), "table"),
                     (len(report["measures_deleted"]), "mesure"),
                     (len(report["columns_deleted"]), "colonne")):
        if n:
            bits.append(f"{n} {label}{'s' if n > 1 else ''}")
    session.close(", ".join(bits) or "aucune modification")

    return report


def delete_from_tmdl(measures: dict, names, backup_root: Path | None = None) -> list[str]:
    """Compat : supprime les blocs TMDL des mesures données.
    Délègue à delete_objects (mesures seules). Retourne les fichiers modifiés."""
    rep = delete_objects({"measures": measures, "columns": {}},
                         measure_names=list(names), backup_root=backup_root)
    return rep["files"]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    result = analyze()
    measures    = result["measures"]
    via         = result["via"]
    unused      = result["unused"]
    referencers = result["referencers"]
    names = set(measures)
    unused_set = set(unused)

    columns        = result["columns"]
    column_via     = result["column_via"]
    unused_cols    = result["unused_columns"]
    chained_cols   = result["column_chained"]
    col_refs       = result["column_referencers"]

    print(f"{len(names)} mesures et {len(columns)} colonnes dans le modèle.")

    # ---- CSV : audit complet (mesures + colonnes) -----------------------------
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Type", "Nom", "Table", "Statut", "Détail", "Générée par script TE", "Rapport analysé"])
        for n in sorted(names):
            if n in unused_set:
                refs = referencers[n]
                statut = "INUTILISÉE (used by unused)" if refs else "INUTILISÉE"
                detail = ("référencée seulement par : " + ", ".join(refs)) if refs else "aucune référence"
            else:
                statut, detail = "utilisée", via.get(n, "")
            w.writerow(["mesure", n, measures[n]["table"], statut, detail,
                        "oui" if measures[n]["generated"] else "non", result["report_path"]])
        for d in sorted(columns, key=str.lower):
            info = columns[d]
            if d in unused_cols:
                statut, detail = "INUTILISÉE", "aucune référence"
            elif d in chained_cols:
                statut = "INUTILISÉE (used by unused)"
                detail = "référencée seulement par : " + ", ".join(col_refs.get(d, []))
            else:
                statut, detail = "utilisée", column_via.get(d, "")
            w.writerow(["colonne", info["name"], info["table"], statut, detail, "", result["report_path"]])
    print(f"Audit écrit : {CSV_PATH.name}")

    # ---- console -------------------------------------------------------------
    if not unused:
        print("Aucune mesure inutilisée. ✨")
    else:
        direct  = [n for n in unused if not referencers[n]]
        chained = [n for n in unused if referencers[n]]
        print(f"\n{len(unused)} mesure(s) inutilisée(s) :")
        if direct:
            print(f"\n  Aucune référence ({len(direct)}) :")
            for n in direct:
                gen = "  [générée, voir measures_config.json]" if measures[n]["generated"] else ""
                print(f"    - {n} ({measures[n]['table']}){gen}")
        if chained:
            print(f"\n  Used by unused : référencées seulement par des inutilisées ({len(chained)}) :")
            for n in chained:
                gen = "  [générée]" if measures[n]["generated"] else ""
                print(f"    - {n}  <- {', '.join(referencers[n])}{gen}")

    # ---- colonnes -------------------------------------------------------------
    if not unused_cols and not chained_cols:
        print("\nAucune colonne inutilisée. ✨")
    else:
        print(f"\n{len(unused_cols) + len(chained_cols)} colonne(s) inutilisée(s) :")
        if unused_cols:
            print(f"\n  Aucune référence ({len(unused_cols)}) :")
            for d in unused_cols:
                print(f"    - {d}")
        if chained_cols:
            print(f"\n  Used by unused : référencées seulement par des mesures inutilisées ({len(chained_cols)}) :")
            for d in chained_cols:
                print(f"    - {d}  <- {', '.join(col_refs.get(d, []))}")


if __name__ == "__main__":
    main()
