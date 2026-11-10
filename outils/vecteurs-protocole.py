#!/usr/bin/env python3
# Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
"""Vecteurs de comparaison du protocole : prototype Python contre portage C++ du firmware (9 nov. 2026).

Rejoue des scénarios fixés (données, pertes tirées par un générateur simple, coupure et reprise, reprise par un
autre récepteur, parité fixe, destinataire final) avec prototype/protocole.py, note chaque trame (instant, sens,
longueur, CRC32, perdue ou non) et écrit un en-tête C++ que le test du firmware rejoue à l'identique
(firmware-projet/test/test_station_protocole/). Même chose pour le budget d'émission (suite d'appels, résultats
exacts en flottants hexadécimaux) et pour la parité RAID 6.

Usage : python3 outils/vecteurs-protocole.py [sortie.h]
(défaut : cpp/test/vecteurs.h)
"""
import pathlib, sys, zlib

ICI = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ICI / "prototype"))
import protocole as P  # noqa: E402
import raid6  # noqa: E402

PAS, LATENCE = 0.5, 1.0                    # pas de l'horloge et délai de livraison d'une trame (s)


class Hasard:
    """Générateur congruentiel, le même en C++ (test_main.cpp)."""
    def __init__(self, graine):
        self.x = graine & 0x7FFFFFFF

    def suivant(self):
        self.x = (self.x * 1103515245 + 12345) & 0x7FFFFFFF
        return self.x


def donnees(taille, graine):
    h = Hasard(graine)
    return bytes((h.suivant() >> 16) & 0xFF for _ in range(taille))


# nom, taille, graine des données, utile, pertes ‰ (émetteur → récepteur), pertes ‰ (retour), graine des pertes,
# durée max (s), parité (-1 auto), délai de relance (0 mesuré), destinataire final (None), coupure (0 : aucune),
# reprise par un autre récepteur
SCENARIOS = [
    ("sans_perte_4k", 4096, 1, 215, 0, 0, 7, 600, -1, 0, None, 0, False),
    ("pertes_10_4k", 4096, 2, 215, 100, 100, 11, 1200, -1, 0, None, 0, False),
    ("pertes_20_20k", 20480, 3, 215, 200, 200, 13, 3600, -1, 0, None, 0, False),
    ("pertes_30_8k", 8192, 4, 215, 300, 300, 17, 3600, -1, 0, None, 0, False),
    ("vide", 0, 5, 215, 0, 0, 19, 300, -1, 0, None, 0, False),
    ("un_octet_pertes", 1, 6, 215, 400, 400, 23, 1800, -1, 0, None, 0, False),
    ("petits_morceaux_parite_2", 3000, 7, 50, 150, 100, 29, 3600, 2, 0, None, 0, False),
    ("parite_0_delai_30", 5000, 8, 215, 100, 50, 31, 3600, 0, 30.0, None, 0, False),
    ("final", 2048, 9, 215, 50, 50, 37, 1200, -1, 0, 0xDEADBEEF, 0, False),
    ("coupure_reprise", 30000, 10, 215, 100, 100, 41, 3600, -1, 0, None, 5.0, False),
    ("coupure_autre_recepteur", 30000, 11, 215, 100, 100, 43, 3600, -1, 0, None, 5.0, True),
    ("gros_60k", 61440, 12, 215, 150, 150, 47, 7200, -1, 0, None, 0, False),
    ("tres_pertes_echec", 4096, 13, 215, 950, 950, 53, 3600, -1, 0, None, 0, False),
    # parité adaptative sur un long transfert (10 nov. 2026, trou vu en préparant le dépôt public : aucun scénario ne
    # faisait passer la parité à 0, ni n'avait des pertes entre 2 et 7 % ou autour de 7 %)
    ("adaptatif_sans_perte_60k", 61440, 14, 215, 0, 0, 59, 7200, -1, 0, None, 0, False),
    ("adaptatif_pertes_4_60k", 61440, 15, 215, 40, 40, 61, 7200, -1, 0, None, 0, False),
    ("adaptatif_pertes_7_60k", 61440, 16, 215, 72, 72, 67, 7200, -1, 0, None, 0, False),
    ("adaptatif_pertes_2_60k", 61440, 17, 215, 20, 20, 71, 7200, -1, 0, None, 0, False),
    ("adaptatif_pertes_6_60k", 61440, 18, 215, 65, 65, 71, 7200, -1, 0, None, 0, False),   # passe le seuil de 7 %
    # petits contenus en morceaux égaux (10 nov. 2026, protocole.utile_pour) : 2 morceaux pile, 450 (3 × 150), 533
    # (178, 178, 177), 1 720 (8 × 215, la limite), 1 600 (8 × 200), 1 721 (9 morceaux : 215 et un dernier de 1), avec pertes ; reprise
    # d'un petit contenu après coupure
    ("egal_430", 430, 19, 215, 100, 100, 73, 1800, -1, 0, None, 0, False),
    ("egal_450", 450, 20, 215, 150, 150, 79, 1800, -1, 0, None, 0, False),
    ("egal_533", 533, 21, 215, 100, 100, 83, 1800, -1, 0, None, 0, False),
    ("egal_1720", 1720, 22, 215, 150, 150, 89, 3600, -1, 0, None, 0, False),
    ("egal_1600", 1600, 25, 215, 100, 100, 103, 3600, -1, 0, None, 0, False),    # 8 morceaux de 200
    ("egal_1721", 1721, 23, 215, 150, 150, 97, 3600, -1, 0, None, 0, False),
    ("egal_1200_coupure", 1200, 24, 215, 100, 100, 101, 3600, -1, 0, None, 3.0, True),
]


