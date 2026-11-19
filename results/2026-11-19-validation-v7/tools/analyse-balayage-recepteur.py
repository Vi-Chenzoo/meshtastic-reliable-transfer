#!/usr/bin/env python3
"""Pertes SANS collision et balayage du canal (CAD) du RÉCEPTEUR : où tombe le balayage par rapport au préambule de la trame ?

Copyright (C) 2026 SoCodeIA et Vincent PERRIN — GPL v3.

    python3 outils/analyse-balayage-recepteur.py [--racine essais] [--json sortie.json] [--detail]

Question (point « pas prouvé » n° 2, 19 nov. 2026) : le journal du 19 nov. 01:00 disait « les trames perdues sans collision ont toutes un
balayage du canal « occupé » chez le récepteur pendant leur durée » (4 sur 66 avec balayage, 0 sur 565 sans). Ici on refait le compte sur TOUS
les journaux (18-19 nov., v4 à v7) et on regarde, pour chaque trame qui a eu au moins un balayage « canal occupé » (cause 2) chez le
récepteur PENDANT sa durée, à quel moment du préambule il tombe : décalage depuis le début de la trame (ms et en symboles), durée de
préambule restant, temps écoulé depuis la fin de la réception précédente du récepteur.

Méthode (mêmes journaux, même calage des horloges que analyse-journal-radio.py) :
  - on garde les trames qui n'ont PAS été recouvertes par une émission du récepteur (celles-là sont des collisions ou de la surdité, étudiées
    ailleurs) ; on ne garde que des trames reçues (état 0) ou absentes chez le récepteur ;
  - le journal ne note un balayage du récepteur que lorsqu'il trouve le canal OCCUPÉ (l'émission est alors repoussée, cause 2) : un balayage
    qui trouve le canal libre ne laisse pas de trace (et la trame d'un autre boîtier n'est de toute façon pas « libre » pendant son temps
    d'antenne) ; on ne voit donc ni le début ni la durée du balayage, seulement l'instant où il a rendu sa réponse ;
  - décalage en symboles : Ts = 2^SF / BW ; préambule total = (préambule + 4,25) symboles (préambule annoncé dans l'en-tête, 16 en Meshtastic).
"""
import argparse, glob, importlib.util, json, os, re, sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import lib_journal_radio as lj

_spec = importlib.util.spec_from_file_location("an", os.path.join(ICI, "analyse-journal-radio.py"))
an = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(an)


def trouver_paires(racine, suffixe="boitier"):
    """Paires de journaux <essai>-<suffixe>1.json / <essai>-<suffixe>2.json sous `racine` (suffixe « boitier » : nos pièces ; « board » : le dossier public anonymisé)."""
    fin1, fin2 = f"-{suffixe}1.json", f"-{suffixe}2.json"
    for f1 in sorted(glob.glob(os.path.join(racine, "**", "*" + fin1), recursive=True)):
        f2 = f1.replace(fin1, fin2)
        if not os.path.exists(f2):
            continue
        if os.path.exists(f1.replace(fin1, "-NON-VALABLE.txt")):
            print(f"(essai {os.path.basename(f1).replace(fin1, '')} écarté : fichier -NON-VALABLE.txt, son journal mélange deux essais)", file=sys.stderr)
            continue
        yield os.path.relpath(f1, racine).replace(fin1, ""), f1, f2


def balayages(chemin):
    """Événements CAD (v8) d'un journal : liste de {debut_us, fin_us, occupe, peek, maintien, reception} dans l'horloge du boîtier."""
    j = json.load(open(chemin, encoding="utf-8"))
    H = j["entete"]["horloge_us"]
    sortie = []
    for e in j["anneaux"]["logiciel"]:
        if e["type"] == lj.EV_CAD:
            fin = lj.etendre_t(e["t"], H)
            sortie.append({"debut_us": fin - e["aux"], "fin_us": fin, "occupe": bool(e["info"] & 1), "peek": bool(e["info"] & 2),
                           "maintien": bool(e["info"] & 4), "reception": bool(e["info"] & 8)})
    return sorted(sortie, key=lambda b: b["fin_us"])


