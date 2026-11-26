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
modèle du rapport cible est à la charge de l'utilisateur.

INDICATEURS. Un gabarit vient d'un autre rapport : ses visuels citent SES
indicateurs. `indicateurs_du_modele` les retrouve (mesures citées dont le nom
est un ICP ou une de ses déclinaisons, « Body Fat % 30d avg » -> « Body Fat % »,
et valeurs de filtre ou de segment égales à un ICP), et `import_model` les
remplace à la copie : « Body Fat % 30d avg » devient « Weight 30d avg »
partout où la mesure est citée (champ, queryRef, nativeQueryRef…), et le
filtre 'Body Fat %' devient 'Weight'. Le reste du texte (titres) n'est pas
touché. `mesures_absentes` dit ensuite ce que le rapport cible n'a pas."""

from __future__ import annotations

import json
import re
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


def _lire_page(template_report_dir, template_page_id) -> dict:
    """jsons BRUTS d'une page (id -> contenu complet)."""
    raw: dict = {}
    src_dir = (Path(template_report_dir) / "definition" / "pages"
               / template_page_id / "visuals")
    for vj in sorted(src_dir.glob("*/visual.json")):
        data = json.loads(vj.read_text(encoding="utf-8"))
        raw[data.get("name") or vj.parent.name] = data
    return raw


def _sous_arbre(raw, root_id) -> set:
    """Clôture par parentGroupName (les ensembles évitent tout cycle)."""
    members = {root_id}
    changed = True
    while changed:
        changed = False
        for vid, data in raw.items():
            if vid not in members and data.get("parentGroupName") in members:
                members.add(vid)
                changed = True
    return members


# ---- indicateurs ---------------------------------------------------------------

def _icp_de(nom, bases_par_longueur):
    """L'ICP dont `nom` est une déclinaison, par plus long préfixe d'abord
    (« Weight cible PY » -> « Weight »), ou None. La même règle que la
    génération (generate_measures.match_kpi), recopiée pour ne pas tirer le
    moteur de génération dans l'import."""
    for b in bases_par_longueur:
        if nom == b or nom.startswith(b + " "):
            return b
    return None


def _sans_quotes(valeur):
    """'Body Fat %' -> Body Fat % ; None si ce n'est pas un texte DAX."""
    if isinstance(valeur, str) and len(valeur) >= 2 \
            and valeur[0] == "'" and valeur[-1] == "'":
        return valeur[1:-1].replace("''", "'")
    return None


def _quotes(texte):
    return "'" + texte.replace("'", "''") + "'"


