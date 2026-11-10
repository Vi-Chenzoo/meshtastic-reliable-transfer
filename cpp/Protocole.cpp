// Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
// C++ port of prototype/protocole.py, written for the Meshtastic firmware (comments in French).
// Portage de prototype/protocole.py (version 7) : mêmes noms, mêmes décisions, dans le même ordre ; les commentaires
// du prototype expliquent chaque règle.
#include "Protocole.h"
#include <algorithm>
#include <cmath>

namespace station
{
namespace
{
void mettre16(Octets &o, uint16_t v)
{
    o.push_back(v >> 8);
    o.push_back(v & 0xFF);
}
void mettre32(Octets &o, uint32_t v)
{
    for (int s = 24; s >= 0; s -= 8)
        o.push_back((v >> s) & 0xFF);
}
uint16_t lire16(const Octets &o, size_t i)
{
    return (uint16_t(o[i]) << 8) | o[i + 1];
}
uint32_t lire32(const Octets &o, size_t i)
{
    return (uint32_t(o[i]) << 24) | (uint32_t(o[i + 1]) << 16) | (uint32_t(o[i + 2]) << 8) | o[i + 3];
}
Trames &ajouter(Trames &a, Trames &&b)
{
    for (auto &x : b)
        a.push_back(std::move(x));
    return a;
}
unsigned lotsDe(unsigned nb, unsigned lot)
{
    return (nb + lot - 1) / lot;
}
} // namespace

uint32_t crc32(const uint8_t *donnees, size_t n, uint32_t crc)
{
    static uint32_t table[256];
    static bool prete = false;
    if (!prete) {
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i;
            for (int k = 0; k < 8; k++)
                c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            table[i] = c;
        }
        prete = true;
    }
    crc = ~crc;
    for (size_t i = 0; i < n; i++)
        crc = table[(crc ^ donnees[i]) & 0xFF] ^ (crc >> 8);
    return ~crc;
}

int paritePour(bool connu, double pertes)
{
    if (!connu)
        return 1;
    return pertes < 0.02 ? 0 : pertes < 0.07 ? 1 : 2;
}

// ---------------------------------------------------------------- Emetteur

size_t utilePour(size_t taille, size_t utile)
{
    size_t n = (taille + utile - 1) / utile;
    return n > 1 && n <= LOT ? (taille + n - 1) / n : utile;
}

Emetteur::Emetteur(uint8_t id, const Octets &donnees, size_t utileMax, int parites, double delaiRelance,
                   unsigned relancesMax, bool avecFinal, uint32_t final)
    : id(id), delai(delaiRelance > 0 ? delaiRelance : 20.0), donnees(donnees), utile(utilePour(donnees.size(), utileMax)),
      avecFinal(avecFinal),
      final(final), fixe(parites), delaiFixe(delaiRelance > 0), relancesMax(relancesMax)
{
    for (size_t i = 0; i < donnees.size(); i += utile)
        morceaux.emplace_back(donnees.begin() + i, donnees.begin() + std::min(donnees.size(), i + utile));
    if (morceaux.empty())
        morceaux.emplace_back();
    for (size_t i = 0; i < morceaux.size(); i += LOT)
        lots.emplace_back(morceaux.begin() + i, morceaux.begin() + std::min(morceaux.size(), i + LOT));
}

int Emetteur::parites() const
{
    if (fixe >= 0)
        return fixe;
    if (!pertesConnues)
        return enteteRelancee ? 2 : 1;
    return paritePour(true, pertes);
}

Octets Emetteur::trameEntete() const
{
    Octets t{ENTETE, id};
    mettre32(t, donnees.size());
    mettre16(t, morceaux.size());
    t.push_back(LOT);
    t.push_back(0);
    mettre32(t, crc32(donnees));
    t.push_back(utile);
    if (avecFinal)
        mettre32(t, final);
    return t;
}

