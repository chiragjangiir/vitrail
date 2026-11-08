---
title: Générateur promo — fabriquer un visuel de promotion
section: promo
roles: []
keywords: [générateur promo, promo, visuel promo, affiche promo, prix, prix barré, remise, promotion, slogan, mentions légales, produit, fond, arrière-plan, détourage, découpe, mise en page, gabarit, format, résolution, calque, calques, préréglage, URL produit, extraire, conformité, lisibilité, générer, vidéo promo, animation, série, mode série, plusieurs visuels, en masse, lot, CSV, import CSV, tableur, Excel, coller, tableau, ligne, plusieurs produits]
---

# Générateur promo — fabriquer un visuel de promotion

Le **Générateur promo** produit une affiche promotionnelle (image ou vidéo courte) à partir
d'un produit, d'un prix et d'une mise en page. Le résultat part dans la **médiathèque** et se
diffuse comme n'importe quel média.

**Où** : Médiathèque → **Générateur promo**.

🔑 **Ce que la machine fabrique et ce qu'elle n'invente jamais.** Le prix, le prix barré, la
remise, le nom du produit et les **mentions légales** sont posés par le compositing à partir de
ce que vous avez saisi — ils ne sont **jamais** demandés à un modèle d'IA. L'IA ne sert qu'au
**fond** (et au détourage du produit). C'est ce qui garantit qu'un prix affiché est le prix que
vous avez tapé.

## Le parcours, en six étapes

La colonne de gauche est un **parcours**. Une seule étape est ouverte à la fois : ouvrir la
suivante referme la précédente, pour que tous les champs d'une étape tiennent à l'écran. Une
étape **repliée affiche sa valeur**, donc on lit l'état complet du visuel en six lignes.
Elles s'ouvrent dans n'importe quel ordre, autant de fois qu'on veut.

| # | Étape | Ce qu'on y fait |
|---|---|---|
| 1 | **Pour qui ?** | Mon enseigne, ou un annonceur. **La charte s'en déduit** — couleurs, police, logo, mentions. |
| 2 | **Le produit** | Coller l'URL d'une fiche produit (extraction automatique), choisir une image de la médiathèque, ou en importer une. Détourage possible. |
| 3 | **Texte et prix** | Slogan, prix, prix barré, remise, devise, mentions légales, nom du média. |
| 4 | **Mise en page** | Le gabarit, le format (16:9 ou 9:16) et la résolution. |
| 5 | **Le fond** | Une image de la médiathèque, ou un fond généré par IA (ambiance + description). |
| 6 | **Retouches libres** | Ajouter des calques texte ou image, déplaçables sur l'aperçu. |

## Partir d'une URL produit

Étape 2, collez l'adresse d'une fiche produit et cliquez **Extraire** : le nom, le prix et la
photo sont récupérés et pré-remplissent le formulaire. **Tout reste modifiable** — l'extraction
est une aide à la saisie, pas une source de vérité. Vous restez responsable des données
affichées et des droits sur l'image.

## Le prix est obligatoire

Un visuel promo sans prix n'a pas de sens : le bouton **Générer** reste éteint tant qu'il
manque, et le bandeau sous l'aperçu **dit ce qui manque et emmène à l'étape concernée**.

Le même bandeau signale les problèmes de **lisibilité** (texte trop long pour son
emplacement, contraste insuffisant). Ces contrôles sont ré-appliqués par le serveur au moment
de générer : on ne peut pas produire un visuel illisible en contournant l'écran.

## Choisir une image

Les étapes **Produit** et **Fond** ouvrent le **tiroir de la médiathèque** : arbre de dossiers,
recherche, aperçu. La recherche se fait **côté serveur**, donc elle trouve aussi les images qui
ne sont pas sur la première page. Le bouton **Importer** à côté téléverse un fichier depuis
votre poste.

💡 Les visuels d'un annonceur sont rangés automatiquement dans **Annonceurs / &lt;nom&gt;**.

## Fond généré par IA, et détourage

