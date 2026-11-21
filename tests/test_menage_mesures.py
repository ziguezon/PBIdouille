"""L'écrasement des mesures et le ménage des orphelines sont indépendants."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bidouille" / "moteurs"))
import generate_measures as gm


class MenageMesures(unittest.TestCase):
    def verifier(self, modele, ecraser, nettoyer):
        table = modele / "definition/tables/Kpi.tmdl"
        table.parent.mkdir(parents=True)
        table.write_text("table Kpi\n\n\tmeasure Ventes = 1\n\t\tdisplayFolder: Base\n",
                         encoding="utf-8")
        variantes = {
            "double": {"namePattern": "{base} double", "dax": "{baseRef} * 2"},
            "ancienne": {"namePattern": "{base} ancienne", "dax": "{baseRef} * 7"},
        }
        config = {"settings": {"sourceTable": "Kpi", "sourceFolder": "Base"},
                  "variations": variantes}

        def generer(simuler=False):
            return gm.generate(modele, config, dry_run=simuler, log=lambda *_: None)

        def mesures():
            blocs = gm.split_members(table.read_text(encoding="utf-8-sig"))
            return [gm.measure_info(texte) for genre, texte in blocs if genre == "measure"]

        generer()
        origine = {m["name"]: m for m in mesures()}
        self.assertEqual(set(origine), {"Ventes", "Ventes double", "Ventes ancienne"})
        del variantes["ancienne"]
        variantes["double"]["dax"] = "{baseRef} * 3"
        config["settings"].update(overwriteExisting=ecraser, removeOrphans=nettoyer)

        for tour in range(2):
            avant = table.read_bytes()
            apercu = generer(simuler=True)
            self.assertEqual(table.read_bytes(), avant)
            resultat = generer()
            attendues = ["Ventes ancienne"] if nettoyer and tour == 0 else []
            self.assertEqual(apercu["removed"], attendues)
            self.assertEqual(resultat["removed"], attendues)
            lues = mesures()
            par_nom = {m["name"]: m for m in lues}
            self.assertEqual(len(lues), len(par_nom))
            self.assertEqual(par_nom["Ventes"], origine["Ventes"])
            double = par_nom["Ventes double"]
            self.assertEqual(double["lineage"], origine["Ventes double"]["lineage"])
            if ecraser:
                self.assertIn("* 3", double["dax"])
            else:
                self.assertEqual(double, origine["Ventes double"])
            self.assertEqual("Ventes ancienne" in par_nom, not nettoyer)
            if not nettoyer:
                self.assertEqual(par_nom["Ventes ancienne"], origine["Ventes ancienne"])

    def test_combinaisons(self):
        for ecraser in (False, True):
            for nettoyer in (False, True):
                with self.subTest(ecraser=ecraser, nettoyer=nettoyer):
                    with tempfile.TemporaryDirectory() as dossier:
                        self.verifier(Path(dossier) / "Modele.SemanticModel", ecraser, nettoyer)


if __name__ == "__main__":
    unittest.main()
