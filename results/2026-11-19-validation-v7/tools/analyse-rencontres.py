#!/usr/bin/env python3
"""Rencontres ESP-NOW (firmware d'essai v8) : en combien de temps un boîtier qui arrive connaît-il son voisin, avec ou sans le « bonjour de rencontre » ?

Copyright (C) 2026 SoCodeIA et Vincent PERRIN — GPL v3.

    python3 outils/analyse-rencontres.py essai-boitier1.json essai-boitier2.json [--json sortie.json]

Entrée : les journaux radio relus par `outils/journal-radio.py lire` sur les DEUX boîtiers après UNE rencontre (ordres de l'essai :
`journal-radio.py oublier --valeur 0` sur le boîtier « ancien » puis `oublier --valeur 1` sur le « nouveau » ; `rencontre --valeur 0|1` sur
l'ancien AVANT, pour couper ou non la réponse de rencontre ; les deux ordres sont notés au journal : événement REGLAGE, lettres 'O' et 'B').
Chaque boîtier date avec SA propre horloge : on ne compare JAMAIS deux horloges, seulement des écarts mesurés sur un même boîtier.
Pour chaque boîtier : T_O = instant de son ordre « oublier » ; « connaît l'autre » = premier bonjour REÇU avec signature valide après T_O ;
délai = connaît − T_O. Sont aussi relevés : les bonjours émis après T_O (instant depuis T_O, durée de signature), les bonjours reçus (durée de
vérification, rencontre ou non, réponse de rencontre programmée ou refusée).
"""
import argparse, json, os, sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import lib_journal_radio as lj


def charger(source):
    j = source if isinstance(source, dict) else json.load(open(source, encoding="utf-8"))
    H = j["entete"]["horloge_us"]
    ev = [dict(e, T=lj.etendre_t(e["t"], H)) for e in j["anneaux"]["logiciel"] if e["type"] in (lj.EV_BONJOUR, lj.EV_REGLAGE)]
    return j.get("boitier", "?"), sorted(ev, key=lambda e: e["T"])


def un_boitier(ev, horizon_s):
    oublis = [e for e in ev if e["type"] == lj.EV_REGLAGE and chr(e["info"]) == "O"]
    regles_b = [e for e in ev if e["type"] == lj.EV_REGLAGE and chr(e["info"]) == "B"]
    if not oublis:
        return {"erreur": "pas d'ordre 'oublier' dans ce journal (firmware d'essai v8 ? journal vidé après l'ordre ?)"}
    o = oublis[-1]
    t0 = o["T"]
    apres = [e for e in ev if e["type"] == lj.EV_BONJOUR and 0 <= e["T"] - t0 <= horizon_s * 1e6]
    recus = [e for e in apres if not e["info"] & 1]
    valides = [e for e in recus if e["info"] & 2]
    emis = [e for e in apres if e["info"] & 1]
    reponse = None
    b_val = [e["x"] for e in regles_b if e["T"] <= t0]
    return {
        "oublier": "oublier et dire bonjour" if o["x"] == 1 else "oublier seulement",
        "reponse_de_rencontre": ("oui" if b_val[-1] == 1 else "non") if b_val else "oui (défaut)",
        "connait_l_autre_apres_s": (valides[0]["T"] - t0) / 1e6 if valides else None,
        "premier_bonjour_valide_rencontre": bool(valides and valides[0]["info"] & 4),
        "bonjours_emis": [{"apres_s": round((e["T"] - t0) / 1e6, 3), "signature_ms": e["x"] / 10} for e in emis],
        "bonjours_recus": [{"apres_s": round((e["T"] - t0) / 1e6, 3), "verification_ms": e["x"] / 10, "valide": bool(e["info"] & 2),
                            "rencontre": bool(e["info"] & 4), "reponse_programmee": bool(e["info"] & 8), "reponse_refusee": bool(e["info"] & 16)}
                           for e in recus],
        "horizon_s": horizon_s,
    }


def analyser(a, b, horizon_s=90.0):
    na, eva = charger(a)
    nb, evb = charger(b)
    return {"a": dict(boitier=na, **un_boitier(eva, horizon_s)), "b": dict(boitier=nb, **un_boitier(evb, horizon_s))}


def rapport(s):
    sortie = []
    for cle, titre in (("a", "Boîtier A"), ("b", "Boîtier B")):
        x = s[cle]
        sortie.append(f"== {titre} {x['boitier']} ==")
        if "erreur" in x:
            sortie.append("  " + x["erreur"])
            continue
        c = x["connait_l_autre_apres_s"]
        sortie.append(f"  ordre : {x['oublier']} ; réponse de rencontre : {x['reponse_de_rencontre']}")
        sortie.append("  connaît l'autre " + (f"{c:.2f} s après son ordre" + (" (bonjour reçu = rencontre)" if x["premier_bonjour_valide_rencontre"] else "") if c is not None
                                            else f"JAMAIS dans les {x['horizon_s']:.0f} s"))
        sortie.append("  bonjours émis : " + (", ".join(f"+{e['apres_s']:.2f} s ({e['signature_ms']:.1f} ms)" for e in x["bonjours_emis"]) or "aucun"))
        for e in x["bonjours_recus"]:
            sortie.append(f"  bonjour reçu +{e['apres_s']:.2f} s : vérification {e['verification_ms']:.1f} ms, " + ("valide" if e["valide"] else "SIGNATURE MAUVAISE")
                          + (", rencontre" if e["rencontre"] else "") + (", réponse programmée" if e["reponse_programmee"] else "")
                          + (", réponse refusée" if e["reponse_refusee"] else ""))
    return "\n".join(sortie)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("boitier1")
    p.add_argument("boitier2")
    p.add_argument("--horizon", type=float, default=90.0, help="secondes après l'ordre « oublier » à regarder (défaut 90 : un bonjour périodique tous les ~60 s)")
    p.add_argument("--json")
    args = p.parse_args()
    s = analyser(args.boitier1, args.boitier2, args.horizon)
    print(rapport(s))
    if args.json:
        json.dump(s, open(args.json, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
