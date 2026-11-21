# 8 · ChopChop

[Documentation](../README.md) › **ChopChop** · voir aussi [Variations](03-1-variations.md), [Restaurer une sauvegarde](01-barre-du-haut.md#restaurer-une-sauvegarde)

L'onglet **ChopChop** repère ce que plus rien n'utilise dans un rapport : mesures,
colonnes et tables entières.

Le verdict couvre le rapport sélectionné et son modèle. D’autres rapports peuvent utiliser le même modèle. Si le dossier du rapport est vide ou inaccessible, ou si un fichier JSON est illisible, l’analyse s’interrompt et la sélection à supprimer est effacée. Corriger le problème indiqué, puis choisir **Réanalyser**. Le classeur et le CSV indiquent le rapport analysé, y compris dans le CSV de la ligne de commande.

![L'onglet ChopChop](../ressources/images/chopchop_onglet.png)

La ligne du haut résume le résultat :

```
133 mesures · 51 inutilisée(s) (dont 51 générée(s) depuis le config) · 111 colonnes · 40 inutilisée(s) · 4 table(s) entièrement inutilisée(s)
```

| Fonction | Version partagée | Édition de développement |
|---|---|---|
| Analyse, filtre, export | Oui | Oui |
| Suppression | Non | Oui |

![Diapo du guide : ChopChop : ce que plus rien n'utilise](../ressources/guide/chopchop.png)

## Lire le résultat

| Groupe | Contenu |
|---|---|
| 🗑 **Tables entièrement inutilisées** | Aucune relation, aucun visuel et aucune mesure utilisée n'en dépend |
| 📏 **Mesures inutilisées · aucune référence** | Rien ne cite la mesure |
| 📏 **Mesures inutilisées · used by unused** | Seules d'autres mesures inutilisées la citent |
| 📏 **Mesures utilisées** | Référence, à titre d'information |
| 🔢 **Colonnes inutilisées · aucune référence** | Rien ne cite la colonne |
| 🔢 **Colonnes · used by unused** | Seules des mesures inutilisées la citent |
| 🔢 **Colonnes utilisées** | Référence, à titre d'information |

La colonne **Référencé par** résume ce qui utilise l'objet, comme
`rapport (2 fichiers), 7 tables calculées`. Déplier une ligne affiche chaque référence.

**Table** limite l'affichage à une table.

### Ce qui compte comme une utilisation

- **Dans le rapport** : visuels, segments, filtres, tris, formatage conditionnel et signets.
- **Dans le modèle** : DAX, relations, colonnes de tri, hiérarchies et paramètres de champ.
- **Dans Power Query** : une colonne citée par une autre requête est conservée.

Une table lue par une autre requête Power Query n'est jamais proposée, ni ses colonnes :
les retirer casserait l'actualisation de cette requête.

### Les étiquettes

| Étiquette | Signification |
|---|---|
| `[générée]` | La mesure vient de `measures_config.json` |
| `[calculée]` | Colonne calculée en DAX |
| `[importée]` | Colonne chargée par Power Query |
| `[table calc.]` | Colonne d'une table calculée. Elle se modifie dans le DAX de la table |
| `[table entière]` | La ligne vise toute la table |

## Une mesure `[générée]` inutilisée

La supprimer ici ne sert à rien : la prochaine génération la recrée. Pour la faire
disparaître :

1. Retirer sa variation, ou l'exclure pour ce KPI, dans [Variations](03-1-variations.md).
2. Lancer **Générer les mesures** avec **Supprimer les orphelines** coché.

Si la variation doit rester pour d'autres KPI, la mesure inutilisée peut aussi être
simplement conservée.

## Exporter l'audit

**Exporter…** écrit un fichier `.csv` ou `.xlsx`, avec une ligne par mesure et par colonne,
utilisées comprises.

Colonnes : `Type`, `Nom`, `Table`, `Statut`, `Référencé par`,
`Détail des référenceurs` et `Générée`.

## Supprimer

> **Édition de développement seulement.**

1. Si Power BI Desktop est ouvert, y enregistrer son travail.
2. Cocher les objets. La case d'un groupe coche tout le groupe, ou seulement la table
   filtrée. **Cocher manuelles seulement** écarte les mesures générées.
3. Cliquer **Supprimer la sélection** et lire la confirmation.
4. Fermer Desktop **sans enregistrer**, puis rouvrir le `.pbip`. Enregistrer remettrait
   ce qui vient d'être supprimé.

| Objet | Ce qui est retiré |
|---|---|
| Mesure | Son bloc dans le fichier de la table |
| Colonne calculée | Son bloc dans le fichier de la table |
| Colonne importée | Son bloc, plus une étape `Colonnes retirées (ChopChop)` en fin de requête Power Query |
| Table entière | Son fichier, et sa référence dans le modèle |

Les mesures qui dépendent d'un objet supprimé et sont elles-mêmes inutilisées partent avec
lui, et la confirmation en donne le nombre. Une suppression se défait avec
[🕘 Restaurer une sauvegarde…](01-barre-du-haut.md#restaurer-une-sauvegarde), dans la barre
du haut. Si une requête Power Query n'est pas reconnue,
la colonne quitte le modèle et un avertissement demande de modifier la requête à la main.

---

← [7 Wireframe](07-wireframe.md) · [Sommaire](../README.md)
