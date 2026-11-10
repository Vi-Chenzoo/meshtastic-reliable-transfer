#!/usr/bin/env python3
# Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
"""Temps d'antenne LoRa des presets Meshtastic, et débit utile qu'on peut en attendre.

Formule de Semtech (fiches SX1261/2 et AN1200.13), avec les réglages du firmware Meshtastic :
préambule de 16 symboles (src/mesh/RadioInterface.h:112), en-tête LoRa explicite, CRC actif
(src/mesh/SX126xInterface.cpp:253), « low data rate optimization » si un symbole dure 16 ms ou plus
(règle automatique de RadioLib : supposée, non vérifiée dans le code de Meshtastic).
Presets : src/mesh/MeshRadio.h:216 (modemPresetToParams). Usage : outils/temps-antenne.py
"""
import math

PREAMBULE = 16
EN_TETE_MESHTASTIC = 16      # src/mesh/RadioInterface.h:22
PAQUET_MAX = 255             # src/mesh/RadioInterface.h:21
UTILE_MAX = 233              # protobufs/meshtastic/mesh.options:24 (Data.payload)

# nom : (largeur de bande kHz, facteur d'étalement, taux de codage 4/x) ; régions où il est permis en Europe
PRESETS = {
    "SHORT_FAST":    (250, 7, 5, "EU_868"),
    "SHORT_SLOW":    (250, 8, 5, "EU_868"),
    "MEDIUM_FAST":   (250, 9, 5, "EU_868"),
    "MEDIUM_SLOW":   (250, 10, 5, "EU_868"),
    "LONG_FAST":     (250, 11, 5, "EU_868 (par défaut)"),
    "LONG_MODERATE": (125, 11, 8, "EU_868"),
    "LONG_SLOW":     (125, 12, 8, "EU_868"),
    "LITE_FAST":     (125, 9, 5, "EU_866"),
    "LITE_SLOW":     (125, 10, 5, "EU_866"),
    "NARROW_FAST":   (62.5, 7, 6, "EU_N_868"),
    "NARROW_SLOW":   (62.5, 8, 6, "EU_N_868"),
    "SHORT_TURBO":   (500, 7, 5, "hors Europe (500 kHz)"),
}


def temps_ms(octets, bw, sf, cr):
    """Durée d'émission d'une trame LoRa de `octets` octets, en millisecondes."""
    t_sym = (2 ** sf) / bw                       # ms (bw en kHz)
    ldro = 1 if t_sym >= 16 else 0
    n = 8 + max(math.ceil((8 * octets - 4 * sf + 28 + 16) / (4 * (sf - 2 * ldro))) * cr, 0)
    return (PREAMBULE + 4.25) * t_sym + n * t_sym


if __name__ == "__main__":
    print("preset | région | débit brut | trame pleine 255 o | paquet court 40 o | utile/s (1 saut, sans attente) | "
          "Ko utiles par heure à 10 % | Ko utiles par heure à 2,5 %")
    for nom, (bw, sf, cr, region) in PRESETS.items():
        brut = sf * (bw * 1000 / 2 ** sf) * 4 / cr          # bits/s
        plein = temps_ms(PAQUET_MAX, bw, sf, cr)
        court = temps_ms(40, bw, sf, cr)
        utile_s = UTILE_MAX / (plein / 1000)
        par_heure = lambda part: 3600 * part / (plein / 1000) * UTILE_MAX / 1024
        print(f"{nom} | {region} | {brut / 1000:.2f} kbit/s | {plein:.0f} ms | {court:.0f} ms | {utile_s:.0f} o/s | "
              f"{par_heure(0.10):.0f} Ko | {par_heure(0.025):.0f} Ko")