Octets Emetteur::trameMorceau(unsigned num) const
{
    Octets t{MORCEAU, id};
    mettre16(t, num | (num == morceaux.size() - 1 ? DERNIER : 0));
    const Octets &m = morceaux[num];
    t.insert(t.end(), m.begin(), m.end());
    return t;
}

Trames Emetteur::tramesLot(unsigned n)
{
    const auto &lot = lots[n];
    Trames trames;
    int kPar = parites();
    for (unsigned k = 0; k < lot.size(); k++)
        trames.push_back(trameMorceau(n * LOT + k));
    if (kPar && lot.size() > 1) {
        Octets p, q;
        raid6::parite(lot, p, q);
        const Octets *pq[2] = {&p, &q};
        for (int j = 0; j < std::min(kPar, 2); j++) {
            Octets t{MORCEAU, id};
            mettre16(t, PARITE | (n << 1) | j);
            t.insert(t.end(), pq[j]->begin(), pq[j]->end());
            trames.push_back(t);
        }
    }
    paritesEnvoyees.push_back(kPar);
    return trames;
}

Trames Emetteur::tramesManquants(unsigned n, uint8_t masque) const
{
    Trames sortie;
    for (unsigned k = 0; k < lots[n].size(); k++)
        if (masque >> k & 1)
            sortie.push_back(trameMorceau(n * LOT + k));
    return sortie;
}

Trames Emetteur::fenetre()
{
    Trames sortie;
    unsigned nLots = 0;
    while (nLots < FENETRE && prochainLot < lots.size()) {
        unsigned n = prochainLot++;
        auto d = deja.find(n);
        if (d != deja.end()) { // reprise : le récepteur a déjà une partie de ce lot
            if (d->second) {
                ajouter(sortie, tramesManquants(n, d->second));
                nLots++;
            }
            continue;
        }
        ajouter(sortie, tramesLot(n));
        nLots++;
    }
    return sortie;
}

Trames Emetteur::demarrer(double maintenant)
{
    attenteDepuis = debut = maintenant;
    enAttente = aDebut = true;
    return {trameEntete()};
}

void Emetteur::emissionTerminee(double instant)
{
    if (enAttente)
        attenteDepuis = std::max(attenteDepuis, instant);
}

Trames Emetteur::recevoir(const Octets &trame, double maintenant)
{
    if (trame.empty())
        return {};
    uint8_t t = trame[0];
    if (t == PRET && !enEnvoi) {
        if (!delaiFixe)
            delai = std::min(60.0, std::max(15.0, FACTEUR_RELANCE * (maintenant - debut)));
        enEnvoi = true;
        relances = 0;
        attenteDepuis = maintenant;
        enAttente = true;
        if (trame.size() >= 4) {
            prochainLot = std::min<unsigned>(lire16(trame, 2), lots.size());
            deja.clear();
            for (size_t k = 4; k < trame.size(); k++)
                deja[prochainLot + (k - 4)] = trame[k];
        }
        lotDeDepart = prochainLot;
        Trames sortie;
        for (unsigned a = 0; a < AVANCE; a++)
            ajouter(sortie, fenetre());
        return sortie;
    }
    if (t == BILAN && enEnvoi && trame.size() >= 10) {
        unsigned premier = lire16(trame, 2), juges = lire16(trame, 4), recus = lire16(trame, 6),
                 attendus = lire16(trame, 8);
        Octets masques;
        if (juges > premier)
            masques.assign(trame.begin() + 10, trame.begin() + std::min(trame.size(), size_t(10 + juges - premier)));
        if (attendus) {
            pertes = 1 - double(recus) / double(attendus);
            pertesConnues = true;
        }
        relances = 0;
        attenteDepuis = maintenant;
        if (juges == lots.size() && premier == juges) {
            fini = true;
            return {};
        }
        Trames sortie;
        for (size_t k = 0; k < masques.size(); k++) {
            unsigned n = premier + k;
            if (!masques[k] || n >= prochainLot) // seulement les lots déjà envoyés
                continue;
            auto r = renvoyeA.find(n);
            if (maintenant - (r != renvoyeA.end() ? r->second : -1e9) < delai)
                continue; // déjà renvoyé récemment, sans doute encore en route
            renvoyeA[n] = maintenant;
            ajouter(sortie, tramesManquants(n, masques[k]));
        }
        return ajouter(sortie, fenetre());
    }
    return {}; // trame en double ou hors d'état : ignorée
}

