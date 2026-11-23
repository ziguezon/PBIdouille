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

    def test_annuler_creation(self):
        import backup_restore as br
        self.config["fieldParameter"] = {"tables": ["Choix"]}
        avant = self.fichiers()
        self.generer()
        self.assertTrue((self.tables / "Choix.tmdl").exists())
        session, = br.list_sessions(self.projet)
        br.restore_session(session["dossier"], self.projet)
        self.assertEqual(self.fichiers(), avant)

    @staticmethod
    def colonne_ordre(texte):
        bloc = texte.split("\tcolumn 'Choix Ordre'\n", 1)[1].split("\n\n", 1)[0]
        return bloc

    def test_ordre_numerique_a_la_creation(self):
        # en texte, Power BI rangeait « 100 » avant « 99 » : une cible au rang
        # 100 passait devant son Réel au rang 99
        self.config["fieldParameter"] = {"tables": ["Choix"]}
        self.generer()
        bloc = self.colonne_ordre((self.tables / "Choix.tmdl").read_text(encoding="utf-8"))
        self.assertIn("\t\tdataType: int64", bloc)
        self.assertIn("\t\tformatString: 0", bloc)
        self.assertNotIn("string", bloc)

    def test_ordre_texte_corrige_a_la_generation(self):
        self.config["fieldParameter"] = {"tables": ["Choix"]}
        self.generer()
        chemin = self.tables / "Choix.tmdl"
        neuf = chemin.read_text(encoding="utf-8")
        # une table créée par une version d'avant : l'ordre en texte
        ancien = neuf.replace("\t\tdataType: int64\n\t\tisHidden\n\t\tformatString: 0\n",
                              "\t\tdataType: string\n\t\tisHidden\n")
        self.assertNotEqual(ancien, neuf)
        chemin.write_text(ancien, encoding="utf-8")
        stats = self.generer()
        corrige = chemin.read_text(encoding="utf-8")
        bloc = self.colonne_ordre(corrige)
        self.assertIn("\t\tdataType: int64", bloc)
        self.assertIn("\t\tformatString: 0", bloc)
        # seule la colonne d'ordre a changé : les autres restent en texte
        self.assertEqual(corrige.count("dataType: string"), ancien.count("dataType: string") - 1)
        self.assertTrue(any("colonne d'ordre passée en nombre" in s for s in stats["fp_statuses"]))
        # une 2e génération n'a plus rien à faire
        self.generer()
        self.assertEqual(chemin.read_text(encoding="utf-8"), corrige)

    def test_champs_tries_par_ordre(self):
        # c'est le tri de Fields qui range les mesures dans un visuel : sans
        # lui, « [Weight cible] » passait devant « [Weight] »
        self.config["fieldParameter"] = {"tables": ["Choix"]}
        self.generer()
        chemin = self.tables / "Choix.tmdl"
        neuf = chemin.read_text(encoding="utf-8")
        champs = neuf.split("\tcolumn 'Choix Fields'\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("\t\tsortByColumn: 'Choix Ordre'", champs)
        # une table d'avant, sans ce tri : rajouté à la génération suivante
        ancien = neuf.replace("\t\tsourceColumn: [Value2]\n\t\tsortByColumn: 'Choix Ordre'\n",
                              "\t\tsourceColumn: [Value2]\n")
        self.assertNotEqual(ancien, neuf)
        chemin.write_text(ancien, encoding="utf-8")
        stats = self.generer()
        self.assertEqual(chemin.read_text(encoding="utf-8"), neuf)
        self.assertTrue(any("champs triés par l'ordre" in s for s in stats["fp_statuses"]))

    def test_tri_existant_respecte(self):
        texte = ("table T\n\n\tcolumn 'T Fields'\n\t\tsourceColumn: [Value2]\n"
                 "\t\tsortByColumn: Autre\n\n\tcolumn 'T Ordre'\n\t\tsourceColumn: [Value3]\n")
        self.assertEqual(gm.champs_tries(texte), texte)

    def test_ordre_deja_numerique_intact(self):
        texte = ("table T\n\n\tcolumn 'T Ordre'\n\t\tisHidden\n\t\tformatString: 0\n"
                 "\t\tsourceColumn: [Value3]\n\n\tcolumn Calcul\n\t\tdataType: string\n"
                 "\t\tsourceColumn: [Value5]\n")
        self.assertEqual(gm.ordre_en_nombre(texte), texte)


if __name__ == "__main__":
    unittest.main()
