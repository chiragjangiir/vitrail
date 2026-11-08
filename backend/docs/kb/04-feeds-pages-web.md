---
title: Contenus dynamiques — Feeds et pages web
section: content
roles: [CMS_ORG_ADMIN, CMS_DESIGNER, CMS_SCHEDULER]
keywords: [feed, flux, RSS, actualité, page web, URL, météo, crypto, modération, dynamique]
---

# Contenus dynamiques — Feeds et pages web

En plus des médias importés, SignFlow diffuse des contenus qui se mettent à jour tout
seuls. On les gère depuis la **Médiathèque** (sous-menus **Feeds** et **Pages web**).

## Feeds (flux d'actualité)

Un **feed** est une source pollée régulièrement par le serveur. Les types courants sont
RSS / Atom, Google News, une chaîne YouTube, ainsi que des sources via le proxy de flux
(météo, cours crypto, finance, réseaux sociaux).

Pour chaque feed, vous choisissez un **mode d'affichage** : bandeau défilant (ticker),
carrousel de cartes, grille, article plein écran, mise en page divisée, liste compacte,
mur social, ou graphique (pour les valeurs numériques comme la météo ou la crypto).

### Résumé IA des articles

Un feed peut activer le **résumé IA** : chaque article est condensé en une phrase claire,
lisible de loin, dans la langue de la source. Si le résumé est indisponible, le player
retombe sur la description d'origine — jamais d'écran vide.

### Modération

Activez la **modération** d'un feed pour valider les articles avant diffusion. Les articles
arrivent en attente ; vous les approuvez ou les rejetez, et seuls les approuvés s'affichent.

### Vignettes hors-ligne

Les vignettes des articles sont ré-hébergées et mises en cache sur le player, donc un feed
continue de s'afficher avec ses images même si le serveur ou Internet est coupé.

## Pages web (URL Display)

Vous pouvez afficher une **page web** directement à l'écran (tableau de bord, site, page
interne). Deux modes :

- **WebView** : la page est rendue en direct sur le player.
- **Capture serveur (screenshot)** : le serveur prend une capture périodique de la page et
  l'affiche comme une image — utile pour les pages qui refusent d'être intégrées, ou qui
  nécessitent une authentification gérée côté serveur.

Une page web est un média comme un autre : on lui met des tags et on la planifie dans une
playlist.
