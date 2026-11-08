---
title: Allumage et extinction des écrans (auto-power)
section: players
roles: [CMS_ORG_ADMIN]
keywords: [écran, alimentation, allumage, extinction, heures d'ouverture, auto-power, veille, RS232, CEC, coupure, rallumage, horaires, fermeture, énergie, offline]
---

# Allumage et extinction des écrans (auto-power)

Vitrail peut **allumer et éteindre vos écrans automatiquement** selon les heures d'ouverture
du site : plus d'écran allumé toute la nuit, plus d'oubli de rallumage le matin. Le player,
lui, reste allumé et connecté — seul l'écran est piloté.

## Comment activer

1. Renseignez les **horaires d'ouverture** du site (Sites → votre site) : jours, heures,
   exceptions par date (jours fériés, événements).
2. Activez l'**auto-power** du site, avec des **marges** optionnelles : allumer un peu avant
   l'ouverture (lead) et éteindre un peu après la fermeture (lag).
3. Sur chaque player (drawer → Affichage), choisissez le **mode d'alimentation** :
   - **Suivre les horaires du site** (recommandé) ;
   - **Fenêtre personnalisée** : horaires propres au player (ex. vitrine allumée plus tard) —
     sans les marges du site ;
   - **Toujours allumé** ; ou **Manuel** (aucun pilotage automatique).

## Comment l'écran est piloté

Selon l'équipement, le player utilise (dans cet ordre de préférence) :
- un **contrôleur d'écran** RS232 ou IP (écrans professionnels) ;
- **HDMI-CEC** (téléviseurs compatibles) ;
- à défaut, le **repli « sortie vidéo »** : le player coupe son signal vidéo et l'écran se met
  en veille (à activer dans la configuration d'affichage du player). Fonctionne sur Linux,
  Raspberry Pi, Windows, Android et BrightSign.

## Ça marche aussi sans serveur (offline)

Chaque player reçoit à l'avance ses **fenêtres d'allumage sur 14 jours** (heure locale du
site, marges et exceptions comprises). Si le serveur est injoignable plus de quelques minutes,
le player **pilote son écran tout seul** ; à la reconnexion, l'état voulu est ré-appliqué
automatiquement. Un player qui redémarre pendant une coupure retrouve aussi ses fenêtres.

## Commande manuelle et exceptions

- Les boutons **Allumer / Éteindre l'écran** du drawer player sont **ponctuels** : le
  programme reprend la main au prochain créneau. Pour une coupure durable, passez le player
  en mode **Manuel**.
- Un **event** peut cocher « garder les écrans allumés » pour maintenir l'affichage pendant
  une diffusion exceptionnelle hors horaires.

## Alertes : la nuit ne sonne plus

Un player dont l'écran est éteint par le programme peut apparaître **hors ligne** (certains
appareils, comme les box Android, coupent aussi leur réseau en veille). Dans ce cas il est
marqué **« Veille programmée »** — pas d'alerte, pas d'état critique. En revanche, si un
player n'est **pas revenu** quelques minutes après l'heure d'ouverture, une alerte « parc pas
réveillé » est levée.
