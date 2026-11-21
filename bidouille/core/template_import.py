# -*- coding: utf-8 -*-
"""Import de modèles de visuels depuis un PBIP « gabarit » vers un rapport
cible (format PBIR).

Un MODÈLE = un élément RACINE d'une page du gabarit : un groupe de visuels
(nom = displayName du groupe, posé dans le volet Sélection de Desktop) ou un
visuel isolé. L'import copie le sous-arbre complet avec de NOUVEAUX ids
(20 hex ; dossier == champ « name », l'invariant PBIR), remappe les
parentGroupName, régénère les ids de filtres, renumérote z/tabOrder au-dessus
du max de la page cible, et conserve x/y/largeur/hauteur À L'IDENTIQUE : les
enfants sont relatifs à leur parent, et la racine garde sa position d'origine
du gabarit (pensé pour les en-têtes/pieds de page standard).

Faits PBIR vérifiés sur les rapports du projet : un visuel = un seul fichier
pages/<pid>/visuals/<id>/visual.json ; AUCUN registre d'ids ailleurs
(page.json / pages.json / report.json n'y font pas référence) ; la seule
référence inter-visuels est parentGroupName. ⚠ Le modèle importé référence les
tables/champs du modèle sémantique du GABARIT — la compatibilité avec le
modèle du rapport cible est à la charge de l'utilisateur."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path

from core import report_reader          # met aussi moteurs\ sur le sys.path

import backup_restore as br             # noqa: E402  (ménage des sauvegardes)


def list_models(template_report_dir) -> list:
    """Modèles offerts par le gabarit : groupes RACINE (nom = displayName) et
    visuels racine isolés (nom = titre, sinon type). Retourne
    [{page_id, page_display, root_id, name, kind, x, y, w, h, n_files}]
    où n_files = taille du sous-arbre (racine incluse)."""
    template_report_dir = Path(template_report_dir)
    out = []
    for page in report_reader.pages(template_report_dir):
        items = report_reader.visuals(template_report_dir, page["id"])
        ids = {d["id"] for d in items}
        kids: dict = {}
        for d in items:
            if d["parent"] in ids:
                kids.setdefault(d["parent"], []).append(d["id"])

        def subtree_size(rid):
            n, stack = 0, [rid]
            while stack:
                n += 1
                stack.extend(kids.get(stack.pop(), []))
            return n

        for d in items:
            if d["parent"] in ids:
                continue                       # pas une racine
            if d["is_group"]:
                name, kind = (d["group_name"] or "groupe"), "groupe"
            else:
                name, kind = (d["title"] or d["type"]), d["type"]
            out.append({
                "page_id": page["id"], "page_display": page["display"],
                "root_id": d["id"], "name": name, "kind": kind,
                "x": d["x"], "y": d["y"], "w": d["w"], "h": d["h"],
                "n_files": subtree_size(d["id"]),
            })
    return out


def _mint_id(used: set) -> str:
    """Nouvel id de visuel 20 hex, unique vs `used` (ajouté dedans)."""
    for _ in range(1000):
        nid = secrets.token_hex(10)
        if nid not in used:
            used.add(nid)
            return nid
    raise ValueError("impossible de générer un id de visuel unique (1000 essais)")


def import_model(template_report_dir, template_page_id, root_id,
                 target_report_dir, target_page_id, backup_root):
    """Copie le sous-arbre `root_id` de la page gabarit vers la page cible.
    Écrit un manifeste (undo = supprimer les dossiers listés) sous
    backup_root/<horodatage>/import_manifest.txt. Retourne
    (nouvel_id_racine, [chemins visual.json écrits], chemin_du_manifeste)."""
    template_report_dir = Path(template_report_dir)
    target_report_dir = Path(target_report_dir)

    # 1. jsons BRUTS de la page gabarit (id -> contenu complet)
    raw: dict = {}
    src_dir = (template_report_dir / "definition" / "pages"
               / template_page_id / "visuals")
    for vj in sorted(src_dir.glob("*/visual.json")):
        data = json.loads(vj.read_text(encoding="utf-8"))
        raw[data.get("name") or vj.parent.name] = data
    if root_id not in raw:
        raise ValueError(f"modèle introuvable dans le gabarit : {root_id}")

    # 2. sous-arbre : clôture par parentGroupName (les ensembles évitent tout
    #    cycle) ; racine d'abord, puis z croissant (ordre interne préservé)
    members = {root_id}
    changed = True
    while changed:
        changed = False
        for vid, data in raw.items():
            if vid not in members and data.get("parentGroupName") in members:
                members.add(vid)
                changed = True
    ordered = [root_id] + sorted(
        (v for v in members if v != root_id),
        key=lambda v: (raw[v].get("position") or {}).get("z", 0))

    # 3. ids déjà pris : rapport cible ENTIER (couvre aussi gabarit == cible)
    used = {p.name for p in target_report_dir.glob("definition/pages/*/visuals/*")}
    mapping = {vid: _mint_id(used) for vid in ordered}

    # 4. base z/tabOrder au-dessus du max de la page cible (z est page-wide)
    tgt = report_reader.visuals(target_report_dir, target_page_id)
    base = ((int(max(d["z"] for d in tgt)) // 1000) + 1) * 1000 if tgt else 0

    session = br.BackupSession(backup_root, "Import Wireframe", br.project_of(backup_root))
    visuels = target_report_dir / "definition" / "pages" / target_page_id / "visuals"
    for ident in mapping.values():
        session.mark_absent(visuels / ident / "visual.json")
    stamp_dir = session.close(f"Import de {len(mapping)} visuel(s)")
    written = []
    for i, vid in enumerate(ordered):
        data = json.loads(json.dumps(raw[vid]))        # copie profonde
        data["name"] = mapping[vid]
        if vid == root_id:
            data.pop("parentGroupName", None)          # défensif : racine
        elif data.get("parentGroupName") in mapping:
            data["parentGroupName"] = mapping[data["parentGroupName"]]
        pos = data.setdefault("position", {})
        pos["z"] = base + i * 1000
        pos["tabOrder"] = base + i * 1000
        # ids de filtres régénérés (visual-locaux, mais évite les doublons si
        # gabarit == cible)
        for f in (data.get("filterConfig") or {}).get("filters") or []:
            if isinstance(f, dict) and "name" in f:
                f["name"] = secrets.token_hex(10)
        dst = (target_report_dir / "definition" / "pages" / target_page_id
               / "visuals" / mapping[vid] / "visual.json")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        written.append(str(dst))

    # 5. manifeste
    manifest = stamp_dir / "import_manifest.txt"
    lines = [
        "# Import de gabarit · " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        f"# source : {template_report_dir}",
        f"# modèle : page {template_page_id} / racine {root_id}",
        f"# cible  : {target_report_dir} / page {target_page_id}",
        "# undo   : supprimer les dossiers des fichiers listés ci-dessous",
    ] + written
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mapping[root_id], written, manifest