Trames Emetteur::horloge(double maintenant)
{
    if (fini || echec || !enAttente)
        return {};
    if (maintenant - attenteDepuis < delai - 1e-6)
        return {};
    relances++;
    attenteDepuis = maintenant;
    if (relances > relancesMax) {
        echec = true;
        return {};
    }
    if (!enEnvoi) {
        enteteRelancee = true;
        debut = maintenant;
        return {trameEntete()};
    }
    Octets question{QUESTION, id};
    if (prochainLot < lots.size()) { // bilan perdu : on avance quand même d'une fenêtre, QUESTION après
        Trames sortie = fenetre();
        sortie.push_back(question);
        return sortie;
    }
    return {question};
}

// ---------------------------------------------------------------- Recepteur

Recepteur::Recepteur(double silenceMin, double relancePret, size_t tailleMax, std::function<bool(uint32_t)> accepter)
    : silenceMin(silenceMin), relancePret(relancePret), lotsParBilan(tailleMax - 10), accepter(std::move(accepter))
{
}

Recepteur::Transfert *Recepteur::trouver(Cle k)
{
    for (auto &e : transferts)
        if (e.first == k)
            return &e.second;
    return nullptr;
}

void Recepteur::ranger(Cle k, Transfert &&t)
{
    for (auto &e : transferts)
        if (e.first == k) {
            e.second = std::move(t);
            return;
        }
    transferts.emplace_back(k, std::move(t));
}

bool Recepteur::retirer(Cle k, Transfert &sortie)
{
    for (auto it = transferts.begin(); it != transferts.end(); ++it)
        if (it->first == k) {
            sortie = std::move(it->second);
            transferts.erase(it);
            return true;
        }
    return false;
}

Trames Recepteur::horloge(double maintenant)
{
    Trames sortie;
    for (auto &e : transferts) {
        if (e.first < 0)
            continue; // repris d'un autre récepteur : en attente de son EN-TÊTE
        uint8_t ident = e.first;
        Transfert &tr = e.second;
        if (!tr.actif && tr.prets < 4 && maintenant - tr.pretA >= relancePret) { // PRÊT perdu ?
            tr.pretA = maintenant;
            tr.prets++;
            sortie.push_back(pret(ident));
        }
        if (tr.aBilanDu && maintenant >= tr.bilanDu) {
            tr.aBilanDu = false;
            sortie.push_back(bilan(ident, true));
        }
    }
    return sortie;
}

void Recepteur::noterArrivee(Transfert &tr, double maintenant, bool dansDernierLot)
{
    if (tr.aDerniere) {
        tr.ecarts.push_back(maintenant - tr.derniere);
        if (tr.ecarts.size() > 8)
            tr.ecarts.erase(tr.ecarts.begin());
    }
    tr.derniere = maintenant;
    tr.aDerniere = true;
    if (dansDernierLot || tr.aBilanDu) {
        double habituel = 0;
        if (!tr.ecarts.empty()) {
            std::vector<double> tri(tr.ecarts);
            std::sort(tri.begin(), tri.end());
            habituel = tri[tri.size() / 2];
        }
        tr.bilanDu = maintenant + std::max(silenceMin, 2 * habituel);
        tr.aBilanDu = true;
    }
}

void Recepteur::oublier(uint8_t ident)
{
    auto it = livres.find(ident);
    if (it != livres.end()) {
        for (auto p = livresParEmpreinte.begin(); p != livresParEmpreinte.end();)
            p = p->second == it->second ? livresParEmpreinte.erase(p) : std::next(p);
        livres.erase(it);
    }
    Transfert t;
    retirer(ident, t);
}

