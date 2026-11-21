# -*- coding: utf-8 -*-
"""
Propage les entrées de formatage conditionnel d'un KPI « template » vers les
autres KPI, dans les visual.json d'un rapport PBIP (format PBIR).

Contexte : avec un paramètre de champ, le selector d'un objet de formatage
vise une mesure précise (ex. _mesures.Total Steps YoY %). Quand le slicer
bascule sur un autre KPI, le selector ne matche plus et le formatage
disparaît. Ce script clone chaque entrée de formatage du KPI template pour
tous les autres KPI, en adaptant les noms de mesures (selector ET mesure CF).

Usage :
  1. enregistrer dans Power BI Desktop, qui peut rester ouvert ;
  2. python propagate_cf.py
  3. fermer Desktop SANS enregistrer et rouvrir le .pbip (il ne relit les
     fichiers qu'à l'ouverture, et un enregistrement écraserait nos
     modifications).

MIROIR, pas simple recopie : le template est la seule source de vérité, donc
ce qu'il ne porte PLUS est RETIRÉ des KPI cibles (retirer l'image d'une carte
sur le KPI template la retire partout). Deux garde-fous : un visuel qui ne
porte aucune entrée du KPI template n'est jamais touché, et les couleurs
statiques « specific column » (color_matrix_by_kpi.py) sont hors périmètre.
Chaque visuel modifié est copié dans
_backupsPBIdouille\\_propagate_backups\\<horodatage>\\ avant écriture — un
retrait involontaire se défait en recopiant le fichier.

Le template a autant de « faces » que de branches : sa face Réel irrigue tout,
une entrée présente UNIQUEMENT sur une branche (ex. le style des marqueurs de
la ligne YTD) ne descend que sur cette branche.

Idempotent : relancer remplace les clones existants. Pour changer le style,
modifier le CF du KPI template dans Desktop, enregistrer, relancer.

Plusieurs familles de KPI, des exceptions : la GRILLE DES SOURCES
(propagation.json, cf. Sources et propagate_regles) — un gabarit de base pour
tout le monde, un gabarit par groupe de KPI, un gabarit par variation, et case
par case (KPI × variation), un autre KPI ou « à la main ».

La liste des KPI est lue automatiquement dans P_Indicateurs.tmdl (colonne
Indicateur), donc elle suit la génération des mesures. TARGET_KPIS permet de
forcer une liste explicite au besoin.
"""

from __future__ import annotations  # annotations paresseuses : Python 3.8+

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# backup_restore.py est le voisin de ce fichier (sauvegardes + manifeste)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_restore as br
from dossiers_mesures import folder_matches
import chemins                    # où sont les projets

# ---------------------------------------------------------------------------
# ligne de commande seulement ; l'app passe toujours le rapport ouvert
REPORT_DIR      = chemins.PROJETS / (chemins.PROJET_DEMO + ".Report")
TEMPLATE_KPI    = "Total Steps"
TARGET_KPIS     = None            # None = auto via <FIELD_PARAMETER>.tmdl ; sinon ["Weight", ...]
ENTITY          = "_mesures"      # table qui héberge les mesures
FIELD_PARAMETER = "P_Indicateurs_parCalcul" # table paramètre où lire la liste des KPI

# Branches (suffixes de mesure) à propager EN PLUS du Réel. "" (Réel) est
# toujours inclus. À partir d'un attribut posé sur UNE branche, le script
# synthétise les autres (le suffixe s'insère juste après le KPI :
# « Weight PY » -> « Weight YTD PY »). Doit correspondre aux ids de `branches`
# dans measures_config.json. [] = pas de synthèse (échange de KPI seulement).
BRANCHES        = ["YTD"]

# --- diagnostic ---
# VERBOSE : liste, pour chaque visuel, TOUS les candidats CF qui visent le KPI
#   template, en marquant lesquels sont pris comme template et lesquels sont
#   IGNORÉS (pas de dataViewWildcard) + les entrées générées. Sert à voir
#   pourquoi une branche ne se propage pas.
# DRY_RUN : n'écrit RIEN (diagnostic pur). Mettre True pour inspecter d'abord.
VERBOSE = False
DRY_RUN = False
# ---------------------------------------------------------------------------


# noms de mesures dans un TMDL : « measure 'Nom avec espaces' = » ou
# « measure Nom = ». Les apostrophes internes y sont DOUBLÉES.
MEASURE_NAME_RE = re.compile(
    r"^\tmeasure\s+(?:'((?:[^']|'')+)'|([^\s=']+))", re.M)


# chemin -> ((date, taille), texte)
_TEXTES: dict = {}


def lire_texte(chemin) -> str:
    """Le texte d'un fichier — relu seulement s'il a CHANGÉ (date, taille).

    Ouvrir un fichier coûte cher dans un dossier synchronisé (OneDrive) sous
    antivirus : plusieurs millisecondes chacun, bien plus au bureau. Lire sa
    date ne coûte presque rien. La grille des sources relisait tout le modèle
    — deux fois — et tout le rapport à chaque ouverture : c'était l'essentiel
    de son temps. Un fichier qu'on vient d'écrire a une nouvelle date : il
    est relu, jamais servi périmé."""
    p = Path(chemin)
    st = p.stat()
    cle = (st.st_mtime_ns, st.st_size)
    vu = _TEXTES.get(str(p))
    if vu is not None and vu[0] == cle:
        return vu[1]
    texte = p.read_text(encoding="utf-8")
    _TEXTES[str(p)] = (cle, texte)
    return texte


def ecrire_texte(chemin, texte) -> None:
    """Écrit, et garde le cache de lire_texte à jour : deux passes qui
    écrivent le même visuel coup sur coup (même seconde, même taille, sur un
    disque à dates grossières) ne relisent jamais l'avant-dernière version."""
    p = Path(chemin)
    p.write_text(texte, encoding="utf-8")
    st = p.stat()
    _TEXTES[str(p)] = ((st.st_mtime_ns, st.st_size), texte)


def measures_of_model(semantic_dir) -> set:
    """Tous les noms de mesures du modèle.

    Garde-fou de la propagation : elle ne doit JAMAIS écrire une référence vers
    une mesure inexistante. Une mesure COMMUNE à toutes les branches (un titre,
    un libellé, une unité) n'a pas de variante « … YTD » — lui en inventer une
    remplaçait l'attribut par une référence morte, et le visuel le perdait.

    Ensemble vide = modèle introuvable : la vérification se désactive alors
    d'elle-même plutôt que de tout bloquer."""
    noms: set = set()
    tables = Path(semantic_dir) / "definition" / "tables"
    for tmdl in sorted(tables.glob("*.tmdl")) if tables.is_dir() else []:
        for m in MEASURE_NAME_RE.finditer(lire_texte(tmdl)):
            nom = m.group(1) or m.group(2)
            if nom:
                noms.add(nom.replace("''", "'"))
    return noms


def cibles_of_model(semantic_dir, dossiers) -> set:
    """Mesures du modèle qui vivent dans l'un des `dossiers` de cibles.

    Le displayFolder est la déclaration la plus fiable de « ceci est une
    cible » : contrairement au paramètre de champ, où les cibles ne figurent
    pas toujours, le dossier est là par construction. Or c'est justement ce
    qui distingue une mesure PROPRE À SON KPI d'une mesure partagée — sans
    quoi « aucun équivalent trouvé » reste ambigu.

    Ensemble vide = aucun dossier déclaré : la règle se désactive d'elle-même."""
    dossiers = [d for d in (dossiers or ()) if str(d).strip()]
    if not dossiers:
        return set()
    out: set = set()
    tables = Path(semantic_dir) / "definition" / "tables"
    for tmdl in sorted(tables.glob("*.tmdl")) if tables.is_dir() else []:
        courante = None
        for ligne in lire_texte(tmdl).splitlines():
            m = MEASURE_NAME_RE.match(ligne + "\n")
            if m:
                courante = (m.group(1) or m.group(2) or "").replace("''", "'")
                continue
            if courante and ligne.startswith("\t\tdisplayFolder:"):
                dossier = ligne.split(":", 1)[1].strip()
                if any(folder_matches(dossier, d) for d in dossiers):
                    out.add(courante)
                courante = None
    return out


def racine_cible(nom, kpi, entity=ENTITY, cibles=None):
    """Plus long préfixe de `nom` qui est une mesure de CIBLE de ce KPI.

    « Weight cible ecartCF » (générée, hors dossier des cibles) retourne donc
    « Weight cible ». None = cette mesure ne vient pas d'une cible."""
    if not (nom and cibles):
        return None
    for prefix in (entity + ".", ""):
        if not nom.startswith(prefix):
            continue
        bare = nom[len(prefix):]
        racine = None
        for cand in cibles:
            if cand != kpi and not cand.startswith(kpi + " "):
                continue                  # jamais traverser les KPI
            if bare == cand or bare.startswith(cand + " "):
                if racine is None or len(cand) > len(racine):
                    racine = cand
        if racine is not None:
            return racine
    return None


def cible_sans_equivalent(nom, src_kpi, dst_kpi, entity=ENTITY,
                          cibles=None, known=None) -> bool:
    """La mesure vient d'une CIBLE, et le KPI visé n'a pas la sienne.

    Tous les KPI n'ont pas de cible. Sans cette règle, l'entrée atterrissait
    sur eux en pointant la cible du GABARIT — « KPI un cible » posée sur KPI
    trois — parce que la cascade de `swap_kpi_branch`, ne trouvant aucun
    équivalent, garde la mesure d'origine. Ce repli est juste pour une mesure
    PARTAGÉE (un titre commun) ; il est faux pour une cible, qui est propre à
    son KPI. Le dossier dédié tranche entre les deux."""
    racine = racine_cible(nom, src_kpi, entity, cibles)
    if racine is None:
        return False
    if not known:
        return False              # modèle illisible : on ne décide rien
    equivalente = dst_kpi + racine[len(src_kpi):]
    return equivalente not in known


def kpis_from_parameter(semantic_dir: Path, field_parameter: str = FIELD_PARAMETER) -> list[str]:
    """Extrait les KPI distincts (colonne Indicateur, 4e valeur des tuples)
    de l'expression de la table paramètre `field_parameter`."""
    tmdl = semantic_dir / "definition" / "tables" / f"{field_parameter}.tmdl"
    if not tmdl.exists():
        raise SystemExit(
            f"Introuvable : {tmdl}\n"
            f"Enregistrer le PBIP après avoir créé {field_parameter}, ou définir "
            "TARGET_KPIS explicitement."
        )
    text = lire_texte(tmdl)
    # NAMEOF\(.*?\) (et non [^)]*) pour gérer les parenthèses DANS les noms de
    # mesures, ex. NAMEOF([Weight (locf)]) : le non-greedy revient à la bonne
    # parenthèse fermante, ancrée par « ), <ordre>, "<KPI>" ». Le 4e élément
    # (Indicateur) est le nom du KPI.
    rows = re.findall(
        r'\(\s*"[^"]*"\s*,\s*NAMEOF\(.*?\)\s*,\s*\d+\s*,\s*"([^"]+)"', text
    )
    out: list[str] = []
    for kpi in rows:
        if kpi not in out:
            out.append(kpi)
    return out


# --------------------------------------------- groupes de propagation

# UN fichier par DOSSIER, à côté des .pbip : « propagation.json ». Les
# versions d'un même rapport (noms un peu différents, même dossier) gardent les
# mêmes réglages de propagation : un fichier PAR rapport les faisait diverger à
# chaque nouvelle copie. Pas dans measures_config.json, qui voyage d'un rapport
# à l'autre : y écrire des noms de KPI le rendrait faux dès sa réutilisation
# ailleurs (même raison que pour kpiTables, cf. read_kpi_tables).
#
# Contrepartie assumée : deux rapports DIFFÉRENTS dans un même dossier
# partageraient aussi leurs groupes. Un KPI absent d'un modèle y est ignoré
# (avertissement), un gabarit absent arrête la propagation en le nommant —
# jamais une écriture fausse.
#
# Avant, le fichier portait le nom du rapport (« <rapport>.propagation.json »).
# Il est encore LU en repli (groupes_a_lire), et un ancien fichier SEUL dans
# le dossier devient propagation.json à l'ouverture (migrer_groupes).
GROUPES_FICHIER = "propagation.json"
GROUPES_SUFFIXE = ".propagation.json"      # l'ancien nom, propre à un rapport


def groupes_path(report_dir) -> Path:
    """Le fichier de groupes PARTAGÉ par les rapports du dossier — celui
    qu'on écrit : <dossier du .pbip>\\propagation.json."""
    return Path(report_dir).parent / GROUPES_FICHIER


def groupes_path_ancien(report_dir) -> Path:
    """L'ancien fichier, propre à UN rapport : <rapport>.propagation.json."""
    report_dir = Path(report_dir)
    nom = report_dir.name
    if nom.endswith(".Report"):
        nom = nom[: -len(".Report")]
    return report_dir.parent / (nom + GROUPES_SUFFIXE)


def groupes_a_lire(report_dir) -> Path:
    """Le fichier à LIRE : le partagé s'il existe ; sinon l'ancien fichier de
    CE rapport, pour ne rien perdre de ce qu'il déclarait ; sinon le partagé
    (absent : pas de groupes, donc le gabarit unique d'avant)."""
    partage = groupes_path(report_dir)
    if partage.exists():
        return partage
    ancien = groupes_path_ancien(report_dir)
    return ancien if ancien.exists() else partage


def migrer_groupes(dossier, log=print):
    """Un ancien fichier SEUL dans le dossier devient propagation.json —
    renommé, pas copié : une seule source de vérité, que toutes les versions
    du rapport lisent aussitôt. Plusieurs anciens fichiers : on ne devine pas
    lequel partager ; chaque rapport lit le sien jusqu'au premier
    enregistrement des groupes, qui écrit le fichier partagé.

    Rend le chemin de propagation.json si un fichier a été renommé, sinon
    None. Jamais d'exception : au pire, on continue de lire l'ancien."""
    dossier = Path(dossier)
    partage = dossier / GROUPES_FICHIER
    if partage.exists():
        return None
    anciens = sorted(p for p in dossier.glob("*" + GROUPES_SUFFIXE)
                     if p.name != GROUPES_FICHIER)
    if len(anciens) != 1:
        return None
    try:
        anciens[0].rename(partage)
    except OSError as e:
        log(f"⚠ groupes de propagation : « {anciens[0].name} » non renommé "
            f"({e}), il reste lu tel quel.")
        return None
    log(f"Groupes de propagation : « {anciens[0].name} » renommé en "
        f"« {GROUPES_FICHIER} », partagé par tous les rapports du dossier.")
    return partage


def read_groupes(chemin) -> list:
    """Groupes de propagation : [{nom, gabarit, kpis}], `[]` si le fichier est
    absent, vide ou illisible — dans ce cas on retombe sur le gabarit unique,
    c'est-à-dire le comportement d'avant. Jamais d'exception ici : le fichier
    est facultatif."""
    if not chemin:
        return []
    p = Path(chemin)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    brut = data.get("groupes") if isinstance(data, dict) else data
    if not isinstance(brut, list):
        return []
    out = []
    for g in brut:
        if not isinstance(g, dict) or not g.get("gabarit"):
            continue
        out.append({"nom": str(g.get("nom") or g["gabarit"]),
                    "gabarit": str(g["gabarit"]),
                    "kpis": [str(k) for k in (g.get("kpis") or [])]})
    return out


def resoudre_groupes(groupes, tous_les_kpis, log=print) -> list:
    """Complète et VALIDE les groupes ; retourne [{nom, gabarit, kpis}] prêts.

    Règles :
      · un gabarit appartient toujours à son propre groupe ;
      · un groupe sans liste de KPI ramasse tous ceux que personne n'a pris
        (au plus un tel groupe) ;
      · un KPI ne peut appartenir qu'à un groupe.

    Ce qui est FATAL l'est parce qu'on ne peut pas deviner l'intention : un
    gabarit qui n'existe pas est une faute de frappe, et un KPI revendiqué deux
    fois n'a pas de gagnant naturel. Propager au hasard réécrirait un rapport
    entier de travers."""
    connus = list(tous_les_kpis or ())
    if not groupes:
        return []

    inconnus = sorted({g["gabarit"] for g in groupes if g["gabarit"] not in connus})
    if inconnus:
        raise SystemExit(
            "Gabarit de groupe introuvable parmi les KPI : "
            + ", ".join(inconnus) + ".\nKPI connus : " + ", ".join(connus))

    defauts = [g for g in groupes if not g["kpis"]]
    if len(defauts) > 1:
        raise SystemExit(
            "Plusieurs groupes par défaut (sans liste de KPI) : "
            + ", ".join(g["nom"] for g in defauts)
            + ".\nUn seul groupe peut ramasser les KPI restants.")

    pris: dict = {}          # KPI -> nom du groupe qui l'a revendiqué
    conflits: list = []

    def revendiquer(kpi, nom):
        if kpi in pris and pris[kpi] != nom:
            conflits.append((kpi, pris[kpi], nom))
            return False
        pris[kpi] = nom
        return True

    # 1. les gabarits d'abord : chacun appartient à son groupe, c'est non
    # négociable, et deux groupes ne peuvent pas partager un gabarit
    for g in groupes:
        revendiquer(g["gabarit"], g["nom"])
    # 2. puis les listes explicites
    for g in groupes:
        for k in g["kpis"]:
            if k not in connus:
                log(f"⚠ groupe « {g['nom']} » : KPI « {k} » absent du modèle, "
                    "ignoré.")
                continue
            revendiquer(k, g["nom"])
    if conflits:
        raise SystemExit(
            "KPI revendiqué par deux groupes : "
            + " ; ".join(f"« {k} » ({a} et {b})" for k, a, b in conflits)
            + ".\nLe retirer de l'un des deux.")

    # 3. le groupe par défaut ramasse le reste
    if defauts:
        nom = defauts[0]["nom"]
        for k in connus:
            if k not in pris:
                pris[k] = nom

    resolus = []
    for g in groupes:
        kpis = [k for k in connus if pris.get(k) == g["nom"]]
        if g["gabarit"] not in kpis:          # ordre du modèle, gabarit inclus
            kpis.append(g["gabarit"])
        resolus.append({"nom": g["nom"], "gabarit": g["gabarit"], "kpis": kpis})

    orphelins = [k for k in connus if k not in pris]
    if orphelins:
        log(f"⚠ {len(orphelins)} KPI dans aucun groupe, donc non traités : "
            + ", ".join(orphelins)
            + ".\n  (un groupe sans liste de KPI les ramasserait tous.)")
    return resolus


