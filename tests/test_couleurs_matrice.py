from pathlib import Path
import json
import sys
import tempfile
import unittest

racine = Path(__file__).resolve().parents[1] / "bidouille"
sys.path[:0] = [str(racine), str(racine / "moteurs")]

from unittest.mock import patch
import color_matrix_by_kpi as cm
import backup_restore as br


class Matrice(unittest.TestCase):
    def test_selecteurs_et_restauration(self):
        with tempfile.TemporaryDirectory() as tmp:
            projet = Path(tmp)
            rapport = projet / "Exemple.Report"
            f = rapport / "definition/pages/page/visuals/matrice/visual.json"
            f.parent.mkdir(parents=True)
            modele = projet / "Exemple.SemanticModel"
            tables = modele / "definition/tables"
            tables.mkdir(parents=True)
            (tables / "Ventes.tmdl").write_text("table Ventes\n\tmeasure Total = 12\n")
            def couleur(nom):
                return {"selector": {"metadata": nom}, "properties": {"backColor": cm.color_value("#000000")}}
            manuel = couleur("Autre.Total")
            contenu = {"visual": {"objects": {"columnFormatting": [couleur("Ventes.Total"), manuel]}}}
            f.write_text(json.dumps(contenu))
            avant = f.read_bytes()
            with patch.object(cm, "read_kpi_colors", return_value={"Total": {"fill": "#ABCDEF", "text": None}}):
                cm.colorize(rapport, modele, dry_run=True, log=lambda *_: None)
                self.assertEqual(f.read_bytes(), avant)
                cm.colorize(rapport, modele, log=lambda *_: None)
                cm.colorize(rapport, modele, log=lambda *_: None)
            entries = json.loads(f.read_bytes())["visual"]["objects"]["columnFormatting"]
            self.assertIn(manuel, entries)
            self.assertIn(cm.color_value("#ABCDEF"), entries[-1]["properties"].values())
            s, = br.list_sessions(projet)
            br.restore_session(s["dossier"], projet)
            self.assertEqual(avant, f.read_bytes())


if __name__ == "__main__":
    unittest.main()
