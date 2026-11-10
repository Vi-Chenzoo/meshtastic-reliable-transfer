// Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
// C++ port of prototype/protocole.py, written for the Meshtastic firmware (comments in French).
//
// Parité façon RAID 6 d'un lot de morceaux : P (ou exclusif) et Q (GF(2^8), polynôme 0x11D, générateur 2), comme le
// RAID 6 de Linux md. Portage octet pour octet de prototype/raid6.py du projet : morceaux de longueurs inégales
// complétés par des zéros ; jusqu'à deux morceaux perdus reconstruits.
#pragma once
#include <cstdint>
#include <map>
#include <vector>

namespace station
{
using Octets = std::vector<uint8_t>;

namespace raid6
{
uint8_t mul(uint8_t a, uint8_t b);
uint8_t div(uint8_t a, uint8_t b); // b != 0
uint8_t exp(unsigned i);           // g^i

/// Morceaux de données d'un lot -> P et Q (longueur du plus long morceau).
void parite(const std::vector<Octets> &morceaux, Octets &p, Octets &q);

/// recus : {indice: morceau} d'un lot de nb morceaux ; p, q : parités reçues (nullptr si absentes) ; longueurs :
/// longueur réelle de chaque morceau (le remplissage des morceaux reconstruits est retiré), absente = tout garder.
/// Rend false si la parité ne suffit pas ; sinon `sortie` reçoit les nb morceaux.
bool reconstruire(const std::map<unsigned, Octets> &recus, unsigned nb, const Octets *p, const Octets *q,
                  const std::map<unsigned, size_t> &longueurs, std::vector<Octets> &sortie);
} // namespace raid6
} // namespace station
