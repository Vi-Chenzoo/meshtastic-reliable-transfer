#!/usr/bin/env python3
"""Analyse de deux journaux radio du firmware d'ESSAI v4 (outils/journal-radio.py lire) : temps d'émission en ms, attente avant émission,
surdité (trames perdues pendant que l'AUTRE boîtier émettait), pauses entre trames.

Copyright (C) 2026 SoCodeIA et Vincent PERRIN — GPL v3.

    python3 outils/analyse-journal-radio.py boitier1.json boitier2.json [--json analyse.json] [--detail]

Méthode (dite pour qu'on puisse la contester) :
  - Chaque boîtier date ses événements avec sa propre horloge (µs, 32 bits, étendue sur 64 avec l'horloge relevée au vidage). Les deux
    horloges ne sont PAS synchronisées et dérivent (cristaux à ±20 ppm : plusieurs dizaines de ms en 10 min).
  - On les cale l'une sur l'autre avec les paquets bien reçus (même identifiant Meshtastic chez l'émetteur et le récepteur) : fin
    d'émission d'un côté = fin de réception de l'autre (boîtiers collés : propagation négligeable). Ajustement linéaire décalage + dérive,
    dans les deux sens s'il y en a (le retard de traitement s'en va), en écartant les points aberrants.
  - Une trame émise par A et absente chez B est « sourde » si une émission de B recouvrait son temps d'antenne (de plus de 5 ms) ; « abîmée »
    si B l'a reçue avec une erreur ; sinon « non expliquée » (brouillage, portée, ou limite de la méthode).
  - Durée d'émission mesurée = instant de l'interruption de fin d'émission − début d'émission ; calculée = formule de Semtech
    (outils/temps-antenne.py) avec les réglages relevés dans l'en-tête, et durée annoncée par le firmware (champ aux de TX_DEBUT).
"""
import argparse, importlib.util, json, math, os, statistics, sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import lib_journal_radio as lj

_spec = importlib.util.spec_from_file_location("temps_antenne", os.path.join(ICI, "temps-antenne.py"))
temps_antenne = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(temps_antenne)

MARGE_RECOUVREMENT_US = 5000          # moins que ça : l'incertitude du calage, pas une vraie surdité
ECART_ABERRANT_MIN_US = 5000          # point de calage écarté s'il s'éloigne de plus de max(ceci, 4 MAD)
RAFALE_ECART_MAX_US = 5_000_000       # deux émissions séparées de moins que ça sont dans la même rafale


