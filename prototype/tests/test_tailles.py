# Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
"""Aucune trame du protocole ne dépasse TRAME_MAX (219 octets : message direct chiffré par clé publique).
Lancer : python3 -m unittest discover prototype/tests"""
import pathlib, random, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from protocole import Emetteur, Recepteur, TRAME_MAX


class TestTailles(unittest.TestCase):
    def test_gros_contenu_avec_pertes(self):
        """1 Mo, 30 % de pertes, contenu final pour une station : EN-TÊTE, morceaux, PRÊT, BILAN partiels, QUESTION."""
        alea = random.Random(5)
        em, rec = Emetteur(1, alea.randbytes(1024 * 1024), final=0x12345678), Recepteur()
        vers_rec, vers_em, t, plus_grande = list(em.demarrer(0)), [], 0.0, 0
        for _ in range(200000):
            t += 0.5
            if vers_rec:
                tr = vers_rec.pop(0)
                plus_grande = max(plus_grande, len(tr))
                if alea.random() >= 0.3:
                    vers_em += rec.recevoir(tr, t)
            elif vers_em:
                tr = vers_em.pop(0)
                plus_grande = max(plus_grande, len(tr))
                vers_rec += em.recevoir(tr, t)
            else:
                if em.fini or em.echec:
                    break
                t += 30
                vers_em += rec.horloge(t)
                vers_rec += em.horloge(t)
        self.assertTrue(em.fini)
        self.assertLessEqual(plus_grande, TRAME_MAX)


if __name__ == "__main__":
    unittest.main()
