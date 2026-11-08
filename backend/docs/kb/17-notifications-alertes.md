---
title: Notifications et alertes
section: settings
roles: [CMS_ORG_ADMIN]
keywords: [notification, alerte, webhook, email, canal, règle, player hors ligne, feed en erreur, déploiement échoué, campagne, approbation, seuil]
---

# Notifications et alertes

**Réglages → Notifications** : Vitrail pousse des alertes vers vos outils quand un
événement important survient. Un **canal** définit *où* envoyer ; une **règle** définit
*quoi* envoyer et sous quelles conditions.

## Canaux

- **Webhook** : POST JSON vers l'URL de votre choix (Slack, Teams, n8n, supervision…).
- **Email** : jusqu'à 20 destinataires par canal — toutes les alertes peuvent partir
  par email (le serveur SMTP de la plateforme est utilisé).

## Événements disponibles

- **Player hors ligne** : un player ne répond plus (les extinctions programmées par
  l'auto-power sont reconnues — « veille programmée » ne déclenche **pas** d'alerte ;
  un parc pas réveillé après l'heure d'ouverture, si).
- **Feed en erreur** : une source d'actualité ne répond plus (avec reprise automatique).
- **Déploiement échoué** : une mise à jour OTA a échoué sur des players.
- **Campagnes** : démarrée, terminée (bilan), **sous-servie** (SOV servi sous un seuil du
  vendu — 80 % par défaut, réglable par règle).
- **Validations** : demande soumise, approuvée, rejetée, modifications demandées.

## Règles

Chaque règle relie des événements à un canal, avec ses paramètres (seuils, délais).
Testez un canal avec le bouton d'envoi de test avant de compter dessus.
