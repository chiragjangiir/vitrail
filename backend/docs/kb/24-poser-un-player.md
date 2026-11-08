---
title: Poser un player en clientèle — les 4 canaux et les 3 preuves
section: players
roles: []
keywords: [poser un player, pose, installer un player, provisioning, provisionner, payload, jeton, sfp_, clé opérateur, sfk_, carte SD, image SD, Raspberry Pi, WinRM, Windows, SSH, ADB, Android, BrightSign, ré-attache, reattach, doublon, terrain, technicien, installeur, first boot, premier démarrage]
---

# Poser un player en clientèle — les 4 canaux et les 3 preuves

Le CMS génère un **payload** — l'adresse du serveur plus un **jeton `sfp_` à usage unique** — et
**pré-crée le player**. L'appareil s'y ré-attache à son premier contact, échange le jeton contre un
jeton permanent, et apparaît **en ligne**.

⚠️ **Un jeton consommé ne resert pas.** Si une pose échoue après l'enregistrement, il faut
**regénérer un payload** : sinon l'essai suivant échoue pour une raison sans rapport avec la vraie
cause, et on cherche au mauvais endroit.

📄 Procédure complète, pas à pas, pour le technicien : `docs/RUNBOOK_POSE_PLAYER.md`.
Boîtiers Android (pièges Device Owner) : `docs/RUNBOOK_POSE_ANDROID_TV.md`.

## À préparer une seule fois

Dans le CMS, en administrateur d'organisation : **Provisioning → Clé opérateur** → générer →
copier la clé `sfk_…` (**affichée une seule fois**). Sur le poste du technicien :

```
signflow-provision --cms https://<serveur>:8443 --key sfk_… --save-config
```

Il n'y a plus rien à ressaisir ensuite. Cette clé est **limitée au provisioning** (créer un
payload, lire l'état d'un player) — elle ne donne **pas** les droits d'administration — et elle est
révocable depuis le CMS. Un jeton d'administrateur marche aussi, mais il **expire en 15 minutes** :
à éviter sur le terrain.

Le technicien n'a besoin que d'**un seul fichier** (`signflow-provision.exe`, ~13 Mo) ; aucun
Python à installer. `signflow-provision --selftest` liste les canaux disponibles.

## Quel canal pour quelle situation

| Situation | Canal | Geste humain sur place |
|---|---|---|
| **Raspberry Pi neuf** | image sur carte SD | insérer la carte, allumer — **c'est tout** |
| **PC Windows déjà installé** | WinRM | ouvrir WinRM une fois |
| **Linux / RPi déjà en service** | SSH | aucun si SSH est déjà ouvert |
| **Boîtier Android** | ADB | activer le débogage USB |
| **BrightSign** | ZIP sur carte SD | copier le ZIP sur la carte |

🔑 **L'outil ne peut pas ouvrir la porte à votre place.** Un point d'entrée doit exister (WinRM,
SSH, ADB, ou l'accès physique à la carte SD) ; tout le reste est automatisé.

## Les 3 preuves qu'une pose a réussi

Ne pas se contenter du message de l'outil — il dit que le script s'est lancé, pas que le player
fonctionne.

1. **Dans le CMS** : le player est **en ligne**, avec le bon système, et il n'y a **qu'une seule
   ligne** — pas de doublon.
2. **Le jeton a été consommé** : dans le `config.json` du player, la valeur commence par `eyJ…`
   (un jeton permanent) et **non plus** par `sfp_`. Si elle commence encore par `sfp_`,
   l'enregistrement n'a pas eu lieu.
3. **L'écran diffuse** (ou affiche le repli si rien n'est encore programmé).

## Pièges rencontrés en réel

**Re-provisionner un player existant sans l'option de ré-attache crée un DOUBLON.** Récupérer son
identifiant dans **Players** et le passer à l'outil. ⚠️ Même une simulation (`--dry-run`) crée un
player côté CMS.

**La clé d'hôte SSH change à chaque réinstallation.** Le refus qui suit est le système qui fait son
travail. Retirer l'ancienne empreinte (`ssh-keygen -R <ip>`) — ⚠️ tant qu'elle est là, OpenSSH
**désactive aussi l'authentification par mot de passe**, et on croit à un mauvais mot de passe
alors que c'est la clé.

**Un Raspberry Pi n'a pas d'horloge.** Au premier démarrage il repart de la date de l'image ; tant
que l'heure n'est pas synchronisée, **toute connexion sécurisée est refusée** (« certificate is not
yet valid »). L'image attend d'elle-même — mais si le site bloque la synchronisation d'heure,
l'installation échoue et le dit.

**Pas de réseau au bon moment = échec propre.** Le message le dit et un redémarrage relance
l'essai : inutile de refaire la carte.

**Sur une machine virtuelle Windows**, utiliser un disque **SATA** et une carte réseau **e1000e** :
Windows n'a aucun pilote virtio, sinon il ne voit ni le disque ni le réseau.

## Si ça ne marche pas

Sur un Raspberry Pi posé par carte SD, le premier démarrage écrit un **journal persistant** :
`/var/log/signflow-firstboot.log`. Il survit au redémarrage et dit à quelle étape ça a cassé —
c'est le premier endroit à regarder avant de refaire quoi que ce soit.