def charger(chemin_ou_dict):
    """Fichier de journal-radio.py (ou dict déjà lu) -> boîtier prêt à analyser."""
    j = chemin_ou_dict if isinstance(chemin_ou_dict, dict) else json.load(open(chemin_ou_dict, encoding="utf-8"))
    h = j["entete"]
    H = h["horloge_us"]
    for nom in ("logiciel", "isr"):
        for e in j["anneaux"][nom]:
            e["T"] = lj.etendre_t(e["t"], H)
    log, isr = j["anneaux"]["logiciel"], j["anneaux"]["isr"]
    b = {"nom": j.get("boitier", "?"), "entete": h, "avertissements": [], "enfile": {}, "attentes": [], "tx": {}, "rx": []}
    isr_tx = sorted((e for e in isr if e["type"] == lj.EV_ISR_TX), key=lambda e: e["T"])
    isr_rx = sorted((e for e in isr if e["type"] == lj.EV_ISR_RX), key=lambda e: e["T"])
    b["isr_tx"], b["isr_rx"] = len(isr_tx), len(isr_rx)
    b["isr_scrutation"] = sum(1 for e in isr if e["info"] & 1)
    tx_fins = [e for e in log if e["type"] == lj.EV_TX_FIN]
    rx_evts = [e for e in log if e["type"] == lj.EV_RX]
    par_seq = {e["aux"]: e for e in isr}
    for e in log:
        if e["type"] == lj.EV_ENFILE:
            b["enfile"].setdefault(e["id"], e["T"])
        elif e["type"] == lj.EV_ATTENTE:
            b["attentes"].append({"T": e["T"], "id": e["id"], "cause": e["info"]})
        elif e["type"] == lj.EV_REGLAGE:
            b.setdefault("reglages", []).append({"T": e["T"], "quoi": chr(e["info"]), "valeur": e["x"]})
        elif e["type"] == lj.EV_TX_DEBUT:
            b["tx"][e["id"]] = {"id": e["id"], "debut": e["T"], "octets": e["x"], "annonce_us": e["aux"], "fin": None}
    # fins d'émission : par ordre si les deux comptes concordent, sinon par numéro d'interruption (et on le dit)
    if len(isr_tx) == len(tx_fins):
        paires = list(zip(tx_fins, isr_tx))
    else:
        b["avertissements"].append(f"{len(tx_fins)} fins d'émission du logiciel pour {len(isr_tx)} interruptions : appariement par numéro, moins sûr")
        paires = [(f, par_seq[f["aux"]]) for f in tx_fins if f["aux"] in par_seq and par_seq[f["aux"]]["type"] == lj.EV_ISR_TX]
    for f, i in paires:
        t = b["tx"].get(f["id"])
        if t is not None and 0 <= i["T"] - t["debut"] < 20_000_000:
            t["fin"] = i["T"]
            t["fin_par_scrutation"] = bool(i["info"] & 1)
    # réceptions : même méthode
    if len(isr_rx) == len(rx_evts):
        paires = list(zip(rx_evts, isr_rx))
    else:
        b["avertissements"].append(f"{len(rx_evts)} paquets sortis de la radio pour {len(isr_rx)} interruptions de réception : appariement "
                                   "par numéro (une interruption peut être un préambule, pas une fin de réception)")
        paires = [(r, par_seq[r["aux"]]) for r in rx_evts if r["aux"] in par_seq and par_seq[r["aux"]]["type"] == lj.EV_ISR_RX]
    isr_de = {id(r): i for r, i in paires}
    for r in rx_evts:
        i = isr_de.get(id(r))
        b["rx"].append({"id": r["id"], "octets": r["x"], "etat": r["info"], "fin": i["T"] if i else r["T"], "exact": i is not None})
    b["tx_liste"] = sorted(b["tx"].values(), key=lambda t: t["debut"])
    for t in b["tx_liste"]:
        if t["fin"] is None:
            t["fin"] = t["debut"] + t["annonce_us"]
            t["fin_estimee"] = True
    return b


def duree_calculee_ms(h, octets):
    return temps_antenne.temps_ms(octets, h["bw_khz"], h["sf"], h["cr"])


# ---- calage des horloges ------------------------------------------------------------------------------------------
def _resoudre(a, y):
    """Moindres carrés : colonnes de a (liste de lignes) -> coefficients, par les équations normales (3 inconnues au plus)."""
    n = len(a[0])
    m = [[sum(r[i] * r[j] for r in a) for j in range(n)] + [sum(r[i] * v for r, v in zip(a, y))] for i in range(n)]
    for i in range(n):
        p = max(range(i, n), key=lambda k: abs(m[k][i]))
        if abs(m[p][i]) < 1e-12:
            return None
        m[i], m[p] = m[p], m[i]
        for k in range(n):
            if k != i:
                f = m[k][i] / m[i][i]
                m[k] = [x - f * z for x, z in zip(m[k], m[i])]
    return [m[i][n] / m[i][i] for i in range(n)]


def caler(a, b):
    """Calage de l'horloge de B sur celle de A : tB = (1 + derive) * (tA - x0) + decalage (+/- retard de traitement). None si impossible."""
    pts = []                                   # (tA, tB, signe) : +1 si A a émis (B a reçu), -1 si B a émis (A a reçu)
    rx_b = {r["id"]: r for r in b["rx"] if r["etat"] == 0 and r["exact"]}
    rx_a = {r["id"]: r for r in a["rx"] if r["etat"] == 0 and r["exact"]}
    for t in a["tx_liste"]:
        if t["id"] in rx_b and not t.get("fin_estimee"):
            pts.append((t["fin"], rx_b[t["id"]]["fin"], 1))
    for t in b["tx_liste"]:
        if t["id"] in rx_a and not t.get("fin_estimee"):
            pts.append((rx_a[t["id"]]["fin"], t["fin"], -1))
    sens = {s for _, _, s in pts}
    if len(pts) < 3:
        return None
    x0 = statistics.median(p[0] for p in pts)
    for _ in range(3):
        if len(sens) == 2:
            res = _resoudre([[p[0] - x0, 1.0, float(p[2])] for p in pts], [p[1] - x0 for p in pts])
            if res is None:
                return None
            d, off, delta = res[0] - 1.0, res[1], res[2]            # res[0] = pente = 1 + dérive
            pred = [(1 + d) * (p[0] - x0) + off + p[2] * delta + x0 for p in pts]
        else:
            res = _resoudre([[p[0] - x0, 1.0] for p in pts], [p[1] - x0 for p in pts])
            if res is None:
                return None
            d, off, delta = res[0] - 1.0, res[1], 0.0
            pred = [(1 + d) * (p[0] - x0) + off + x0 for p in pts]
        r = [p[1] - q for p, q in zip(pts, pred)]
        mad = statistics.median(abs(v - statistics.median(r)) for v in r)
        seuil = max(ECART_ABERRANT_MIN_US, 4 * 1.4826 * mad)
        garde = [p for p, v in zip(pts, r) if abs(v) <= seuil]
        if len(garde) == len(pts) or len(garde) < 3:
            break
        pts = garde
    residus = [p[1] - q for p, q in zip(pts, pred)]
    return {"x0": x0, "derive": d, "decalage_us": off, "retard_traitement_us": delta, "points": len(pts), "deux_sens": len(sens) == 2,
            "residu_median_us": statistics.median(abs(v) for v in residus), "residu_max_us": max(abs(v) for v in residus)}


