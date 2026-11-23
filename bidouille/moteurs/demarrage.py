# -*- coding: utf-8 -*-
"""Démarrer un rapport qui n'a pas encore de measures_config.json ni de
TD_Indicateurs.xlsx : des fichiers de DÉPART, devinés d'après le modèle.

Ce qui est deviné :
  · sourceTable : la table qui porte le plus de mesures écrites à la main (pas
    générées par PBIdouille) : c'est là que vivent les KPI ;
  · dateColumn : la colonne de dates d'une table marquée « table de dates »
    (dataCategory: Time), sinon d'une table dont le nom parle de date ou de
    calendrier, sinon la première colonne de type date du modèle ;
  · le reste prend les valeurs par défaut du générateur. Aucune variation,
    aucun paramètre de champ ni switch : rien n'est écrit dans le modèle tant
    qu'on n'a pas choisi quoi générer (la Bibliothèque en propose).

Le TD_Indicateurs.xlsx de départ a une ligne par mesure de base, avec les
colonnes que l'outil lit par défaut (generate_measures.INDICATEURS_DEFAUT) et
un libellé égal au nom. Il est mis en tableau Excel, prêt à importer dans
Power BI.

Rien n'est jamais écrasé : un fichier déjà là fait échouer l'écriture
(FileExistsError). Le modèle n'est que lu.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import generate_measures as gm

TABLE_RE = re.compile(r"^table\s+(?:'((?:[^']|'')+)'|(\S+))", re.M)
COLONNE_RE = re.compile(r"^\tcolumn\s+(?:'((?:[^']|'')+)'|([^\s=]+))", re.M)
TABLE_DE_DATES_RE = re.compile(r"^\tdataCategory:\s*Time\s*$", re.M)
NOMS_DE_DATES = ("date", "calend", "temps", "time", "jour")

COLONNES_TD = ("mesure", "libelle_indicateur", "couleur_fill", "couleur_text")
FEUILLE_TD = "TD_Indicateurs"


def _nom(m) -> str:
    return m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2)


def _tables(model_dir) -> list:
    """[(nom, texte)] des tables du modèle, dans l'ordre des fichiers."""
    dossier = Path(model_dir) / "definition" / "tables"
    out = []
    for f in sorted(dossier.glob("*.tmdl")) if dossier.exists() else []:
        texte = f.read_text(encoding="utf-8-sig")
        m = TABLE_RE.search(texte)
        out.append((_nom(m) if m else f.stem, texte))
    return out


def mesures_de_base(texte: str) -> list:
    """Les mesures d'une table qui ne sont pas générées par PBIdouille, dans
    l'ordre de Power BI."""
    mesures = gm.index_mesures(gm.split_members(texte))
    return sorted((n for n, e in mesures.items() if not e["annotation"]), key=gm.sort_key_pbi)


def _colonnes_de_dates(texte: str) -> list:
    """Les colonnes de type date d'une table, dans l'ordre du fichier."""
    trouvees = list(COLONNE_RE.finditer(texte))
    out = []
    for i, m in enumerate(trouvees):
        fin = trouvees[i + 1].start() if i + 1 < len(trouvees) else len(texte)
        # une colonne d'une table calculée ne déclare pas son dataType : Power
        # BI y laisse l'annotation UnderlyingDateTimeDataType
        if re.search(r"^\t\t(?:dataType:\s*dateTime|annotation UnderlyingDateTimeDataType\b)",
                     texte[m.end():fin], re.M):
            out.append(_nom(m))
    return out


def _colonne_de_dates(tables) -> str:
    """'Table'[Colonne] de la colonne de dates la plus probable, ou ""."""
    def preferee(cols):
        return next((c for c in cols if c.lower() == "date"), cols[0])

    candidates = [(t, _colonnes_de_dates(x), bool(TABLE_DE_DATES_RE.search(x)))
                  for t, x in tables]
    candidates = [(t, cols, marquee) for t, cols, marquee in candidates if cols]
    for regle in (lambda t, m: m,
                  lambda t, m: any(n in t.lower() for n in NOMS_DE_DATES),
                  lambda t, m: True):
        for t, cols, marquee in candidates:
            if regle(t, marquee):
                return f"'{t}'[{preferee(cols)}]"
    return ""


def config_de_depart(model_dir) -> tuple:
    """(config, notes, bases) : le measures_config.json de départ, ce qui a
    été deviné (lisible), et les mesures de base de la table choisie."""
    tables = _tables(model_dir)
    comptes = [(t, mesures_de_base(x)) for t, x in tables]
    comptes = [(t, b) for t, b in comptes if b]
    notes = []
    if comptes:
        source, bases = max(comptes, key=lambda tb: len(tb[1]))
        notes.append(f"Table des mesures : {source} ({len(bases)} mesures de base)")
    else:
        source, bases = "_mesures", []
        notes.append("Table des mesures : aucune table n'a de mesure, « _mesures » par défaut")
    date = _colonne_de_dates(tables)
    if date:
        notes.append(f"Colonne de dates : {date}")
    else:
        date = "'dim_Date'[Date]"
        notes.append("Colonne de dates : aucune trouvée, " + date + " par défaut")
    config = {
        "settings": {
            "sourceTable": source,
            "dateColumn": date,
            "targetTable": source,
            "displayFolderPattern": "{baseFolder}\\_{variation}",
            "branchFolderPattern": "{baseFolder}\\__{branch}",
            "overwriteExisting": True,
            "removeOrphans": False,
            "dryRun": False,
        },
        "variations": {},
        "branches": {},
        "fieldParameter": {"enabled": False},
        "switch": {"enabled": False},
    }
    return config, notes, bases


def ecrire_config(chemin, config) -> Path:
    chemin = Path(chemin)
    if chemin.exists():
        raise FileExistsError(f"existe déjà : {chemin}")
    chemin.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return chemin


def ecrire_td(chemin, mesures) -> Path:
    """TD_Indicateurs.xlsx : une ligne par mesure, dans un tableau Excel."""
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table, TableStyleInfo

    chemin = Path(chemin)
    if chemin.exists():
        raise FileExistsError(f"existe déjà : {chemin}")
    wb = Workbook()
    ws = wb.active
    ws.title = FEUILLE_TD
    ws.append(list(COLONNES_TD))
    for m in mesures:
        ws.append([m, m, "", ""])
    fin = max(len(mesures), 1) + 1
    if not mesures:
        ws.append(["", "", "", ""])
    tableau = Table(displayName=FEUILLE_TD, ref=f"A1:D{fin}")
    tableau.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(tableau)
    for col, largeur in zip("ABCD", (34, 34, 14, 14)):
        ws.column_dimensions[col].width = largeur
    wb.save(chemin)
    wb.close()
    return chemin
