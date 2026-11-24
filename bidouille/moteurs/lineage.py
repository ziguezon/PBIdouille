# -*- coding: utf-8 -*-
"""Les sources de données d'UN rapport PBIP — le lineage du projet ouvert.

Porté de « Autres outils\\scan_lineage.py » (qui parcourt tout un dossier et
écrit un CSV) : la même lecture, pour un seul projet, rendue en données que
la vue « Par source » de la Radiographie affiche.

Ce qui est lu :
  · le lien rapport -> modèle (<rapport>.Report\\definition.pbir) : modèle
    local (byPath) ou connexion live (byConnection) ;
  · chaque partition de chaque table du modèle : son mode (import,
    directQuery, directLake…) et les connecteurs M de son source
    (Sql.Database, Excel.Workbook, Odbc.DataSource…) avec leurs deux premiers
    arguments (serveur / base, chemin, URL…), et ce que la requête y prend :
    la feuille ou le tableau d'un classeur, la table d'une base, ou une
    requête SQL écrite à la main ;
  · expressions.tmdl : les requêtes partagées et les PARAMÈTRES M — un
    connecteur qui reçoit un paramètre (Sql.Database(Serveur, Base)) montre
    aussi sa valeur.

Lecture seule : aucun fichier du projet n'est modifié.
"""

from __future__ import annotations

import csv
import chemins
import json
import re
from pathlib import Path

# fonctions M considérées comme des sources de données (préfixes)
CONNECTOR_PREFIXES = (
    "Sql.", "Excel.", "Csv.", "Web.", "OData.", "SharePoint.", "Folder.",
    "File.", "AnalysisServices.", "PowerBI.", "PowerPlatform.", "Snowflake.",
    "Databricks.", "Odbc.", "OleDb.", "MySql.", "PostgreSQL.", "Oracle.",
    "Teradata.", "AzureStorage.", "AzureDataLake", "Lakehouse.", "Fabric.",
    "GoogleBigQuery.", "Dataverse", "Salesforce", "Parquet.", "Access.",
    "DeltaLake.", "Kusto", "AzureDataExplorer", "Json.", "Xml.", "Pdf.",
)

# le nom qu'on lit dans l'onglet, par préfixe de connecteur (le premier qui
# correspond gagne : « Sql.Database » avant « Sql. »)
FAMILLES = (
    ("Sql.", "SQL Server"), ("Excel.", "Excel"), ("Csv.", "CSV"),
    ("Web.", "Web"), ("OData.", "OData"), ("SharePoint.", "SharePoint"),
    ("Folder.", "Dossier"), ("File.", "Fichier"), ("Odbc.", "ODBC"),
    ("OleDb.", "OLE DB"), ("AnalysisServices.", "Analysis Services"),
    ("PowerBI.", "Power BI"), ("PowerPlatform.", "Power Platform"),
    ("Snowflake.", "Snowflake"), ("Databricks.", "Databricks"),
    ("MySql.", "MySQL"), ("PostgreSQL.", "PostgreSQL"), ("Oracle.", "Oracle"),
    ("Teradata.", "Teradata"), ("AzureStorage.", "Azure Storage"),
    ("AzureDataLake", "Azure Data Lake"), ("Lakehouse.", "Lakehouse"),
    ("Fabric.", "Fabric"), ("GoogleBigQuery.", "BigQuery"),
    ("Dataverse", "Dataverse"), ("Salesforce", "Salesforce"),
    ("Parquet.", "Parquet"), ("Access.", "Access"), ("DeltaLake.", "Delta Lake"),
    ("Kusto", "Kusto"), ("AzureDataExplorer", "Azure Data Explorer"),
    ("Json.", "JSON"), ("Xml.", "XML"), ("Pdf.", "PDF"),
)