def vers_b(cal, tA):
    return (1 + cal["derive"]) * (tA - cal["x0"]) + cal["decalage_us"] + cal["x0"]


def vers_a(cal, tB):
    return (tB - cal["x0"] - cal["decalage_us"]) / (1 + cal["derive"]) + cal["x0"]


# ---- classement des trames perdues --------------------------------------------------------------------------------
def classer_pertes(emetteur, recepteur, vers_emetteur):
    """Trames de `emetteur` absentes chez `recepteur` ; `vers_emetteur` convertit une date du récepteur dans l'horloge de l'émetteur."""
    recus = {}
    for r in recepteur["rx"]:
        recus.setdefault(r["id"], r)
    tx_rec = [(vers_emetteur(t["debut"]), vers_emetteur(t["fin"]), t) for t in recepteur["tx_liste"]]
    sortie = {"recues": 0, "abimees": [], "sourdes": [], "non_expliquees": []}
    for t in emetteur["tx_liste"]:
        r = recus.get(t["id"])
        if r is not None and r["etat"] == 0:
            sortie["recues"] += 1
            continue
        if r is not None:
            sortie["abimees"].append({"id": t["id"], "t_us": t["debut"], "erreur": r["etat"] & 0x7F})
            continue
        deb, fin = t["debut"], t["fin"]
        meilleur = None
        for d2, f2, t2 in tx_rec:
            rec = min(fin, f2) - max(deb, d2)
            if rec > MARGE_RECOUVREMENT_US and (meilleur is None or rec > meilleur[0]):
                meilleur = (rec, t2, d2, f2)
        if meilleur:
            rec, t2, d2, f2 = meilleur
            place = "début" if d2 <= deb else "fin" if f2 >= fin else "milieu"
            sortie["sourdes"].append({"id": t["id"], "t_us": deb, "recouvrement_ms": rec / 1000, "emission_du_recepteur_octets": t2["octets"],
                                      "place_dans_la_trame": place})
        else:
            sortie["non_expliquees"].append({"id": t["id"], "t_us": deb})
    return sortie


# ---- statistiques d'un boîtier ------------------------------------------------------------------------------------
def _centiles(v):
    if not v:
        return None
    v = sorted(v)
    return {"n": len(v), "min": v[0], "mediane": statistics.median(v), "p95": v[min(len(v) - 1, int(0.95 * len(v)))], "max": v[-1]}


