---
title: Chartes de marque — déclarer une fois, pré-remplir partout
section: promo
roles: []
keywords: [charte, charte de marque, brand kit, marque, couleurs, palette, accent, encre, fond, pastille, police, typographie, logo, mentions légales, ton, identité visuelle, annonceur, organisation, enseigne, générateur promo, visuel promo, pré-remplissage, template, modèle, assistant de prompt, atmosphère]
---

# Chartes de marque — déclarer une fois, pré-remplir partout

Une **charte de marque** rassemble ce qu'on retapait à chaque visuel : les couleurs, la
police, le nom de la marque, son logo, ses mentions légales et son ton. Elle se déclare
**une seule fois**, et le **Générateur promo** s'en sert ensuite pour pré-remplir chaque
visuel.

On la gère depuis la page **Générateur promo**, bouton **« Chartes et polices »** dans la
barre du haut. Sa modification est réservée à l'**administrateur d'organisation** :
la charte décide de l'identité visuelle, comme les polices personnalisées.

## Deux portées, et laquelle l'emporte

| Portée | À qui elle sert |
|---|---|
| **Organisation** | l'enseigne elle-même — ses propres visuels |
| **Annonceur** | une marque fournisseur qui diffuse chez vous |

Il y a **au plus une charte de chaque** : une pour l'organisation, une par annonceur. Quand
un visuel est fait *pour un annonceur*, c'est **sa** charte qui s'applique ; sinon celle de
l'organisation. Un visuel Brightwell ne porte pas les couleurs du magasin.

Le choix se fait dans la carte **« Charte appliquée »**, en haut de la colonne de gauche :
*Visuel de l'enseigne*, ou l'annonceur visé. La ligne en dessous dit toujours quelle charte
s'applique réellement — ou qu'il n'y en a aucune.

## Une charte ne remplace que ce qu'elle déclare

C'est le point le plus important, et il explique la case à cocher devant chaque couleur.

Une couleur **non déclarée** n'est pas « blanche » : elle signifie *« la charte ne dit
rien »*, et le modèle garde alors la sienne. Vous pouvez donc n'imposer que votre couleur
d'accent et laisser le reste du modèle intact. Sans ces cases, poser une seule couleur de
marque effacerait en silence les quatre autres et produirait un visuel incohérent.

Il en va de même pour la police : si vous n'en déclarez aucune, celle du modèle est
conservée.

## Elle pré-remplit, elle ne verrouille pas

L'ordre est toujours le même :

**couleurs du modèle → puis la charte → puis ce que vous saisissez sur ce visuel.**

Vous gardez donc la main : sur un visuel donné, un réglage de style que vous posez
vous-même l'emporte sur la charte. La charte vous évite de tout ressaisir, elle ne vous
enferme pas.

Les **mentions légales** suivent la même logique, avec une nuance : elles sont recopiées
dans le champ *Mentions* **une seule fois**. Si vous les effacez volontairement, elles ne
reviennent pas.

## Le logo et le nom de marque ne sont jamais dessinés par l'IA

Quand vous demandez un **fond généré par IA**, la charte transmet au modèle **la palette et
le ton**, comme une *atmosphère à viser*. Elle ne lui demande jamais de dessiner votre logo,
d'écrire le nom de la marque ni les mentions légales.

C'est volontaire : un modèle génératif ne sait pas reproduire un logo fidèlement, et il
écrirait un texte approximatif. Ces trois éléments sont **posés après**, par le compositing,
qui est déterministe — donc exact. Le bouton **« Poser le logo de la marque »** ajoute le
logo comme calque, que vous pouvez ensuite déplacer et redimensionner.

Autrement dit : l'IA fournit l'ambiance, le compositing fournit l'exactitude.

## Ce qui change quand aucune charte n'existe

Rien. Tant qu'aucune charte n'est créée, les visuels gardent exactement les couleurs et la
police de leur modèle, et l'assistant de rédaction de prompt se comporte comme avant.

## Questions fréquentes

**Je viens de changer les couleurs de la charte, faut-il refaire les visuels déjà
générés ?**
Oui. Un visuel généré est une image : elle fige les couleurs du moment. La charte agit sur
les visuels que vous générez **ensuite**.

**J'ai choisi une police dans la charte mais le visuel ne la montre pas.**
Vérifiez qu'elle est toujours présente dans les **polices personnalisées** de
l'organisation. Si elle a été supprimée depuis, le visuel retombe volontairement sur la
police du modèle plutôt que d'échouer.

**Un annonceur peut-il gérer sa propre charte depuis le portail ?**
Non. La charte d'un annonceur se règle depuis le CMS, par un administrateur de
l'organisation.