def read_fp_maps(semantic_dir: Path, field_parameter: str = FIELD_PARAMETER):
    """Lit le paramètre de champ et renvoie deux tables :
      forward[(KPI, Calcul, Branche)] -> nom de mesure ;
      reverse[nom de mesure]          -> (KPI, Calcul, Branche).
    Source de vérité pour propager une mesure vers un autre KPI/branche SANS
    parser son nom : chaque rangée est « ("aff", NAMEOF([mesure]), ordre,
    "Indicateur", "Calcul", "Branche") ». Gère nativement les cibles dont la
    branche n'est PAS juste après le KPI (« Weight cible YTD »)."""
    tmdl = semantic_dir / "definition" / "tables" / f"{field_parameter}.tmdl"
    forward: dict = {}
    reverse: dict = {}
    if not tmdl.exists():
        return forward, reverse
    text = lire_texte(tmdl)
    for m in re.finditer(
        r'\(\s*"[^"]*"\s*,\s*NAMEOF\(\s*\[([^\]]+)\]\s*\)\s*,\s*\d+\s*,'
        r'\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)', text):
        measure, kpi, calcul, branche = m.group(1), m.group(2), m.group(3), m.group(4)
        forward[(kpi, calcul, branche)] = measure
        reverse[measure] = (kpi, calcul, branche)
    return forward, reverse


def racine_fp(nom, kpi, entity=ENTITY, fp_reverse=None):
    """Plus long PRÉFIXE de `nom` connu du paramètre de champ pour ce KPI.

    Beaucoup de mesures dérivées n'entrent pas dans le paramètre
    (`inFieldParameter: false` — couleurs de formatage conditionnel,
    sparklines) alors que leur RACINE, elle, y est. « Weight cible ecartCF »
    n'est pas mappée, mais « Weight cible » l'est : c'est par elle qu'on sait
    à quel (Calcul, Branche) l'attribut se rattache.

    Retourne (racine, préfixe_d_entité) ou (None, ""). On n'apparie jamais à
    travers les KPI : seules les mesures du KPI donné sont candidates."""
    if not (nom and fp_reverse):
        return None, ""
    for prefix in (entity + ".", ""):
        if not nom.startswith(prefix):
            continue
        bare = nom[len(prefix):]
        racine = None
        for cand, (kpi_c, _calc, _br) in fp_reverse.items():
            if kpi_c != kpi:
                continue
            if bare == cand or bare.startswith(cand + " "):
                if racine is None or len(cand) > len(racine):
                    racine = cand
        if racine is not None:
            return racine, prefix
    return None, ""


def kpi_sans_equivalent(metadata, src_kpi, dst_kpi, entity=ENTITY,
                        fp_forward=None, fp_reverse=None) -> bool:
    """Le KPI cible n'a-t-il AUCUN équivalent de l'attribut visé ?

    Le paramètre de champ le dit : la mesure source se rattache à un CALCUL
    (« Cible », « Réel »…) par sa racine. Si le KPI visé n'a aucune ligne pour
    ce calcul, il n'a simplement pas cette mesure — propager quand même
    laissait l'entrée pointer celle du KPI TEMPLATE. Les valeurs restaient
    justes, mais Power BI signalait un problème sur le visuel.

    Retourne False dès qu'on ne sait pas (pas de paramètre, racine inconnue) :
    une mesure GÉNÉRALE, partagée par tous les KPI — un titre, un libellé —
    doit continuer de se propager. C'est la différence entre « ce KPI n'a pas
    de cible » et « cette mesure ne dépend pas du KPI »."""
    if not (fp_forward and fp_reverse):
        return False
    racine, _ = racine_fp(metadata, src_kpi, entity, fp_reverse)
    if racine is None:
        return False
    # Le paramètre ne connaît pas ce KPI DU TOUT : il n'en dit rien, donc on
    # n'en déduit rien. C'est le cas d'un KPI passé en cible explicite sans
    # figurer dans le paramètre — tout lui écarter serait le rendre muet.
    if not any(k == dst_kpi for (k, _c, _b) in fp_forward):
        return False
    calcul = fp_reverse[racine][1]
    return not any(k == dst_kpi and c == calcul for (k, c, _b) in fp_forward)


def _chaines(node):
    """Toutes les chaînes d'un sous-arbre JSON, en profondeur."""
    if isinstance(node, dict):
        for v in node.values():
            for s in _chaines(v):
                yield s
    elif isinstance(node, list):
        for v in node:
            for s in _chaines(v):
                yield s
    elif isinstance(node, str):
        yield node


def entree_sans_equivalent(entry, src_kpi, dst_kpi, entity=ENTITY,
                           fp_forward=None, fp_reverse=None,
                           cibles=None, known=None):
    """1re mesure de l'entrée dont le KPI visé n'a pas d'équivalent, ou None.

    On regarde TOUTE l'entrée, pas seulement son `selector`. Le cas courant est
    une règle posée sur la mesure de BASE dont la couleur vient de la cible
    (« Weight cible ecartCF », enfoui dans les `properties`) : le selector se
    traduit très bien, la couleur non — et l'entrée atterrissait sur un KPI sans
    cible en pointant celle du template. Valeurs justes, mais Power BI signalait
    un problème sur le visuel.

    Deux raisons INDÉPENDANTES d'écarter, parce qu'aucune ne suffit seule :
    le paramètre de champ (le KPI n'a pas ce Calcul) et le dossier des cibles
    (la mesure est une cible, le KPI n'en a pas). Les cibles ne figurent pas
    toujours dans le paramètre — c'est précisément le cas où la 1re règle
    laissait passer la cible du gabarit sur un KPI qui n'en a pas."""
    for s in _chaines(entry):
        if kpi_sans_equivalent(s, src_kpi, dst_kpi, entity,
                               fp_forward, fp_reverse):
            return s
        if cible_sans_equivalent(s, src_kpi, dst_kpi, entity, cibles, known):
            return s
    return None


def swap_kpi_branch(value: str, src_kpi: str, src_branch: str,
                    dst_kpi: str, dst_branch: str, entity: str = ENTITY,
                    fp_forward=None, fp_reverse=None,
                    known=None, communes=None) -> str:
    """Nom de la mesure équivalente pour (dst_kpi, dst_branch).

    Chemin ROBUSTE : si la mesure est connue du paramètre de champ (fp_reverse),
    on relit sa (KPI, Calcul, Branche) et on cherche la mesure cible (dst_kpi,
    MÊME Calcul, dst_branch) dans fp_forward — aucun parsing du nom, donc les
    cibles marchent quelle que soit la position de la branche.
    Repli (mesures hors paramètre : couleurs CF…) : ancien comportement, la
    branche s'insère juste après le KPI. branch = "" pour Réel. Prefix-safe.

    `known` = mesures existantes du modèle (cf. measures_of_model). Un nom
    calculé n'est retenu que s'il en fait partie, et l'on descend une cascade
    d'intentions (cf. `retenu`) : la propagation n'écrit jamais une référence
    vers une mesure qui n'existe pas. `communes` collecte pour le journal les
    mesures laissées telles quelles."""

    def retenu(*candidats) -> str:
        """Le premier candidat qui EXISTE vraiment, sinon la mesure d'origine.

        L'ordre dit l'intention :

          1. la variante de la branche visée — « Weight YTD » ;
          2. la mesure du MÊME KPI sans branche — « Weight titre » : un titre
             par KPI, commun à ses deux branches ;
          3. rien du tout : la mesure d'origine, commune à tout le rapport
             (« Titre commun »).

        Sans `known` (modèle introuvable) on garde l'ancien comportement : le
        1er candidat, sans vérifier."""
        candidats = [c for c in candidats if c]
        if not known:
            return candidats[0]
        for c in candidats:
            bare = (c[len(entity) + 1:]
                    if c.startswith(entity + ".") else c)
            if c == value or bare in known:
                return c
        if communes is not None:
            communes.add(value)
        return value

    candidats: list = []
    # 1. via le paramètre de champ (le plus fiable : aucun parsing de nom).
    # La racine dit le (Calcul, Branche) de l'attribut ; on cherche la mesure
    # du KPI visé pour le MÊME calcul, et on recolle le reste du nom. La
    # branche atterrit ainsi au bon endroit — « Weight cible » ->
    # « Body Fat % cible YTD », et non « Body Fat % YTD cible », inexistant.
    racine, prefix = racine_fp(value, src_kpi, entity, fp_reverse)
    if racine is not None:
        calcul = fp_reverse[racine][1]
        reste = value[len(prefix) + len(racine):]
        # branche visée, puis SANS branche (le « commun aux branches »)
        for br in (dst_branch, ""):
            tgt = (fp_forward or {}).get((dst_kpi, calcul, br))
            if tgt:
                candidats.append(prefix + tgt + reste)

    # 2. repli par le NOM, pour les mesures hors paramètre. Ces candidats sont
    # ajoutés MÊME quand le paramètre a répondu : il peut n'avoir aucune ligne
    # « Réel » pour le KPI visé, et la cascade s'arrêtait alors trop tôt — le
    # titre du KPI template restait sur les faces YTD de tous les autres.
    src_head = src_kpi + ((" " + src_branch) if src_branch else "")
    dst_head = dst_kpi + ((" " + dst_branch) if dst_branch else "")
    for prefix in (f"{entity}.", ""):
        full = prefix + src_head
        if value == full:
            candidats += [prefix + dst_head, prefix + dst_kpi]
            break
        if value.startswith(full + " "):
            reste = value[len(full):]
            candidats += [prefix + dst_head + reste, prefix + dst_kpi + reste]
            break

    # dédoublonnage en gardant l'ORDRE : c'est lui qui porte l'intention
    vus: list = []
    for cand in candidats:
        if cand and cand not in vus:
            vus.append(cand)
    return retenu(*vus) if vus else value


def swap_tree_branch(node, src_kpi, src_branch, dst_kpi, dst_branch,
                     entity: str = ENTITY, fp_forward=None, fp_reverse=None,
                     known=None, communes=None):
    """Copie profonde d'un sous-arbre JSON, noms de mesures adaptés (KPI+branche)."""
    if isinstance(node, dict):
        return {k: swap_tree_branch(v, src_kpi, src_branch, dst_kpi, dst_branch,
                                    entity, fp_forward, fp_reverse,
                                    known, communes)
                for k, v in node.items()}
    if isinstance(node, list):
        return [swap_tree_branch(x, src_kpi, src_branch, dst_kpi, dst_branch,
                                 entity, fp_forward, fp_reverse,
                                 known, communes) for x in node]
    if isinstance(node, str):
        return swap_kpi_branch(node, src_kpi, src_branch, dst_kpi, dst_branch,
                               entity, fp_forward, fp_reverse,
                               known, communes)
    return node


def detect_branch(metadata, kpi, branches=BRANCHES, entity: str = ENTITY,
                  fp_reverse=None):
    """Branche de l'entrée template. Si la mesure est connue du paramètre de
    champ, on lit sa colonne Branche directement (robuste aux cibles) ; sinon
    on cherche le suffixe (parmi `branches`) qui suit le KPI dans le nom."""
    if metadata and fp_reverse:
        # plus long PRÉFIXE connu (racine_fp), pour que les mesures dérivées
        # hors paramètre (couleurs CF, sparklines) héritent de la branche de
        # leur racine — « Weight cible YTD ecartCF » est en YTD parce que
        # « Weight cible YTD » l'est.
        racine, _ = racine_fp(metadata, kpi, entity, fp_reverse)
        if racine is not None:
            branche = fp_reverse[racine][2]
            return branche if branche in branches else ""
    if not metadata:
        return ""
    for prefix in (f"{entity}.", ""):
        head = prefix + kpi
        if metadata.startswith(head + " "):
            remainder = metadata[len(head) + 1:]
            for b in branches:
                if remainder == b or remainder.startswith(b + " "):
                    return b
            return ""
    return ""


def entry_metadata(entry) -> str | None:
    if not isinstance(entry, dict):
        return None
    selector = entry.get("selector")
    if not isinstance(selector, dict):
        return None
    return selector.get("metadata")


def is_static_color(entry) -> bool:
    """Entrée de couleur STATIQUE « specific column » (gérée par
    color_matrix_by_kpi.py, PAS par ici) : selector avec metadata SANS 'data',
    et une propriété couleur qui n'est PAS une mesure (ThemeDataColor/Literal).
    Tout le reste (CF à base de mesure, reference labels, display units...) se
    propage. Même logique que color_matrix_by_kpi.is_static_color_entry."""
    if not isinstance(entry, dict):
        return False
    sel = entry.get("selector")
    if not isinstance(sel, dict) or "metadata" not in sel or "data" in sel:
        return False
    for v in (entry.get("properties") or {}).values():
        if isinstance(v, dict) and isinstance(v.get("solid"), dict) and "color" in v["solid"]:
            if "Measure" not in v["solid"]["color"].get("expr", {}):
                return True
    return False


# Seule clé d'objet que color_matrix_by_kpi.py écrit (matrices « specific
# column ») — cf. son process_visual : « ne touche QUE objects.columnFormatting
# -> jamais les graphes (dataPoint), slicers, cartes ». Les couleurs statiques
# des AUTRES clés n'ont donc aucun autre propriétaire : la ligne PY en noir
# (dataPoint), la bordure des marqueurs… sont des attributs de style uniformes
# sur tous les KPI, et se propagent ici comme le reste.
COLUMN_FORMATTING_KEY = "columnFormatting"


def owned_by_color_matrix(key, entry) -> bool:
    """L'entrée appartient-elle à color_matrix_by_kpi.py (couleur STATIQUE dans
    la clé qu'il gère) ? Lui seul y attribue une couleur PAR KPI depuis
    l'Excel ; hors de cette clé, la couleur suit le template."""
    return key == COLUMN_FORMATTING_KEY and is_static_color(entry)


def _selector_id_order(entry):
    """(selector.id, selector.order) d'une entrée — les deux discriminants qui
    distinguent DEUX étiquettes de référence sur le MÊME KPI : chaque étiquette
    porte un id « field-<uuid> » propre (et un order 0/1 sur sa valeur), et son
    titre/détail se rattachent à elle par ce même id."""
    sel = entry.get("selector") if isinstance(entry, dict) else None
    if not isinstance(sel, dict):
        return (None, None)
    return (sel.get("id"), sel.get("order"))


def entry_key(entry):
    """Identité d'une entrée pour la déduplication : (metadata, id, order,
    propriétés). Deux entrées de même metadata mais de propriétés DIFFÉRENTES
    (« backColor » CF vs « labelDisplayUnits ») doivent COEXISTER ; et DEUX
    étiquettes de référence sur le même KPI se distinguent par leur selector.id
    (un field-<uuid> par étiquette) et leur order — sans eux, la 2e écrase la
    1re au clonage (bug : « seule la dernière étiquette est propagée »)."""
    md = entry_metadata(entry)
    sid, order = _selector_id_order(entry)
    props = ()
    if isinstance(entry, dict) and isinstance(entry.get("properties"), dict):
        props = tuple(sorted(entry["properties"].keys()))
    return (md, sid, order, props)


# Propriétés d'étiquette de référence PROUVÉES « point de donnée » : sur une
# carte à paramètre de champ, chaque KPI est un POINT DE DONNÉE du paramètre,
# et ces propriétés n'atteignent les KPI « virtuels » que si leur selector
# porte data:[dataViewWildcard] (la VALEUR l'a nativement ; le TEXTE du titre
# en a besoin — vérifié dans Desktop). TOUT LE RESTE (titleContentType, show du
# détail, labelDisplayUnits/labelPrecision de la valeur, etc.) est au niveau
# CHAMP : {metadata, id} SANS wildcard — leur ajouter la portée point de donnée
# fait que Power BI les IGNORE et le réglage retombe au défaut (titre -> « nom
# du champ », display units -> « Automatique »). Liste BLANCHE volontairement :
# une propriété inconnue garde la portée écrite par Desktop.
POINT_SCOPED_PROPS = {"value", "titleText", "detailValue"}


def _expr_has_measure(node) -> bool:
    """Le sous-arbre référence-t-il une MESURE (clé « Measure ») ?"""
    if isinstance(node, dict):
        return "Measure" in node or any(_expr_has_measure(v) for v in node.values())
    if isinstance(node, list):
        return any(_expr_has_measure(x) for x in node)
    return False


def _prop_point_scoped(name, val) -> bool:
    """Propriété d'étiquette « point de donnée » : nom connu
    (POINT_SCOPED_PROPS) OU valeur portée par une MESURE — elle doit se
    résoudre par KPI du paramètre (value, detailValue, couleur CF…), donc
    exige data:[dataViewWildcard]. Les bascules/formats littéraux (show,
    titleContentType, labelDisplayUnits…) restent niveau champ."""
    return name in POINT_SCOPED_PROPS or (isinstance(val, dict) and _expr_has_measure(val))


def _is_point_scoped_only(entry) -> bool:
    """L'entrée ne porte QUE des propriétés « point de donnée » ?"""
    props = entry.get("properties") if isinstance(entry, dict) else None
    return bool(props) and all(_prop_point_scoped(k, v) for k, v in props.items())


_WILDCARD_ONLY = [{"dataViewWildcard": {"matchingOption": 0}}]