CALL_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*\.[A-Z][A-Za-z0-9]*)\s*\(")
# les noms TMDL entre apostrophes échappent l'apostrophe en la doublant ('')
PARTITION_RE = re.compile(r"^\tpartition\s+(?:'((?:[^']|'')+)'|(\S+))", re.M)
TABLE_RE = re.compile(r"^table\s+(?:'((?:[^']|'')+)'|(\S+))", re.M)
MODE_RE = re.compile(r"\bmode:\s*(\w+)")
STRING_RE = re.compile(r'"(?:[^"]|"")*"')
# expression Serveur = "srv01" meta [IsParameterQuery=true, …]
PARAM_RE = re.compile(
    r"^expression\s+(?:'((?:[^']|'')+)'|(\S+))\s*=\s*(\"(?:[^\"]|\"\")*\"|[\w\.\-]+)"
    r"\s*meta\s*\[[^\]]*IsParameterQuery\s*=\s*true", re.M | re.I)
EXPRESSION_RE = re.compile(r"^expression\s+(?:'((?:[^']|'')+)'|(\S+))", re.M)

# genres de ligne
SOURCE, CALCULEE, AUCUN, LIVE = "source", "calculee", "aucun", "live"
EXPRESSIONS = "(expressions partagées)"

COLONNES_CSV = ["Table", "Partition", "Mode", "Connecteur", "Détail 1", "Détail 2", "Objet",
                "Tables lues"]

# Source{[Item="Table1",Kind="Table"]}[Data] : le pas de navigation qui choisit,
# dans la source, la feuille, le tableau ou la table qu'on lit
NAVIGATION_RE = re.compile(r"\{\s*\[([^\[\]]*)\]\s*\}")
CHAMP_NAV_RE = re.compile(r'(\w+)\s*=\s*"((?:[^"]|"")*)"')
# ce qui contient l'objet lu sans l'être : on le garde en préfixe (dbo.Ventes)
CONTENEURS = {"database", "schema", "catalog", "folder"}
# dans un classeur, le même nom peut être une feuille ou un tableau
GENRES_EXCEL = {"sheet": "feuille", "table": "tableau", "definedname": "plage nommée"}
REQUETE_SQL = "requête SQL"
SQL_ECRIT_RE = re.compile(r"\bValue\.NativeQuery\s*\(|\[[^\]]*\bQuery\s*=", re.I)

# Ce qu'une table calculée (DAX) ou une requête sans connecteur (M) lit dans le
# modèle. On efface d'abord ce qui ne peut pas nommer une table : les chaînes,
# les commentaires et les [colonnes] ou [mesures]. En DAX, 'Nom' est toujours
# une table ; en M, #"Nom" est une requête.
DAX_JETONS_RE = re.compile(r'"(?:[^"]|"")*"|--[^\n]*|//[^\n]*|/\*.*?\*/'
                           r"|'((?:[^']|'')+)'|\[(?:[^\]]|\]\])*\]", re.S)
M_JETONS_RE = re.compile(r'#"((?:[^"]|"")*)"|"(?:[^"]|"")*"|//[^\n]*|/\*.*?\*/'
                         r"|\[(?:[^\]]|\]\])*\]", re.S)
# un nom nu qui n'appelle pas une fonction : SELECTCOLUMNS ( dim_Date, …)
MOT_NU_RE = re.compile(r"(?<![\w.#])([A-Za-z_]\w*)(?![\w.])(?!\s*\()")
# en M, un nom nu qui APPELLE est une requête-fonction du modèle : fnCharger("x")
# lit fnCharger, et ce qu'elle lit. Les fonctions de M ont un point
# (Table.SelectRows) : elles ne passent pas, et seuls les noms connus comptent.
MOT_NU_M_RE = re.compile(r"(?<![\w.#])([A-Za-z_]\w*)(?![\w.])")
VAR_RE = re.compile(r"\bVAR\s+([A-Za-z_]\w*)", re.I)
SOURCE_DAX_RE = re.compile(r"^\t\tsource\s*=\s*(.*)$", re.M)


def _tmdl_name(match) -> str:
    """Nom capturé, apostrophes dé-échappées."""
    if match.group(1) is not None:
        return match.group(1).replace("''", "'")
    return match.group(2)


def clean_arg(arg) -> str:
    if not arg:
        return ""
    arg = arg.strip()
    if arg.startswith('#"') and arg.endswith('"'):
        return arg[2:-1].replace('""', '"')
    if arg.startswith('"') and arg.endswith('"'):
        arg = arg[1:-1].replace('""', '"')
    return arg


def famille(connecteur: str) -> str:
    """« Excel.Workbook » -> « Excel » : ce qu'on lit dans l'onglet."""
    for prefixe, nom in FAMILLES:
        if connecteur.startswith(prefixe):
            return nom
    return connecteur


def call_span(text: str, open_paren: int) -> int:
    """Position juste après la parenthèse fermante correspondante, en
    respectant les littéraux M ("" = guillemet échappé)."""
    depth = 0
    i = open_paren
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n:
                if text[i] == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        i += 2
                        continue
                    break
                i += 1
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def arguments(inside: str) -> list:
    """Les arguments de PREMIER niveau d'un appel M (le texte entre ses
    parenthèses), coupés aux virgules hors littéraux, parenthèses, crochets
    et accolades."""
    args, depth, debut, i, n = [], 0, 0, 0, len(inside)
    while i < n:
        ch = inside[i]
        if ch == '"':
            i += 1
            while i < n:
                if inside[i] == '"':
                    if i + 1 < n and inside[i + 1] == '"':
                        i += 2
                        continue
                    break
                i += 1
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(inside[debut:i].strip())
            debut = i + 1
        i += 1
    dernier = inside[debut:].strip()
    if dernier or args:
        args.append(dernier)
    return args


def valeur_arg(arg: str) -> str:
    """Ce qu'un argument dit de la source : un littéral -> sa valeur ; un
    nom (Serveur, #"Base") -> le nom (résolu plus tard s'il est un
    paramètre) ; un appel imbriqué (File.Contents("x.xlsx")) -> son premier
    littéral."""
    arg = (arg or "").strip()
    # options [Delimiter=";"…], listes, et null / true / false : pas une source
    if arg[:1] in "[{" or arg.lower() in ("null", "true", "false"):
        return ""
    if re.fullmatch(r'"(?:[^"]|"")*"', arg) or re.fullmatch(r'#"(?:[^"]|"")*"', arg):
        return clean_arg(arg)
    if re.fullmatch(r"[A-Za-z_][\w\.]*", arg):
        return arg
    for lit in STRING_RE.finditer(arg):
        if not (lit.start() > 0 and arg[lit.start() - 1] == "#"):
            return clean_arg(lit.group(0))
    return ""


def connectors_in(m_text: str) -> list:
    """[(connecteur, arg1, arg2)] pour chaque appel M ressemblant à une source.

    Les appels imbriqués dans un autre connecteur sont fusionnés : pour
    Excel.Workbook(File.Contents("x.xlsx")), on garde UNE ligne Excel.Workbook
    avec le chemin de File.Contents comme argument."""
    calls = []
    for call in CALL_RE.finditer(m_text):
        fn = call.group(1)
        if not fn.startswith(CONNECTOR_PREFIXES):
            continue
        open_paren = call.end() - 1
        calls.append((call.start(), open_paren, call_span(m_text, open_paren), fn))

    found = []
    for start, open_paren, end, fn in calls:
        # appel imbriqué dans un autre connecteur ? l'englobant s'en charge
        if any(s2 < start and end <= e2 for s2, _, e2, _ in calls if s2 != start):
            continue
        args = arguments(m_text[open_paren + 1:end - 1])
        a1 = valeur_arg(args[0]) if args else ""
        a2 = valeur_arg(args[1]) if len(args) > 1 else ""
        found.append((fn, a1, a2))
    return found


def objets_lus(m_text: str, connecteur: str) -> str:
    """Ce qu'une requête prend dans sa source : « Table1 (tableau) » pour un
    classeur, « dbo.Ventes » pour une base, « requête SQL » si la requête est
    écrite à la main. "" si la source est lue entière (un CSV) ou si la
    navigation ne se lit pas."""
    if connecteur.endswith(".Query") or SQL_ECRIT_RE.search(m_text):
        return REQUETE_SQL
    excel = connecteur.startswith("Excel.")
    prefixe, objets = [], []
    for nav in NAVIGATION_RE.finditer(m_text):
        champs = {k.lower(): v.replace('""', '"') for k, v in CHAMP_NAV_RE.findall(nav.group(1))}
        genre = champs.get("kind", "").lower()
        nom = champs.get("item") or champs.get("name") or ""
        if not nom:
            continue
        if genre in CONTENEURS:
            prefixe.append(nom)
            continue
        if champs.get("schema"):
            nom = f'{champs["schema"]}.{nom}'
        elif prefixe and not excel:
            nom = f"{prefixe[-1]}.{nom}"
        if excel and genre in GENRES_EXCEL:
            nom += f" ({GENRES_EXCEL[genre]})"
        if nom not in objets:
            objets.append(nom)
    return ", ".join(objets)


def tables_citees(texte: str, noms, langage: str = "dax", soi: str = "") -> list:
    """Les tables du modèle qu'une expression DAX ou M cite, dans l'ordre où
    elle les cite, sans doublon ni elle-même. `noms` : les tables (et, pour M,
    les requêtes partagées) qui existent ; un nom qui n'en est pas une, comme
    une variable ou une étape, est ignoré."""
    connus = {n.lower(): n for n in noms}
    vus: list = []                  # (position, nom)

    def garder(pos, nom):
        n = connus.get(nom.lower())
        if n and n != soi:
            vus.append((pos, n))

    def effacer(m):
        if m.group(1) is not None:
            garder(m.start(), m.group(1).replace("''" if langage == "dax" else '""',
                                                 "'" if langage == "dax" else '"'))
        # même longueur : les positions des noms nus restent celles du texte
        return " " * len(m.group(0))

    nu = (DAX_JETONS_RE if langage == "dax" else M_JETONS_RE).sub(effacer, texte)
    variables = {v.lower() for v in VAR_RE.findall(nu)} if langage == "dax" else set()
    for m in (MOT_NU_RE if langage == "dax" else MOT_NU_M_RE).finditer(nu):
        if m.group(1).lower() not in variables:
            garder(m.start(), m.group(1))
    return list(dict.fromkeys(n for _p, n in sorted(vus)))


def source_calculee(bloc: str) -> str:
    """Le DAX d'une partition calculée : ce qui suit « source = », sur la même
    ligne ou dans les lignes plus indentées qui suivent."""
    m = SOURCE_DAX_RE.search(bloc)
    if not m:
        return ""
    lignes = [m.group(1)]
    for ligne in bloc[m.end():].splitlines()[1:]:
        if ligne.strip() and not ligne.startswith("\t\t\t"):
            break
        lignes.append(ligne)
    return "\n".join(lignes)


COLONNE_CALC_RE = re.compile(r"^\tcolumn\s+(?:'((?:[^']|'')+)'|([^\s=]+))\s*=(.*)$", re.M)


def colonnes_calculees(model_dir) -> list:
    """Les colonnes calculées du modèle : [{"table", "nom", "dax", "lit"}], où
    `lit` donne les AUTRES tables que leur DAX cite (sa propre table, elle la
    lit forcément)."""
    tables = Path(model_dir) / "definition" / "tables"
    textes = []
    for tmdl in sorted(tables.glob("*.tmdl")) if tables.exists() else []:
        text = tmdl.read_text(encoding="utf-8")
        tm = TABLE_RE.search(text)
        textes.append((_tmdl_name(tm) if tm else tmdl.stem, text))
    noms = [t for t, _x in textes]
    out = []
    for table, text in textes:
        for m in COLONNE_CALC_RE.finditer(text):
            lignes = [m.group(3)]
            for ligne in text[m.end():].splitlines()[1:]:
                if ligne.strip() and not ligne.startswith("\t\t\t"):
                    break
                lignes.append(ligne)
            dax = "\n".join(lignes).strip()
            out.append({"table": table, "nom": _tmdl_name(m), "dax": dax,
                        "lit": tables_citees(dax, noms, "dax", table)})
    return out


def dependances(lignes) -> dict:
    """{table : [tables qu'elle lit directement dans le modèle]}."""
    dep: dict = {}
    for l in lignes:
        for t in l.get("lit") or []:
            dep.setdefault(nom_noeud(l), [])
            if t not in dep[nom_noeud(l)]:
                dep[nom_noeud(l)].append(t)
    return dep


def nom_noeud(l) -> str:
    """Le nom d'une ligne dans le lineage : sa table, ou sa requête partagée."""
    return l["partition"] if l["table"] == EXPRESSIONS else l["table"]


def _atteintes(depart, voisins: dict) -> list:
    """Tout ce qu'on atteint depuis `depart` en suivant `voisins`, sans boucler."""
    vus, pile = [], list(voisins.get(depart, []))
    while pile:
        n = pile.pop(0)
        if n != depart and n not in vus:
            vus.append(n)
            pile.extend(voisins.get(n, []))
    return vus


def reprises(lignes) -> dict:
    """{table : [tables calculées ou requêtes qui la lisent, directement ou
    par une autre]} : pourquoi une table qu'aucun visuel n'affiche reste utile."""
    lecteurs: dict = {}
    for t, lues in dependances(lignes).items():
        for x in lues:
            lecteurs.setdefault(x, []).append(t)
    return {t: _atteintes(t, lecteurs) for t in lecteurs}


def sources_au_bout(lignes) -> dict:
    """{table calculée : [tables à source externe qu'elle lit au bout du compte]}."""
    dep = dependances(lignes)
    externes = {nom_noeud(l) for l in lignes if l["genre"] == SOURCE}
    return {t: [x for x in _atteintes(t, dep) if x in externes] for t in dep}


def split_partitions(text: str) -> list:
    """[(nom, bloc)] des partitions d'un fichier table TMDL."""
    matches = list(PARTITION_RE.finditer(text))
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((_tmdl_name(m), text[m.start():end]))
    return out


def parametres_m(text: str) -> dict:
    """{nom : valeur} des paramètres M d'un expressions.tmdl."""
    return {_tmdl_name(m): clean_arg(m.group(3)) for m in PARAM_RE.finditer(text)}


def _resoudre(arg: str, params: dict) -> str:
    """Un argument qui nomme un paramètre M montre aussi sa valeur."""
    if arg and arg in params:
        return f"{arg} = {params[arg]}"
    return arg


def _ligne(table, partition, mode, connecteur, d1, d2, genre, objet="", lit=None) -> dict:
    return {"table": table, "partition": partition, "mode": mode,
            "connecteur": connecteur, "famille": famille(connecteur) if genre == SOURCE else "",
            "detail1": d1, "detail2": d2, "genre": genre, "objet": objet,
            "lit": list(lit or [])}


def _lignes_source(table, partition, mode, bloc, params, lit=None) -> list:
    """Une ligne par connecteur d'un bloc M. Ce que la requête y prend n'est
    attribué que s'il n'y a qu'UN connecteur : avec deux, on ne saurait pas
    dire à laquelle des deux sources va chaque pas de navigation."""
    conns = connectors_in(bloc)
    seul = len(conns) == 1
    return [_ligne(table, partition, mode, fn, _resoudre(a1, params), _resoudre(a2, params),
                   SOURCE, objets_lus(bloc, fn) if seul else "", lit)
            for fn, a1, a2 in conns]


def scan_model(model_dir: Path) -> tuple:
    """(lignes, paramètres) : les partitions et expressions partagées d'un modèle."""
    definition = Path(model_dir) / "definition"
    expressions = definition / "expressions.tmdl"
    texte_expr = expressions.read_text(encoding="utf-8") if expressions.exists() else ""
    params = parametres_m(texte_expr)

    tables = definition / "tables"
    textes = []
    for tmdl in sorted(tables.glob("*.tmdl")) if tables.exists() else []:
        text = tmdl.read_text(encoding="utf-8")
        tm = TABLE_RE.search(text)
        textes.append((_tmdl_name(tm) if tm else tmdl.stem, text))
    blocs = list(EXPRESSION_RE.finditer(texte_expr))
    requetes = [_tmdl_name(m) for m in blocs if _tmdl_name(m) not in params]
    # ce qu'une table peut citer : les autres tables, et en M les requêtes partagées
    noms_dax = [t for t, _x in textes]
    noms_m = noms_dax + requetes

    lignes = []
    for table, text in textes:
        for part_name, block in split_partitions(text):
            mode_m = MODE_RE.search(block)
            mode = mode_m.group(1) if mode_m else ""
            calc = "= calculated" in block.splitlines()[0]
            if calc:
                lit = tables_citees(source_calculee(block), noms_dax, "dax", table)
                lignes.append(_ligne(table, part_name, mode, "DAX (table calculée)",
                                     "", "", CALCULEE, lit=lit))
                continue
            # la ligne « partition X = m » nomme la table elle-même : on la saute
            lit = tables_citees(block.split("\n", 1)[-1], noms_m, "m", table)
            sources_bloc = _lignes_source(table, part_name, mode, block, params, lit)
            lignes.extend(sources_bloc or [_ligne(table, part_name, mode, "(aucun connecteur)",
                                                  "", "", AUCUN, lit=lit)])

    # les requêtes partagées (hors paramètres) : souvent là où vivent les serveurs
    for i, m in enumerate(blocs):
        nom = _tmdl_name(m)
        if nom in params:
            continue
        fin = blocs[i + 1].start() if i + 1 < len(blocs) else len(texte_expr)
        bloc = texte_expr[m.start():fin]
        lit = tables_citees(bloc.split("=", 1)[-1], noms_m, "m", nom)
        # une requête partagée sans connecteur (une étape qui en reprend une
        # autre, une fusion) reste une ligne : sans elle, la chaîne Brut ->
        # Propre -> Ventes se coupait à Propre
        lignes.extend(_lignes_source(EXPRESSIONS, nom, "", bloc, params, lit)
                      or [_ligne(EXPRESSIONS, nom, "", "(aucun connecteur)", "", "", AUCUN,
                                 lit=lit)])
    return lignes, params


def scan_projet(pbip) -> dict:
    """Le lineage d'un projet PBIP.

    {"modele": libellé, "modele_dir": Path | None, "live": chaîne de connexion
     ou "", "lignes": [ {table, partition, mode, connecteur, famille,
     detail1, detail2, genre, objet, lit} ], "parametres": {nom: valeur},
     "erreur": "" ou ce qui a empêché la lecture}"""
    pbip = Path(pbip)
    res = {"modele": "", "modele_dir": None, "live": "", "lignes": [],
           "parametres": {}, "erreur": ""}
    try:
        report_dir = chemins.dossier_rapport(pbip)
        model_dir, conn = chemins.modele_du_rapport(report_dir)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        res["erreur"] = str(exc)
        return res
    if model_dir is None:
        res["modele"] = conn.get("pbiModelDatabaseName") or "Connexion live"
        res["live"] = conn.get("connectionString", "")
        res["lignes"].append(_ligne("", "", "", "Connexion live", res["live"], "", LIVE))
        return res
    res["modele"] = model_dir.name
    if not model_dir.exists():
        res["erreur"] = f"modèle introuvable : {model_dir}"
        return res
    res["modele_dir"] = model_dir
    res["lignes"], res["parametres"] = scan_model(model_dir)
    return res


def sources(lignes) -> list:
    """Les sources DISTINCTES, dans l'ordre de première apparition :
    [{"connecteur", "famille", "detail1", "detail2", "lignes": [...]}]."""
    par_cle: dict = {}
    for ligne in lignes:
        if ligne["genre"] not in (SOURCE, LIVE):
            continue
        cle = (ligne["connecteur"], ligne["detail1"], ligne["detail2"])
        if cle not in par_cle:
            par_cle[cle] = {"connecteur": ligne["connecteur"], "famille": ligne["famille"],
                            "detail1": ligne["detail1"], "detail2": ligne["detail2"],
                            "lignes": []}
        par_cle[cle]["lignes"].append(ligne)
    return list(par_cle.values())


def chemin_local(detail: str):
    """Le chemin d'un fichier LOCAL (lettre de lecteur) cité en détail, sinon
    None. Les chemins réseau (\\\\serveur\\…) ne sont pas testés : un partage
    injoignable ferait attendre l'onglet de longues secondes."""
    if re.match(r"^[A-Za-z]:\\", detail or ""):
        return Path(detail)
    return None


def ecrire_csv(lignes, chemin) -> None:
    """Le lineage en CSV (séparateur ;, UTF-8 avec BOM : Excel l'ouvre tel quel)."""
    with Path(chemin).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(COLONNES_CSV)
        for ligne in lignes:
            w.writerow([ligne["table"], ligne["partition"], ligne["mode"],
                        ligne["connecteur"], ligne["detail1"], ligne["detail2"],
                        ligne.get("objet", ""), ", ".join(ligne.get("lit") or [])])
