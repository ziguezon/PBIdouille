# Exporte des diapos du guide en images, à deux endroits :
#   · bidouille\aide\*.png       l'aide intégrée à l'app (bidouille\tabs\dialog_guide.py) ;
#   · docs\ressources\guide\*.png  les articles de la documentation.
#
#     powershell -ExecutionPolicy Bypass -File docs\ressources\sources\exporter_aide.ps1
#
# À relancer après chaque changement de build_deck.py touchant ces diapos.
# Les diapos sont retrouvées par leur TITRE, pas par leur numéro : en ajouter
# une au guide ne décale rien ici. Il faut PowerPoint (rendu fidèle aux
# polices du guide).

$ErrorActionPreference = "Stop"
$ici = Split-Path -Parent $MyInvocation.MyCommand.Path
$outil = (Resolve-Path (Join-Path $ici "..\..\..")).Path
$deck = Join-Path $outil "docs\PBIdouille - Guide de demarrage rapide.pptx"

# dossier -> (fichier -> titre de la diapo), et la largeur de l'export
$exports = @(
    @{  # même table que PAGES dans dialog_guide.py
        dossier = Join-Path $outil "bidouille\aide"; largeur = 1600; pages = [ordered]@{
            "variations.png"        = "Comment les variations se ramifient"
            "parametres_champ.png"  = "Ce que reçoivent les paramètres de champ"
            "jetons.png"            = "Les jetons à connaître"
            "propagation.png"       = "Comment le formatage se propage"
            "propagation_carte.png" = "La carte se propage aussi"
            "gabarits.png"          = "Qui copie qui : gabarits et groupes"
            "regles.png"            = "Qui l'emporte, variation par variation"
        } },
    @{  # les diapos que citent les articles de docs\articles\
        dossier = Join-Path $outil "docs\ressources\guide"; largeur = 1280; pages = [ordered]@{
            "coup-d-oeil.png"          = "Un rapport, quatre onglets"
            "avant-de-commencer.png"   = "Avant de commencer"
            "lancer.png"               = "Lancer l'app et ouvrir un rapport"
            "variations.png"           = "Comment les variations se ramifient"
            "parametres-de-champ.png"  = "Ce que reçoivent les paramètres de champ"
            "jetons.png"               = "Les jetons à connaître"
            "generer.png"              = "Générer les mesures"
            "propagation.png"          = "Comment le formatage se propage"
            "propagation-carte.png"    = "La carte se propage aussi"
            "gabarits.png"             = "Qui copie qui : gabarits et groupes"
            "regles.png"               = "Qui l'emporte, variation par variation"
            "propager-colorer.png"     = "Propager et colorer"
            "chopchop.png"             = "ChopChop : ce que plus rien n'utilise"
            "filets.png"               = "Les filets de sécurité"
            "pepin.png"                = "En cas de pépin"
        } }
)

$pp = New-Object -ComObject PowerPoint.Application
try {
    $pres = $pp.Presentations.Open($deck, $true, $false, $false)
    foreach ($e in $exports) {
        New-Item -ItemType Directory -Force -Path $e.dossier | Out-Null
        foreach ($f in $e.pages.Keys) {
            $titre = $e.pages[$f]
            $trouvee = $null
            foreach ($s in $pres.Slides) {
                foreach ($sh in $s.Shapes) {
                    if ($sh.HasTextFrame -and $sh.TextFrame.HasText -and
                        $sh.TextFrame.TextRange.Text.Trim() -eq $titre) { $trouvee = $s; break }
                }
                if ($trouvee) { break }
            }
            if (-not $trouvee) { throw "diapo introuvable : $titre" }
            $haut = [int]($e.largeur * 9 / 16)
            $trouvee.Export((Join-Path $e.dossier $f), "PNG", $e.largeur, $haut)
            "  $f  <-  diapo $($trouvee.SlideIndex) : $titre"
        }
    }
    $pres.Close()
} finally {
    $pp.Quit()
}
