# 7 · Wireframe

[Documentation](../README.md) › **Wireframe** · voir aussi [Rapport](04-rapport.md), [ChopChop](08-chopchop.md)

> **Édition de développement seulement.** Cet onglet n'apparaît pas dans la version
> partagée de PBIdouille. Il s'active avec un fichier `.dev` à côté de `app.py`, ou avec
> la variable d'environnement `PBIDOUILLE_DEV=1`.

L'onglet **Wireframe** dessine chaque page du rapport à l'échelle, et permet de déplacer,
redimensionner, grouper, répartir et aligner les visuels sans ouvrir Power BI Desktop.

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

## Aligner les bords

**📐 Aligner les bords** range au pixel ce qui n'est décalé que de quelques pixels, sans
changer la mise en page. La tolérance se règle à côté du bouton, de 1 à 20 pixels (5 par
défaut), et elle est retenue.

| Avant | Après |
|---|---|
| Deux visuels à 3 pixels l'un de l'autre | Collés |
| Deux hauts à 2 pixels près | Alignés |
| Un visuel à 4 pixels du bord de la page | Sur le bord |
| Des gouttières de 10, 12 et 10 pixels | 10, 10 et 10 |
| Des marges de 16, 16 et 18 pixels | 16 partout (les marges ne prennent pas la valeur des gouttières) |
| Des positions à 381,65 | Des pixels entiers |

Les bords proches deviennent **une même ligne**. Quand une gouttière s'ajuste, c'est la
ligne qui bouge : tout ce qui était aligné dessus le reste. Une ligne prend la valeur la
plus fréquente parmi ses bords. À égalité, elle prend celle d'un bord déjà posé sur un
pixel entier : il a sans doute été placé exprès, l'autre a glissé.

Un bord qui n'a rien sur quoi s'aligner suit l'autre bord de son visuel. Un visuel qui ne
touche quelque chose que d'un côté se déplace donc d'un bloc, sans s'étirer.

Ce qui ne bouge pas :

- un écart plus grand que la tolérance, gouttière voulue comprise ;
- un vide de plus de 48 pixels, qui n'est pas une gouttière ;
- l'épaisseur d'un trait de séparation ;
- la taille des visuels : rendre des cases égales, c'est le rôle de **Répartir**.

Le bouton s'applique, dans cet ordre, à :

1. la sélection multiple ;
2. l'élément sélectionné (un groupe vient avec tout son contenu) ;
3. tout le niveau actif, contenu des groupes compris.

Le reste de la page sert d'appui et ne bouge pas. Dans un groupe, le cadre du groupe sert
de bord de page. Un groupe dont la boîte épousait son contenu l'épouse encore après ; un
groupe plus grand que son contenu garde sa boîte.

Une gouttière voulue plus petite que la tolérance se refermerait : garder la tolérance
sous la plus petite gouttière du rapport. L'alignement est fait en mémoire, comme un
déplacement : il reste à l'enregistrer, et Ctrl+Z l'annule.

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

Un import est aussi une sauvegarde. Après la fermeture de l'app, **Ctrl+Z** ne l'annule
plus, mais [🕘 Restaurer une sauvegarde…](01-barre-du-haut.md#restaurer-une-sauvegarde)
retire ses visuels. Un import fait avec une version plus ancienne n'a que sa liste
`import_manifest.txt` : ses visuels se retirent à la main.

**Annuler**, ou **Ctrl+Z**, défait le dernier geste ou la dernière action, y compris un
enregistrement.

Chaque écriture est sauvegardée dans `_backupsPBIdouille\_wireframe_backups`. Elle reste
aussi restaurable depuis [🕘 Restaurer une sauvegarde…](01-barre-du-haut.md#restaurer-une-sauvegarde).

## Importer un gabarit

Le panneau **Gabarits** copie des éléments d'un autre rapport :

1. Cocher **Gabarits** pour ouvrir le panneau.
2. Cliquer **Choisir…** et sélectionner un `.pbip`.
3. Choisir une page, puis un modèle. Chaque groupe racine et chaque visuel isolé en est un.
4. Choisir, pour chaque indicateur du modèle, celui de ce rapport qui le remplace.
5. Cliquer **Importer dans la page courante**.

Le modèle garde sa position et sa taille d'origine.

### Changer les indicateurs

Un gabarit vient d'un autre rapport : ses visuels citent **ses** indicateurs. Sous la liste
des modèles, une rangée par indicateur que cite le modèle choisi, avec à côté la liste des
indicateurs de ce rapport. Par défaut, chacun se garde lui-même ; un indicateur que ce
rapport n'a pas est marqué « absent de ce rapport ».

Un indicateur est reconnu dans un modèle de deux façons :

- une **mesure** qui est l'indicateur ou une de ses déclinaisons : `Body Fat % 30d avg`
  est une déclinaison de `Body Fat %` ;
- un **filtre** ou un **segment** dont la valeur est l'indicateur : `'Body Fat %'`.

À l'import, avec `Body Fat %` remplacé par `Weight` :

| Dans le gabarit | Dans le rapport |
|---|---|
| La mesure `Body Fat % 30d avg` | `Weight 30d avg` |
| Le filtre ou segment `'Body Fat %'` | `'Weight'` |
| Une colonne qui s'appelle `Body Fat %` | Inchangée : ce n'est pas une mesure |
| Un titre « Évolution de Body Fat % » | Inchangé : à retoucher dans Desktop |

Les indicateurs reconnus sont ceux du gabarit (lus dans son modèle, avec son
`measures_config.json` s'il en a un) et ceux de ce rapport.

Après l'import, les mesures citées que ce rapport n'a pas sont signalées : les visuels
qui les utilisent resteront vides. Pour le reste, le modèle cite les mêmes tables et
colonnes que dans le gabarit (dates, paramètres de champ) : ce rapport doit les avoir.

---

← [6 Radiographie](06-radiographie.md) · [Sommaire](../README.md) · [8 ChopChop](08-chopchop.md) →
