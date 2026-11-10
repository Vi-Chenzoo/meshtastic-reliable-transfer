// Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
// C++ port of prototype/protocole.py, written for the Meshtastic firmware (comments in French).
//
// Protocole de transfert de contenus de quelques Ko (version 7) : portage de prototype/protocole.py du projet, mêmes
// trames octet pour octet et mêmes décisions (comparé aux vecteurs du prototype : test/test_station_protocole).
// Indépendant du transport : on donne des trames et l'heure (secondes), on reçoit les trames à envoyer.
//
// Trames (octets, gros-boutiste) :
//   0x01 EN-TÊTE  : id(1) taille(4) nb_morceaux(2) lot(1) réservé(1) empreinte CRC32(4) taille_morceau(1)
//                   [destinataire final(4), facultatif : passage par une station]
//   0x02 PRÊT     : id(1) premier(2) puis 1 octet par lot entamé à partir de `premier` : morceaux manquants
//   0x03 MORCEAU  : id(1) numéro(2) ; bit 15 = dernier morceau ; bit 14 = parité, numéro = lot << 1 | (0 = P, 1 = Q)
//   0x04 BILAN    : id(1) premier(2) lots_jugés(2) reçus(2) attendus(2) puis 1 octet par lot de premier à
//                   lots_jugés-1 : morceaux manquants (0 = complet ou reconstruit)
//   0x05 QUESTION : id(1)
// Parité RAID 6 (P, Q) par lot de 8, adaptative ; fenêtres de 4 lots, deux d'avance ; fin sur silence ; reprise
// d'un contenu déjà commencé, reconnu par son empreinte. Détail des règles : en-tête de prototype/protocole.py.
#pragma once
#include "Raid6.h"
#include <cstdint>
#include <deque>
#include <functional>
#include <map>
#include <set>
#include <tuple>
#include <utility>
#include <vector>

namespace station
{
using Trames = std::vector<Octets>;

constexpr unsigned LOT = 8, FENETRE = 4, AVANCE = 2; // morceaux par lot, lots par fenêtre, fenêtres d'avance
constexpr size_t TRAME_MAX = 219;                    // chiffrement par clé publique compris (prototype : TRAME_MAX)
constexpr size_t UTILE_COMPACT = TRAME_MAX - 4;      // 4 octets d'en-tête de MORCEAU
constexpr uint8_t ENTETE = 1, PRET = 2, MORCEAU = 3, BILAN = 4, QUESTION = 5;
constexpr uint16_t DERNIER = 0x8000, PARITE = 0x4000;
constexpr double FACTEUR_RELANCE = 2.5;

uint32_t crc32(const uint8_t *donnees, size_t n, uint32_t crc = 0); // même valeur que zlib.crc32
inline uint32_t crc32(const Octets &o)
{
    return crc32(o.data(), o.size());
}
/// Morceaux de parité par lot selon le taux de pertes observé ; connu = false : pas encore de mesure.
int paritePour(bool connu, double pertes);

/// Taille des morceaux (protocole.utile_pour) : petit contenu (2 à LOT morceaux, un seul lot) en morceaux égaux, le
/// reste dans les premiers ; au-delà, `utile`. La parité rapetisse avec eux.
size_t utilePour(size_t taille, size_t utile = UTILE_COMPACT);

class Emetteur
{
  public:
    /// parites : -1 = adaptative ; delaiRelance : <= 0 = mesuré sur l'aller-retour EN-TÊTE / PRÊT ;
    /// final : destinataire final (passage par une station), ajouté à l'EN-TÊTE si avecFinal.
    Emetteur(uint8_t id, const Octets &donnees, size_t utile = UTILE_COMPACT, int parites = -1, double delaiRelance = 0,
             unsigned relancesMax = 10, bool avecFinal = false, uint32_t final = 0);
    Trames demarrer(double maintenant);
    void emissionTerminee(double instant); // nos trames sont réellement parties : l'attente commence là
    Trames recevoir(const Octets &trame, double maintenant);
    Trames horloge(double maintenant); // à appeler régulièrement : relance sans nouvelles depuis `delai`

    uint8_t id;
    bool fini = false, echec = false;
    double delai;
    unsigned relances = 0, lotDeDepart = 0;
    std::vector<int> paritesEnvoyees; // parité choisie lot par lot (compte rendu)
    size_t nbMorceaux() const { return morceaux.size(); }

  private:
    Octets donnees;
    size_t utile;
    bool avecFinal;
    uint32_t final;
    int fixe;
    bool delaiFixe;
    unsigned relancesMax;
    std::vector<Octets> morceaux;
    std::vector<std::vector<Octets>> lots;
    bool aDebut = false, enteteRelancee = false, enEnvoi = false, enAttente = false, pertesConnues = false;
    double debut = 0, attenteDepuis = 0, pertes = 0;
    unsigned prochainLot = 0;
    std::map<unsigned, double> renvoyeA;
    std::map<unsigned, uint8_t> deja; // reprise : lot -> morceaux qui manquent au récepteur

