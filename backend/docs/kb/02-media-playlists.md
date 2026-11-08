---
title: Médias et playlists
section: content
roles: [CMS_ORG_ADMIN, CMS_DESIGNER, CMS_SCHEDULER]
keywords: [média, import, upload, vidéo, image, playlist, encodage, rendition, transcodage, rotation, sous-playlist, imbriquée, un item par tour, aléatoire, shuffle, aperçu, prévisualiser, visualiser, lecteur, multi-zones, template, zones, mise en page]
---

# Médias et playlists

## Importer un média

1. Allez dans la **Médiathèque**.
2. Cliquez sur **Importer** (barre du haut) et sélectionnez vos fichiers (vidéo, image,
   document). Vous pouvez aussi puiser dans les **Photos libres** (Unsplash / Pexels).
3. À l'import, une vidéo est transcodée automatiquement en un format universel (H.264).
   Le contenu reste diffusé pendant le traitement ; aucun écran ne passe au noir.

### Renditions adaptatives

Si votre organisation active la politique de renditions (par exemple « Auto FHD »), une
vidéo 4K importée génère aussi une version Full HD. Chaque player reçoit alors la
résolution adaptée à son écran et à sa puissance de décodage — un écran 1080p n'a pas
besoin du flux 4K. Cela réduit la bande passante et évite les saccades.

### Remplacer le fichier d'un média

Vous pouvez remplacer le fichier d'un média existant sans changer son identité : il reste
référencé par les mêmes playlists. L'ancien contenu continue d'être diffusé jusqu'à la
fin du nouveau transcodage (bascule atomique).

## Créer une playlist

1. Allez dans **Playlists** et cliquez sur **Nouvelle playlist**.
2. Ajoutez des médias (un même média peut être ajouté à plusieurs playlists). La
   multi-sélection permet d'ajouter plusieurs médias d'un coup.
3. Réglez la durée d'affichage de chaque image et l'ordre des items.
4. Une playlist se joue en boucle sur les players qui la diffusent.

## Visualiser une playlist avant de la programmer

Le bouton **lecture** — sur la carte d'une playlist ou dans son éditeur — déroule la boucle
comme le ferait un écran, sans quitter la page.

Si la playlist est posée sur un **template multi-zones**, l'aperçu compose **toutes les zones
en même temps**, au ratio du template, chaque zone avançant sur son propre minuteur — c'est
ce que fait un écran. Un template à une seule zone garde l'aperçu plein écran habituel.

C'est un aperçu, pas le miroir d'un écran, et il vaut mieux le savoir avant de s'y fier :
chaque zone part du **début de sa boucle** (et non de la position qu'aurait un écran à cet
instant), et la **rotation « N par tour »**, les **spots de campagne** et le **filtrage par
tags** n'y sont pas rejoués — ces trois-là dépendent du player, qu'un aperçu n'a pas. Les
**flux, pages web et entrées HDMI** sont nommés à leur vraie place et à leur vraie taille,
sans être rendus : ils sont produits sur l'écran, au moment de la diffusion.

Pour connaître le déroulé réel d'une journée sur un écran donné, utilisez la **simulation de
journée** (Programmes) ou le **programme compilé** d'un player, qui font foi.

## Playlist rotation (sous-playlist « N items par tour »)

Une playlist peut être **imbriquée dans une autre** comme un item (bouton **« Ajouter une
playlist »** dans l'éditeur, à côté d'« Ajouter un média »). Le comportement dépend du
réglage **Rotation** de la playlist imbriquée (section « Rotation » de son éditeur) :

- **Tous les items** (défaut) : la sous-playlist se joue en entier à chaque tour de boucle.
- **N par tour — dans l'ordre** : seuls N item(s) passent à chaque tour ; au tour suivant,
  les suivants (curseur circulaire). Exemple avec 5 vidéos et 2 par tour :
  vidéos 1-2, puis 3-4, puis 5-1, etc.
- **N par tour — aléatoire (sans répétition)** : ordre mélangé, mais aucun item n'est
  rejoué tant que tous ne sont pas passés ; le mélange recommence ensuite.

Points utiles :

- Le champ **« Items par tour »** règle N (défaut 1).
- Ces réglages **suivent le brouillon**, comme les contenus : les modifier fait apparaître
  le bandeau « Modifications non publiées », et les écrans continuent de jouer la boucle
  publiée jusqu'à ce que vous cliquiez sur **Publier** (ou, pour une playlist gouvernée
  sous modération, jusqu'à l'**approbation**). « Annuler » revient à la boucle publiée.
- **Un seul niveau d'imbrication** : une sous-playlist ne peut pas en contenir une autre.
- Une playlist utilisée comme sous-playlist ne peut pas être supprimée tant qu'elle est
  référencée (retirez-la d'abord de ses playlists parentes).
- Les règles de diffusion et tags par item se posent sur les items **de la sous-playlist**
  (ce sont eux qui sont réellement servis aux players).
- La rotation est **synchronisée** : deux écrans d'un même groupe LAN jouent le même item
  au même moment, et la **simulation timeline** montre le déroulé réel tour par tour.
- Si la **même sous-playlist apparaît plusieurs fois** dans une boucle, toutes ses
  occurrences jouent **le même item au même tour** (elles partagent le tirage — c'est ce
  qui garantit le déterminisme et la synchro). Pour entendre des items différents au sein
  d'un même tour, augmentez plutôt « Items par tour » ou créez deux sous-playlists
  distinctes.
- La preuve de diffusion (Proof of Play) est enregistrée pour chaque passage réel de
  chaque item, comme pour un média classique.

## Supprimer un média en toute sécurité

Avant de supprimer un média, SignFlow affiche son **impact** : playlists, programmes,
events et paniers audio qui l'utilisent, et s'il est en cours de diffusion. La suppression
en cascade peut retirer le média des playlists, supprimer les playlists devenues vides et
annuler les events orphelins. Lisez la modale avant de confirmer.
