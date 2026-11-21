# -*- coding: utf-8 -*-
"""Lecture du modèle et du config pour peupler l'UI. Délègue aux scripts
racine (propagate_cf, color_matrix_by_kpi) — une seule implémentation, la même
qu'en CLI — et à measures_config.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# moteurs importables quel que soit le lanceur (core\ et moteurs\ sont
# deux dossiers frères sous bidouille\).
_FITBIT_DIR = Path(__file__).resolve().parent.parent / "moteurs"
if str(_FITBIT_DIR) not in sys.path:
    sys.path.insert(0, str(_FITBIT_DIR))

import propagate_cf as _pcf              # noqa: E402
import color_matrix_by_kpi as _cmx       # noqa: E402
import xlsx_lecture as _xl               # noqa: E402  (relâche le classeur)
import generate_measures as _gm          # noqa: E402  (fp_table_names)

DEFAULT_FIELD_PARAMETER = "P_Indicateurs_parCalcul"
DEFAULT_ENTITY = "_mesures"


def read_config(project) -> dict:
    """measures_config.json du dossier projet, ou {} s'il manque/est illisible."""
    p = project.config_json
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def candidate_parameters(project) -> list:
    """Noms de tables paramètre où chercher la liste des KPI : celles du
    config, dans son ordre (fieldParameter.tables, ou l'ancien format relu par
    generate_measures.fp_table_names), sinon le nom par défaut."""
    fp = read_config(project).get("fieldParameter") or {}
    # sans liste explicite, l'ancien format retomberait sur « P_Indicateurs » :
    # ici on garde le défaut historique de l'onglet Rapport
    if not fp.get("tables") and not any(
            fp.get(k) for k in ("tableNames", "tableName", "tableNamesKpiBase",
                                "tableNamesByKpi")):
        return [DEFAULT_FIELD_PARAMETER]
    return _gm.fp_table_names(fp) or [DEFAULT_FIELD_PARAMETER]


def _scan_field_parameter(project):
    """Dernier recours : première table du modèle qui RESSEMBLE à un paramètre
    de champ (NAMEOF + parameterMetadata) et dont on peut extraire des KPI.
    Utile quand le config ne correspond pas au rapport ouvert."""
    if project.model_dir is None:
        return None
    tables_dir = Path(project.model_dir) / "definition" / "tables"
    if not tables_dir.exists():
        return None
    for tmdl in sorted(tables_dir.glob("*.tmdl")):
        try:
            low = tmdl.read_text(encoding="utf-8").lower()
        except OSError:
            continue
        if "nameof(" in low and "parametermetadata" in low:
            try:
                if _pcf.kpis_from_parameter(project.model_dir, tmdl.stem):
                    return tmdl.stem
            except SystemExit:
                continue
    return None


def field_parameter(project) -> str:
    """Nom de la table paramètre à utiliser : la première CONFIGURÉE qui
    existe dans le modèle, sinon un scan du modèle, sinon la première
    configurée (l'outil appelé donnera alors l'erreur détaillée)."""
    if project.model_dir is None:
        return candidate_parameters(project)[0]
    tables_dir = Path(project.model_dir) / "definition" / "tables"
    cands = candidate_parameters(project)
    for name in cands:
        if (tables_dir / (name + ".tmdl")).exists():
            return name
    return _scan_field_parameter(project) or cands[0]


def entity(project) -> str:
    """Table qui héberge les mesures (settings.sourceTable, sinon défaut)."""
    return (read_config(project).get("settings") or {}).get("sourceTable") or DEFAULT_ENTITY


def branches(project) -> list:
    """Branches définies dans le config (clés de `branches`), ex. ['YTD']."""
    br = read_config(project).get("branches")
    return list(br.keys()) if isinstance(br, dict) else []


def kpis(project) -> list:
    """KPI distincts via la table paramètre résolue (réutilise propagate_cf).
    RuntimeError actionnable si rien ne se résout (config d'un autre rapport,
    ou pas de config choisi — bouton « Config… »)."""
    if project.model_dir is None:
        raise RuntimeError("Le rapport ne référence aucun modèle local accessible.")
    name = field_parameter(project)
    tmdl = Path(project.model_dir) / "definition" / "tables" / (name + ".tmdl")
    if not tmdl.exists():
        cands = candidate_parameters(project)
        cfg = project.config_json
        raise RuntimeError(
            "table paramètre introuvable dans ce modèle, essayé : "
            + ", ".join(cands)
            + (f" (config : {cfg})" if cfg.exists()
               else f" (AUCUN config chargé, attendu : {cfg})")
            + ". Cliquer sur le bouton du chemin du config (sous la barre du projet) pour choisir le measures_config.json de CE rapport, "
              "ou vérifier ses tables paramètre (⚙ Réglages)."
        )
    try:
        return _pcf.kpis_from_parameter(project.model_dir, name)
    except SystemExit as e:
        raise RuntimeError(str(e))


def measures(project) -> list:
    """Toutes les mesures du modèle (réutilise color_matrix_by_kpi)."""
    return _cmx.all_measures(project.model_dir) if project.model_dir else []


def excel_headers(xlsx_path) -> list:
    """En-têtes (1re ligne, 1re feuille) d'un .xlsx — pour peupler les menus de
    colonnes sans ouvrir le fichier. [] si absent / illisible / openpyxl manquant
    (les combos restent éditables : on peut taper un nom à la main)."""
    p = Path(str(xlsx_path))
    if not p.exists():
        return []
    try:
        # une seule ligne suffit, et le classeur est refermé au retour : ce
        # menu se repeuple souvent, un handle oublié par passage bloquerait
        # l'enregistrement du fichier depuis Excel
        rows = _xl.lire_lignes(p, max_rows=1)
    except Exception:
        return []
    return [str(h).strip() for h in (rows[0] if rows else ())
            if h is not None and str(h).strip()]
