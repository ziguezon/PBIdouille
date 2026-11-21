from pathlib import Path
import json
import sys
import tempfile
import unittest

racine = Path(__file__).resolve().parents[1] / "bidouille"
sys.path[:0] = [str(racine), str(racine / "moteurs")]

from core.project import Project
import lineage
import propagate_cf as pc
import radiographie
import unused_measures as um


class Modeles(unittest.TestCase):
    def test_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pbip = root / "Ancien.pbip"
            rapport = root / "Rapport.Report"
            rapport.mkdir()
            modele = root / "Partage.SemanticModel"
            (modele / "definition/tables").mkdir(parents=True)
            (modele / "definition/tables/M.tmdl").write_text("table M\n\n\tmeasure Vraie = 1\n")
            (root / "Ancien.SemanticModel").mkdir()
            pbip.write_text(json.dumps({"artifacts": [{"report": {"path": rapport.name}}]}))
            pbir = rapport / "definition.pbir"
            pbir.write_text(json.dumps({"datasetReference": {"byPath": {"path": "../" + modele.name}}}))
            projet = Project(pbip)
            self.assertEqual(projet.report_dir, rapport.resolve())
            self.assertEqual(projet.model_dir, modele.resolve())
            self.assertEqual(lineage.scan_projet(pbip)["modele_dir"], modele.resolve())
            self.assertEqual(pc.contexte_modele(rapport, targets=["Vraie"])["semantic_dir"], modele.resolve())
            um.set_project(pbip)
            self.assertEqual(um.MODEL_DIR, modele.resolve())
            self.assertIn("Vraie", radiographie.analyser(pbip)["mesures"])
            for ref in ({"byPath": {"path": "../Absent.SemanticModel"}}, {"byConnection": {}}, {}):
                pbir.write_text(json.dumps({"datasetReference": ref}))
                self.assertFalse(projet.valid)
                with self.assertRaises(SystemExit):
                    pc.contexte_modele(rapport, targets=["Vraie"])
                with self.assertRaises(FileNotFoundError):
                    radiographie.analyser(pbip)
            pbir.unlink()
            self.assertEqual(projet.model_dir, rapport.with_suffix(".SemanticModel").resolve())


if __name__ == "__main__":
    unittest.main()