def rapport_cad(nom, preset, b1, b2, conv_1_vers_2):
    """Statistiques des balayages des DEUX boîtiers d'un essai v8 (durée, résultat, état avant, intervalle entre balayages successifs)."""
    lignes = []
    for titre, bal in (("boîtier 1", b1), ("boîtier 2", b2)):
        if not bal:
            continue
        occ = [x for x in bal if x["occupe"]]
        lib = [x for x in bal if not x["occupe"]]
        def cent(l):
            l = sorted((x["fin_us"] - x["debut_us"]) / 1000 for x in l)
            return f"{len(l)} balayages, durée min {l[0]:.1f} / médiane {l[len(l) // 2]:.1f} / max {l[-1]:.1f} ms" if l else "aucun"
        lignes.append(f"  {titre} : occupés : {cent(occ)} ; libres : {cent(lib)}")
        lignes.append(f"    état avant le balayage (occupés) : maintien du préambule {sum(x['maintien'] for x in occ)}, balayage de lecture {sum(x['peek'] for x in occ)}, "
                      f"réception armée {sum(x['reception'] for x in occ)} sur {len(occ)} ; (libres) : maintien {sum(x['maintien'] for x in lib)}, lecture {sum(x['peek'] for x in lib)}, "
                      f"réception armée {sum(x['reception'] for x in lib)} sur {len(lib)}")
        ecarts = sorted((y["debut_us"] - x["fin_us"]) / 1000 for x, y in zip(bal, bal[1:]) if x["occupe"] and 0 <= y["debut_us"] - x["fin_us"] < 100_000)
        if ecarts:
            lignes.append(f"    pause entre la fin d'un balayage OCCUPÉ et le début du suivant (< 100 ms) : {len(ecarts)} mesures, min {ecarts[0]:.1f} / médiane {ecarts[len(ecarts) // 2]:.1f} / max {ecarts[-1]:.1f} ms")
    return lignes


def preset_de(h):
    return lj.PRESETS.get(h["preset"], str(h["preset"]))


