---
title: Campagnes retail media (publicité annonceurs)
section: content
roles: []
keywords: [campagne, retail media, annonceur, publicité, SOV, part de voix, inventaire, surbooking, plafond, tarif, devis, SOV réalisable, exclusion concurrentielle, catégorie, créatif, durée max, approbation, rapport annonceur, calendrier, import, preuve de diffusion, CPM, monétisation]
---

# Campagnes retail media (publicité annonceurs)

La page **Campagnes** transforme vos écrans en **inventaire publicitaire monétisable** :
un annonceur (marque) achète une **part de voix (SOV)** — un pourcentage du temps
d'antenne — sur une période et des écrans donnés. SignFlow intercale automatiquement ses
créatifs dans la boucle de contenu, mesure la diffusion réelle (preuves signées) et
produit le **rapport annonceur** chiffré.

## Concepts

- **Annonceur** : la marque cliente (page **Campagnes → Annonceurs**). Sa création ouvre
  automatiquement un dossier médiathèque « Annonceurs/&lt;nom&gt; ». Un annonceur porte
  une ou plusieurs **catégories d'industrie** (voir exclusion concurrentielle) et peut
  recevoir des **accès portail** (voir la fiche Portail annonceur).
- **Campagne** : période (dates + fenêtre horaire quotidienne optionnelle), SOV vendue en %,
  modèle de prix (**SOV** ou **forfait**, CPM indicatif), cibles (org / site / **groupe de
  sites** / groupe / player — cumulables) et créatifs (vidéos ou images, rotation pondérée).
- **Statuts** : brouillon → publiée (**programmée** avant la date de début, **live**
  pendant, **terminée** après) ; pause/reprise/annulation à tout moment. La pause retire
  les créatifs des écrans immédiatement. La **suppression** d'une campagne nettoie tout
  (diffusion, inventaire, liens annonceur révoqués).
- **Opt-out** : un player marqué « Exclu des campagnes publicitaires » (drawer player) ne
  diffuse jamais de créatif et ne compte pas dans l'inventaire (écran caisse, back-office).

## Inventaire, plafonds et tarifs par écran

Le panneau **Inventaire** montre la part de voix déjà vendue par écran. À la saisie d'une
campagne, la projection d'occupation avertit à **80 %** et **bloque à 100 %** (un org-admin
peut forcer explicitement — surbooking assumé, les parts sont alors réduites
proportionnellement). Chaque écran peut porter :

- un **plafond d'occupation publicitaire** (drawer player, hérité du site sinon) : un écran
  de caisse plafonné à 20 % ne dépassera jamais 20 % de publicité — les seuils 80/100 %
  s'entendent alors **par rapport au plafond** ;
- un **tarif** (€ pour 1 % de SOV par jour, hérité org → site → player) : le drawer
  campagne affiche un **devis indicatif** (total, écrans tarifés, jours). Le **prix
  contractuel** de la campagne reste un champ saisi à la main — le devis aide à le fixer.

## SOV réalisable

Vendre 40 % de SOV sur un écran dont la boucle est longue peut être physiquement
impossible (une seule pub par tour de boucle). Le bandeau **« SOV réalisable »** (ambre)
calcule le maximum atteignable selon la boucle réellement programmée et la durée moyenne
des créatifs, et propose **« Utiliser X % »** en un clic. L'écart est aussi visible du
valideur dans la file d'approbation.

## Exclusion concurrentielle

Gérez des **catégories d'industrie** (bouton Catégories, page Annonceurs) et affectez-les
aux annonceurs (une agence peut en porter plusieurs). Sur chaque **site**, listez les
catégories **exclues** (ex. un magasin sous contrat exclusif boissons) : les campagnes des
annonceurs concernés ne peuvent ni cibler ni diffuser sur ce site — ciblage, occupation,
devis, rapport et portail (sites grisés) l'appliquent partout.

## Créatifs : durée max et approbation

- **Durée maximale d'un créatif** : réglable au niveau org (défaut **30 s**, vide =
  illimité) — un créatif trop long est refusé à l'ajout et re-vérifié à la publication.
- Case **« Approbation des créatifs requise »** (org-admin) : tout **nouveau créatif**
  arrive **En attente** et doit être approuvé avant diffusion ; un créatif rejeté ne passe
  jamais à l'écran. Les créatifs **téléversés par un annonceur** (portail) naissent
  toujours en attente. Voir aussi la fiche **Validations (workflow d'approbation)** pour
  l'approbation de la campagne entière.

## Diffusion et preuve

Les créatifs sont **intercalés dans la boucle existante** des écrans ciblés, à la fréquence
correspondant à la SOV vendue — sans toucher aux playlists, et **jamais deux spots dos à
dos** : au plus une publicité par tour de boucle (anti-martèlement). Si la SOV vendue
dépasse ce que la boucle permet, l'excédent devient du **sous-service mesuré** (alerte
« campagne sous-servie »). Chaque passage génère une **preuve de diffusion** horodatée,
chaînée (Merkle) et **signée par l'écran** (Ed25519). Conseil groupes synchronisés (LAN
sync) : ciblez des groupes **entiers**.

## Calendrier et import

- Le panneau **Calendrier** de la page Campagnes affiche un Gantt mensuel des campagnes
  avec la **charge par jour** (ambre ≥ 80 %, rouge > 100 %).
- **Importer (JSON)** : créez une campagne complète depuis un fichier (annonceur, cibles
  par noms, créatifs par URL) — **aperçu (dry-run)** avec projection d'occupation avant
  création, publication toujours manuelle. Le même import existe **par API** avec une clé
  machine `sfi_` (scope campaigns:import) pour brancher un outil externe.

## Rapport annonceur

Bouton **Rapport** dans le drawer : passages (dont signés), temps d'antenne, **SOV servi
vs vendu**, répartition **hiérarchique groupes → sites → écrans** (repliable), par jour et
par créatif, montant. Export **PDF white-label** (au niveau de détail choisi) et **lien
public protégé** (mot de passe, allowlist IP) à envoyer à l'annonceur.

## Notifications

Dans **Réglages → Notifications** (canaux **webhook ou email**) : **campagne démarrée**,
**campagne terminée** (bilan) et **campagne sous-servie** (SOV servi sous un seuil du
vendu — 80 % par défaut, réglable par règle).

## Demander à l'assistant

L'assistant (et Jeanine sur Telegram) répond à « **où en est la campagne X ?** » (statut,
dates, cibles, créatifs) et « **le rapport de la campagne X** » (passages, SOV servi,
montant — réservé aux comptes ayant la permission campaigns : report).
