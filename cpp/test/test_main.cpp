// Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
// C++ port of prototype/protocole.py, written for the Meshtastic firmware (comments in French).
//
// Le portage C++ du protocole (src/modules/station) rejoue les scénarios du prototype Python et doit produire les
// mêmes trames, dans le même ordre, aux mêmes instants (vecteurs.h, généré par outils/vecteurs-protocole.py du
// projet). Même chose pour le budget d'émission (résultats flottants exacts) et la parité RAID 6.
#include "../Protocole.h"
#include "vecteurs.h"
#include <algorithm>
#include <cstdio>
#include "unity_mini.h"

using namespace station;

namespace
{
// Générateur congruentiel, le même que Hasard dans outils/vecteurs-protocole.py.
struct Hasard {
    uint32_t x;
    explicit Hasard(uint32_t graine) : x(graine & 0x7FFFFFFF) {}
    uint32_t suivant()
    {
        x = uint32_t((uint64_t(x) * 1103515245u + 12345u) & 0x7FFFFFFF);
        return x;
    }
};

Octets donnees(uint32_t taille, uint32_t graine)
{
    Hasard h(graine);
    Octets d(taille);
    for (auto &o : d)
        o = (h.suivant() >> 16) & 0xFF;
    return d;
}

struct EnVol {
    double t;
    unsigned seq;
    char sens;
    Octets trame;
};

constexpr double PAS = 0.5, LATENCE = 1.0;

void rejouer(const vecteurs::Scenario &sc)
{
    char msg[160];
    Octets d = donnees(sc.taille, sc.graineDonnees);
    Hasard hasard(sc.grainePertes);
    Recepteur r1, r2;
    Recepteur *rec = &r1;
    auto nouvelEmetteur = [&](uint8_t ident) {
        return Emetteur(ident, d, sc.utile, sc.parite, sc.delai, 10, sc.avecFinal, sc.final);
    };
    Emetteur em = nouvelEmetteur(1);
    int phase = 1;
    std::vector<EnVol> file;
    size_t ligne = 0;
    unsigned seq = 0;

    auto envoyer = [&](char sens, const Trames &trames, double t) {
        for (const Octets &f : trames) {
            seq++;
            bool perdu = hasard.suivant() % 1000 < (sens == 'E' ? sc.pertesAller : sc.pertesRetour);
            snprintf(msg, sizeof msg, "%s : trame %u (t=%.1f, sens %c)", sc.nom, unsigned(ligne), t, sens);
            TEST_ASSERT_LESS_THAN_MESSAGE(sc.nJournal, ligne, msg);
            const vecteurs::Ligne &v = sc.journal[ligne++];
            TEST_ASSERT_EQUAL_DOUBLE_MESSAGE(v.t, t, msg);
            TEST_ASSERT_EQUAL_CHAR_MESSAGE(v.sens, sens, msg);
            TEST_ASSERT_EQUAL_UINT16_MESSAGE(v.longueur, f.size(), msg);
            TEST_ASSERT_EQUAL_HEX32_MESSAGE(v.crc, crc32(f), msg);
            TEST_ASSERT_EQUAL_MESSAGE(v.perdu, perdu, msg);
            if (!perdu)
                file.push_back({t + LATENCE, seq, sens, f});
        }
    };

    envoyer('E', em.demarrer(0.0), 0.0);
    unsigned k = 0;
    while (k * PAS <= sc.tmax) {
        double t = k * PAS;
        if (sc.coupure > 0 && phase == 1 && t >= sc.coupure) {
            phase = 2;
            rec = sc.autreRecepteur ? &r2 : &r1;
            file.clear();
            em = nouvelEmetteur(2);
            envoyer('E', em.demarrer(t), t);
        }
        std::vector<EnVol> dus, reste;
        for (auto &x : file)
            (x.t <= t ? dus : reste).push_back(x);
        file = reste;
        std::sort(dus.begin(), dus.end(), [](const EnVol &a, const EnVol &b) {
            return a.t != b.t ? a.t < b.t : a.seq < b.seq;
        });
        for (auto &x : dus) {
            if (x.sens == 'E') {
                if (phase == 2 && sc.autreRecepteur && x.trame[0] == ENTETE)
                    rec->adopter({&r1}, x.trame);
                envoyer('R', rec->recevoir(x.trame, t), t);
            } else {
                envoyer('E', em.recevoir(x.trame, t), t);
            }
        }
        envoyer('E', em.horloge(t), t);
        envoyer('R', rec->horloge(t), t);
        if ((em.fini || em.echec) && !(sc.coupure > 0 && phase == 1))
            break;
        k++;
    }
    snprintf(msg, sizeof msg, "%s : fin", sc.nom);
    TEST_ASSERT_EQUAL_MESSAGE(sc.nJournal, ligne, msg);
    TEST_ASSERT_EQUAL_MESSAGE(sc.fini, em.fini, msg);
    TEST_ASSERT_EQUAL_MESSAGE(sc.echec, em.echec, msg);
    TEST_ASSERT_EQUAL_DOUBLE_MESSAGE(sc.tFin, k * PAS, msg);
    TEST_ASSERT_EQUAL_UINT_MESSAGE(sc.lotDepart, em.lotDeDepart, msg);
    TEST_ASSERT_EQUAL_MESSAGE(sc.nParites, em.paritesEnvoyees.size(), msg);
    for (size_t i = 0; i < sc.nParites; i++)
        TEST_ASSERT_EQUAL_INT_MESSAGE(sc.parites[i], em.paritesEnvoyees[i], msg);
    auto livre = rec->livres.find(em.id);
    TEST_ASSERT_EQUAL_MESSAGE(sc.livre, livre != rec->livres.end(), msg);
    if (sc.livre) {
        TEST_ASSERT_EQUAL_HEX32_MESSAGE(sc.crcLivre, crc32(livre->second), msg);
        TEST_ASSERT_TRUE_MESSAGE(livre->second == d, msg);
    }
}
} // namespace

