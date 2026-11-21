# -*- coding: utf-8 -*-
"""Générateur des variations de mesures : écrit directement les fichiers TMDL
du projet PBIP.

Découverte des mesures de base, variations, branches (variations de
variations), cibles, tables paramètre de champ, rang unique KPI-puis-calcul,
orphelines. Tout vient de measures_config.json.

⚠ Desktop peut rester ouvert, mais doit ensuite être fermé SANS enregistrer
puis rouvert (il ne relit les fichiers qu'à l'ouverture, et un enregistrement
écraserait nos modifications). Backup automatique sous
_backupsPBIdouille\\_tmdl_backups\\<horodatage>\\ avant chaque écriture.
Rouvrir le .pbip ensuite.

En ligne de commande :  py generate_measures.py   (config à côté du script)
En module (BIdouille)  : generate(model_dir, config, dry_run=..., log=...)

Sérialisation TMDL (calquée sur la sortie réelle de Desktop) :
  - description en lignes « /// » AVANT la mesure ;
  - DAX mono-ligne : « measure 'X' = <dax> » ; multi-ligne : « = » puis lignes
    à 3 tabs ; propriétés à 2 tabs (formatString brut NON quoté, displayFolder,
    lineageTag) ; « annotation MeasureVariation = <base>|<variation> » ;
  - lineageTags PRÉSERVÉS pour les mesures/tables existantes (uuid4 sinon) ;
  - table paramètre existante : seule l'expression `source =` est réécrite ;
    nouvelle table : fichier complet + « ref table » ajouté dans model.tmdl.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
import uuid
from pathlib import Path

# réutilise le découpage TMDL éprouvé de unused_measures (mêmes fichiers cibles)
sys.path.insert(0, str(Path(__file__).resolve().parent))   # moteurs\ voisins
from unused_measures import MEMBER_RE, MEASURE_NAME_RE, _first_group
import backup_restore as br                                # sauvegardes + manifeste
import xlsx_lecture as _xl                                 # relâche le classeur
import chemins                                             # où sont les projets

# ---------------------------------------------------------------------------
# lancement en ligne de commande seulement ; l'app passe toujours le sien
PBIP_DIR    = chemins.PROJETS
PROJECT     = chemins.PROJET_DEMO
CONFIG_PATH = PBIP_DIR / "measures_config.json"
# ---------------------------------------------------------------------------

ANNOTATION = "MeasureVariation"   # marque les mesures générées : "base|variation"

ANNOT_RE   = re.compile(r"^\t\tannotation " + ANNOTATION + r" = (.+)$", re.M)
FORMAT_RE  = re.compile(r"^\t\tformatString: (.*)$", re.M)
QUOTE = '"'
FOLDER_RE  = re.compile(r"^\t\tdisplayFolder: (.*)$", re.M)
LINEAGE_RE = re.compile(r"^\t\tlineageTag: (.*)$", re.M)
TABLE_LINEAGE_RE = re.compile(r"^\tlineageTag: (.*)$", re.M)
SOURCE_BLOCK_RE  = re.compile(r"(^\t\tsource =\n)((?:\t{3,}[^\n]*\n|\n(?=\t{3}))+)", re.M)


# Caractères que le tri culturel .NET (donc Power BI) IGNORE au premier niveau :
# « Nombre d'unités » se range entre « Nombre de jours » et « Nombre dz », comme
# si l'apostrophe n'existait pas. Un tri ordinal, lui, la traite comme un
# caractère de faible valeur et propulse le nom EN TÊTE de liste. Ensemble
# vérifié un par un contre [StringComparer]::CurrentCulture (l'apostrophe
# TYPOGRAPHIQUE U+2019, elle, est significative — ne pas l'ajouter ici).
_LIAISON = (
    "'"  # apostrophe droite
    "ʼ"  # apostrophe modificative
    "-"  # trait d'union
    "­"  # trait d'union conditionnel
    "–"  # tiret demi-cadratin
    "—"  # tiret cadratin
)
_IGNORABLES = str.maketrans("", "", _LIAISON)
# … et pour départager, elles pèsent PLUS que n'importe quelle lettre : à
# radical égal, « Nombre d'unites » se range APRÈS « Nombre dunites ».
_APRES_TOUT = {ord(c): "￿" for c in _LIAISON}


def sort_key_pbi(name):
    """Clé de tri alphabétique « à la Power BI ».

    Power BI trie ses colonnes texte avec le collation du modèle. Un tri
    ordinal Python en diverge de trois façons : il place toutes les majuscules
    avant les minuscules ('Weight' avant 'avg'), rejette les accentués après le
    Z ('Écart' après 'Zone'), et remonte les apostrophes en tête de liste
    ('Nombre d''unités' avant 'Nombre de jours'). L'ordre écrit dans la colonne
    Ordre du paramètre de champ ne correspondait alors plus à l'ordre affiché
    par le rapport.

    Reproduit donc les QUATRE niveaux du comparateur culturel .NET (celui
    avec lequel Power BI trie les noms), dans cet ordre de priorité (vérifié un à un contre StringComparer) :
    lettres nues, puis accents, puis casse (minuscule d'abord), puis
    ponctuation de liaison (qui pèse plus que toute lettre : à radical égal,
    « Nombre d'unites » se range APRÈS « Nombre dunites »).
    """
    decomp = unicodedata.normalize("NFKD", name)
    plat = "".join(c for c in decomp if not unicodedata.combining(c))
    return (
        plat.translate(_IGNORABLES).casefold(),     # 1. lettres nues
        decomp.translate(_IGNORABLES).casefold(),   # 2. accents
        tuple(c.isupper() for c in plat.translate(_IGNORABLES)),   # 3. casse
        plat.translate(_APRES_TOUT).casefold(),     # 4. ponctuation
    )


# ======================= helpers format ======================================

def positive_section(f):
    """Première section (valeurs positives) d'un format, sans signe initial.
    Gère les ';' échappés ou entre guillemets."""
    if not f:
        return f
    in_quote = False
    cut = len(f)
    i = 0
    while i < len(f):
        ch = f[i]
        if ch == '"':
            in_quote = not in_quote
        elif ch == "\\":
            i += 1
        elif ch == ";" and not in_quote:
            cut = i
            break
        i += 1
    s = f[:cut].strip()
    while s and s[0] in "+-":
        s = s[1:]
    return s


def has_scaling_percent(f) -> bool:
    """Le format contient-il un % actif (non échappé, hors guillemets) ?"""
    if not f:
        return False
    in_quote = False
    i = 0
    while i < len(f):
        ch = f[i]
        if ch == '"':
            in_quote = not in_quote
        elif ch == "\\":
            i += 1
        elif ch == "%" and not in_quote:
            return True
        i += 1
    return False


# Types de mesure reconnus d'après le formatString de la BASE. Sert à limiter
# une variation aux bases qui ont du sens : un « % du total » sur une base déjà
# en pourcentage donne un pourcentage de pourcentage — la mesure ne doit alors
# même pas être créée.
# Types d'une mesure, DÉDUITS de son formatString.
FORMAT_KINDS = ("nombre", "pourcentage", "devise")

_CURRENCY = "$\u20ac\u00a3\u00a5\u20a3\u20a4\u20bd\u20b9"


def format_kind(fmt) -> str:
    """Type d'une mesure d'après son formatString :

        « 0.0 % »        -> pourcentage
        « #,0.00 $ »     -> devise
        « #,0 », vide    -> nombre

    Une base sans formatString compte comme un nombre : c'est le cas le plus
    courant et le plus sûr (on n'exclut pas une mesure faute d'information)."""
    if has_scaling_percent(fmt):
        return "pourcentage"
    if any(c in (fmt or "") for c in _CURRENCY):
        return "devise"
    return "nombre"


def kind_allowed(tpl, base_fmt) -> bool:
    """La variation `tpl` accepte-t-elle une base de ce format ? Sans
    `appliesToFormats` (ou liste vide), tous les types passent — le filtre est
    donc facultatif et rétrocompatible."""
    kinds = tpl.get("appliesToFormats") if isinstance(tpl, dict) else None
    if not kinds:
        return True
    return format_kind(base_fmt) in kinds


def name_included(tpl, *noms) -> bool:
    """Rattrapage EXPLICITE : un nom contenant l'un de ces fragments est gardé
    quoi qu'il arrive — malgré l'exclusion par nom ET malgré le filtre de type.

    Sert au cas « j'exclus large, sauf celui-là » : écarter tout ce qui
    contient « average », mais garder « Average Steps » parce que la mesure est
    en réalité une somme malgré son nom."""
    motifs = tpl.get("includeNameContains") if isinstance(tpl, dict) else None
    if not motifs:
        return False
    return _name_matches(motifs, noms)


def base_retenue(tpl, base_fmt, *noms) -> bool:
    """La base passe-t-elle les filtres de la variation ? Ordre de priorité :

        1. inclusion explicite (includeNameContains)  -> gardée
        2. exclusion par nom   (excludeNameContains)  -> écartée
        3. filtre de type      (appliesToFormats)     -> selon le format

    L'inclusion est le dernier mot : c'est une décision nommée, prise KPI par
    KPI, alors que les deux autres filtres sont des règles larges."""
    if name_included(tpl, *noms):
        return True
    if name_excluded(tpl, *noms):
        return False
    return kind_allowed(tpl, base_fmt)


def name_excluded(tpl, *noms) -> bool:
    """L'un des `noms` contient-il un fragment de `excludeNameContains` ?

    Le formatString ne dit pas tout : un ratio en décimal (0,85) s'écrit comme
    un nombre. Plutôt qu'un attribut de plus à tenir à jour ailleurs, on
    s'appuie sur ce que le nom dit déjà — « Ratio ... », « ... / ... »,
    « Taux ... » — ou sur le nom complet d'un KPI à écarter.

    Comparaison insensible à la casse ET aux accents (« Durée » attrape
    « duree »). On teste le nom de la BASE et celui du KPI : exclure « Weight »
    écarte donc aussi « Weight cible »."""
    motifs = tpl.get("excludeNameContains") if isinstance(tpl, dict) else None
    if not motifs:
        return False
    return _name_matches(motifs, noms)


def _plat(s) -> str:
    """Minuscules sans accents, pour comparer « Durée » et « duree »."""
    d = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in d if not unicodedata.combining(c)).casefold()


def _name_matches(motifs, noms) -> bool:
    """L'un des `noms` contient-il l'un des `motifs` ? Insensible à la casse et
    aux accents ; les motifs vides sont ignorés."""
    cibles = [_plat(n) for n in noms if n]
    return any(_plat(m) in c
               for m in motifs if str(m).strip()
               for c in cibles)


def to_pts_format(core: str) -> str:
    """Format % -> format « points » : retire le % actif (et l'espace qui le
    précède, échappé ou non) et ajoute « pts » ÉCHAPPÉ (\\ \\p\\t\\s, forme
    Power BI — pas de guillemets). Le ×100 vient de {deltaScale}."""
    out: list = []
    in_quote = False
    i = 0
    while i < len(core):
        ch = core[i]
        if ch == '"':
            in_quote = not in_quote
            out.append(ch)
        elif ch == "\\":
            if i + 1 < len(core):
                out.append(ch)
                out.append(core[i + 1])
                i += 1
        elif ch == "%" and not in_quote:
            if len(out) >= 2 and out[-2] == "\\" and out[-1] == " ":
                del out[-2:]
            elif out and out[-1] == " ":
                del out[-1]
            # le % lui-même disparaît
        else:
            out.append(ch)
        i += 1
    # « pts » échappé (\ \p\t\s) et non entre guillemets : même forme que ce
    # que Power BI écrit lui-même — c'est le format des deltas de pourcentage,
    # et c'était le seul de tout le modèle à porter des guillemets
    return "".join(out) + escape_literal(" pts")


# Symboles d'un format « delta », par section (positif ; négatif ; zéro).
# Modifiables dans ⚙ Réglages (settings.deltaSymbols) : « + / − », des
# flèches « ▲ / ▼ », ou rien du tout.
DELTA_SYMBOLS = {"positive": "+", "negative": "-", "zero": ""}

# Format utilisé pour un delta dont la mesure de base n'a AUCUN formatString.
# Sans lui, le delta n'avait pas de format du tout — donc pas de signe, quels
# que soient les symboles choisis. "" = revenir à l'ancien « aucun format ».
DELTA_FALLBACK = "#,##0.##"


# Caractères qui s'affichent D'EUX-MÊMES dans un format Power BI/VBA : ni
# backslash, ni guillemets. « #,0.00 $ » s'écrit donc tel quel, avec une vraie
# espace. Tout le reste (lettres, flèches…) doit être échappé, sinon le moteur
# peut le lire comme un code de format.
SELF_DISPLAY = set(" +-$()")


def escape_literal(text) -> str:
    """Texte littéral dans un formatString, sous sa forme la plus SIMPLE :
    rien devant les caractères qui s'affichent d'eux-mêmes (cf. SELF_DISPLAY),
    un backslash devant les autres. « " " » -> « " " » (une espace nue),
    « pts » -> « \\p\\t\\s ». Jamais de guillemets."""
    return "".join(c if c in SELF_DISPLAY else "\\" + c for c in str(text))


def normalize_literals(fmt):
    """Ramène les littéraux d'un format à cette forme canonique : espace nue,
    pas de guillemets, backslash seulement là où il est nécessaire.

        0.0\\ %      -> 0.0 %        (l'espace n'a pas besoin d'échappement)
        #,0.00\\ $   -> #,0.00 $
        0.0" pts"   -> 0.0 \\p\\t\\s

    Un formatString hérité ou saisi à la main peut contenir l'une ou l'autre
    écriture ; tout ce qui est GÉNÉRÉ passe ici."""
    if not fmt or ('"' not in fmt and "\\" not in fmt):
        return fmt
    out: list = []
    i = 0
    in_quote = False
    while i < len(fmt):
        ch = fmt[i]
        if ch == '"':
            in_quote = not in_quote
            i += 1
            continue
        if in_quote:
            out.append(escape_literal(ch))
            i += 1
            continue
        if ch == "\\" and i + 1 < len(fmt):
            out.append(escape_literal(fmt[i + 1]))   # réduit \X à X si possible
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def format_symbol(sym) -> str:
    """Symbole littéral en tête d'une section. « + » et « - » passent tels
    quels ; tout le reste est ÉCHAPPÉ caractère par caractère pour ne pas être
    lu comme un code de format (# 0 . , % E…). Une flèche donne « \\▲#,##0 » —
    des backslashes, jamais de guillemets (cf. escape_literal)."""
    if not sym:
        return ""
    if sym in ("+", "-"):
        return sym
    return escape_literal(sym)


# « <<each ALLSELECTED({table})>> » : le fragment est répété une fois par table
# de la portée du KPI, séparé par des virgules. C'est LE jeton générique — la
# fonction DAX est écrite par toi, pas imposée par l'outil, donc ALL,
# ALLSELECTED, REMOVEFILTERS, ALLEXCEPT, CROSSFILTER… tout passe.
EACH_RE = re.compile(r"<<each\s+(.+?)>>", re.S)

# tables citées par un DAX : 'weight obs'[weight] ou Table[col] — jamais une
# simple référence de mesure [Weight] (rien devant le crochet).
TABLE_IN_DAX_RE = re.compile(
    r"'((?:[^']|'')+)'\s*\[|(?<![A-Za-z0-9_'\]])([A-Za-z_][A-Za-z0-9_]*)\s*\[")


def tables_from_dax(dax) -> list:
    """Tables citées par une expression DAX, dans l'ordre d'apparition et sans
    doublon : « CALCULATE(SUM('weight obs'[weight]), 'dim_Date'[x]=1) » donne
    ['weight obs', 'dim_Date']. Sert de portée par DÉFAUT quand rien n'est
    déclaré pour ce KPI."""
    if not dax:
        return []
    trouve = []
    for m in TABLE_IN_DAX_RE.finditer(dax):
        nom = (m.group(1) or m.group(2) or "").replace("''", "'")
        if nom and nom not in trouve:
            trouve.append(nom)
    return trouve


def expand_each(text, tables, sep=", "):
    """Développe les « <<each …>> » de `text` : le fragment est répété pour
    chaque table, avec {table} = la référence DAX ('steps') et {tableName} =
    le nom nu (steps). Sans table, le jeton est LAISSÉ en place — process()
    saute alors la mesure au lieu d'en écrire une bancale."""
    if not text or "<<each" not in text:
        return text
    if not tables:
        return text
    refs = [dax_table_ref(x) for x in tables]

    def repl(m):
        frag = m.group(1).strip()
        return sep.join(frag.replace("{table}", r)
                            .replace("{tableName}", str(n))
                        for r, n in zip(refs, tables))

    return EACH_RE.sub(repl, text)


def read_kpi_tables(spec, model_dir, default_xlsx, default_key, log=print) -> dict:
    """{KPI: [tables]} — la portée de chaque KPI, lue dans UNE COLONNE de
    l'Excel des indicateurs (TD_Indicateurs) :

        "kpiTables": { "column": "tables" }

    L'attribut vit ainsi avec LE RAPPORT. Le measures_config.json, lui, voyage
    d'un rapport à l'autre : y écrire des noms de KPI le rendrait faux dès sa
    réutilisation ailleurs — c'est pourquoi il ne retient que le nom de la
    colonne, et rien de spécifique au rapport.

    Une cellule liste les tables séparées par des virgules (ou des
    points-virgules) : « steps, dim_Date ». Cellule vide = ce KPI n'a pas de
    portée, donc pas la variation."""
    if not isinstance(spec, dict):
        return {}
    col = spec.get("column")
    if not col:
        return {}
    xlsx = Path(spec.get("xlsx") or default_xlsx)
    if not xlsx.is_absolute():
        xlsx = Path(model_dir).parent / xlsx
    try:
        brut = read_attribute_map(xlsx, spec.get("keyColumn") or default_key, col)
    except SystemExit as e:
        log(f"⚠ portée par KPI : {e}, colonne « {col} » ignorée.")
        return {}
    out = {}
    for kpi, val in brut.items():
        tables = [x.strip() for x in re.split(r"[;,]", str(val)) if x.strip()]
        if tables:
            out[kpi] = tables
    return out


def complete_kpi_tables(portees, existing, bases, actif, log=print) -> dict:
    """Complète les portées manquantes en LISANT le DAX de la mesure de base :
    « SUM('weight obs'[weight]) » donne la portée ['weight obs'].

    Ne touche jamais à ce que la colonne de TD_Indicateurs a déclaré — celle-ci
    reste la référence, la déduction ne sert qu'aux KPI qu'elle ne couvre pas.
    Ce que la déduction trouve est écrit au journal : elle voit TOUTES les
    tables citées, y compris une table de dates utilisée dans un filtre, ce qui
    n'est pas toujours la portée voulue."""
    if not actif:
        return portees
    out = dict(portees)
    deduits = []
    for b in bases:
        if b in out:
            continue
        tables = tables_from_dax((existing.get(b) or {}).get("dax"))
        if tables:
            out[b] = tables
            deduits.append(f"{b} -> {', '.join(tables)}")
    if deduits:
        log("Portée déduite du DAX (à vérifier) : " + " · ".join(deduits))
    return out


def dax_table_ref(name) -> str:
    """Référence DAX d'une table : toujours entre apostrophes — valide même
    pour un nom simple, et indispensable dès qu'il contient une espace."""
    return "'" + str(name).strip().replace("'", "''") + "'"


def kpi_table_tokens(tables) -> dict:
    """Jetons « portée » dérivés de la liste de tables d'UN KPI.

    Résout le cas « parfois une table, parfois plusieurs » : ALL() ne prend
    qu'une table à la fois, donc N tables donnent N filtres SÉPARÉS — la seule
    forme correcte dans un CALCULATE. Le DAX de la variation s'écrit une fois,
    pour 1 comme pour N tables :

        CALCULATE({baseRef}, <<allTables>>)
          1 table  -> CALCULATE([Weight], ALL('weight obs'))
          2 tables -> CALCULATE([Steps], ALL('steps'), ALL('dim_Date'))

    Liste vide -> aucun jeton : le <<...>> reste, et process() saute la mesure
    en le disant (un KPI sans portée déclarée n'a pas cette variation)."""
    refs = [dax_table_ref(x) for x in (tables or []) if str(x).strip()]
    if not refs:
        return {}
    return {
        "tables": ", ".join(refs),
        "allTables": ", ".join("ALL(" + r + ")" for r in refs),
        "removeFilters": ", ".join("REMOVEFILTERS(" + r + ")" for r in refs),
    }


def resolve_format(fmt, base_fmt, symbols=None, fallback=DELTA_FALLBACK):
    """Applique inherit / delta / text / {baseFormat} / littéral.

    « delta » construit un format à trois sections (positif;négatif;zéro) pour
    que le signe soit TOUJOURS visible : Power BI n'ajoute pas de « + » tout
    seul, et dans la section négative il n'ajoute même pas le « - » — chaque
    signe doit être écrit dans le format. Un format de base en % devient des
    « pts » (l'écart de deux pourcentages se lit en points)."""
    if not fmt or fmt == "inherit":
        return base_fmt
    if fmt == "text":
        return None            # mesure TEXTE : aucun format
    if fmt == "delta":
        sym = dict(DELTA_SYMBOLS)
        sym.update({k: v for k, v in (symbols or {}).items() if v is not None})
        core = positive_section(base_fmt)
        if not core:
            # base sans format : sans repli, le delta n'aurait aucun format et
            # donc aucun signe — c'est le cas qui « perdait » le + / −
            core = fallback or ""
            if not core:
                return None
        elif has_scaling_percent(core):
            core = to_pts_format(core)
        # littéraux sous leur forme la plus simple : espace nue, pas de
        # guillemets, backslash seulement si nécessaire (cf. normalize_literals)
        core = normalize_literals(core)
        return (format_symbol(sym["positive"]) + core + ";"
                + format_symbol(sym["negative"]) + core + ";"
                + format_symbol(sym["zero"]) + core)
    if "{baseFormat}" in fmt:
        return None if not base_fmt else fmt.replace("{baseFormat}", positive_section(base_fmt))
    return fmt


def dax_str(s) -> str:
    """Échappe une chaîne pour un littéral DAX entre guillemets."""
    return "" if s is None else str(s).replace('"', '""')


def bracket(name: str) -> str:
    """Référence DAX [Nom] (']' s'échappe en ']]')."""
    return "[" + name.replace("]", "]]") + "]"


def chaine_dax(texte) -> str:
    """Une chaîne DAX : entre guillemets, ceux du dedans doublés. C'est ce
    que rend {baseFormatString} — le format de la base, prêt pour FORMAT().

    Pourquoi un jeton : DAX ne sait pas lire le format d'une AUTRE mesure.
    SELECTEDMEASUREFORMATSTRING() ne vaut que dans un groupe de calcul ou le
    format dynamique de la mesure elle-même, et les fonctions INFO.* ne
    s'emploient pas dans une mesure. Le générateur, lui, le lit dans le
    TMDL : il l'écrit en dur, et une régénération le remet à jour."""
    return '"' + (texte or "").replace('"', '""') + '"'


# {branch} et UNE espace voisine — celle d'avant de préférence
_JETON_BRANCHE = re.compile(r" \{branch\}|\{branch\} ?")


def remplacer_branche(texte, branche):
    """{branch} : la branche courante (« YTD »). En Réel il n'y en a pas : le
    jeton s'efface AVEC l'espace qui le sépare de son voisin, pour qu'un nom
    composé reste juste des deux côtés —

        [{kpi} cible {branch}]  ->  [Weight cible]  /  [Weight cible YTD]
        [{kpi} {branch} PY]     ->  [Weight PY]     /  [Weight YTD PY]

    Sans ça, le Réel visait « Weight cible  » (une espace de trop) : une
    mesure qui n'existe pas."""
    if texte is None:
        return None
    if branche:
        return texte.replace("{branch}", branche)
    return _JETON_BRANCHE.sub("", texte)


def quote_tmdl(name: str) -> str:
    """Nom TMDL : quoté (apostrophes doublées) sauf identifiant simple."""
    if re.match(r"^[A-Za-z0-9_]+$", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def token_to_text(t):
    """dax/description du config : chaîne OU tableau de lignes -> chaîne."""
    if t is None:
        return None
    if isinstance(t, list):
        return "\n".join(str(x) for x in t)
    return str(t)


# ======================= parse de _mesures.tmdl ==============================

def split_members(text: str) -> list:
    """Découpe un .tmdl en [préambule + membres], en rattachant les lignes
    « /// description » de fin de chunk au membre SUIVANT (TMDL les place
    au-dessus de la déclaration qu'elles documentent)."""
    members = list(MEMBER_RE.finditer(text))
    if not members:
        return [[None, text]]
    chunks = [[None, text[: members[0].start()]]]
    for i, m in enumerate(members):
        end = members[i + 1].start() if i + 1 < len(members) else len(text)
        chunks.append([m.group(1), text[m.start():end]])

    for i in range(len(chunks) - 1):
        lines = chunks[i][1].split("\n")
        k = len(lines)
        while k > 0 and lines[k - 1].strip() == "":
            k -= 1
        d = k
        while d > 0 and lines[d - 1].startswith("\t///"):
            d -= 1
        if d < k:  # des /// juste avant la fin -> au chunk suivant
            moved = lines[d:k]
            chunks[i][1] = "\n".join(lines[:d] + lines[k:])
            chunks[i + 1][1] = "\n".join(moved) + "\n" + chunks[i + 1][1]
    return chunks


# TMDL entoure une valeur de guillemets dès qu'elle en contient elle-même, et
# DOUBLE ceux du dedans. Un format « secondes » saisi dans Desktop comme
#     #,0 "s"
# se retrouve donc sur le disque écrit ainsi (3 guillemets à la fin) :
#     formatString: "#,0 ""s"""
# Lire la ligne telle quelle prenait le quoting de TMDL pour une partie du
# format, avec deux dégâts dans les deltas :
#   · la valeur entière passait pour un littéral, donc un backslash devant
#     CHAQUE caractère (\#\,\0 \s) — le format ne formatait plus rien ;
#   · un « + » déjà en tête ne l'était plus (le guillemet l'était), donc le
#     signe du delta s'ajoutait par-dessus (++…).

def unquote_tmdl_value(valeur):
    """Valeur de propriété TMDL -> valeur RÉELLE (cf. le commentaire ci-dessus).

    Un guillemet SOLITAIRE à l'intérieur signe une valeur que TMDL n'a PAS
    quotée (les formats « pts » du modèle, que TMDL lit jusqu'au bout de
    ligne) : on n'y touche pas. Aucune devinette — l'inverse exact de
    `quote_tmdl_value`."""
    if not valeur or len(valeur) < 2:
        return valeur
    if not (valeur[0] == QUOTE and valeur[-1] == QUOTE):
        return valeur
    dedans = valeur[1:-1]
    out: list = []
    i = 0
    while i < len(dedans):
        if dedans[i] == QUOTE:
            if i + 1 < len(dedans) and dedans[i + 1] == QUOTE:
                out.append(QUOTE)
                i += 2
                continue
            return valeur              # pas du quoting TMDL : on laisse tel quel
        out.append(dedans[i])
        i += 1
    return "".join(out)


def quote_tmdl_value(valeur):
    """Inverse de `unquote_tmdl_value` : quote SEULEMENT quand TMDL en a besoin
    pour relire la même valeur, c'est-à-dire quand elle commence par un
    guillemet (sinon TMDL lit la ligne jusqu'au bout et les guillemets
    intérieurs se conservent tout seuls).

    Volontairement plus avare que Desktop, qui quote dès qu'il y a un
    guillemet : les formats « pts » déjà écrits dans les modèles restent
    identiques au caractère, donc aucune réécriture pour rien."""
    if not valeur:
        return valeur
    if valeur[0] != QUOTE and valeur == valeur.strip():
        return valeur
    return QUOTE + valeur.replace(QUOTE, QUOTE + QUOTE) + QUOTE


def expression_mesure(chunk_text: str, m_line) -> str | None:
    """L'expression DAX d'un chunk de mesure, ligne par ligne, désindentée :
    ce qui suit « = » sur la ligne de la mesure, puis les lignes du corps
    (trois tabulations) jusqu'à la 1re propriété. Un bloc ``` … ``` est lu
    jusqu'à sa clôture, lignes vides et propriétés apparentes comprises."""
    if not m_line or "=" not in m_line.group(0):
        return None
    tete = m_line.group(0).split("=", 1)[1].strip()
    lignes = [] if tete in ("", "```") else [tete]
    cloture = tete == "```"
    # m_line finit AVANT son saut de ligne : le 1er morceau est vide
    for ln in chunk_text[m_line.end():].splitlines()[1:]:
        if cloture:
            if ln.strip() == "```":
                break
        elif re.match(r"^\t\t[A-Za-z/]", ln):
            break
        lignes.append(ln[3:] if ln.startswith("\t\t\t") else ln.lstrip("\t"))
    while lignes and not lignes[-1].strip():
        lignes.pop()
    while lignes and not lignes[0].strip():
        lignes.pop(0)
    return "\n".join(lignes) or None


def measure_info(chunk_text: str) -> dict:
    """Extrait nom/annotation/format/dossier/lineage d'un chunk de mesure."""
    m_line = re.search(r"^\tmeasure .*$", chunk_text, re.M)
    name = _first_group(MEASURE_NAME_RE.match(m_line.group(0))) if m_line else None
    a = ANNOT_RE.search(chunk_text)
    f = FORMAT_RE.search(chunk_text)
    d = FOLDER_RE.search(chunk_text)
    lt = LINEAGE_RE.search(chunk_text)
    # expression : ce qui suit « = » sur la ligne, plus les lignes indentées
    # qui suivent jusqu'à la 1re propriété (formatString, annotation…). Sert à
    # DÉDUIRE les tables d'un KPI quand aucune portée n'est déclarée.
    dax = None
    if m_line and "=" in m_line.group(0):
        morceaux = [m_line.group(0).split("=", 1)[1].strip()]
        for ln in chunk_text[m_line.end():].splitlines():
            if re.match(r"^\t\t[A-Za-z/]", ln):      # propriété ou annotation
                break
            if ln.strip():
                morceaux.append(ln.strip())
        dax = " ".join(x for x in morceaux if x) or None
    return {
        # l'expression TELLE QU'ÉCRITE, sur ses lignes (l'arbre des mesures
        # la montre) ; « dax » ci-dessous l'aplatit pour la déduction
        "expression": expression_mesure(chunk_text, m_line),
        "name": name,
        "annotation": a.group(1).strip() if a else None,
        # dé-quoté : c'est LE format, pas la ligne TMDL qui le porte
        "format": unquote_tmdl_value(f.group(1)) if f else None,
        "folder": d.group(1) if d else None,
        "lineage": lt.group(1).strip() if lt else None,
        "dax": dax,
    }


# ======================= sérialisation TMDL ==================================

def measure_block(name, dax, fmt, folder, desc, tag, data_cat, lineage) -> str:
    """Bloc TMDL d'une mesure générée — même forme que la sortie Desktop/TE."""
    out: list = []
    if desc:
        for dl in str(desc).split("\n"):
            out.append("\t/// " + dl)
    qname = "'" + name.replace("'", "''") + "'"
    dax_lines = (dax or "").split("\n")
    if len(dax_lines) == 1:
        out.append("\tmeasure " + qname + " = " + dax_lines[0])
    else:
        out.append("\tmeasure " + qname + " =")
        for l in dax_lines:
            out.append("\t\t\t" + l)
    if fmt:
        # quoté seulement si TMDL ne saurait pas relire la valeur autrement
        out.append("\t\tformatString: " + quote_tmdl_value(fmt))
    if folder:
        out.append("\t\tdisplayFolder: " + folder)
    out.append("\t\tlineageTag: " + lineage)
    if data_cat:
        out.append("\t\tdataCategory: " + data_cat)
    out.append("")
    out.append("\t\tannotation " + ANNOTATION + " = " + tag)
    return "\n".join(out) + "\n"


def param_table_file(table, expr, kpi_col, calc_col, branch_col, lineages) -> str:
    """Fichier .tmdl complet d'une NOUVELLE table paramètre de champ (même
    structure que celles générées par Desktop/TE). `lineages` : dict nom ->
    lineageTag à préserver (vide pour une création)."""
    def tag(key):
        return lineages.get(key) or str(uuid.uuid4())

    disp, fields, ordre = table, table + " Fields", table + " Ordre"
    ind = "\t\t\t\t"
    body = "\n".join(ind + l for l in expr.split("\n"))
    return (
        "table " + quote_tmdl(table) + "\n"
        + "\tlineageTag: " + tag("__table__") + "\n\n"
        + "\tcolumn " + quote_tmdl(disp) + "\n"
        + "\t\tdataType: string\n"
        + "\t\tlineageTag: " + tag(disp) + "\n"
        + "\t\tsummarizeBy: none\n"
        + "\t\tsourceColumn: [Value1]\n"
        + "\t\tsortByColumn: " + quote_tmdl(ordre) + "\n\n"
        + "\t\trelatedColumnDetails\n"
        + "\t\t\tgroupByColumn: " + quote_tmdl(fields) + "\n\n"
        + "\tcolumn " + quote_tmdl(fields) + "\n"
        + "\t\tdataType: string\n"
        + "\t\tisHidden\n"
        + "\t\tlineageTag: " + tag(fields) + "\n"
        + "\t\tsummarizeBy: none\n"
        + "\t\tsourceColumn: [Value2]\n\n"
        + "\t\textendedProperty ParameterMetadata =\n"
        + "\t\t\t\t{\n"
        + '\t\t\t\t  "version": 3,\n'
        + '\t\t\t\t  "kind": 2\n'
        + "\t\t\t\t}\n\n"
        + "\tcolumn " + quote_tmdl(ordre) + "\n"
        + "\t\tdataType: string\n"
        + "\t\tisHidden\n"
        + "\t\tlineageTag: " + tag(ordre) + "\n"
        + "\t\tsummarizeBy: none\n"
        + "\t\tsourceColumn: [Value3]\n\n"
        + "\tcolumn " + quote_tmdl(kpi_col) + "\n"
        + "\t\tdataType: string\n"
        + "\t\tlineageTag: " + tag(kpi_col) + "\n"
        + "\t\tsummarizeBy: none\n"
        + "\t\tsourceColumn: [Value4]\n\n"
        + "\tcolumn " + quote_tmdl(calc_col) + "\n"
        + "\t\tdataType: string\n"
        + "\t\tlineageTag: " + tag(calc_col) + "\n"
        + "\t\tsummarizeBy: none\n"
        + "\t\tsourceColumn: [Value5]\n\n"
        + "\tcolumn " + quote_tmdl(branch_col) + "\n"
        + "\t\tdataType: string\n"
        + "\t\tlineageTag: " + tag(branch_col) + "\n"
        + "\t\tsummarizeBy: none\n"
        + "\t\tsourceColumn: [Value6]\n\n"
        + "\tpartition " + quote_tmdl(table) + " = calculated\n"
        + "\t\tmode: import\n"
        + "\t\tsource =\n"
        + body + "\n\n"
    )


# ---- les tables paramètre : UNE liste, chacune avec ses réglages -------------
# Autrefois trois familles figées (tableNames / tableNamesByKpi /
# tableNamesKpiBase) partageant les mêmes options : une table « par calcul »
# ne pouvait pas, par exemple, garder la base et une autre l'écarter. Chaque
# table porte maintenant ses propres réglages ; les trois anciennes listes se
# relisent comme les trois cas particuliers qu'elles étaient.
#
# Les filtres sont des EXCLUSIONS : un KPI, une variation ou une branche
# ajoutés plus tard entrent d'eux-mêmes dans chaque table, comme avant. Dans
# excludeBranches, "" désigne les rangées hors branche.
FP_TABLE_DEFAUT = {
    "rows": "calcul",          # chaque rangée affiche : "calcul" | "kpi"
    "baseRow": "calcul",       # (rows = calcul) la base affiche : "calcul" | "kpi"
    "kpiLabel": True,          # KPI affiché par son libellé (lookup), sinon le nom
    "includeBase": True,       # la rangée de la mesure de base
    "includeTargets": True,    # les rangées des cibles
    "excludeKpis": [],
    "excludeVariations": [],
    "excludeBranches": [],
}


def _fp_liste(v) -> list:
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if isinstance(x, (str, int, float))]


def fp_table_specs(fp) -> list:
    """Réglages normalisés de chaque table paramètre, dans l'ordre du config :
    [{name, rows, baseRow, kpiLabel, includeBase, includeTargets,
    excludeKpis, excludeVariations, excludeBranches}].

    `fieldParameter.tables` fait foi dès qu'il existe (une liste vide = aucune
    table). Sinon on relit l'ancien format : tableNames (par calcul),
    tableNamesKpiBase (base = libellé du KPI) et tableNamesByKpi (par KPI),
    avec l'includeBase et le byKpiUsesLabel communs d'alors. Un nom en double
    n'est gardé qu'une fois (le premier)."""
    if not isinstance(fp, dict) or not fp:
        return []
    commun_base = bool(fp.get("includeBase", True))
    commun_lbl = bool(fp.get("byKpiUsesLabel", True))
    brut: list = []
    if isinstance(fp.get("tables"), list):
        for t in fp["tables"]:
            brut.append({"name": t} if isinstance(t, str) else t)
    else:
        noms = fp.get("tableNames") or (
            [fp["tableName"]] if fp.get("tableName") else ["P_Indicateurs"])
        brut += [{"name": n} for n in _fp_liste(noms)]
        # l'ancienne table « base = libellé » faisait TOUJOURS le LOOKUPVALUE
        brut += [{"name": n, "baseRow": "kpi", "kpiLabel": True}
                 for n in _fp_liste(fp.get("tableNamesKpiBase"))]
        brut += [{"name": n, "rows": "kpi", "kpiLabel": commun_lbl}
                 for n in _fp_liste(fp.get("tableNamesByKpi"))]
    out, vus = [], set()
    for t in brut:
        if not isinstance(t, dict):
            continue
        nom = str(t.get("name") or "").strip()
        if not nom or nom.lower() in vus:
            continue
        vus.add(nom.lower())
        s = dict(FP_TABLE_DEFAUT, includeBase=commun_base, kpiLabel=commun_lbl)
        s.update({k: t[k] for k in FP_TABLE_DEFAUT if k in t})
        s["name"] = nom
        s["rows"] = "kpi" if s["rows"] == "kpi" else "calcul"
        s["baseRow"] = "kpi" if s["baseRow"] == "kpi" else "calcul"
        for k in ("kpiLabel", "includeBase", "includeTargets"):
            s[k] = bool(s[k])
        for k in ("excludeKpis", "excludeVariations", "excludeBranches"):
            s[k] = _fp_liste(s[k])
        out.append(s)
    return out


def fp_table_names(fp) -> list:
    """Noms des tables paramètre du config, dans l'ordre."""
    return [s["name"] for s in fp_table_specs(fp)]


def fp_spec_compacte(spec) -> dict:
    """La forme à ÉCRIRE dans le config : le nom, plus ce qui s'écarte des
    défauts — un config lisible, où chaque table dit en quoi elle diffère."""
    out = {"name": spec["name"]}
    for k, d in FP_TABLE_DEFAUT.items():
        v = spec.get(k, d)
        if v != d:
            out[k] = v
    return out


def fp_rows_pour(spec, rows) -> list:
    """Les rangées que garde UNE table. `rows` : la liste complète, chaque
    rangée [affichage, réf, rang, KPI, calcul, branche, variation | None,
    cible?, base?, clé de branche ("" = hors branche)]."""
    ex_k = set(spec["excludeKpis"])
    ex_v = set(spec["excludeVariations"])
    ex_b = set(spec["excludeBranches"])
    garde = []
    for r in rows:
        kpi, vid, cible, base, bcle = r[3], r[6], r[7], r[8], r[9]
        if kpi in ex_k or bcle in ex_b:
            continue
        if base and not spec["includeBase"]:
            continue
        if cible and not spec["includeTargets"]:
            continue
        if vid is not None and vid in ex_v:
            continue
        garde.append(r)
    return garde


# ======================= le générateur =======================================

def _fmt_attr(v) -> str:
    """Valeur de cellule Excel -> texte pour l'injecter BRUT dans le DAX
    (entier/float entier sans décimale ; booléen -> TRUE/FALSE)."""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


# Bloc UNIQUE décrivant l'Excel des indicateurs (TD_Indicateurs). Il était
# défini à deux endroits — ici pour les jetons <<…>>, et dans l'onglet Rapport
# pour les couleurs de matrice — avec des valeurs qui pouvaient diverger. Une
# seule source désormais : ce bloc du measures_config.json.
INDICATEURS_DEFAUT = {
    "path": "TD_Indicateurs.xlsx",
    "keyColumn": "mesure",
    "fillColumn": "couleur_fill",
    "textColumn": "couleur_text",
    # colonne d'ORDRE des KPI dans les tables paramètre. Vide = tri
    # alphabétique de Power BI (cf. kpi_ranks).
    "orderColumn": "",
}


# BIBLIOTHEQUE de variations : un fichier GLOBAL, hors projet, où l'on garde
# toutes les variations qu'on réutilise d'un rapport à l'autre. On y PIOCHE :
# la variation choisie est COPIÉE dans le measures_config.json du rapport, qui
# reste donc autonome — la génération ne lit jamais la bibliothèque.
#
# C'est l'inverse d'un catalogue partagé qu'on filtrerait par rapport : plus
# rien à cocher ni à retenir projet par projet, ce que le config du rapport
# contient est exactement ce qu'il génère.
BIBLIO_DEFAUT = "catalogue_variations.json"


def read_biblio(chemin) -> dict:
    """{variations, branches} de la bibliothèque. Fichier absent ou illisible
    = bibliothèque vide, jamais une erreur : elle est facultative."""
    if not chemin:
        return {"variations": {}, "branches": {}}
    p = Path(chemin)
    if not p.exists():
        return {"variations": {}, "branches": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"variations": {}, "branches": {}}
    if not isinstance(data, dict):
        return {"variations": {}, "branches": {}}
    return {"variations": data.get("variations") or {},
            "branches": data.get("branches") or {}}


def write_biblio(chemin, variations, branches=None) -> Path:
    """Écrit la bibliothèque (crée le dossier au besoin)."""
    p = Path(chemin)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"variations": variations,
                             "branches": branches or {}},
                            indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return p


def import_variations(config, biblio, ids, log=print) -> list:
    """Copie les variations `ids` de la bibliothèque dans `config` (modifié sur
    place). Retourne les ids réellement importés.

    Une variation qui sert de BRANCHE amène son entrée `branches`, sinon la 2e
    passe irait chercher une branche inexistante. Un id déjà présent dans le
    rapport est ÉCRASÉ par la version de la bibliothèque — importer, c'est
    demander celle-ci."""
    src_v = (biblio or {}).get("variations") or {}
    src_b = (biblio or {}).get("branches") or {}
    dst_v = config.setdefault("variations", {})
    faits = []
    for vid in ids:
        if vid not in src_v:
            log(f"⚠ « {vid} » absente de la bibliothèque, ignorée.")
            continue
        dst_v[vid] = json.loads(json.dumps(src_v[vid]))   # copie profonde
        faits.append(vid)
        if vid in src_b:
            config.setdefault("branches", {})[vid] = \
                json.loads(json.dumps(src_b[vid]))
    return faits


def export_variations(config, biblio, ids) -> list:
    """Sens inverse : publie des variations DU RAPPORT dans la bibliothèque
    (`biblio` modifié sur place), pour les réutiliser ailleurs."""
    src_v = config.get("variations") or {}
    src_b = config.get("branches") or {}
    dst_v = biblio.setdefault("variations", {})
    faits = []
    for vid in ids:
        if vid not in src_v:
            continue
        dst_v[vid] = json.loads(json.dumps(src_v[vid]))
        faits.append(vid)
        if vid in src_b:
            biblio.setdefault("branches", {})[vid] = \
                json.loads(json.dumps(src_b[vid]))
    return faits


def indicateurs_xlsx(config, project_dir=None) -> dict:
    """Définition résolue de l'Excel des indicateurs :
    {path (absolu si project_dir donné), keyColumn, fillColumn, textColumn}.

    `hardcodedAttributes.xlsx` / `.keyColumn` et `kpiTables.xlsx` / `.keyColumn`
    restent acceptés comme SURCHARGES locales (configs existants), mais le
    défaut vient d'ici."""
    spec = dict(INDICATEURS_DEFAUT)
    bloc = (config or {}).get("indicateursXlsx")
    if isinstance(bloc, dict):
        for k, v in bloc.items():
            if v:
                spec[k] = v
    # compat : un ancien config ne porte l'Excel que sous hardcodedAttributes
    hc = (config or {}).get("hardcodedAttributes") or {}
    if not (isinstance(bloc, dict) and bloc.get("path")) and hc.get("xlsx"):
        spec["path"] = hc["xlsx"]
    if not (isinstance(bloc, dict) and bloc.get("keyColumn")) and hc.get("keyColumn"):
        spec["keyColumn"] = hc["keyColumn"]
    if project_dir:
        p = Path(spec["path"])
        if not p.is_absolute():
            p = Path(project_dir) / p
        spec["path"] = str(p)
    return spec


# Cache des lignes d'Excel, PRÊTÉ par l'appelant le temps d'un generate()
# (cf. son argument cache_excel) — l'arbre des mesures se recalcule à chaque
# affichage et ne doit pas rouvrir le classeur à chaque fois. Clé : chemin,
# date et taille du fichier ; un os.stat ne tient pas le classeur, et un
# fichier enregistré depuis Excel change de clé, donc est relu. Sans cache
# prêté (la génération, les lignes de commande), chaque lecture va au disque.
_CACHE_LIGNES = None


def _lignes_excel(xlsx: Path) -> list:
    cache = _CACHE_LIGNES
    if cache is None:
        return _xl.lire_lignes(xlsx)      # referme le classeur quoi qu'il arrive
    st = xlsx.stat()
    chemin = str(xlsx.resolve())
    cle = (chemin, st.st_mtime_ns, st.st_size)
    if cle not in cache:
        for k in [k for k in cache if k[0] == chemin]:
            del cache[k]                  # l'ancienne version de ce fichier
        cache[cle] = _xl.lire_lignes(xlsx)
    return cache[cle]


def read_attribute_map(xlsx, key_col, attr_col) -> dict:
    """{ valeur_clé : valeur_attribut_formatée } depuis la 1re feuille de l'Excel
    (openpyxl puis pandas) — pour figer un attribut du KPI dans le DAX."""
    xlsx = Path(xlsx)
    if not xlsx.exists():
        raise SystemExit(f"Excel des attributs introuvable : {xlsx}")
    kl, al = key_col.lower(), attr_col.lower()
    out = {}
    try:
        rows = _lignes_excel(xlsx)
    except ImportError:
        rows = None
    if rows is not None:
        if not rows:
            return out
        header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
        if kl not in header or al not in header:
            raise SystemExit(f"Colonne '{key_col}' ou '{attr_col}' absente de {xlsx.name} "
                             f"(colonnes : {rows[0]}).")
        ki, ai = header.index(kl), header.index(al)
        for r in rows[1:]:
            if ki < len(r) and r[ki] is not None and str(r[ki]).strip() \
                    and ai < len(r) and r[ai] is not None:
                out[str(r[ki]).strip()] = _fmt_attr(r[ai])
        return out

    import pandas as pd                     # repli : pandas referme tout seul
    df = pd.read_excel(xlsx)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if kl not in df.columns or al not in df.columns:
        raise SystemExit(f"Colonne '{key_col}' ou '{attr_col}' absente : {list(df.columns)}")
    for _, r in df.iterrows():
        if pd.notna(r[kl]) and str(r[kl]).strip() and pd.notna(r[al]):
            out[str(r[kl]).strip()] = _fmt_attr(r[al])
    return out


# --------------------------------- ordre des KPI dans les tables paramètre

# KPI que la colonne d'ordre ne mentionne pas : rangé APRÈS ceux qu'elle
# mentionne. Devant, un KPI oublié se retrouverait en tête du slicer — la
# place la plus visible pour la seule ligne dont personne n'a décidé.
ORDRE_ABSENT = (2, 0.0, "")


def _cle_ordre(valeur):
    """Clé de tri d'une valeur de la colonne d'ordre.

    Un nombre est comparé COMME UN NOMBRE : sinon « 10 » se rangerait entre
    « 1 » et « 2 », la première déception de toute colonne d'ordre. Ce qui
    n'en est pas un se range après, alphabétiquement — une colonne à moitié
    remplie de texte reste ainsi déterministe au lieu de planter."""
    texte = str(valeur).strip()
    try:
        return (0, float(texte.replace(",", ".")), "")
    except ValueError:
        return (1, 0.0, texte.casefold())


def read_kpi_order(td, log=print) -> dict:
    """{KPI : valeur d'ordre} lue dans la colonne `orderColumn` de
    TD_Indicateurs. Pas de colonne configurée, ou illisible = {}, donc tri
    alphabétique : l'ordre est facultatif, il ne fait jamais échouer.

    L'ordre vit avec LE RAPPORT, comme la portée et les couleurs : le
    measures_config.json voyage d'un rapport à l'autre, et y inscrire une
    liste de KPI le rendrait faux dès sa réutilisation ailleurs. Le config ne
    retient donc que le NOM de la colonne."""
    col = (td or {}).get("orderColumn")
    if not col:
        return {}
    try:
        return read_attribute_map(td["path"], td["keyColumn"], col)
    except SystemExit as e:
        log(f"⚠ ordre des KPI : {e}, colonne « {col} » ignorée, "
            "tri alphabétique.")
        return {}


def kpi_ranks(bases, ordres, log=print) -> dict:
    """{KPI : rang} — ce qui atterrit dans la colonne Ordre des tables
    paramètre, et donc l'ordre affiché par le slicer (sortByColumn).

    Sans colonne d'ordre : le tri alphabétique de Power BI (`sort_key_pbi`),
    celui que le rapport appliquerait de lui-même. Avec : la colonne commande,
    et l'alphabétique ne sert plus qu'à départager deux ex æquo — deux KPI au
    même rang doivent tomber dans un ordre STABLE, sinon chaque génération
    réécrirait la table pour rien."""
    if not ordres:
        return {b: i for i, b in enumerate(sorted(bases, key=sort_key_pbi))}
    ordonnes = sorted(bases, key=lambda b: (_cle_ordre(ordres[b]) if b in ordres
                                            else ORDRE_ABSENT, sort_key_pbi(b)))
    sans = [b for b in bases if b not in ordres]
    if sans:
        log(f"⚠ ordre des KPI : {len(sans)} sans valeur dans la colonne "
            f"({', '.join(sorted(sans, key=sort_key_pbi))}), rangé(s) à la fin.")
    log("Ordre des KPI : " + " → ".join(ordonnes))
    return {b: i for i, b in enumerate(ordonnes)}


def match_kpi(name: str, bases_by_len) -> str | None:
    """Le KPI dont `name` est une déclinaison, par PLUS LONG préfixe d'abord
    (« Weight cible » -> « Weight »). None si aucun ne correspond.
    `bases_by_len` = les mesures de base triées par longueur décroissante."""
    for b in bases_by_len:
        if name == b or name.startswith(b + " "):
            return b
    return None


def folder_matches(mfolder, cfolder) -> bool:
    """Le displayFolder `mfolder` correspond-il au dossier de cibles `cfolder` ?
    Match si chemin complet identique OU si le dossier FEUILLE est le même — un
    dossier imbriqué (« _indicateurs\\_cibles ») matche donc la config
    « _cibles », sans avoir à écrire le chemin complet."""
    mf = (mfolder or "").strip().lower()
    cf = (cfolder or "").strip().lower()
    if not mf or not cf:
        return False
    return mf == cf or re.split(r"[\\/]", mf)[-1] == cf


def read_measures(model_dir, config) -> tuple:
    """(mesures, bases) d'après le TMDL : `mesures` = nom -> info (dossier,
    format, annotation…), `bases` = les mesures de BASE (non générées, dans
    sourceFolder) triées comme Power BI. Lecture seule."""
    settings = config.get("settings") or {}
    source_table = settings.get("sourceTable") or "_mesures"
    target_table = settings.get("targetTable") or source_table
    source_folder = settings.get("sourceFolder")
    src = Path(model_dir) / "definition" / "tables" / (target_table + ".tmdl")
    if not src.exists():
        return {}, []
    existing = {}
    for kind, ctext in split_members(src.read_text(encoding="utf-8")):
        if kind == "measure":
            info = measure_info(ctext)
            if info["name"]:
                existing[info["name"]] = info
    bases = sorted(
        (n for n, e in existing.items()
         if not e["annotation"]
         and (source_folder is None
              or (e["folder"] or "").lower() == source_folder.lower())),
        key=sort_key_pbi,
    )
    return existing, bases


def scan_cibles(model_dir, config) -> list:
    """[(cible racine, KPI)] telles que la GÉNÉRATION les verra : même règle de
    dossier, même correspondance « plus long préfixe KPI », mêmes exclusions
    (on ignore ce qui ressemble déjà à une variation/branche).

    Existe pour que l'aperçu de l'UI montre les VRAIES bases d'une variation
    « aux cibles » au lieu de la liste des KPI — et pour qu'il n'y ait qu'UNE
    définition de « qu'est-ce qu'une cible », partagée avec le générateur."""
    existing, bases = read_measures(model_dir, config)
    if not bases:
        return []
    bases_by_len = sorted(bases, key=len, reverse=True)
    source_folder = ((config.get("settings") or {}).get("sourceFolder") or "")
    suffixes = list(config.get("variations") or {}) + list(config.get("branches") or {})
    out = []
    for spec in (config.get("kpiMeasureFolders") or []):
        if not isinstance(spec, dict):
            continue
        cfolder = (spec.get("folder") or "").strip()
        if not cfolder or (source_folder and cfolder.lower() == source_folder.lower()):
            continue
        for cname in sorted((n for n, e in existing.items()
                             if not e["annotation"]
                             and folder_matches(e["folder"], cfolder)),
                            key=sort_key_pbi):
            if any(cname.endswith(" " + s) for s in suffixes):
                continue          # déjà une variation : le générateur la crée
            kpi = match_kpi(cname, bases_by_len)
            if kpi:
                out.append((cname, kpi))
    return out


# Rangement des dossiers d'affichage (settings.folderLayout).
#
#   « variation » (défaut) — un dossier par VARIATION sous le dossier de la
#   base ; les motifs sont ceux des settings (displayFolderPattern,
#   branchFolderPattern) :
#       _indicateurs\Weight
#       _indicateurs\_7d avg\Weight 7d avg
#       _indicateurs\__YTD\Weight YTD
#       _indicateurs\__YTD\_7d avg\Weight YTD 7d avg
#
#   « kpi » — un dossier par KPI, la base restant DEHORS ; dedans, toutes ses
#   variations, et un dossier par branche qui porte la mesure de branche et
#   ses variations :
#       _indicateurs\Weight
#       _indicateurs\Weight\Weight 7d avg
#       _indicateurs\Weight\YTD\Weight YTD
#       _indicateurs\Weight\YTD\Weight YTD 7d avg
#
# Les deux motifs des settings ne suffisent pas à dire « kpi » : une variation
# EN BRANCHE prend le motif des variations avec le dossier de la branche pour
# {baseFolder}, et {baseFolder}\{kpi} redescendrait d'un cran
# (…\Weight\YTD\Weight). D'où un troisième motif, propre à chaque rangement.
RANGEMENTS = ("variation", "kpi")
DOSSIERS_PAR_KPI = {
    "variation": "{baseFolder}\\{kpi}",                 # Weight 7d avg
    "branche": "{baseFolder}\\{kpi}\\{branch}",          # Weight YTD
    "variation_en_branche": "{baseFolder}",              # Weight YTD 7d avg
}


def motifs_dossiers(settings) -> tuple:
    """(variation, branche, variation en branche) : les motifs de dossier du
    rangement choisi (cf. RANGEMENTS)."""
    settings = settings or {}
    if str(settings.get("folderLayout") or "").lower() == "kpi":
        return (DOSSIERS_PAR_KPI["variation"], DOSSIERS_PAR_KPI["branche"],
                DOSSIERS_PAR_KPI["variation_en_branche"])
    var = settings.get("displayFolderPattern") or "{baseFolder}"
    return (var, settings.get("branchFolderPattern") or "{baseFolder}\\__{branch}", var)


def patron_enveloppe(branch_id, bdef, variations):
    """Le DAX avec lequel une branche ENVELOPPE ses variations, ou None si
    elle les recopie (substitution).

    L'enveloppe est le DÉFAUT : « Weight YTD PY » devient
        CALCULATE([Weight PY], DATESYTD('dim_Date'[Date]))
    plutôt que la logique de PY recopiée autour de [Weight YTD]. Toutes les
    mesures d'une branche se lisent alors pareil, et ce qui cloche se débogue
    dans la variation Réel.

    · `"substitution": true` sur la branche : pas d'enveloppe, pour elle ;
    · `"wrap"` : un patron écrit à la main ({variationRef} = la mesure Réel) ;
    · sinon le patron vient du DAX de la branche elle-même, où la base
      ({baseRef} ou [{base}]) devient {variationRef} — YTD =
      CALCULATE({baseRef}, DATESYTD({date})) donne
      CALCULATE({variationRef}, DATESYTD({date})). Un DAX qui ne cite pas sa
      base ne peut pas envelopper : None."""
    bdef = bdef if isinstance(bdef, dict) else {}
    if bdef.get("substitution"):
        return None
    if str(bdef.get("wrap") or "").strip():
        return str(bdef["wrap"])
    tpl = (variations or {}).get(branch_id)
    dax = token_to_text(tpl.get("dax")) if isinstance(tpl, dict) else None
    if not dax:
        return None
    patron = dax.replace("{baseRef}", "{variationRef}").replace("[{base}]", "{variationRef}")
    return patron if "{variationRef}" in patron else None


def enveloppable(tpl) -> bool:
    """Une variation s'enveloppe en branche sauf si elle dit le contraire
    (`"wrapInBranch": false`). C'est le DRAPEAU, celui de la case de
    l'éditeur ; la génération ajoute une règle (cf. s_enveloppe)."""
    return not (isinstance(tpl, dict) and tpl.get("wrapInBranch") is False)


def s_enveloppe(tpl) -> bool:
    """La génération enveloppe-t-elle cette variation en branche ? Son drapeau,
    ET son DAX ne cite pas {branch} : une variation qui nomme la branche
    (« [{kpi} {branch} PY] ») a été écrite POUR la branche — l'envelopper
    jetterait ce qu'elle y fait. Elle est recopiée, comme avant."""
    return enveloppable(tpl) and "{branch}" not in (token_to_text(tpl.get("dax")) or "")


def variations_de_branche(branch_id, bdef, variations) -> list:
    """Les variations qu'une branche applique, dans l'ordre du config.

    · `excludeVariations` (ce que l'outil écrit) : toutes SAUF celles-là. Une
      branche s'applique par défaut, et une variation ajoutée plus tard y
      entre d'office — on décoche ce qu'on ne veut pas, on ne coche pas ce
      qu'on veut ;
    · `variations` (ancien format, liste blanche) : seulement celles-là, encore
      lues telles quelles ; l'outil les réécrit en exclusions à l'enregistrement ;
    · ni l'une ni l'autre : toutes.

    Jamais la branche elle-même (« Weight YTD YTD »)."""
    bdef = bdef if isinstance(bdef, dict) else {}
    if bdef.get("variations"):
        return [str(x) for x in bdef["variations"]]
    exclues = {str(x) for x in (bdef.get("excludeVariations") or [])}
    return [vid for vid in variations
            if vid.lower() != branch_id.lower() and vid not in exclues]


def generate(model_dir, config, *, dry_run=None, remove_orphans=None, log=print,
             cache_excel=None) -> dict:
    """Génère les mesures et les tables paramètre (cf. _generate).

    `cache_excel` : un dict que l'appelant garde d'un appel à l'autre pour ne
    relire l'Excel des indicateurs que s'il a changé (cf. _lignes_excel)."""
    global _CACHE_LIGNES
    avant = _CACHE_LIGNES
    _CACHE_LIGNES = cache_excel
    try:
        return _generate(model_dir, config, dry_run=dry_run,
                         remove_orphans=remove_orphans, log=log)
    finally:
        _CACHE_LIGNES = avant


# les jetons {…} du DAX, dans l'ordre où on les présente
JETONS_DAX = ("{base}", "{baseRef}", "{kpi}", "{kpiRef}", "{branch}", "{variation}",
              "{date}", "{deltaScale}", "{baseFormatString}")
JETONS_PORTEE = ("<<tables>>", "<<allTables>>", "<<removeFilters>>",
                 "<<each ALLSELECTED({table})>>")
_VARIATION_SONDE = "⟦jetons⟧"
ATTRIBUT_TOUJOURS_PROPOSE = "direction"
_SEP_SONDE = "⟦|⟧"


def apercu_jetons(model_dir, config, variation="", cache_excel=None) -> dict:
    """Ce que vaut chaque jeton, pour chaque KPI, cible et branche.

    Rien n'est recalculé ici : on ajoute à une COPIE du config des variations
    « sondes » dont le DAX n'est que des jetons, et on lit ce que la génération
    à blanc en fait. L'aperçu ne peut donc pas diverger de « Générer ». Une
    sonde par <<jeton>> : un attribut vide pour un KPI ne fait tomber que lui.

    Les attributs sondés sont ceux qui sont déclarés, plus `direction`, proposé
    même s'il ne l'est pas. Les cibles sont celles du rapport, dans les branches
    où elles sont générées.

    Rend {"bases": [{nom, mesure, kpi, branche, cible, valeurs}],
    "attributs": [{jeton, colonne, declare, absente, valeurs}],
    "portee": [jetons], "colonnes": [en-têtes de l'Excel]}.
    `valeurs` : jeton -> texte, ou None si ce KPI n'a pas de valeur."""
    global _CACHE_LIGNES
    import copy
    model_dir = Path(model_dir)
    cfg = copy.deepcopy(config or {})
    td = indicateurs_xlsx(cfg, model_dir.parent)
    bloc = cfg.get("hardcodedAttributes")
    if not isinstance(bloc, dict):
        bloc = cfg["hardcodedAttributes"] = {}
    declares = dict(bloc.get("tokens") or {})
    xlsx = Path(bloc.get("xlsx") or td["path"])
    if not xlsx.is_absolute():
        xlsx = model_dir.parent / xlsx
    colonnes: list = []
    if xlsx.exists():
        avant = _CACHE_LIGNES
        _CACHE_LIGNES = cache_excel         # même cache que la génération
        try:
            lignes = _lignes_excel(xlsx)
            colonnes = [str(c).strip() for c in (lignes[0] if lignes else ())
                        if c is not None and str(c).strip()]
        except Exception:
            colonnes = []
        finally:
            _CACHE_LIGNES = avant
    deja = {str(c).lower() for c in declares.values()}
    portee = list(JETONS_PORTEE) if cfg.get("kpiTables") else []
    jetons = dict(declares)
    attributs = [{"jeton": "<<" + lab + ">>", "colonne": col, "declare": True,
                  "absente": False} for lab, col in declares.items()]
    dir_ = ATTRIBUT_TOUJOURS_PROPOSE
    if dir_ not in deja and dir_ not in jetons:
        trouvee = next((c for c in colonnes if c.lower() == dir_), None)
        if trouvee:
            jetons[dir_] = trouvee
        attributs.append({"jeton": "<<" + dir_ + ">>", "colonne": trouvee or dir_,
                          "declare": False, "absente": trouvee is None})
    bloc["tokens"] = jetons

    # la valeur BRUTE de chaque cellule : celle qu'on édite dans la fenêtre
    cle_xlsx = bloc.get("keyColumn") or td["keyColumn"]
    avant = _CACHE_LIGNES
    _CACHE_LIGNES = cache_excel
    try:
        for a in attributs:
            a["valeurs"] = {}
            if not a["absente"] and xlsx.exists():
                try:
                    a["valeurs"] = read_attribute_map(xlsx, cle_xlsx, a["colonne"])
                except (SystemExit, Exception):
                    a["valeurs"] = {}
    finally:
        _CACHE_LIGNES = avant

    variations = cfg.setdefault("variations", {})
    modele = {"inFieldParameter": False, "appliesToKpi": True, "appliesToCibles": True,
              "wrapInBranch": False, "formatString": "inherit"}
    variations[_VARIATION_SONDE] = dict(modele, namePattern="{base} " + _VARIATION_SONDE,
                                        dax=_SEP_SONDE.join(JETONS_DAX))
    sondes: dict = {}
    for i, jeton in enumerate([a["jeton"] for a in attributs if not a["absente"]] + portee):
        vid = f"{_VARIATION_SONDE} {i}"
        sondes[vid] = jeton
        variations[vid] = dict(modele, namePattern="{base} " + vid, dax=jeton)
    # une branche restreinte doit quand même recevoir les sondes
    cfg["branches"] = {b: {k: v for k, v in d.items()
                           if k not in ("variations", "excludeVariations")}
                       if isinstance(d, dict) else {}
                       for b, d in (cfg.get("branches") or {}).items()}
    cfg["fieldParameter"] = {"enabled": False}      # sans objet ici

    st = generate(model_dir, cfg, dry_run=True, remove_orphans=False,
                  log=lambda *a, **k: None, cache_excel=cache_excel)
    arbre = {n["name"]: n for n in st.get("arbre") or []}

    def racine(nom):
        n = arbre.get(nom)
        # une mesure de branche descend de sa base ; une cible, elle, est
        # une racine à part entière (son parent est son KPI)
        while n and n.get("type") == "branche" and n.get("parent") in arbre:
            nom, n = n["parent"], arbre[n["parent"]]
        return nom

    bases: dict = {}
    for n in st.get("arbre") or []:
        vid = n.get("variation") or ""
        if not vid.startswith(_VARIATION_SONDE):
            continue
        mesure = n["parent"]
        cle = (racine(mesure), n.get("branche") or "")
        b = bases.setdefault(cle, {
            "nom": cle[0], "mesure": mesure, "kpi": n.get("kpi"), "branche": cle[1],
            "cible": bool(n.get("cible")),
            "valeurs": {j: None for j in sondes.values()}})
        if vid == _VARIATION_SONDE:
            for j, v in zip(JETONS_DAX, (n.get("dax") or "").split(_SEP_SONDE)):
                b["valeurs"][j] = variation if j == "{variation}" else v
        else:
            b["valeurs"][sondes[vid]] = n.get("dax")
    return {"bases": list(bases.values()), "attributs": attributs,
            "portee": portee, "colonnes": colonnes}


def _generate(model_dir, config, *, dry_run=None, remove_orphans=None, log=print) -> dict:
    """Génère mesures + tables paramètre dans les TMDL de `model_dir`
    d'après `config` (dict du measures_config.json). Retourne les stats.
    dry_run / remove_orphans None = valeurs du config (settings)."""
    model_dir = Path(model_dir)
    tables_dir = model_dir / "definition" / "tables"
    if not tables_dir.exists():
        raise SystemExit(f"Modèle introuvable : {tables_dir}")

    # ---- settings -------------------------------------------------------------
    settings = config.get("settings") or {}
    source_table   = settings.get("sourceTable") or "_mesures"
    source_folder  = settings.get("sourceFolder")
    date_column    = settings.get("dateColumn") or "'dim_Date'[Date]"
    target_table   = settings.get("targetTable") or source_table
    # rangement par variation (motifs des settings) ou par KPI
    folder_pattern, branch_folder_pattern, branch_var_folder_pattern = \
        motifs_dossiers(settings)
    par_kpi = str(settings.get("folderLayout") or "").lower() == "kpi"
    overwrite      = settings.get("overwriteExisting", True)
    # formats « delta » : symboles par section + repli si la base n'a pas de
    # format (sinon le delta n'a aucun format, donc aucun signe visible)
    delta_symbols  = settings.get("deltaSymbols") or {}
    delta_fallback = settings.get("deltaFallbackFormat", DELTA_FALLBACK)
    if remove_orphans is None:
        remove_orphans = settings.get("removeOrphans", False)
    if dry_run is None:
        dry_run = settings.get("dryRun", False)

    fp = config.get("fieldParameter") or {}
    fp_enabled = fp.get("enabled", True) if fp else False
    # chaque table paramètre avec SES réglages (cf. fp_table_specs)
    fp_specs = fp_table_specs(fp) if fp_enabled else []
    lkp = fp.get("kpiLabelLookup") or {}
    lkp_table = lkp.get("table") or "TD_Indicateurs"
    lkp_key   = lkp.get("keyColumn") or "mesure"
    lkp_lbl   = lkp.get("labelColumn") or "libelle_indicateur"
    lkp_key_ref = "'" + lkp_table.replace("'", "''") + "'" + bracket(lkp_key)
    lkp_lbl_ref = "'" + lkp_table.replace("'", "''") + "'" + bracket(lkp_lbl)
    # Garde-fou : sans la table de correspondance dans le modèle, le
    # LOOKUPVALUE rendrait la table paramètre invalide. On retombe alors sur le
    # nom brut plutôt que de casser la génération.
    lkp_ok = (tables_dir / (lkp_table + ".tmdl")).exists()
    if not lkp_ok and any(s_["kpiLabel"] and "kpi" in (s_["rows"], s_["baseRow"])
                          for s_ in fp_specs):
        log(f"⚠ table de correspondance « {lkp_table} » absente du modèle, "
            f"les tables paramètre afficheront le nom brut du KPI. "
            f"Corriger fieldParameter.kpiLabelLookup.table.")
    fp_kpi_col    = fp.get("kpiColumn") or "Indicateur"
    fp_calc_col   = fp.get("calcColumn") or "Calcul"
    fp_base_lbl   = fp.get("baseLabel") or "Base"
    fp_branch_col = fp.get("branchColumn") or "Branche"
    fp_nobranch   = fp.get("noBranchLabel") or "Base"

    # le config du rapport est AUTONOME : ce qu'il contient est exactement ce
    # qui sera généré (les variations viennent de la bibliothèque par import)
    variations = config.get("variations") or {}
    if not variations:
        raise SystemExit(
            "La config n'a pas d'objet 'variations', en importer depuis la "
            "bibliothèque (Mesures -> Bibliothèque…).")
    branches = dict(config.get("branches") or {})

    # attributs codés en dur : jeton <<label>> dans le DAX -> valeur de la colonne
    # pour le KPI (lue dans l'Excel), au lieu d'un LOOKUPVALUE à l'exécution.
    hardcoded = config.get("hardcodedAttributes") or {}
    # Excel des indicateurs : défini UNE fois dans le config (cf. indicateurs_xlsx)
    td = indicateurs_xlsx(config, model_dir.parent)
    hc: dict = {}                 # label -> {clé KPI : valeur formatée}
    if hardcoded.get("tokens"):
        hx = Path(hardcoded.get("xlsx") or td["path"])
        if not hx.is_absolute():
            hx = model_dir.parent / hx
        hkey = hardcoded.get("keyColumn") or td["keyColumn"]
        for label, col in hardcoded["tokens"].items():
            hc[label] = read_attribute_map(hx, hkey, col)

    # portée par KPI -> jetons <<tables>> / <<allTables>> / <<removeFilters>>.
    # Source à privilégier : une colonne de TD_Indicateurs (cf. read_kpi_tables)
    kpi_tables = read_kpi_tables(
        config.get("kpiTables"), model_dir, td["path"], td["keyColumn"], log)
    if kpi_tables:
        log(f"Portée par KPI : {len(kpi_tables)} KPI avec des tables déclarées.")
    kpi_tables_auto = bool((config.get("kpiTables") or {}).get("fromMeasureDax"))


    def branch_variation_ids(branch_id, bdef):
        return variations_de_branche(branch_id, bdef, variations)

    # index de tri par variation (constant par libellé — exigence SortByColumn)
    var_order: dict = {}
    idx = 1                  # 0 : la base (le rang final est recalculé plus bas)
    for vid, tpl in variations.items():
        if isinstance(tpl, dict) and tpl.get("inFieldParameter"):
            var_order[vid] = idx
            idx += 1

    # ---- parse du fichier des mesures ---------------------------------------
    src_path = tables_dir / (target_table + ".tmdl")
    if not src_path.exists():
        raise SystemExit(f"Table cible introuvable : {src_path}")
    text = src_path.read_text(encoding="utf-8")
    chunks = split_members(text)

    existing: dict = {}      # nom -> {chunk_idx, info}
    for ci, (kind, ctext) in enumerate(chunks):
        if kind == "measure":
            info = measure_info(ctext)
            if info["name"]:
                existing[info["name"]] = {"idx": ci, **info}

    # mesures de base : sans annotation, displayFolder == sourceFolder.
    # Ordre alphabétique « à la Power BI » (et non ordinal) : c'est l'ordre
    # d'écriture dans le TMDL, et le repli des tables paramètre quand aucune
    # colonne d'ordre n'est configurée (cf. kpi_ranks).
    bases = sorted(
        (n for n, e in existing.items()
         if not e["annotation"]
         and (source_folder is None
              or (e["folder"] or "").lower() == source_folder.lower())),
        key=sort_key_pbi,
    )
    if not bases:
        raise SystemExit(f"Aucune mesure de base dans '{target_table}' "
                         f"(dossier '{source_folder}').")

    # portées manquantes : déduites du DAX des bases si l'option est active
    kpi_tables = complete_kpi_tables(kpi_tables, existing, bases,
                                     kpi_tables_auto, log)

    # ---- compute : les specs de toutes les mesures générées ------------------
    created, updated, unchanged, skipped, removed = [], [], [], [], []
    preserved_names = set()  # mesures demandées, conservées sans écrasement
    planned: dict = {}       # tag -> spec {name, dax, fmt, folder, desc, data_cat}
    planned_names: dict = {} # nom de mesure -> tag propriétaire (dédup par NOM)
    # [affichage, réf DAX, tri, KPI, calcul, branche, variation | None, cible?,
    #  base?, clé de branche ("" = hors branche)] — TOUTES les rangées ; chaque
    # table garde les siennes (fp_rows_pour)
    fp_rows: list = []
    # l'ARBRE de ce qui est généré (vue « Arbre des mesures » de l'onglet
    # Mesures) : nom -> {name, parent, type, kpi, variation, branche, cible}.
    # Le parent est la mesure DONT celle-ci est dérivée : la base pour une
    # variation ou une mesure de branche, la mesure de branche pour une
    # variation en branche, le KPI pour une cible racine.
    arbre: dict = {}
    # (KPI, branche) -> nom RÉEL de la mesure du KPI dans cette branche, tel que
    # la 1re passe l'a générée. C'est ce que {kpiRef} rend en branche : on ne
    # suppose PAS « <KPI> <branche> », car le namePattern d'une branche est
    # librement configurable (« {base} cumul », « YTD {base} »…).
    kpi_branch_ref: dict = {}

    def process(base_name, base_fmt, base_folder, kpi_lbl, vid, tpl,
                fp_label, fp_branch, pass_folder_pattern, branch_id, fp_group=2,
                dax_impose=None, en_branche=False, modele_impose=None):
        """Port de processVariation : calcule la spec + la rangée paramètre.
        `fp_group` = groupe de tri de la rangée (2 = variation de KPI ; 1 =
        cible). `dax_impose` remplace le DAX de la variation — c'est ainsi
        qu'une branche ENVELOPPE la variation Réel au lieu d'en recopier la
        logique. Tout le reste (nom, format, dossier, annotation, rangée du
        paramètre) est inchangé. Retourne (nom, format, dossier) ou None."""
        delta_scale = "100" if has_scaling_percent(base_fmt) else "1"

        def expand(s):
            if s is None:
                return None
            # attributs de TD_Indicateurs : <<label>> -> valeur pour ce KPI (si
            # trouvée ; sinon le jeton reste et process() saute la mesure en
            # avertissant). AVANT les autres jetons : une cellule peut porter
            # du DAX, donc {baseRef} ou {date}.
            for label, valmap in hc.items():
                tok = "<<" + label + ">>"
                v = valmap.get(kpi_lbl)
                if tok in s and v is not None:
                    s = s.replace(tok, v)
            # {branch} d'abord : il emporte son espace, avant que les autres
            # jetons ne deviennent du texte
            s = remplacer_branche(s, branch_id)
            # {kpi}    = le KPI RACINE, sans branche (« Weight ») — un libellé.
            # {kpiRef} = la mesure du KPI dans la MÊME branche que la base
            # courante : [Weight] en Réel, [Weight YTD] en branche YTD. Pour une
            # base normale, {kpiRef} == {baseRef} ; pour une cible « Weight cible
            # YTD », {kpiRef}=[Weight YTD] donne l'écart réel−cible COHÉRENT
            # ({kpiRef} - {baseRef}). Écrire « [{kpi}] » à la place compare le
            # réel COURANT à la cible YTD — les deux côtés doivent être en YTD.
            # Le nom vient de la 1re passe (kpi_branch_ref), pas d'un suffixe
            # supposé ; repli sur « <KPI> <branche> » si la branche n'a rien
            # produit pour ce KPI.
            kpi_ref_name = kpi_lbl or ""
            if branch_id:
                kpi_ref_name = kpi_branch_ref.get(
                    (kpi_lbl, branch_id), kpi_ref_name + " " + branch_id)
            kpi_ref = bracket(kpi_ref_name)
            s = (s.replace("{baseRef}", bracket(base_name))
                  .replace("{kpiRef}", kpi_ref)
                  .replace("{base}", base_name)
                  .replace("{kpi}", kpi_lbl or "")
                  .replace("{date}", date_column)
                  .replace("{variation}", vid)
                  .replace("{deltaScale}", delta_scale)
                  .replace("{baseFormatString}", chaine_dax(base_fmt)))
            # portée par KPI (config, pas Excel) : les cibles héritent de celle
            # de LEUR KPI, puisque kpi_lbl vaut le KPI même pour « Weight cible »
            portee = kpi_tables.get(kpi_lbl)
            for label, v in kpi_table_tokens(portee).items():
                s = s.replace("<<" + label + ">>", v)
            # jeton générique : la fonction DAX vient de TOI, on ne fait que la
            # répéter par table (<<each ALLSELECTED({table})>>)
            s = expand_each(s, portee)
            return s

        name = expand(tpl.get("namePattern"))
        dax = expand(token_to_text(dax_impose if dax_impose is not None
                                   else tpl.get("dax")))
        desc = expand(token_to_text(tpl.get("description")))
        if (not base_fmt and "{baseFormatString}"
                in (token_to_text(tpl.get("dax")) or "")):
            log(f"⚠ variation '{vid}' : « {base_name} » n'a pas de format, "
                "{baseFormatString} vaut \"\" (FORMAT rendra le nombre brut). "
                "Lui donner un format dans Desktop, puis régénérer.")
        fmt = resolve_format(tpl.get("formatString"), base_fmt,
                             delta_symbols, delta_fallback)
        if not name or not dax:
            log(f"⚠ variation '{vid}' sans namePattern ou dax, ignorée.")
            return None
        if "<<" in dax or "<<" in (name or ""):
            missing = re.findall(r"<<([^>]+)>>", dax + " " + (name or ""))
            manquants = ", ".join("<<" + m + ">>" for m in dict.fromkeys(missing))
            log(f"⚠ « {name} » non générée : {manquants} sans valeur pour "
                f"« {kpi_lbl} », remplir sa colonne dans TD_Indicateurs.")
            return None

        folder_var = tpl.get("folderVariation") or vid
        default_folder = (pass_folder_pattern
                          .replace("{baseFolder}", base_folder or "")
                          .replace("{base}", base_name)
                          .replace("{variation}", folder_var)
                          .replace("{kpi}", kpi_lbl or "")
                          .replace("{branch}", branch_id or ""))
        # le dossier qu'une variation IMPOSE ({baseFolder}\_SVG) : rangé par
        # KPI, {baseFolder} y est le dossier du KPI, sinon « Weight sparkline »
        # sortirait du dossier de Weight alors que « Weight YTD sparkline »
        # (dont la base est déjà le dossier de branche) y resterait
        base_imposee = base_folder or ""
        if par_kpi and not en_branche:
            base_imposee = (DOSSIERS_PAR_KPI["variation"]
                            .replace("{baseFolder}", base_folder or "")
                            .replace("{kpi}", kpi_lbl or ""))
        folder = ((tpl.get("displayFolder") or "{folder}")
                  .replace("{folder}", default_folder)
                  .replace("{baseFolder}", base_imposee)
                  .replace("{base}", base_name)
                  .replace("{variation}", folder_var)
                  .replace("{kpi}", kpi_lbl or "")
                  .replace("{branch}", branch_id or ""))

        tag = base_name + "|" + vid

        # rangée du paramètre (mêmes libellés en branche : colonne Branche
        # distingue). Clé de tri (groupe, sous-rang) en position 2 : la base et
        # les cibles se placent AVANT les variations du KPI, identiquement dans
        # toutes les branches (voir le tri « rang KPI-puis-calcul » plus bas).
        if tpl.get("inFieldParameter") and fp_label is not None:
            fp_rows.append([fp_label, bracket(name), (fp_group, var_order[vid]),
                            kpi_lbl, fp_label, fp_branch, vid, fp_group == 1,
                            False, "" if fp_branch == fp_nobranch else fp_branch])

        prev = existing.get(name)
        if prev is not None and not prev["annotation"]:
            # collision avec une mesure NON générée : ne pas y toucher
            log(f"⚠ '{name}' existe mais n'est pas générée, ignorée.")
            skipped.append(name)
            return (name, prev["format"], prev["folder"])
        if prev is not None and not overwrite:
            preserved_names.add(name)
            skipped.append(name)
            return (name, prev["format"], prev["folder"])

        # dédup par NOM : dans le modèle les noms de mesures sont UNIQUES.
        # La passe de base et une passe de branche peuvent viser le même nom
        # quand le namePattern est invariant par branche (utilise {kpi} au lieu
        # de {base} — ex. une mesure « direction / libellé du KPI »). On ne
        # garde que la 1re (la base) ; les suivantes sont ignorées. Sinon deux
        # blocs TMDL de même nom -> Power BI refuse de charger le modèle.
        owner = planned_names.get(name)
        if owner is not None and owner != tag:
            log(f"⚠ « {name} » déjà générée par « {owner.split('|', 1)[1]} », "
                f"variante « {vid} »" + (f" (branche {branch_id})" if branch_id else "")
                + " ignorée : même nom (namePattern en {kpi}, invariant par branche ?).")
            return (name, fmt, folder)

        planned[tag] = {
            "name": name, "dax": dax, "fmt": fmt, "folder": folder,
            "desc": desc, "data_cat": tpl.get("dataCategory") or None,
        }
        planned_names[name] = tag
        arbre[name] = {"name": name, "parent": base_name,
                       "type": "branche" if branch_id == vid else "variation",
                       "kpi": kpi_lbl, "variation": vid,
                       "branche": branch_id, "cible": fp_group == 1,
                       # les attributs, tels que « Générer » les écrira
                       "dax": dax, "format": fmt, "dossier": folder,
                       "description": desc,
                       "dataCategory": tpl.get("dataCategory") or None,
                       "enveloppe": dax_impose is not None,
                       # le DAX AVANT développement (jetons compris) : l'aperçu
                       # s'en sert pour colorer ce que chaque jeton est devenu.
                       # Pour une enveloppe, c'est le patron de la branche.
                       "dax_modele": token_to_text(
                           modele_impose if (dax_impose is not None and modele_impose)
                           else tpl.get("dax"))}
        return (name, fmt, folder)

    # -- 1re passe : bases × variations (KPI, puis cibles) --
    # Portée par variation (contrôlée dans l'UI) : une variation va aux KPI
    # (appliesToKpi, défaut True), aux cibles (appliesToCibles, défaut False),
    # ou aux deux. Les cibles ne reçoivent donc QUE ce qui est coché « aux
    # cibles » — typiquement l'écart réel−cible ({kpiRef} - {baseRef}), pas les
    # 7d avg / sparkline. Les écarts, eux, ne vont pas aux KPI (ils vaudraient 0).
    kpi_vids   = [vid for vid, tpl in variations.items()
                  if isinstance(tpl, dict) and tpl.get("appliesToKpi", True)]
    cible_vids = [vid for vid, tpl in variations.items()
                  if isinstance(tpl, dict) and tpl.get("appliesToCibles", False)]

    branch_bases: list = []   # (nom, fmt, dossier, kpi, branche, hors_param, préfixe, vids_autorisés, base_racine)
    # (base racine, variation) -> nom RÉEL généré à la 1re passe. C'est lui que
    # la branche ENVELOPPE (par défaut, cf. patron_enveloppe) : la 2e passe
    # référence la mesure au lieu de recopier sa logique.
    var_ref: dict = {}
    filtres_format: dict = {}  # variation -> bases écartées par appliesToFormats

    def run_base(base_name, base_fmt, base_folder, kpi_lbl, base_calcul,
                 calc_prefix, allowed_vids):
        """Décline UNE base dans les variations `allowed_vids` (et prépare ses
        branches). Sert aux KPI comme aux cibles :
        - `kpi_lbl`   : valeur Indicateur du paramètre — le VRAI KPI, même pour
                        une cible (« Weight » pour « Weight cible ») ;
        - `base_calcul` : libellé Calcul de la base (« Réel » ou « Cible ») ;
        - `calc_prefix` : préfixe des Calcul de variations (« » ou « Cible ») ;
        - `allowed_vids` : variations à générer (kpi_vids ou cible_vids)."""
        # groupes de tri : base KPI = 0, cible (base+variations) = 1, variations
        # du KPI = 2 -> la cible se range en 2e, avant les variations, partout.
        is_cible = bool(calc_prefix)
        base_group = 1 if is_cible else 0
        arbre[base_name] = {"name": base_name,
                            "parent": kpi_lbl if is_cible else None,
                            "type": "cible" if is_cible else "base",
                            "kpi": kpi_lbl, "variation": None, "branche": None,
                            "cible": is_cible,
                            # écrite à la main : ses attributs viennent du TMDL
                            "dax": (existing.get(base_name) or {}).get("expression"),
                            "format": base_fmt, "dossier": base_folder,
                            "description": None, "dataCategory": None,
                            "enveloppe": False}
        var_group  = 1 if is_cible else 2
        # toujours produite : c'est chaque table qui la garde ou non
        fp_rows.append([base_calcul, bracket(base_name), (base_group, 0),
                        kpi_lbl, base_calcul, fp_nobranch, None, is_cible,
                        True, ""])
        for vid in allowed_vids:
            tpl = variations.get(vid)
            if not isinstance(tpl, dict):
                log(f"⚠ variation '{vid}' n'est pas un objet, ignorée.")
                continue
            # filtres : la mesure n'est pas créée du tout
            if not base_retenue(tpl, base_fmt, base_name, kpi_lbl):
                filtres_format.setdefault(vid, []).append(base_name)
                continue
            is_branch = vid in branches
            result = process(base_name, base_fmt, base_folder, kpi_lbl, vid, tpl,
                             None if is_branch else (calc_prefix + vid), fp_nobranch,
                             branch_folder_pattern if is_branch else folder_pattern,
                             vid if is_branch else None, var_group)
            if result and not is_branch:
                var_ref[(base_name, vid)] = result[0]
            if result and is_branch:
                # mémorise la mesure de branche du KPI (jamais celle d'une
                # cible : {kpiRef} doit rendre [Weight YTD], pas [Weight cible YTD])
                if not is_cible:
                    kpi_branch_ref[(kpi_lbl, vid)] = result[0]
                if tpl.get("inFieldParameter"):
                    fp_rows.append([base_calcul, bracket(result[0]), (base_group, 0),
                                    kpi_lbl, base_calcul, vid, None, is_cible,
                                    False, vid])
                branch_bases.append((result[0], result[1], result[2],
                                     kpi_lbl, vid, False, calc_prefix,
                                     allowed_vids, base_name))

    for base in bases:
        run_base(base, existing[base]["format"], existing[base]["folder"],
                 base, fp_base_lbl, "", kpi_vids)

    if filtres_format:
        for vid, ecartes in sorted(filtres_format.items()):
            log(f"« {vid} » : {len(ecartes)} base(s) écartée(s) par le filtre de "
                f"format/nom ({', '.join(sorted(ecartes))}).")

    # -- l'ancienne mesure Switch -----------------------------------------------
    # La mesure Switch (SWITCH(SELECTEDVALUE(...)) sur tous les KPI) et ses
    # variations ne sont plus générées : elles produisaient beaucoup d'erreurs
    # et ne servaient pas. Celles qu'un modèle porte encore sont des
    # orphelines comme les autres (retirées si « Supprimer les orphelines »
    # est coché) — on le dit en clair plutôt que de les laisser se perdre
    # dans la liste des orphelines. Un bloc « switch » resté dans le config
    # est simplement ignoré.
    anciens_sw = {t.split("|", 1)[1] for t in
                  (e["annotation"] for e in existing.values() if e["annotation"])
                  if t.startswith("switch|")}
    if anciens_sw:
        restes = sorted(n for n, e in existing.items() if e["annotation"]
                        and (e["annotation"].startswith("switch|")
                             or any(e["annotation"].split("|", 1)[0].startswith(w)
                                    for w in anciens_sw)))
        log(f"⚠ La mesure Switch n'est plus générée : {len(restes)} mesure(s) "
            f"« {', '.join(sorted(anciens_sw))}… » encore dans le modèle "
            + ("seront supprimées avec les orphelines."
               if remove_orphans else
               "restent en place, cocher « Supprimer les orphelines » pour les "
               "retirer (vérifier d'abord qu'aucun visuel ne s'en sert)."))

    # -- mesures « cibles » : bases SUPPLÉMENTAIRES d'un dossier dédié ---------
    # L'utilisateur crée à la main la cible RACINE par KPI (ex. « Weight cible »,
    # DAX spécifique : value-at-close…). Le générateur la décline en TOUTES les
    # variations, comme un KPI (elles enveloppent [Weight cible] ; « Weight cible
    # YTD » = CALCULATE([Weight cible], DATESYTD)). Au paramètre : Indicateur = le
    # KPI (Weight), Calcul = « Cible » / « Cible 7d avg »… (préfixé pour ne pas
    # collisionner avec les Calcul du KPI), Branche gérée comme d'habitude.
    bases_by_len = sorted(bases, key=len, reverse=True)   # plus long préfixe d'abord
    var_branch_suffixes = list(variations) + list(branches)
    for spec in (config.get("kpiMeasureFolders") or []):
        if not isinstance(spec, dict):
            continue
        cfolder = (spec.get("folder") or "").strip()
        calcul  = spec.get("calcul") or cfolder or "Cible"
        if not cfolder:
            continue
        if source_folder and cfolder.lower() == source_folder.lower():
            log(f"⚠ kpiMeasureFolders : « {cfolder} » est le dossier des bases, ignoré.")
            continue
        found = 0
        cnames = sorted((n for n, e in existing.items()
                         if not e["annotation"] and folder_matches(e["folder"], cfolder)),
                        key=sort_key_pbi)
        for cname in cnames:
            # on ne décline QUE la cible RACINE : on saute ce qui ressemble déjà
            # à une variation/branche (le générateur les crée lui-même)
            if any(cname.endswith(" " + s) for s in var_branch_suffixes):
                log(f"⚠ « {cname} » ressemble à une variation/branche, ignorée. "
                    f"Ne mettre que la cible RACINE (« <KPI> cible ») dans le dossier ; "
                    f"le générateur décline le reste.")
                continue
            kpi = match_kpi(cname, bases_by_len)
            if kpi is None:
                log(f"⚠ cible « {cname} » : aucun KPI ne correspond au préfixe, ignorée.")
                continue
            e = existing[cname]
            run_base(cname, e["format"], e["folder"], kpi, calcul, calcul + " ",
                     cible_vids)
            found += 1
        if found:
            log(f"Cibles ({cfolder}) : {found} cible(s) racine déclinée(s) en variations "
                f"(Indicateur = KPI, Calcul « {calcul}… »).")
        else:
            seen_folders = sorted({e["folder"] for e in existing.values()
                                   if e["folder"] and not e["annotation"]})
            log(f"⚠ Cibles ({cfolder}) : AUCUNE cible racine trouvée dans « {target_table} ». "
                f"À vérifier : (1) les cibles sont dans cette table ; (2) leur dossier "
                f"correspond ; (3) leur nom commence par un KPI de base (ex. "
                f"« Weight cible »). Dossiers présents : {', '.join(seen_folders) or '(aucun)'}.")

    # -- 2e passe : branches (KPI ET cibles) --
    n_wrap = 0
    sans_patron: set = set()       # branches signalées une fois sans enveloppe
    for (bname, bfmt, bfolder, bkpi, branch_id, no_fp, calc_prefix,
         allowed_vids, base_racine) in branch_bases:
        bdef = branches.get(branch_id)
        wrap = patron_enveloppe(branch_id, bdef, variations)
        if (wrap is None and not (isinstance(bdef, dict) and bdef.get("substitution"))
                and branch_id not in sans_patron):
            sans_patron.add(branch_id)
            log(f"⚠ branche '{branch_id}' : son DAX ne cite pas sa base "
                "({baseRef}), on ne peut pas en tirer d'enveloppe, ses variations "
                "sont recopiées (substitution). Écrire le patron dans ⚙ Réglages → "
                "Branches → Enveloppe pour envelopper.")
        allowed_set = set(allowed_vids)          # portée de la base (KPI ou cible)
        for vid in branch_variation_ids(branch_id, bdef):
            if vid not in allowed_set:            # respecte aux KPI / aux cibles
                continue
            if vid.lower() == branch_id.lower():
                log(f"⚠ branche '{branch_id}' : ne peut pas s'appliquer à elle-même.")
                continue
            tpl = variations.get(vid)
            if not isinstance(tpl, dict):
                log(f"⚠ branche '{branch_id}' : variation inconnue '{vid}'.")
                continue
            # mêmes filtres en branche (le nom de branche contient le KPI,
            # donc exclusion comme inclusion l'attrapent aussi)
            if not base_retenue(tpl, bfmt, bname, bkpi):
                continue
            # ENVELOPPEMENT : au lieu de ré-émettre la logique de la variation
            # avec [base branche] à l'intérieur, on enveloppe la mesure Réel
            # déjà générée. « Weight YTD PY » devient
            #     CALCULATE([Weight PY], DATESYTD(dates))
            # Débogage : toutes les mesures de branche se ressemblent, donc le
            # problème est forcément dans la variation Réel. Et un correctif
            # apporté à celle-ci se répercute SANS régénérer.
            #
            # C'est le DÉFAUT (cf. patron_enveloppe), avec deux portes de
            # sortie : la branche (`substitution`) ou la variation
            # (`wrapInBranch: false`). Ce n'est pas toujours équivalent — une
            # variation qui ÉPINGLE une fenêtre sur la borne du contexte
            # (MAX({date}), DATEADD) change de sens si on l'enveloppe, alors
            # qu'un simple DÉCALAGE (SAMEPERIODLASTYEAR) est identique.
            dax_impose = modele = None
            if wrap and s_enveloppe(tpl):
                reel = var_ref.get((base_racine, vid))
                if reel:
                    dax_impose = wrap.replace("{variationRef}", bracket(reel))
                    modele = wrap
                    n_wrap += 1
                else:
                    log(f"⚠ branche '{branch_id}' : « {vid} » s'enveloppe "
                        f"mais sa mesure Réel sur « {base_racine} » "
                        "n'a pas été générée, repli sur la substitution.")
            process(bname, bfmt, bfolder, bkpi, vid, tpl,
                    None if no_fp else (calc_prefix + vid), branch_id,
                    branch_var_folder_pattern, branch_id, 1 if calc_prefix else 2,
                    dax_impose, en_branche=True, modele_impose=modele)

    if n_wrap:
        log(f"Branches : {n_wrap} mesure(s) ENVELOPPENT leur variation Réel "
            "(au lieu d'en recopier la logique).")

    # ---- classement des specs vs l'existant ----------------------------------
    def normalized(block_text):
        """Bloc sans lineageTag ni espaces de fin (comparaison « inchangée »)."""
        return re.sub(r"^\t\tlineageTag: .*\n", "", block_text, flags=re.M).rstrip()

    new_chunks_by_tag: dict = {}
    for tag, spec in planned.items():
        prev = existing.get(spec["name"])
        lineage = (prev or {}).get("lineage") or str(uuid.uuid4())
        block = measure_block(spec["name"], spec["dax"], spec.get("fmt"),
                              spec["folder"], spec["desc"], tag,
                              spec.get("data_cat"), lineage)
        new_chunks_by_tag[tag] = block
        if prev is None:
            created.append(spec["name"])
        elif normalized(chunks[prev["idx"]][1]) == normalized(block):
            unchanged.append(spec["name"])
        else:
            updated.append(spec["name"])

    # ---- reconstruction du fichier des mesures --------------------------------
    kept: list = []
    for kind, ctext in chunks:
        if kind == "measure":
            info = measure_info(ctext)
            tag = info["annotation"]
            if tag and info["name"] not in preserved_names:
                # remplacée par la version recalculée. Le NOM compte aussi : une
                # variation dont l'id a changé garde ses noms sous une autre
                # annotation, et la laisser ferait deux mesures du même nom,
                # que Power BI refuse de charger.
                if tag in planned or info["name"] in planned_names:
                    continue
                if remove_orphans:
                    removed.append(info["name"])
                    continue          # orpheline supprimée
                # orpheline conservée telle quelle
        kept.append([kind, ctext])

    # insertion : après la dernière mesure conservée, sinon avant la 1re partition
    insert_at = None
    for i, (kind, _) in enumerate(kept):
        if kind == "measure":
            insert_at = i + 1
    if insert_at is None:
        insert_at = next((i for i, (k, _) in enumerate(kept) if k == "partition"),
                         len(kept))

    gen_blocks = [new_chunks_by_tag[t] + "\n" for t in planned]
    new_text = ("".join(c for _, c in kept[:insert_at])
                + "".join(gen_blocks)
                + "".join(c for _, c in kept[insert_at:]))
    new_text = re.sub(r"\n{3,}", "\n\n", new_text).rstrip() + "\n"

    # ---- tables paramètre ------------------------------------------------------
    fp_statuses: list = []
    fp_writes: list = []      # (path, contenu)
    model_refs_needed: list = []
    # le CONTENU de chaque table, tel que Power BI le montrera (onglet Mesures
    # -> Paramètres de champ) : [{name, rows, rangees, etat}], une rangée =
    # {affichage, libelle?, mesure, ordre, indicateur, calcul, branche}
    fp_detail: list = []
    if fp_specs and fp_rows:
        # ordre des KPI : la colonne d'ordre de TD_Indicateurs si elle est
        # configurée, sinon le tri alphabétique de Power BI
        kpi_order = kpi_ranks(bases, read_kpi_order(td, log), log)

        # rang unique KPI-puis-(groupe, sous-rang) : chaque rangée porte en
        # position 2 une clé (groupe, sous-rang) — base=0, cible=1, variations
        # KPI=2 — donc la cible se range en 2e AVANT les variations, à
        # l'identique dans toutes les branches (l'ancien tri par ordre
        # d'insertion plaçait la cible différemment selon la branche). `i`
        # départage de façon stable.
        order_idx = sorted(range(len(fp_rows)),
                           key=lambda i: (kpi_order[fp_rows[i][3]], fp_rows[i][2], i))
        for rank, i in enumerate(order_idx):
            fp_rows[i][2] = rank

        def build_expr(spec, rows):
            """Le DAX de la table `spec`. rows = « kpi » : chaque rangée affiche
            le KPI (c'est lui qu'on y choisit) et se range à son rang de KPI.
            baseRow = « kpi » : seule la rangée de BASE l'affiche, les
            variations gardant le nom du calcul. Le KPI s'affiche par son
            libellé (LOOKUPVALUE) si kpiLabel et que la table de
            correspondance existe, sinon par le nom de sa mesure."""
            par_kpi = spec["rows"] == "kpi"
            lines = []
            for r in rows:
                disp0, ref, order, kpi, calc, branch = r[:6]
                if par_kpi:
                    order = kpi_order[kpi]
                montre_kpi = par_kpi or (spec["baseRow"] == "kpi"
                                         and calc == fp_base_lbl)
                if montre_kpi and spec["kpiLabel"] and lkp_ok:
                    disp = ("LOOKUPVALUE(" + lkp_lbl_ref + ", " + lkp_key_ref
                            + ', "' + dax_str(kpi) + '")')
                elif montre_kpi:
                    disp = '"' + dax_str(kpi) + '"'
                else:
                    disp = '"' + dax_str(disp0) + '"'
                lines.append('    (' + disp + ", NAMEOF(" + ref + "), " + str(order)
                             + ', "' + dax_str(kpi) + '", "' + dax_str(calc)
                             + '", "' + dax_str(branch) + '")')
            return "{\n" + ",\n".join(lines) + "\n}"

        # les libellés que le LOOKUPVALUE trouvera, lus dans l'Excel des
        # indicateurs quand il porte la colonne (sinon l'aperçu dit « libellé
        # de Weight » : la valeur n'existe qu'au rafraîchissement)
        libelles: dict = {}
        if lkp_ok and any(s_["kpiLabel"] and "kpi" in (s_["rows"], s_["baseRow"])
                          for s_ in fp_specs):
            try:
                libelles = read_attribute_map(td["path"], lkp_key, lkp_lbl)
            except (SystemExit, Exception):
                libelles = {}

        def decrire(spec, rows):
            """Les rangées de `spec` pour l'aperçu : la MÊME logique
            d'affichage que build_expr, en texte lisible, triées par ordre."""
            par_kpi = spec["rows"] == "kpi"
            out = []
            for r in rows:
                disp0, ref, order, kpi, calc, branch = r[:6]
                if par_kpi:
                    order = kpi_order[kpi]
                montre_kpi = par_kpi or (spec["baseRow"] == "kpi"
                                         and calc == fp_base_lbl)
                libelle = bool(montre_kpi and spec["kpiLabel"] and lkp_ok)
                if libelle:
                    disp = libelles.get(kpi) or kpi
                elif montre_kpi:
                    disp = kpi
                else:
                    disp = disp0
                out.append({"affichage": disp, "libelle": libelle,
                            "libelle_trouve": bool(libelle and libelles.get(kpi)),
                            "mesure": ref[1:-1] if ref.startswith("[") else ref,
                            "ordre": order, "indicateur": kpi, "calcul": calc,
                            "branche": branch})
            out.sort(key=lambda x: (x["ordre"], x["indicateur"]))
            return out

        targets = []
        for spec in fp_specs:
            rows = fp_rows_pour(spec, fp_rows)
            fp_detail.append({"name": spec["name"], "rows": spec["rows"],
                              "rangees": decrire(spec, rows),
                              "etat": "vide" if not rows else ""})
            if not rows:
                # {} n'est pas une table DAX valide : on n'y touche pas
                fp_statuses.append(f"⚠ {spec['name']} : aucune rangée après ses "
                                   f"filtres, non modifiée")
                continue
            targets.append((spec["name"], build_expr(spec, rows), len(rows)))

        # tables où se trouve chaque mesure (le marqueur de l'arbre)
        par_ref = {bracket(n): n for n in arbre}
        for spec in fp_specs:
            for r in fp_rows_pour(spec, fp_rows):
                n = par_ref.get(r[1])
                if n is not None:
                    arbre[n].setdefault("tables", []).append(spec["name"])

        etats_fp: dict = {}
        for tname, expr, n_rows in targets:
            tpath = tables_dir / (tname + ".tmdl")
            indented = "\n".join("\t\t\t\t" + l for l in expr.split("\n"))
            if tpath.exists():
                ttext = tpath.read_text(encoding="utf-8")
                m = SOURCE_BLOCK_RE.search(ttext)
                if not m:
                    fp_statuses.append(f"⚠ {tname} : bloc `source =` introuvable, non modifiée")
                    etats_fp[tname] = "source introuvable"
                    continue
                new_ttext = ttext[: m.start(2)] + indented + "\n" + ttext[m.end(2):]
                new_ttext = re.sub(r"\n{3,}", "\n\n", new_ttext)
                if new_ttext != ttext:
                    fp_writes.append((tpath, new_ttext))
                    fp_statuses.append(f"{tname} : expression mise à jour ({n_rows} rangées)")
                    etats_fp[tname] = "modifiée"
                else:
                    fp_statuses.append(f"{tname} : inchangée ({n_rows} rangées)")
                    etats_fp[tname] = "inchangée"
            else:
                etats_fp[tname] = "nouvelle"
                content = param_table_file(tname, expr, fp_kpi_col, fp_calc_col,
                                           fp_branch_col, {})
                fp_writes.append((tpath, content))
                model_refs_needed.append(tname)
                fp_statuses.append(f"{tname} : CRÉÉE ({n_rows} rangées). Penser à la "
                                   f"relation TD → {fp_kpi_col} à créer une fois dans Desktop)")

    # ---- résumé / écriture -----------------------------------------------------
    log(f"{len(bases)} mesure(s) de base : " + ", ".join(bases))
    log(f"Mesures générées : {len(created)} à créer, {len(updated)} à mettre à jour, "
        f"{len(unchanged)} inchangée(s), {len(skipped)} ignorée(s), "
        f"{len(removed)} orpheline(s) supprimée(s)")
    for s in fp_statuses:
        log("Paramètre : " + s)
    for n in created:
        log("  + " + n)
    for n in updated:
        log("  ~ " + n)
    for n in removed:
        log("  - " + n)

    etat = {}
    for lst, mot in ((created, "nouvelle"), (updated, "modifiée"),
                     (unchanged, "inchangée")):
        for n in lst:
            etat[n] = mot
    for n, noeud in arbre.items():
        noeud.setdefault("tables", [])
        noeud["etat"] = etat.get(n, "à la main" if noeud["type"] in ("base", "cible")
                                 else "")
    if fp_detail:
        for d in fp_detail:
            d["etat"] = d["etat"] or etats_fp.get(d["name"], "")
    stats = {"bases": bases, "created": created, "updated": updated,
             "unchanged": unchanged, "skipped": skipped, "removed": removed,
             "fp_statuses": fp_statuses, "dry_run": bool(dry_run),
             "arbre": list(arbre.values()),
             "parametres": fp_detail,
             "parametres_colonnes": {"kpi": fp_kpi_col, "calcul": fp_calc_col,
                                     "branche": fp_branch_col},
             "parametres_actifs": bool(fp_specs)}

    if dry_run:
        log("*** DRY_RUN : aucun fichier modifié ***")
        return stats

    # backup puis écriture
    to_write = [(src_path, new_text)] + fp_writes
    model_path = model_dir / "definition" / "model.tmdl"
    if model_refs_needed:
        mtext = model_path.read_text(encoding="utf-8")
        add = "".join("ref table " + quote_tmdl(t) + "\n"
                      for t in model_refs_needed
                      if re.search(r"^ref table " + re.escape(quote_tmdl(t)) + r"\s*$",
                                   mtext, re.M) is None)
        if add:
            if "\nref cultureInfo" in mtext:
                mtext = mtext.replace("\nref cultureInfo", "\n" + add + "\nref cultureInfo", 1)
            else:
                mtext = mtext.rstrip() + "\n" + add
            to_write.append((model_path, mtext))

    # session de sauvegarde partagée : copies + manifeste (d'où venait chaque
    # fichier), donc restaurable d'un clic depuis « Restaurer une sauvegarde… » comme le
    # reste — et soumise au même ménage (on ne garde que les plus récentes)
    session = br.BackupSession(br.backup_root(model_dir.parent, "_tmdl_backups"),
                               "Mesures générées", model_dir.parent)
    for path, _ in to_write:
        session.save(path)
    for path, content in to_write:
        path.write_text(content, encoding="utf-8")
    backup_dir = session.close(f"{len(created)} créée(s), {len(updated)} mise(s) "
                               f"à jour, {len(removed)} retirée(s)")
    log(f"Écrit : {', '.join(p.name for p, _ in to_write)}"
        + (f"  (backup : {backup_dir.name})" if backup_dir else ""))
    log("Rouvrir le .pbip dans Power BI Desktop pour charger le nouveau modèle.")
    return stats


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config introuvable : {CONFIG_PATH}")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    generate(PBIP_DIR / (PROJECT + ".SemanticModel"), config)


if __name__ == "__main__":
    main()
