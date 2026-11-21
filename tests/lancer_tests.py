"""Lance chaque script dans son propre interpréteur et distingue les tests ignorés."""
from pathlib import Path
import subprocess
import sys


def main():
    dossier = Path(__file__).resolve().parent
    comptes = {"réussis": 0, "ignorés": 0, "échoués": 0}
    for script in sorted(dossier.glob("test_*.py")):
        execution = subprocess.run([sys.executable, "-X", "utf8", "-B", str(script)],
                                   cwd=dossier.parent, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
        lignes = execution.stdout.splitlines()
        motif = next((s for s in lignes if s.startswith("IGNORE")), "")
        if execution.returncode:
            statut = "échoués"
            print(execution.stdout)
        else:
            statut = "ignorés" if motif else "réussis"
        comptes[statut] += 1
        print(f"{script.name} — {motif or statut}", flush=True)
    print(" · ".join(f"{n} {statut}" for statut, n in comptes.items()))
    return int(bool(comptes["échoués"]))


if __name__ == "__main__":
    sys.exit(main())
