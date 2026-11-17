#!/usr/bin/env python3
# Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
"""Simulation en mémoire du protocole de transfert sur un lien radio à pertes (un saut), sans le banc.

Modèle volontairement simple, à recouper ensuite sur le banc (firmware réel) :
- un seul canal partagé : une trame à la fois, dans un sens ou dans l'autre ;
- chaque trame coûte son temps d'antenne (outils/temps-antenne.py ; taille = 16 octets d'en-tête radio + 6 octets
  d'enveloppe Data + la trame) plus un délai moyen d'accès au canal (3,5 tranches, docs/03) ;
- chaque trame est perdue avec la probabilité `perte`, indépendamment.

Trois façons de livrer un contenu, comparées sur les mêmes tirages :
- « actuel » : ce que ferait une appli aujourd'hui, un message Meshtastic de 233 octets par morceau avec want_ack,
  renvoi après l'attente du firmware (docs/03 : 2 x trame + forfait) jusqu'à 5 essais, un morceau à la fois ;
- « officiel » : notre protocole avec des morceaux de 216 octets (champs ChunkedPayload, docs/05) ;
- « compact » : notre protocole avec des morceaux de 215 octets (229 avant le 5 nov. 2026) (idée de l'utilisateur, docs/07 P10).
Usage : prototype/simulation.py            (comparaison des méthodes, canal libre)
        prototype/simulation.py --budget   (protocole compact adaptatif, libre puis avec protocole.Budget)
"""
import bisect, heapq, importlib.util, math, pathlib, random, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from protocole import Budget, Emetteur, Recepteur, UTILE_COMPACT, UTILE_OFFICIEL

spec = importlib.util.spec_from_file_location("ta", pathlib.Path(__file__).parent.parent / "outils" / "temps-antenne.py")
ta = importlib.util.module_from_spec(spec); spec.loader.exec_module(ta)


class Canal:
    def __init__(self, preset, perte, graine, rafale=0.0):
        """rafale (17 nov. 2026) : 0 = pertes indépendantes trame par trame (modèle historique, mêmes tirages) ;
        sinon durée MOYENNE en secondes d'une période brouillée (modèle de Gilbert-Elliott en temps continu) : le canal
        alterne périodes calmes et brouillées de durées exponentielles, brouillé `perte` du temps en moyenne ; une
        trame est perdue si le milieu de son émission tombe dans une période brouillée. Même taux moyen, mais groupé."""
        self.bw, self.sf, self.cr, _ = ta.PRESETS[preset]
        self.tranche = (4.5 * 2 ** self.sf / self.bw + 7.6) / 1000
        self.perte, self.alea = perte, random.Random(graine)
        self.libre_a, self.antenne, self.trames = 0.0, 0.0, 0
        self.occupe = []                       # intervalles (début, fin) réservés, triés : trames espacées par le budget
        self.rafale, self.perdues = rafale, 0
        # rafale < 0 : rafales comptées EN TRAMES (|rafale| trames perdues d'affilée en moyenne), modèle de Gilbert à
        # deux états tiré trame par trame : la part de trames perdues est `perte` quoi que fasse l'émetteur (le cas le
        # plus dur : attendre pendant une coupure ne fait plus perdre moins de trames)
        if rafale < 0 and perte:
            self.alea_r = random.Random(graine * 7919 + 17)
            self.etat_brouille = self.alea_r.random() < perte
        elif rafale and perte:
            self.alea_r = random.Random(graine * 7919 + 17)    # tirages à part : le reste de la simulation ne bouge pas
            self.brouille = []                 # périodes brouillées (début, fin), produites au fur et à mesure
            self.horizon = 0.0
            self.etat_brouille = self.alea_r.random() < perte   # état de départ selon la proportion de temps

    def _brouille_a(self, t):
        calme = self.rafale * (1 - self.perte) / self.perte
        while self.horizon <= t:
            d = self.alea_r.expovariate(1 / (self.rafale if self.etat_brouille else calme))
            if self.etat_brouille:
                self.brouille.append((self.horizon, self.horizon + d))
            self.horizon += d
            self.etat_brouille = not self.etat_brouille
        k = bisect.bisect_right(self.brouille, (t, math.inf)) - 1
        return k >= 0 and self.brouille[k][0] <= t < self.brouille[k][1]

    def duree(self, octets):
        return ta.temps_ms(min(16 + 6 + octets, 255), self.bw, self.sf, self.cr) / 1000

    def place(self, quand, d):
        """Premier début >= quand (après l'accès au canal) où la trame tient sans chevaucher une autre."""
        debut = quand + 3.5 * self.tranche
        for a, b in self.occupe:
            if debut + d <= a:
                break
            if b > debut:
                debut = b + 3.5 * self.tranche
        return debut

    def emettre(self, quand, octets, budget=None):
        """-> (instant d'arrivée, perdue ?). Avec un budget, la trame attend qu'il le permette."""
        if octets > 233:          # Data.payload : 233 octets au plus (mesh.options:24) ; la radio refuserait la trame
            raise ValueError(f"trame de {octets} octets, plus que les 233 de Data.payload")
        # Nos trames : 219 au plus (protocole.TRAME_MAX, chiffrement par clé publique des messages directs)
        d = self.duree(octets)
        debut = self.place(quand, d)
        while budget is not None:
            t = budget.quand(debut, d)
            if t <= debut:
                break
            debut = self.place(t, d)
        if budget is not None:
            budget.noter(debut, d)
        bisect.insort(self.occupe, (debut, debut + d))
        self.occupe = [x for x in self.occupe if x[1] > quand - 600]
        self.libre_a = max(self.libre_a, debut + d)
        self.antenne += d
        self.trames += 1
        if self.rafale < 0 and self.perte:
            perdue = self.etat_brouille
            l = -self.rafale
            sortir, entrer = 1 / l, self.perte / (l * (1 - self.perte))
            if self.alea_r.random() < (sortir if self.etat_brouille else entrer):
                self.etat_brouille = not self.etat_brouille
        elif self.rafale and self.perte:
            perdue = self._brouille_a(debut + d / 2)
        else:
            perdue = self.alea.random() < self.perte
        self.perdues += perdue
        return debut + d, perdue