- **Générer le fond** (étape 5) : choisissez une *ambiance*, éventuellement une *zone à laisser
  vide* (pour que le produit ou le prix s'y posent) et une description libre.
- **Détourer** (étape 2) : retire l'arrière-plan de la photo produit et rend un PNG transparent.

Les deux consomment votre **clé IA d'organisation** (BYOK) et sont donc soumis aux plafonds de
dépense éventuels. Un refus de quota est annoncé **avant** l'appel, chiffré.

## Image ou vidéo

Sous l'aperçu, **Image** ou **Vidéo**. En vidéo, réglez la durée (3 à 15 s) et l'animation
(zoom avant, zoom arrière, fixe). La vidéo est encodée par le serveur : elle apparaît dans
**Visuels produits**, à droite, quand elle est prête.

## Mode série — un gabarit, N produits

La bascule **« Un visuel / Série »**, en haut de la page, remplace l'aperçu par un **tableau** :
une ligne par visuel.

🔑 **Le partage est le cœur du mode** : le parcours de gauche continue de définir ce qui est
**commun** (marque, mise en page, fond, mentions, devise, retouches) ; le tableau ne porte que ce
qui **varie** — image produit, slogan, prix, prix barré, remise. C'est ce partage qui fait passer
douze visuels de douze parcours complets à douze lignes.

**Trois façons de remplir le tableau**, qui se cumulent :

- **Ajouter une ligne** et saisir directement — pour corriger ou compléter.
- **Importer un CSV** — le fichier n'a besoin que des colonnes qui varient. Les en-têtes sont
  reconnus en français comme en anglais (`nom`/`produit`/`slogan`, `prix`, `prix barré`, `remise`),
  dans n'importe quel ordre, avec ou sans accents.
- **Coller depuis un tableur** — copiez les cellules dans Excel ou Google Sheets et collez-les :
  les colonnes séparées par des tabulations sont reconnues comme le `;` d'un export Excel.

⚠️ **Sans en-tête reconnu, les colonnes sont lues DANS L'ORDRE** (nom, prix, prix barré, remise)
et l'écran le signale. Vérifiez le tableau : c'est le seul cas où un prix pourrait se retrouver
dans la mauvaise colonne.

ℹ️ L'import **ajoute** au tableau, il ne le remplace pas : on peut importer deux fichiers, ou
compléter un import à la main.

### Une ligne incomplète n'arrête pas la série

Une ligne **sans prix** est surlignée, marquée « prix manquant », **nommée** dans l'avertissement
sous le tableau — et **ignorée**. Le reste de la série part quand même. Le bouton indique combien
de visuels seront réellement produits : « Générer les 4 ».

Chaque visuel est **nommé d'après son produit** : sans cela, N visuels arriveraient dans la
médiathèque sous le même nom. Leur avancement s'affiche dans **Visuels produits**, à droite.

## Enchaîner plusieurs visuels

- **Refaire avec un autre produit** (après une génération) garde la marque, la mise en page, le
  fond et les mentions, et ne vide que le produit et son prix.
- **Préréglages** (en haut à gauche) enregistre la configuration complète pour la rappeler plus
  tard.

## Questions fréquentes

**Le bouton Générer est gris.** Lisez le bandeau sous l'aperçu : il nomme ce qui manque (le plus
souvent le prix) et propose d'aller à l'étape concernée.

**Mes couleurs ne sont pas celles de la marque.** Étape 1 : vérifiez pour qui le visuel est fait.
Sans charte, le visuel garde les couleurs du gabarit. Voir la fiche *Chartes de marque*.

**Je ne trouve pas mon image.** Utilisez la recherche du tiroir plutôt que de faire défiler : elle
interroge le serveur et couvre toute la médiathèque, pas seulement la première page.

**Où est passé mon visuel ?** Dans la médiathèque, sous le nom donné à l'étape 3 (ou un nom par
défaut). Le panneau **Visuels produits** garde la liste de la séance en cours.
