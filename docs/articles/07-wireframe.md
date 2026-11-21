# 7 · Wireframe

[Documentation](../README.md) › **Wireframe** · voir aussi [Rapport](04-rapport.md), [ChopChop](08-chopchop.md)

> **Édition de développement seulement.** Cet onglet n'apparaît pas dans la version
> partagée de PBIdouille. Il s'active avec un fichier `.dev` à côté de `app.py`, ou avec
> la variable d'environnement `PBIDOUILLE_DEV=1`.

L'onglet **Wireframe** dessine chaque page du rapport à l'échelle, et permet de déplacer,
redimensionner, grouper et répartir les visuels sans ouvrir Power BI Desktop.

![L'onglet Wireframe, sur une page avec des groupes imbriqués](../ressources/images/wireframe_onglet.png)

Power BI Desktop peut rester ouvert. Après l'écriture, le fermer **sans enregistrer** et
rouvrir le `.pbip` : enregistrer dans Desktop remettrait les visuels à leur ancienne place.

## Lire une page

| Zone | Contenu |
|---|---|
| **Page** | La page affichée, avec ses dimensions |
| **Plan** | Chaque visuel à sa position et à sa taille réelles. Un visuel caché est en pointillé |
| **Structure de la page** | Les groupes et les visuels, synchronisés avec le plan |
| **Sélection** | Position, type, groupe parent, champs utilisés et clés de formatage |

🎨 indique une matrice qui porte un gabarit de couleur pour
[Colorer](04-rapport.md#colorer-les-matrices). **Ouvrir visual.json** ouvre le fichier du
visuel choisi.

## Travailler dans un groupe

Les gestes agissent sur le **niveau actif** : la page, ou le groupe dans lequel on est
entré.

- **Double-cliquer** sur un groupe, ou cliquer **Entrer dans le groupe**, pour y entrer.
- **Échap**, ou un double-clic sur le fond, pour remonter d'un niveau.
- Le chemin au-dessus du plan indique le niveau, et chaque segment est cliquable.

Hors du niveau actif, tout est grisé et inactif.

## Les gestes

| Geste | Effet |
|---|---|
| Glisser un élément **sur un voisin** | L'insère à côté de lui, dans sa rangée ou sa colonne |
| Glisser un élément **ailleurs** | Le place librement, aimanté aux bords proches |
| Glisser le **bord** d'un élément | Le redimensionne |
| Glisser une **bordure verte** | Déplace la frontière entre les éléments collés |
| Redimensionner un **groupe** | Met tout son contenu à l'échelle |
| **Ctrl+clic**, ou lasso depuis le fond | Sélectionne plusieurs éléments |

Les éléments restent dans la page, et l'aimantation agit à 10 pixels.

## Répartir

**Répartir également dans la zone** range les éléments en grille, à parts égales. Il
s'applique, dans cet ordre, à :

1. la sélection multiple ;
2. le contenu du groupe sélectionné ;
3. tout le niveau actif.

## Grouper et dégrouper

- **Grouper** crée un groupe avec au moins deux éléments sélectionnés.
- **Dégrouper** dissout le groupe sélectionné, et ses enfants remontent d'un niveau.

Rien ne bouge à l'écran. Ces deux actions sont écrites immédiatement, avec une sauvegarde.

## Enregistrer et annuler

Les déplacements s'accumulent à l'écran. **Enregistrer** affiche leur nombre et s'allume
tant qu'il reste quelque chose à écrire. Seule la position des visuels change dans leurs
fichiers.

Changer de page ou cliquer **Recharger** avec des déplacements non enregistrés ouvre un
avertissement :

| Choix | Effet |
|---|---|
| **Enregistrer** | Écrit les positions, puis continue |
| **Abandonner les changements** | Oublie les déplacements, puis continue |
| **Rester ici** | Reste sur la page, sans rien perdre |

Changer de rapport ou fermer l'app ne pose pas cette question : enregistrer avant.

Après réouverture du projet, **Restaurer une sauvegarde…** permet de retirer les visuels d’un import enregistré avec un manifeste JSON. Les anciens imports accompagnés uniquement d’`import_manifest.txt` doivent être vérifiés à partir de cette liste.

**Annuler**, ou **Ctrl+Z**, défait le dernier geste ou la dernière action, y compris un
enregistrement.

Chaque écriture est sauvegardée dans `_backupsPBIdouille\_wireframe_backups`. Elle reste
aussi restaurable depuis [🕘 Restaurer une sauvegarde…](01-barre-du-haut.md#restaurer-une-sauvegarde).

## Importer un gabarit

Le panneau **Gabarits** copie des éléments d'un autre rapport :

1. Cocher **Gabarits** pour ouvrir le panneau.
2. Cliquer **Choisir…** et sélectionner un `.pbip`.
3. Choisir une page, puis un modèle. Chaque groupe racine et chaque visuel isolé en est un.
4. Cliquer **Importer dans la page courante**.

Le modèle garde sa position et sa taille d'origine. Il cite les champs du modèle sémantique
du gabarit : vérifier que le rapport cible possède ces mêmes tables et mesures.

---

← [6 Radiographie](06-radiographie.md) · [Sommaire](../README.md) · [8 ChopChop](08-chopchop.md) →
