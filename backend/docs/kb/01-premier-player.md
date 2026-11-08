---
title: Enrôler votre premier player
section: players
roles: [CMS_ORG_ADMIN, CMS_SCHEDULER]
keywords: [player, enrôlement, provisioning, token, installation, NUC, raspberry, windows, android, chromeos]
---

# Enrôler votre premier player

Un player est un appareil qui pilote un écran. Pour qu'il rejoigne votre organisation,
il faut un **token de provisioning** : un secret à usage limité que le player présente au
serveur pour s'enregistrer.

## Générer un token de provisioning

1. Allez dans **Players → Provisioning**.
2. Cliquez sur **Nouveau token** dans la barre du haut.
3. Choisissez le nombre de players maximum que ce token peut enrôler, et une expiration
   (ou cochez « Sans expiration » pour un token permanent).
4. Copiez le token généré (il commence par `sfp_`).

Un token actif peut être **révoqué** (icône ⊘) : il ne pourra plus enrôler de nouveaux
players, mais ceux déjà enrôlés continuent de fonctionner. Un token révoqué peut ensuite
être **supprimé** définitivement.

## Installer le player sur l'appareil

Le logiciel player existe pour Linux (Debian), Raspberry Pi, Windows 11, Android, et en
PWA ChromeOS / extension Chrome. À l'installation, on lui fournit deux choses :

- l'**URL du serveur** SignFlow,
- le **token de provisioning** (`sfp_…`).

Au premier démarrage, le player échange le token contre son identité permanente et
apparaît dans **Players**. À partir de là, il reçoit sa configuration et son contenu
automatiquement.

## Vérifier qu'un player est en ligne

Dans la liste des Players, un badge indique l'état (en ligne / hors-ligne) avec la date
de dernier contact. Ouvrez le drawer d'un player pour voir sa machine, son écran, son
adresse réseau, son inventaire de médias et une capture d'écran récente.

## Configurer un player à distance

Depuis le drawer d'un player, sans SSH, vous pouvez pousser : résolution, rotation
d'écran, volume, activation du son, choix du moteur de rendu. Le bouton **« Infos à
l'écran »** affiche un panneau de diagnostic directement sur l'écran du player (nom,
machine, réseau, programme en cours, média joué) — pratique pour identifier un écran à
distance.

## Agir sur plusieurs players à la fois

Le bouton **« Commandes en masse »** en haut de la page Players envoie la même commande à
toute une **cible** : organisation entière, site, groupe de sites, groupe de players, ou un
player précis. La cible est résolue par le serveur — un player ajouté au site plus tard
sera donc inclus lors du prochain envoi.

Avant d'envoyer, un **aperçu liste les écrans concernés** : vérifiez-le, c'est la seule
occasion de rattraper une cible trop large.

Les commandes **destructives** (redémarrer la machine ou l'application, quitter
l'application, mode maintenance) exigent en plus :

- une **case de confirmation** mentionnant le nombre d'écrans touchés ;
- votre **PIN à 6 chiffres** (le même que pour l'assistant par messagerie), à définir dans
  votre profil, carte « Messagerie ». Trois PIN faux verrouillent la fonction 15 minutes.

Les commandes inoffensives (capture d'écran, détection des capacités, overlay
d'informations) ne demandent pas de PIN.

Chaque envoi en masse est **journalisé** dans l'audit avec la cible demandée et la liste
des players réellement touchés.
