# Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
"""Tests de la reprise (v7) : un contenu déjà commencé n'est pas renvoyé depuis le début.

Cas de l'utilisateur (docs/10 §5 bis) : R1 envoie une photo à U1, U1 s'éloigne en plein transfert ; R2 reprend la
même photo, U1 la reconnaît à son empreinte et ne reçoit que ce qui manque.
Lancer : python3 -m unittest discover prototype/tests
"""
import pathlib, random, struct, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from protocole import Emetteur, Recepteur, MORCEAU, PARITE, DERNIER, PRET


def echanger(em, rec, t0=0.0, couper_apres=None):
    """Échange sans pertes, trame par trame. couper_apres = nombre de morceaux de données livrés avant la coupure
    (U1 sort de portée). Renvoie le nombre de morceaux de données envoyés par l'émetteur."""
    vers_rec, vers_em, t, donnees, livres = list(em.demarrer(t0)), [], t0, 0, 0
    for _ in range(100000):
        t += 0.5
        if vers_rec:
            trame = vers_rec.pop(0)
            if trame[0] == MORCEAU and not (struct.unpack(">H", trame[2:4])[0] & PARITE and
                                            not struct.unpack(">H", trame[2:4])[0] & DERNIER):
                donnees += 1
                if couper_apres is not None and livres >= couper_apres:
                    continue                                  # hors de portée : la trame se perd
                livres += 1
            elif couper_apres is not None and livres >= couper_apres:
                continue
            vers_em += rec.recevoir(trame, t)
        elif vers_em:
            vers_rec += em.recevoir(vers_em.pop(0), t)
        else:
            if em.fini or em.echec:
                break
            t += 30
            vers_em += rec.horloge(t)
            vers_rec += em.horloge(t)
    return donnees


class TestReprise(unittest.TestCase):
    def setUp(self):
        self.photo = random.Random(1).randbytes(30 * 1024)          # 135 morceaux de 229 octets, 17 lots

    def test_transfert_ordinaire(self):
        em, rec = Emetteur(1, self.photo), Recepteur()
        echanger(em, rec)
        self.assertTrue(em.fini)
        self.assertEqual(rec.livres[1], self.photo)

    def test_reprise_par_un_autre_relais(self):
        rec = Recepteur()                                           # U1
        r1 = Emetteur(1, self.photo, relances_max=2)                # R1 : U1 sort de portée après 60 morceaux
        echanger(r1, rec, couper_apres=60)
        self.assertTrue(r1.echec)
        self.assertNotIn(1, rec.livres)
        r2 = Emetteur(7, self.photo)                                # R2 reprend la même photo (autre id)
        envoyes = echanger(r2, rec, t0=1000)
        self.assertTrue(r2.fini)
        self.assertEqual(rec.livres[7], self.photo)
        self.assertGreater(r2.lot_de_depart, 0)
        self.assertEqual(envoyes, len(r2.morceaux) - 60)            # exactement les 75 morceaux manquants

    def test_reprise_avec_trous_eparpilles(self):
        """U1 a reçu 70 % des morceaux des 10 premiers lots, au hasard (lien qui perd), puis plus rien."""
        rec, alea = Recepteur(), random.Random(3)
        r1 = Emetteur(1, self.photo, parites=0)
        rec.recevoir(r1.demarrer(0)[0], 0)
        recus = 0
        for n in range(10):
            for trame in r1.trames_lot(n):
                if alea.random() < 0.7:
                    rec.recevoir(trame, 1)
                    recus += 1
        r2 = Emetteur(7, self.photo)
        envoyes = echanger(r2, rec, t0=1000)
        self.assertTrue(r2.fini)
        self.assertEqual(rec.livres[7], self.photo)
        self.assertEqual(envoyes, len(r2.morceaux) - recus)         # exactement ce qui manquait

    def test_deja_recu_rien_a_renvoyer(self):
        rec = Recepteur()
        echanger(Emetteur(1, self.photo), rec)
        r2 = Emetteur(9, self.photo)
        envoyes = echanger(r2, rec, t0=1000)
        self.assertTrue(r2.fini)
        self.assertEqual(envoyes, 0)
        self.assertEqual(rec.livres[9], self.photo)

    def test_meme_id_autre_contenu_pas_de_melange(self):
        rec = Recepteur()
        echanger(Emetteur(1, self.photo), rec)
        autre = random.Random(2).randbytes(5000)
        em = Emetteur(1, autre)                                     # même id, contenu différent
        echanger(em, rec, t0=1000)
        self.assertTrue(em.fini)
        self.assertEqual(rec.livres[1], autre)

    def test_reprise_chez_un_autre_recepteur(self):
        """Un récepteur par émetteur (U2 côté utilisateur) : R2 reprend chez U2 ce que R1 avait commencé."""
        rec_r1, rec_r2 = Recepteur(), Recepteur()
        r1 = Emetteur(1, self.photo, relances_max=2)
        echanger(r1, rec_r1, couper_apres=60)
        r2 = Emetteur(1, self.photo)                                # même id par hasard, autre émetteur
        premiere = r2.demarrer(1000)
        self.assertTrue(rec_r2.adopter([rec_r1], premiere[0]))
        r2b = Emetteur(1, self.photo)
        envoyes = echanger(r2b, rec_r2, t0=1000)
        self.assertTrue(r2b.fini)
        self.assertEqual(rec_r2.livres[1], self.photo)
        self.assertEqual(envoyes, len(r2b.morceaux) - 60)

    def test_pret_ancien_format_accepte(self):
        em = Emetteur(1, self.photo)
        em.demarrer(0)
        self.assertTrue(em.recevoir(struct.pack(">BB", PRET, 1), 1))  # PRÊT de 2 octets : départ au lot 0
        self.assertEqual(em.lot_de_depart, 0)


if __name__ == "__main__":
    unittest.main()
