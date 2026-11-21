from pathlib import Path
import json
import sys
import tempfile
import unittest

racine = Path(__file__).resolve().parents[1] / "bidouille"
sys.path[:0] = [str(racine), str(racine / "moteurs")]

import generate_measures as gm
from projet_minimal import creer


class ProjetMinimal(unittest.TestCase):
    def test_aperçu_et_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            projet = creer(Path(tmp) / "atelier").parent
            cfg = json.loads((projet / "measures_config.json").read_text(encoding="utf-8"))
            modele = projet / "Atelier.SemanticModel"
            apercu = gm.generate(modele, cfg, dry_run=True, log=lambda *_: None)
            self.assertFalse((projet / "_backupsPBIdouille").exists())
            resultat = gm.generate(modele, cfg, dry_run=False, log=lambda *_: None)
            self.assertEqual(set(resultat["created"]), {"Total double", "Lignes double"})
            self.assertEqual(resultat["created"], apercu["created"])
            self.assertTrue((modele / "definition/tables/Choix.tmdl").is_file())


if __name__ == "__main__":
    unittest.main()
