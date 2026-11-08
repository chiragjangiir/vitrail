---
title: Player Chrome Extension (sans matériel)
section: players
roles: [CMS_ORG_ADMIN, CMS_SCHEDULER]
keywords: [chrome, extension, player, sans matériel, zero-hardware, navigateur, kiosk]
---

# Player Chrome Extension (sans matériel)

L'**extension Chrome** transforme un simple Chrome en player Vitrail, sans installer
d'appareil dédié. Idéal pour tester, ou pour un poste existant qui dispose déjà d'un écran.

## Quand l'utiliser

- Vous voulez essayer Vitrail sans NUC ni box.
- Vous avez un PC/écran déjà en place sous Chrome.
- Vous n'avez pas besoin de la synchronisation LAN entre écrans (non disponible en
  extension, qui fonctionne en lecture en ligne avec dégradation gracieuse hors-ligne).

## Installer

1. Récupérez le dossier de l'extension auprès de votre administrateur.
2. Dans Chrome : `chrome://extensions`, activez le **mode développeur**, puis
   **« Charger l'extension non empaquetée »** et pointez le dossier.
3. Ouvrez la **popup** de l'extension : saisissez l'URL du serveur Vitrail et un token de
   provisioning (`sfp_…`), puis lancez. Une fenêtre kiosk plein écran s'ouvre et le player
   s'enregistre.

Le player Chrome Extension apparaît ensuite dans **Players** comme n'importe quel autre, et
reçoit sa programmation normalement.

## Limites

- Pas de synchronisation LAN entre plusieurs écrans.
- Le mode hors-ligne est limité (lecture en streaming) comparé aux players natifs qui
  téléchargent et jouent localement.
- Pour un déploiement verrouillé et auto-lancé sur ChromeOS managé, c'est plutôt le **player
  ChromeOS PWA** (kiosk) qui est utilisé.