def simuler(sc):
    nom, taille, gd, utile, pe, pr, gp, tmax, par, delai, final, coupure, autre = sc
    d = donnees(taille, gd)
    hasard = Hasard(gp)
    r1 = P.Recepteur()
    r2 = P.Recepteur() if autre else r1

    def emetteur(ident):
        return P.Emetteur(ident, d, utile=utile, parites="auto" if par < 0 else par,
                          delai_relance=delai or None, final=final)

    em, rec, phase, file, journal, seq = emetteur(1), r1, 1, [], [], [0]

    def envoyer(sens, trames, t):
        for f in trames:
            seq[0] += 1
            perdu = hasard.suivant() % 1000 < (pe if sens == "E" else pr)
            journal.append((t, sens, len(f), zlib.crc32(f), perdu))
            if not perdu:
                file.append((t + LATENCE, seq[0], sens, f))

    envoyer("E", em.demarrer(0.0), 0.0)
    k = 0
    while k * PAS <= tmax:
        t = k * PAS
        if coupure and phase == 1 and t >= coupure:
            phase, rec = 2, r2
            file.clear()
            em = emetteur(2)
            envoyer("E", em.demarrer(t), t)
        dus = sorted((x for x in file if x[0] <= t), key=lambda x: (x[0], x[1]))
        file[:] = [x for x in file if x[0] > t]
        for _, _, sens, f in dus:
            if sens == "E":
                if phase == 2 and autre and f[0] == P.ENTETE:
                    rec.adopter([r1], f)
                envoyer("R", rec.recevoir(f, t), t)
            else:
                envoyer("E", em.recevoir(f, t), t)
        envoyer("E", em.horloge(t), t)
        envoyer("R", rec.horloge(t), t)
        if (em.fini or em.echec) and not (coupure and phase == 1):
            break
        k += 1
    livre = rec.livres.get(em.id)
    return {"fini": em.fini, "echec": em.echec, "t_fin": k * PAS, "livre": livre is not None,
            "crc_livre": zlib.crc32(livre) if livre is not None else 0, "juste": livre == d if livre is not None else False,
            "journal": journal, "parites": em.parites_envoyees, "lot_depart": em.lot_de_depart}


def budget():
    """Suite d'appels au budget : (opération, a, b, c, résultat)."""
    b, h, sortie = P.Budget(), Hasard(97), []
    t = 0.0
    for _ in range(400):
        x = h.suivant()
        t += (x % 5000) / 100.0
        op = x % 7
        if op == 0:
            canal, emission = (h.suivant() % 600) / 10.0, (h.suivant() % 100) / 10.0
            b.signaler(t, canal, emission)
            sortie.append((2, t, canal, emission, 0.0))
        else:
            duree = 0.05 + (h.suivant() % 2500) / 1000.0
            urgent = op == 1
            q = b.quand(t, duree, urgent)
            sortie.append((1 if urgent else 0, t, duree, 0.0, q))
            b.noter(q, duree)
            sortie.append((3, q, duree, 0.0, b.depense(q + 1.0)))
    sortie.append((4, 0.0, 0.0, 0.0, b.attentes))
    return sortie


