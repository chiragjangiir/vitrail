---
title: Diffusion à la demande (VOD)
section: content
roles: []
keywords: [VOD, à la demande, on-demand, takeover, diffuser maintenant, lecture immédiate, magasin, promo flash, déclenchement]
---

# Diffusion à la demande (VOD)

La page **On-Demand (VOD)** permet de **diffuser un contenu immédiatement** sur des écrans,
par-dessus la programmation en cours — sans toucher aux playlists ni aux programmes. Cas
d'usage : promo flash, annonce en magasin, démonstration à un client.

## Créer une config VOD

Une config VOD regroupe des **médias** (vidéos, images, documents — et le média
**Entrée HDMI** pour basculer une source externe) et une **cible**, au choix :

- **Players choisis** : vous cochez les players un par un — tous du **même site** ;
- **Site entier** : vous choisissez un site, et **tous ses players** sont ciblés. La cible
  est *dynamique* : un player installé sur ce site plus tard reçoit automatiquement le
  pré-téléchargement et les déclenchements, **sans rouvrir la config**. C'est le mode à
  privilégier pour un magasin dont le parc bouge.

Dès la config enregistrée, les médias sont **pré-téléchargés** sur les players
concernés : le déclenchement est instantané, même sur une connexion lente.

## Déclencher une diffusion

Ouvrez la config → section **Diffuser maintenant** :
1. sélectionnez les players cibles (tous par défaut) ;
2. sur le média voulu : **Une fois** (le contenu joue une fois puis la programmation
   reprend) ou **En boucle** (jusqu'au bouton **Stop**).

Pour un média **Entrée HDMI**, les boutons deviennent **Basculer sur HDMI / Revenir à la
playlist** (voir la fiche « Entrée HDMI »), et seuls les players avec entrée HDMI physique
sont proposés.

## Qui peut déclencher ?

Le déclenchement demande la permission **vod : trigger** : vous pouvez donner ce seul droit à
un compte « magasin » (ex. rôle opérateur) pour que l'équipe sur place lance les diffusions
sans accéder au reste du CMS.

## Bon à savoir

- La diffusion à la demande est un **takeover** : à la fin (ou au Stop), la programmation
  normale reprend exactement où elle en est (heure courante, pas au début).
- Une config VOD reste cantonnée à **un seul site** dans les deux modes (contrainte du
  déclenchement LAN local entre players) ; un avertissement signale des players sur des
  réseaux différents (la lecture reste possible, le déclenchement LAN local entre players non).
- Le **pré-téléchargement** peut prendre du temps juste après la création de la config
  (fichiers 4K volumineux, téléchargements séquentiels). Tant qu'un média n'est pas encore
  en cache sur un player (visible dans le drawer du player, inventaire des contenus), un
  déclenchement le joue **en streaming** — démarrage un peu différé. Une fois caché,
  la lecture est instantanée et locale.
- **Particularités BrightSign** : le démarrage et l'arrêt d'une diffusion à la demande
  peuvent mettre **jusqu'à 2 secondes** (relais local embarqué sur le player) — c'est
  normal, y compris depuis la page de contrôle locale (téléphone). Pendant la diffusion,
  la playlist est **suspendue** (un seul flux vidéo matériel sur ces players) puis reprend
  à l'heure courante. Le déclenchement depuis le panneau local fonctionne aussi
  **hors-ligne** (diffusion LAN signée entre players, comme les players Electron).
