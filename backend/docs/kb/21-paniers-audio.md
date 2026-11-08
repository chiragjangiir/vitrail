---
title: Paniers audio — la musique et les messages en magasin
section: audio
roles: []
keywords: [audio, paniers audio, musique, ambiance, jingle, message, urgence, ducking, mix, ratio, poids, aléatoire, shuffle, récurrence, tous les N morceaux, toutes les N minutes, programme audio, player audio, son, volume, panneau magasin, store control, écouter, pré-écoute, règle de diffusion, obligatoire, national, régional, local, style]
---

# Paniers audio — la musique et les messages en magasin

Un **panier audio** est une réserve de contenus sonores dans laquelle un écran (ou un player
sans écran) puise en continu : une playlist de musique de fond, un jeu d'annonces
promotionnelles, un jingle d'enseigne. La page **Paniers Audio** sert à les composer ; c'est
la **Programmation** qui décide ensuite quels players les diffusent, par un *programme
audio*.

Un panier n'est donc pas assigné à un écran depuis cette page : on y compose le contenu, on
diffuse ailleurs. C'est la même séparation que pour les playlists visuelles — composer et
diffuser sont deux gestes distincts.

## Les cinq types, et pourquoi le type compte

| Type | Rôle |
|---|---|
| **Musique** | le fond sonore continu |
| **Ambiance** | nappe sonore d'atmosphère, même logique que la musique |
| **Message** | une annonce parlée (promotion, information client) |
| **Jingle** | l'identité sonore de l'enseigne, à intervalle régulier |
| **Urgence** | annonce prioritaire (évacuation, rappel) |

Le type ne sert pas qu'à ranger : il détermine **qui baisse le son de qui**. Les paniers
*message*, *jingle* et *urgence* font baisser la musique pendant qu'ils parlent ; les
paniers *musique* et *ambiance* subissent cette baisse. C'est le **ducking**.

## Le ducking

Sans lui, une annonce parlée se superposerait à la musique et deviendrait incompréhensible.
Trois réglages, sur le panier qui **subit** la baisse :

- **volume de la musique pendant le message** (en %) ;
- **fondu entrant** et **fondu sortant** (en millisecondes) — une coupure nette s'entend
  comme un défaut technique, un fondu de quelques centaines de millisecondes passe inaperçu.

## Composer un panier

**Ajouter des contenus** ouvre un tiroir de recherche sur toute la médiathèque audio, avec
pré-écoute : on peut en sélectionner plusieurs d'un coup, et les titres déjà présents sont
signalés. Chaque item porte ensuite :

- un **poids** — plus il est élevé, plus le titre revient souvent ;
- l'ordre **aléatoire** ou séquentiel, au niveau du panier ;
- une **règle de diffusion** facultative : jours de la semaine et créneau horaire, en heure
  locale du site. Sans règle, le titre passe toujours. C'est ce qui permet à une annonce de
  ne sortir qu'aux heures d'affluence, ou à une musique de Noël de s'arrêter toute seule.

**Écouter le panier** enchaîne les titres actifs comme le fera le player : c'est le seul
moyen honnête de juger un enchaînement avant de l'envoyer en magasin.

## La récurrence d'un jingle

Un panier *jingle* ne se joue pas en boucle mais **par intervalle**, au choix :

- **tous les N morceaux** — l'identité sonore revient à un rythme lié au contenu ;
- **toutes les N minutes** — le rythme est lié à l'horloge.

## Portée et mélange entre niveaux

Un panier a une **portée** — *national*, *régional*, *local* ou *style* — et un **taux de
mélange** encadré par un minimum et un maximum. Ces garde-fous sont le cœur du sujet dans un
réseau : un magasin peut ajuster la part de sa musique locale, mais **jamais** descendre
sous le minimum ni dépasser le maximum fixés au-dessus de lui.

La case **Obligatoire** va plus loin : elle verrouille le ratio pour les niveaux inférieurs.
Un jingle d'enseigne obligatoire à 10 % passera à 10 % dans tous les magasins, sans
discussion possible sur place.

Un panier peut aussi être rattaché à un **nœud de gouvernance** (voir la fiche Gouvernance) :
il n'appartient alors plus à toute l'organisation mais à ce niveau, qui seul peut le
modifier.

## Le panneau magasin

Le responsable d'un magasin n'a pas besoin d'un compte CMS pour agir sur l'ambiance sonore :
un panneau local, accessible sur le réseau du magasin, permet d'ajuster le mélange dans les
limites autorisées et de déclencher une annonce. Il continue de fonctionner même si le
serveur central est injoignable.

## Ce qui est mesuré

Chaque lecture réelle — musique, ambiance, message, jingle — remonte une **preuve de
diffusion** signée, exactement comme le visuel. C'est ce qui permet de facturer un spot
audio d'annonceur et de prouver qu'il est passé, à la seconde près.

## Questions fréquentes

**« La musique ne baisse pas pendant les annonces. »** Vérifiez le type des deux paniers :
seul un panier *message*, *jingle* ou *urgence* déclenche le ducking, et seuls *musique* et
*ambiance* le subissent. Un message rangé par erreur en *musique* ne fera rien baisser.

**« Un magasin n'arrive pas à changer son mélange. »** C'est probablement un panier
*obligatoire*, ou un minimum/maximum posé à un niveau supérieur. Le verrou est volontaire.

**« Je supprime un panier et le produit refuse. »** Il est utilisé par une diffusion en
cours. Le message nomme ce qui le retient ; vous pouvez confirmer, le panier sera alors
retiré de ces diffusions.

**« Rien ne sort sur le player. »** Un panier composé ne diffuse pas tout seul : il faut un
**programme audio** dans la Programmation, qui vise ce player. Composer et diffuser sont
deux gestes distincts.
