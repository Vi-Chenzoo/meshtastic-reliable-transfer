#!/usr/bin/env python3
"""Collisions et balayages CAD (firmware d'essai v8/v8b) : où tombe la fin du dernier balayage de chaque boîtier par rapport au départ de l'AUTRE ?

Copyright (C) 2026 SoCodeIA et Vincent PERRIN — GPL v3.

    python3 outils/analyse-collisions-balayage.py [--suffixe board] essais/2026-11-18-lot-v5/c1 essais/2026-11-18-lot-v5/c2 …   (préfixes : <préfixe>-boitier1.json / -boitier2.json ; `--suffixe board` pour -board1.json / -board2.json)

Une collision = deux émissions qui se recouvrent de plus de 5 ms dont les DEUX trames sont absentes chez l'autre. Pour chacune, on cherche le dernier balayage
(événement CAD) que chaque boîtier a terminé avant de partir, et on mesure : (1) le délai entre la FIN de ce balayage et son propre début d'émission ;
(2) la place de la fin du balayage par rapport au début d'émission de l'AUTRE boîtier (négatif = le balayage a fini avant que l'autre parte).
Deux horloges calées comme dans analyse-journal-radio.py (résidu < 0,1 ms)."""
import importlib.util, os, statistics, sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
_s = importlib.util.spec_from_file_location("ab", os.path.join(ICI, "analyse-balayage-recepteur.py"))
ab = importlib.util.module_from_spec(_s)
_s.loader.exec_module(ab)
an = ab.an


def collisions(prefixe, suffixe="boitier"):
    f1, f2 = f"{prefixe}-{suffixe}1.json", f"{prefixe}-{suffixe}2.json"
    a, b = an.charger(f1), an.charger(f2)
    cal = an.caler(a, b)
    bal_a = ab.balayages(f1)
    bal_b = [dict(s, debut_us=an.vers_a(cal, s["debut_us"]), fin_us=an.vers_a(cal, s["fin_us"])) for s in ab.balayages(f2)]
    tx_a = [(t["debut"], t["fin"], t["id"]) for t in a["tx_liste"]]
    tx_b = [(an.vers_a(cal, t["debut"]), an.vers_a(cal, t["fin"]), t["id"]) for t in b["tx_liste"]]
    rec_a = {r["id"] for r in a["rx"] if r["etat"] == 0}
    rec_b = {r["id"] for r in b["rx"] if r["etat"] == 0}
    lignes = []
    for sa, fa, ia in tx_a:
        for sb, fb, ib in tx_b:
            if min(fa, fb) - max(sa, sb) > an.MARGE_RECOUVREMENT_US and ia not in rec_b and ib not in rec_a:
                def dernier(bal, debut):
                    l = [s for s in bal if s["fin_us"] <= debut + 500]
                    return l[-1] if l else None
                s_a, s_b = dernier(bal_a, sa), dernier(bal_b, sb)
                if s_a and s_b:
                    lignes.append({"essai": os.path.basename(prefixe), "ecart_departs_ms": (sb - sa) / 1000,
                                   "A": {"fin_scan_vers_depart_ms": (sa - s_a["fin_us"]) / 1000, "fin_scan_vs_depart_autre_ms": (s_a["fin_us"] - sb) / 1000},
                                   "B": {"fin_scan_vers_depart_ms": (sb - s_b["fin_us"]) / 1000, "fin_scan_vs_depart_autre_ms": (s_b["fin_us"] - sa) / 1000}})
    return lignes


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    args = sys.argv[1:]
    suffixe = "boitier"
    if args[:1] == ["--suffixe"]:                                 # « board » pour les journaux anonymisés du dossier public
        suffixe, args = args[1], args[2:]
    tout = []
    for p in args:
        tout += collisions(p, suffixe)
    print("essai  écart des départs (B−A) | boîtier A : délai fin-balayage→départ ; fin du balayage par rapport au départ de B | boîtier B : idem")
    for x in tout:
        print(f"{x['essai']:5s}  {x['ecart_departs_ms']:+6.1f} ms | {x['A']['fin_scan_vers_depart_ms']:5.2f} ; {x['A']['fin_scan_vs_depart_autre_ms']:+6.1f} | "
              f"{x['B']['fin_scan_vers_depart_ms']:5.2f} ; {x['B']['fin_scan_vs_depart_autre_ms']:+6.1f}")
    if tout:
        delais = [x[k]["fin_scan_vers_depart_ms"] for x in tout for k in "AB"]
        places = [x[k]["fin_scan_vs_depart_autre_ms"] for x in tout for k in "AB"]
        print(f"\n{len(tout)} collisions. Délai fin du dernier balayage → début d'émission : min {min(delais):.2f}, médiane {statistics.median(delais):.2f}, max {max(delais):.2f} ms "
              f"({2 * len(tout)} mesures).")
        print(f"Fin du balayage par rapport au départ de l'autre boîtier : de {min(places):+.1f} à {max(places):+.1f} ms "
              "(positif = le balayage a fini APRÈS le départ de l'autre sans le voir).")
        print(f"Écarts de départ : de {min(x['ecart_departs_ms'] for x in tout):+.1f} à {max(x['ecart_departs_ms'] for x in tout):+.1f} ms.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
