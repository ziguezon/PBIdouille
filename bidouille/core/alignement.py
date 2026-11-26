# -*- coding: utf-8 -*-
"""Alignement « à quelques pixels près » des boîtes d'une page (wireframe).

Sans Qt : l'onglet Wireframe lui passe des boîtes absolues et applique ce
qui revient. Chaque axe est traité seul, en trois temps :

1. LES BORDS. Les bords gauches et droits (ou hauts et bas) de toutes les
   boîtes sont regroupés quand ils tiennent dans `tolerance` pixels. Chaque
   groupe devient UNE ligne, et tous ses bords s'y posent. Une ligne qui
   contient un bord FIXE (la page, le cadre d'un groupe, un élément hors de
   la cible) prend ce bord ; sinon elle prend la valeur la plus fréquente,
   arrondie au pixel. Deux bords à 3 pixels l'un de l'autre se collent, deux
   éléments presque alignés le deviennent.

2. LES GOUTTIÈRES. Entre deux voisins d'une même bande, l'écart restant est
   une gouttière ; entre le cadre et le premier ou le dernier élément d'une
   bande, c'est une marge. Les gouttières qui ne diffèrent que de quelques
   pixels prennent la même valeur, la plus fréquente, et les marges entre
   elles de même : les deux familles ne se mélangent pas. C'est une LIGNE
   qui bouge, donc tout ce qui était aligné dessus le reste.

3. LE PIXEL. Tout finit sur des entiers, sauf un bord posé sur un appui
   fixe qui n'en est pas un : être aligné passe avant être rond.

Un bord qui n'a rien sur quoi s'aligner suit l'autre bord de son élément :
un visuel qui ne touche quelque chose que d'un côté se déplace d'un bloc,
il ne s'étire pas.

Ce qui n'est PAS fait, exprès : rendre des tailles égales (le bouton
« Répartir » le fait, et égaliser des tailles déplace des bords que
d'autres rangées partagent) et aligner des centres.

Une boîte plus mince que la tolérance (un trait de séparation) ne donne que
son bord de départ : ses deux bords tomberaient sinon dans la même ligne et
le trait disparaîtrait. Elle garde sa taille arrondie, au moins 1 pixel."""

from __future__ import annotations

GOUTTIERE_MAX = 48.0     # au-delà, un écart est un vide voulu, pas une gouttière


def _grouper(valeurs, tol):
    """Groupes de valeurs triées dont l'ÉTENDUE ne dépasse pas `tol` (une
    chaîne 0, 4, 8, 12 ne fusionne pas de proche en proche)."""
    groupes, cur, debut = [], [], None
    for v in sorted(valeurs, key=lambda e: e[0]):
        if cur and v[0] - debut > tol:
            groupes.append(cur)
            cur = []
        if not cur:
            debut = v[0]
        cur.append(v)
    if cur:
        groupes.append(cur)
    return groupes


