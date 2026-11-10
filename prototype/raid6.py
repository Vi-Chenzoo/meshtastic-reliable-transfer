# Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
"""Parité façon RAID 6 pour un lot de morceaux (docs/07, P9) : deux morceaux de parité P et Q permettent de
reconstruire jusqu'à deux morceaux perdus, quels qu'ils soient.

Même calcul que le RAID 6 des NAS (Linux md, H. Peter Anvin, « The mathematics of RAID-6ʺ) : dans le corps de
Galois GF(2^8) de polynôme 0x11D, générateur g = 2,
    P = D0 ⊕ D1 ⊕ … ⊕ Dn-1            (le RAID 5)
    Q = g^0·D0 ⊕ g^1·D1 ⊕ … ⊕ g^(n-1)·Dn-1
octet par octet. Morceaux de longueurs inégales : complétés par des zéros (le dernier morceau d'un fichier est court).
"""

# Tables du corps GF(2^8), polynôme x^8 + x^4 + x^3 + x^2 + 1 (0x11D)
EXP = [0] * 512
LOG = [0] * 256
_x = 1
for _i in range(255):
    EXP[_i] = _x
    LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def mul(a, b):
    return 0 if a == 0 or b == 0 else EXP[LOG[a] + LOG[b]]


def div(a, b):
    if b == 0:
        raise ZeroDivisionError
    return 0 if a == 0 else EXP[(LOG[a] - LOG[b]) % 255]


def _completer(morceaux):
    n = max(len(m) for m in morceaux)
    return [m + bytes(n - len(m)) for m in morceaux], n


def parite(morceaux):
    """Morceaux de données d'un lot -> (P, Q)."""
    d, n = _completer(morceaux)
    p, q = bytearray(n), bytearray(n)
    for i, m in enumerate(d):
        g = EXP[i]
        for j, octet in enumerate(m):
            p[j] ^= octet
            q[j] ^= mul(g, octet)
    return bytes(p), bytes(q)


def reconstruire(recus, nb, p=None, q=None, longueurs=None):
    """recus : {indice: morceau} pour un lot de nb morceaux ; p, q : parités reçues (ou None).
    Rend la liste complète des nb morceaux, ou lève ValueError si c'est impossible.
    longueurs : {indice: longueur réelle}, pour retirer le remplissage des morceaux reconstruits."""
    manquants = [i for i in range(nb) if i not in recus]
    if not manquants:
        return [recus[i] for i in range(nb)]
    taille = max([len(m) for m in recus.values()] + [len(x) for x in (p, q) if x is not None])
    d = {i: recus[i] + bytes(taille - len(recus[i])) for i in recus}
    if len(manquants) == 1 and p is not None:                      # un seul trou : P suffit (RAID 5)
        x = bytearray(p + bytes(taille - len(p)))
        for m in d.values():
            for j, o in enumerate(m):
                x[j] ^= o
        d[manquants[0]] = bytes(x)
    elif len(manquants) == 1 and q is not None:                    # un seul trou, P perdue : Q suffit
        a = manquants[0]
        x = bytearray(q + bytes(taille - len(q)))
        for i, m in d.items():
            for j, o in enumerate(m):
                x[j] ^= mul(EXP[i], o)
        d[a] = bytes(div(v, EXP[a]) for v in x)
    elif len(manquants) == 2 and p is not None and q is not None:  # deux trous : P et Q (RAID 6)
        a, b = manquants
        pxy, qxy = bytearray(p + bytes(taille - len(p))), bytearray(q + bytes(taille - len(q)))
        for i, m in d.items():
            for j, o in enumerate(m):
                pxy[j] ^= o
                qxy[j] ^= mul(EXP[i], o)
        # Da·g^a ⊕ Db·g^b = qxy ; Da ⊕ Db = pxy  =>  Da = (qxy ⊕ g^b·pxy) / (g^a ⊕ g^b)
        den = EXP[a] ^ EXP[b]
        da = bytes(div(qxy[j] ^ mul(EXP[b], pxy[j]), den) for j in range(taille))
        d[a] = da
        d[b] = bytes(pxy[j] ^ da[j] for j in range(taille))
    else:
        raise ValueError(f"{len(manquants)} morceau(x) manquant(s), parité insuffisante")
    longueurs = longueurs or {}
    return [d[i][:longueurs.get(i, len(d[i]))] for i in range(nb)]
