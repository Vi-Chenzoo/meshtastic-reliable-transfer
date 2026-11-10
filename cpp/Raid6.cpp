// Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
// C++ port of prototype/protocole.py, written for the Meshtastic firmware (comments in French).
#include "Raid6.h"
#include <algorithm>

namespace station
{
namespace raid6
{
namespace
{
struct Tables {
    uint8_t exp[512];
    uint8_t log[256];
    Tables()
    {
        unsigned x = 1;
        for (unsigned i = 0; i < 255; i++) {
            exp[i] = x;
            log[x] = i;
            x <<= 1;
            if (x & 0x100)
                x ^= 0x11D;
        }
        for (unsigned i = 255; i < 512; i++)
            exp[i] = exp[i - 255];
        log[0] = 0;
    }
};
const Tables &tables()
{
    static const Tables t;
    return t;
}
} // namespace

uint8_t exp(unsigned i)
{
    return tables().exp[i % 255];
}

uint8_t mul(uint8_t a, uint8_t b)
{
    if (a == 0 || b == 0)
        return 0;
    const Tables &t = tables();
    return t.exp[t.log[a] + t.log[b]];
}

uint8_t div(uint8_t a, uint8_t b)
{
    if (a == 0)
        return 0;
    const Tables &t = tables();
    return t.exp[(t.log[a] + 255 - t.log[b]) % 255];
}

void parite(const std::vector<Octets> &morceaux, Octets &p, Octets &q)
{
    size_t n = 0;
    for (const Octets &m : morceaux)
        n = std::max(n, m.size());
    p.assign(n, 0);
    q.assign(n, 0);
    for (size_t i = 0; i < morceaux.size(); i++) {
        uint8_t g = exp(i);
        const Octets &m = morceaux[i];
        for (size_t j = 0; j < m.size(); j++) { // le remplissage (zéros) ne change ni P ni Q
            p[j] ^= m[j];
            q[j] ^= mul(g, m[j]);
        }
    }
}

namespace
{
Octets complete(const Octets &m, size_t taille)
{
    Octets x(m);
    x.resize(taille, 0);
    return x;
}
} // namespace

bool reconstruire(const std::map<unsigned, Octets> &recus, unsigned nb, const Octets *p, const Octets *q,
                  const std::map<unsigned, size_t> &longueurs, std::vector<Octets> &sortie)
{
    std::vector<unsigned> manquants;
    for (unsigned i = 0; i < nb; i++)
        if (!recus.count(i))
            manquants.push_back(i);
    sortie.clear();
    if (manquants.empty()) {
        for (unsigned i = 0; i < nb; i++)
            sortie.push_back(recus.at(i)); // comme le prototype : morceaux rendus tels quels
        return true;
    }
    size_t taille = 0;
    bool unePartie = false;
    for (const auto &r : recus) {
        taille = std::max(taille, r.second.size());
        unePartie = true;
    }
    for (const Octets *x : {p, q})
        if (x) {
            taille = std::max(taille, x->size());
            unePartie = true;
        }
    if (!unePartie)
        return false; // rien du tout (le prototype lève ValueError)
    std::map<unsigned, Octets> d;
    for (const auto &r : recus)
        d[r.first] = complete(r.second, taille);
    if (manquants.size() == 1 && p) { // un seul trou : P suffit (RAID 5)
        Octets x = complete(*p, taille);
        for (const auto &m : d)
            for (size_t j = 0; j < taille; j++)
                x[j] ^= m.second[j];
        d[manquants[0]] = x;
    } else if (manquants.size() == 1 && q) { // un seul trou, P perdue : Q suffit
        unsigned a = manquants[0];
        Octets x = complete(*q, taille);
        for (const auto &m : d)
            for (size_t j = 0; j < taille; j++)
                x[j] ^= mul(exp(m.first), m.second[j]);
        for (size_t j = 0; j < taille; j++)
            x[j] = div(x[j], exp(a));
        d[a] = x;
    } else if (manquants.size() == 2 && p && q) { // deux trous : P et Q (RAID 6)
        unsigned a = manquants[0], b = manquants[1];
        Octets pxy = complete(*p, taille), qxy = complete(*q, taille);
        for (const auto &m : d)
            for (size_t j = 0; j < taille; j++) {
                pxy[j] ^= m.second[j];
                qxy[j] ^= mul(exp(m.first), m.second[j]);
            }
        // Da·g^a ⊕ Db·g^b = qxy ; Da ⊕ Db = pxy  =>  Da = (qxy ⊕ g^b·pxy) / (g^a ⊕ g^b)
        uint8_t den = exp(a) ^ exp(b);
        Octets da(taille), db(taille);
        for (size_t j = 0; j < taille; j++) {
            da[j] = div(qxy[j] ^ mul(exp(b), pxy[j]), den);
            db[j] = pxy[j] ^ da[j];
        }
        d[a] = da;
        d[b] = db;
    } else {
        return false;
    }
    for (unsigned i = 0; i < nb; i++) {
        Octets m = d[i];
        auto l = longueurs.find(i);
        if (l != longueurs.end() && l->second < m.size())
            m.resize(l->second);
        sortie.push_back(m);
    }
    return true;
}
} // namespace raid6
} // namespace station