bool Recepteur::adopter(const std::vector<Recepteur *> &autres, const Octets &trame)
{
    if (trame.size() < 15 || trame[0] != ENTETE)
        return false;
    Empreinte e{lire32(trame, 10), lire32(trame, 2), trame[14]};
    for (auto &x : transferts)
        if (x.second.empreinte == e)
            return false;
    if (livresParEmpreinte.count(e))
        return false;
    for (Recepteur *autre : autres)
        for (auto it = autre->transferts.begin(); it != autre->transferts.end(); ++it)
            if (it->second.empreinte == e && !autre->livresParEmpreinte.count(e)) {
                Transfert t = std::move(it->second);
                autre->transferts.erase(it);
                transferts.emplace_back(prochainRepris--, std::move(t));
                return true;
            }
    return false;
}

Trames Recepteur::recevoir(const Octets &trame, double maintenant)
{
    if (trame.size() < 2)
        return {};
    uint8_t t = trame[0], ident = trame[1];
    if (t == ENTETE) {
        if (trame.size() < 15)
            return {};
        uint32_t taille = lire32(trame, 2), crc = lire32(trame, 10);
        unsigned nb = lire16(trame, 6), lot = trame[8];
        uint8_t utile = trame[14];
        if (!nb || !lot)
            return {}; // en-tête impossible (le prototype échouerait)
        Empreinte e{crc, taille, utile};
        finals[ident] = std::pair<bool, uint32_t>(trame.size() >= 19, trame.size() >= 19 ? lire32(trame, 15) : 0u);
        if (accepter && !livresParEmpreinte.count(e)) {
            bool enCours = false;
            for (auto &x : transferts)
                enCours |= x.second.empreinte == e;
            if (!enCours && !accepter(taille))
                return {}; // pas la place : silence, l'émetteur relancera
        }
        Transfert *tr = trouver(ident);
        if (!tr || !(tr->empreinte == e)) {
            livres.erase(ident); // id réutilisé pour un autre contenu : nouveau transfert
            Cle ancien = 0;
            bool trouve = false;
            for (auto &x : transferts)
                if (x.second.empreinte == e) {
                    ancien = x.first;
                    trouve = true;
                    break;
                }
            Transfert nouveau;
            if (trouve) { // reprise : même contenu déjà commencé sous un autre id
                retirer(ancien, nouveau);
                nouveau.aBilanDu = false;
            } else {
                nouveau.taille = taille;
                nouveau.nb = nb;
                nouveau.lot = lot;
                nouveau.crc = crc;
                nouveau.utile = utile;
                nouveau.empreinte = e;
            }
            ranger(ident, std::move(nouveau));
            tr = trouver(ident);
        }
        tr->pretA = maintenant;
        tr->prets++;
        tr->actif = false;
        auto deja = livresParEmpreinte.find(e);
        if (deja != livresParEmpreinte.end()) { // déjà tout reçu : bilan final direct
            livres[ident] = deja->second;
            unsigned total = lotsDe(tr->nb, tr->lot);
            for (unsigned n = 0; n < total; n++)
                tr->complets.insert(n);
            tr->morceaux.clear();
            for (unsigned i = 0; i < tr->nb; i++)
                tr->morceaux[i] = Octets();
            return {pret(ident), bilanVideFinal(ident)};
        }
        return {pret(ident)};
    }
    Transfert *tr = trouver(ident);
    if (!tr)
        return {};
    if (t == MORCEAU && trame.size() >= 4) {
        tr->actif = true;
        uint16_t num = lire16(trame, 2);
        unsigned dernierLot = lotsDe(tr->nb, tr->lot) - 1;
        Octets charge(trame.begin() + 4, trame.end());
        if ((num & PARITE) && !(num & DERNIER)) {
            unsigned n = (num & 0x3FFF) >> 1;
            tr->par[{n, unsigned(num & 1)}] = charge;
            noterArrivee(*tr, maintenant, n == dernierLot);
            return {};
        }
        unsigned i = num & 0x7FFF;
        noterArrivee(*tr, maintenant, i / tr->lot == dernierLot || tr->finVue);
        bool nouveau = !tr->bruts.count(i);
        tr->bruts.insert(i);
        tr->morceaux[i] = charge;
        tr->plusHaut = std::max<long>(tr->plusHaut, i);
        if ((num & DERNIER) || (tr->finVue && nouveau)) {
            tr->finVue = true;
            if (tr->morceaux.size() == tr->nb) { // rien ne manque : bilan final tout de suite
                tr->aBilanDu = false;
                return {bilan(ident)};
            }
        }
        if (nouveau && i % (LOT * FENETRE) == 0 && i) // point d'étape
            return {bilan(ident)};
        return {};
    }
    if (t == QUESTION)
        return {bilan(ident, true)};
    return {};
}

