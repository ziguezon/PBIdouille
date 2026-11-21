"""Vérifie que la barre d'onglets réserve la largeur de son texte peint."""
import os
from pathlib import Path
import sys
import unittest

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
elif os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    # Le greffon hors écran de Qt 5 lit les polices du dossier indiqué.
    os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ["WINDIR"]) / "Fonts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bidouille"))
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QTabWidget, QWidget
from core.theme import neon_stylesheet


class LibellesOnglets(unittest.TestCase):
    def test_largeur_du_texte_peint(self):
        app = QApplication.instance() or QApplication([])
        app.setStyleSheet(neon_stylesheet())
        onglets = QTabWidget()
        onglets.setAttribute(Qt.WA_DontShowOnScreen)
        onglets.setObjectName("ongletsPrincipaux")
        barre = onglets.tabBar()
        barre.setFocusPolicy(Qt.NoFocus)
        for libelle in ("Mesures", "Rapport", "Sources de données", "Radiographie 🩻", "ChopChop 🪓"):
            onglets.addTab(QWidget(), libelle)
        onglets.resize(1600, 180)
        onglets.show()

        def largeur_encre(index):
            app.processEvents()
            image = barre.grab(barre.tabRect(index)).toImage()
            dpr = image.devicePixelRatio()
            marge = round(5 * dpr)
            xs = [x for x in range(marge, image.width() - marge)
                  if any(image.pixelColor(x, y).green() > 115
                         for y in range(marge, image.height() - marge))]
            return max(xs) - min(xs) + 1 if xs else 0

        for index in range(barre.count()):
            for actif in (False, True):
                with self.subTest(onglet=barre.tabText(index), actif=actif):
                    onglets.setCurrentIndex(index if actif else (index + 1) % barre.count())
                    barre.setStyleSheet("")
                    normale = largeur_encre(index)
                    # Même texte et même état dans un onglet assez large pour tout peindre.
                    barre.setStyleSheet("QTabBar::tab { min-width: 235px; }")
                    reference = largeur_encre(index)
                    self.assertGreater(reference, 10)
                    self.assertLessEqual(abs(reference - normale), 2 * barre.devicePixelRatioF(),
                                         (normale, reference))
        onglets.close()


if __name__ == "__main__":
    unittest.main()
