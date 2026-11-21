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

    def test_tri_et_modification_concurrente(self):
        import backup_restore as br
        wb = load_workbook(self.fichier)
        ws = wb.active
        ws["A2"], ws["A3"] = "B", "A"
        ws["C2"] = "#334455"
        wb.save(self.fichier)
        wb.close()
        avant = self.fichier.read_bytes()
        self.dlg.state["A"]["fill"] = "#ABCDEF"
        with patch.object(QMessageBox, "information"):
            self.dlg._save()
        wb = load_workbook(self.fichier)
        self.assertEqual(wb.active["B3"].value, "#ABCDEF")
        self.assertEqual(wb.active["C2"].value, "#334455")
        wb.close()
        session, = br.list_sessions(self.fichier.parent)
        br.restore_session(session["dossier"], self.fichier.parent)
        self.assertEqual(self.fichier.read_bytes(), avant)


if __name__ == "__main__":
    unittest.main()
