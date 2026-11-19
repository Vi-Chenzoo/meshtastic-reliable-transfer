"""Décodage du journal radio du firmware d'ESSAI v4 (heltec-v4-projet-essai) : enregistrements, en-tête, morceaux.

Format : firmware-projet/src/modules/station/RafaleEssaiLogique.h, namespace journal ; le même vecteur d'or est vérifié des deux côtés
(firmware-projet/test/test_rafale_essai, outils/tests/test_journal_radio.py).
Copyright (C) 2026 SoCodeIA et Vincent PERRIN — GPL v3.
"""
import struct

ENREG = 16
PAR_MORCEAU = 13
ENTETE_OCTETS = 33
VERSION = 1

EV_ENFILE, EV_ATTENTE, EV_TX_DEBUT, EV_TX_FIN, EV_RX, EV_ISR_TX, EV_ISR_RX = 1, 2, 3, 4, 5, 16, 17
EV_CAD = 7       # v8 : balayage du canal avant émission terminé ; info bit 0 = occupé, bit 1 = balayage de lecture (maintien du préambule levé), bit 2 = maintien du préambule actif AVANT, bit 3 = réception armée AVANT ; id = paquet, aux = durée en µs, t = FIN du balayage
EV_BONJOUR = 8   # v8 : bonjour ESP-NOW ; info : bit 0 émis, bit 1 signature valide, bit 2 voisin nouveau, bit 3 réponse de rencontre programmée, bit 4 refusée ; x = durée en 0,1 ms ; id = compteur ; aux = voisin
EV_REGLAGE = 6   # réglage d'essai reçu du client (info = lettre de l'ordre, x = valeur) : 'W' = supplément de fenêtre de contention
NOMS = {EV_CAD: "CAD", EV_BONJOUR: "BONJOUR", EV_REGLAGE: "REGLAGE", EV_ENFILE: "ENFILE", EV_ATTENTE: "ATTENTE", EV_TX_DEBUT: "TX_DEBUT", EV_TX_FIN: "TX_FIN", EV_RX: "RX",
        EV_ISR_TX: "ISR_TX", EV_ISR_RX: "ISR_RX"}
CAUSE_RECEPTION, CAUSE_CANAL_OCCUPE, CAUSE_REPORT_MODULE, CAUSE_EMISSION = 1, 2, 4, 5
CAUSES = {CAUSE_RECEPTION: "radio en réception", CAUSE_CANAL_OCCUPE: "canal occupé (CAD)", CAUSE_REPORT_MODULE: "report demandé par un module",
          CAUSE_EMISSION: "émission en cours"}
PRESETS = {0: "LONG_FAST", 1: "LONG_SLOW", 2: "VERY_LONG_SLOW", 3: "MEDIUM_SLOW", 4: "MEDIUM_FAST", 5: "SHORT_SLOW", 6: "SHORT_FAST",
           7: "LONG_MODERATE", 8: "SHORT_TURBO", 9: "LONG_TURBO", 10: "LITE_FAST", 11: "LITE_SLOW", 12: "NARROW_FAST",
           13: "NARROW_SLOW"}  # firmware-projet/protobufs/meshtastic/config.proto, enum ModemPreset


def decoder_enreg(b):
    """16 octets -> dict(type, info, x, id, t, aux) (grand-boutiste)."""
    type_, info, x, id_, t, aux = struct.unpack(">BBHIII", bytes(b[:ENREG]))
    return {"type": type_, "info": info, "x": x, "id": id_, "t": t, "aux": aux}


def encoder_enreg(e):
    return struct.pack(">BBHIII", e["type"], e["info"], e["x"], e["id"], e["t"], e["aux"])


def decoder_morceau(b):
    """Réponse 'J' (sans ORDRE ni 'J') -> (anneau, decalage, total, [enregistrements])."""
    anneau, decalage, total = struct.unpack(">BHH", bytes(b[:5]))
    corps = bytes(b[5:])
    return anneau, decalage, total, [decoder_enreg(corps[i:i + ENREG]) for i in range(0, len(corps) - ENREG + 1, ENREG)]


def decoder_entete(b):
    """Réponse 'H' (sans ORDRE ni 'H') -> dict."""
    if len(b) < ENTETE_OCTETS:
        raise ValueError(f"en-tête trop court : {len(b)} octets")
    v, sf, cr, region, preset, bw, pre, cap_l, cap_i, ec_l, ec_i, ms, hi, lo = struct.unpack(">BBBBBHHHHIIIII", bytes(b[:ENTETE_OCTETS]))
    return {"version": v, "sf": sf, "cr": cr, "region": region, "preset": preset, "bw_khz": bw / 10.0, "preambule": pre,
            "cap_logiciel": cap_l, "cap_isr": cap_i, "ecrits_logiciel": ec_l, "ecrits_isr": ec_i, "millis_ms": ms,
            "horloge_us": (hi << 32) | lo}


def encoder_entete(h):
    """Pour les tests : l'inverse de decoder_entete."""
    return struct.pack(">BBBBBHHHHIIIII", h.get("version", VERSION), h["sf"], h["cr"], h.get("region", 0), h.get("preset", 0),
                       int(round(h["bw_khz"] * 10)), h["preambule"], h["cap_logiciel"], h["cap_isr"], h["ecrits_logiciel"],
                       h["ecrits_isr"], h.get("millis_ms", 0), h["horloge_us"] >> 32, h["horloge_us"] & 0xFFFFFFFF)


def etendre_t(t32, horloge_us):
    """Instant 32 bits du boîtier (µs, boucle en 71 min) -> instant 64 bits le plus récent qui ne dépasse pas l'horloge relevée au vidage."""
    plein = (horloge_us & ~0xFFFFFFFF) + t32
    return plein - (1 << 32) if plein > horloge_us else plein