    int parites() const;
    Octets trameEntete() const;
    Octets trameMorceau(unsigned num) const;
    Trames tramesLot(unsigned n);
    Trames tramesManquants(unsigned n, uint8_t masque) const;
    Trames fenetre();
};

struct Empreinte {
    uint32_t crc, taille;
    uint8_t utile;
    bool operator<(const Empreinte &o) const
    {
        return std::make_tuple(crc, taille, utile) < std::make_tuple(o.crc, o.taille, o.utile);
    }
    bool operator==(const Empreinte &o) const { return crc == o.crc && taille == o.taille && utile == o.utile; }
};

class Recepteur
{
  public:
    /// accepter(taille) : la station a-t-elle la place ? Sinon pas de PRÊT, l'émetteur relancera plus tard.
    explicit Recepteur(double silenceMin = 5.0, double relancePret = 20.0, size_t tailleMax = TRAME_MAX,
                       std::function<bool(uint32_t)> accepter = nullptr);
    Trames recevoir(const Octets &trame, double maintenant);
    Trames horloge(double maintenant); // BILAN final après un silence, PRÊT renvoyé
    /// Reprise d'un récepteur à l'autre : avant l'EN-TÊTE `trame`, reprendre aux `autres` un transfert inachevé du
    /// même contenu (même empreinte).
    bool adopter(const std::vector<Recepteur *> &autres, const Octets &trame);
    /// Propre au firmware : le contenu livré sous `ident` n'a pas pu être rangé (flash) ; on l'oublie entièrement,
    /// un nouvel EN-TÊTE le fera recevoir de nouveau (le prototype ne peut pas échouer à ranger).
    void oublier(uint8_t ident);

    std::map<uint8_t, Octets> livres;                       // id -> contenu complet
    std::map<uint8_t, std::pair<bool, uint32_t>> finals;    // id -> destinataire final annoncé (présent, numéro)
    std::map<Empreinte, Octets> livresParEmpreinte;         // contenus déjà livrés (reprise)

  private:
    struct Transfert {
        uint32_t taille = 0, crc = 0;
        unsigned nb = 0, lot = 0;
        uint8_t utile = 0;
        Empreinte empreinte{};
        std::map<unsigned, Octets> morceaux;
        std::set<unsigned> bruts, complets;
        std::map<std::pair<unsigned, unsigned>, Octets> par;
        bool finVue = false, actif = false, aDerniere = false, aBilanDu = false;
        long plusHaut = -1;
        double derniere = 0, bilanDu = 0, pretA = 0;
        std::vector<double> ecarts;
        unsigned prets = 0;
    };
    using Cle = int64_t; // 0..255 : id du transfert ; < 0 : transfert repris d'un autre récepteur
    std::vector<std::pair<Cle, Transfert>> transferts; // dans l'ordre d'arrivée, comme le dict du prototype
    double silenceMin, relancePret;
    size_t lotsParBilan;
    std::function<bool(uint32_t)> accepter;
    Cle prochainRepris = -1;

    Transfert *trouver(Cle k);
    void ranger(Cle k, Transfert &&t); // remplace en place, sinon ajoute à la fin
    bool retirer(Cle k, Transfert &sortie);
    void noterArrivee(Transfert &tr, double maintenant, bool dansDernierLot);
    bool lotComplet(Transfert &tr, unsigned n);
    unsigned premierIncomplet(Transfert &tr);
    Octets pret(uint8_t ident);
    Octets bilanVideFinal(uint8_t ident);
    Octets bilan(uint8_t ident, bool tout = false);
};

/// Discipline d'émission d'UN appareil : 5 % de l'heure glissante, canal sous 25 % (prototype : Budget).
class Budget
{
  public:
    explicit Budget(double partHeure = 0.05, double partCanal = 0.25, double heure = 3600.0, double mesure = 60.0);
    double depense(double t) const;
    double propre(double debut, double fin) const;
    double quand(double instant, double duree, bool urgent = false); // premier instant >= instant permis
    void noter(double debut, double duree);
    void signaler(double instant, double canalPct, double emissionPct); // télémétrie de l'appareil
    double attentes = 0;

  private:
    double partHeure, partCanal, heure, mesure;
    std::deque<std::pair<double, double>> journal;
    double finDerniere = -1e9, dureeDerniere = 0;
    bool aSignale = false;
    double vu = 0, canal = 0, emission = 0;
};
} // namespace station
