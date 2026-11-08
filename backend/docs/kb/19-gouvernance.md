---
title: Gouvernance hiérarchique (réseaux multi-sites)
section: gouvernance
roles: []
keywords: [gouvernance, hiérarchie, nœud, node, national, régional, département, magasin, site, enseigne, réseau, multi-sites, couche, layer, programme compilé, délégation, règle, item_count, budget, plafond, restriction, verrou, périmètre, administrateur de nœud, admin de nœud, entrée, sortie, groupe de players, modération, approbation, rattacher, orphelin, déplacer un nœud, re-parentage, directeur, programmeur, éditeur, valideur, contenu gouverné, lecture seule, sous-arbre]
---

# Gouvernance hiérarchique (réseaux multi-sites)

La **Gouvernance** (page `/governance`) sert aux réseaux où plusieurs niveaux décident de
ce qui s'affiche : un siège, des régions, des magasins. Chaque niveau compose **sa** part
du programme, et les écrans diffusent la **somme** des niveaux dont ils dépendent — sans
que personne ne puisse écraser le contenu d'un autre.

Une installation mono-site n'en a pas besoin : sans nœud, le produit se comporte
exactement comme avant (le sélecteur « Nœud propriétaire » ne s'affiche même pas).

## Les cinq notions

**Le nœud** est un niveau de l'organisation (National, Département, Magasin). Les nœuds
forment un arbre ; c'est le **niveau** (racine = 0) qui fixe l'ordre national → local dans
le programme final, pas le « type » du nœud, qui n'est qu'une étiquette.

**Le périmètre** d'un nœud est l'ensemble des écrans qu'il pilote. On le compose en
rattachant des **cibles** : un écran, un groupe d'écrans, un site, un groupe de sites. Le
périmètre d'un nœud **inclut celui de ses descendants** : rattacher les sites aux nœuds de
magasin suffit, le département et le national les couvrent automatiquement.

**La couche** : chaque programme rattaché à un nœud produit une couche. Un écran compile
toutes les couches des nœuds dont il dépend, du national au local. C'est ce qu'affiche la
colonne « Programme compilé » de la page Gouvernance — pour **cet écran** et à **cet
instant**, avec le vrai moteur de diffusion, mais avant filtrage par tags, campagnes et
ancrage horaire.

**La règle** dit combien chaque niveau peut prendre. La plus utilisée est **« nombre de
contenus par tour »** (`item_count`) : avec 1, chaque niveau place un contenu par tour, et
ses contenus **tournent** d'un tour à l'autre au lieu de rejouer toujours le même. Existent
aussi le budget de temps, la fenêtre horaire et la préemption.

**L'administrateur de nœud** est la personne qui décide pour ce nœud. ⚠️ Une permission
ne suffit **jamais** : c'est cette affectation qui autorise à écrire. Un utilisateur qui
détient « programmes : modifier » sans être administrateur d'aucun nœud ne peut modifier
aucun programme gouverné.

## Qui peut quoi

L'administrateur d'un nœud agit sur **son nœud et tout son sous-arbre**. Il voit les nœuds
au-dessus de lui **en lecture seule** (comprendre ce qui vient du national fait partie du
métier) et ne voit **pas du tout** les branches voisines : contenu, structure et écrans
d'un magasin voisin lui renvoient « introuvable ».

Trois gestes remontent toujours d'un cran :

- **retirer un contenu de la gouvernance** (le « détacher ») ;
- **retirer la modération** d'un nœud ou **lever une restriction** sur ses règles ;
- **valider** une soumission — le valideur doit administrer un nœud **parent**, et
  personne ne valide sa propre soumission.

Créer un nœud **racine** est réservé à l'administrateur d'organisation.

## Les quatre rôles de gouvernance

| Rôle | Ce qu'il fait |
|---|---|
| **Gouvernance — Directeur** | Bâtit la structure : nœuds, périmètres, administrateurs, règles et plafonds. Voit le contenu, ne le produit pas. |
| **Gouvernance — Programmeur** | Crée les **programmes** et les **playlists** de ses nœuds, soumet à l'approbation. |
| **Gouvernance — Éditeur** | Produit le contenu (playlists, médias) et le soumet. **Ne supprime aucun média**, ne programme pas. |
| **Gouvernance — Valideur** | Approuve, rejette ou demande des modifications sur son sous-arbre. Ne produit rien. |

Ces quatre rôles portent une **sémantique de périmètre** : leur porteur n'agit que dans
son sous-arbre, **et le contenu non gouverné lui est invisible**. Un « Programmeur » ne
voit donc ni les playlists ni les programmes d'organisation — seulement ceux des nœuds
qu'il administre. C'est voulu : sans cela, la restriction s'arrêterait à la frontière de
la gouvernance.

## Le contenu gouverné

Une **playlist**, un **média**, un **template**, un **événement** et une **configuration
VOD** peuvent appartenir à un nœud (champ « Nœud propriétaire »). Sans nœud, l'objet
appartient à l'organisation et se comporte comme avant.

Un objet rattaché n'est modifiable que par les administrateurs de son nœud ou d'un nœud
parent. Si le nœud est marqué **« Contenu soumis à approbation »**, la publication directe
est refusée : on **soumet à l'approbation**, et c'est la validation qui publie. Cette
modération est **héritée vers le bas** — la décocher sur un magasin ne sert à rien si le
national l'exige.

⚠️ **Deux malentendus qui coûtent cher.** Rattacher une playlist à un nœud décide **qui
l'édite** ; ça ne la **diffuse pas** — la diffusion vient d'un **programme** rattaché au
même nœud. Et le **rôle** dit ce qu'on peut faire, l'**affectation d'administrateur** dit
**où**.

## Viser une partie des écrans d'un nœud

Par défaut, un programme rattaché à un nœud diffuse sur **tous** les écrans du nœud. Pour
n'en viser qu'une partie, ajoutez-lui des **cibles** : elles **restreignent** le périmètre,
elles ne l'élargissent jamais, et un niveau inférieur ne peut jamais restreindre une couche
héritée. Une cible qui ne retient aucun écran du nœud est refusée à l'enregistrement, en la
nommant.

**Laisser un programme sans cible est souvent le bon choix** : il couvre alors tout son
nœud, y compris les sites ajoutés plus tard. Un programme national ciblé site par site
oublie silencieusement chaque nouveau magasin.

## Exemple complet : entrée et sortie de magasin

Besoin réel : dans chaque magasin, l'écran d'**entrée** et celui de **sortie** diffusent un
contenu **en plus** des autres écrans, et le responsable du magasin doit pouvoir changer
lui-même ses contenus et ses programmes.

**L'arbre** — `National TOTO` → `Dpt-01` → `Dpt-01/Site-01` et `Dpt-01/Site-02`.

**Le périmètre** — on rattache **le site** au nœud de magasin (`Site-01` au nœud
`Dpt-01/Site-01`). Le département et le national n'ont **aucune affectation** : ils
héritent du sous-arbre. C'est plus simple et ça ne se périme pas.

**Les deux groupes d'écrans** — un groupe **« Entrance shop »** qui contient l'écran
d'entrée **de chaque** magasin, et un groupe **« Exit Shop »** pour les sorties. Le groupe
marque le **rôle** de l'écran, le nœud marque le **magasin** : le croisement des deux
désigne le bon écran, sans jamais créer un groupe par magasin.

**Les contenus** — chaque nœud possède ses playlists. Le magasin en a trois : sa playlist
locale, celle de son entrée, celle de sa sortie. 🔑 **Chaque magasin doit posséder les
siennes** : une playlist partagée entre deux magasins n'est modifiable que par le
propriétaire, et l'autre responsable ne peut même pas la lire.

**Les programmes** — un par nœud, plus deux par magasin :

| Nœud | Programme | Cible | Effet |
|---|---|---|---|
| National TOTO | SC National | *(aucune)* | tous les écrans du réseau |
| Dpt-01 | SC Dpt | *(aucune)* | tous les écrans du département |
| Dpt-01/Site-01 | SC Site-01 | les 5 écrans du magasin | contenu local |
| Dpt-01/Site-01 | SC Entrance Site-01 | groupe « Entrance shop » | l'entrée seulement |
| Dpt-01/Site-01 | SC Exit Site-01 | groupe « Exit Shop » | la sortie seulement |

**Les règles** — `item_count = 1` sur chaque nœud : chaque niveau place un contenu par
tour et fait tourner ses contenus.

**Le résultat mesuré** : les écrans ordinaires diffusent **3 contenus par tour** (national
+ département + local), l'entrée et la sortie en diffusent **4**. Chaque responsable de
magasin modifie ses trois playlists et ses trois programmes, se voit refuser ceux du
magasin voisin, et lit sans modifier ceux du national et du département.

**Ajouter un magasin** se fait alors en cinq gestes : créer le nœud sous le département,
y rattacher le site, créer ses trois playlists, créer ses trois programmes, et ajouter son
écran d'entrée au groupe « Entrance shop » et celui de sortie à « Exit Shop ». Les
programmes national et département n'ont pas à être touchés — ils sont sans cible.

## Composer un périmètre à l'échelle

Le bouton **« Ajouter des écrans »** de la carte Cibles ouvre une recherche **côté
serveur** : on filtre par nature (écran, groupe d'écrans, site, groupe de sites), on
sélectionne **plusieurs cibles d'un coup**, et chaque ligne annonce **le nombre d'écrans
qu'elle représente** — indispensable dès qu'on mêle sites et groupes. Un écran encore
rattaché à **aucun** nœud est proposé et **étiqueté** : c'est ainsi qu'un oubli
d'installation se voit et se répare. Un écran gouverné **ailleurs** n'apparaît pas.

## Réorganiser

Un nœud peut être **déplacé** sous un autre parent : les chemins et les niveaux de tout son
sous-arbre sont recalculés, et les écrans concernés recompilent. On ne peut pas déplacer un
nœud sous lui-même ni sous un de ses descendants, ni le greffer dans une branche qu'on
n'administre pas.

## Diagnostic : « aucune couche active »

Quand l'aperçu d'un écran est vide, le message nomme la cause : aucun nœud pour cet écran,
aucun programme sur le nœud, programme inactif, programme sans playlist, programme **sans
règle horaire** (il ne sera jamais actif), ou hors de sa fenêtre à cet instant. La cause la
plus fréquente est la première : une playlist rattachée à un nœud ne diffuse rien tant
qu'un **programme** n'est pas rattaché au même nœud.
