# Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
"""Protocole de transfert de contenus volumineux (docs/07 : P1, P9, P10) — prototype côté client.

Règles (version 7, 5 novembre 2026 ; v7 = reprise d'un contenu déjà commencé, reconnu par son empreinte ; v6 = bilan dès qu'un renvoi complète le contenu, relance à 2,5 fois
l'aller-retour, 10 relances ; v3 = renvoi des seuls morceaux manquants ; v4 = fin sur silence, délai de
relance mesuré, parité de départ selon l'en-tête ; v5 = budget d'émission (classe Budget), renvoi limité aux lots
déjà envoyés) :
- un EN-TÊTE donne toutes les infos du message (idée de l'utilisateur, P10) et attend une réponse PRÊT ;
- les MORCEAUX ne portent que 4 octets d'en-tête (type, id du transfert, numéro) ; la fin est un bit du dernier
  morceau ;
- parité façon RAID 6 (P, Q) par lot de 8, **adaptative** : 1 morceau de parité au départ, puis 0, 1 ou 2 selon le
  taux de pertes que le récepteur annonce dans ses bilans (sans perte, la parité ne coûte rien) ;
- envoi par **fenêtres** de 4 lots, deux fenêtres d'avance : chaque point d'étape du récepteur (au premier morceau de
  chaque groupe de 32) fait partir la fenêtre suivante, avec la parité ajustée ;
- le récepteur répond par un BILAN (lots jugés, morceaux reçus et attendus, carte des lots incomplets) aux points
  d'étape et à la fin ; un BILAN ne demande jamais d'accusé ; sans nouvelles, l'émetteur relance par une QUESTION ;
- **fin sur silence (v4)** : au dernier morceau, si rien ne manque, BILAN final tout de suite ; sinon, le BILAN final
  part après un court silence (2 fois l'écart **habituel** entre trames — médiane des 8 derniers —, 5 s au moins ; le
  plus grand écart, essayé d'abord, comptait les pauses entre fenêtres et ralentissait tout), dès qu'un morceau
  du dernier lot est arrivé : la parité du dernier
  lot a le temps d'arriver (en v3, le bilan partait au dernier morceau de données, avant elle, et réclamait des
  morceaux que la parité aurait reconstruits), et la perte du morceau « fin » ne bloque plus rien ;
- **délai de relance mesuré (v4)** : 4 fois l'aller-retour entre le dernier EN-TÊTE envoyé et le PRÊT, borné entre
  15 et 60 s (60 s fixes en v3) ;
- **parité de départ (v4)** : 2 s'il a fallu renvoyer l'EN-TÊTE, 1 sinon ;
- **poignée de main rapide (v4)** : avant toute mesure, l'EN-TÊTE (15 octets, une demi-seconde d'antenne) est relancé
  après 20 s et non 60 ; le récepteur renvoie PRÊT s'il ne voit aucun morceau dans les 20 s (sur le banc, trois pertes
  de suite pendant la poignée de main avaient coûté 3 minutes) ;
- pour un lot incomplet malgré la parité, le bilan dit **quels morceaux manquent** (1 octet par lot) et l'émetteur ne
  renvoie que ceux-là (version 3 : renvoyer le lot entier coûtait 2 à 3 fois trop, mesuré en simulation).

Indépendant du transport : les objets reçoivent des trames et rendent des trames à envoyer, avec une horloge en
secondes fournie par l'appelant (simulation.py, ou le relais du banc).

Trames (octets) :
  0x01 EN-TÊTE  : id(1) taille(4) nb_morceaux(2) lot(1) réservé(1) empreinte CRC32(4) taille_morceau(1)
                  [destinataire final(4), facultatif : passage par une station, v7]
  0x02 PRÊT     : id(1) premier(2) : premier lot que le récepteur n'a pas en entier (reprise, v7 ; 0 si nouveau),
                  puis 1 octet par lot entamé à partir de `premier` : morceaux qui lui manquent (0 = complet)
  0x03 MORCEAU  : id(1) numéro(2) ; bit 15 = dernier morceau ; bit 14 = parité, alors numéro = lot << 1 | (0 = P, 1 = Q)
  0x04 BILAN    : id(1) premier(2) lots_jugés(2) reçus(2) attendus(2) puis 1 octet par lot de premier à lots_jugés-1 :
                  bits des morceaux manquants (0 = complet ou reconstruit) ; les lots avant `premier` sont complets (v6)
  0x05 QUESTION : id(1)
"""
import struct, zlib
from collections import deque

