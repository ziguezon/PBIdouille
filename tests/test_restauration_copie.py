"""Restauration d'une copie de projet, avec ou sans l'original."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bidouille" / "moteurs"))
import backup_restore as br


class RestaurationCopie(unittest.TestCase):
    def test_copie_et_deplacement(self):
        for deplace in (False, True):
            with self.subTest(deplace=deplace), tempfile.TemporaryDirectory() as dossier:
                a, b = (Path(dossier) / nom for nom in ("A", "B"))
                a.mkdir()
                cible = Path("Modele.SemanticModel/definition/tables/Kpi.tmdl")
                (a / cible).parent.mkdir(parents=True)
                (a / cible).write_bytes(b"avant")
                session = br.BackupSession(br.backup_root(a, "_tmdl_backups"), "Mesures", a)
                session.save(a / cible)
                session.close()
                (a / cible).write_bytes(b"original")
                if deplace:
                    a.rename(b)
                else:
                    shutil.copytree(a, b)
                (b / cible).write_bytes(b"copie")
                info, = br.list_sessions(b)
                self.assertEqual(Path(info["racine"]), b)
                apercu = br.restore_session(info["dossier"], b, dry_run=True)
                self.assertEqual(apercu["restaurés"], [str(cible)])
                self.assertEqual((b / cible).read_bytes(), b"copie")
                resultat = br.restore_session(info["dossier"], b)
                self.assertEqual((b / cible).read_bytes(), b"avant")
                br.restore_session(resultat["sauvegarde_avant"], b)
                self.assertEqual((b / cible).read_bytes(), b"copie")
                if deplace:
                    self.assertFalse(a.exists())
                else:
                    self.assertEqual((a / cible).read_bytes(), b"original")

    def test_session_archivee_sans_projet_selectionne(self):
        with tempfile.TemporaryDirectory() as dossier:
            projet = Path(dossier) / "projet"
            projet.mkdir()
            cible = projet / "table.tmdl"
            cible.write_bytes(b"avant")
            session = br.BackupSession(Path(dossier) / "archives", "Mesures", projet)
            session.save(cible)
            session.close()
            cible.write_bytes(b"apres")
            br.restore_session(session.dir)
            self.assertEqual(cible.read_bytes(), b"avant")

    def test_classeur_externe(self):
        with tempfile.TemporaryDirectory() as dossier:
            projet = Path(dossier) / "projet"
            externe = Path(dossier) / "indicateurs.xlsx"
            externe.write_bytes(b"avant")
            session = br.BackupSession(br.backup_root(projet, "_indicateurs_backups"),
                                       "Excel des indicateurs", projet)
            session.save(externe)
            session.close()
            externe.write_bytes(b"apres")
            apercu = br.restore_session(session.dir, projet, dry_run=True)
            self.assertEqual(apercu["restaurés"], [str(externe.resolve())])
            self.assertEqual(externe.read_bytes(), b"apres")
            resultat = br.restore_session(session.dir, projet)
            self.assertEqual(resultat["restaurés"], apercu["restaurés"])
            self.assertEqual(externe.read_bytes(), b"avant")
            br.restore_session(resultat["sauvegarde_avant"], projet)
            self.assertEqual(externe.read_bytes(), b"apres")

    def test_ancienne_sauvegarde_sans_manifeste(self):
        with tempfile.TemporaryDirectory() as dossier:
            projet = Path(dossier)
            cible = projet / "Modele.SemanticModel/definition/tables/Kpi.tmdl"
            cible.parent.mkdir(parents=True)
            session = projet / "_tmdl_backups/20260101_120000"
            session.mkdir(parents=True)
            (session / cible.name).write_bytes(b"avant")
            resultat = br.restore_session(session, projet)
            self.assertEqual(cible.read_bytes(), b"avant")
            br.restore_session(resultat["sauvegarde_avant"], projet)
            self.assertFalse(cible.exists())


if __name__ == "__main__":
    unittest.main()
