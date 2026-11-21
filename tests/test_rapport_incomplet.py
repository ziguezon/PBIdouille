from pathlib import Path
import csv
import json
import sys
import tempfile
import unittest

racine = Path(__file__).resolve().parents[1] / "bidouille"
sys.path[:0] = [str(racine), str(racine / "moteurs")]

import unused_measures as um
from unittest.mock import patch


class Lecture(unittest.TestCase):
    def test_rapport_vide_ou_dossier_illisible(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(um, "REPORT_DIR", Path(tmp)):
            with self.assertRaisesRegex(SystemExit, "aucun fichier JSON"):
                um.report_used({"Total"})
            with patch("os.scandir", side_effect=PermissionError("accès refusé")):
                with self.assertRaisesRegex(SystemExit, "accès refusé"):
                    um.report_used_columns({("T", "X")})

    def test_csv_indique_le_rapport_analyse(self):
        with tempfile.TemporaryDirectory() as tmp:
            projet = Path(tmp)
            rapport = projet / "Essai.Report"
            rapport.mkdir()
            (rapport / "report.json").write_text("{}", encoding="utf-8")
            tables = projet / "Essai.SemanticModel/definition/tables"
            tables.mkdir(parents=True)
            (tables / "Ventes.tmdl").write_text(
                "table Ventes\n\n\tmeasure Total = 12\n\n\tcolumn Valeur\n\t\tdataType: int64\n",
                encoding="utf-8")
            sortie = projet / "audit.csv"
            with patch.multiple(um, MODEL_DIR=tables.parents[1], REPORT_DIR=rapport, CSV_PATH=sortie), patch("builtins.print"):
                um.main()
            with sortie.open(encoding="utf-8-sig", newline="") as fichier:
                lignes = list(csv.DictReader(fichier, delimiter=";"))
            self.assertEqual({ligne["Type"] for ligne in lignes}, {"mesure", "colonne"})
            self.assertEqual({ligne["Rapport analysé"] for ligne in lignes}, {str(rapport)})

    def test_usage_ou_erreur(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(um, "REPORT_DIR", Path(tmp)):
            visuel = Path(tmp) / "visual.json"
            visuel.write_text(json.dumps({"Measure": {"Property": "Total"}}), encoding="utf-8-sig")
            self.assertEqual(um.report_used({"Total"}), {"Total": ["visual.json"]})
            visuel.write_bytes(b"{")
            for analyser in (lambda: um.report_used({"Total"}), lambda: um.report_used_columns({("T", "X")})):
                with self.assertRaisesRegex(SystemExit, "visual.json"):
                    analyser()


if __name__ == "__main__":
    unittest.main()