from raid6 import parite, reconstruire

LOT, FENETRE, AVANCE = 8, 4, 2          # morceaux par lot, lots par fenêtre, fenêtres d'avance
# Taille maximale d'une trame (5 nov. 2026, vu sur le banc : TOO_LARGE) : entre deux nœuds qui connaissent leurs clés,
# un message direct est chiffré par clé publique (Router.cpp:1336, +12 octets, RadioInterface.h:23), et le firmware
# ajoute le champ bitfield (Router.cpp:1236). Data encodé = trame + 8 (portnum 3, longueur 3, bitfield 2) ; il faut
# trame + 8 + 16 (en-tête radio) + 12 <= 255 (Router.cpp:1337) : trame <= 219 (et non 233).
TRAME_MAX = 219
UTILE_COMPACT = TRAME_MAX - 4           # 4 octets d'en-tête de MORCEAU : type, id, numéro(2)
                                        # (230 jusqu'au 4 nov. 2026 au soir : trames de 234 octets, vu par le contrôle de taille)
UTILE_OFFICIEL = 216                    # ChunkedPayload, champs au pire (docs/05)
ENTETE, PRET, MORCEAU, BILAN, QUESTION = 1, 2, 3, 4, 5
DERNIER, PARITE = 0x8000, 0x4000
FACTEUR_RELANCE = 2.5                   # délai de relance = FACTEUR x aller-retour EN-TÊTE / PRÊT, borné à 15-60 s
                                        # (4 en v4 : 37 s sur deux sauts du banc, chaque trame de contrôle perdue coûtait cela)


