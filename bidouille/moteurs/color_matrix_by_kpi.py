# -*- coding: utf-8 -*-
"""
Colore les colonnes d'une matrice par KPI, dans les visual.json d'un rapport
PBIP : chaque colonne reçoit la couleur de SON KPI (la même pour toutes ses
variations), via la mise en forme « specific column » (statique) de Power BI.

Deux couleurs par KPI : un FOND (couleur_fill) et un TEXTE (couleur_text),
définis dans TD_Indicateurs.xlsx — source unique, tu recolores dans Excel.
Combiner fond × texte multiplie les combinaisons distinctes quand il y a
beaucoup de KPI.

Approche TEMPLATE (comme propagate_cf) — IMPORTANT pour les deux couleurs :
applique à la main, sur UN KPI dans la matrice, **un fond ET un texte** (Specific
column → une série → Background color + Text color), puis enregistre. Le script
lit ce gabarit, DÉTECTE ses propriétés de couleur (backColor = le fond ; l'autre
propriété couleur = le texte, peu importe son nom interne), et réplique pour
toutes les mesures avec le fond/texte de chaque KPI. Si le gabarit n'a qu'un
fond, seul le fond est appliqué (un avertissement le signale).

Distinction des entrées (le script ne touche QUE les couleurs statiques) :
  - CF (propagate_cf)        : selector avec « data » (dataViewWildcard),
                               couleur = une Measure -> IGNORÉ
  - couleur statique (ici)   : selector avec « metadata » seul -> GÉRÉ

Ordre : lancer propagate_cf.py AVANT, puis ce script. Enregistrer dans
Desktop, « py color_matrix_by_kpi.py », puis fermer Desktop SANS enregistrer et
rouvrir. Idempotent.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # moteurs\ voisins
import backup_restore as br
from unused_measures import TABLE_NAME_RE, _first_group
import xlsx_lecture as _xl                  # relâche toujours le classeur
import chemins                              # où sont les projets

# ---------------------------------------------------------------------------
PBIP_DIR     = chemins.PROJETS   # ligne de commande ; l'app passe le sien
PROJECT      = chemins.PROJET_DEMO
TD_XLSX      = PBIP_DIR / "TD_Indicateurs.xlsx"
TD_SHEET     = None              # None = première feuille
TD_KEY_COL   = "mesure"          # colonne = nom de la mesure de base (= KPI)
TD_FILL_COL  = "couleur_fill"    # colonne = code hex du FOND
TD_TEXT_COL  = "couleur_text"    # colonne = code hex du TEXTE
ENTITY       = "_mesures"        # table des mesures

# Clé d'objet des couleurs « specific column » (matrices tableEx). Le script ne
# touche QUE cette clé -> les graphes en lignes (objects.dataPoint), slicers,
# cartes, etc. sont exclus automatiquement. L'opt-in est donc naturel : SEULES
# les matrices où tu as appliqué une couleur « specific column » (le gabarit)
# sont traitées. Aucun GUID, aucun marquage — le gabarit EST le marqueur.
COLUMN_FORMATTING_KEY = "columnFormatting"
# ---------------------------------------------------------------------------

REPORT_DIR = PBIP_DIR / f"{PROJECT}.Report"
MODEL_DIR  = PBIP_DIR / f"{PROJECT}.SemanticModel"

MEASURE_NAME_RE = re.compile(r"^\tmeasure\s+(?:'((?:[^']|'')+)'|([^\s=']+))", re.M)


def read_kpi_colors(xlsx=TD_XLSX, sheet=TD_SHEET, key_col=TD_KEY_COL,
                    fill_col=TD_FILL_COL, text_col=TD_TEXT_COL) -> dict[str, dict]:
    """Lit { nom de mesure de base : {'fill': hex|None, 'text': hex|None} }
    depuis l'Excel `xlsx`. openpyxl d'abord, sinon pandas."""
    xlsx = Path(xlsx)
    if not xlsx.exists():
        raise SystemExit(f"Excel introuvable : {xlsx}")

    def build(get_row_dicts):
        out = {}
        for row in get_row_dicts():
            key = row.get(key_col.lower())
            if not key:
                continue
            fill = row.get(fill_col.lower())
            text = row.get(text_col.lower())
            if fill or text:
                out[str(key).strip()] = {
                    "fill": str(fill).strip() if fill else None,
                    "text": str(text).strip() if text else None,
                }
        return out

    # Le classeur est refermé AVANT qu'on en fasse quoi que ce soit : il n'y a
    # plus de chemin — succès, colonne manquante, erreur — qui laisse le
    # fichier tenu par le processus. C'est ce qui empêchait d'enregistrer
    # TD_Indicateurs depuis Excel après avoir lancé les couleurs.
    try:
        rows = _xl.lire_lignes(xlsx, sheet)
    except ImportError:
        rows = None

    if rows is not None:
        if not rows:
            return {}
        header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
        for need in (key_col, fill_col, text_col):
            if need.lower() not in header:
                raise SystemExit(f"Colonne '{need}' absente de {xlsx.name}. "
                                 f"Colonnes : {rows[0]}")

        def gen():
            for r in rows[1:]:
                yield {header[i]: r[i] for i in range(min(len(header), len(r)))}
        return build(gen)

    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("Ni openpyxl ni pandas disponible (py -m pip install openpyxl).")
    df = pd.read_excel(xlsx, sheet_name=sheet if sheet else 0)
    df.columns = [str(c).strip().lower() for c in df.columns]
    for need in (key_col, fill_col, text_col):
        if need.lower() not in df.columns:
            raise SystemExit(f"Colonne '{need}' absente : {list(df.columns)}")

    def gen():
        for _, r in df.iterrows():
            yield {c: (r[c] if pd.notna(r[c]) else None) for c in df.columns}
    return build(gen)


def normalize_hex(v) -> str:
    v = str(v).strip()
    if not v.startswith("#"):
        v = "#" + v
    return v.upper()


def mesures_et_tables(model_dir):
    noms = {}
    tables_dir = Path(model_dir) / "definition" / "tables"
    for tmdl in sorted(tables_dir.glob("*.tmdl")) if tables_dir.exists() else []:
        text = tmdl.read_text(encoding="utf-8")
        table = _first_group(TABLE_NAME_RE.search(text)) or tmdl.stem
        for m in MEASURE_NAME_RE.finditer(text):
            nm = m.group(1) or m.group(2)
            if nm:
                noms[nm.replace("''", "'")] = table
    return noms


def all_measures(model_dir=MODEL_DIR) -> list[str]:
    return list(mesures_et_tables(model_dir))


def kpi_of(measure: str, kpi_keys) -> str | None:
    best = None
    for k in kpi_keys:
        if measure == k or measure.startswith(k + " "):
            if best is None or len(k) > len(best):
                best = k
    return best


def is_static_color_entry(e) -> bool:
    """Couleur statique « specific column » : selector avec metadata seul (pas
    de 'data'), et au moins une propriété couleur qui n'est PAS une mesure."""
    if not isinstance(e, dict):
        return False
    sel = e.get("selector")
    if not isinstance(sel, dict) or "metadata" not in sel or "data" in sel:
        return False
    for v in e.get("properties", {}).values():
        if isinstance(v, dict) and isinstance(v.get("solid"), dict) and "color" in v["solid"]:
            if "Measure" not in v["solid"]["color"].get("expr", {}):
                return True
    return False


