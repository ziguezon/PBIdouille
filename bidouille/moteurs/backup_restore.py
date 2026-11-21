# -*- coding: utf-8 -*-
"""Sauvegardes horodatées ET restauration, partagées par tous les outils.

Chaque outil qui écrit dans un projet PBIP copie d'abord les fichiers touchés
dans `<projet>\\_backupsPBIdouille\\_<outil>_backups\\<horodatage>\\`. Ces copies
étaient jusqu'ici « à plat » : le nom du fichier ne disait pas d'où il venait,
donc restaurer voulait dire retrouver la bonne destination à la main.

Deux règles de ménage, pour que le dossier du projet reste lisible :

  - tout est regroupé sous UN dossier parent (`_backupsPBIdouille\\`) au lieu
    de semer trois dossiers à la racine du projet — `backup_root()` le
    construit, `migrate_legacy()` range ceux d'avant ;
  - chaque outil ne garde que ses `MAX_SESSIONS` sauvegardes les plus
    récentes (`prune()`, appelé automatiquement par `BackupSession.close()`).
    Le compte est PAR OUTIL : une propagation ne doit pas faire disparaître
    l'historique du wireframe, dont le Ctrl+Z s'appuie dessus.

Ce module ajoute un **manifeste** (`manifeste.json`) à côté des copies : pour
chaque fichier, son chemin d'origine RELATIF au projet et ce qui lui est
arrivé (modifié / supprimé). Restaurer devient alors mécanique.

  - BackupSession : à utiliser côté outil (save() puis close()) ;
  - list_sessions() : toutes les sauvegardes d'un projet, la plus récente
    d'abord, tous outils confondus ;
  - restore_session() : remet les fichiers en place — en sauvegardant D'ABORD
    l'état courant, pour qu'une restauration soit elle-même annulable.

Les noms de fichiers de sauvegarde restent ceux que chaque outil utilisait
(`save(..., name=...)`) : les anciens dossiers restent lisibles, et le
wireframe continue de retrouver ses copies par convention pour son Ctrl+Z.

Les sauvegardes ANTÉRIEURES à ce module n'ont pas de manifeste : leur cible
est alors retrouvée en recalculant, pour chaque fichier candidat du projet, le
nom aplati qu'il aurait eu (déterministe — aucune devinette), avec repli sur
`definition\\tables\\` pour un .tmdl dont la table a été supprimée.

Aucune dépendance Qt : utilisable depuis les scripts en ligne de commande
comme depuis PBIdouille.
"""

from __future__ import annotations  # annotations paresseuses : Python 3.8+

import json
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path

MANIFEST = "manifeste.json"

# dossier de sauvegarde -> outil qui l'alimente (ordre = ordre d'affichage)
BACKUP_ROOTS = {
    "_tmdl_backups": "ChopChop",
    "_propagate_backups": "Propagation",
    "_wireframe_backups": "Wireframe",
    "_indicateurs_backups": "Excel des indicateurs",
}

# dossier parent qui les rassemble, à la racine du projet
PARENT = "_backupsPBIdouille"

# sauvegardes conservées PAR OUTIL ; au-delà, la plus ancienne s'efface toute
# seule. Ces copies sont un filet pour les dernières opérations, pas une
# archive : dix suffisent, et il n'y a plus de ménage à faire à la main.
MAX_SESSIONS = 10

MODIFIED = "modifié"   # le fichier existait : la copie le remet tel qu'il était
DELETED = "supprimé"   # l'opération l'a effacé : restaurer le RECRÉE
# le fichier n'existait PAS au moment de la sauvegarde : restaurer doit donc
# l'EFFACER. Sans cette troisième valeur, annuler une restauration qui a
# recréé un fichier serait impossible (rien à copier pour exprimer « absent »).
ABSENT = "absent"


def _stamp() -> str:
    """Horodatage à la microseconde : deux opérations rapprochées ne peuvent
    pas partager (ni écraser) un même dossier."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


# ------------------------------------------------------- où vivent les copies

def backup_root(project_root, folder: str) -> Path:
    """Dossier de sauvegarde d'un outil : `<projet>\\_backupsPBIdouille\\<folder>`.

    Passe par ici plutôt que de composer le chemin à la main — c'est le seul
    endroit qui décide de la disposition."""
    return Path(project_root) / PARENT / folder


def project_of(tool_root) -> Path:
    """Projet auquel appartient un dossier d'outil, qu'il soit rangé sous
    `PARENT\\` (disposition actuelle) ou resté à la racine (les anciens). Le
    manifeste stocke des chemins RELATIFS au projet : se tromper de racine
    d'un cran restaurerait à côté."""
    parent = Path(tool_root).parent
    return parent.parent if parent.name == PARENT else parent


