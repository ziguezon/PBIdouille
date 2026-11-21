# -*- coding: utf-8 -*-
"""Les sources de données d'UN rapport PBIP — le lineage du projet ouvert.

Porté de « Autres outils\\scan_lineage.py » (qui parcourt tout un dossier et
écrit un CSV) : la même lecture, pour un seul projet, rendue en données que
l'onglet « Sources de données » affiche.

Ce qui est lu :
  · le lien rapport -> modèle (<rapport>.Report\\definition.pbir) : modèle
    local (byPath) ou connexion live (byConnection) ;
  · chaque partition de chaque table du modèle : son mode (import,
    directQuery, directLake…) et les connecteurs M de son source
    (Sql.Database, Excel.Workbook, Odbc.DataSource…) avec leurs deux premiers
    arguments (serveur / base, chemin, URL…) ;
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

COLONNES_CSV = ["Table", "Partition", "Mode", "Connecteur", "Détail 1", "Détail 2"]


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


def _ligne(table, partition, mode, connecteur, d1, d2, genre) -> dict:
    return {"table": table, "partition": partition, "mode": mode,
            "connecteur": connecteur, "famille": famille(connecteur) if genre == SOURCE else "",
            "detail1": d1, "detail2": d2, "genre": genre}


def scan_model(model_dir: Path) -> tuple:
    """(lignes, paramètres) : les partitions et expressions partagées d'un modèle."""
    definition = Path(model_dir) / "definition"
    expressions = definition / "expressions.tmdl"
    texte_expr = expressions.read_text(encoding="utf-8") if expressions.exists() else ""
    params = parametres_m(texte_expr)

    lignes = []
    tables = definition / "tables"
    for tmdl in sorted(tables.glob("*.tmdl")) if tables.exists() else []:
        text = tmdl.read_text(encoding="utf-8")
        tm = TABLE_RE.search(text)
        table = _tmdl_name(tm) if tm else tmdl.stem
        for part_name, block in split_partitions(text):
            mode_m = MODE_RE.search(block)
            mode = mode_m.group(1) if mode_m else ""
            conns = connectors_in(block)
            if conns:
                for fn, a1, a2 in conns:
                    lignes.append(_ligne(table, part_name, mode, fn,
                                         _resoudre(a1, params), _resoudre(a2, params), SOURCE))
            else:
                calc = "= calculated" in block.splitlines()[0]
                lignes.append(_ligne(table, part_name, mode,
                                     "DAX (table calculée)" if calc else "(aucun connecteur)",
                                     "", "", CALCULEE if calc else AUCUN))

    # les requêtes partagées (hors paramètres) : souvent là où vivent les serveurs
    blocs = list(EXPRESSION_RE.finditer(texte_expr))
    for i, m in enumerate(blocs):
        nom = _tmdl_name(m)
        if nom in params:
            continue
        fin = blocs[i + 1].start() if i + 1 < len(blocs) else len(texte_expr)
        for fn, a1, a2 in connectors_in(texte_expr[m.start():fin]):
            lignes.append(_ligne(EXPRESSIONS, nom, "", fn,
                                 _resoudre(a1, params), _resoudre(a2, params), SOURCE))
    return lignes, params


def scan_projet(pbip) -> dict:
    """Le lineage d'un projet PBIP.

    {"modele": libellé, "modele_dir": Path | None, "live": chaîne de connexion
     ou "", "lignes": [ {table, partition, mode, connecteur, famille,
     detail1, detail2, genre} ], "parametres": {nom: valeur},
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
                        ligne["connecteur"], ligne["detail1"], ligne["detail2"]])