def _mode(valeurs):
    """La valeur entière la plus fréquente. À égalité, celle qu'un bord
    occupait DÉJÀ (un bord posé pile sur un pixel a été placé exprès, celui
    d'à côté a glissé), puis la plus proche de la médiane, puis la plus
    grande : 100.4 / 100.6 / 103 donne 101, 97 / 99.6 donne 97."""
    ronds = [round(v) for v in valeurs]
    compte: dict = {}
    for r in ronds:
        compte[r] = compte.get(r, 0) + 1
    meilleur = max(compte.values())
    cands = [r for r, n in compte.items() if n == meilleur]
    s = sorted(valeurs)
    med = (s[(len(s) - 1) // 2] + s[len(s) // 2]) / 2
    pile = {r for v, r in zip(valeurs, ronds) if abs(v - r) < 1e-6}
    return min(cands, key=lambda r: (r not in pile, abs(r - med), -r))


def _axe(boites, fixes, cadre, tol, gouttieres):
    """Un axe. `boites` : {id: (lo, hi, perp_lo, perp_hi)} mobiles ; `fixes` :
    [(lo, hi, perp_lo, perp_hi)] ; `cadre` : (lo, hi) ou None. Retourne
    ({id: (lo, hi)}, nombre de gouttières retouchées)."""
    # entrées : (valeur, ancre?, clé) ; clé = (id, 0|1) pour un bord mobile
    entrees = []
    minces = {}
    for i, (lo, hi, _a, _b) in boites.items():
        entrees.append((lo, False, (i, 0)))
        if hi - lo > tol:
            entrees.append((hi, False, (i, 1)))
        else:
            minces[i] = max(1, round(hi - lo))
    for k, (lo, hi, _a, _b) in enumerate(fixes):
        entrees.append((lo, True, ("fixe", k, 0)))
        entrees.append((hi, True, ("fixe", k, 1)))
    if cadre is not None:
        entrees.append((cadre[0], True, ("cadre", 0)))
        entrees.append((cadre[1], True, ("cadre", 1)))

    ligne_de: dict = {}       # clé -> indice de ligne
    rep: list = []            # valeur de chaque ligne
    fige: list = []           # ligne posée sur une ancre (ou déjà réglée)
    seule: list = []          # ligne d'un seul bord, sans appui
    for g in _grouper(entrees, tol):
        ancres = [v for v, a, _k in g if a]
        mobiles = [v for v, a, _k in g if not a]
        if ancres:
            cible = _mode(mobiles) if mobiles else ancres[0]
            val = min(ancres, key=lambda a: abs(a - cible))
        else:
            val = _mode(mobiles)
        for _v, _a, k in g:
            ligne_de[k] = len(rep)
        rep.append(val)
        fige.append(bool(ancres))
        seule.append(len(g) == 1)

    retouches = 0
    if gouttieres:
        avant = list(rep)
        retouches = _gouttieres(boites, fixes, cadre, tol, minces,
                                ligne_de, rep, fige)
        seule = [s and rep[i] == avant[i] for i, s in enumerate(seule)]

    out = {}
    for i, (lo, hi, _a, _b) in boites.items():
        a = rep[ligne_de[(i, 0)]]
        if i in minces:
            out[i] = (a, a + minces[i])
            continue
        b = rep[ligne_de[(i, 1)]]
        # un bord qui n'a rien sur quoi s'aligner suit l'autre : un élément
        # qui ne touche quelque chose que d'un côté se DÉPLACE, il ne
        # s'étire pas
        seul_a, seul_b = seule[ligne_de[(i, 0)]], seule[ligne_de[(i, 1)]]
        if seul_b and not seul_a:
            b = a + round(hi - lo)
        elif seul_a and not seul_b:
            a = b - round(hi - lo)
        if b - a < 1:
            # deux bords rapprochés au point de croiser : on n'y touche pas
            a, b = round(lo), max(round(lo) + 1, round(hi))
        out[i] = (a, b)
    return out, retouches


def _gouttieres(boites, fixes, cadre, tol, minces, ligne_de, rep, fige):
    """Égalise les gouttières proches en déplaçant des LIGNES (en place)."""
    elems = []     # (lo_ligne, hi_ligne, perp_lo, perp_hi, lo_brut)
    for i, (lo, _hi, a, b) in boites.items():
        if i not in minces:
            elems.append((ligne_de[(i, 0)], ligne_de[(i, 1)], a, b, lo))
    for k, (lo, _hi, a, b) in enumerate(fixes):
        elems.append((ligne_de[("fixe", k, 0)], ligne_de[("fixe", k, 1)], a, b, lo))

    def meme_bande(e, f):
        # chevauchement net : deux rangées qui se touchent ne sont pas une bande
        return min(e[3], f[3]) - max(e[2], f[2]) > tol

    paires = set()
    for e in elems:
        voisins = [f for f in elems if f is not e and meme_bande(e, f)
                   and rep[f[0]] >= rep[e[1]]]
        if voisins:
            f = min(voisins, key=lambda f: rep[f[0]])
            paires.add((e[1], f[0], "g"))
        if cadre is not None:
            # marge : rien ne commence avant lui dans sa bande
            if not any(f is not e and meme_bande(e, f) and f[4] < e[4]
                       for f in elems):
                paires.add((ligne_de[("cadre", 0)], e[0], "m"))
            if not voisins and not any(
                    f is not e and meme_bande(e, f) and rep[f[1]] > rep[e[1]]
                    for f in elems):
                paires.add((e[1], ligne_de[("cadre", 1)], "m"))
    paires = [p for p in paires if 0 < rep[p[1]] - rep[p[0]] <= GOUTTIERE_MAX]

    # les marges (jusqu'au cadre) et les gouttières (entre voisins) sont deux
    # familles : une marge de 9 n'a pas à prendre la gouttière de 12
    cible_de = {}
    for famille in ("g", "m"):
        ecarts = [(rep[b] - rep[a], False, (a, b, f))
                  for a, b, f in paires if f == famille]
        for g in _grouper(ecarts, tol):
            if len(g) >= 2:
                c = _mode([v for v, _x, _k in g])
                for _v, _x, k in g:
                    cible_de[k] = c

    retouches = 0
    for a, b, f in sorted(cible_de, key=lambda p: (rep[p[0]], rep[p[1]], p[2])):
        ecart = rep[b] - rep[a]
        s = cible_de[(a, b, f)] - ecart
        if s == 0:
            fige[a] = fige[b] = True
            continue
        if ecart <= 0 or abs(s) > tol:
            continue
        if not fige[b]:
            rep[b] += s
        elif not fige[a]:
            rep[a] -= s
        else:
            continue
        fige[a] = fige[b] = True
        retouches += 1
    return retouches


def aligner(boites, fixes=(), cadre=None, tolerance=5.0, gouttieres=True):
    """Aligne des boîtes absolues.

    boites : {id: (x0, y0, x1, y1)}, ce qui peut bouger ;
    fixes  : [(x0, y0, x1, y1)], des boîtes dont les bords servent d'appui
             sans bouger (les éléments visibles hors de la cible) ;
    cadre  : (x0, y0, x1, y1) ou None, la page ou le groupe : ses bords sont
             des appuis, et l'écart jusqu'à eux une marge.

    Retourne (nouvelles boîtes en entiers, nombre de gouttières retouchées).
    """
    tol = float(tolerance)
    bx = {i: (b[0], b[2], b[1], b[3]) for i, b in boites.items()}
    by = {i: (b[1], b[3], b[0], b[2]) for i, b in boites.items()}
    fx = [(f[0], f[2], f[1], f[3]) for f in fixes]
    fy = [(f[1], f[3], f[0], f[2]) for f in fixes]
    cx = (cadre[0], cadre[2]) if cadre else None
    cy = (cadre[1], cadre[3]) if cadre else None
    xs, nx = _axe(bx, fx, cx, tol, gouttieres)
    ys, ny = _axe(by, fy, cy, tol, gouttieres)
    out = {i: (xs[i][0], ys[i][0], xs[i][1], ys[i][1]) for i in boites}
    return out, nx + ny
