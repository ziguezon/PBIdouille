from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bidouille" / "moteurs"))
import generate_measures as gm


class Generation(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.projet = Path(tmp.name)
        self.modele = self.projet / "Exemple.SemanticModel"
        self.tables = self.modele / "definition/tables"
        self.tables.mkdir(parents=True)
        (self.tables.parent / "model.tmdl").write_text("model Model\n\nref table Ventes\n", encoding="utf-8")
        (self.tables / "Ventes.tmdl").write_text(
            "table Ventes\n\n\tmeasure Total = 12\n\t\tdisplayFolder: Base\n", encoding="utf-8")
        self.config = {"settings": {"sourceTable": "Ventes", "sourceFolder": "Base"},
                       "variations": {"double": {"namePattern": "{base} double", "dax": "{baseRef} * 2"}}}

    def generer(self, apercu=False):
        return gm.generate(self.modele, self.config, dry_run=apercu, log=lambda *_: None)

    def fichiers(self):
        return {p.relative_to(self.modele): p.read_bytes() for p in self.modele.rglob("*") if p.is_file()}

    def test_reprise(self):
        from unittest.mock import patch
        import backup_restore as br
        self.config["fieldParameter"] = {"tables": ["Choix"]}
        avant = self.fichiers()
        ecrire = Path.write_text
        def panne(path, *args, **kwargs):
            if path == self.tables.parent / "model.tmdl":
                raise OSError("interruption simulée")
            return ecrire(path, *args, **kwargs)
        with patch.object(Path, "write_text", panne), self.assertRaises(OSError):
            self.generer()
        session, = br.list_sessions(self.projet)
        self.assertTrue(session["manifeste"])
        br.restore_session(session["dossier"], self.projet)
        self.assertEqual(self.fichiers(), avant)
        self.generer()
        self.assertIn("ref table Choix", (self.tables.parent / "model.tmdl").read_text())


if __name__ == "__main__":
    unittest.main()
