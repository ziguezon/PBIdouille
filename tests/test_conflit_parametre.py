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

    def test_conflits_sans_ecriture(self):
        table = self.tables / "Produits.tmdl"
        self.config["fieldParameter"] = {"tables": ["Nouveau", "Produits"]}
        def colonne(valeur):
            return "\tcolumn Fields\n\t\textendedProperty ParameterMetadata = " + valeur + "\n"

        for partition, metadata in (("m", ""), ("calculated", ""),
                                    ("m", colonne('{"kind": 2}')),
                                    ("calculated", colonne("{}")),
                                    ("calculated", colonne('{"kind": 1}')),
                                    ("calculated", colonne("{illisible"))):
            table.write_text("table Produits\n" + metadata + "\tpartition Produits = " + partition
                             + "\n\t\tsource =\n\t\t\t1\n", encoding="utf-8")
            avant = self.fichiers()
            for simulation in (True, False):
                with self.subTest(partition=partition, simulation=simulation):
                    with self.assertRaisesRegex(SystemExit, "Produits"):
                        self.generer(simulation)
                    self.assertEqual(self.fichiers(), avant)
                    self.assertFalse((self.projet / "_backupsPBIdouille").exists())

    def test_nom_logique_independant_du_fichier(self):
        self.config["fieldParameter"] = {"tables": ["PRODUITS"]}
        (self.tables / "table_42.tmdl").write_text(
            "table Produits\n\n\tpartition Produits = m\n\t\tsource =\n\t\t\t1\n")
        avant = self.fichiers()
        with self.assertRaisesRegex(SystemExit, "PRODUITS"):
            self.generer()
        self.assertEqual(avant, self.fichiers())

    def test_metadonnees_des_parametres_existants(self):
        for valeur in ('{"kind": 2}', '\n\t\t\t{"kind": 2}', '```\n\t\t\t{"kind": 2}\n\t\t\t```'):
            texte = ("table Choix\n\tcolumn Champ\n\t\textendedProperty 'ParameterMetadata' = "
                     + valeur + "\n\tpartition Choix = calculated\n\t\tsource =\n\t\t\t{}\n")
            with self.subTest(valeur=valeur):
                self.assertIsNotNone(gm.source_parametre(texte, "Choix"))

    def test_vrai_parametre(self):
        self.config["fieldParameter"] = {"tables": ["Choix"]}
        self.generer()
        table = self.tables / "Choix.tmdl"
        avant = table.read_text(encoding="utf-8")
        self.config["variations"]["double"]["inFieldParameter"] = True
        self.generer()
        apres = table.read_text(encoding="utf-8")
        self.assertIn("Total double", apres)
        self.assertEqual(avant.split("\tpartition")[0], apres.split("\tpartition")[0])


if __name__ == "__main__":
    unittest.main()