def ensure_datapoint_scope(entry) -> bool:
    """Normalise la PORTÉE du selector d'une entrée liée à un emplacement
    (selector.id). Mutation en place ; renvoie True si modifiée.

    - propriétés toutes « point de donnée » (POINT_SCOPED_PROPS) : ajoute
      data:[dataViewWildcard] si absent — sinon elles ne suivent pas le
      paramètre de champ ;
    - sinon (propriétés niveau champ, ex. titleContentType, labelDisplayUnits) :
      RETIRE un wildcard pur posé par une version précédente du script — sinon
      Power BI ignore l'entrée et le réglage retombe au défaut. On ne retire
      jamais un `data` plus riche (entrée VALEUR native : wildcard + order) ni
      celui d'une règle CF liée aux données."""
    if not isinstance(entry, dict):
        return False
    sel = entry.get("selector")
    if not isinstance(sel, dict) or "id" not in sel:
        return False
    if _is_point_scoped_only(entry):
        if "data" not in sel:
            sel["data"] = [{"dataViewWildcard": {"matchingOption": 0}}]
            return True
        return False
    if sel.get("data") == _WILDCARD_ONLY and "order" not in sel:
        del sel["data"]                     # réparation (portée champ restaurée)
        return True
    return False


def split_entry_scopes(entry):
    """Sépare une entrée MIXTE d'étiquette de référence selon la portée de ses
    propriétés : les bascules/formats niveau CHAMP (titleContentType, show du
    détail, labelDisplayUnits… — selector {metadata, id} sans wildcard) d'un
    côté, les valeurs POINT DE DONNÉE (POINT_SCOPED_PROPS : titleText, value —
    avec dataViewWildcard) de l'autre. Renvoie 1 ou 2 entrées.

    Nécessaire car Power BI ignore une bascule scopée point de donnée (retour
    au défaut — titre « nom du champ », units « Automatique »… et à la
    SAUVEGARDE suivante Desktop PURGE l'entrée ignorée du fichier, d'où des
    réglages qui « disparaissent ») MAIS ignore une valeur qui n'est PAS scopée
    point de donnée (elle ne suit pas le paramètre de champ). Les deux familles
    ne peuvent donc pas cohabiter dans un même selector. Cas typiques : le
    TITRE {titleContentType, titleText} et le DÉTAIL {show, value} (une mesure
    d'écart en détail). Idempotent : une entrée « pure » est renvoyée telle
    quelle."""
    if not isinstance(entry, dict):
        return [entry]
    props = entry.get("properties")
    sel = entry.get("selector")
    if not isinstance(props, dict) or not isinstance(sel, dict) or "id" not in sel:
        return [entry]
    field_props = {k: v for k, v in props.items() if not _prop_point_scoped(k, v)}
    point_props = {k: v for k, v in props.items() if _prop_point_scoped(k, v)}
    if not field_props or not point_props:
        return [entry]  # déjà pure ; la portée est gérée par ensure_datapoint_scope
    base_sel = {k: v for k, v in sel.items() if k != "data"}
    field_entry = {"properties": field_props, "selector": dict(base_sel)}
    point_sel = dict(base_sel)
    point_sel["data"] = [{"dataViewWildcard": {"matchingOption": 0}}]
    point_entry = {"properties": point_props, "selector": point_sel}
    return [field_entry, point_entry]


# ---- à quelle variation appartient une entrée ? ---------------------------
#
# D'ordinaire, au selector : la série « Weight YTD PY » d'un graphique, la
# colonne « Weight PY » d'une matrice. Mais sur une CARTE, toutes les entrées
# visent la mesure du KPI (`_mesures.Weight`) : la variation est DANS
# l'entrée. Une étiquette de référence montre `Weight PY` en valeur ; son
# titre et son détail s'y rattachent par le même `selector.id` ; l'image de
# la carte est `Weight sparkline`. Classées au selector, elles tombaient
# toutes au Réel — et un gabarit par variation n'y pouvait rien : sur une
# page de cartes, seule la base propageait.

# propriétés dont la mesure EST ce que l'entrée montre (hors étiquettes de
# référence, rattachées par leur id)
PROPRIETES_AFFICHEES = ("imageData", "imageUrl")

# Le DÉTAIL d'une étiquette (referenceLabelDetail, même id) a sa colonne à
# lui : « Cible — détail » à côté de « Cible ». Le détail de la cible montre
# un écart en % chez l'un, en valeur chez l'autre : il doit pouvoir rester à
# la main — ou se propager — sans emporter l'étiquette, et réciproquement.
# Tant qu'aucune règle ne le nomme, il suit son étiquette (cf. Sources).
DETAIL = " — détail"
CLES_DETAIL = ("referenceLabelDetail",)


def colonne_detail(variation) -> str:
    return f"{variation}{DETAIL}"


def etiquette_du_detail(variation):
    """« Cible » pour « Cible — détail », sinon None."""
    v = str(variation or "")
    return v[:-len(DETAIL)] if v.endswith(DETAIL) and len(v) > len(DETAIL) else None


