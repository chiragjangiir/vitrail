---
title: Programmation et events
section: scheduling
roles: [CMS_ORG_ADMIN, CMS_SCHEDULER]
keywords: [programmation, schedule, planning, horaire, event, diffusion, priorité, spot, déclencheur, calendrier, filtre, cible, export]
---

# Programmation et events

## Le calendrier unifié

La page **Programmation** affiche un calendrier (vues semaine et mois) qui superpose tout
ce qui diffuse : **programmes visuels**, **programmes audio**, **événements** et
**campagnes Retail Media**. Une légende à quatre familles (icônes distinctes : éclair =
événement, mégaphone = campagne, note = audio) aide à les distinguer.

- **Filtre de type** : les pastilles « Tout / Visuels / Audio / Événements / Campagnes »
  restreignent l'affichage à une famille.
- **Filtre par cible** : le bouton « Toutes les cibles » ouvre une recherche par
  **groupe de sites, site ou player** — le calendrier ne montre alors que ce qui touche
  réellement cette cible (la résolution utilise le même moteur que la diffusion).
- **Export CSV** : le bouton Export télécharge exactement ce qui est affiché, filtres
  compris (type de chaque ligne, contenu, jours, créneau, validité).
- Le type d'un nouveau programme (visuel ou audio) se choisit **dans le formulaire de
  création** (« Type de programme »).

## Programmer une playlist

Une **programmation (schedule)** dit *quoi* diffuser, *où* (quels players ou groupes) et
*quand* (plages horaires, jours, dates).

1. Allez dans **Programmation** et créez une règle.
2. Choisissez la playlist, les cibles (players ou groupes), et la fenêtre temporelle.
3. Enregistrez : les players concernés se mettent à jour en quelques secondes.

Si une playlist utilise un template dont la résolution ne correspond pas à l'écran cible,
un avertissement s'affiche à l'affectation.

## Events : diffusions prioritaires

Un **event** prend temporairement la priorité sur la programmation normale. Utile pour une
promotion, une annonce, ou un message déclenché par un capteur ou une condition.

- Un event peut diffuser **une playlist** ou **un seul média**.
- Il a une fenêtre d'activité ; à la fin, le player revient automatiquement à sa
  programmation normale.
- Les cibles peuvent **mélanger les types** dans un même event : « ce site » **plus**
  « ces 3 écrans » **plus** « ce groupe », comme le font les campagnes. Les sélections
  faites sous des types différents se cumulent — l'event vise leur union, et le
  récapitulatif du formulaire nomme tout ce qui est retenu. Choisir « Toute
  l'organisation » remplace en revanche toutes les autres sélections.

### Event (ré)activé en cours de fenêtre : bascule différée possible

Les players ne diffusent jamais un média qu'ils n'ont pas fini de télécharger (pas d'écran
noir) : un event **(ré)activé en cours de fenêtre** avec un média jamais distribué peut
donc mettre **quelques minutes** à apparaître sur les players qui téléchargent de gros
fichiers (4K) — ils continuent leur programmation puis basculent dès le fichier prêt.
Activez ou planifiez l'event **à l'avance** : le pré-chargement distribue le média avant
l'heure et la bascule est instantanée. Une fois le média en cache (event récurrent), les
occurrences suivantes basculent sans délai.

### Spot horaire (event programmé « jouer une fois »)

Pour qu'un message passe à intervalle régulier (par exemple une fois toutes les 30 minutes)
plutôt qu'en boucle continue, créez un event **Programmé** avec l'option **« Jouer une
fois »**. Le champ de récurrence du spot horaire n'apparaît que dans cette combinaison
(event programmé + jouer une fois). Le player joue alors le spot une fois par créneau, puis
attend le créneau suivant.

## Synchronisation entre écrans (LAN Sync)

Plusieurs players d'un même réseau local peuvent jouer une vidéo en synchronisation image
par image (mur d'écrans, ambiance cohérente). La synchronisation est fiable quand les
players du groupe sont **homogènes** (même matériel et même configuration). Mélanger des
appareils très différents dans un même groupe synchronisé peut provoquer des décalages.
