---
title: Génération de contenu par IA
section: content
roles: [CMS_ORG_ADMIN, CMS_DESIGNER, CMS_CAMPAIGN_MANAGER]
keywords: [génération, IA, image, vidéo, prompt, negative prompt, assistant, image vers vidéo, i2v, fal, ElevenLabs, studio, campagne, clé IA]
---

# Génération de contenu par IA

SignFlow peut générer des **images**, des **vidéos**, de la **musique** et des **voix off**
à partir d'une description en langage naturel. Le média généré devient un média normal de la
médiathèque (renditions par écran, playlists, paniers audio).

## Pré-requis : vos clés IA (BYOK)

La génération utilise **les clés de votre organisation** (vous payez votre propre fournisseur).
Configurez-les dans **Réglages → Clés IA** :

- **fal.ai** : images, vidéos, musique, voix.
- **ElevenLabs** : musique et voix (alternative, qualité commerciale).
- **Anthropic** : nécessaire pour l'**assistant de rédaction de prompt** et le directeur créatif
  du Studio.

Sans la clé concernée, la fonction reste visible mais inactive (« configurez vos clés IA »).

## Où générer

- **Médiathèque → Générer (IA)** : un asset isolé (image, vidéo ou audio).
- **Studio** : une **campagne** complète à partir d'un brief (concepts visuels déclinés par
  format, + vidéo / voix / musique).

## Écrire un bon prompt

Les modèles de génération sont **entraînés majoritairement en anglais**. Saisissez votre prompt
en anglais si possible, ou laissez **l'assistant de rédaction de prompt** le faire pour vous.

### L'assistant de rédaction de prompt

Sous le champ de description, dépliez **« Assistant de rédaction du prompt »**. Décrivez votre
idée dans **n'importe quelle langue** ; l'assistant produit un prompt **anglais optimisé** adapté
au modèle choisi, et un **prompt négatif** quand le modèle le supporte. Le résultat pré-remplit
les champs — il reste **entièrement modifiable**. Deux modes :

- **Direct** : une idée → un prompt.
- **Conversationnel** : l'assistant peut poser 1 à 3 questions avant de livrer le prompt.

### Bonnes pratiques

- Décrivez un **sujet + une action + un style** ; pour la vidéo, ajoutez la **caméra** et la
  **lumière**.
- Restez **simple** : 3 à 5 éléments au maximum, des mots concrets.
- Évitez les nombres précis (« 10 produits ») et les mouvements compliqués.
- N'écrivez pas de **méta-instructions** (« contenu promotionnel à diffuser sur des écrans ») :
  le modèle ne les exécute pas, il les **dessine** — d'où des bandeaux de texte parasites.

### Prompt négatif

Le **prompt négatif** liste ce que le modèle doit éviter. Valeurs utiles par défaut :
`text, banner, watermark, letters, blurry, warped faces`. Il neutralise notamment les bandeaux
de texte incrustés. Le champ n'apparaît que pour les modèles qui le supportent (FLUX dev, Qwen,
MiniMax, WAN, Kling…).

## Animer une image (image → vidéo)

Pour transformer une image en vidéo (modèles « image→vidéo »), fournissez une **image de
référence** nette, au sujet clair, sans fond chargé. Dans le prompt, **décrivez uniquement le
mouvement** à insuffler — pas une nouvelle scène :

- mouvement ambiant subtil : eau, nuages, feuillage, vapeur, scintillement de lumière ;
- au plus **un** léger mouvement de caméra (ex. *slow push-in*) ;
- bannissez « promotional / screens / text / banner / poster » du prompt, et ajoutez-les au
  prompt négatif.

## Coût

Un **estimatif de coût** s'affiche en direct (selon le modèle, la résolution et la durée).
Pour tester un style, commencez par une vidéo **courte** (quelques secondes) avant de générer
plus long. Le Studio affiche le **coût total** de la campagne avant de lancer la génération.
