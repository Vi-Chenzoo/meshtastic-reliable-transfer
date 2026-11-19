#!/usr/bin/env python3
"""Conflits d'accès au canal entre deux boîtiers (18 nov. 2026) : à partir de DEUX journaux radio (outils/journal-radio.py lire), repère chaque « conflit »
= une fin de trame après laquelle LES DEUX boîtiers repartent dans la seconde (ils attendaient tous deux la fin de cette trame, puis tirent un délai
aléatoire), mesure l'écart de leurs départs à la µs, dit s'il y a eu CHEVAUCHEMENT (collision : les deux trames perdues) et trace le taux de collision
par tranche d'écart. Même calage d'horloges que analyse-journal-radio.py.

    python3 outils/analyse-conflits.py boitier1.json boitier2.json [--json sortie.json] [--fenetre 1.0]

Limites : un conflit n'existe que si les deux boîtiers ont une trame en attente (mitraillage symétrique, mode rafale) ; deux boîtiers collés, pas de nœud caché.
Copyright (C) 2026 SoCodeIA et Vincent PERRIN — GPL v3."""
import argparse, importlib.util, json, os, sys

ICI = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("analyse", os.path.join(ICI, "analyse-journal-radio.py"))
an = importlib.util.module_from_spec(_s)
_s.loader.exec_module(an)

TRANCHES_MS = (2, 5, 10, 20, 50, 100, 300, 1000)


def conflits(ja, jb, fenetre_s=1.0):
    a, b = an.charger(ja), an.charger(jb)
    cal = an.caler(a, b)
    if cal is None:
        return {"erreur": "horloges non calées (moins de 3 paquets communs)"}
    A = [(an.vers_b(cal, t["debut"]), an.vers_b(cal, t["fin"]), t["id"], t["octets"]) for t in a["tx_liste"]]   # tout dans l'horloge de B
    B = [(t["debut"], t["fin"], t["id"], t["octets"]) for t in b["tx_liste"]]
    fen = fenetre_s * 1e6
    evts, vus = [], set()
    for X, Y, nom in ((A, B, "A"), (B, A, "B")):
        for d, f, i, o in X:
            nx = [t for t in X if t[0] > f and t[0] - f < fen]
            ny = [t for t in Y if t[0] > f and t[0] - f < fen]
            if not nx or not ny:
                continue
            tx, ty = min(nx, key=lambda t: t[0]), min(ny, key=lambda t: t[0])
            cle = (round(tx[0]), round(ty[0]))
            if cle in vus:
                continue
            vus.add(cle)
            ecart = abs(tx[0] - ty[0])
            recouvrement = min(tx[1], ty[1]) - max(tx[0], ty[0])
            evts.append({"apres_trame_de": nom, "t_s": f / 1e6, "ecart_ms": ecart / 1000, "recouvrement_ms": max(0.0, recouvrement / 1000),
                         "collision": recouvrement > 5000})
    evts.sort(key=lambda e: e["t_s"])
    tranches = []
    bas = 0.0
    for haut in TRANCHES_MS + (float("inf"),):
        dans = [e for e in evts if bas <= e["ecart_ms"] < haut]
        tranches.append({"de_ms": bas, "a_ms": haut, "conflits": len(dans), "collisions": sum(e["collision"] for e in dans)})
        bas = haut
    n, c = len(evts), sum(e["collision"] for e in evts)
    return {"conflits": n, "collisions": c, "taux_collision_pct": (100 * c / n) if n else None, "tranches": tranches, "evenements": evts,
            "calage": {"points": cal["points"], "residu_max_ms": cal["residu_max_us"] / 1000},
            "emissions": {"A": len(A), "B": len(B)}}


def rapport(r):
    if "erreur" in r:
        return "ATTENTE : " + r["erreur"]
    out = [f"{r['conflits']} conflits (les deux boîtiers repartent dans la seconde qui suit une fin de trame), {r['collisions']} collisions"
           + (f" = {r['taux_collision_pct']:.1f} %" if r["taux_collision_pct"] is not None else "")
           + f" ; émissions A {r['emissions']['A']}, B {r['emissions']['B']} ; calage : {r['calage']['points']} paquets, résidu max {r['calage']['residu_max_ms']:.2f} ms"]
    for t in r["tranches"]:
        if t["conflits"]:
            haut = "∞" if t["a_ms"] == float("inf") else f"{t['a_ms']:g}"
            out.append(f"   écart de départ {t['de_ms']:g} à {haut} ms : {t['conflits']} conflits, {t['collisions']} collisions")
    for e in r["evenements"]:
        if e["collision"]:
            out.append(f"   COLLISION à {e['t_s']:.2f} s (horloge de B) : départs à {e['ecart_ms']:.2f} ms l'un de l'autre, recouvrement {e['recouvrement_ms']:.0f} ms")
    return "\n".join(out)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Conflits d'accès au canal entre deux boîtiers.")
    p.add_argument("boitier_a")
    p.add_argument("boitier_b")
    p.add_argument("--json")
    p.add_argument("--fenetre", type=float, default=1.0, help="secondes après une fin de trame pendant lesquelles on cherche les deux départs")
    a = p.parse_args()
    r = conflits(a.boitier_a, a.boitier_b, a.fenetre)
    print(rapport(r))
    if a.json:
        json.dump(r, open(a.json, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