bool Recepteur::lotComplet(Transfert &tr, unsigned n)
{
    unsigned debut = n * tr.lot, fin = std::min((n + 1) * tr.lot, tr.nb);
    std::map<unsigned, Octets> recus;
    for (unsigned i = debut; i < fin; i++) {
        auto m = tr.morceaux.find(i);
        if (m != tr.morceaux.end())
            recus[i - debut] = m->second;
    }
    if (recus.size() == fin - debut)
        return true;
    std::map<unsigned, size_t> longueurs;
    for (unsigned i = debut; i < fin; i++) {
        long l = i == tr.nb - 1 ? long(tr.taille) - long(i) * tr.utile : long(tr.utile);
        longueurs[i - debut] = l > 0 ? size_t(l) : 0;
    }
    auto p = tr.par.find({n, 0u}), q = tr.par.find({n, 1u});
    std::vector<Octets> complet;
    if (!raid6::reconstruire(recus, fin - debut, p != tr.par.end() ? &p->second : nullptr,
                             q != tr.par.end() ? &q->second : nullptr, longueurs, complet))
        return false;
    for (unsigned k = 0; k < complet.size(); k++)
        tr.morceaux[debut + k] = complet[k];
    return true;
}

unsigned Recepteur::premierIncomplet(Transfert &tr)
{
    unsigned total = lotsDe(tr.nb, tr.lot), n = 0;
    while (n < total && (tr.complets.count(n) || lotComplet(tr, n))) {
        tr.complets.insert(n);
        n++;
    }
    return n;
}

Octets Recepteur::pret(uint8_t ident)
{
    Transfert &tr = *trouver(ident);
    unsigned premier = premierIncomplet(tr);
    long dernierEntame = tr.bruts.empty() ? -1 : long(*tr.bruts.rbegin() / tr.lot);
    Octets t{PRET, ident};
    mettre16(t, premier);
    long fin = std::min<long>(dernierEntame + 1, long(premier + TRAME_MAX - 4));
    for (long n = premier; n < fin; n++) {
        if (tr.complets.count(n) || lotComplet(tr, n)) {
            tr.complets.insert(n);
            t.push_back(0);
        } else {
            unsigned debut = n * tr.lot, f = std::min<unsigned>((n + 1) * tr.lot, tr.nb);
            uint8_t m = 0;
            for (unsigned i = debut; i < f; i++)
                if (!tr.morceaux.count(i))
                    m |= 1 << (i - debut);
            t.push_back(m);
        }
    }
    return t;
}

Octets Recepteur::bilanVideFinal(uint8_t ident)
{
    Transfert &tr = *trouver(ident);
    unsigned total = lotsDe(tr.nb, tr.lot);
    Octets t{BILAN, ident};
    mettre16(t, total);
    mettre16(t, total);
    mettre16(t, tr.nb);
    mettre16(t, tr.nb);
    return t;
}