def utile_pour(taille, utile=UTILE_COMPACT):
    """Taille des morceaux (10 nov. 2026, idée de l'utilisateur : « 2 moyens plutôt qu'un gros puis un petit »).
    Petit contenu (2 à LOT morceaux, un seul lot) : morceaux égaux, le reste dans les premiers (533 octets : 178, 178,
    177) ; la parité, aussi longue que le plus long morceau du lot, rapetisse d'autant (450 octets : −8 % d'antenne).
    Au-delà, `utile` : le gain disparaît (−0,7 à +0,8 % selon les arrondis de la LoRa). Même règle chez tous les
    émetteurs : l'empreinte d'une reprise compte la taille des morceaux."""
    n = -(-taille // utile)
    return -(-taille // n) if 1 < n <= LOT else utile


def decouper(donnees, utile):
    return [donnees[i:i + utile] for i in range(0, len(donnees), utile)] or [b""]


def parite_pour(pertes):
    """Nombre de morceaux de parité par lot de 8 selon le taux de pertes observé (docs/07, P9 ; outils/parite.py)."""
    if pertes is None:
        return 1
    return 0 if pertes < 0.02 else 1 if pertes < 0.07 else 2


class Emetteur:
    def __init__(self, ident, donnees, utile=UTILE_COMPACT, parites="auto", delai_relance=None, relances_max=10,
                 final=None):
        # final : numéro du destinataire final quand on passe par une station (docs/10 §4) ; ajouté à l'EN-TÊTE
        # 10 relances (6 en v4) : à 30 % de pertes par sens, un aller-retour échoue une fois sur deux et 6 échecs de
        # suite faisaient abandonner 1 transfert sur 40 alors que le récepteur répondait (simulation, 4 nov. 2026).
        utile = utile_pour(len(donnees), utile)       # `utile` : taille maximale d'un morceau
        self.id, self.donnees, self.utile, self.final = ident, donnees, utile, final
        self.fixe = None if parites == "auto" else parites
        self.morceaux = decouper(donnees, utile)
        self.lots = [self.morceaux[i:i + LOT] for i in range(0, len(self.morceaux), LOT)]
        # délai de relance : fixé par l'appelant, sinon mesuré sur l'aller-retour EN-TÊTE / PRÊT (60 s en attendant)
        self.delai_fixe, self.delai, self.relances_max = delai_relance, delai_relance or 20.0, relances_max
        self.debut, self.entete_relancee = None, False
        self.etat, self.attente_depuis, self.relances = "entete", None, 0
        self.prochain_lot, self.pertes, self.renvoye_a = 0, None, {}
        self.parites_envoyees = []          # pour le compte rendu : parité choisie lot par lot
        self.lot_de_depart = 0              # > 0 si le récepteur avait déjà le début (reprise, v7)
        self.deja = {}                      # reprise : lot -> morceaux qui manquent au récepteur (lots entamés)
        self.fini = self.echec = False

    def parites(self):
        if self.fixe is not None:
            return self.fixe
        if self.pertes is None:                       # pas encore de bilan : d'après l'échange d'en-tête
            return 2 if self.entete_relancee else 1
        return parite_pour(self.pertes)

    def trame_entete(self):
        trame = struct.pack(">BBIHBBIB", ENTETE, self.id, len(self.donnees), len(self.morceaux), LOT, 0,
                            zlib.crc32(self.donnees), self.utile)
        return trame + (struct.pack(">I", self.final) if self.final is not None else b"")

    def trames_lot(self, n):
        lot, trames, k_par = self.lots[n], [], self.parites()
        for k, m in enumerate(lot):
            num = n * LOT + k
            trames.append(struct.pack(">BBH", MORCEAU, self.id, num | (DERNIER if num == len(self.morceaux) - 1 else 0)) + m)
        if k_par and len(lot) > 1:
            p, q = parite(lot)
            for j, x in enumerate((p, q)[:k_par]):
                trames.append(struct.pack(">BBH", MORCEAU, self.id, PARITE | (n << 1) | j) + x)
        self.parites_envoyees.append(k_par)
        return trames

    def fenetre(self):
        sortie, lots = [], 0
        while lots < FENETRE and self.prochain_lot < len(self.lots):
            n = self.prochain_lot
            self.prochain_lot += 1
            if n in self.deja:                         # reprise : le récepteur a déjà une partie de ce lot (v7)
                if self.deja[n]:                       # 0 = lot complet chez lui : rien à envoyer, ne compte pas
                    sortie += self.trames_manquants(n, self.deja[n])
                    lots += 1
                continue
            sortie += self.trames_lot(n)
            lots += 1
        return sortie

    def demarrer(self, maintenant):
        self.attente_depuis = self.debut = maintenant
        return [self.trame_entete()]

    def emission_terminee(self, instant):
        """Le transport signale que nos trames sont réellement parties : l'attente d'une réponse commence là."""
        if self.attente_depuis is not None:
            self.attente_depuis = max(self.attente_depuis, instant)

    def recevoir(self, trame, maintenant):
        t = trame[0]
        if t == PRET and self.etat == "entete":
            if self.delai_fixe is None:
                # mesuré depuis le DERNIER en-tête envoyé (depuis le premier, un en-tête perdu gonflait le délai à 240 s)
                self.delai = min(60.0, max(15.0, FACTEUR_RELANCE * (maintenant - self.debut)))
            self.etat, self.relances, self.attente_depuis = "envoi", 0, maintenant
            # Reprise (v7) : le PRÊT dit à partir de quel lot le récepteur n'a plus tout (contenu déjà commencé avec un
            # autre émetteur ou un autre transfert, reconnu par son empreinte) ; les lots d'avant ne partent pas.
            if len(trame) >= 4:
                self.prochain_lot = min(struct.unpack(">H", trame[2:4])[0], len(self.lots))
                # puis, pour les lots suivants entamés chez lui, les morceaux qui lui manquent (1 octet par lot)
                self.deja = {self.prochain_lot + k: m for k, m in enumerate(trame[4:])}
            self.lot_de_depart = self.prochain_lot
            sortie = []
            for _ in range(AVANCE):
                sortie += self.fenetre()
            return sortie
        if t == BILAN and self.etat == "envoi":
            premier, juges, recus, attendus = struct.unpack(">HHHH", trame[2:10])
            masques = trame[10:10 + juges - premier]       # lots premier..juges-1 ; ceux d'avant sont complets (v6)
            if attendus:
                self.pertes = 1 - recus / attendus
            self.relances, self.attente_depuis = 0, maintenant
            if juges == len(self.lots) and premier == juges:
                self.fini = True
                return []
            # Seulement les lots DÉJÀ envoyés : un bilan complet (réponse à une QUESTION) juge aussi les lots pas encore
            # partis, tous « manquants » ; les renvoyer les faisait partir deux fois (100 Ko : 2 fois l'antenne, v5).
            incomplets = [premier + k for k, m in enumerate(masques) if m and premier + k < self.prochain_lot]
            sortie = []
            for n in incomplets:
                if maintenant - self.renvoye_a.get(n, -1e9) < self.delai:
                    continue                           # déjà renvoyé récemment, sans doute encore en route
                self.renvoye_a[n] = maintenant
                sortie += self.trames_manquants(n, masques[n - premier])
            return sortie + self.fenetre()
        return []                                     # trame en double ou hors d'état (ex. PRÊT renvoyé) : ignorée

    def trames_manquants(self, n, masque):
        """Seulement les morceaux de données que le récepteur n'a pas (et qu'il n'a pas pu reconstruire)."""
        sortie = []
        for k, m in enumerate(self.lots[n]):
            if masque >> k & 1:
                num = n * LOT + k
                sortie.append(struct.pack(">BBH", MORCEAU, self.id,
                                          num | (DERNIER if num == len(self.morceaux) - 1 else 0)) + m)
        return sortie

    def horloge(self, maintenant):
        """À appeler régulièrement : relance si aucune nouvelle depuis `delai`."""
        if self.fini or self.echec or self.attente_depuis is None:
            return []
        if maintenant - self.attente_depuis < self.delai - 1e-6:
            return []
        self.relances += 1
        self.attente_depuis = maintenant
        if self.relances > self.relances_max:
            self.echec = True
            return []
        if self.etat == "entete":
            self.entete_relancee, self.debut = True, maintenant
            return [self.trame_entete()]
        if self.prochain_lot < len(self.lots):        # bilan perdu : on avance quand même d'une fenêtre
            # QUESTION APRÈS la fenêtre (v7) : posée avant, le récepteur répondait avant d'avoir reçu la fenêtre,
            # la déclarait manquante, et l'émetteur la renvoyait en double (vu par test_reprise, 5 nov. 2026).
            return self.fenetre() + [struct.pack(">BB", QUESTION, self.id)]
        return [struct.pack(">BB", QUESTION, self.id)]


class Recepteur:
    def __init__(self, silence_min=5.0, relance_pret=20.0, taille_max=TRAME_MAX, accepter=None):
        self.transferts, self.livres, self.silence_min, self.relance_pret = {}, {}, silence_min, relance_pret
        # accepter(taille) -> bool : la station a-t-elle la place ? Sinon pas de PRÊT, l'émetteur relancera plus tard.
        self.accepter = accepter
        self.finals = {}                            # id -> destinataire final annoncé dans l'EN-TÊTE (ou None)
        self.lots_par_bilan = taille_max - 10       # 10 octets d'en-tête de BILAN, puis 1 octet par lot décrit
        self.livres_par_empreinte = {}              # (crc, taille, utile) -> contenu déjà livré (reprise, v7)

    def horloge(self, maintenant):
        """À appeler régulièrement : envoie le BILAN final après un silence, une fois le dernier lot entamé."""
        sortie = []
        for ident, tr in self.transferts.items():
            # PRÊT perdu ? aucun morceau depuis : on le renvoie (3 fois au plus)
            if not tr["actif"] and tr["prets"] < 4 and maintenant - tr["pret_a"] >= self.relance_pret:
                tr["pret_a"], tr["prets"] = maintenant, tr["prets"] + 1
                sortie.append(self.pret(ident))
            if tr["bilan_du"] is not None and maintenant >= tr["bilan_du"]:
                tr["bilan_du"] = None
                sortie += self.bilan(ident, tout=True)
        return sortie

    def noter_arrivee(self, tr, maintenant, dans_dernier_lot):
        if tr["derniere"] is not None:
            tr["ecarts"] = (tr["ecarts"] + [maintenant - tr["derniere"]])[-8:]
        tr["derniere"] = maintenant
        if dans_dernier_lot or tr["bilan_du"] is not None:
            habituel = sorted(tr["ecarts"])[len(tr["ecarts"]) // 2] if tr["ecarts"] else 0.0
            tr["bilan_du"] = maintenant + max(self.silence_min, 2 * habituel)

    def adopter(self, autres, trame):
        """Reprise d'une station à l'autre (5 nov. 2026) : un récepteur par émetteur, mais U2 qui passe de R1 à R2 doit
        retrouver chez R2 ce qu'il a déjà reçu de R1. Avant de traiter l'EN-TÊTE `trame`, on reprend aux récepteurs
        `autres` un transfert inachevé du même contenu (même empreinte) ; recevoir() le reconnaît ensuite."""
        if not trame or trame[0] != ENTETE or len(trame) < 15:
            return False
        _, _, taille, _, _, _, crc, utile = struct.unpack(">BBIHBBIB", trame[:15])
        empreinte = (crc, taille, utile)
        if any(x["empreinte"] == empreinte for x in self.transferts.values()) or empreinte in self.livres_par_empreinte:
            return False
        for autre in autres:
            for k, x in list(autre.transferts.items()):
                if x["empreinte"] == empreinte and empreinte not in autre.livres_par_empreinte:
                    self.transferts[("repris", id(autre), k)] = autre.transferts.pop(k)
                    return True
        return False

    def recevoir(self, trame, maintenant):
        t, ident = trame[0], trame[1]
        if t == ENTETE:
            _, _, taille, nb, lot, _, crc, utile = struct.unpack(">BBIHBBIB", trame[:15])
            empreinte = (crc, taille, utile)
            self.finals[ident] = struct.unpack(">I", trame[15:19])[0] if len(trame) >= 19 else None
            if self.accepter is not None and empreinte not in self.livres_par_empreinte and \
                    not any(x["empreinte"] == empreinte for x in self.transferts.values()) and not self.accepter(taille):
                return []                                 # pas la place : silence, l'émetteur relancera
            tr = self.transferts.get(ident)
            if tr is None or tr["empreinte"] != empreinte:
                self.livres.pop(ident, None)                  # id réutilisé pour un autre contenu : nouveau transfert
                # Reprise (v7) : même contenu déjà commencé sous un autre id (autre émetteur, transfert interrompu) ?
                ancien = next((k for k, x in self.transferts.items() if x["empreinte"] == empreinte), None)
                if ancien is not None:
                    tr = self.transferts.pop(ancien)
                    tr["bilan_du"] = None       # fin_vue gardé : le dernier morceau reçu avant ne sera pas renvoyé
                else:
                    tr = {"taille": taille, "nb": nb, "lot": lot, "crc": crc, "utile": utile, "empreinte": empreinte,
                          "morceaux": {}, "bruts": set(), "par": {}, "fin_vue": False, "plus_haut": -1,
                          "derniere": None, "ecarts": [], "bilan_du": None, "complets": set(), "prets": 0}
                self.transferts[ident] = tr
            tr["pret_a"], tr["prets"], tr["actif"] = maintenant, tr["prets"] + 1, False
            if empreinte in self.livres_par_empreinte:        # déjà tout reçu : rien à envoyer, bilan final direct
                self.livres[ident] = self.livres_par_empreinte[empreinte]
                tr["complets"] = set(range(-(-nb // lot)))
                tr["morceaux"] = {i: b"" for i in range(nb)}  # inutile de garder les octets : déjà livré
                return [self.pret(ident), self.bilan_vide_final(ident)]
            return [self.pret(ident)]
        tr = self.transferts.get(ident)
        if tr is None:
            return []
        if t == MORCEAU:
            tr["actif"] = True
            num = struct.unpack(">H", trame[2:4])[0]
            dernier_lot = -(-tr["nb"] // tr["lot"]) - 1
            if num & PARITE and not num & DERNIER:
                n = (num & 0x3FFF) >> 1
                tr["par"][n, num & 1] = trame[4:]
                self.noter_arrivee(tr, maintenant, n == dernier_lot)
                return []
            i = num & 0x7FFF
            # Après le dernier morceau, tout morceau (renvoi) relance l'attente du bilan final (v6) : sinon le récepteur
            # se taisait une fois complet et l'émetteur attendait son délai de relance (2 min perdues sur le banc).
            self.noter_arrivee(tr, maintenant, i // tr["lot"] == dernier_lot or tr["fin_vue"])
            nouveau = i not in tr["bruts"]
            tr["bruts"].add(i)
            tr["morceaux"][i] = trame[4:]
            tr["plus_haut"] = max(tr["plus_haut"], i)
            if num & DERNIER or (tr["fin_vue"] and nouveau):
                tr["fin_vue"] = True
                if len(tr["morceaux"]) == tr["nb"]:    # rien ne manque : bilan final tout de suite
                    tr["bilan_du"] = None
                    return self.bilan(ident)
                # sinon le BILAN final partira après le silence (horloge), la parité ayant pu arriver
            # Point d'étape au premier morceau nouveau de chaque groupe de 32 : les lots d'avant et leur parité sont
            # passés. Seulement sur un morceau nouveau : un renvoi ne doit pas relancer de point d'étape (boucle
            # point d'étape -> renvoi -> point d'étape, vue en simulation le 4 nov. 2026).
            if nouveau and i % (LOT * FENETRE) == 0 and i:
                return self.bilan(ident)
            return []
        if t == QUESTION:
            return self.bilan(ident, tout=True)
        return []

    def lot_complet(self, tr, n):
        debut, fin = n * tr["lot"], min((n + 1) * tr["lot"], tr["nb"])
        recus = {i - debut: tr["morceaux"][i] for i in range(debut, fin) if i in tr["morceaux"]}
        if len(recus) == fin - debut:
            return True
        longueurs = {i - debut: (tr["taille"] - i * tr["utile"] if i == tr["nb"] - 1 else tr["utile"])
                     for i in range(debut, fin)}
        try:
            complet = reconstruire(recus, fin - debut, tr["par"].get((n, 0)), tr["par"].get((n, 1)), longueurs)
        except ValueError:
            return False
        for k, m in enumerate(complet):
            tr["morceaux"][debut + k] = m
        return True

    def premier_incomplet(self, tr):
        total_lots = -(-tr["nb"] // tr["lot"])
        n = 0
        while n < total_lots and (n in tr["complets"] or self.lot_complet(tr, n)):
            tr["complets"].add(n)
            n += 1
        return n

    def pret(self, ident):
        """PRÊT (v7) : id, le premier lot que le récepteur n'a pas en entier (0 pour un contenu nouveau), puis pour ce
        lot et les suivants déjà entamés, 1 octet des morceaux qui manquent (0 = lot complet, reconstruit compris)."""
        tr = self.transferts[ident]
        premier = self.premier_incomplet(tr)
        dernier_entame = max(tr["bruts"]) // tr["lot"] if tr["bruts"] else -1
        masques = bytearray()
        for n in range(premier, min(dernier_entame + 1, premier + TRAME_MAX - 4)):
            if n in tr["complets"] or self.lot_complet(tr, n):
                tr["complets"].add(n)
                masques.append(0)
            else:
                debut, fin = n * tr["lot"], min((n + 1) * tr["lot"], tr["nb"])
                masques.append(sum(1 << (i - debut) for i in range(debut, fin) if i not in tr["morceaux"]))
        return struct.pack(">BBH", PRET, ident, premier) + bytes(masques)

    def bilan_vide_final(self, ident):
        total_lots = -(-self.transferts[ident]["nb"] // self.transferts[ident]["lot"])
        nb = self.transferts[ident]["nb"]
        return struct.pack(">BBHHHH", BILAN, ident, total_lots, total_lots, nb, nb)

    def bilan(self, ident, tout=False):
        """BILAN (v6) : lots 0..premier-1 complets ; un octet de manquants pour chaque lot premier..juges-1.
        Au plus `lots_par_bilan` lots décrits (209 dans 219 octets) : au-delà, le bilan juge moins de lots et les
        suivants seront décrits au bilan d'après (avant v6 : un octet par lot depuis 0, limite d'environ 400 Ko)."""
        tr = self.transferts[ident]
        total_lots = -(-tr["nb"] // tr["lot"])
        juges = total_lots if (tout or tr["fin_vue"]) else max(tr["plus_haut"], 0) // tr["lot"]
        premier = 0
        while premier < juges and (premier in tr["complets"] or self.lot_complet(tr, premier)):
            tr["complets"].add(premier)
            premier += 1
        juges = min(juges, premier + self.lots_par_bilan)
        carte = bytearray(juges - premier)
        for n in range(premier, juges):
            if n in tr["complets"] or self.lot_complet(tr, n):
                tr["complets"].add(n)
            else:
                debut, fin = n * tr["lot"], min((n + 1) * tr["lot"], tr["nb"])
                carte[n - premier] = sum(1 << (i - debut) for i in range(debut, fin) if i not in tr["morceaux"])
        attendus = min(juges * tr["lot"], tr["nb"])
        recus = sum(1 for i in tr["bruts"] if i < attendus)
        if juges == total_lots and premier == juges and ident not in self.livres:
            contenu = b"".join(tr["morceaux"][i] for i in range(tr["nb"]))[:tr["taille"]]
            if zlib.crc32(contenu) == tr["crc"]:
                self.livres[ident] = contenu
                self.livres_par_empreinte[tr["empreinte"]] = contenu
            else:                                    # empreinte fausse : tout redemander (ne devrait pas arriver)
                tr["complets"].clear()
                premier, juges = 0, min(total_lots, self.lots_par_bilan)
                carte = bytearray(b"\xff" * juges)
        return [struct.pack(">BBHHHH", BILAN, ident, premier, juges, recus, attendus) + bytes(carte)]


class Budget:
    """Discipline d'émission d'UN appareil (chaque radio a son budget : lecture de la loi, docs/06 et docs/07).

    Mêmes règles que les modules polis du firmware (docs/02 ; `airtime.h:231-232`, `airtime.cpp:304-331`) :
    - **5 % d'émission sur l'heure glissante** (moitié de la limite de 10 % d'EU_868 : l'autre moitié reste aux
      messages ordinaires, que le firmware ne bloque qu'à 10 %) ;
    - **canal sous 25 %** : nos propres trames n'occupent jamais plus de 25 % du temps (après une trame de durée d,
      silence de 3 d : un rythme régulier plutôt que des rafales de 15 s suivies de 45 s de silence, qui feraient
      croire au récepteur que l'émission est finie) ; et si l'appareil signale un canal occupé à 25 % ou plus
      (télémétrie DeviceMetrics, envoyée au client chaque minute : `DeviceTelemetry.h:43`), on se tait jusqu'à la
      mesure suivante. Notre propre part de la dernière minute est retirée de la mesure (banc, 5 nov. 2026 : deux
      appareils qui échangent voyaient chacun le canal chargé par l'autre ET par eux-mêmes, et se taisaient ensemble
      une minute sur deux) ; une trame urgente (réponse de récepteur, quelques octets) n'attend pas cette mesure :
      elle débloque l'autre côté et reste comptée dans l'heure et l'espacement.
    Le transport demande `quand(instant, durée)` avant chaque trame, puis `noter(début, durée)` à l'émission.
    """

    def __init__(self, part_heure=0.05, part_canal=0.25, heure=3600.0, mesure=60.0):
        self.part_heure, self.part_canal, self.heure, self.mesure = part_heure, part_canal, heure, mesure
        self.journal = deque()                 # (début, durée) de nos trames sur l'heure écoulée
        self.fin_derniere, self.duree_derniere = -1e9, 0.0
        self.signale = None                     # (instant, canal %, émission %) de la dernière télémétrie
        self.attentes = 0.0                     # pour le compte rendu : temps passé à attendre le budget

    def depense(self, t):
        """Secondes d'émission comptées dans l'heure qui précède t."""
        return sum(min(d, max(0.0, debut + d - (t - self.heure))) for debut, d in self.journal)

    def propre(self, debut, fin):
        """Secondes de nos trames entre debut et fin."""
        return sum(max(0.0, min(fin, d + l) - max(debut, d)) for d, l in self.journal)

    def quand(self, instant, duree, urgent=False):
        """Premier instant >= `instant` où une trame de `duree` secondes respecte le budget."""
        t = max(instant, self.fin_derniere + self.duree_derniere * (1 / self.part_canal - 1))
        if self.signale and not urgent:
            vu, canal, emission = self.signale
            autres = canal - 100 * self.propre(vu - self.mesure, vu) / self.mesure
            if (autres >= 100 * self.part_canal or emission >= 100 * self.part_heure) and t < vu + self.mesure:
                t = vu + self.mesure            # canal chargé ou budget du boîtier entamé : attendre la mesure suivante
        plafond = self.part_heure * self.heure
        for debut, d in self.journal:           # du plus ancien au plus récent : attendre qu'ils sortent de l'heure
            if self.depense(t) + duree <= plafond:
                break
            t = max(t, debut + d + self.heure)
        self.attentes += t - instant
        return t

    def noter(self, debut, duree):
        self.journal.append((debut, duree))
        self.fin_derniere, self.duree_derniere = debut + duree, duree
        while self.journal and self.journal[0][0] + self.journal[0][1] < debut - self.heure:
            self.journal.popleft()

    def signaler(self, instant, canal_pct, emission_pct):
        """Télémétrie de l'appareil (DeviceMetrics.channel_utilization et air_util_tx, en %)."""
        self.signale = (instant, canal_pct, emission_pct)
