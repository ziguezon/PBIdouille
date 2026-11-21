from pathlib import Path
import json
import sys
import tempfile
import unittest

racine = Path(__file__).resolve().parents[1] / "bidouille"
sys.path[:0] = [str(racine), str(racine / "moteurs")]

import backup_restore as br
from core.template_import import import_model


class Import(unittest.TestCase):
    def test_import_restauration_apres_reouverture(self):
        with tempfile.TemporaryDirectory() as tmp:
            projet = Path(tmp)
            rapport = projet / "Essai.Report"
            visuels = rapport / "definition/pages/source/visuals"
            for nom, parent in (("groupe", None), ("enfant", "groupe")):
                path = visuels / nom / "visual.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"name": nom, "parentGroupName": parent, "position": {}}))
            repertoire = br.backup_root(projet, "_wireframe_backups")
            _, crees, manifeste = import_model(rapport, "source", "groupe", rapport, "cible", repertoire)
            self.assertTrue(manifeste.exists())
            self.assertEqual(len(crees), 2)
            info, = br.list_sessions(projet)
            self.assertTrue(info["manifeste"])
            retour = br.restore_session(info["dossier"], projet)
            self.assertTrue(all(not Path(p).exists() for p in crees))
            br.restore_session(retour["sauvegarde_avant"], projet)
            self.assertTrue(all(Path(p).exists() for p in crees))


if __name__ == "__main__":
    unittest.main()
