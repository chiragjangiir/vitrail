---
title: Validations (workflow d'approbation)
section: workflow
roles: []
keywords: [validation, approbation, approval, workflow, revue, soumettre, rejeter, modifications demandées, resoumettre, file, valideur, reviewer, campagne, motif, export, email de décision, playlist gouvernée, nœud propriétaire, gouvernance, modération, lecture seule]
---

# Validations (workflow d'approbation)

La page **Validations** (`/approvals`, sous Campagnes dans le menu) centralise les
**demandes d'approbation** : une ressource soumise ne peut pas être publiée tant qu'un
valideur ne l'a pas approuvée. Le circuit s'applique aux **campagnes retail media**
(soumises depuis le CMS ou par un annonceur depuis le portail) et aux **playlists
gouvernées** (gouvernance hiérarchique §XVIII, voir « Playlists sous modération »
plus bas).

## Le circuit

1. **Soumettre** : bouton « Soumettre pour approbation » (drawer campagne) ou soumission
   automatique depuis le portail annonceur. Une seule demande **active** par ressource.
2. **Revue** : la demande apparaît dans la file des valideurs avec tout le contexte —
   créatifs **visionnables** (lecteur intégré), annonceur, période, SOV demandée et
   **SOV réalisable**, tarif/devis, cibles nommées, **occupation projetée** des écrans
   avec le détail des campagnes déjà en place.
3. **Décision** : **Approuver**, **Rejeter** ou **Demander des modifications** — le motif
   est **obligatoire** pour un rejet ou une demande de modifications. La case « Notifier
   l'annonceur par email » (cochée par défaut) envoie un récapitulatif de la décision aux
   comptes portail de l'annonceur, dans leur langue.
4. **Resoumission** : après « modifications demandées », le soumetteur corrige et
   resoumet ; l'historique (timeline + commentaires) est conservé.
5. **Publication** : une campagne **en revue ne peut pas être publiée** ; une campagne
   approuvée se publie normalement (l'approbation de la demande **approuve aussi ses
   créatifs en attente** — un créatif ajouté après repart en revue de créatif).

## Qui valide ?

Les comptes disposant des permissions **approvals : approve / reject** (org-admin et rôle
Approbateur par défaut). Les valideurs voient la **file de l'organisation entière** ; un
soumetteur ne voit que **ses** demandes. Une **cloche** dans la barre du haut signale les
demandes en attente.

## Gestion de la file

- **Pastilles de comptage** par statut (en revue, urgentes < 48 h de l'échéance…),
  recherche, filtre.
- **Exports CSV / PDF** de la file (avec motifs), filtre courant respecté.
- **Ménage** : les demandes en statut terminal (approuvée, rejetée, annulée, publiée)
  peuvent être supprimées de la liste — la trace reste dans le journal d'audit.
- La **suppression de la ressource** purge ses demandes.

## Playlists sous modération (gouvernance hiérarchique)

Une playlist ou un média peut appartenir à un **nœud de gouvernance** (champ « Nœud
propriétaire » dans les réglages de la playlist / le panneau du média). Deux effets :

- **Écriture réservée** : seuls les administrateurs de ce nœud — ou d'un nœud **parent**
  — peuvent modifier ou supprimer le contenu. Les niveaux inférieurs le voient en
  **lecture seule** (comprendre ce qui passe au-dessus de soi fait partie du métier) ;
  un nœud **voisin** ne le voit pas du tout.
- **Modération** : si le nœud porte « **Contenu soumis à approbation** » (case dans la
  page Gouvernance, héritée par les nœuds créés en dessous), la publication directe est
  **refusée**. Le bouton devient « **Soumettre à l'approbation** » : c'est l'approbation
  qui **publie le brouillon**. Le valideur voit l'**aperçu du brouillon soumis** (items,
  durées, vignettes) dans sa file.

Les **modérateurs** sont les administrateurs du **nœud parent** le plus proche (la
hiérarchie est l'organigramme de validation : le contenu d'un magasin est validé par sa
région), avec repli sur les org-admins si aucun ancêtre n'a d'administrateur. Retirer la
modération d'un nœud est réservé à un administrateur d'un nœud **parent** — un nœud ne se
dispense pas lui-même de modération.

## Ne viser qu'une PARTIE des écrans d'un nœud

Par défaut, un programme rattaché à un nœud diffuse sur **tous** les écrans de ce nœud et
de son sous-arbre. Pour n'en viser qu'une partie — le cas classique « écrans d'entrée » vs
« rayon boucherie » dans un même magasin — ajoutez des **cibles** au programme (page
Programmation) : elles **restreignent** le périmètre du nœud.

- Les cibles ne peuvent que **retirer** des écrans, jamais en ajouter : un programme
  gouverné ne sort jamais de son nœud.
- **Sans cible = tout le nœud.** C'est le comportement par défaut, rien à faire.
- Pratique : créez un **groupe de players** « Entrées » et posez **une seule cible** pour
  toute l'enseigne, au lieu d'un ciblage magasin par magasin.
- Une cible qui ne retient **aucun** écran du nœud est **refusée à l'enregistrement**, en
  la nommant. Le nombre d'écrans réellement retenus est affiché à côté du sélecteur.
- Un niveau inférieur ne peut **jamais** restreindre une couche **héritée** : le magasin ne
  décide pas que la playlist nationale saute son écran boucherie.
- La page Gouvernance signale les écrans du nœud qu'**aucun programme local ne vise** —
  utile pour repérer un écran neuf oublié dans son groupe (il ne reçoit que l'héritage).

## À ne pas confondre

La case « **Approbation des créatifs requise** » (page Campagnes) est un contrôle
**par créatif** : elle modère chaque fichier ajouté à une campagne déjà validée. Le
workflow de cette fiche valide la **campagne entière** (commercial + contenu) avant
publication. Les deux se combinent naturellement.