def tool_roots(project_root, roots=None) -> list:
    """Dossiers d'outils à examiner pour ce projet : ceux rangés sous
    `PARENT\\`, PLUS ceux restés à la racine. Les anciennes sauvegardes
    demeurent donc listables et restaurables même sans rangement."""
    project_root = Path(project_root)
    out = []
    for folder in (roots or BACKUP_ROOTS):
        for base in (project_root / PARENT / folder, project_root / folder):
            if base.is_dir():
                out.append(base)
    return out


def abandonner(session) -> None:
    """Oublie une session dont l'écriture a échoué : rien n'a changé, sa copie
    ne décrit aucune opération."""
    if session.dir.exists():
        shutil.rmtree(session.dir, ignore_errors=True)


class BackupSession:
    """Une opération = un dossier horodaté + son manifeste.

        s = BackupSession(racine, "ChopChop", projet)
        s.save(chemin)                       # avant d'écrire
        s.save(chemin, action=DELETED)       # avant de supprimer
        s.close("3 mesures, 1 table")        # écrit le manifeste

    Rien n'est créé sur le disque tant qu'aucun fichier n'est sauvegardé."""

    def __init__(self, root, tool: str, project_root, stamp: str | None = None,
                 protect=()):
        self.dir = Path(root) / (stamp or _stamp())
        self.tool = tool
        self.project_root = Path(project_root)
        self.entries: list[dict] = []
        self._used: set = set()
        self._cibles: dict = {}     # cible résolue -> copie (1re sauvegarde)
        # sessions que le ménage de close() ne doit pas emporter, même si
        # elles sortent des MAX_SESSIONS plus récentes (cf. restore_session)
        self.protect = [Path(p) for p in protect]

    # -- écriture -----------------------------------------------------------

    def _rel(self, path: Path) -> str:
        """Chemin relatif au projet (le manifeste reste valide si le dossier
        est déplacé/renommé) ; absolu en secours si le fichier est hors projet."""
        try:
            return path.resolve().relative_to(self.project_root.resolve()).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def _unique(self, name: str, path: Path) -> str:
        """Nom de copie libre. Deux fichiers homonymes dans des dossiers
        différents ne doivent pas s'écraser (le manifeste, lui, garde le vrai
        chemin) : on préfixe alors par le dossier parent, puis on numérote."""
        if name not in self._used:
            return name
        stem, suffix = Path(name).stem, Path(name).suffix
        candidate = f"{path.parent.name}_{stem}{suffix}"
        i = 2
        while candidate in self._used:
            candidate = f"{path.parent.name}_{stem}_{i}{suffix}"
            i += 1
        return candidate

    def save(self, path, *, action: str = MODIFIED, name: str | None = None):
        """Copie `path` dans la session et enregistre son origine. `name` force
        le nom de la copie (conventions historiques des outils). Retourne le
        chemin de la copie, ou None si la source n'existe pas.

        Un fichier DÉJÀ sauvegardé dans cette session ne l'est pas deux fois :
        une session décrit l'état d'AVANT l'opération, donc c'est la PREMIÈRE
        copie qui vaut. Sans ce garde-fou, une opération qui touche deux fois le
        même fichier (une propagation en plusieurs passes, par exemple) y
        déposait une seconde copie — celle de l'état intermédiaire — et comme
        la restauration applique le manifeste dans l'ordre, annuler rendait
        l'état du milieu de l'opération au lieu de celui du début."""
        path = Path(path)
        if not path.exists():
            return None
        deja = self._cibles.get(path.resolve())
        if deja is not None:
            return deja
        self.dir.mkdir(parents=True, exist_ok=True)
        name = self._unique(name or path.name, path)
        self._used.add(name)
        shutil.copy2(path, self.dir / name)   # octet pour octet, date conservée
        self.entries.append({"sauvegarde": name, "cible": self._rel(path),
                             "action": action})
        self._cibles[path.resolve()] = self.dir / name
        return self.dir / name

    def mark_absent(self, path):
        """Note qu'à cet instant `path` n'existe PAS. Restaurer la session
        effacera donc ce fichier. Aucune copie n'est faite (il n'y a rien à
        copier) — c'est la seule façon d'exprimer « ce fichier ne doit pas
        exister », et donc de rendre annulable une restauration qui recrée."""
        path = Path(path)
        self.entries.append({"sauvegarde": "", "cible": self._rel(path),
                             "action": ABSENT})

    def close(self, summary: str = ""):
        """Écrit le manifeste, puis fait le ménage du dossier de l'outil (on
        n'y garde que les MAX_SESSIONS plus récentes). Sans entrée : ne crée
        rien et retourne None (pas de dossier vide qui pollue la liste)."""
        if not self.entries:
            return None
        self.dir.mkdir(parents=True, exist_ok=True)   # session « absent » seule
        (self.dir / MANIFEST).write_text(json.dumps({
            "outil": self.tool,
            "horodatage": self.dir.name,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "racine": str(self.project_root),
            "resume": summary,
            "fichiers": self.entries,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        prune(self.dir.parent, protect=[self.dir] + self.protect)
        return self.dir


# ---------------------------------------------------------------- lecture

def _infer_entries(session_dir: Path, project_root: Path) -> list[dict]:
    """Cibles d'une sauvegarde SANS manifeste (antérieure à ce module).

    Aucune devinette : on recalcule, pour chaque fichier candidat du projet, le
    nom aplati qu'il aurait porté, et on compare. Seul cas non résolu par cet
    index : un fichier que l'opération a SUPPRIMÉ (il n'existe plus, donc
    n'est plus candidat) — un .tmdl retombe alors sur `definition\\tables\\`,
    l'emplacement de toute table, et est marqué « deviné »."""
    index: dict = {}
    for vj in project_root.glob("*.Report/definition/pages/*/visuals/*/visual.json"):
        index.setdefault(f"{vj.parents[2].name}_{vj.parent.name}.json", vj)  # propagation
        index.setdefault(f"{vj.parent.name}_visual.json", vj)                # wireframe
    for tm in project_root.glob("*.SemanticModel/definition/**/*.tmdl"):
        index.setdefault(tm.name, tm)

    tables_dirs = sorted(project_root.glob("*.SemanticModel/definition/tables"))
    out: list[dict] = []
    for f in sorted(session_dir.iterdir()):
        if f.is_dir() or f.name == MANIFEST:
            continue
        target = index.get(f.name)
        if target is not None:
            out.append({"sauvegarde": f.name,
                        "cible": target.relative_to(project_root).as_posix(),
                        "action": MODIFIED})
        elif f.suffix.lower() == ".tmdl" and tables_dirs:
            out.append({"sauvegarde": f.name,
                        "cible": (tables_dirs[0] / f.name)
                                 .relative_to(project_root).as_posix(),
                        "action": DELETED, "devine": True})
        else:
            out.append({"sauvegarde": f.name, "cible": None, "action": MODIFIED})
    return out


def session_info(session_dir, project_root=None) -> dict:
    """Décrit une sauvegarde : outil, date, résumé, fichiers (avec leur cible).
    Lit le manifeste s'il existe, sinon reconstitue (cf. _infer_entries)."""
    session_dir = Path(session_dir)
    root_dir = session_dir.parent
    projet_selectionne = project_root is not None
    project_root = Path(project_root) if projet_selectionne else project_of(root_dir)
    man = session_dir / MANIFEST
    info = {}
    if man.exists():
        try:
            info = json.loads(man.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            info = {}
    if info.get("fichiers"):
        info["manifeste"] = True
        # Une copie du projet emporte le manifeste et son ancienne racine.
        # Une session archivée à part, ouverte seule, conserve sa racine enregistrée.
        if projet_selectionne or root_dir.name in BACKUP_ROOTS:
            info["racine"] = str(project_root)
        else:
            info.setdefault("racine", str(project_root))
    else:
        info = {"outil": BACKUP_ROOTS.get(root_dir.name, root_dir.name.strip("_")),
                "horodatage": session_dir.name,
                "date": _pretty_stamp(session_dir),
                "racine": str(project_root),
                "resume": "",
                "fichiers": _infer_entries(session_dir, project_root),
                "manifeste": False}
    info["dossier"] = str(session_dir)
    info["n_fichiers"] = len(info["fichiers"])
    info["n_orphelins"] = sum(1 for e in info["fichiers"] if not e.get("cible"))
    return info


def _pretty_stamp(session_dir: Path) -> str:
    """« 2026-07-28 14:30:00 » depuis le nom du dossier, sinon depuis sa date
    de modification."""
    name = session_dir.name
    try:
        return datetime.strptime(name[:15], "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.fromtimestamp(session_dir.stat().st_mtime) \
                       .strftime("%Y-%m-%d %H:%M:%S")


def list_sessions(project_root, roots=None) -> list[dict]:
    """Toutes les sauvegardes d'un projet, la PLUS RÉCENTE d'abord, tous
    outils confondus. `roots` restreint aux dossiers voulus."""
    project_root = Path(project_root)
    out: list[dict] = []
    for base in tool_roots(project_root, roots):
        for session in base.iterdir():
            if session.is_dir():
                out.append(session_info(session, project_root))
    out.sort(key=lambda i: i["horodatage"], reverse=True)
    return out


# ------------------------------------------------------------------- ménage

def _rmtree(path) -> None:
    """rmtree qui lève l'attribut lecture-seule avant de réessayer : sous
    Windows/OneDrive, les copies héritent parfois d'attributs qui font échouer
    la suppression en « Accès refusé »."""
    def onerror(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(str(path), onerror=onerror)


def _is_session(d: Path) -> bool:
    """Un dossier de sauvegarde, et pas autre chose posé là à la main : son
    nom commence par une date, ou il porte un manifeste. Le ménage n'efface
    que ça — il ne devine jamais."""
    if not d.is_dir():
        return False
    return (d.name[:8].isdigit() and len(d.name) >= 8) or (d / MANIFEST).exists()


def sessions_of(tool_root) -> list[Path]:
    """Sauvegardes d'un dossier d'outil, de la PLUS RÉCENTE à la plus
    ancienne. Le tri passe par la date lue (nom horodaté, sinon date du
    dossier) : les anciens noms `%Y%m%d_%H%M%S` et les nouveaux, à la
    microseconde, se rangent donc ensemble."""
    tool_root = Path(tool_root)
    if not tool_root.is_dir():
        return []
    sessions = [d for d in tool_root.iterdir() if _is_session(d)]
    sessions.sort(key=lambda d: (_pretty_stamp(d), d.name), reverse=True)
    return sessions


def prune(tool_root, keep: int = MAX_SESSIONS, protect=(), log=None) -> list:
    """N'y garde que les `keep` sauvegardes les plus récentes et retourne les
    noms de celles effacées.

    `protect` met des sessions hors d'atteinte quel que soit leur âge : une
    restauration lit la sauvegarde choisie APRÈS avoir écrit celle de l'état
    courant, et le ménage déclenché par cette écriture ne doit surtout pas
    emporter celle qu'on est en train de restaurer."""
    log = log or (lambda *_: None)
    gardes = {Path(p).resolve() for p in protect}
    efface = []
    for d in sessions_of(tool_root)[max(keep, 0):]:
        if d.resolve() in gardes:
            continue
        try:
            _rmtree(d)
        except OSError as e:
            log(f"⚠ ménage : {d.name} non effacé ({e})")
            continue
        efface.append(d.name)
    if efface:
        log(f"Ménage : {len(efface)} vieille(s) sauvegarde(s) effacée(s) "
            f"(on en garde {keep}).")
    return efface


def prune_all(project_root, keep: int = MAX_SESSIONS, log=None) -> list:
    """Le même ménage, sur TOUS les dossiers d'outils d'un projet. Appelé au
    chargement d'un projet : la règle s'applique dès l'ouverture, sans
    attendre la prochaine écriture."""
    efface = []
    for base in tool_roots(project_root):
        efface += [base.name + "\\" + n for n in prune(base, keep, log=log)]
    return efface


def migrate_legacy(project_root, log=None) -> list:
    """Range sous `PARENT\\` les dossiers de sauvegarde restés à la racine du
    projet, et retourne ce qui a bougé.

    Rien n'est fusionné de force : une session dont l'horodatage existe déjà
    de l'autre côté est laissée où elle est plutôt qu'écrasée. Le contenu des
    sauvegardes n'est jamais touché — seul leur rangement change."""
    log = log or (lambda *_: None)
    project_root = Path(project_root)
    bouge = []
    for folder in BACKUP_ROOTS:
        ancien = project_root / folder
        if not ancien.is_dir():
            continue
        nouveau = project_root / PARENT / folder
        nouveau.mkdir(parents=True, exist_ok=True)
        for d in list(ancien.iterdir()):
            cible = nouveau / d.name
            if cible.exists():
                log(f"⚠ {folder}\\{d.name} existe déjà rangé, laissé en place.")
                continue
            try:
                shutil.move(str(d), str(cible))
            except OSError as e:
                log(f"⚠ {folder}\\{d.name} non déplacé ({e})")
                continue
            bouge.append(f"{folder}\\{d.name}")
        try:                       # le dossier vidé n'a plus de raison d'être
            ancien.rmdir()
        except OSError as e:
            # sous OneDrive, le dossier reste parfois verrouillé juste après
            # avoir été vidé. Ce n'est pas grave (rien n'y est plus lu) et le
            # prochain chargement du projet réessaie — mais on le DIT, sinon
            # le voir traîner ferait croire que rien n'a bougé.
            log(f"⚠ {folder}\\ vidé mais non supprimé ({e}), sans effet, "
                "il partira au prochain chargement.")
    if bouge:
        log(f"{len(bouge)} sauvegarde(s) rangée(s) sous {PARENT}\\.")
    return bouge


# ------------------------------------------------------------ restauration

def restore_session(session_dir, project_root=None, *, dry_run: bool = False,
                    log=None) -> dict:
    """Remet en place les fichiers d'une sauvegarde.

    L'état COURANT de chaque fichier touché est d'abord copié dans une
    nouvelle session « Restauration » : revenir en arrière sur une
    restauration se fait donc comme n'importe quelle autre annulation.

    Un fichier supprimé par l'opération est recréé (dossiers parents compris).
    Un fichier dont la cible est inconnue (vieille sauvegarde, index muet) est
    ignoré et listé dans `ignorés` — jamais écrit au hasard.

    ⚠ Ensuite, fermer Desktop SANS enregistrer et rouvrir : il ne relit les
    fichiers qu'à l'ouverture et les réécrirait à l'enregistrement."""
    log = log or (lambda *_: None)
    session_dir = Path(session_dir)
    info = session_info(session_dir, project_root)
    root = Path(info["racine"])

    plan, skipped = [], []
    for entry in info["fichiers"]:
        action = entry.get("action", MODIFIED)
        if not entry.get("cible"):
            skipped.append(entry.get("sauvegarde") or "?")
            continue
        if action == ABSENT:                    # à EFFACER, rien à copier
            plan.append((None, Path(entry["cible"]), ABSENT))
            continue
        src = session_dir / entry["sauvegarde"]
        if not src.exists():
            skipped.append(entry["sauvegarde"])
            continue
        plan.append((src, Path(entry["cible"]), action))

    report = {"restaurés": [], "supprimés": [], "ignorés": skipped,
              "sauvegarde_avant": None, "dossier": str(session_dir),
              "outil": info.get("outil", "")}
    if dry_run or not plan:
        report["restaurés"] = [str(d) for _s, d, a in plan
                               if a != ABSENT]
        report["supprimés"] = [str(d) for _s, d, a in plan
                               if a == ABSENT]
        return report

    # filet : l'état courant part dans sa propre session avant d'être écrasé.
    # Un fichier actuellement ABSENT est noté comme tel — sinon annuler cette
    # restauration ne saurait pas qu'il faut le ré-effacer.
    # `protect` : cette écriture déclenche le ménage du dossier, qui ne doit
    # pas emporter la sauvegarde qu'on n'a pas encore fini de relire.
    undo = BackupSession(session_dir.parent, "Restauration", root,
                         protect=[session_dir])
    for _src, cible, _action in plan:
        dest = root / cible
        if dest.exists():
            undo.save(dest)
        else:
            undo.mark_absent(dest)
    undo_dir = undo.close(f"état avant restauration de {session_dir.name}")
    if undo_dir:
        report["sauvegarde_avant"] = str(undo_dir)

    for src, cible, action in plan:
        dest = root / cible
        if action == ABSENT:
            if dest.exists():
                dest.unlink()
                # dossier de visuel PBIR devenu vide : le laisser traînerait un
                # répertoire fantôme dans le rapport
                try:
                    if dest.parent.is_dir() and not any(dest.parent.iterdir()):
                        dest.parent.rmdir()
                except OSError:
                    pass
                report["supprimés"].append(str(cible))
                log(f"effacé : {cible}  (absent à la sauvegarde)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        report["restaurés"].append(str(cible))
        log(f"restauré : {cible}"
            + ("  (fichier recréé)" if action == DELETED else ""))
    return report