def _premiere_mesure(node):
    """Le nom de la première mesure référencée dans un sous-arbre, ou None."""
    if isinstance(node, dict):
        m = node.get("Measure")
        if isinstance(m, dict) and m.get("Property"):
            return m["Property"]
        for v in node.values():
            r = _premiere_mesure(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _premiere_mesure(v)
            if r:
                return r
    return None


def emplacements_de(objects, classer, kpis_tries, entity=ENTITY) -> dict:
    """{selector.id: variation} des étiquettes de référence d'un visuel : la
    variation de la mesure que l'étiquette montre en VALEUR. Le même id
    porte cette étiquette pour tous les KPI — c'est l'emplacement dans la
    carte — et son titre, son détail, sa mise en forme s'y rattachent."""
    out: dict = {}
    entrees = (objects or {}).get("referenceLabel")
    for e in entrees if isinstance(entrees, list) else []:
        sel = e.get("selector") if isinstance(e, dict) else None
        ident = sel.get("id") if isinstance(sel, dict) else None
        if not ident or ident in out:
            continue
        m = _premiere_mesure((e.get("properties") or {}).get("value"))
        if not m:
            continue
        md = f"{entity}.{m}"
        k = kpi_de(md, kpis_tries, entity)
        if k is not None:
            out[ident] = classer(md, k)
    return out


def variation_entree(entry, kpi, classer, emplacements=None, entity=ENTITY,
                     cle=None):
    """La variation qu'une entrée MONTRE, pour le KPI `kpi` : celle de son
    étiquette de référence (par son id) — la colonne de son DÉTAIL si
    l'entrée vient d'une clé de détail (`cle`, la clé d'objet) —, celle de
    l'image qu'elle affiche, sinon celle de son selector."""
    sel = entry.get("selector") if isinstance(entry, dict) else None
    ident = sel.get("id") if isinstance(sel, dict) else None
    if ident and emplacements and ident in emplacements:
        if cle and str(cle).startswith(CLES_DETAIL):
            return colonne_detail(emplacements[ident])
        return emplacements[ident]
    props = entry.get("properties") if isinstance(entry, dict) else None
    if isinstance(props, dict):
        for nom in PROPRIETES_AFFICHEES:
            m = _premiere_mesure(props.get(nom))
            if m and (m == kpi or m.startswith(kpi + " ")):
                return classer(f"{entity}.{m}", kpi)
    return classer(entry_metadata(entry), kpi)


# ---- un gabarit de groupe se pose PAR-DESSUS la base ------------------------
#
# Un groupe reçoit d'abord ce que donne le maître — la base, ou le gabarit
# par variation de « Tous les KPI » —, puis les réglages de son gabarit
# par-dessus : ce que le gabarit règle lui-même l'emporte, le reste vient du
# maître. C'est le GABARIT qui reçoit le maître ; ses KPI le copient ensuite
# en entier. Il se lit donc dans Desktop tel que son groupe le verra.
#
# PROPRIÉTÉ par propriété : la couleur du titre que le gabarit a choisie
# l'emporte, la taille qu'il ne règle pas vient du maître. Pour qu'un
# changement du maître descende AUSSI dans les gabarits, on retient ce qu'on
# y a posé (la MÉMOIRE, cf. memoire_path) : une valeur posée par nous et que
# personne n'a retouchée suit le maître ; une valeur retouchée dans Desktop
# appartient au gabarit. Un gabarit ne peut pas RETIRER ce que le maître
# donne — seulement le régler autrement (ou rendre son groupe indépendant).

def _canon(x) -> str:
    """Une valeur JSON en texte canonique : pour comparer sans que True == 1."""
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def superposer_entrees(dessous, dessus, posees):
    """Pose `dessous` — les entrées du maître, déjà clonées sur le gabarit —
    SOUS `dessus`, celles du gabarit, propriété par propriété.

    `posees` : {(sélecteur canonique, propriété): valeur} que les passes
    précédentes ont posées depuis le maître. Pour chaque propriété :

      - le gabarit ne l'a pas : celle du maître (posée, retenue) ;
      - il a la même : rien à faire (retenue : elle suit le maître) ;
      - il a celle qu'on y avait posée : le maître a changé, elle suit ;
      - il a autre chose : c'est la sienne, elle l'emporte ;
      - le maître ne l'a plus et c'est celle qu'on avait posée : retirée.

    Rend (remplacements {id(entrée du gabarit): nouvelle entrée, ou None
    quand il ne lui reste rien}, ajouts [entrées neuves], posées après,
    nombre d'entrées changées)."""
    m: dict = {}
    venues: list = []                       # (entrée du maître, sélecteur)
    for e in dessous:
        sel = _canon(e.get("selector"))
        venues.append((e, sel))
        for p, v in (e.get("properties") or {}).items():
            m[(sel, p)] = v
    h: dict = {}
    for e in dessus:
        sel = _canon(e.get("selector"))
        for p, v in (e.get("properties") or {}).items():
            h[(sel, p)] = v

    def posee_par_nous(k):
        return k in posees and _canon(h[k]) == _canon(posees[k])

    garde: dict = {}
    # ce qu'on avait posé HORS de cette passe (une autre variation, un autre
    # maître) ne la regarde pas : retenu tel quel
    apres = {k: v for k, v in posees.items() if k not in m and k not in h}
    for k, v in m.items():
        if k not in h or _canon(h[k]) == _canon(v) or posee_par_nous(k):
            garde[k] = v
            apres[k] = v
        else:
            garde[k] = h[k]                  # la sienne : elle l'emporte
    for k, v in h.items():
        if k not in m and not posee_par_nous(k):
            garde[k] = v                     # à lui seul

    remplacements: dict = {}
    hotes: dict = {}                         # sélecteur -> entrée qui accueille
    for e in dessus:
        sel = _canon(e.get("selector"))
        neuves = {p: garde[(sel, p)] for p in (e.get("properties") or {})
                  if (sel, p) in garde}
        if not neuves:
            remplacements[id(e)] = None
            continue
        nouvelle = dict(e)
        nouvelle["properties"] = neuves
        remplacements[id(e)] = nouvelle
        hotes.setdefault(sel, nouvelle)
    ajouts: list = []
    for e, sel in venues:
        neuves = {p: garde[(sel, p)] for p in (e.get("properties") or {})
                  if (sel, p) not in h}
        if not neuves:
            continue
        hote = hotes.get(sel)
        if hote is None:
            # même sélecteur que le maître (copié : l'ordre de ses clés reste
            # celui que Desktop écrit)
            hote = {"properties": {},
                    "selector": json.loads(json.dumps(e.get("selector")))}
            ajouts.append(hote)
            hotes[sel] = hote
        hote["properties"].update(neuves)
    n = sum(1 for e in dessus
            if remplacements[id(e)] is None
            or _canon(remplacements[id(e)]) != _canon(e)) + len(ajouts)
    return remplacements, ajouts, apres, n


def _posees_lues(liste) -> dict:
    """La mémoire d'un gabarit, pour une clé d'objet : {(sélecteur canonique,
    propriété): valeur}."""
    out: dict = {}
    for x in liste or ():
        if isinstance(x, dict) and isinstance(x.get("proprietes"), dict):
            sel = _canon(x.get("selector"))
            for p, v in x["proprietes"].items():
                out[(sel, p)] = v
    return out


def _posees_ecrites(posees) -> list:
    par_sel: dict = {}
    for (sel, p), v in posees.items():
        par_sel.setdefault(sel, {})[p] = v
    return [{"selector": json.loads(sel), "proprietes": props}
            for sel, props in sorted(par_sel.items())]


def process_visual(path: Path, template: str, targets: list[str], *,
                   entity: str = ENTITY, branches=BRANCHES,
                   verbose: bool = False, dry_run: bool = False, log=print,
                   backup_dir=None, fp_forward=None, fp_reverse=None,
                   known=None, communes=None, sans_equiv=None,
                   kpis_connus=None, cibles=None,
                   cellules=None, classer=None,
                   superposer=False, memoire=None) -> int:
    """Aligne, dans chaque liste de visual.objects, les KPI cibles sur le KPI
    template : les entrées visant le template sont clonées vers chaque cible,
    et celles que le template ne porte PLUS sont retirées des cibles (miroir).
    Retourne le nombre d'entrées ajoutées, mises à jour ou retirées.

    `kpis_connus` = TOUS les KPI du rapport, y compris ceux hors `targets`.
    Sert uniquement à découper correctement les noms (cf. `_managed`) quand la
    passe ne porte que sur une partie des KPI — une propagation par groupes.

    `cellules` : les CASES (KPI, variation) de cette passe — tout objet qui
    répond à `(kpi, variation) in cellules` (cf. Sources.cases_de) —, et
    `classer(metadata, kpi)` dit la variation d'une entrée (cf. classeur).
    Une entrée hors des cases de la passe n'est ni une source, ni une cible,
    ni à retirer : la base et une exception se partagent un même visuel sans
    se marcher dessus. None = toutes les variations des KPI de la passe.

    `superposer` : le template est un MAÎTRE (la base, un gabarit par
    variation) et les `targets` des gabarits de groupe — il passe DESSOUS,
    propriété par propriété (cf. superposer_entrees), sans miroir. `memoire`
    : ce qu'on a posé sur ces gabarits dans ce visuel, {gabarit: {clé
    d'objet: [...]}}, tenu à jour ici."""
    data = json.loads(lire_texte(path))
    objects = (data.get("visual") or {}).get("objects")
    if not isinstance(objects, dict):
        return 0

    changes = 0

    # DEUX ensembles, et il ne faut pas les confondre :
    #
    #  · `_managed` sert à DÉCOUPER un nom de mesure — quel KPI vise-t-elle ?
    #    Il doit contenir TOUS les KPI du rapport, du plus long au plus court.
    #    « Average Steps » ne doit pas capter « Average Steps YTD », et surtout,
    #    quand la passe ne porte que sur un groupe, un KPI d'un AUTRE groupe
    #    dont le nom commence par celui du gabarit (« Total Steps Goal » face à
    #    « Total Steps ») serait pris pour une déclinaison du gabarit. Ses
    #    clones redeviendraient des sources au tour suivant : les entrées
    #    doublent à chaque passe et la propagation ne converge jamais.
    #
    #  · `_portee` est le PÉRIMÈTRE D'ÉCRITURE : les seuls KPI qu'on a le droit
    #    de remplir et d'où l'on a le droit de retirer. Les autres groupes sont
    #    intouchables, même dans le même visuel.
    _portee = set(targets) | {template}
    _managed = sorted(set(kpis_connus or ()) | _portee, key=len, reverse=True)

    def _managed_kpi(md):
        """KPI visé par ce metadata (Réel ou branche), sinon None."""
        return kpi_de(md, _managed, entity)

    # les étiquettes de référence du visuel (cartes) : id -> variation montrée
    emplacements = (emplacements_de(objects, classer, _managed, entity)
                    if cellules is not None else {})

    def _variation(e, kpi, cle):
        return variation_entree(e, kpi, classer, emplacements, entity, cle)

    def _face_reel(e, kpi):
        """(branche, sélecteur ramené au Réel, signature ramenée au Réel)
        d'une entrée de `kpi` — la signature a la forme d'entry_key."""
        md = entry_metadata(e)
        b = detect_branch(md, kpi, branches, entity, fp_reverse)
        base_md = (swap_kpi_branch(md, kpi, b, kpi, "", entity, fp_forward,
                                   fp_reverse) if b else md)
        sel = dict(e.get("selector") or {}) if isinstance(e, dict) else {}
        if b:
            sel["metadata"] = base_md
        sid, order = _selector_id_order(e)
        props = ()
        if isinstance(e, dict) and isinstance(e.get("properties"), dict):
            props = tuple(sorted(e["properties"].keys()))
        return b, _canon(sel), (base_md, sid, order, props)

    def _faces(reel):
        """Le test « face d'une de ces entrées Réel » : une entrée de branche
        À LA PLACE d'une entrée Réel — même signature, ou même sélecteur.
        Le sélecteur suffit : si le Réel a gagné (ou perdu) une propriété
        depuis la dernière passe, sa face d'avant a gardé l'ancienne
        signature, mais elle reste sa face. La prendre pour une entrée « de
        branche seule » la gardait, et la propageait : deux entrées au même
        sélecteur sur chaque face, l'ancienne valeur restait collée."""
        cles = {entry_key(e) for e in reel}
        sels = {_canon(e.get("selector")) for e in reel}

        def est_face(e, kpi):
            b, sel, sig = _face_reel(e, kpi)
            return bool(b) and (sig in cles or sel in sels)
        return est_face

    def _dans_la_passe(e, cle) -> bool:
        """Cette entrée tombe-t-elle dans une case de CETTE passe ?"""
        kpi = _managed_kpi(entry_metadata(e))
        if kpi not in _portee:
            return False
        return cellules is None or (kpi, _variation(e, kpi, cle)) in cellules

    def _targets_template(entry, cle) -> bool:
        """L'entrée vise-t-elle une mesure DU KPI template ?

        Le test doit passer par _managed_kpi (plus long KPI géré d'abord), et
        NON par un préfixe de chaîne : si un autre KPI s'appelle « Total Steps
        Goal », « _mesures.Total Steps Goal PY » commence bel et bien par
        « _mesures.Total Steps » — il serait pris pour une déclinaison du
        template. Ses clones, écrits au run précédent, redeviendraient alors
        des SOURCES au run suivant : le nombre d'entrées double à chaque
        passe, et la propagation ne converge jamais."""
        md = entry_metadata(entry)
        if _managed_kpi(md) != template:
            return False
        # le gabarit ne donne que les variations dont il est la source : les
        # autres appartiennent à une autre passe (une colonne venue d'ailleurs)
        return cellules is None or (template, _variation(entry, template, cle)) in cellules

    # Le MIROIR (retrait de ce que le template ne porte plus) ne s'applique
    # qu'aux visuels PILOTÉS par le template, c'est-à-dire portant au moins une
    # entrée visant le KPI template. Un visuel qui n'affiche pas le template
    # n'est pas concerné : on n'y touche à rien (garde-fou anti-effacement).
    #
    # Avec des cases, « piloté » se juge sur les entrées que la source porte
    # DANS SES CASES — celles qu'aucune autre passe n'écrit. Juger sur toutes
    # ses entrées ferait dépendre le résultat de l'ordre des passes : la base
    # peut poser des entrées sur le KPI source d'une exception, dans un visuel
    # où il n'en avait aucune, et la passe suivante s'y croirait pilotée.
    driven_by_template = any(
        _targets_template(e, cle)
        for cle, entries in objects.items() if isinstance(entries, list)
        for e in entries
    )
    if superposer and not driven_by_template:
        return 0           # le maître n'a rien ici : rien à poser dessous

    for key, entries in objects.items():
        if not isinstance(entries, list):
            continue

        # Entrées MIXTES des ÉTIQUETTES DE RÉFÉRENCE (titre {titleContentType,
        # titleText}, détail {show, value-mesure}, …) : scinder chaque entrée
        # en une part « champ » et une part « point de donnée » AVANT de
        # propager — les deux portées s'annulent dans un même selector (et
        # Desktop PURGE les entrées à la mauvaise portée à la sauvegarde
        # suivante, d'où des réglages qui « disparaissent »). Restreint aux
        # clés referenceLabel* : ailleurs (referenceLine d'axe…), `value` n'est
        # PAS une propriété point-de-donnée. Idempotent (entrée pure =
        # inchangée) ; répare aussi les entrées combinées héritées.
        if key.startswith("referenceLabel"):
            rebuilt = []
            for e in entries:
                rebuilt.extend(split_entry_scopes(e))
            if rebuilt != entries:
                changes += len(rebuilt) - len(entries) or 1
                entries[:] = rebuilt

        # candidats = toute entrée dont le selector.metadata vise le KPI template
        candidates = [e for e in entries if _targets_template(e, key)]
        # templates = candidats qui visent une mesure du KPI template, SAUF les
        # couleurs statiques de columnFormatting (gérées par color_matrix_by_kpi).
        # -> inclut CF à base de mesure, reference labels (titre, détail), display
        #    units, couleurs de série d'un graphique (dataPoint, markers…) —
        #    tout ce qui a un selector.metadata.
        template_entries = [
            e for e in candidates
            if not owned_by_color_matrix(key, e)
        ]

        if verbose and candidates:
            log("  [{0} / objects.{1}]".format(path.parent.name, key))
            for e in candidates:
                mark = ("-> IGNORÉ (couleur statique columnFormatting)"
                        if owned_by_color_matrix(key, e) else "-> propagé")
                log("      candidat  {0:<48} {1}".format(entry_metadata(e), mark))

        # normalisation de portée EN PLACE de toutes les entrées du template
        # (ajout du wildcard aux propriétés point-de-donnée, RETRAIT d'un
        # wildcard erroné posé par une version antérieure sur les propriétés
        # niveau champ — ex. labelDisplayUnits, que Power BI ignorait alors)
        for e in template_entries:
            if ensure_datapoint_scope(e):
                changes += 1
                if verbose:
                    log("        * portée normalisée {0}".format(entry_metadata(e)))

        # Le RÉEL (sans branche) du template est MAÎTRE :
        # - ses entrées ne sont JAMAIS réécrites par un clone (sinon une entrée
        #   de branche périmée d'un run précédent écrase la modif fraîche de
        #   l'utilisateur — vu avec les display units) ;
        # - une entrée de BRANCHE à la place d'une entrée Réel en est une FACE
        #   (cf. _faces) : régénérée depuis le Réel, jamais source. Seule une
        #   entrée de branche sans Réel en face sert de source (branche seule
        #   formatée).
        reel_keys = {entry_key(e) for e in template_entries
                     if not detect_branch(entry_metadata(e), template, branches, entity, fp_reverse)}
        est_face = _faces([e for e in template_entries
                           if not detect_branch(entry_metadata(e), template,
                                                branches, entity, fp_reverse)])
        sources = [e for e in template_entries if not est_face(e, template)]

        # signatures que le visuel DOIT porter à la fin : celles du template
        # (il garde ce qu'il porte, sauf ses faces : elles sont régénérées)
        # + tous les clones générés ci-dessous. Tout le reste, sur un KPI
        # géré, est une relique -> retiré (miroir) — dont une face restée à
        # l'ancienne signature.
        expected = {entry_key(e) for e in sources}

        if superposer:
            # PAR-DESSOUS : le maître passe sous chaque gabarit de groupe —
            # sous son RÉEL (ses faces de branche le suivront à sa propre
            # passe, cf. _faces), et sous ses entrées de branche seule. Ni
            # miroir ni retrait en bloc : on ne retire que ce qu'on avait posé
            # et que le maître n'a plus.
            for kpi in targets:
                if kpi == template:
                    continue
                siennes = [e for e in entries
                           if not owned_by_color_matrix(key, e)
                           and _managed_kpi(entry_metadata(e)) == kpi
                           and (kpi, _variation(e, kpi, key)) in cellules]
                dessous = []
                for tpl_entry in sources:
                    if (kpi, _variation(tpl_entry, template, key)) not in cellules:
                        continue
                    manquante = entree_sans_equivalent(
                        tpl_entry, template, kpi, entity, fp_forward,
                        fp_reverse, cibles, known)
                    if manquante is not None:
                        if sans_equiv is not None:
                            sans_equiv.add((manquante, kpi))
                        continue
                    b = detect_branch(entry_metadata(tpl_entry), template,
                                      branches, entity, fp_reverse)
                    clone = swap_tree_branch(
                        tpl_entry, template, b, kpi, b,
                        entity, fp_forward, fp_reverse, known, communes)
                    ensure_datapoint_scope(clone)
                    dessous.append(clone)
                # ses faces suivent son Réel : le maître n'y passe pas dessous
                face_du_gabarit = _faces(
                    [e for e in siennes + dessous
                     if not detect_branch(entry_metadata(e), kpi, branches,
                                          entity, fp_reverse)])
                dessous = [c for c in dessous if not face_du_gabarit(c, kpi)]
                dessus = [e for e in siennes if not face_du_gabarit(e, kpi)]
                if not dessous and not dessus:
                    continue
                notes = memoire.setdefault(kpi, {}) if memoire is not None else {}
                remplacements, ajouts, apres, n = superposer_entrees(
                    dessous, dessus, _posees_lues(notes.get(key)))
                if apres:
                    notes[key] = _posees_ecrites(apres)
                else:
                    notes.pop(key, None)
                if memoire is not None and not notes:
                    memoire.pop(kpi, None)
                if n:
                    entries[:] = [remplacements.get(id(e), e) for e in entries
                                  if remplacements.get(id(e), e) is not None
                                  ] + ajouts
                    changes += n
                    if verbose:
                        log("        sous {0} : {1} entrée(s) ({2})".format(
                            kpi, n, template))
            continue

        for tpl_entry in sources:
            # branche de l'entrée template (ex. Réel ou YTD)
            src_branch = detect_branch(entry_metadata(tpl_entry), template, branches, entity, fp_reverse)
            # Une source RÉEL irrigue toutes les branches. Une source « branche
            # seule » (aucune entrée Réel de même signature — ex. le style des
            # marqueurs de la ligne YTD sur un graphique qui ne trace QUE des
            # mesures YTD) décrit un état propre à cette branche : elle reste
            # DANS SA BRANCHE. Sans ça, elle recréerait des entrées sur les
            # faces Réel — dont celle du template qu'on vient de supprimer.
            dst_branches = ([""] + list(branches)) if not src_branch else [src_branch]
            # on génère pour chaque KPI cible ET chaque branche visée,
            # en sautant l'entrée template elle-même (même KPI + même branche)
            src_var = (_variation(tpl_entry, template, key)
                       if cellules is not None else None)
            for kpi in targets:
                if cellules is not None and (kpi, src_var) not in cellules:
                    continue           # cette case copie une autre source
                # Ce KPI n'a pas cet attribut du tout (pas de cible, par
                # exemple) : on ne lui écrit RIEN. Avant, l'entrée restait et
                # pointait la mesure du template — valeurs justes, mais Power BI
                # signalait un problème sur le visuel. Une mesure GÉNÉRALE, elle,
                # continue de se propager (cf. kpi_sans_equivalent).
                manquante = None if kpi == template else entree_sans_equivalent(
                    tpl_entry, template, kpi, entity, fp_forward, fp_reverse,
                    cibles, known)
                if manquante is not None:
                    if sans_equiv is not None:
                        sans_equiv.add((manquante, kpi))
                    if verbose:
                        log("      ∅ {0} / {1} : pas d'équivalent de {2}".format(
                            key, kpi, manquante))
                    continue
                for dst_branch in dst_branches:
                    if kpi == template and dst_branch == src_branch:
                        continue
                    clone = swap_tree_branch(tpl_entry, template, src_branch, kpi, dst_branch,
                                             entity, fp_forward, fp_reverse,
                                             known, communes)
                    ensure_datapoint_scope(clone)  # même portée que la source normalisée
                    clone_md = entry_metadata(clone)
                    clone_key = entry_key(clone)
                    expected.add(clone_key)
                    if kpi == template and clone_key in reel_keys:
                        continue       # le Réel du template n'est jamais réécrit

                    # dédup par (metadata + propriétés) : une entrée CF et une
                    # entrée display-units sur la MÊME mesure coexistent
                    existing = next(
                        (i for i, e in enumerate(entries)
                         if entry_key(e) == clone_key),
                        None,
                    )
                    if existing is None:
                        entries.append(clone)
                        changes += 1
                        if verbose: log("        + {0}".format(clone_md))
                    elif entries[existing] != clone:
                        entries[existing] = clone
                        changes += 1
                        if verbose: log("        ~ {0}".format(clone_md))

        # ---- MIROIR : retirer des cibles ce que le template ne porte plus ---
        # Sans ça la propagation n'était qu'additive : supprimer un réglage sur
        # le KPI template (retirer l'image d'une carte, par exemple) le laissait
        # en place sur tous les autres KPI — et une relique de branche finissait
        # même par le RECRÉER sur le template. On ne touche qu'aux entrées
        # visant un KPI géré ; les couleurs statiques (color_matrix_by_kpi) et
        # tout selector sans metadata (« default », règles globales) sont hors
        # jeu, comme à la propagation.
        def _reference_morte(e) -> bool:
            """L'entrée vise-t-elle une mesure qui N'EXISTE PAS ?

            Relique d'avant la règle « on n'invente pas de nom » : un
            « Total Steps YTD titre » posé sur le KPI template, que Power BI
            ignore puisque la mesure est absente. Le template est maître et ses
            entrées ne sont jamais réécrites — mais celle-là ne décrit rien, et
            la laisser voudrait dire l'enlever à la main dans Desktop.

            Garde-fou : on n'enlève que si le nom est préfixé par la TABLE DES
            MESURES. Un selector peut viser une COLONNE, et les colonnes ne
            sont pas dans `known`."""
            if not known:
                return False
            md = entry_metadata(e) or ""
            if not md.startswith(entity + "."):
                return False
            return md[len(entity) + 1:] not in known

        if driven_by_template:
            # `_dans_la_passe` et non « un KPI géré » : on ne retire QUE dans
            # les cases de cette passe. Sinon une passe emporterait le
            # formatage des autres sources, qu'elle n'a pas vocation à décrire.
            stale = [e for e in entries
                     if not owned_by_color_matrix(key, e)
                     and _dans_la_passe(e, key)
                     and (entry_key(e) not in expected or _reference_morte(e))]
            if stale:
                for e in stale:
                    log("      - {0} / {1} : retiré ({2})".format(
                        key, entry_metadata(e),
                        "mesure inexistante" if _reference_morte(e)
                        else "absent de sa source, " + template))
                stale_ids = {id(e) for e in stale}
                entries[:] = [e for e in entries if id(e) not in stale_ids]
                changes += len(stale)

    if changes and not dry_run:
        if backup_dir is not None:
            # nom historique <page>_<visuel>.json conservé ; le manifeste de la
            # session note le chemin d'origine, ce qui rend la restauration
            # mécanique (cf. backup_restore.py)
            backup_dir.save(
                path, name=f"{path.parents[2].name}_{path.parent.name}.json")
        ecrire_texte(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return changes


def propagate(report_dir, template_kpi, *, branches=BRANCHES, targets=None,
              entity: str = ENTITY, field_parameter: str = FIELD_PARAMETER,
              dry_run: bool = False, verbose: bool = False, log=print,
              backup_dir=None, cible_folders=(), cellules=None, classer=None,
              contexte=None, entete=None, superposer=False,
              memoire=None) -> int:
    """Propage le formatage conditionnel du KPI template vers tous les KPI (et
    toutes les branches) dans les visual.json du rapport. Retourne le nombre
    total d'entrées écrites. Point d'entrée commun CLI (main) et UI (Atelier) :
    `log` reçoit chaque ligne (print par défaut, redirigé vers la console UI).

    `backup_dir` : session de sauvegarde FOURNIE par l'appelant. Elle n'est
    alors ni créée ni fermée ici — celui qui l'ouvre la ferme. C'est ce qui
    permet à `propagate_groupes` de couvrir plusieurs passes avec UNE seule
    sauvegarde, donc une seule restauration.

    `cellules` / `classer` : la passe d'UNE source de la grille des sources
    (cf. propagate_regles) — seules ses cases sont lues, écrites, nettoyées.
    `contexte` : le modèle déjà lu (cf. contexte_modele) — N passes ne le
    relisent pas N fois, et n'en répètent pas le compte rendu. `entete`
    remplace alors les lignes « KPI template / KPI cibles » du journal.

    `superposer` / `memoire` : le template passe SOUS les gabarits de groupe
    (cf. process_visual) ; `memoire` = {"page/visuel": {...}}, tenue à jour."""
    report_dir = Path(report_dir)
    branches = list(branches)
    # Ce qu'on lit du modèle (cf. contexte_modele) : TOUS les KPI — pour
    # découper les noms même quand la passe n'en touche que quelques-uns —,
    # le paramètre de champ (une CIBLE se propage sans parser son nom : «
    # Weight cible YTD » -> « Body Fat % cible YTD », pas « … YTD cible »),
    # les mesures existantes (on ne réécrit une référence que vers une mesure
    # qui EXISTE) et les cibles (un KPI sans cible ne reçoit pas celle du
    # gabarit). Fourni par l'appelant, il n'est ni relu ni redit.
    ctx = contexte
    if ctx is None:
        ctx = contexte_modele(report_dir, field_parameter, cible_folders,
                              targets)
        journal_contexte(ctx, cible_folders, log)
    kpis_connus = ctx["kpis_connus"]
    if not targets:
        targets = list(kpis_connus)
    fp_forward, fp_reverse = ctx["fp_forward"], ctx["fp_reverse"]
    known, cibles = ctx["known"], ctx["cibles"]
    communes: set = set()
    sans_equiv: set = set()      # (mesure source, KPI) laissés de côté

    if entete is None:
        log(f"KPI template : {template_kpi}")
        cibles_hors_gabarit = [k for k in targets if k != template_kpi]
        log("KPI cibles   : " + (", ".join(cibles_hors_gabarit)
                                  or "aucune, le gabarit est seul"))
    else:
        for ligne in entete:
            log(ligne)
    if dry_run and contexte is None:
        log("*** DRY_RUN : aucun fichier modifié (diagnostic seulement) ***")

    # la propagation RETIRE maintenant ce que le template ne porte plus :
    # copie de chaque visual.json modifié avant écriture (undo = le recopier).
    # Une session FOURNIE est réutilisée telle quelle, et pas fermée ici.
    session_a_nous = backup_dir is None
    if not dry_run and session_a_nous:
        backup_dir = br.BackupSession(
            br.backup_root(report_dir.parent, "_propagate_backups"),
            "Propagation", report_dir.parent)
        log(f"Sauvegardes  : {backup_dir.dir} (visuels modifiés seulement)")

    total = 0
    n_visuals = 0
    for visual_json in sorted(report_dir.glob("definition/pages/*/visuals/*/visual.json")):
        n = process_visual(visual_json, template_kpi, targets, entity=entity,
                           branches=branches, verbose=verbose, dry_run=dry_run, log=log,
                           backup_dir=backup_dir, fp_forward=fp_forward, fp_reverse=fp_reverse,
                           known=known, communes=communes, sans_equiv=sans_equiv,
                           kpis_connus=kpis_connus, cibles=cibles,
                           cellules=cellules, classer=classer,
                           superposer=superposer,
                           memoire=(None if memoire is None else memoire.setdefault(
                               f"{visual_json.parents[2].name}/"
                               f"{visual_json.parent.name}", {})))
        if n:
            page = visual_json.parents[2].name
            log(f"  page {page} / visuel {visual_json.parent.name} : {n} entrée(s)")
            total += n
            n_visuals += 1

    if sans_equiv:
        par_kpi: dict = {}
        for mesure, kpi in sans_equiv:
            par_kpi.setdefault(kpi, []).append(mesure)
        log(f"KPI sans équivalent ({len(par_kpi)}), rien ne leur a été écrit "
            "pour ces attributs (le paramètre de champ ne leur donne pas ce "
            "calcul) :")
        for kpi in sorted(par_kpi):
            log(f"  ∅ {kpi} : {', '.join(sorted(set(par_kpi[kpi])))}")

    if communes:
        log(f"Mesures COMMUNES à toutes les branches ({len(communes)}), "
            "gardées telles quelles, elles n'ont pas de variante par branche :")
        for nom in sorted(communes):
            log("  = " + nom)
        log("  (si l'une d'elles DEVRAIT avoir une variante, c'est qu'elle "
            "manque au modèle : la générer, puis relancer.)")

    if backup_dir is not None and session_a_nous:
        # manifeste : d'où venait chaque copie -> restauration en un clic
        backup_dir.close(f"{total} entrée(s) sur {n_visuals} visuel(s), "
                         f"template {template_kpi}")

    log("Aucun changement." if total == 0 else f"Terminé : {total} entrée(s) écrites.")
    return total


# ------------------------------------------------ la grille des sources
#
# De quel KPI chaque KPI copie-t-il le formatage de chaque variation ? Une
# GRILLE KPI × variation, décrite par des règles. Pour une case, la première
# règle qui répond l'emporte :
#
#   1. une exception du KPI, pour cette variation ;
#   2. son GROUPE, pour cette variation ;
#   3. « Tous les KPI », pour cette variation — un gabarit par variation ;
#   4. une exception du KPI pour toutes ses variations ;
#   5. le GABARIT DE SON GROUPE ;
#   6. le GABARIT DE BASE.
#
# Une règle POUR UNE VARIATION passe donc avant une règle « toutes
# variations » : le PY de tout le monde se règle une fois (3). À niveau égal,
# le plus étroit gagne (KPI > groupe > tous).
#
# Un GROUPE est une famille de KPI qui se propagent entre eux : son gabarit
# (un de ses membres) donne à tous les autres ce qu'aucune règle plus précise
# ne règle. Un KPI n'est que dans un groupe ; le gabarit de base, dans aucun.
#
# Le gabarit d'un groupe se pose PAR-DESSUS le maître : il reçoit d'abord la
# base — ou, pour une variation, le gabarit de « Tous les KPI » —, puis ses
# propres réglages par-dessus, propriété par propriété (cf.
# superposer_entrees). Ses KPI le copient ensuite en entier. Le PY « Tous les
# KPI » arrive donc aux KPI d'un tel groupe PAR leur gabarit (niveau 5), et ce
# que le gabarit règle lui-même pour le PY l'emporte. Un groupe INDÉPENDANT
# (les groupes de l'ancien format, ou décoché dans la fenêtre) ne reçoit rien
# du maître : son gabarit est sa seule source, et « Tous les KPI » (3) passe
# avant lui pour ses KPI.
#
# Une source est un nom de KPI, ou MANUEL : la case est formatée à la main —
# rien ne lui est copié d'ailleurs (ses faces de branche suivent son Réel).
# Sans base ni règle, une case n'est à personne : ni remplie ni nettoyée.
#
# Une seule contrainte, mais elle tient tout : une SOURCE est sa propre source
# pour la variation qu'elle donne. Une copie de copie ferait dépendre le
# résultat de l'ordre des passes ; on la refuse (cf. Sources.problemes), et la
# grille de l'onglet Rapport ne sait pas en fabriquer (cf. Sources._reparer).
#
# propagation.json, format actuel :
#
#   {"version": 2,
#    "base": "Average Steps",
#    "colonnes": {"PY": "Total Steps"},
#    "groupes": [
#      {"nom": "Sommeil", "kpis": ["Average Sleep Duration", "Sleep Score"],
#       "base": "Average Sleep Duration",
#       "colonnes": {"YoY %": "Weight"}},
#      {"nom": "Poids", "kpis": ["Weight", "Body Fat %"], "base": "Weight",
#       "independant": true}],
#    "exceptions": [
#      {"source": "Weight", "kpis": ["Body Fat %"], "variations": ["YoY %"]},
#      {"source": "(manuel)", "kpis": ["Total Steps"], "variations": ["Réel"]}]}
#
# Une exception sans "variations" vaut pour toutes. La source d'une exception
# (ou d'un gabarit par variation) y est comprise d'office : elle donne sa
# variation, elle la garde. (Plus tard : des exceptions PAR VISUEL, pour les
# gros rapports — un champ "visuels" de plus, sans rien changer au reste.)

MANUEL = "(manuel)"
CHACUN = MANUEL                     # nom historique, gardé pour les scripts
_ANCIENS_MANUEL = {"(chacun le sien)"}
AUTRE = "(toute autre variation)"   # une variation qu'aucune règle ne nomme


def _source(valeur):
    """Une source lue dans le fichier : un nom de KPI, MANUEL, ou None."""
    if not valeur:
        return None
    valeur = str(valeur)
    return MANUEL if valeur in _ANCIENS_MANUEL else valeur



def variations_du_config(config) -> list:
    """[(id, suffixe)] de TOUTES les variations du config, dans son ordre —
    celles du paramètre de champ comme les autres (sparkline, couleurs CF…) :
    chacune est une colonne de la grille des sources.

    Le suffixe se lit dans namePattern (« {base} PY » -> « PY ») ; c'est lui
    qui range une mesure ABSENTE du paramètre de champ dans sa colonne. Une
    variation dont le nom ne commence pas par {base} n'en a pas (None) : elle
    a sa colonne, mais ses mesures se rangent par le paramètre de champ."""
    out = []
    for vid, tpl in ((config or {}).get("variations") or {}).items():
        motif = (tpl.get("namePattern") if isinstance(tpl, dict) else None) \
            or ("{base} " + str(vid))
        suffixe = (motif[len("{base}"):].strip()
                   if motif.startswith("{base}") else "")
        out.append((str(vid), suffixe or None))
    return out


def _config_voisin(report_dir) -> dict:
    """Le measures_config.json posé à côté du rapport, s'il y en a un (usage
    en ligne de commande ; l'app passe le config du projet)."""
    p = Path(report_dir).parent / "measures_config.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def libelle_reel(fp_reverse, defaut="Réel") -> str:
    """Le Calcul que le paramètre de champ donne à la mesure de BASE d'un KPI
    (« Réel » ici ; fieldParameter.baseLabel le rend réglable)."""
    vus: dict = {}
    for mesure, (kpi, calcul, _b) in (fp_reverse or {}).items():
        if mesure == kpi and calcul:
            vus[calcul] = vus.get(calcul, 0) + 1
    return max(vus, key=vus.get) if vus else defaut


def kpi_de(metadata, kpis_tries, entity=ENTITY):
    """KPI visé par ce metadata : le PLUS LONG nom de KPI qui le préfixe
    (`kpis_tries` va du plus long au plus court — « Total Steps Goal » avant
    « Total Steps »), sinon None."""
    if not metadata:
        return None
    for kpi in kpis_tries:
        for prefix in (entity + ".", ""):
            head = prefix + kpi
            if metadata == head or metadata.startswith(head + " "):
                return kpi
    return None


def classeur(*, entity=ENTITY, branches=BRANCHES, fp_reverse=None,
             variations=(), cibles=None, reel=None):
    """Rend classer(metadata, kpi) -> la VARIATION visée, c'est-à-dire une
    colonne de la grille des sources. Mémoïsé : appelé pour chaque entrée, à
    chaque passe. `classer.libelles` : les libellés des cibles rencontrées.

    Une mesure se lit ainsi : une RACINE — le KPI lui-même, ou une de ses
    CIBLES (« Weight cible ») —, une branche éventuelle, puis le suffixe d'une
    variation. La cible est une base à part entière, déclinée comme un KPI :
    « Weight cible écart » est la variation « écart » de la cible, donc la
    colonne « Cible écart » — le Calcul même que le générateur lui donne au
    paramètre de champ. Sans ça, toutes les variations d'une cible, absentes
    du paramètre, tombaient dans une colonne où leurs KPI n'avaient « pas de
    mesure ».

    Du plus sûr au plus deviné :
      1. le paramètre de champ connaît la mesure : son Calcul ;
      2. la racine : le plus long préfixe parmi le KPI et ses cibles — une
         cible se reconnaît à son dossier dédié, ou au paramètre de champ
         (un Calcul qui n'est ni le Réel ni une variation : « Cible ») ;
      3. la branche est mise de côté (« Weight YTD PY » est du PY) : une
         variation vit sur toutes ses branches, comme le gabarit l'entend ;
      4. le suffixe d'une variation du config — le plus long d'abord, pour
         que « CF YoY % » ne soit pas pris pour « YoY % » ;
      5. la racine connue du paramètre (mesure dérivée, hors paramètre) ;
      6. à défaut, le Réel : la mesure appartient au KPI lui-même.

    `branches` : TOUTES celles du modèle. Classer avec les seules branches
    cochées ferait de « Weight YTD PY » une variation « YTD »."""
    reel = reel or libelle_reel(fp_reverse)
    branches = [b for b in (branches or ()) if b]
    suffixes = sorted(((s, vid) for vid, s in (variations or ())
                       if s and s not in branches), key=lambda x: -len(x[0]))
    vids = [vid for vid, _s in (variations or ())]
    # les racines qui ne sont pas un KPI : nom -> libellé de sa colonne
    racines: dict = {}
    for mesure, (_k, calcul, _b) in (fp_reverse or {}).items():
        if (calcul and calcul != reel and calcul not in vids
                and not any(calcul.endswith(" " + v) for v in vids)):
            racines[mesure] = calcul
    for mesure in cibles or ():
        info = (fp_reverse or {}).get(mesure)
        racines.setdefault(mesure, (info[1] if info and info[1] else "Cible"))
    memo: dict = {}

    def _classer(md, kpi):
        bare = md[len(entity) + 1:] if md.startswith(entity + ".") else md
        info = (fp_reverse or {}).get(bare)
        if info and info[0] == kpi:
            return info[1] or reel
        if bare != kpi and not bare.startswith(kpi + " "):
            return reel
        racine, libelle = kpi, None
        for r, lib in racines.items():
            if (len(r) > len(racine) and r.startswith(kpi + " ")
                    and (bare == r or bare.startswith(r + " "))):
                racine, libelle = r, lib
        reste = bare[len(racine):].strip()
        for b in branches:
            if reste == b:
                reste = ""
                break
            if reste.startswith(b + " "):
                reste = reste[len(b) + 1:]
                break
        if not reste:
            return libelle or reel
        for s, vid in suffixes:
            if reste == s or reste.startswith(s + " "):
                return f"{libelle} {vid}" if libelle else vid
        if libelle:
            return f"{libelle} {reste}"
        r_fp, _ = racine_fp(md, kpi, entity, fp_reverse)
        if r_fp is not None:
            return fp_reverse[r_fp][1] or reel
        return reel

    def classer(metadata, kpi):
        cle = (metadata, kpi)
        if cle not in memo:
            memo[cle] = _classer(metadata or "", kpi)
        return memo[cle]
    classer.libelles = list(dict.fromkeys(racines.values()))
    return classer


def contexte_modele(report_dir, field_parameter=FIELD_PARAMETER,
                    cible_folders=(), targets=None) -> dict:
    """Ce qu'une passe lit du modèle : les KPI, le paramètre de champ, les
    mesures existantes, les cibles. Une grille de N sources le lit UNE fois
    (cf. `contexte` dans propagate).

    Paramètre de champ illisible : on ne l'exige que si les cibles n'ont pas
    été données explicitement — l'ancien comportement de propagate."""
    report_dir = Path(report_dir)
    semantic_dir = Path(str(report_dir).replace(".Report", ".SemanticModel"))
    try:
        kpis_connus = kpis_from_parameter(semantic_dir, field_parameter)
    except SystemExit:
        if not targets:
            raise
        kpis_connus = list(targets)
    fp_forward, fp_reverse = read_fp_maps(semantic_dir, field_parameter)
    return {"semantic_dir": semantic_dir, "kpis_connus": kpis_connus,
            "fp_forward": fp_forward, "fp_reverse": fp_reverse,
            "known": measures_of_model(semantic_dir),
            "cibles": cibles_of_model(semantic_dir, cible_folders)}


def journal_contexte(ctx, cible_folders, log) -> None:
    """Le compte rendu de ce qu'on a lu du modèle — une fois par action."""
    if ctx["fp_reverse"]:
        log(f"Paramètre de champ : {len(ctx['fp_reverse'])} mesure(s) "
            f"mappée(s) (KPI/Calcul/Branche).")
    if ctx["cibles"]:
        log(f"Cibles       : {len(ctx['cibles'])} mesure(s) dans "
            + ", ".join(str(d) for d in cible_folders)
            + " (un KPI sans cible ne recevra pas celle du gabarit).")
    if ctx["known"]:
        log(f"Modèle : {len(ctx['known'])} mesure(s) connues (référence "
            f"vérifiée avant écriture).")
    else:
        log("⚠ Modèle introuvable : les noms de mesures ne seront pas "
            "vérifiés avant écriture.")


def analyser(report_dir, *, entity=ENTITY, field_parameter=FIELD_PARAMETER,
             branches=BRANCHES, variations=(), cible_folders=(), kpis=None,
             contexte=None) -> dict:
    """Ce que la grille des sources doit savoir du modèle et du rapport :

      kpis        les KPI, dans l'ordre du paramètre de champ ;
      variations  les colonnes, lues dans les MESURES qui existent —
                  dans le paramètre de champ ou non : le Réel, les
                  variations du config (son ordre), puis chaque cible et
                  ses variations (« Cible », « Cible écart »…), puis le
                  reste. Une BRANCHE n'est pas une colonne : « Weight YTD
                  PY » est du PY, sa face YTD ;
      mesures     {(KPI, variation)} qui existent dans le modèle — un KPI
                  sans cible n'a pas de case « Cible » à remplir ;
      reglages    {(KPI, variation): {visuel: entrées}} — le formatage que
                  la propagation lit, écrit et retire ;
      classer     la fonction qui range une mesure dans sa colonne.

    Les couleurs statiques des matrices (color_matrix_by_kpi) ne comptent
    pas : la propagation n'y touche pas."""
    report_dir = Path(report_dir)
    ctx = contexte or contexte_modele(report_dir, field_parameter,
                                      cible_folders, kpis)
    kpis = list(kpis if kpis is not None else ctx["kpis_connus"])
    fp_forward, fp_reverse = ctx["fp_forward"], ctx["fp_reverse"]
    reel = libelle_reel(fp_reverse)
    classer = classeur(entity=entity, branches=branches, fp_reverse=fp_reverse,
                       variations=variations, cibles=ctx["cibles"], reel=reel)
    tries = sorted(kpis, key=len, reverse=True)

    mesures: set = set()
    for nom in ctx["known"]:
        k = kpi_de(nom, tries, entity)
        if k is not None:
            mesures.add((k, classer(nom, k)))

    reglages: dict = {}
    for vj in sorted(report_dir.glob("definition/pages/*/visuals/*/visual.json")):
        try:
            data = json.loads(lire_texte(vj))
        except (OSError, ValueError):
            continue
        objets = (data.get("visual") or {}).get("objects")
        if not isinstance(objets, dict):
            continue
        visuel = f"{vj.parents[2].name}/{vj.parent.name}"
        emplacements = emplacements_de(objets, classer, tries, entity)
        for cle, entrees in objets.items():
            if not isinstance(entrees, list):
                continue
            for e in entrees:
                if owned_by_color_matrix(cle, e):
                    continue
                md = entry_metadata(e)
                k = kpi_de(md, tries, entity)
                if k is None:
                    continue
                par_visuel = reglages.setdefault(
                    (k, variation_entree(e, k, classer, emplacements, entity,
                                         cle)),
                    {})
                par_visuel[visuel] = par_visuel.get(visuel, 0) + 1

    # les colonnes : ce qui EXISTE (mesures du modèle, formatage en place),
    # rangé — le Réel, les variations du KPI dans l'ordre du config, puis
    # chaque cible et ses variations, puis le reste
    presentes = {v for (_k, v) in mesures} | {v for (_k, v) in reglages}
    colonnes = [reel]

    def ajouter(v):
        if v in presentes and v not in colonnes:
            colonnes.append(v)

    for vid, _s in variations or ():
        if vid not in branches:
            ajouter(vid)
    for libelle in classer.libelles:
        ajouter(libelle)
        for vid, _s in variations or ():
            ajouter(f"{libelle} {vid}")
    for (_k, calcul, _b) in fp_forward:
        ajouter(calcul)
    for v in sorted(presentes):
        ajouter(v)
    # le détail d'une étiquette juste après elle
    details = [v for v in colonnes if etiquette_du_detail(v) is not None]
    rangees: list = []
    for v in colonnes:
        if v in details:
            continue
        rangees.append(v)
        if colonne_detail(v) in details:
            rangees.append(colonne_detail(v))
    colonnes = rangees + [d for d in details if d not in rangees]
    # un KPI a le détail d'une étiquette s'il en a la mesure
    mesures |= {(k, colonne_detail(v)) for (k, v) in mesures
                if colonne_detail(v) in details}
    return {"kpis": kpis, "variations": colonnes, "reel": reel,
            "mesures": mesures, "reglages": reglages, "classer": classer}


def _regles_propres(data) -> dict | None:
    """Le format actuel, lu avec tolérance : ce qui ne se comprend pas est
    laissé de côté plutôt que de tout refuser."""
    def colonnes_de(d):
        if not isinstance(d, dict):
            return {}
        return {str(v): _source(s) for v, s in d.items() if v and s}

    groupes = []
    for gr in data.get("groupes") or []:
        if not isinstance(gr, dict) or not gr.get("nom"):
            continue
        groupes.append({"nom": str(gr["nom"]),
                        "kpis": [str(k) for k in (gr.get("kpis") or []) if k],
                        "base": _source(gr.get("base")),
                        "colonnes": colonnes_de(gr.get("colonnes")),
                        "independant": bool(gr.get("independant"))})
    exceptions = []
    for x in data.get("exceptions") or []:
        if not isinstance(x, dict) or not x.get("source"):
            continue
        ex = {"source": _source(x["source"]),
              "kpis": [str(k) for k in (x.get("kpis") or []) if k]}
        if not ex["kpis"] and ex["source"] == MANUEL:
            continue
        variations = [str(v) for v in (x.get("variations") or []) if v]
        if variations:
            ex["variations"] = variations
        exceptions.append(ex)
    regles = {"base": _source(data.get("base")),
              "colonnes": colonnes_de(data.get("colonnes")),
              "groupes": groupes, "exceptions": exceptions}
    if not (regles["base"] or regles["colonnes"] or groupes or exceptions):
        return None
    return regles


def regles_depuis_groupes(groupes) -> dict:
    """L'ancien format dans le nouveau, sans rien changer au résultat : le
    groupe SANS liste de KPI devient la base ; chaque autre groupe reste un
    GROUPE, avec son gabarit — INDÉPENDANT, comme il l'était : il ne reçoit
    rien de la base. Sans groupe par défaut, un KPI dans aucun groupe reste
    hors propagation, comme avant — et les passes gardent l'ordre des
    groupes."""
    defauts = [g for g in groupes if not g["kpis"]]
    return {"base": defauts[0]["gabarit"] if defauts else None,
            "colonnes": {},
            "groupes": [{"nom": g["nom"], "kpis": list(g["kpis"]),
                         "base": g["gabarit"], "colonnes": {},
                         "independant": True}
                        for g in groupes if g["kpis"]],
            "exceptions": [],
            "ordre": [g["gabarit"] for g in groupes],
            "anciens_groupes": groupes}


def lire_regles(chemin) -> dict | None:
    """Les règles de propagation.json, ou None (absent, vide, illisible).

    Deux formats : l'actuel ({"version": 2, "base", "colonnes", "groupes",
    "exceptions"}) et l'ancien ({"groupes": [...]} avec un gabarit par
    groupe), converti à la lecture — un fichier d'avant marche tel quel.
    Jamais d'exception : le fichier est facultatif."""
    if not chemin:
        return None
    p = Path(chemin)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and any(
            k in data for k in ("base", "colonnes", "exceptions", "version")):
        return _regles_propres(data)
    groupes = read_groupes(p)
    return regles_depuis_groupes(groupes) if groupes else None


def ecrire_regles(chemin, regles) -> None:
    """propagation.json, lisible à la main (indentation, accents en clair)."""
    Path(chemin).write_text(
        json.dumps(regles, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")


class _CasesDe:
    """Les cases d'UNE source, telles que process_visual les interroge :
    `(kpi, variation) in cases`."""

    def __init__(self, grille, source):
        self.grille, self.source = grille, source

    def __contains__(self, cle):
        kpi, variation = cle
        g = self.grille
        # garde-fou : une source qui ne serait pas la sienne pour cette
        # variation ne donne rien — une copie de copie dépendrait de l'ordre
        return (g.source(kpi, variation) == self.source
                and g.source(self.source, variation) == self.source)


class _CouchesDe:
    """Les cases d'une passe PAR-DESSOUS : un maître et les gabarits de
    groupe qu'il passe sous (cf. Sources.sous_couche)."""

    def __init__(self, grille, source, gabarits):
        self.grille, self.source = grille, source
        self.gabarits = list(gabarits)

    def __contains__(self, cle):
        kpi, variation = cle
        g = self.grille
        if kpi == self.source:
            return any(g.sous_couche(t, variation) == self.source
                       for t in self.gabarits)
        return (kpi in self.gabarits
                and g.sous_couche(kpi, variation) == self.source)


def groupe_en_mots(nom, majuscule=False) -> str:
    """« groupe Sommeil » — mais « groupe 2 » (un ancien nom) ne devient pas
    « groupe groupe 2 »."""
    if str(nom).lower().startswith(("groupe", "group")):
        return str(nom)
    return ("Groupe " if majuscule else "groupe ") + str(nom)


# les niveaux de règle, du plus précis au plus large (cf. Sources.niveau)
NIVEAUX = ("case", "groupe", "tous", "ligne", "gabarit_groupe", "base")


class Sources:
    """La grille des sources : de quel KPI chaque (KPI, variation) copie son
    formatage. Pour une case, la première règle qui répond l'emporte (cf. le
    commentaire de tête de section) :

      1. case            une exception du KPI, pour cette variation ;
      2. groupe          son groupe, pour cette variation ;
      3. tous            « Tous les KPI », pour cette variation ;
      4. ligne           une exception du KPI, pour toutes ses variations ;
      5. gabarit_groupe  le gabarit de son groupe — par-dessus la base, et
                         pour ses KPI la ligne « Tous les KPI » passe PAR lui
                         (sauf groupe indépendant) ;
      6. base            le gabarit de base.

    Sert au moteur (propagate_regles) ET à la fenêtre qui l'édite : les
    règles d'édition — une source est toujours sa propre source, ceux qui la
    copiaient la suivent, ce que l'usager a posé reste posé — vivent ICI,
    testables sans interface."""

    def __init__(self, kpis, variations=(), base=None):
        self.kpis = list(kpis)
        self.variations = list(dict.fromkeys(variations))
        self.base = base
        self.colonnes: dict = {}      # variation -> KPI | MANUEL (tous les KPI)
        self.groupes: dict = {}       # nom -> {"kpis", "base", "colonnes",
                                      #         "independant"}
        self.groupe_de: dict = {}     # KPI -> nom de son groupe
        self.lignes: dict = {}        # KPI -> KPI | MANUEL (toutes ses variations)
        self.cases: dict = {}         # (KPI, variation) -> KPI | MANUEL
        self.ordre = None             # ordre des passes imposé (ancien format)
        self.erreurs: list = []       # relevées à la lecture (conflits…)
        self.avertissements: list = []
        self._nommees: list = []      # variations nommées par les règles
        self._analysees = bool(self.variations)
        # cases (et lignes) « à la main » parce que SOURCE, pas parce que
        # l'usager l'a demandé : elles s'en vont avec leur dernier copieur
        self._implicites: set = set()
        self._lignes_implicites: set = set()
        # règles posées par une RÉPARATION, pas par l'usager : elles seules
        # peuvent disparaître quand elles ne changent plus rien. Ce que
        # l'usager pose reste posé, même égal à ce qu'il hérite — son PY
        # « pour tous » doit tenir le jour où un groupe apparaît.
        self._auto: set = set()

    # ---- lecture -----------------------------------------------------------

    @classmethod
    def depuis_regles(cls, regles, kpis, variations=()):
        g = cls(kpis, variations)
        regles = regles or {}
        connus = set(g.kpis)
        g.base = _source(regles.get("base"))
        g.ordre = list(regles.get("ordre") or []) or None
        for v, src in (regles.get("colonnes") or {}).items():
            g._nommer(v)
            g.colonnes[v] = _source(src)
        absents: list = []

        for gr in regles.get("groupes") or []:
            nom = gr.get("nom")
            if not nom:
                continue
            if nom in g.groupes:
                g.erreurs.append(f"Deux groupes s'appellent « {nom} ».")
                continue
            base_g = _source(gr.get("base"))
            lus = [k for k in (gr.get("kpis") or []) if k]
            # le gabarit d'un groupe en est membre, d'office
            if base_g and base_g != MANUEL and base_g not in lus:
                lus.insert(0, base_g)
            membres = []
            for k in lus:
                if k not in connus:
                    absents.append(k)
                    continue
                if k in g.groupe_de:
                    g.erreurs.append(
                        f"« {k} » est dans deux groupes, « {g.groupe_de[k]} » "
                        f"et « {nom} », le retirer de l'un des deux.")
                    continue
                g.groupe_de[k] = nom
                membres.append(k)
            colonnes_g = {}
            for v, src in (gr.get("colonnes") or {}).items():
                g._nommer(v)
                colonnes_g[v] = _source(src)
            g.groupes[nom] = {"kpis": membres, "base": base_g,
                              "colonnes": colonnes_g,
                              "independant": bool(gr.get("independant"))}

        voulues: set = set()          # « à la main » demandés tels quels
        lignes_voulues: set = set()
        for ex in regles.get("exceptions") or []:
            src = _source(ex.get("source"))
            if not src:
                continue
            kpis_ex = [k for k in (ex.get("kpis") or []) if k]
            # la source DONNE sa variation : elle la garde, d'office. Cette
            # case-là n'existe que pour ses copieurs : IMPLICITE, elle s'en va
            # avec le dernier (cf. _menage_colonne).
            implicite = (src != MANUEL
                         and any(k != src and k in connus for k in kpis_ex))
            if src != MANUEL and src not in kpis_ex:
                kpis_ex.insert(0, src)
            variations_ex = [v for v in (ex.get("variations") or []) if v]
            for v in variations_ex:
                g._nommer(v)
            for k in kpis_ex:
                if k not in connus:
                    absents.append(k)
                    continue
                valeur = MANUEL if src == k else src
                sienne_implicite = k == src and implicite
                if variations_ex:
                    for v in variations_ex:
                        g._poser(g.cases, (k, v), valeur,
                                 f"« {k} » · « {v} »")
                        if valeur == MANUEL:
                            (g._implicites if sienne_implicite
                             else voulues).add((k, v))
                else:
                    g._poser(g.lignes, k, valeur,
                             f"« {k} » (toutes ses variations)")
                    if valeur == MANUEL:
                        (g._lignes_implicites if sienne_implicite
                         else lignes_voulues).add(k)
        # une « à la main » demandée explicitement l'emporte sur la même,
        # implicite
        g._implicites -= voulues
        g._lignes_implicites -= lignes_voulues
        g._sources_gardent_leur_variation()
        if absents:
            g.avertissements.append(
                "KPI absent(s) du modèle, ignoré(s) : "
                + ", ".join(dict.fromkeys(absents)) + ".")
        return g

    def _sources_gardent_leur_variation(self):
        """Un KPI nommé par un gabarit PAR VARIATION (tous les KPI, ou un
        groupe) donne cette variation : il la garde, d'office — sinon, pris
        par une règle plus précise, il copierait ailleurs ce qu'il donne."""
        for v in self._toutes_variations():
            nommees = [self.colonnes.get(v)] + [
                gr["colonnes"].get(v) for gr in self.groupes.values()]
            for s in dict.fromkeys(nommees):
                if (s and s != MANUEL and s in self.kpis
                        and (s, v) not in self.cases
                        and self.source(s, v) != s):
                    self.cases[(s, v)] = MANUEL
                    self._implicites.add((s, v))

    def _nommer(self, v):
        if v not in self.variations:
            self.variations.append(v)
            self._nommees.append(v)

    def _poser(self, table, cle, valeur, quoi):
        if cle in table and table[cle] != valeur:
            self.erreurs.append(
                f"{quoi} a deux sources : {self.nom(table[cle])} et "
                f"{self.nom(valeur)}, une case n'en a qu'une.")
            return
        table[cle] = valeur

    @staticmethod
    def nom(s):
        """Une source, en mots."""
        if s == MANUEL:
            return "« à la main »"
        return f"« {s} »" if s else "aucune"

    # ---- résolution ----------------------------------------------------------

    def par_dessus(self, nom):
        """Le gabarit du groupe `nom` s'il se pose PAR-DESSUS le maître (un
        KPI, groupe non indépendant), sinon None."""
        gr = self.groupes.get(nom)
        if (gr is None or gr.get("independant")
                or gr["base"] in (None, MANUEL) or gr["base"] not in self.kpis):
            return None
        return gr["base"]

    def gabarits_par_dessus(self) -> list:
        return [t for t in (self.par_dessus(nom) for nom in self.groupes) if t]

    @staticmethod
    def _chaine_variations(variation) -> list:
        """La variation, puis l'étiquette dont elle est le DÉTAIL : le détail
        suit son étiquette tant qu'aucune règle ne le nomme lui."""
        etiquette = etiquette_du_detail(variation)
        return [variation] + ([etiquette] if etiquette else [])

    def _decision(self, kpi, variation):
        """(niveau, qui, variation dont la règle décide) — cf. niveau."""
        nom = self.groupe_de.get(kpi)
        groupe = self.groupes.get(nom)
        for v in self._chaine_variations(variation):
            if (kpi, v) in self.cases:
                return ("case", kpi, v)
            if groupe is not None and v in groupe["colonnes"]:
                return ("groupe", nom, v)
            if v in self.colonnes:
                # le gabarit par variation de « Tous les KPI » arrive aux KPI
                # d'un groupe PAR leur gabarit, qui se pose par-dessus (cf.
                # sous_couche). « À la main » pour tous reste à la main.
                if self.colonnes[v] != MANUEL and self.par_dessus(nom):
                    return ("gabarit_groupe", nom, v)
                return ("tous", None, v)
        if kpi in self.lignes:
            return ("ligne", kpi, variation)
        if groupe is not None and groupe["base"]:
            return ("gabarit_groupe", nom, variation)
        return ("base", None, variation)

    def niveau(self, kpi, variation):
        """(niveau, qui) : la règle qui décide de la case — cf. NIVEAUX."""
        quoi, qui, _v = self._decision(kpi, variation)
        return (quoi, qui)

    def suit_son_etiquette(self, kpi, variation) -> bool:
        """Une case de DÉTAIL décidée par la règle de son étiquette."""
        return self._decision(kpi, variation)[2] != variation

    def sous_couche(self, kpi, variation):
        """Ce qui passe SOUS une case de gabarit de groupe : le maître — le
        gabarit de « Tous les KPI » pour cette variation, sinon la base —,
        que le gabarit reçoit d'abord avant ses propres réglages. None :
        rien dessous (pas un gabarit qui se pose par-dessus, ou une règle
        posée sur la case, sur le groupe pour cette variation, ou sur le KPI
        pour toutes : elle dit tout)."""
        nom = self.groupe_de.get(kpi)
        if nom is None or self.par_dessus(nom) != kpi:
            return None
        if self.source(kpi, variation) != kpi:
            return None
        gr = self.groupes[nom]
        u = self.base
        for v in self._chaine_variations(variation):
            if (kpi, v) in self.cases and (kpi, v) not in self._implicites:
                return None
            if v in gr["colonnes"]:
                return None
            if v in self.colonnes:
                u = self.colonnes[v]
                break
        else:
            if kpi in self.lignes and kpi not in self._lignes_implicites:
                return None
        if u in (None, MANUEL, kpi) or u not in self.kpis:
            return None
        # le maître doit être SA source : sinon ce serait une copie de copie
        return u if self.source(u, variation) == u else None

    def couches(self) -> dict:
        """{maître: [gabarits de groupe qu'il passe sous]} — les passes
        PAR-DESSOUS, à faire avant toutes les autres."""
        out: dict = {}
        for t in self.gabarits_par_dessus():
            for v in self._toutes_variations():
                u = self.sous_couche(t, v)
                if u and t not in out.setdefault(u, []):
                    out[u].append(t)
        return out

    def regle(self, kpi, variation):
        """La valeur de la règle qui décide : un KPI, MANUEL ou None."""
        quoi, qui, v = self._decision(kpi, variation)
        if quoi == "case":
            return self.cases[(kpi, v)]
        if quoi == "groupe":
            return self.groupes[qui]["colonnes"][v]
        if quoi == "tous":
            return self.colonnes[v]
        if quoi == "ligne":
            return self.lignes[kpi]
        if quoi == "gabarit_groupe":
            return self.groupes[qui]["base"]
        return self.base

    def source(self, kpi, variation):
        """Le KPI dont (kpi, variation) copie le formatage — lui-même s'il est
        à la main —, ou None : la case n'est à personne."""
        s = self.regle(kpi, variation)
        return kpi if s == MANUEL else s

    def donne(self, kpi, variation) -> bool:
        """D'autres KPI copient-ils cette case ?"""
        return any(x != kpi and self.source(x, variation) == kpi
                   for x in self.kpis)

    def gabarit(self, kpi, variation) -> bool:
        """La case est-elle un GABARIT — formatée à la main ET copiée, ou
        nommée comme gabarit par une règle (la base, un gabarit de groupe,
        un gabarit par variation) ? Sinon, à la main, elle est « manuelle »."""
        return self.source(kpi, variation) == kpi and (
            self.donne(kpi, variation) or self.regle(kpi, variation) == kpi)

    def _toutes_variations(self) -> list:
        return self.variations + [AUTRE]

    def sources(self) -> list:
        """Les sources, dans l'ordre des passes : celui des anciens groupes
        s'il y en a (résultat identique au caractère), sinon la base
        d'abord, puis dans l'ordre de la grille."""
        vues: list = []
        for s in (self.ordre or []) + [self.base]:
            if s and s not in vues:
                vues.append(s)
        for k in self.kpis:
            for v in self._toutes_variations():
                s = self.source(k, v)
                if s and s not in vues:
                    vues.append(s)
        return [s for s in vues if s in self.kpis]

    def cases_de(self, source) -> _CasesDe:
        return _CasesDe(self, source)

    # ---- validation ----------------------------------------------------------

    def problemes(self):
        """(erreurs, avertissements). Une erreur empêche d'écrire : on ne
        devine pas l'intention, et propager au hasard réécrirait un rapport
        entier de travers."""
        erreurs = list(self.erreurs)
        avert = list(self.avertissements)
        connus = set(self.kpis)

        def inconnue(s):
            return s is not None and s != MANUEL and s not in connus

        if inconnue(self.base):
            erreurs.append(
                f"Gabarit de base introuvable parmi les KPI : « {self.base} ».")
        if self.base in self.groupe_de:
            erreurs.append(
                f"« {self.base} » est le gabarit de base : il ne peut pas être "
                f"dans un groupe (« {self.groupe_de[self.base]} »).")
        for v, s in self.colonnes.items():
            if inconnue(s):
                erreurs.append(f"Tous les KPI, « {v} » : source « {s} » "
                               "introuvable parmi les KPI.")
        for nom, gr in self.groupes.items():
            if inconnue(gr["base"]):
                erreurs.append(f"Groupe « {nom} » : gabarit « {gr['base']} » "
                               "introuvable parmi les KPI.")
            for v, s in gr["colonnes"].items():
                if inconnue(s):
                    erreurs.append(f"Groupe « {nom} », « {v} » : source "
                                   f"« {s} » introuvable parmi les KPI.")
        for s in dict.fromkeys(list(self.lignes.values())
                               + list(self.cases.values())):
            if inconnue(s):
                erreurs.append(f"Source introuvable parmi les KPI : « {s} ».")
        if erreurs:
            return erreurs, list(dict.fromkeys(avert))

        dites: set = set()
        for v in self._toutes_variations():
            for k in self.kpis:
                s = self.source(k, v)
                if s in (None, k) or (s, v) in dites:
                    continue
                s2 = self.source(s, v)
                if s2 != s:
                    dites.add((s, v))
                    erreurs.append(self._chaine(k, v, s, s2))

        if self._analysees and self._nommees:
            avert.append(
                "Variation(s) sans formatage dans ce rapport : "
                + ", ".join(f"« {v} »" for v in self._nommees)
                + ", sans effet tant qu'aucun visuel ne les formate.")
        for nom, gr in self.groupes.items():
            if not gr["kpis"]:
                avert.append(f"Le groupe « {nom} » n'a aucun KPI.")
        hors = [k for k in self.kpis
                if all(self.source(k, v) is None
                       for v in self._toutes_variations())]
        if hors:
            avert.append(f"{len(hors)} KPI non propagé(s) (ni gabarit, ni "
                         "règle), ni remplis ni nettoyés : "
                         + ", ".join(hors) + ".")
        return erreurs, list(dict.fromkeys(avert))

    def _chaine(self, k, v, s, s2) -> str:
        quoi = "toutes ses variations" if v == AUTRE else f"« {v} »"
        s2_ = f"« {s2} »" if s2 else "aucun KPI"
        if s == self.base and self.niveau(k, v)[0] == "base":
            return (f"« {s} » est le gabarit de base : les KPI qui le suivent "
                    f"copient son {quoi}, il ne peut pas lui-même le copier "
                    f"de {s2_}. Donner {quoi} à tous les KPI depuis {s2_} "
                    f"(ligne « Tous les KPI »), ou mettre « {s} » à la main "
                    "pour cette variation.")
        return (f"« {k} » copie {quoi} de « {s} », qui le copie lui-même de "
                f"{s2_} : une copie de copie dépendrait de l'ordre des "
                f"passes. Faire copier « {k} » directement de {s2_}, ou mettre "
                f"« {s} » à la main pour cette variation.")

    # ---- comptes rendus --------------------------------------------------------

    def _rang(self, v):
        vs = self._toutes_variations()
        return vs.index(v) if v in vs else len(vs)

    def _variations_rangees(self, noms):
        return sorted(noms, key=self._rang)

    def resume(self) -> list:
        """Le plan, pour le journal : une ligne « clé : valeurs » par règle,
        que le journal range en tableau."""
        out = [f"Sources du formatage, gabarit de base : "
               f"{self.base or 'aucun'}"]
        if self.base:
            out.append(f"  {self.base} : gabarit de base (tout le reste)")

        def par_source(regles):
            """{variation: source} -> [(source, [variations])], dans l'ordre."""
            groupes: dict = {}
            for v in self._variations_rangees(regles):
                groupes.setdefault(regles[v], []).append(v)
            return list(groupes.items())

        def ligne(s, vs, qui):
            vs = ", ".join(vs)
            return (f"  {vs} à la main : {qui}" if s == MANUEL
                    else f"  {s} → {vs} : {qui}")

        for s, vs in par_source(self.colonnes):
            out.append(ligne(s, vs, "tous les KPI"))
        for nom, gr in self.groupes.items():
            tete = groupe_en_mots(nom, majuscule=True)
            if gr["base"] == MANUEL:
                tete += " à la main"
            elif gr["base"]:
                tete += f" ← {gr['base']}"
                if gr.get("independant"):
                    tete += ", indépendant"
                elif self.base or self.colonnes:
                    tete += (", par-dessus la base" if self.base
                             else ", par-dessus « Tous les KPI »")
            out.append(f"  {tete} : " + (", ".join(gr["kpis"]) or "aucun KPI"))
            for s, vs in par_source(gr["colonnes"]):
                out.append(ligne(s, vs, groupe_en_mots(nom)))
        par_ligne: dict = {}
        for k in self.kpis:
            if k in self.lignes:
                s = self.lignes[k]
                if s == MANUEL and (k in self._lignes_implicites
                                    or self._donne_tout(k)):
                    continue               # un gabarit, pas une « à la main »
                par_ligne.setdefault(s, []).append(k)
        for s, ks in par_ligne.items():
            out.append(ligne(s, ["toutes les variations"], ", ".join(ks)))
        dons: dict = {}      # (source, KPI copieurs) -> [variations]
        for v in self._toutes_variations():
            par_src: dict = {}
            for k in self.kpis:
                s = self.cases.get((k, v))
                if s is None or (s == MANUEL and self.donne(k, v)):
                    continue               # un gabarit, pas une « à la main »
                par_src.setdefault(s, []).append(k)
            for s, ks in par_src.items():
                dons.setdefault((s, tuple(ks)), []).append(v)
        for (s, ks), vs in dons.items():
            out.append(ligne(s, vs, ", ".join(ks)))
        return out

    def exceptions_de_kpi(self) -> set:
        """Les KPI qui ont une exception à eux (hors cases implicites)."""
        return ({k for (k, v) in self.cases if (k, v) not in self._implicites}
                | (set(self.lignes) - self._lignes_implicites))

    def resume_court(self) -> str:
        """Une ligne, pour l'onglet Rapport."""
        def compte(n, un, plusieurs):
            return f"{n} {un if n == 1 else plusieurs}"

        morceaux = [f"gabarit de base : {self.base}" if self.base
                    else "pas de gabarit de base"]
        if self.groupes:
            morceaux.append(compte(len(self.groupes), "groupe", "groupes"))
        if self.colonnes:
            morceaux.append(compte(len(self.colonnes), "gabarit par variation",
                                   "gabarits par variation"))
        n = len(self.exceptions_de_kpi())
        if n:
            morceaux.append(compte(n, "KPI avec une exception",
                                   "KPI avec des exceptions"))
        return " · ".join(morceaux)

    # ---- édition : les cases (la fenêtre de l'onglet Rapport) -------------------

    def _etat(self, variations) -> dict:
        return {(k, v): self.source(k, v)
                for v in variations for k in self.kpis}

    def _deplier(self, kpi):
        """Une LIGNE devient des cases : on ne peut changer une variation d'un
        KPI sans toucher aux autres qu'en les nommant une à une. (Une
        variation qui apparaîtrait plus tard suivra alors les règles plus
        larges.)"""
        if kpi in self.lignes:
            s = self.lignes.pop(kpi)
            implicite = kpi in self._lignes_implicites
            self._lignes_implicites.discard(kpi)
            for v in self.variations:
                if (kpi, v) not in self.cases:
                    self.cases[(kpi, v)] = s
                    if implicite and s == MANUEL:
                        self._implicites.add((kpi, v))

    def _poser_case(self, kpi, variation, valeur, implicite=False, auto=False):
        """`implicite` : la case est « à la main » parce qu'elle est SOURCE ;
        `auto` : posée par une réparation (cf. _auto)."""
        self._deplier(kpi)
        self._implicites.discard((kpi, variation))
        cle = ("case", kpi, variation)
        (self._auto.add if auto else self._auto.discard)(cle)
        if valeur is None:
            self.cases.pop((kpi, variation), None)
            self._auto.discard(cle)
            return
        valeur = MANUEL if valeur == kpi else valeur
        self.cases[(kpi, variation)] = valeur
        if implicite and valeur == MANUEL:
            self._implicites.add((kpi, variation))

    def _poser_groupe(self, nom, variation, valeur, auto=False):
        cle = ("groupe", nom, variation)
        (self._auto.add if auto else self._auto.discard)(cle)
        if valeur is None:
            self.groupes[nom]["colonnes"].pop(variation, None)
            self._auto.discard(cle)
        else:
            self.groupes[nom]["colonnes"][variation] = valeur

    def _poser_tous(self, variation, valeur, auto=False):
        cle = ("tous", variation)
        (self._auto.add if auto else self._auto.discard)(cle)
        if valeur is None:
            self.colonnes.pop(variation, None)
            self._auto.discard(cle)
        else:
            self.colonnes[variation] = valeur

    def appliquer(self, cases, valeur) -> list:
        """Pose `valeur` sur des cases [(qui, variation)] — qui : un KPI,
        None (la ligne « Tous les KPI ») ou ("groupe", nom). `valeur` : un
        KPI (copier depuis), MANUEL (à la main) ou None (retirer la règle).
        Puis répare, pour qu'aucune case ne copie une copie. Rend les
        phrases à montrer à l'usager."""
        cases = list(cases)
        colonnes = sorted({v for _q, v in cases}, key=self._rang)
        # le détail d'une étiquette la suit : il se répare avec elle
        colonnes += [colonne_detail(v) for v in list(colonnes)
                     if colonne_detail(v) in self.variations
                     and colonne_detail(v) not in colonnes]
        avant = self._etat(colonnes)
        for qui, v in cases:
            if qui is None:
                self._poser_tous(v, valeur)
            elif isinstance(qui, tuple):
                self._poser_groupe(qui[1], v, valeur)
            else:
                self._poser_case(qui, v, valeur)
        voulu = self._etat(colonnes)
        notes: list = []
        for v in colonnes:
            notes += self._reparer(v, avant, voulu)
        return notes

    def _repointer(self, niveau, kpi, v, nouvelle):
        quoi, qui = niveau
        if quoi in ("case", "ligne"):
            self._poser_case(kpi, v, nouvelle,
                             implicite=nouvelle == kpi, auto=True)
        elif quoi in ("groupe", "gabarit_groupe"):
            self._poser_groupe(qui, v, nouvelle, auto=True)
        else:                                  # « tous » ou la base
            self._poser_tous(v, nouvelle, auto=True)

    def _epingler(self, v, voulu, bouges):
        """Seuls ceux qui copiaient la source déplacée changent de source. Un
        repointage PARTAGÉ (tous les KPI, un groupe) en déplacerait d'autres
        — un groupe qui suivait son gabarit, par exemple : on les remet où
        ils étaient, au niveau de leur groupe si tout le groupe a bougé
        pareil, sinon case par case."""
        deplaces = [k for k in self.kpis if k not in bouges
                    and self.source(k, v) != voulu[(k, v)]]
        par_groupe: dict = {}
        for k in deplaces:
            par_groupe.setdefault(self.groupe_de.get(k), []).append(k)
        for nom, ks in par_groupe.items():
            gr = self.groupes.get(nom)
            cibles = {voulu[(k, v)] for k in ks}
            libres = [m for m in (gr["kpis"] if gr else [])
                      if (m, v) not in self.cases]
            if (gr is not None and v not in gr["colonnes"] and len(cibles) == 1
                    and set(ks) == set(libres) and None not in cibles):
                self._poser_groupe(nom, v, cibles.pop(), auto=True)
            else:
                for k in ks:
                    if voulu[(k, v)] is not None:
                        self._poser_case(k, v, voulu[(k, v)], auto=True,
                                         implicite=voulu[(k, v)] == k)

    def _reparer(self, v, avant, voulu, suivre=True) -> list:
        notes: list = []
        if suivre:
            # 1. ceux qui copiaient une source qui a changé de source la
            #    suivent. La base qui copie ailleurs emmène ceux qui la
            #    suivaient : c'est ce que veut dire « base ».
            bouges: set = set()
            faits: set = set()
            anciennes = [s for s in dict.fromkeys(avant[(k, v)] for k in self.kpis)
                         if s is not None and any(avant[(x, v)] == s and x != s
                                                  for x in self.kpis)]
            for s in anciennes:
                nouvelle = voulu[(s, v)]
                if nouvelle in (s, None):
                    continue
                copieurs = [k for k in self.kpis if k != s
                            and avant[(k, v)] == s and self.source(k, v) == s]
                if not copieurs:
                    continue
                for k in copieurs:
                    niveau = self.niveau(k, v)
                    if niveau not in faits:
                        faits.add(niveau)
                        self._repointer(niveau, k, v, nouvelle)
                    bouges.add(k)
                notes.append(f"« {v} » : ce qui copiait « {s} » copie "
                             f"maintenant « {nouvelle} ».")
            self._epingler(v, voulu, bouges)
        # 2. plus de copie de copie. Si la source copie ailleurs PAR UNE
        #    RÈGLE DE L'USAGER, ceux qui la copiaient copient ce qu'elle
        #    copie (la règle tient) ; sinon, la source garde sa variation
        #    (elle la donne : elle en est la source).
        for _ in range(len(self.kpis) + 1):
            chaine = next(((k, s) for k in self.kpis
                           for s in [self.source(k, v)]
                           if s not in (None, k) and self.source(s, v) != s),
                          None)
            if chaine is None:
                break
            _k, s = chaine
            t = self.source(s, v)
            voulue = (self.cases.get((s, v)) not in (None, MANUEL)
                      and ("case", s, v) not in self._auto
                      and (s, v) not in self._implicites)
            if voulue and t is not None:
                etat = self._etat([v])
                copieurs = [x for x in self.kpis
                            if x != s and self.source(x, v) == s]
                faits: set = set()
                for x in copieurs:
                    niveau = self.niveau(x, v)
                    if niveau not in faits:
                        faits.add(niveau)
                        self._repointer(niveau, x, v, t)
                self._epingler(v, etat, set(copieurs))
                notes.append(f"« {v} » : ce qui copiait « {s} » copie "
                             f"maintenant « {t} », comme lui.")
            else:
                self._poser_case(s, v, MANUEL, implicite=True)
        # 3. ménage
        self._menage_colonne(v)
        self._menage_lignes()
        return notes

    def _menage_colonne(self, v):
        # une case « à la main » IMPLICITE — à la main parce que source — qui
        # n'a plus de copieur s'en va : retirer la dernière exception qui
        # copiait Weight rend Weight aux règles générales
        for k in self.kpis:
            if ((k, v) in self._implicites
                    and self.cases.get((k, v)) == MANUEL
                    and not self.donne(k, v)):
                del self.cases[(k, v)]
                self._implicites.discard((k, v))
        # une règle posée par une RÉPARATION qui ne change plus rien s'en va ;
        # celles de l'usager restent
        etat = {k: self.source(k, v) for k in self.kpis}

        def sans_effet():
            return all(self.source(k, v) == etat[k] for k in self.kpis)

        for k in self.kpis:
            cle = ("case", k, v)
            if cle in self._auto and (k, v) in self.cases:
                garde = self.cases.pop((k, v))
                if sans_effet():
                    self._auto.discard(cle)
                    self._implicites.discard((k, v))
                else:
                    self.cases[(k, v)] = garde
        for nom, gr in self.groupes.items():
            cle = ("groupe", nom, v)
            if cle in self._auto and v in gr["colonnes"]:
                garde = gr["colonnes"].pop(v)
                if sans_effet():
                    self._auto.discard(cle)
                else:
                    gr["colonnes"][v] = garde
        cle = ("tous", v)
        if cle in self._auto and v in self.colonnes:
            garde = self.colonnes.pop(v)
            if sans_effet():
                self._auto.discard(cle)
            else:
                self.colonnes[v] = garde

    def _menage_lignes(self):
        """Même règle pour une LIGNE implicite : sans plus aucun copieur,
        elle s'en va."""
        for k in list(self._lignes_implicites):
            if (self.lignes.get(k) == MANUEL and not self._donne_tout(k)
                    and not any(self.donne(k, v) for v in self.variations)):
                del self.lignes[k]
            if k not in self.lignes or self.lignes[k] != MANUEL:
                self._lignes_implicites.discard(k)

    def menage(self):
        """Retire ce qui n'a plus de raison d'être (après une lecture)."""
        for v in list(self.variations):
            self._menage_colonne(v)
        self._menage_lignes()

    def _donne_tout(self, kpi) -> bool:
        return any(x != kpi and self.lignes.get(x) == kpi for x in self.kpis)

    # ---- édition : la base, les groupes ---------------------------------------

    def _structure(self, changer) -> list:
        """Applique un changement de STRUCTURE (base, groupes) puis répare,
        sans faire suivre personne : une source reste une source (elle garde
        ce qu'elle donne), tout le reste suit les nouvelles règles."""
        avant = self._etat(self.variations)
        notes = changer() or []
        voulu = self._etat(self.variations)
        for v in self.variations:
            notes += self._reparer(v, avant, voulu, suivre=False)
        return notes

    def _quitter(self, kpi) -> list:
        """Sort un KPI de son groupe ; le gabarit qui part laisse son groupe
        sans gabarit (ses KPI suivent alors la base)."""
        nom = self.groupe_de.pop(kpi, None)
        if nom is None:
            return []
        gr = self.groupes[nom]
        gr["kpis"] = [k for k in gr["kpis"] if k != kpi]
        if gr["base"] == kpi:
            gr["base"] = None
            return [f"Le groupe « {nom} » n'a plus de gabarit : « {kpi} » "
                    "l'a quitté."]
        return []

    def changer_base(self, base) -> list:
        """Change le gabarit de base. Il ne peut pas être dans un groupe, et
        il est la référence : ses exceptions, là où d'autres le suivent,
        sont retirées (et dites)."""
        def changer():
            notes = []
            if base and base in self.groupe_de:
                nom = self.groupe_de[base]
                notes += self._quitter(base)
                notes.append(f"« {base} » devient le gabarit de base : il "
                             f"quitte le groupe « {nom} ».")
            self.base = base or None
            if self.base:
                if self.lignes.get(self.base) not in (None, MANUEL):
                    notes.append(f"« {self.base} » devient le gabarit de base : "
                                 f"il ne copie plus « {self.lignes.pop(self.base)} ».")
                retirees = [v for v in self.variations
                            if v not in self.colonnes
                            and self.cases.get((self.base, v)) not in (None, MANUEL)]
                for v in retirees:
                    self._poser_case(self.base, v, None)
                if retirees:
                    notes.append(f"« {self.base} » devient le gabarit de base : "
                                 "ses exceptions sur " + ", ".join(retirees)
                                 + " sont retirées.")
            return notes
        return self._structure(changer)

    def creer_groupe(self, nom, kpis, gabarit=None) -> list:
        """Un groupe neuf avec ces KPI ; son gabarit : `gabarit`, sinon le
        premier d'entre eux. Rend les phrases à montrer (ou une erreur)."""
        nom = (nom or "").strip()
        if not nom:
            return ["Donner un nom au groupe."]
        if nom in self.groupes:
            return [f"Un groupe s'appelle déjà « {nom} »."]
        self.groupes[nom] = {"kpis": [], "base": None, "colonnes": {},
                             "independant": False}
        notes = self.mettre_dans(nom, kpis)
        membres = self.groupes[nom]["kpis"]
        if membres:
            notes += self.changer_gabarit_groupe(
                nom, gabarit if gabarit in membres else membres[0])
        return notes

    def mettre_dans(self, nom, kpis) -> list:
        def changer():
            notes = []
            for k in kpis:
                if k not in self.kpis or self.groupe_de.get(k) == nom:
                    continue
                if k == self.base:
                    notes.append(f"« {k} » est le gabarit de base : il ne va "
                                 "pas dans un groupe.")
                    continue
                notes += self._quitter(k)
                self.groupe_de[k] = nom
                self.groupes[nom]["kpis"].append(k)
            self.groupes[nom]["kpis"].sort(key=self.kpis.index)
            return notes
        return self._structure(changer)

    def sortir_du_groupe(self, kpis) -> list:
        def changer():
            notes = []
            for k in kpis:
                notes += self._quitter(k)
            return notes
        return self._structure(changer)

    def changer_gabarit_groupe(self, nom, gabarit) -> list:
        """Le gabarit d'un groupe : un de ses membres, MANUEL (chacun à la
        main), ou None (ses KPI suivent la base)."""
        def changer():
            if gabarit not in (None, MANUEL) and gabarit not in self.groupes[nom]["kpis"]:
                return [f"« {gabarit} » n'est pas dans le groupe « {nom} »."]
            self.groupes[nom]["base"] = gabarit
            return []
        return self._structure(changer)

    def rendre_independant(self, nom, independant=True) -> list:
        """Un groupe INDÉPENDANT ne reçoit rien du maître : son gabarit est sa
        seule source, et « Tous les KPI » passe avant lui pour ses KPI. Sinon
        (le défaut) son gabarit se pose par-dessus la base."""
        def changer():
            self.groupes[nom]["independant"] = bool(independant)
            if independant:
                return [f"Groupe « {nom} » indépendant : son gabarit ne reçoit "
                        "plus rien de la base ni de « Tous les KPI »."]
            return [f"Groupe « {nom} » : son gabarit se pose par-dessus la "
                    "base, ce qu'il ne règle pas vient d'elle."]
        return self._structure(changer)

    def renommer_groupe(self, ancien, nouveau) -> list:
        nouveau = (nouveau or "").strip()
        if not nouveau or nouveau == ancien:
            return []
        if nouveau in self.groupes:
            return [f"Un groupe s'appelle déjà « {nouveau} »."]
        self.groupes = {(nouveau if n == ancien else n): gr
                        for n, gr in self.groupes.items()}
        for k, n in list(self.groupe_de.items()):
            if n == ancien:
                self.groupe_de[k] = nouveau
        self._auto = {(c[0], nouveau, *c[2:]) if c[0] == "groupe" and c[1] == ancien
                      else c for c in self._auto}
        return []

    def supprimer_groupe(self, nom) -> list:
        def changer():
            for k in list(self.groupes[nom]["kpis"]):
                self.groupe_de.pop(k, None)
            del self.groupes[nom]
            self._auto = {c for c in self._auto
                          if not (c[0] == "groupe" and c[1] == nom)}
            return [f"Groupe « {nom} » supprimé : ses KPI suivent les "
                    "règles générales."]
        return self._structure(changer)

    # ---- écriture --------------------------------------------------------------

    def vers_regles(self) -> dict:
        """Les règles, pour propagation.json : des rectangles (une source,
        des KPI, les mêmes variations) plutôt qu'une case par ligne."""
        out: dict = {"version": 2, "base": self.base}
        if self.colonnes:
            out["colonnes"] = {v: self.colonnes[v]
                               for v in self._variations_rangees(self.colonnes)}
        if self.groupes:
            out["groupes"] = []
            for nom, gr in self.groupes.items():
                x: dict = {"nom": nom, "kpis": list(gr["kpis"])}
                if gr["base"]:
                    x["base"] = gr["base"]
                if gr.get("independant"):
                    x["independant"] = True
                if gr["colonnes"]:
                    x["colonnes"] = {v: gr["colonnes"][v] for v in
                                     self._variations_rangees(gr["colonnes"])}
                out["groupes"].append(x)
        # Une case « à la main » IMPLICITE n'est pas écrite : la source d'une
        # exception y est comprise d'office à la lecture. Une « à la main »
        # voulue, elle, l'est — même si d'autres la copient.
        exceptions: list = []
        par_ligne: dict = {}
        for k in self.kpis:
            if k in self.lignes:
                s = self.lignes[k]
                if s == MANUEL and k in self._lignes_implicites:
                    continue
                par_ligne.setdefault(s, []).append(k)
        for s, ks in par_ligne.items():
            exceptions.append({"source": s, "kpis": ks})
        dons: dict = {}          # source -> {KPI: [variations]}
        for k in self.kpis:
            for v in self.variations:
                s = self.cases.get((k, v))
                if s is None or (s == MANUEL and (k, v) in self._implicites):
                    continue
                dons.setdefault(s, {}).setdefault(k, []).append(v)
        for s, par_kpi in dons.items():
            rectangles: dict = {}
            for k, vs in par_kpi.items():
                rectangles.setdefault(tuple(vs), []).append(k)
            for vs, ks in rectangles.items():
                exceptions.append({"source": s, "kpis": ks,
                                   "variations": list(vs)})
        if exceptions:
            out["exceptions"] = exceptions
        return out


# ---- la MÉMOIRE de ce qu'on a posé sous les gabarits de groupe -----------------
#
# Par rapport, dans le dossier des sauvegardes (hors de Desktop, hors du
# dépôt) : {"page/visuel": {gabarit: {clé d'objet: [{"selector",
# "proprietes"}]}}}. Perdue, rien ne casse : ce que le gabarit porte passe
# pour le sien tant que le maître n'y change rien.

MEMOIRE_DOSSIER = "_propagate_memoire"


def memoire_path(report_dir) -> Path:
    report_dir = Path(report_dir)
    nom = report_dir.name
    if nom.endswith(".Report"):
        nom = nom[:-len(".Report")]
    return br.backup_root(report_dir.parent, MEMOIRE_DOSSIER) / (nom + ".json")


def lire_memoire(chemin) -> dict:
    """La mémoire d'un rapport ; {} si absente ou illisible."""
    try:
        data = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    vis = data.get("visuels") if isinstance(data, dict) else None
    return vis if isinstance(vis, dict) else {}


def ecrire_memoire(chemin, memoire, rapport="") -> None:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({
        "version": 1,
        "rapport": rapport,
        "role": "ce que la propagation a posé sous les gabarits de groupe "
                "(depuis la base ou « Tous les KPI »), pour qu'un "
                "changement du maître y descende aussi",
        "visuels": memoire}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")


def _elaguer_memoire(memoire, report_dir) -> None:
    """Sans les visuels disparus ni les tiroirs vides."""
    report_dir = Path(report_dir)
    for vis in list(memoire):
        page, _, visuel = vis.partition("/")
        if (not isinstance(memoire[vis], dict) or not memoire[vis]
                or not (report_dir / "definition" / "pages" / page / "visuals"
                        / visuel / "visual.json").exists()):
            del memoire[vis]


def retraits_prevus(analyse, grille) -> list:
    """Ce que la prochaine propagation RETIRERA faute de source :
    [(KPI, variation, source, entrées)]. Une case qui copie un KPI qui n'a
    RIEN pour cette variation, dans un visuel que ce KPI pilote, perd son
    formatage — le miroir est voulu (retirer un réglage du gabarit le retire
    partout), mais sur une case qu'on croyait couverte, c'est une perte qu'on
    veut voir AVANT d'écrire."""
    reglages = (analyse or {}).get("reglages") or {}
    pilotes: dict = {}       # source -> visuels où elle porte ses propres cases
    for (k, v), par_visuel in reglages.items():
        if grille.source(k, v) == k:
            pilotes.setdefault(k, set()).update(
                vis for vis, n in par_visuel.items() if n)
    # un gabarit de groupe recevra d'abord ce que son maître porte : là où
    # le maître pilote, le gabarit pilotera aussi
    gabarits = grille.gabarits_par_dessus()
    for (u, v), par_visuel in reglages.items():
        for t in gabarits:
            if grille.sous_couche(t, v) == u:
                pilotes.setdefault(t, set()).update(
                    vis for vis, n in par_visuel.items() if n)

    def chez(s, v) -> dict:
        """Ce que la source portera pour v : le sien, et sa sous-couche."""
        out = dict(reglages.get((s, v)) or {})
        u = grille.sous_couche(s, v)
        for vis, n in ((reglages.get((u, v)) or {}).items() if u else ()):
            out[vis] = out.get(vis, 0) + n
        return out

    out = []
    for (k, v), par_visuel in reglages.items():
        s = grille.source(k, v)
        if s in (None, k):
            continue
        chez_la_source = chez(s, v)
        n = sum(nb for vis, nb in par_visuel.items()
                if vis in pilotes.get(s, ()) and not chez_la_source.get(vis))
        if n:
            out.append((k, v, s, n))
    return sorted(out, key=lambda r: (grille._rang(r[1]),
                                      grille.kpis.index(r[0])
                                      if r[0] in grille.kpis else 0))


def _executer_passes(report_dir, grille, *, branches, entity, field_parameter,
                     dry_run, verbose, log, cible_folders, classer, contexte,
                     titre, entete_passe, memoire=None) -> tuple:
    """Une passe par source de la grille, sous UNE session de sauvegarde.
    Rend (total, session, sources).

    D'abord les passes PAR-DESSOUS : chaque maître (la base, un gabarit par
    variation) passe sous les gabarits de groupe — c'est ce qu'ils donneront
    ensuite à leurs KPI. Un maître est toujours sa propre source : il est
    prêt avant toute passe, l'ordre de ces passes-là ne compte pas."""
    session = None
    if not dry_run:
        session = br.BackupSession(
            br.backup_root(report_dir.parent, "_propagate_backups"),
            titre, report_dir.parent)
        log(f"Sauvegardes  : {session.dir} (une seule pour toute l'action)")
    total = 0
    for u, gabarits in grille.couches().items():
        log("")
        log(f"--- « {u} » d'abord, sous le gabarit de groupe : "
            + ", ".join(gabarits) + " ---")
        total += propagate(report_dir, u, branches=branches,
                           targets=list(gabarits), entity=entity,
                           field_parameter=field_parameter, dry_run=dry_run,
                           verbose=verbose, log=log, backup_dir=session,
                           cible_folders=cible_folders,
                           cellules=_CouchesDe(grille, u, gabarits),
                           classer=classer, contexte=contexte, entete=[],
                           superposer=True, memoire=memoire)
    sources = grille.sources()
    for s in sources:
        log("")
        log(entete_passe(s))
        total += propagate(report_dir, s, branches=branches,
                           targets=list(grille.kpis), entity=entity,
                           field_parameter=field_parameter, dry_run=dry_run,
                           verbose=verbose, log=log, backup_dir=session,
                           cible_folders=cible_folders,
                           cellules=grille.cases_de(s), classer=classer,
                           contexte=contexte, entete=[])
    return total, session, sources


def propagate_regles(report_dir, regles=None, *, branches=BRANCHES,
                     toutes_branches=None, entity: str = ENTITY,
                     field_parameter: str = FIELD_PARAMETER, variations=None,
                     dry_run: bool = False, verbose: bool = False, log=print,
                     regles_json=None, cible_folders=()) -> int:
    """La propagation selon la GRILLE DES SOURCES (propagation.json).

    Une passe par source — la base, puis chaque KPI dont d'autres copient
    une variation —, chacune bornée à SES cases : une passe ne lit, n'écrit
    et ne retire rien hors d'elles, même dans un visuel partagé. UNE session
    de sauvegarde pour le tout : l'usager a fait une action, il la défait
    d'un coup.

    `regles` : déjà lues (cf. lire_regles) ; None = lues dans `regles_json`,
    sinon dans le propagation.json du dossier. `variations` : celles du
    config, [(id, suffixe)] (cf. variations_du_config) ; None = celles du
    measures_config.json voisin du rapport. `toutes_branches` : les branches
    du modèle, pour CLASSER les mesures ; `branches` ne dit que celles à
    synthétiser.

    Tout est validé AVANT la première écriture : des règles fautives ne
    produisent jamais un rapport à moitié propagé."""
    report_dir = Path(report_dir)
    chemin = Path(regles_json) if regles_json else groupes_a_lire(report_dir)
    if regles is None:
        regles = lire_regles(chemin)
    if not regles:
        raise SystemExit(
            "Aucune source de formatage : " + str(chemin) + " est absent ou "
            "vide.\nOuvrir la grille des sources (onglet Rapport) et choisir "
            "au moins le gabarit de base.")
    if variations is None:
        variations = variations_du_config(_config_voisin(report_dir))
    ctx = contexte_modele(report_dir, field_parameter, cible_folders)
    kpis = list(ctx["kpis_connus"])
    if regles.get("anciens_groupes"):
        # un ancien fichier garde ses verdicts : mêmes refus, mêmes mots
        resoudre_groupes(regles["anciens_groupes"], kpis, lambda *_: None)
    analyse = analyser(report_dir, entity=entity,
                       field_parameter=field_parameter,
                       branches=toutes_branches or branches,
                       variations=variations, cible_folders=cible_folders,
                       kpis=kpis, contexte=ctx)
    grille = Sources.depuis_regles(regles, kpis, analyse["variations"])
    erreurs, avertissements = grille.problemes()
    if erreurs:
        raise SystemExit("La grille des sources a un problème, rien n'a été "
                         "écrit :\n  · " + "\n  · ".join(erreurs))

    journal_contexte(ctx, cible_folders, log)
    for ligne in grille.resume():
        log(ligne)
    for a in avertissements:
        log("⚠ " + a)
    for k, v, s, n in retraits_prevus(analyse, grille):
        log(f"⚠ {k} · {v} : {n} réglage(s) retiré(s), sa source, {s}, "
            "n'en porte aucun.")
    if dry_run:
        log("*** DRY_RUN : aucun fichier modifié (diagnostic seulement) ***")

    chemin_memoire = memoire_path(report_dir)
    memoire = lire_memoire(chemin_memoire)
    memoire_avant = _canon(memoire)
    total, session, sources = _executer_passes(
        report_dir, grille, branches=list(branches), entity=entity,
        field_parameter=field_parameter, dry_run=dry_run, verbose=verbose,
        log=log, cible_folders=cible_folders, classer=analyse["classer"],
        contexte=ctx, titre="Propagation",
        entete_passe=lambda s: (f"--- source « {s} » "
                                + ("(base) ---" if s == grille.base else "---")),
        memoire=memoire)
    _elaguer_memoire(memoire, report_dir)
    if session is not None and _canon(memoire) != memoire_avant:
        # la mémoire suit le rapport : restaurer la sauvegarde la remet
        # aussi comme elle était (sinon on croirait avoir posé ce qui ne
        # l'est plus)
        if chemin_memoire.exists():
            session.save(chemin_memoire)
        else:
            session.mark_absent(chemin_memoire)
        ecrire_memoire(chemin_memoire, memoire, report_dir.name)
    if session is not None:
        session.close(f"{total} entrée(s), {len(sources)} source(s) : "
                      + ", ".join(sources))
    log("")
    log("Aucun changement." if total == 0 else
        f"Terminé : {total} entrée(s) au total, {len(sources)} source(s).")
    return total


def propagate_groupes(report_dir, groupes=None, *, branches=BRANCHES,
                      entity: str = ENTITY,
                      field_parameter: str = FIELD_PARAMETER,
                      dry_run: bool = False, verbose: bool = False,
                      log=print, groupes_json=None, cible_folders=()) -> int:
    """Une passe de propagation PAR GROUPE, chacune avec SON gabarit : l'ancien
    format de propagation.json, gardé pour les scripts et les fichiers d'avant.

    Les groupes sont devenus des LIGNES de la grille des sources (cf.
    regles_depuis_groupes) : même périmètre, même ordre de passes, même
    résultat au caractère. L'app passe désormais par propagate_regles.

    `groupes` = sortie brute de `read_groupes` ; None = lue dans le fichier du
    rapport. La validation a lieu ici, AVANT la première écriture : un fichier
    fautif ne produit jamais un rapport à moitié propagé."""
    report_dir = Path(report_dir)
    chemin = Path(groupes_json) if groupes_json else groupes_a_lire(report_dir)
    if groupes is None:
        groupes = read_groupes(chemin)
    ctx = contexte_modele(report_dir, field_parameter, cible_folders)
    resolus = resoudre_groupes(groupes, ctx["kpis_connus"], log)
    if not resolus:
        raise SystemExit(
            "Aucun groupe de propagation utilisable, vérifier " + str(chemin)
            + "\n(un groupe = un nom, un gabarit, et ses KPI ; une liste de "
              "KPI vide ramasse tous ceux qui restent).")

    log(f"Propagation par GROUPES : {len(resolus)} groupe(s)")
    for g in resolus:
        # « groupe : gabarit, KPI, KPI… » — le journal de l'app en fait un
        # tableau : le groupe en clé, un KPI par rangée, gabarit en tête
        autres = [k for k in g["kpis"] if k != g["gabarit"]]
        log(f"  {g['nom']} : " + ", ".join(
            [f"{g['gabarit']} (gabarit)"] + autres))
    journal_contexte(ctx, cible_folders, log)

    grille = Sources.depuis_regles(regles_depuis_groupes(groupes),
                                   ctx["kpis_connus"])
    classer = classeur(entity=entity, branches=branches,
                       fp_reverse=ctx["fp_reverse"],
                       variations=variations_du_config(
                           _config_voisin(report_dir)),
                       cibles=ctx["cibles"])
    noms = {g["gabarit"]: g["nom"] for g in resolus}
    total, session, _sources = _executer_passes(
        report_dir, grille, branches=list(branches), entity=entity,
        field_parameter=field_parameter, dry_run=dry_run, verbose=verbose,
        log=log, cible_folders=cible_folders, classer=classer, contexte=ctx,
        titre="Propagation par groupes",
        entete_passe=lambda s: f"--- groupe « {noms.get(s, s)} » ---")

    if session is not None:
        session.close("{0} entrée(s), {1} groupe(s) : {2}".format(
            total, len(resolus), ", ".join(g["gabarit"] for g in resolus)))

    log("")
    log("Aucun changement." if total == 0 else
        f"Terminé : {total} entrée(s) au total sur {len(resolus)} groupe(s).")
    return total


def main() -> None:
    propagate(REPORT_DIR, TEMPLATE_KPI, branches=BRANCHES, targets=TARGET_KPIS,
              entity=ENTITY, field_parameter=FIELD_PARAMETER,
              dry_run=DRY_RUN, verbose=VERBOSE)


if __name__ == "__main__":
    main()