def trames_d_un_sens(em, rec, vers_em, h):
    """Trames de `em` vues par `rec` : liste de dict. `vers_em` : date du récepteur -> horloge de l'émetteur."""
    ts_ms = (2 ** h["sf"]) / h["bw_khz"]                       # durée d'un symbole en ms
    pre_ms = (h["preambule"] + 4.25) * ts_ms
    recus = {}
    for r in rec["rx"]:
        recus.setdefault(r["id"], r)
    tx_rec = [(vers_em(t["debut"]), vers_em(t["fin"])) for t in rec["tx_liste"]]
    rx_fins = sorted(vers_em(r["fin"]) for r in rec["rx"])      # fins de réception du récepteur (horloge de l'émetteur)
    attentes = [(vers_em(a["T"]), a["cause"]) for a in rec["attentes"]]
    sortie = []
    for t in em["tx_liste"]:
        deb, fin = t["debut"], t["fin"]
        if any(min(fin, f2) - max(deb, d2) > an.MARGE_RECOUVREMENT_US for d2, f2 in tx_rec):
            continue                                              # le récepteur émettait : collision / surdité, pas notre sujet
        r = recus.get(t["id"])
        if r is not None and r["etat"] != 0:
            continue                                              # abîmée : autre sujet
        occupes = sorted((T - deb) / 1000 for T, c in attentes if c == lj.CAUSE_CANAL_OCCUPE and deb <= T <= fin)
        en_rx = sorted((T - deb) / 1000 for T, c in attentes if c == lj.CAUSE_RECEPTION and deb <= T <= fin)
        avant = [f for f in rx_fins if f <= deb]
        ecart_prec = (deb - avant[-1]) / 1000 if avant else None
        sortie.append({"id": t["id"], "octets": t["octets"], "duree_ms": (fin - deb) / 1000, "recue": r is not None,
                       "ecart_depuis_rx_precedente_ms": ecart_prec, "occupes_ms": occupes, "en_reception_ms": en_rx,
                       "ts_ms": ts_ms, "preambule_ms": pre_ms})
    return sortie


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--racine", default=os.path.join(os.path.dirname(ICI), "essais"))
    p.add_argument("--suffixe", default="boitier", help="« boitier » (nos pièces, défaut) ou « board » (journaux anonymisés du dossier public)")
    p.add_argument("--json")
    p.add_argument("--detail", action="store_true", help="une ligne par trame avec balayage « occupé » pendant sa durée")
    args = p.parse_args()
    lignes, ignores, tout, cad_essais = [], [], [], []
    for nom, f1, f2 in trouver_paires(args.racine, args.suffixe):
        try:
            a, b = an.charger(f1), an.charger(f2)
            cal = an.caler(a, b)
        except Exception as e:                                    # journal incomplet : on le dit
            ignores.append((nom, f"illisible : {e}"))
            continue
        if cal is None or a["entete"]["sf"] != b["entete"]["sf"]:
            ignores.append((nom, "aucune émission LoRa (essai ESP-NOW seul)" if not a["tx_liste"] and not b["tx_liste"] else "horloges non calées"))
            continue
        h = a["entete"]
        b1, b2 = balayages(f1), balayages(f2)
        if b1 or b2:
            cad_essais.append((nom, preset_de(h), b1, b2))
        for sens, (em, rec, conv) in {"A->B": (a, b, lambda t: an.vers_a(cal, t)), "B->A": (b, a, lambda t: an.vers_b(cal, t))}.items():
            for x in trames_d_un_sens(em, rec, conv, h):
                x.update({"essai": nom, "sens": sens, "preset": preset_de(h)})
                tout.append(x)
    # ---- comptes
    def groupe(f):
        return [x for x in tout if f(x)]

    def compte(lst):
        perdues = sum(1 for x in lst if not x["recue"])
        return f"{perdues} perdues sur {len(lst)}"

    print(f"Essais lus : {len({x['essai'] for x in tout})} ; ignorés : {len(ignores)}" + ("".join(f"\n  ignoré {n} : {m}" for n, m in ignores)))
    print(f"Trames étudiées (non recouvertes par une émission du récepteur, reçues ou absentes) : {len(tout)}")
    for preset in sorted({x['preset'] for x in tout}):
        sous = groupe(lambda x: x["preset"] == preset)
        avec = [x for x in sous if x["occupes_ms"]]
        sans = [x for x in sous if not x["occupes_ms"]]
        print(f"\n== {preset} ==  Ts = {sous[0]['ts_ms']:.2f} ms, préambule total {sous[0]['preambule_ms']:.1f} ms")
        print(f"  sans balayage « occupé » chez le récepteur pendant la trame : {compte(sans)}")
        print(f"  avec au moins un balayage « occupé » pendant la trame      : {compte(avec)}")
        # par décalage du PREMIER balayage occupé, en symboles
        tr = [(1, 2), (2, 4), (4, 8), (8, 16), (16, 99)]
        for lo, hi in tr:
            g = [x for x in avec if lo <= x["occupes_ms"][0] / x["ts_ms"] < hi]
            if g:
                print(f"    1er balayage entre +{lo} et +{hi if hi < 99 else '…'} symboles ({lo * g[0]['ts_ms']:.0f} à {hi * g[0]['ts_ms']:.0f} ms) : {compte(g)}")
        for nb in (1, 2, 3):
            g = [x for x in avec if (len(x["occupes_ms"]) == nb if nb < 3 else len(x["occupes_ms"]) >= 3)]
            if g:
                print(f"    {'1 balayage' if nb == 1 else '2 balayages' if nb == 2 else '3 balayages ou plus'} « occupé » pendant la trame : {compte(g)}")
        print("  selon le préambule RESTANT (en symboles) au DERNIER balayage « occupé » tombé pendant le préambule :")
        for lo, hi, nom_ in ((0, 5, "moins de 5"), (5, 6.5, "5 à 6,5"), (6.5, 7.5, "6,5 à 7,5"), (7.5, 10, "7,5 à 10"), (10, 1e9, "10 et plus")):
            g = [x for x in avec if any(o <= x["preambule_ms"] for o in x["occupes_ms"])
                 and lo <= (x["preambule_ms"] - max(o for o in x["occupes_ms"] if o <= x["preambule_ms"])) / x["ts_ms"] < hi]
            if g:
                print(f"    reste {nom_} symboles : {compte(g)}")
        g = [x for x in avec if not any(o <= x["preambule_ms"] for o in x["occupes_ms"])]
        if g:
            print(f"    tous les balayages APRÈS la fin du préambule (le récepteur ne recevait déjà plus) : {compte(g)}")
        ecarts = [b - a_ for x in avec for a_, b in zip(x["occupes_ms"], x["occupes_ms"][1:]) if b - a_ < 40 * x["ts_ms"]]
        if ecarts:
            ecarts.sort()
            print(f"  écart entre deux balayages « occupé » successifs de la même trame (< {40 * sous[0]['ts_ms']:.0f} ms) : {len(ecarts)} mesures, "
                  f"min {ecarts[0]:.1f}, médiane {ecarts[len(ecarts) // 2]:.1f}, max {ecarts[-1]:.1f} ms")
        g0 = [x for x in avec if x["occupes_ms"][0] / x["ts_ms"] < 1]
        if g0:
            print(f"    1er balayage dans le 1er symbole : {compte(g0)}")
        # selon l'écart depuis la réception précédente (le récepteur vient-il de finir une trame ?)
        for lo, hi in ((0, 100), (100, 500), (500, 5000), (5000, 1e12)):
            g = [x for x in avec if x["ecart_depuis_rx_precedente_ms"] is not None and lo <= x["ecart_depuis_rx_precedente_ms"] < hi]
            if g:
                print(f"    réception précédente finie depuis {lo} à {hi if hi < 1e11 else '…'} ms : {compte(g)}")
        # trames sans balayage « occupé » MAIS pendant lesquelles le journal note « radio en réception » chez le récepteur (autre cause d'attente)
        rxr = [x for x in sans if x["en_reception_ms"]]
        if rxr:
            print(f"  sans balayage occupé mais avec une attente « radio en réception » du récepteur : {compte(rxr)}")
    perdues_sans = [x for x in tout if not x["recue"] and not x["occupes_ms"]]
    if perdues_sans:
        print(f"\nTrames PERDUES sans balayage « occupé » du récepteur ({len(perdues_sans)}), par essai :")
        par = {}
        for x in perdues_sans:
            par.setdefault((x["essai"], x["sens"]), []).append(x)
        for (essai, sens), l in sorted(par.items()):
            print(f"  {essai:36s} {sens} : {len(l)} perdue(s) ; octets {sorted({x['octets'] for x in l})} ; "
                  f"réception précédente finie depuis {', '.join(('%.0f' % x['ecart_depuis_rx_precedente_ms']) if x['ecart_depuis_rx_precedente_ms'] is not None else '—' for x in l[:6])} ms")
    if cad_essais:
        print(f"\n== Événements CAD du journal (firmware d'essai v8) : {len(cad_essais)} essais ==")
        for nom_, preset_, b1, b2 in cad_essais:
            print(f"- {nom_} ({preset_})")
            for l in rapport_cad(nom_, preset_, b1, b2, None):
                print(l)
    if args.detail:
        print("\nDétail (trames avec balayage « occupé » pendant leur durée) :")
        for x in sorted((x for x in tout if x["occupes_ms"]), key=lambda x: (x["preset"], x["recue"], x["occupes_ms"][0])):
            print(f"  {x['preset']:11s} {x['essai']:34s} {x['sens']} {x['octets']:3d} o  {'reçue ' if x['recue'] else 'PERDUE'} 1er balayage à +{x['occupes_ms'][0]:6.1f} ms "
                  f"({x['occupes_ms'][0] / x['ts_ms']:5.1f} symboles) ; reste de préambule {max(0.0, x['preambule_ms'] - x['occupes_ms'][0]):5.1f} ms ; "
                  f"{len(x['occupes_ms'])} balayage(s) ; réception précédente finie depuis "
                  f"{('%.0f ms' % x['ecart_depuis_rx_precedente_ms']) if x['ecart_depuis_rx_precedente_ms'] is not None else '—'}")
    if args.json:
        json.dump(tout, open(args.json, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
