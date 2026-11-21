"""Crée un PBIP fictif autonome dans un dossier neuf pour les essais de Desktop."""
import argparse
import json
from pathlib import Path

from openpyxl import Workbook


def creer(projet):
    projet = Path(projet)
    projet.mkdir(parents=True, exist_ok=False)
    rapport = projet / "Atelier.Report"
    modele = projet / "Atelier.SemanticModel"
    schema = "https://developer.microsoft.com/json-schemas/fabric/item/"
    page = "a0000000000000000001"
    visuel = "b0000000000000000001"

    def ecrire(path, contenu):
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contenu, dict):
            contenu = json.dumps(contenu, ensure_ascii=False, indent=2) + "\n"
        path.write_text(contenu, encoding="utf-8")

    pbip = projet / "Atelier.pbip"
    ecrire(pbip, {"version": "1.0", "artifacts": [{"report": {"path": rapport.name}}],
                  "settings": {"enableAutoRecovery": True}})
    ecrire(rapport / "definition.pbir", {"version": "4.0", "datasetReference": {
        "byPath": {"path": "../" + modele.name}}})
    ecrire(modele / "definition.pbism", {"version": "4.0", "settings": {}})
    ecrire(modele / "definition/database.tmdl", "database\n\tcompatibilityLevel: 1604\n")
    ecrire(modele / "definition/model.tmdl",
           "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
           "\tsourceQueryCulture: en-US\n\nref table Ventes\n")
    ecrire(modele / "definition/tables/Ventes.tmdl",
           "table Ventes\n\n\tmeasure Total = SUM(Ventes[Montant])\n\t\tdisplayFolder: Base\n"
           "\n\tmeasure Lignes = COUNTROWS(Ventes)\n\t\tdisplayFolder: Base\n"
           "\n\tcolumn Montant\n\t\tdataType: int64\n\t\tsourceColumn: Montant\n"
           "\n\tpartition Ventes = m\n\t\tmode: import\n\t\tsource =\n"
           "\t\t\t#table(type table [Montant = Int64.Type], {{4}, {8}})\n")
    definition = rapport / "definition"
    def objet(path, type_schema, **champs):
        ecrire(definition / path, {"$schema": schema + "report/definition/" + type_schema
                                   + "/schema.json", **champs})
    objet("version.json", "versionMetadata/1.0.0", version="2.0.0")
    objet("report.json", "report/2.0.0", themeCollection={})
    objet("pages/pages.json", "pagesMetadata/1.0.0", pageOrder=[page], activePageName=page)
    prefixe = "pages/" + page + "/"
    objet(prefixe + "page.json", "page/2.0.0", name=page, displayName="Contrôle",
          displayOption="FitToPage", height=720, width=1280)
    objet(prefixe + "visuals/" + visuel + "/visual.json", "visualContainer/2.0.0",
          name=visuel, position={"x": 48, "y": 48, "width": 420, "height": 160},
          visual={"visualType": "pivotTable", "query": {"queryState": {"Values": {
              "projections": [{"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Ventes"}},
                                                     "Property": "Total"}}, "queryRef": "Ventes.Total"}]}}}})
    ecrire(projet / "measures_config.json", {
        "settings": {"sourceTable": "Ventes", "sourceFolder": "Base"},
        "variations": {"double": {"namePattern": "{base} double", "dax": "{baseRef} * 2",
                                  "inFieldParameter": True}},
        "fieldParameter": {"tables": ["Choix"]}})
    wb = Workbook()
    ws = wb.active
    ws.title = "TD_Indicateurs"
    ws.append(["mesure", "couleur_fill", "couleur_text"])
    ws.append(["Total", "#336699", "#FFFFFF"])
    ws.append(["Lignes", "#008866", "#FFFFFF"])
    wb.save(projet / "TD_Indicateurs.xlsx")
    wb.close()
    return pbip


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dossier", type=Path, help="Nouveau dossier de destination")
    print(creer(parser.parse_args().dossier))
