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

    def test_autre_table(self):
        # le conflit est signalé et ignoré ; le reste du lot s'écrit
        self.config["variations"]["triple"] = {"namePattern": "{base} triple",
                                               "dax": "{baseRef} * 3"}
        ventes = self.tables / "Ventes.tmdl"
        initial = ventes.read_bytes()
        autre = self.tables / "Archives.tmdl"
        for nom in ("Total double", "TOTAL DOUBLE"):
            ventes.write_bytes(initial)
            autre.write_text(f"table Archives\n\n\tmeasure '{nom}' = 42\n")
            archives = autre.read_bytes()
            for simulation in (True, False):
                with self.subTest(nom=nom, simulation=simulation):
                    journal = []
                    st = gm.generate(self.modele, self.config, dry_run=simulation,
                                     log=journal.append)
                    self.assertIn("Total double", st["skipped"])
                    self.assertNotIn("Total double", st["created"])
                    self.assertTrue(any("'Archives'" in str(l) for l in journal))
                    self.assertEqual(autre.read_bytes(), archives)
                    texte = ventes.read_text(encoding="utf-8")
                    self.assertNotIn("Total double", texte)
                    self.assertEqual("Total triple" in texte, not simulation)

    def test_casse_dans_la_meme_table(self):
        path = self.tables / "Ventes.tmdl"
        with path.open("a") as fichier:
            fichier.write("\n\tmeasure 'TOTAL DOUBLE' = 99\n")
        st = self.generer()
        self.assertIn("Total double", st["skipped"])
        self.assertNotIn("'Total double'", path.read_text())

    def test_mesure_manuelle_locale(self):
        path = self.tables / "Ventes.tmdl"
        with path.open("a") as fichier:
            fichier.write("\n\tmeasure 'Total double' = 99\n")
        self.assertIn("Total double", self.generer()["skipped"])
        self.assertIn("= 99", path.read_text())


if __name__ == "__main__":
    unittest.main()
