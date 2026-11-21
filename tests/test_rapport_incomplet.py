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
            # rien d'analysable : on s'arrête
            with self.assertRaisesRegex(SystemExit, "Aucun fichier JSON"):
                um.report_used({"Total"})
            # un dossier illisible : noté, l'analyse continue
            illisibles = {}
            with patch("os.scandir", side_effect=PermissionError("accès refusé")):
                self.assertEqual(um.report_used_columns({("T", "X")}, None, illisibles), {})
            self.assertEqual(len(illisibles), 1)
            self.assertIn("accès refusé", next(iter(illisibles.values())))

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

            def colonne_rapport():
                with patch.multiple(um, MODEL_DIR=tables.parents[1], REPORT_DIR=rapport,
                                    CSV_PATH=sortie), patch("builtins.print"):
                    um.main()
                with sortie.open(encoding="utf-8-sig", newline="") as fichier:
                    lignes = list(csv.DictReader(fichier, delimiter=";"))
                self.assertEqual({ligne["Type"] for ligne in lignes}, {"mesure", "colonne"})
                return {ligne["Rapport analysé"] for ligne in lignes}

            # le NOM du rapport, jamais son chemin complet
            self.assertEqual(colonne_rapport(), {"Essai.Report"})
            (rapport / "casse.json").write_bytes(b"{")
            self.assertEqual(colonne_rapport(),
                             {"Essai.Report (analyse incomplète : 1 fichier(s) illisible(s))"})

    def test_usage_ou_erreur(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(um, "REPORT_DIR", Path(tmp)):
            visuel = Path(tmp) / "visual.json"
            visuel.write_text(json.dumps({"Measure": {"Property": "Total"}}), encoding="utf-8-sig")
            self.assertEqual(um.report_used({"Total"}), {"Total": ["visual.json"]})
            visuel.write_bytes(b"{")
            # illisible : la référence manque, mais l'analyse le dit
            for analyser in (lambda ill: um.report_used({"Total"}, ill),
                             lambda ill: um.report_used_columns({("T", "X")}, None, ill)):
                illisibles = {}
                self.assertEqual(analyser(illisibles), {})
                self.assertEqual(list(illisibles), ["visual.json"])


if __name__ == "__main__":
    unittest.main()