def statistiques(b):
    h = b["entete"]
    tx = b["tx_liste"]
    mesure = [(t["fin"] - t["debut"]) / 1000 for t in tx if not t.get("fin_estimee")]
    calcule = [duree_calculee_ms(h, t["octets"]) for t in tx if not t.get("fin_estimee")]
    annonce = [t["annonce_us"] / 1000 for t in tx if not t.get("fin_estimee")]
    retard = [(t["debut"] - b["enfile"][t["id"]]) / 1000 for t in tx if t["id"] in b["enfile"]]
    attentes = {}
    for a in b["attentes"]:
        attentes[a["cause"]] = attentes.get(a["cause"], 0) + 1
    ecart = [(m - c) for m, c in zip(mesure, calcule)]
    ecarts_rafale = [(t2["debut"] - t1["fin"]) / 1000 for t1, t2 in zip(tx, tx[1:]) if 0 <= t2["debut"] - t1["fin"] < RAFALE_ECART_MAX_US]
    debut = min([t["debut"] for t in tx] + [r["fin"] for r in b["rx"]] or [0])
    fin = max([t["fin"] for t in tx] + [r["fin"] for r in b["rx"]] or [0])
    total_tx = sum(mesure)
    return {"boitier": b["nom"], "emissions": len(tx), "emissions_mesurees": len(mesure), "duree_emission_totale_ms": total_tx,
            "duree_calculee_totale_ms": sum(calcule), "duree_annoncee_totale_ms": sum(annonce),
            "ecart_mesure_calcule_ms": _centiles(ecart), "ecart_relatif_pct": (100 * (total_tx - sum(calcule)) / sum(calcule)) if calcule else None,
            "retard_file_vers_air_ms": _centiles(retard), "attentes_par_cause": {lj.CAUSES.get(k, str(k)): v for k, v in attentes.items()},
            "paquets_recus_bons": sum(1 for r in b["rx"] if r["etat"] == 0), "paquets_recus_en_erreur": sum(1 for r in b["rx"] if r["etat"] != 0),
            "interruptions_tx": b["isr_tx"], "interruptions_rx": b["isr_rx"], "vues_par_scrutation": b["isr_scrutation"],
            "fenetre_ms": (fin - debut) / 1000, "part_sourde_pct": (100 * total_tx / ((fin - debut) / 1000)) if fin > debut else None,
            "pause_entre_emissions_ms": _centiles(ecarts_rafale), "avertissements": b["avertissements"],
            "reglages": [{"quoi": r["quoi"], "valeur": r["valeur"]} for r in b.get("reglages", [])]}


def reponses_courtes_dans_rafale(a, b, conv, seuil_octets=100):
    """Émissions COURTES de B (BILAN, point d'étape…) tombées PENDANT une rafale de A : t en s depuis le début de la rafale de A.
    `conv` : date de B -> horloge de A."""
    tx = a["tx_liste"]
    if not tx:
        return []
    deb_a = tx[0]["debut"]
    sortie = []
    for t in b["tx_liste"]:
        d, f = conv(t["debut"]), conv(t["fin"])
        dedans = any(x["debut"] - 1_000_000 <= d <= x["fin"] + 1_000_000 for x in tx)
        if dedans and t["octets"] <= seuil_octets:
            retard = (t["debut"] - b["enfile"][t["id"]]) / 1000 if t["id"] in b["enfile"] else None
            sortie.append({"t_s": (d - deb_a) / 1e6, "octets": t["octets"], "duree_ms": (f - d) / 1000, "retard_file_ms": retard})
    return sortie


def analyser(ja, jb):
    a, b = charger(ja), charger(jb)
    sortie = {"a": statistiques(a), "b": statistiques(b), "calage": None}
    cal = caler(a, b)
    if cal is None:
        sortie["avertissement_calage"] = ("moins de 3 paquets bien reçus communs aux deux boîtiers : horloges non calées, "
                                          "pas de classement des pertes")
        return sortie
    sortie["calage"] = cal
    sortie["a_vers_b"] = classer_pertes(a, b, lambda t: vers_a(cal, t))
    sortie["b_vers_a"] = classer_pertes(b, a, lambda t: vers_b(cal, t))
    sortie["reponses_courtes_de_b_dans_la_rafale_de_a"] = reponses_courtes_dans_rafale(a, b, lambda t: vers_a(cal, t))
    sortie["reponses_courtes_de_a_dans_la_rafale_de_b"] = reponses_courtes_dans_rafale(b, a, lambda t: vers_b(cal, t))
    return sortie


def _ms(v, n=1):
    return "—" if v is None else f"{v:.{n}f}"


def _ligne_centiles(c, unite="ms"):
    return "aucune" if not c else f"{c['n']} mesures, médiane {c['mediane']:.1f}, p95 {c['p95']:.1f}, max {c['max']:.1f} {unite}"