Octets Recepteur::bilan(uint8_t ident, bool tout)
{
    Transfert &tr = *trouver(ident);
    unsigned total = lotsDe(tr.nb, tr.lot);
    unsigned juges = (tout || tr.finVue) ? total : unsigned(std::max<long>(tr.plusHaut, 0)) / tr.lot;
    unsigned premier = 0;
    while (premier < juges && (tr.complets.count(premier) || lotComplet(tr, premier))) {
        tr.complets.insert(premier);
        premier++;
    }
    juges = std::min<unsigned>(juges, premier + lotsParBilan);
    Octets carte(juges - premier, 0);
    for (unsigned n = premier; n < juges; n++) {
        if (tr.complets.count(n) || lotComplet(tr, n)) {
            tr.complets.insert(n);
        } else {
            unsigned debut = n * tr.lot, fin = std::min((n + 1) * tr.lot, tr.nb);
            uint8_t m = 0;
            for (unsigned i = debut; i < fin; i++)
                if (!tr.morceaux.count(i))
                    m |= 1 << (i - debut);
            carte[n - premier] = m;
        }
    }
    unsigned attendus = std::min(juges * tr.lot, tr.nb), recus = 0;
    for (unsigned i : tr.bruts)
        if (i < attendus)
            recus++;
    if (juges == total && premier == juges && !livres.count(ident)) {
        Octets contenu;
        for (unsigned i = 0; i < tr.nb; i++) {
            const Octets &m = tr.morceaux[i];
            contenu.insert(contenu.end(), m.begin(), m.end());
        }
        if (contenu.size() > tr.taille)
            contenu.resize(tr.taille);
        if (crc32(contenu) == tr.crc) {
            livres[ident] = contenu;
            livresParEmpreinte[tr.empreinte] = contenu;
        } else { // empreinte fausse : tout redemander (ne devrait pas arriver)
            tr.complets.clear();
            premier = 0;
            juges = std::min<unsigned>(total, lotsParBilan);
            carte.assign(juges, 0xFF);
        }
    }
    Octets t{BILAN, ident};
    mettre16(t, premier);
    mettre16(t, juges);
    mettre16(t, recus);
    mettre16(t, attendus);
    t.insert(t.end(), carte.begin(), carte.end());
    return t;
}

// ---------------------------------------------------------------- Budget

Budget::Budget(double partHeure, double partCanal, double heure, double mesure)
    : partHeure(partHeure), partCanal(partCanal), heure(heure), mesure(mesure)
{
}

double Budget::depense(double t) const
{
    double s = 0;
    for (const auto &j : journal)
        s += std::min(j.second, std::max(0.0, j.first + j.second - (t - heure)));
    return s;
}

double Budget::propre(double debut, double fin) const
{
    double s = 0;
    for (const auto &j : journal)
        s += std::max(0.0, std::min(fin, j.first + j.second) - std::max(debut, j.first));
    return s;
}

double Budget::quand(double instant, double duree, bool urgent)
{
    double t = std::max(instant, finDerniere + dureeDerniere * (1 / partCanal - 1));
    if (aSignale && !urgent) {
        double autres = canal - 100 * propre(vu - mesure, vu) / mesure;
        if ((autres >= 100 * partCanal || emission >= 100 * partHeure) && t < vu + mesure)
            t = vu + mesure; // canal chargé ou budget du boîtier entamé : attendre la mesure suivante
    }
    double plafond = partHeure * heure;
    for (const auto &j : journal) {
        if (depense(t) + duree <= plafond)
            break;
        t = std::max(t, j.first + j.second + heure);
    }
    attentes += t - instant;
    return t;
}

void Budget::noter(double debut, double duree)
{
    journal.emplace_back(debut, duree);
    finDerniere = debut + duree;
    dureeDerniere = duree;
    while (!journal.empty() && journal.front().first + journal.front().second < debut - heure)
        journal.pop_front();
}

void Budget::signaler(double instant, double canalPct, double emissionPct)
{
    aSignale = true;
    vu = instant;
    canal = canalPct;
    emission = emissionPct;
}
} // namespace station
