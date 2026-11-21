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
from qtpy.QtWidgets import QApplication, QMessageBox
from _fixture import reglages_jetables
sys.path.insert(0, str(racine.parent))
import app
from tabs.tab_config import IDX_RAW


class Brouillon(unittest.TestCase):
    def test_recharger_apres_echec(self):
        qapp = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            projet = Path(tmp)
            reglages_jetables("brouillon")
            with patch.object(app.BidouilleWindow, "_load_initial_project"):
                fen = app.BidouilleWindow()
            for suffixe in (".Report", ".SemanticModel"):
                (projet / ("Atelier" + suffixe)).mkdir()
            pbip = projet / "Atelier.pbip"
            pbip.write_text("{}")
            config = projet / "measures_config.json"
            config.write_text('{"settings": {}}')
            fen._set_project(pbip)
            tab = fen.tab_config
            tab.inner.setCurrentIndex(IDX_RAW)
            tab.ed_raw.setPlainText("{brouillon")
            self.assertTrue(tab._dirty)
            with patch.object(QMessageBox, "exec_", return_value=0, create=True), \
                    patch.object(QMessageBox, "clickedButton", lambda box: box.defaultButton()), \
                    patch.object(QMessageBox, "critical") as erreur:
                fen._reload_all()
            erreur.assert_called_once()
            self.assertEqual(tab.ed_raw.toPlainText(), "{brouillon")
            self.assertTrue(tab._dirty)
            self.assertEqual(config.read_text(), '{"settings": {}}')
            tab._set_dirty(False)
            fen.close()


if __name__ == "__main__":
    unittest.main()
