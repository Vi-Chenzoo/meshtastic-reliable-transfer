# Copyright (C) 2026 SoCodeIA and Vincent PERRIN. Licensed under the GNU General Public License version 3 (LICENSE).
"""Règles du budget d'émission (Budget). Lancer : python3 -m unittest discover prototype/tests"""
import pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from protocole import Budget


class TestBudget(unittest.TestCase):
    def test_notre_part_retiree_de_la_mesure(self):
        b = Budget()
        for i in range(6):                       # 6 trames de 2 s dans la minute : 20 % du canal, à nous
            b.noter(i * 10.0, 2.0)
        b.signaler(60.0, canal_pct=40.0, emission_pct=1.0)   # canal à 40 % : 20 % à nous, 20 % aux autres
        self.assertLess(b.quand(61.0, 2.0), 62.0)            # les autres sont sous 25 % : on continue
        b.signaler(60.0, canal_pct=50.0, emission_pct=1.0)   # les autres à 30 % : on se tait jusqu'à la mesure
        self.assertEqual(b.quand(61.0, 2.0), 120.0)

    def test_reponse_urgente_n_attend_pas_la_mesure(self):
        b = Budget()
        b.signaler(0.0, canal_pct=80.0, emission_pct=1.0)
        self.assertEqual(b.quand(1.0, 0.2), 60.0)
        self.assertEqual(b.quand(1.0, 0.2, urgent=True), 1.0)

    def test_urgente_reste_comptee_dans_l_heure(self):
        b = Budget()
        b.noter(0.0, 180.0)                       # toute l'heure déjà dépensée
        self.assertGreater(b.quand(200.0, 0.2, urgent=True), 3600.0)


if __name__ == "__main__":
    unittest.main()