def color_property_keys(props: dict) -> list[str]:
    """Clés des propriétés couleur (qui ont .solid.color) dans un bloc properties."""
    return [k for k, v in props.items()
            if isinstance(v, dict) and isinstance(v.get("solid"), dict) and "color" in v["solid"]]


def color_value(hex_color: str) -> dict:
    return {"solid": {"color": {"expr": {"Literal": {"Value": "'" + hex_color + "'"}}}}}


def visual_title(data: dict) -> str:
    """Titre du visuel pour l'affichage (best-effort), sinon ''. Lit le titre
    de données (objects.title) PUIS le titre de conteneur
    (visualContainerObjects.title — c'est là que Desktop écrit le texte quand
    on nomme/titre un visuel, ex. les modèles d'un PBIP gabarit)."""
    vis = data.get("visual") or {}
    for holder in (vis.get("objects") or {}, vis.get("visualContainerObjects") or {}):
        title = holder.get("title")
        if isinstance(title, list):
            for entry in title:
                v = (entry.get("properties", {}).get("text", {})
                     .get("expr", {}).get("Literal", {}).get("Value"))
                if v:
                    return str(v).strip("'")
    return ""


def process_visual(path: Path, measure_colors: dict[str, dict], *,
                   entity: str = ENTITY,
                   column_formatting_key: str = COLUMN_FORMATTING_KEY,
                   dry_run: bool = False, session=None) -> tuple[int, bool, str]:
    """Régénère les couleurs statiques de la matrice à partir de son gabarit.
    Ne touche QUE objects.columnFormatting -> jamais les graphes (dataPoint),
    slicers, cartes, etc. Une matrice n'est traitée que si elle a un gabarit
    « specific column » (c'est l'opt-in). dry_run = calcule sans écrire.
    Retourne (nb écrites, sans_texte, titre)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    objects = (data.get("visual") or {}).get("objects")
    if not isinstance(objects, dict):
        return 0, False, ""

    entries = objects.get(column_formatting_key)
    if not isinstance(entries, list):
        return 0, False, ""  # pas de specific column -> pas une matrice ciblée
    cibles = {col.get("table", entity) + "." + mesure for mesure, col in measure_colors.items()}
    def gere(entree):
        return (is_static_color_entry(entree) and set(entree["selector"]) == {"metadata"}
                and entree["selector"]["metadata"] in cibles)

    static = [e for e in entries if gere(e)]
    if not static:
        return 0, False, ""  # aucun gabarit -> non ciblée

    # gabarit = entrée statique aux propriétés les plus riches
    template = max(static, key=lambda e: len(e.get("properties", {})))
    tmpl_props = template["properties"]

    # backColor = le FOND ; toute autre propriété couleur = le TEXTE
    ckeys = color_property_keys(tmpl_props)
    fill_key = "backColor" if "backColor" in ckeys else (ckeys[0] if ckeys else None)
    text_key = next((k for k in ckeys if k != fill_key), None)
    missing_text = text_key is None

    # retire les couleurs statiques existantes (idempotent), garde le reste
    avant = list(entries)
    entries[:] = [e for e in entries if not gere(e)]

    written = 0
    for measure in sorted(measure_colors):
        col = measure_colors[measure]
        props = copy.deepcopy(tmpl_props)
        if fill_key and col.get("fill"):
            props[fill_key] = color_value(col["fill"])
        if text_key and col.get("text"):
            props[text_key] = color_value(col["text"])
        entries.append({
            "properties": props,
            "selector": {"metadata": col.get("table", entity) + "." + measure},
        })
        written += 1

    if not dry_run and entries != avant:
        if session is not None:
            session.save(path)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return written, missing_text, visual_title(data)


def colorize(report_dir=REPORT_DIR, model_dir=MODEL_DIR, xlsx=TD_XLSX, *,
             sheet=TD_SHEET, key_col=TD_KEY_COL, fill_col=TD_FILL_COL,
             text_col=TD_TEXT_COL, entity: str = ENTITY,
             dry_run: bool = False, log=print) -> int:
    """Colore les colonnes de matrice par KPI dans tous les visual.json du
    rapport, d'après le gabarit « specific column » de chaque matrice et les
    couleurs de l'Excel. Retourne le nombre total de colonnes colorées.
    Point d'entrée commun CLI (main) et UI (Atelier) ; `log` = print par défaut,
    redirigé vers la console de l'UI. dry_run = aperçu sans écrire."""
    report_dir = Path(report_dir)
    model_dir = Path(model_dir)

    kpi_colors = read_kpi_colors(xlsx, sheet, key_col, fill_col, text_col)
    if not kpi_colors:
        raise SystemExit(f"Aucune couleur lue dans {Path(xlsx).name} "
                         f"(colonnes '{fill_col}' / '{text_col}').")
    log("Couleurs par KPI :")
    for k, c in kpi_colors.items():
        log(f"  {k}: fond={c['fill']} texte={c['text']}")

    # mesure -> couleurs de son KPI (toutes les variations, sauf les mesures CF)
    measure_colors = {}
    for m, table in mesures_et_tables(model_dir).items():
        if " CF " in m or m.endswith(" CF"):
            continue
        k = kpi_of(m, kpi_colors.keys())
        if k:
            c = kpi_colors[k]
            measure_colors[m] = {
                "table": table,
                "fill": normalize_hex(c["fill"]) if c["fill"] else None,
                "text": normalize_hex(c["text"]) if c["text"] else None,
            }
    if not measure_colors:
        raise SystemExit("Aucune mesure ne correspond aux KPI de l'Excel "
                         "(la colonne clé doit contenir les noms de mesures de base).")
    log(f"{len(measure_colors)} mesures à colorer.")
    if dry_run:
        log("*** DRY_RUN : aucun fichier modifié (aperçu seulement) ***")

    total = 0
    warned = False
    session = br.BackupSession(br.backup_root(report_dir.parent, "_propagate_backups"),
                               "Couleurs des matrices", report_dir.parent)
    try:
        for visual_json in sorted(report_dir.glob("definition/pages/*/visuals/*/visual.json")):
            n, missing_text, title = process_visual(visual_json, measure_colors,
                                                    entity=entity, dry_run=dry_run, session=session)
            if n:
                label = '"' + title + '"' if title else visual_json.parent.name
                log(f"  matrice {label} : {n} colonnes colorées"
                    + ("  [gabarit sans texte]" if missing_text else ""))
                total += n
                if missing_text:
                    warned = True

    finally:
        session.close(f"{total} couleurs de matrice")
    if total == 0:
        log("Aucune matrice avec un gabarit de couleur « specific column ». "
            "Appliquer fond + texte sur une série de la matrice voulue, "
            "enregistrer, relancer.")
    else:
        if warned:
            log("⚠ Un gabarit n'avait QU'UN fond (pas de texte), seul le fond a "
                "été appliqué. Ajouter une couleur de texte sur la série gabarit "
                "puis relancer pour colorer le texte aussi.")
        log(f"Terminé : {total} entrées écrites. Rouvrir le .pbip.")
    return total


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    colorize(REPORT_DIR, MODEL_DIR, TD_XLSX, sheet=TD_SHEET, key_col=TD_KEY_COL,
             fill_col=TD_FILL_COL, text_col=TD_TEXT_COL, entity=ENTITY)


if __name__ == "__main__":
    main()