def protocole(donnees, utile, preset, perte, graine, parites="auto", budget=False, rafale=0.0, code="raid6",
              entrelacer=False, relances_max=None):
    """budget=True : chaque nœud respecte la discipline d'émission (protocole.Budget : 5 % sur l'heure, canal 25 %).
    rafale, code, entrelacer (17 nov. 2026) : voir Canal et protocole.Emetteur. Compte rendu en plus dans les
    attributs de la fonction : renvois (morceaux de données renvoyés), perte_vue (part des trames perdues)."""
    canal = Canal(preset, perte, graine, rafale)
    em = Emetteur(1, donnees, parites=parites, utile=utile, code=code, entrelacer=entrelacer,
                  **({} if relances_max is None else {"relances_max": relances_max}))
    rec = Recepteur()
    renvois = [0]
    manquants = em.trames_manquants

    def compter(n, masque):
        trames = manquants(n, masque)
        renvois[0] += len(trames)
        return trames
    em.trames_manquants = compter
    budgets = {"rec": Budget(), "em": Budget()} if budget else {}   # clé = destinataire, donc budget de l'expéditeur
    file_de = {"rec": 0.0, "em": 0.0}      # chaque nœud émet ses trames l'une après l'autre
    evts, n = [], 0                        # (instant, ordre, destinataire, trame)

    def poster(quand, dest, trames):
        nonlocal n
        for t in trames:
            arrivee, perdue = canal.emettre(max(quand, file_de[dest]), len(t), budgets.get(dest))
            file_de[dest] = arrivee
            if not perdue:
                n += 1
                heapq.heappush(evts, (arrivee, n, dest, t))
        if dest == "rec" and trames:
            em.emission_terminee(file_de[dest])

    poster(0.0, "rec", em.demarrer(0.0))
    maintenant = 0.0
    tours = 0
    while not (em.fini or em.echec) and maintenant < 48 * 3600:
        tours += 1
        if tours > 200000:                     # garde-fou : le protocole ne doit jamais tourner en rond
            raise RuntimeError("boucle : le protocole ne converge pas")
        prochain = evts[0][0] if evts else maintenant + 5
        # Horloges : relance de l'émetteur, bilan final du récepteur après silence
        echeance = (em.attente_depuis or 0) + em.delai
        fins = [tr["bilan_du"] for tr in rec.transferts.values() if tr["bilan_du"] is not None]
        fins += [tr["pret_a"] + rec.relance_pret for tr in rec.transferts.values()
                 if not tr["morceaux"] and not tr["par"] and tr["prets"] < 4]
        if fins and min(fins) < min(prochain, echeance):
            maintenant = max(maintenant, min(fins) + 1e-3)
            poster(maintenant, "em", rec.horloge(maintenant))
            continue
        if not evts or echeance < prochain:
            maintenant = max(maintenant, echeance + 1e-3)
            poster(maintenant, "rec", em.horloge(maintenant))
            continue
        maintenant, _, dest, t = heapq.heappop(evts)
        if dest == "rec":
            poster(maintenant, "em", rec.recevoir(t, maintenant))
        else:
            poster(maintenant, "rec", em.recevoir(t, maintenant))
    ok = rec.livres.get(1) == donnees
    protocole.parites_vues = em.parites_envoyees
    protocole.attente_budget = budgets["rec"].attentes if budget else 0.0
    protocole.renvois = renvois[0]
    protocole.perte_vue = canal.perdues / max(canal.trames, 1)
    return ok, canal.antenne, maintenant, canal.trames


