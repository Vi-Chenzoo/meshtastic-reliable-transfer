#!/usr/bin/env python3
# Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
"""Pertes en rafale (17 nov. 2026) : notre parité façon RAID 6 (0 à 2 par lot de 8) tient-elle quand les pertes
arrivent groupées, et que gagnerait-on avec un code de Cauchy (jusqu'à 4 parités, idée d'indian-aman, discussion
meshtastic/firmware #12338) ou avec un simple entrelacement des lots d'une fenêtre ?

Simulation en mémoire (simulation.py), un saut, LONG_FAST, canal libre (et avec le budget d'émission en fin de
fichier). Pertes : même taux MOYEN, mais en rafales de durée moyenne 0 (pertes indépendantes, modèle historique),
5, 15 ou 45 s (trame pleine LONG_FAST : 2 s ; une rafale de 15 s couvre donc 7 trames en moyenne). Mêmes tirages pour
toutes les variantes. Chiffres : part des contenus livrés, temps d'antenne, durée, morceaux de données renvoyés.
Usage : prototype/rafales.py [--vite] [--relances N]
(sortie : prototype/resultats-rafales-2026-11-17-<N>-relances.txt ; N par défaut = celui du protocole, 20 depuis le
17 nov. 2026 ; le fichier « 10-relances » a été produit avant le changement)
"""
import pathlib, random, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import simulation as s
from protocole import UTILE_COMPACT, Emetteur

TIRAGES = 10 if "--vite" in sys.argv else 40
RELANCES = int(sys.argv[sys.argv.index("--relances") + 1]) if "--relances" in sys.argv else None
TAILLES = (4, 10, 30)                   # Ko : 4 = cas publié le 10 nov. ; 10 = photo WebP 320 px ; 30 = 18 lots
PERTES = (0.10, 0.20, 0.30)
RAFALES = (0, 5, 15, 45)
VARIANTES = (
    ("messages avec accusé", None),
    ("RAID 6 (le nôtre)", dict(code="raid6")),
    ("RAID 6 entrelacé", dict(code="raid6", entrelacer=True)),
    ("Cauchy ≤ 4", dict(code="cauchy")),
    ("Cauchy ≤ 4 entrelacé", dict(code="cauchy", entrelacer=True)),
)


def mesurer(donnees, perte, rafale, options, budget=False):
    livres = antenne = duree = renvois = vue = 0
    for g in range(TIRAGES):
        if options is None:
            ok, a, d, _ = s.actuel(donnees, "LONG_FAST", perte, g, rafale)
            r, v = 0, s.actuel.perte_vue
        else:
            ok, a, d, _ = s.protocole(donnees, UTILE_COMPACT, "LONG_FAST", perte, g, budget=budget, rafale=rafale,
                                      relances_max=RELANCES, **options)
            r, v = s.protocole.renvois, s.protocole.perte_vue
        livres += ok
        antenne += a
        duree += d
        renvois += r
        vue += v
    n = TIRAGES
    return 100 * livres / n, antenne / n, duree / n, renvois / n, 100 * vue / n


def main():
    debut = time.time()
    relances = RELANCES or Emetteur(1, b"x").relances_max
    lignes = [f"Pertes en rafale, simulation.py, LONG_FAST, un saut, {TIRAGES} tirages par case, {relances} relances "
              f"({time.strftime('%d/%m/%Y %H:%M')})",
              "Format : livré % | antenne s | durée s | morceaux renvoyés | pertes vues %", ""]
    alea = random.Random(3)
    for ko in TAILLES:
        donnees = bytes(alea.randrange(256) for _ in range(ko * 1024))
        for perte in PERTES:
            for rafale in RAFALES:
                titre = f"{ko} Ko, pertes {perte:.0%}, " + ("indépendantes" if not rafale else f"rafales de {rafale} s")
                lignes.append(titre)
                for nom, options in VARIANTES:
                    l, a, d, r, v = mesurer(donnees, perte, rafale, options)
                    lignes.append(f"  {nom:22} livré {l:5.1f} % | antenne {a:6.0f} s | durée {d:6.0f} s | "
                                  f"renvoyés {r:5.1f} | pertes vues {v:4.1f} %")
                print("\n".join(lignes[-6:]), flush=True)
            lignes.append("")
    # Avec la discipline d'émission (5 % de l'heure par nœud) : les trames s'espacent, une rafale en touche moins
    lignes.append("Avec le budget d'émission (protocole.Budget), 10 Ko")
    donnees = bytes(random.Random(5).randrange(256) for _ in range(10 * 1024))
    for perte in (0.20, 0.30):
        for rafale in (0, 15, 45):
            for nom, options in VARIANTES[1:]:
                l, a, d, r, v = mesurer(donnees, perte, rafale, options, budget=True)
                lignes.append(f"  pertes {perte:.0%}, {'indépendantes' if not rafale else f'rafales {rafale} s':13} "
                              f"{nom:22} livré {l:5.1f} % | antenne {a:6.0f} s | durée {d:6.0f} s | renvoyés {r:5.1f} | "
                              f"pertes vues {v:4.1f} %")
                print(lignes[-1], flush=True)
    # Partie 2 : le cas le plus dur, rafales comptées en trames (la part de trames perdues est exactement `perte`,
    # l'émetteur ne peut pas « attendre la fin de la coupure ») ; et une parité FIXE plus forte dès le départ
    # (adaptative, 4 et 10 Ko ne dépassent jamais 2 parités : tous les lots partent avant le premier bilan).
    variantes2 = VARIANTES[1:] + (("RAID 6 fixe 2", dict(code="raid6", parites=2)),
                                  ("Cauchy fixe 3", dict(code="cauchy", parites=3)),
                                  ("Cauchy fixe 4", dict(code="cauchy", parites=4)))
    lignes += ["", "PARTIE 2 : rafales comptées en trames (part de trames perdues = pertes visées), parités fixes"]
    alea = random.Random(7)
    for ko in TAILLES:
        donnees = bytes(alea.randrange(256) for _ in range(ko * 1024))
        for perte in (0.20, 0.30):
            for rafale in (-1, -3, -6):
                lignes.append(f"{ko} Ko, pertes {perte:.0%}, " +
                              ("indépendantes" if rafale == -1 else f"rafales de {-rafale} trames en moyenne"))
                for nom, options in variantes2:
                    l, a, d, r, v = mesurer(donnees, perte, rafale, options)
                    lignes.append(f"  {nom:22} livré {l:5.1f} % | antenne {a:6.0f} s | durée {d:6.0f} s | "
                                  f"renvoyés {r:5.1f} | pertes vues {v:4.1f} %")
                print("\n".join(lignes[-1 - len(variantes2):]), flush=True)
        lignes.append("")
    lignes.append(f"\nCalcul : {time.time() - debut:.0f} s")
    sortie = pathlib.Path(__file__).parent / f"resultats-rafales-2026-11-17-{relances}-relances.txt"
    if "--vite" not in sys.argv:
        sortie.write_text("\n".join(lignes) + "\n")
        print("écrit :", sortie)


if __name__ == "__main__":
    main()
