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

    def test_ecrit_dans_cible(self):
        cible = self.tables / "Sortie.tmdl"
        cible.write_text("table Sortie\n\n\tmeasure Locale = 2\n")
        self.config["settings"]["targetTable"] = "Sortie"
        source = (self.tables / "Ventes.tmdl").read_bytes()
        self.assertEqual(self.generer(True)["created"], ["Total double"])
        self.generer()
        self.assertEqual(source, (self.tables / "Ventes.tmdl").read_bytes())
        self.assertIn("measure Locale = 2", cible.read_text())
        self.assertIn("Total double", cible.read_text())
        self.assertFalse(self.generer(True)["created"])


if __name__ == "__main__":
    unittest.main()
