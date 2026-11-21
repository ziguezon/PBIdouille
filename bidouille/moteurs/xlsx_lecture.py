# -*- coding: utf-8 -*-
"""Lecture d'un classeur Excel qui RELÂCHE toujours le fichier.

openpyxl en mode `read_only` ne charge pas le classeur en mémoire : il garde
le .xlsx OUVERT et y lit à la demande. Tant que `close()` n'a pas été appelé,
le fichier reste tenu par le processus — et sous Windows, enregistrer depuis
Excel revient à écrire un temporaire puis à le SUBSTITUER au fichier, ce qu'un
handle ouvert fait échouer. D'où le « je ne peux plus enregistrer
TD_Indicateurs ».

Le symptôme était intermittent, et c'est le plus traître : les objets openpyxl
se référencent en cycle (classeur ↔ feuille), donc le compteur de références
ne les libère pas. Il faut attendre un passage du ramasse-miettes, qui arrive
quand il arrive — parfois tout de suite, parfois bien après. Le verrou
semblait donc aléatoire alors qu'il était systématique.

Une seule porte d'entrée ici, avec un `finally` : on ne peut plus oublier de
refermer, ni sur le chemin normal ni sur une erreur en cours de lecture.

Et comme la lecture se fait sur un INSTANTANÉ copié dans le temporaire, le
temps pendant lequel on touche au classeur de l'usager tombe à une copie
d'octets : on peut garder Excel ouvert dessus et l'enregistrer sans se cogner
à l'outil. Les appelants, eux, ne gardent RIEN en cache ici — c'est à la
couche UI de décider quand relire (au démarrage, puis à chaque exécution).
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from copy import copy
from pathlib import Path


def lire_lignes(xlsx, sheet=None, max_rows=None) -> list:
    """Lignes d'une feuille (tuples de valeurs), fichier RENDU au retour.

    `sheet` : nom de la feuille, None pour la première.
    `max_rows` : s'arrêter après N lignes (l'en-tête seul, par exemple) —
    inutile de streamer tout un classeur pour lire sa première ligne.

    On lit un INSTANTANÉ : le classeur est copié dans le dossier temporaire,
    puis c'est la copie qu'openpyxl analyse. La fenêtre pendant laquelle on
    touche au fichier de l'usager se réduit ainsi à une copie d'octets
    (quelques millisecondes) au lieu de toute la durée de l'analyse XML — et
    Excel peut enregistrer par-dessus sans se heurter à nous. Le classeur fait
    quelques dizaines de Ko : la copie ne coûte rien.

    Lève ImportError si openpyxl manque : les appelants retombent alors sur
    pandas, qui, lui, referme tout seul."""
    import openpyxl

    source = Path(xlsx)
    dossier = tempfile.mkdtemp(prefix="pbidouille_xlsx_")
    copie = Path(dossier) / source.name
    try:
        shutil.copy2(source, copie)          # seul moment où l'on tient l'original
        wb = openpyxl.load_workbook(copie, read_only=True, data_only=True)
        try:
            ws = wb[sheet] if sheet else wb.worksheets[0]
            return list(ws.iter_rows(max_row=max_rows, values_only=True))
        finally:
            wb.close()
    finally:
        shutil.rmtree(dossier, ignore_errors=True)


def valeur_cellule(texte: str):
    """Ce qu'on écrit dans une cellule : un nombre s'il en a la forme, sinon le
    texte tel quel (du DAX, par exemple). Vide : rien."""
    t = (texte or "").strip()
    if not t:
        return None
    if re.fullmatch(r"[+-]?\d+", t):
        return int(t)
    if re.fullmatch(r"[+-]?\d+\.\d+", t):
        return float(t)
    return t


def _entetes(ws) -> dict:
    """{en-tête en minuscules : numéro de colonne} de la 1re ligne."""
    out = {}
    for c in range(1, ws.max_column + 1):
        h = ws.cell(row=1, column=c).value
        if h is not None and str(h).strip():
            out[str(h).strip().lower()] = c
    return out


def _substituer(wb, source, avant_ecriture) -> None:
    """Écrit le classeur à côté, puis le substitue d'un coup : un Excel ouvert
    fait échouer la substitution (PermissionError) sans rien abîmer."""
    with tempfile.NamedTemporaryFile(dir=source.parent, prefix="~pbidouille_",
                                     suffix=source.suffix, delete=False) as fichier:
        temp = Path(fichier.name)
    try:
        wb.save(temp)
        if avant_ecriture:
            avant_ecriture(source)
        os.replace(temp, source)
    finally:
        if temp.exists():
            temp.unlink()


def ajouter_colonne(xlsx, cle, nom, valeurs=None, avant_ecriture=None) -> int:
    """Ajoute la colonne `nom` à la 1re feuille ; `valeurs` : {clé : valeur}.
    Rend le nombre de cellules remplies.

    Un tableau Excel qui finit juste avant la colonne est agrandi : sans cela
    la colonne resterait à côté du tableau, invisible pour ce qui le lit.
    `avant_ecriture(chemin)` est appelé juste avant, pour la sauvegarde."""
    import openpyxl
    from openpyxl.utils import get_column_letter as lettre, range_boundaries
    from openpyxl.worksheet.table import TableColumn

    source = Path(xlsx)
    valeurs = valeurs or {}
    wb = openpyxl.load_workbook(source)       # sans data_only : garde les formules
    try:
        ws = wb.worksheets[0]
        entetes = _entetes(ws)
        if cle.lower() not in entetes:
            raise ValueError(f"Colonne clé « {cle} » absente de {source.name}.")
        if nom.lower() in entetes:
            raise ValueError(f"La colonne « {nom} » existe déjà dans {source.name}.")
        derniere = max(entetes.values())
        col, col_cle = derniere + 1, entetes[cle.lower()]

        def poser(ligne, valeur):
            cellule = ws.cell(row=ligne, column=col, value=valeur)
            cellule._style = copy(ws.cell(row=ligne, column=derniere)._style)

        poser(1, nom)
        n = 0
        for r in range(2, ws.max_row + 1):
            k = ws.cell(row=r, column=col_cle).value
            v = valeurs.get(str(k).strip()) if k is not None else None
            if v is not None:
                poser(r, v)
                n += 1

        for t in ws.tables.values():
            c1, l1, c2, l2 = range_boundaries(t.ref)
            if l1 == 1 and c2 == derniere:
                t.ref = f"{lettre(c1)}{l1}:{lettre(col)}{l2}"
                if t.autoFilter is not None:
                    t.autoFilter.ref = t.ref
                t.tableColumns.append(
                    TableColumn(id=max(x.id for x in t.tableColumns) + 1, name=nom))
        _substituer(wb, source, avant_ecriture)
    finally:
        wb.close()
    return n


def ecrire_cellule(xlsx, cle, kpi, colonne, valeur, avant_ecriture=None) -> None:
    """Écrit la valeur d'un KPI dans une colonne existante."""
    import openpyxl

    source = Path(xlsx)
    wb = openpyxl.load_workbook(source)
    try:
        ws = wb.worksheets[0]
        entetes = _entetes(ws)
        for nom in (cle, colonne):
            if nom.lower() not in entetes:
                raise ValueError(f"Colonne « {nom} » absente de {source.name}.")
        col_cle, col = entetes[cle.lower()], entetes[colonne.lower()]
        for r in range(2, ws.max_row + 1):
            k = ws.cell(row=r, column=col_cle).value
            if k is not None and str(k).strip() == kpi:
                # pas value= : openpyxl y ignore None, et la cellule resterait pleine
                ws.cell(row=r, column=col).value = valeur
                break
        else:
            raise ValueError(f"« {kpi} » n'a pas de ligne dans {source.name}.")
        _substituer(wb, source, avant_ecriture)
    finally:
        wb.close()