def _mesures_citees(obj, out):
    """Noms des mesures citées (champ « Measure » des requêtes PBIR)."""
    if isinstance(obj, dict):
        m = obj.get("Measure")
        if isinstance(m, dict) and isinstance(m.get("Property"), str):
            out.append(m["Property"])
        for v in obj.values():
            _mesures_citees(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _mesures_citees(v, out)
    return out


def _entites_mesures(obj, out):
    """Tables nommées dans les références de mesure (SourceRef.Entity)."""
    if isinstance(obj, dict):
        m = obj.get("Measure")
        if isinstance(m, dict):
            ref = (m.get("Expression") or {}).get("SourceRef") or {}
            out.add(ref.get("Entity"))
        for v in obj.values():
            _entites_mesures(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _entites_mesures(v, out)
    return out


def _litteraux(obj, out):
    """Valeurs texte des littéraux (filtres, segments, mise en forme)."""
    if isinstance(obj, dict):
        lit = obj.get("Literal")
        if isinstance(lit, dict):
            t = _sans_quotes(lit.get("Value"))
            if t is not None:
                out.append(t)
        for v in obj.values():
            _litteraux(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _litteraux(v, out)
    return out


def indicateurs_du_modele(template_report_dir, template_page_id, root_id,
                          bases) -> list:
    """Les ICP que cite un modèle du gabarit, dans l'ordre où on les
    rencontre : une mesure citée qui est un ICP de `bases` ou une de ses
    déclinaisons, ou une valeur de filtre égale à un ICP. `bases` = les ICP
    connus (ceux du gabarit, et ceux du rapport cible)."""
    raw = _lire_page(template_report_dir, template_page_id)
    if root_id not in raw:
        return []
    par_longueur = sorted(set(bases), key=len, reverse=True)
    vus: list = []
    for vid in sorted(_sous_arbre(raw, root_id)):
        data = raw[vid]
        for nom in _mesures_citees(data, []):
            b = _icp_de(nom, par_longueur)
            if b and b not in vus:
                vus.append(b)
        for t in _litteraux(data, []):
            if t in par_longueur and t not in vus:
                vus.append(t)
    return vus


def remplacer_indicateurs(data, remplacements, bases) -> int:
    """Remplace en place les ICP de `data` (un visual.json) selon
    `remplacements` {ancien: nouveau}. Retourne le nombre de remplacements.

    - une mesure citée, déclinaison d'un ancien ICP : son nom ;
    - toute AUTRE chaîne égale à une de ces mesures, ou qui finit par
      « .<mesure> » (queryRef « _mesures.Body Fat % 30d avg ») ;
    - un littéral égal à un ancien ICP ('Body Fat %', filtre ou segment).
    Chaque chaîne est lue une seule fois d'après sa valeur D'ORIGINE : un
    échange (A -> B et B -> A) ne se défait pas."""
    remplacements = {a: b for a, b in (remplacements or {}).items()
                     if a and b and a != b}
    if not remplacements:
        return 0
    par_longueur = sorted(set(bases) | set(remplacements), key=len, reverse=True)

    def nouveau(nom):
        b = _icp_de(nom, par_longueur)
        if b in remplacements:
            return remplacements[b] + nom[len(b):]
        return None

    citees = {n: nouveau(n) for n in _mesures_citees(data, [])}
    citees = {a: b for a, b in citees.items() if b}
    # « Table.Mesure » seulement pour une table qui porte des mesures citées :
    # une COLONNE du même nom ailleurs (« dim.Weight ») ne bouge pas
    entites = {e for e in _entites_mesures(data, set()) if e}
    compte = [0]

    def chaine(s):
        if s in citees:
            return citees[s]
        for e in entites:
            if s.startswith(e + ".") and s[len(e) + 1:] in citees:
                return e + "." + citees[s[len(e) + 1:]]
        return None

    def visiter(obj):
        if isinstance(obj, dict):
            m = obj.get("Measure")
            if isinstance(m, dict) and isinstance(m.get("Property"), str):
                n = citees.get(m["Property"])
                if n:
                    m["Property"] = n
                    compte[0] += 1
                for k, v in m.items():
                    if k != "Property":
                        m[k] = visiter(v)
            lit = obj.get("Literal")
            if isinstance(lit, dict):
                t = _sans_quotes(lit.get("Value"))
                n = remplacements.get(t) if t is not None else None
                if n is None and t is not None:
                    n = citees.get(t)
                if n:
                    lit["Value"] = _quotes(n)
                    compte[0] += 1
            for k, v in obj.items():
                if (k == "Measure" and isinstance(v, dict)) or \
                        (k == "Literal" and isinstance(v, dict)):
                    continue
                obj[k] = visiter(v)
            return obj
        if isinstance(obj, list):
            return [visiter(v) for v in obj]
        if isinstance(obj, str):
            n = chaine(obj)
            if n:
                compte[0] += 1
                return n
        return obj

    visiter(data)
    return compte[0]


_MESURE_TMDL = re.compile(r"^\tmeasure\s+('(?:[^']|'')+'|[^=\n]+?)\s*=", re.M)


def mesures_du_modele(model_dir) -> set:
    """Noms de toutes les mesures du modèle sémantique (toutes tables)."""
    noms = set()
    tables = Path(model_dir) / "definition" / "tables" if model_dir else None
    if not tables or not tables.is_dir():
        return noms
    for f in tables.glob("*.tmdl"):
        try:
            texte = f.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for m in _MESURE_TMDL.finditer(texte):
            n = m.group(1).strip()
            if n.startswith("'") and n.endswith("'"):
                n = n[1:-1].replace("''", "'")
            noms.add(n)
    return noms


def mesures_absentes(chemins_json, model_dir) -> list:
    """Mesures citées par des visual.json et absentes du modèle cible (triées).
    Liste vide si le modèle est illisible : on ne crie pas au loup."""
    connues = mesures_du_modele(model_dir)
    if not connues:
        return []
    manquent = set()
    for p in chemins_json:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        manquent |= {n for n in _mesures_citees(data, []) if n not in connues}
    return sorted(manquent)


def _mint_id(used: set) -> str:
    """Nouvel id de visuel 20 hex, unique vs `used` (ajouté dedans)."""
    for _ in range(1000):
        nid = secrets.token_hex(10)
        if nid not in used:
            used.add(nid)
            return nid
    raise ValueError("impossible de générer un id de visuel unique (1000 essais)")


def import_model(template_report_dir, template_page_id, root_id,
                 target_report_dir, target_page_id, backup_root,
                 remplacements=None, bases=()):
    """Copie le sous-arbre `root_id` de la page gabarit vers la page cible.
    `remplacements` {ICP du gabarit: ICP du rapport} est appliqué à chaque
    copie (voir remplacer_indicateurs ; `bases` = les ICP connus).
    Écrit un manifeste (undo = supprimer les dossiers listés) sous
    backup_root/<horodatage>/import_manifest.txt. Retourne
    (nouvel_id_racine, [chemins visual.json écrits], chemin_du_manifeste)."""
    template_report_dir = Path(template_report_dir)
    target_report_dir = Path(target_report_dir)

    # 1. jsons BRUTS de la page gabarit (id -> contenu complet)
    raw = _lire_page(template_report_dir, template_page_id)
    if root_id not in raw:
        raise ValueError(f"modèle introuvable dans le gabarit : {root_id}")

    # 2. sous-arbre ; racine d'abord, puis z croissant (ordre interne préservé)
    members = _sous_arbre(raw, root_id)
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
        remplacer_indicateurs(data, remplacements, bases)
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
    ] + [f"# indicateur : {a} -> {b}"
         for a, b in sorted((remplacements or {}).items()) if a != b] + [
        "# undo   : supprimer les dossiers des fichiers listés ci-dessous",
    ] + written
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mapping[root_id], written, manifest
