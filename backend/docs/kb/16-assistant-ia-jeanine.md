---
title: Assistant IA et Jeanine (Telegram)
section: assistant
roles: []
keywords: [assistant, IA, chat, widget, Jeanine, Telegram, messagerie, actions, confirmation, PIN, vocal, voix, lecture, intents, lier, code de liaison, quota, BYOK, OTA assistant]
---

# Assistant IA et Jeanine (Telegram)

Vitrail embarque un **assistant conversationnel** qui connaît votre compte : il répond
sur vos données en direct, explique le produit (cette documentation), et peut **préparer
des actions** que vous confirmez. Il existe sous deux formes : le **widget** dans le CMS
(bouton en bas à droite ou **Ctrl+Shift+A**) et **Jeanine**, le même assistant par
**Telegram**.

## Ce qu'il sait répondre (lecture)

Players (statut, déconnectés, à jour de contenu, pourquoi un écran est éteint),
playlists (contenu, durée, « qui la joue »), **sites et horaires d'ouverture** (« le site
X est-il ouvert le dimanche ? »), programmations et cibles, médias (non classés, jamais
diffusés, temps d'antenne prouvé), campagnes retail media (statut, rapport), sessions
HDMI, alertes. Il répond **dans la langue de votre profil**.

## Les actions (toujours confirmées)

L'assistant ne modifie **jamais** rien directement : il **prépare** l'action (résout les
noms, vérifie vos permissions) et vous la **confirmez** d'un bouton (widget) ou d'un
« OUI » (Telegram). Exemples : ajouter/retirer un média d'une playlist, créer une
playlist / un feed / un événement / un programme, redémarrer des players, capture
d'écran, allumer/éteindre un écran, basculer une entrée HDMI, lancer une VOD, régler un
fuseau, ranger des médias dans un dossier, **mettre à jour le logiciel des players (OTA,
dernière version stable)**… Les actions sensibles sont réservées à l'org-admin.

## Jeanine sur Telegram

1. **Profil → carte « Messagerie — Telegram »** : générez votre code de liaison et
   envoyez `/link VOTRECODE` au bot (lien direct fourni).
2. L'org-admin voit et révoque les comptes liés dans **Réglages → Messagerie**.
3. Parlez-lui comme au widget : mêmes réponses, mêmes actions, mêmes permissions.
   Sans compte lié, le bot ne répond pas (aucun coût).

### Code PIN (actions sensibles)

Par messagerie, un « OUI » ne suffit pas pour les actions à risque (reboot, extinction
d'écran, suppression de programme, changement de fuseau, **mise à jour OTA**…) : Jeanine
demande votre **code PIN à 6 chiffres**. Définissez-le dans **Profil → carte Messagerie**.
Le code vaut pour une action, expire en 2 minutes, se bloque 15 minutes après 3 erreurs,
et votre message est effacé du fil. Le PIN se tape **au clavier, jamais à la voix**.

### Messages vocaux

Envoyez un **message vocal** (≤ 2 min) : Jeanine transcrit (dans la langue de votre
profil), affiche ce qu'elle a compris (« 🎤 … »), répond en texte **et en note vocale**.
Nécessite les clés IA de l'organisation (fal.ai pour la transcription, ElevenLabs pour la
voix — Réglages → Clés IA).

## Coûts et quotas

L'assistant utilise **les clés IA de votre organisation** (BYOK) et respecte le quota IA
configuré. Widget et Telegram partagent les mêmes gardes ; un compte Telegram non lié ne
déclenche aucun appel.
