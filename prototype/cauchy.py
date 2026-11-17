# Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
"""Parité par code de Cauchy (Reed-Solomon systématique) pour un lot de morceaux : jusqu'à PARITE_MAX morceaux de
parité, et N'IMPORTE QUELS k morceaux parmi les k données + m parités reconstruisent le lot (code MDS).

Essai du 17 nov. 2026 (discussion meshtastic/firmware #12338, idée d'indian-aman) : comparer au RAID 6 (raid6.py,
2 parités au plus) quand les pertes arrivent en rafales. Option du prototype seulement : rien dans le firmware.

Même corps que raid6.py : GF(2^8), polynôme 0x11D. Matrice de Cauchy C[j][i] = 1 / (x_j ⊕ y_i) avec x_j = j
(j < PARITE_MAX) et y_i = PARITE_MAX + i (i < LOT_MAX) : tous distincts, donc toute sous-matrice carrée est
inversible. La ligne j ne dépend pas du nombre de parités choisi : la parité j est la même que le lot en reçoive 1 ou 4
(la parité est adaptative d'une fenêtre à l'autre).
"""
from raid6 import EXP, LOG, div, mul

PARITE_MAX = 4
LOT_MAX = 8


def coef(j, i):
    return div(1, j ^ (PARITE_MAX + i))


def _completer(morceaux, taille):
    return [m + bytes(taille - len(m)) for m in morceaux]


def parites(morceaux, m):
    """Morceaux de données d'un lot (au plus LOT_MAX) -> liste de m morceaux de parité (m <= PARITE_MAX)."""
    if m > PARITE_MAX or len(morceaux) > LOT_MAX:
        raise ValueError("trop de parités ou de morceaux")
    taille = max(len(x) for x in morceaux)
    d = _completer(morceaux, taille)
    sortie = []
    for j in range(m):
        p = bytearray(taille)
        for i, x in enumerate(d):
            c = coef(j, i)
            lc = LOG[c]
            for o, octet in enumerate(x):
                if octet:
                    p[o] ^= EXP[lc + LOG[octet]]
        sortie.append(bytes(p))
    return sortie


def _inverser(a):
    """Inverse d'une matrice carrée sur GF(2^8) (Gauss-Jordan). ValueError si elle n'est pas inversible."""
    n = len(a)
    m = [list(ligne) + [1 if c == r else 0 for c in range(n)] for r, ligne in enumerate(a)]
    for col in range(n):
        pivot = next((r for r in range(col, n) if m[r][col]), None)
        if pivot is None:
            raise ValueError("matrice non inversible")
        m[col], m[pivot] = m[pivot], m[col]
        inv = div(1, m[col][col])
        m[col] = [mul(inv, v) for v in m[col]]
        for r in range(n):
            if r != col and m[r][col]:
                f = m[r][col]
                m[r] = [v ^ mul(f, w) for v, w in zip(m[r], m[col])]
    return [ligne[n:] for ligne in m]


def reconstruire(recus, nb, pars, longueurs=None):
    """recus : {indice: morceau} pour un lot de nb morceaux ; pars : {j: morceau de parité j reçu}.
    Rend la liste complète des nb morceaux, ou lève ValueError s'il manque plus de morceaux que de parités reçues.
    longueurs : {indice: longueur réelle}, pour retirer le remplissage des morceaux reconstruits."""
    manquants = [i for i in range(nb) if i not in recus]
    if not manquants:
        return [recus[i] for i in range(nb)]
    if len(pars) < len(manquants):
        raise ValueError(f"{len(manquants)} morceau(x) manquant(s), {len(pars)} parité(s)")
    lignes = sorted(pars)[:len(manquants)]
    taille = max([len(x) for x in recus.values()] + [len(x) for x in pars.values()])
    d = {i: recus[i] + bytes(taille - len(recus[i])) for i in recus}
    # syndromes : s_j = P_j ⊕ Σ(reçus) C[j][i]·D_i = Σ(manquants) C[j][i]·D_i
    s = []
    for j in lignes:
        x = bytearray(pars[j] + bytes(taille - len(pars[j])))
        for i, morceau in d.items():
            lc = LOG[coef(j, i)]
            for o, octet in enumerate(morceau):
                if octet:
                    x[o] ^= EXP[lc + LOG[octet]]
        s.append(x)
    inv = _inverser([[coef(j, i) for i in manquants] for j in lignes])
    for c, i in enumerate(manquants):
        x = bytearray(taille)
        for r, sr in enumerate(s):
            f = inv[c][r]
            if f:
                lf = LOG[f]
                for o, octet in enumerate(sr):
                    if octet:
                        x[o] ^= EXP[lf + LOG[octet]]
        d[i] = bytes(x)
    longueurs = longueurs or {}
    return [d[i][:longueurs.get(i, len(d[i]))] for i in range(nb)]