void setUp() {}
void tearDown() {}

// zlib.crc32 de "123456789" (valeur de contrôle du CRC-32 IEEE).
void test_crc32_comme_zlib()
{
    const char *s = "123456789";
    TEST_ASSERT_EQUAL_HEX32(0xCBF43926u, crc32(reinterpret_cast<const uint8_t *>(s), 9));
}

// Chaque scénario du prototype (pertes, coupure, reprise, autre récepteur, échec) : trames identiques.
void test_scenarios_comme_le_prototype()
{
    for (const auto &sc : vecteurs::scenarios)
        rejouer(sc);
}

// Budget d'émission : mêmes instants permis, à l'octet près des flottants.
void test_budget_comme_le_prototype()
{
    Budget b;
    for (const auto &a : vecteurs::budget) {
        switch (a.op) {
        case 0:
        case 1: {
            double q = b.quand(a.a, a.b, a.op == 1);
            TEST_ASSERT_EQUAL_DOUBLE(a.resultat, q);
            TEST_ASSERT_TRUE(q == a.resultat);
            break;
        }
        case 2:
            b.signaler(a.a, a.b, a.c);
            break;
        case 3:
            b.noter(a.a, a.b);
            TEST_ASSERT_TRUE(b.depense(a.a + 1.0) == a.resultat);
            break;
        case 4:
            TEST_ASSERT_TRUE(b.attentes == a.resultat);
            break;
        }
    }
}

// Parité RAID 6 : P et Q comme le prototype ; tout morceau perdu, ou toute paire, se reconstruit.
void test_raid6_parite_et_reconstruction()
{
    for (const auto &l : vecteurs::lots) {
        Hasard h(1000 + l.graine);
        unsigned nb = 2 + h.suivant() % 7;
        TEST_ASSERT_EQUAL_UINT(l.nb, nb);
        std::vector<Octets> lot;
        for (unsigned i = 0; i < nb; i++) {
            unsigned n = 1 + h.suivant() % 215;
            TEST_ASSERT_EQUAL_UINT(l.longueurs[i], n);
            lot.push_back(donnees(n, 5000 + l.graine * 10 + i));
        }
        Octets p, q;
        raid6::parite(lot, p, q);
        TEST_ASSERT_EQUAL_HEX32(l.crcP, crc32(p));
        TEST_ASSERT_EQUAL_HEX32(l.crcQ, crc32(q));
        std::map<unsigned, size_t> longueurs;
        for (unsigned i = 0; i < nb; i++)
            longueurs[i] = lot[i].size();
        for (unsigned a = 0; a < nb; a++)
            for (unsigned b = a; b < nb; b++) {
                std::map<unsigned, Octets> recus;
                for (unsigned i = 0; i < nb; i++)
                    if (i != a && i != b)
                        recus[i] = lot[i];
                std::vector<Octets> sortie;
                bool deux = a != b;
                TEST_ASSERT_TRUE(raid6::reconstruire(recus, nb, &p, &q, longueurs, sortie));
                TEST_ASSERT_TRUE(sortie == lot);
                if (!deux) { // un seul trou : P seule, puis Q seule
                    TEST_ASSERT_TRUE(raid6::reconstruire(recus, nb, &p, nullptr, longueurs, sortie));
                    TEST_ASSERT_TRUE(sortie == lot);
                    TEST_ASSERT_TRUE(raid6::reconstruire(recus, nb, nullptr, &q, longueurs, sortie));
                    TEST_ASSERT_TRUE(sortie == lot);
                } else { // deux trous et une seule parité : impossible
                    TEST_ASSERT_FALSE(raid6::reconstruire(recus, nb, &p, nullptr, longueurs, sortie));
                }
            }
    }
}

int main()
{
    UNITY_BEGIN();
    RUN_TEST(test_crc32_comme_zlib);
    RUN_TEST(test_scenarios_comme_le_prototype);
    RUN_TEST(test_budget_comme_le_prototype);
    RUN_TEST(test_raid6_parite_et_reconstruction);
    return UNITY_END();
}
