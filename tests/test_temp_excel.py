from pathlib import Path
import json
import sys
import tempfile
import unittest

racine = Path(__file__).resolve().parents[1] / "bidouille"
sys.path[:0] = [str(racine), str(racine / "moteurs")]

import os
from unittest.mock import patch
from openpyxl import Workbook
import xlsx_lecture as xl


class DossierTemporaire(unittest.TestCase):
    def test_lecture_et_nettoyage(self):
        with tempfile.TemporaryDirectory() as tmp:
            espace = Path(tmp) / "reserve"
            espace.mkdir()
            source = Path(tmp) / "source.xlsx"
            wb = Workbook()
            wb.active["A1"] = "Total"
            wb.save(source)
            wb.close()
            import shutil
            copie = shutil.copy2
            def copier(src, dst):
                self.assertEqual(Path(dst).parent.parent, espace)
                return copie(src, dst)
            with patch.dict(os.environ, PBIDOUILLE_TEMP_EXCEL=str(espace)), patch.object(xl.shutil, "copy2", copier):
                self.assertEqual(xl.lire_lignes(source), [("Total",)])
                self.assertEqual(list(espace.iterdir()), [])
                with self.assertRaises(KeyError):
                    xl.lire_lignes(source, sheet="Absent")
                self.assertEqual(list(espace.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