def raid():
    """Lots tirés au hasard : (nb morceaux, longueurs, CRC de P, CRC de Q, graine)."""
    sortie = []
    for g in range(1, 21):
        h = Hasard(1000 + g)
        nb = 2 + h.suivant() % 7
        lot = [donnees(1 + h.suivant() % 215, 5000 + g * 10 + i) for i in range(nb)]
        p, q = raid6.parite(lot)
        sortie.append((nb, [len(m) for m in lot], zlib.crc32(p), zlib.crc32(q), g))
    return sortie


def main():
    sortie = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ICI / "cpp/test/vecteurs.h"
    L = ["// Généré par outils/vecteurs-protocole.py du projet (prototype/protocole.py) : ne pas modifier à la main.",
         "#pragma once", "#include <cstddef>", "#include <cstdint>", "", "namespace vecteurs", "{",
         "struct Ligne {", "    double t;", "    char sens;", "    uint16_t longueur;", "    uint32_t crc;",
         "    bool perdu;", "};", "struct Scenario {", "    const char *nom;", "    uint32_t taille, graineDonnees;",
         "    uint16_t utile, pertesAller, pertesRetour;", "    uint32_t grainePertes;", "    double tmax;",
         "    int parite;", "    double delai;", "    bool avecFinal;", "    uint32_t final;", "    double coupure;",
         "    bool autreRecepteur;", "    bool fini, echec, livre;", "    double tFin;", "    uint32_t crcLivre;",
         "    unsigned lotDepart;", "    const Ligne *journal;", "    size_t nJournal;", "    const int *parites;",
         "    size_t nParites;", "};", ""]
    entrees = []
    for sc in SCENARIOS:
        r = simuler(sc)
        assert r["juste"] or not r["livre"], sc[0]
        nom = sc[0]
        L.append(f"static const Ligne journal_{nom}[] = {{")
        for t, s, n, c, p in r["journal"]:
            L.append(f"    {{{t.hex()}, '{s}', {n}, 0x{c:08X}u, {'true' if p else 'false'}}},")
        L.append("};")
        par = r["parites"] or [0]
        L.append(f"static const int parites_{nom}[] = {{{', '.join(map(str, par))}}};")
        _, taille, gd, utile, pe, pr, gp, tmax, pa, delai, final, coupure, autre = sc
        entrees.append(
            f"    {{\"{nom}\", {taille}, {gd}, {utile}, {pe}, {pr}, {gp}, {float(tmax).hex()}, {pa}, "
            f"{float(delai).hex()}, {'true' if final is not None else 'false'}, 0x{(final or 0):08X}u, "
            f"{float(coupure).hex()}, {'true' if autre else 'false'}, {str(r['fini']).lower()}, "
            f"{str(r['echec']).lower()}, {str(r['livre']).lower()}, {r['t_fin'].hex()}, 0x{r['crc_livre']:08X}u, "
            f"{r['lot_depart']}, journal_{nom}, {len(r['journal'])}, parites_{nom}, {len(r['parites'])}}},")
        print(f"{nom:28} fini={r['fini']!s:5} échec={r['echec']!s:5} t={r['t_fin']:7.1f} s "
              f"trames={len(r['journal'])} parité={sorted(set(r['parites']))} départ={r['lot_depart']}")
    L += ["static const Scenario scenarios[] = {"] + entrees + ["};", ""]
    L += ["struct AppelBudget {", "    int op; // 0 quand, 1 quand urgent, 2 signaler, 3 dépense, 4 attentes",
          "    double a, b, c, resultat;", "};", "static const AppelBudget budget[] = {"]
    for op, a, b, c, res in budget():
        L.append(f"    {{{op}, {float(a).hex()}, {float(b).hex()}, {float(c).hex()}, {float(res).hex()}}},")
    L += ["};", "", "struct LotRaid {", "    unsigned nb;", "    unsigned longueurs[8];", "    uint32_t crcP, crcQ;",
          "    unsigned graine;", "};", "static const LotRaid lots[] = {"]
    for nb, lg, cp, cq, g in raid():
        L.append(f"    {{{nb}, {{{', '.join(map(str, lg + [0] * (8 - len(lg))))}}}, 0x{cp:08X}u, 0x{cq:08X}u, {g}}},")
    L += ["};", "} // namespace vecteurs", ""]
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text("\n".join(L))
    print(f"écrit : {sortie} ({len(L)} lignes)")


if __name__ == "__main__":
    main()
