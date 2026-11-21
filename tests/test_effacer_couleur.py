from pathlib import Path
import json
import sys
import tempfile
import unittest

racine = Path(__file__).resolve().parents[1] / "bidouille"
sys.path[:0] = [str(racine), str(racine / "moteurs")]
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest.mock import patch
from openpyxl import Workbook, load_workbook
from qtpy.QtWidgets import QApplication, QMessageBox
from tabs.dialog_couleurs import CouleursDialog


class Couleurs(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fichier = Path(tmp.name) / "indicateurs.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(["KPI", "fond", "texte"])
        ws.append(["A", "#111111", "#FFFFFF"])
        ws.append(["B", "#222222", "#FFFFFF"])
        wb.save(self.fichier)
        wb.close()
        self.dlg = CouleursDialog(self.fichier, "KPI", "fond", "texte")
        self.addCleanup(self.dlg.close)

    def test_effacer(self):
        self.dlg.state["A"]["fill"] = ""
        with patch.object(QMessageBox, "information"):
            self.dlg._save()
        wb = load_workbook(self.fichier)
        self.assertIsNone(wb.active["B2"].value)
        self.assertEqual(wb.active["C2"].value, "#FFFFFF")
        wb.close()


if __name__ == "__main__":
    unittest.main()
