---
title: Fuseau horaire et synchronisation de l'heure (NTP)
section: players
roles: [CMS_ORG_ADMIN]
keywords: [fuseau horaire, timezone, heure, NTP, horloge, synchronisation, décalage, mauvaise heure, site, chrony]
---

# Fuseau horaire et synchronisation de l'heure (NTP)

Toute la programmation (playlists, events, allumage des écrans) s'exécute en **heure locale
du site**. Deux réglages garantissent que players et serveur sont d'accord sur l'heure.

## Le fuseau du site fait référence

Chaque site a un **fuseau horaire** (Sites → votre site). C'est lui qui pilote les horaires
de diffusion et d'auto-power. Quand un player est **rattaché à un site** (ou que le fuseau du
site change), SignFlow **aligne automatiquement l'horloge du player** sur ce fuseau — utile
pour un player cloné ou venu d'un autre pays.

## Voir et corriger le fuseau d'un player

Dans le drawer du player, section **Appareil**, la ligne « Fuseau horaire » montre le fuseau
réel de l'appareil, avec un **badge d'alerte s'il ne correspond pas au site**. Vous pouvez le
changer à distance ; le player applique et confirme (coche verte quand la nouvelle valeur est
remontée). Particularités par plateforme :
- **Linux / Raspberry Pi / Android** : liste complète des fuseaux (ex. Europe/Paris).
- **Windows** : liste des fuseaux canoniques Windows (un par zone — Monaco s'affiche par
  exemple via le fuseau d'Europe centrale).
- **BrightSign** : libellés propres au système (ex. **CET** = équivalent Europe/Paris, le
  badge le reconnaît) ; l'appareil **redémarre** pour appliquer.
- **ChromeOS / extension Chrome** : géré par la politique Google / le système, non pilotable.

## Serveur NTP par site

Pour que tous les players d'un site partagent exactement la même horloge (indispensable à la
synchronisation LAN entre écrans), renseignez un **serveur NTP** sur le site (IP ou nom
d'hôte — souvent le serveur SignFlow du site). Chaque player l'applique automatiquement :
- Linux / Raspberry Pi : via chrony ;
- Windows : via le service de temps Windows ;
- BrightSign : via sa configuration réseau native.

Un player qui a déjà une configuration NTP propre (relais NTP d'un groupe de synchronisation
LAN) la conserve : elle prime sur le réglage du site.
