---
title: Entrée HDMI (diffuser une source externe)
section: media
roles: []
keywords: [HDMI, entrée HDMI, hdmi-in, source externe, décodeur TV, box, switch, bascule, BrightSign, no signal, /control, VOD HDMI, prise d'antenne]
---

# Entrée HDMI : diffuser une source externe sur un écran

Le média **« Entrée HDMI »** permet d'afficher sur un écran **n'importe quelle source
branchée** sur l'entrée HDMI du player : décodeur TV, box du magasin, console de démo,
ordinateur… La lecture est purement locale (rien ne transite par le serveur).

**Players compatibles** : BrightSign avec entrée HDMI physique — gammes **XT** (XT1143/1144/
1145, XT2145…), **4K1142/4K1242** et **XD1230**. Les gammes HD/LS et les autres types de
players n'ont pas d'entrée : ils ignorent ce média.

## Créer le média

Médiathèque → bouton **Entrée HDMI** → donnez-lui un nom. C'est un média « pointeur » : pas de
fichier, pas de téléchargement.

## L'utiliser en playlist (créneau programmé)

Ajoutez le média à une playlist comme n'importe quel contenu, avec une **durée** : pendant ce
créneau, le player bascule sur sa source HDMI, puis reprend la playlist. Les players sans
entrée HDMI **ne reçoivent jamais cet item** (ils enchaînent sur le reste) ; à la création du
programme, un avertissement liste les players ciblés non compatibles.

**Pas de signal ?** Si la source est débranchée ou éteinte, l'écran affiche
**« No Signal Detected »** (après ~3 s) au lieu d'un écran noir, pour la durée de l'item — la
playlist n'est pas décalée. Dès que le signal revient, l'image s'affiche toute seule.

## Le switch à la demande (VOD)

Pour basculer **quand vous voulez** (pas à heure fixe) : créez une **config VOD** (page
On-Demand) contenant le média Entrée HDMI — seuls les players compatibles sont proposés.
Deux boutons remplacent la lecture classique :
- **Basculer sur HDMI** : l'écran passe sur la source, la playlist est suspendue ;
- **Revenir à la playlist** : reprise exactement là où la programmation en est (pas au début).

## Le pilotage local, sans CMS

Chaque BrightSign compatible sert une **page de contrôle locale** :
`http://<ip-du-player>:8888/control` — utilisable depuis n'importe quel téléphone ou PC du
réseau du magasin, sans compte ni serveur, même hors ligne. Deux boutons : basculer / revenir.

## Garde-fous et traçabilité

- **Extinction automatique** : si l'écran s'éteint (fermeture du site, coupure manuelle), un
  switch resté actif est **terminé automatiquement** — le lendemain, la playlist reprend
  normalement.
- **Tout est tracé** : chaque bascule apparaît dans le journal d'audit (source du
  déclenchement — VOD, drawer ou page locale — et durée réelle), et une **preuve de diffusion
  signée** est émise avec la durée réelle de la session (visible dans les rapports Proof of
  Play, comme l'item de playlist).
