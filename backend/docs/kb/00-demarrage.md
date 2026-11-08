---
title: Démarrer avec Vitrail
section: getting-started
roles: []
keywords: [démarrage, prise en main, dashboard, organisation, rôles, premiers pas]
---

# Démarrer avec Vitrail

Vitrail est une plateforme d'affichage dynamique (digital signage) : vous diffusez des
contenus (vidéos, images, pages web, flux d'actualité) sur des écrans pilotés par des
players, depuis une interface web centralisée.

## Les grands concepts

- **Organisation** : votre espace de travail. Tout votre contenu, vos players et vos
  utilisateurs y sont isolés (aucune autre organisation ne voit vos données).
- **Player** : le logiciel installé sur l'appareil branché à un écran (NUC, Raspberry Pi,
  PC Windows, box Android, Chromebox, ou une simple extension Chrome). Il reçoit ses
  consignes du serveur — jamais l'inverse — et continue de fonctionner hors-ligne.
- **Média** : un contenu importé (vidéo, image, document) ou dynamique (page web, flux).
- **Playlist** : une suite de médias jouée en boucle.
- **Programmation (schedule)** : quand et sur quels players une playlist est diffusée.
- **Event** : une diffusion ponctuelle ou déclenchée qui prend la priorité sur la
  programmation normale (promotion, annonce, spot horaire).

## Le parcours type

1. **Enrôler un player** : générez un token de provisioning, installez le player sur
   l'appareil, il apparaît dans la liste des Players.
2. **Importer du contenu** dans la Médiathèque.
3. **Créer une playlist** avec ce contenu.
4. **Programmer** la playlist sur un ou plusieurs players.

L'écran affiche le contenu en quelques secondes une fois la programmation enregistrée.

## Rôles et permissions

Vitrail gère des rôles (Org Admin, Designer, Scheduler, Approbateur, Lecteur de
rapports, Opérateur magasin…). Chaque rôle donne accès à un sous-ensemble de modules.
Si un menu ou une action vous manque, c'est probablement une question de rôle :
demandez à votre administrateur d'organisation de vous l'attribuer.