def actuel(donnees, preset, perte, graine, rafale=0.0):
    """Un message Meshtastic fiable par morceau de 233 octets, l'un après l'autre."""
    canal = Canal(preset, perte, graine, rafale)
    attente = 2 * canal.duree(233) + (8 + 16 + 32) * canal.tranche + 4.5      # getRetransmissionMsec, docs/03
    t, ok = 0.0, True
    for i in range(0, len(donnees), 233):
        taille = len(donnees[i:i + 233])
        for essai in range(5):
            arrivee, perdu = canal.emettre(t, taille)
            if not perdu:
                retour, accuse_perdu = canal.emettre(arrivee, 12)
                if not accuse_perdu:
                    t = retour
                    break
            t = max(arrivee, t) + attente
        else:
            ok = False
    actuel.perte_vue = canal.perdues / max(canal.trames, 1)
    return ok, canal.antenne, t, canal.trames


def avec_budget():
    alea = random.Random(3)
    for ko in (2, 4, 10, 30, 100):
        donnees = bytes(alea.randrange(256) for _ in range(ko * 1024))
        for perte in (0.0, 0.10, 0.20):
            ligne = []
            for budget in (False, True):
                essais = [protocole(donnees, UTILE_COMPACT, "LONG_FAST", perte, g, budget=budget) for g in range(20)]
                ligne.append(f"{'budget 5 %/25 %' if budget else 'libre'} : livré {5 * sum(e[0] for e in essais)} %, "
                             f"antenne {sum(e[1] for e in essais) / 20:.0f} s, durée {sum(e[2] for e in essais) / 20:.0f} s")
            print(f"{ko:3} Ko LONG_FAST pertes {perte:.0%} | " + " | ".join(ligne), flush=True)


if __name__ == "__main__" and "--budget" in sys.argv:
    avec_budget()
elif __name__ == "__main__":
    alea = random.Random(3)
    for ko in (2, 10, 30):
        donnees = bytes(alea.randrange(256) for _ in range(ko * 1024))
        for preset in ("LONG_FAST",):
            for perte in (0.0, 0.10, 0.20):
                res = {}
                for nom, f in (("actuel", lambda g: actuel(donnees, preset, perte, g)),
                               ("compact 8+2 fixe", lambda g: protocole(donnees, UTILE_COMPACT, preset, perte, g, 2)),
                               ("officiel adaptatif", lambda g: protocole(donnees, UTILE_OFFICIEL, preset, perte, g)),
                               ("compact adaptatif", lambda g: protocole(donnees, UTILE_COMPACT, preset, perte, g))):
                    essais = [f(g) for g in range(20)]
                    res[nom] = (sum(e[0] for e in essais) / 20, sum(e[1] for e in essais) / 20,
                                sum(e[2] for e in essais) / 20, sum(e[3] for e in essais) / 20)
                print(f"{ko:2} Ko {preset:10} pertes {perte:.0%} | " + " | ".join(
                    f"{nom} : livré {100 * r[0]:.0f} %, antenne {r[1]:.0f} s, durée {r[2]:.0f} s, {r[3]:.0f} trames"
                    for nom, r in res.items()))