def rapport(s):
    out = []
    for cle, nom in (("a", "Boîtier A"), ("b", "Boîtier B")):
        x = s[cle]
        out.append(f"== {nom} {x['boitier']} ==")
        out.append(f"émissions : {x['emissions']} ({x['emissions_mesurees']} avec durée mesurée) ; temps d'émission mesuré {x['duree_emission_totale_ms']:.0f} ms, "
                   f"calculé (Semtech) {x['duree_calculee_totale_ms']:.0f} ms, annoncé par le firmware {x['duree_annoncee_totale_ms']:.0f} ms"
                   + (f" ; écart mesuré/calculé {x['ecart_relatif_pct']:+.2f} %" if x["ecart_relatif_pct"] is not None else ""))
        out.append(f"écart par trame (mesuré − calculé) : {_ligne_centiles(x['ecart_mesure_calcule_ms'])}")
        out.append(f"attente entre la mise en file et le début d'émission : {_ligne_centiles(x['retard_file_vers_air_ms'])}")
        out.append("émissions repoussées : " + (", ".join(f"{k} ×{v}" for k, v in x["attentes_par_cause"].items()) or "aucune"))
        out.append(f"pause entre deux émissions d'une même rafale : {_ligne_centiles(x['pause_entre_emissions_ms'])}")
        out.append(f"reçus : {x['paquets_recus_bons']} bons, {x['paquets_recus_en_erreur']} en erreur ; interruptions : {x['interruptions_tx']} d'émission, "
                   f"{x['interruptions_rx']} de réception ({x['vues_par_scrutation']} vues par la scrutation)")
        out.append(f"temps passé à émettre (donc sourd) : {_ms(x['part_sourde_pct'])} % d'une fenêtre de {x['fenetre_ms'] / 1000:.1f} s")
        if x.get("reglages"):
            out.append("réglages d'essai reçus : " + ", ".join(f"{r['quoi']} = {r['valeur']}" for r in x["reglages"]) + "  (W : bits de fenêtre de contention en plus pour les données)")
        for w in x["avertissements"]:
            out.append("ATTENTION : " + w)
    if s.get("calage") is None:
        out.append("")
        out.append("ATTENTION : " + s.get("avertissement_calage", "horloges non calées"))
        return "\n".join(out)
    c = s["calage"]
    out.append("")
    out.append(f"== Calage des horloges == {c['points']} paquets communs ({'deux sens' if c['deux_sens'] else 'un seul sens'}), dérive {c['derive'] * 1e6:+.1f} ppm, "
               f"résidu médian {c['residu_median_us'] / 1000:.2f} ms, max {c['residu_max_us'] / 1000:.2f} ms"
               + (f", retard de traitement {c['retard_traitement_us'] / 1000:.2f} ms" if c["deux_sens"] else ""))
    for cle, titre in (("a_vers_b", "A → B"), ("b_vers_a", "B → A")):
        p = s[cle]
        envoyees = p["recues"] + len(p["abimees"]) + len(p["sourdes"]) + len(p["non_expliquees"])
        out.append(f"== Trames {titre} == {envoyees} émises : {p['recues']} reçues, {len(p['sourdes'])} perdues par surdité (le récepteur émettait), "
                   f"{len(p['abimees'])} abîmées, {len(p['non_expliquees'])} perdues sans cause vue")
        for z in p["sourdes"]:
            out.append(f"   sourde : id {z['id']:#010x}, recouvrement {z['recouvrement_ms']:.0f} ms ({z['place_dans_la_trame']} de la trame), "
                       f"le récepteur émettait {z['emission_du_recepteur_octets']} octets")
    for cle, titre in (("reponses_courtes_de_b_dans_la_rafale_de_a", "B pendant la rafale de A"),
                       ("reponses_courtes_de_a_dans_la_rafale_de_b", "A pendant la rafale de B")):
        if s[cle]:
            out.append(f"== Réponses courtes de {titre} (BILAN, point d'étape…) ==")
            for r in s[cle]:
                out.append(f"   à {r['t_s']:.1f} s : {r['octets']} octets, {r['duree_ms']:.0f} ms d'antenne"
                           + (f", attente avant départ {r['retard_file_ms']:.0f} ms" if r["retard_file_ms"] is not None else ""))
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description="Analyse de deux journaux radio du firmware d'essai v4.")
    p.add_argument("boitier_a")
    p.add_argument("boitier_b")
    p.add_argument("--json", help="écrire aussi le détail en JSON")
    args = p.parse_args()
    s = analyser(args.boitier_a, args.boitier_b)
    print(rapport(s))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
