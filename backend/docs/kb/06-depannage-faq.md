---
title: Dépannage et questions fréquentes
section: troubleshooting
roles: []
keywords: [dépannage, problème, FAQ, écran noir, hors-ligne, player déconnecté, son, média indisponible, aide]
---

# Dépannage et questions fréquentes

## Un player apparaît hors-ligne

Le serveur initie toujours la connexion vers le player : vérifiez que l'appareil est
allumé, connecté au réseau, et que l'URL du serveur configurée est joignable depuis lui.
Le badge d'état affiche la date de dernier contact. Un player hors-ligne **continue de
diffuser** son dernier contenu reçu, car il fonctionne en mode local.

**Hors-ligne la nuit ou hors horaires d'ouverture ?** C'est normal si l'auto-power éteint
ses écrans : certains appareils (box Android notamment) coupent aussi leur réseau en veille.
Le player est alors marqué **« Veille programmée »** — aucune alerte n'est levée, et il
revient tout seul à l'ouverture. Une alerte ne part que s'il n'est **pas revenu** quelques
minutes après l'heure d'ouverture.

## L'écran affiche « No Signal Detected »

Cet écran apparaît pendant un contenu **« Entrée HDMI »** quand la source branchée sur le
player (décodeur, box…) n'émet pas de signal : source éteinte, câble débranché ou mauvaise
entrée. Rallumez/rebranchez la source — l'image revient automatiquement en quelques secondes,
sans toucher au player.

## L'écran affiche « Média indisponible »

C'est généralement un player dont le logiciel n'est pas à jour pour le type de contenu
programmé (par exemple un feed ou une page web sur une version trop ancienne). Mettez le
player à jour. Vérifiez aussi que le média a bien fini son traitement côté serveur.

## L'écran reste noir ou fige

- Vérifiez que le média est bien transcodé (statut dans la Médiathèque).
- Sur les murs synchronisés, assurez-vous que le groupe est **homogène** (même matériel) ;
  un groupe hétérogène peut provoquer des décalages ou des sauts.
- Le bouton **« Infos à l'écran »** du drawer player affiche un diagnostic directement sur
  l'écran (média en cours, résolution réellement jouée, état réseau) pour situer le
  problème.

## Pas de son

Le son dépend du **rôle audio** du player : « Contenus standards » joue le son des vidéos
sans musique de fond ; « Audio seul » joue uniquement un fond sonore (paniers audio) ;
« Mixte » joue le fond sonore avec les contenus mutés. Vérifiez aussi le volume poussé
depuis le drawer player et que le son n'est pas coupé.

## Le contenu ne se met pas à jour

Toute modification (playlist, programmation, configuration) pousse normalement une
synchronisation immédiate aux players en ligne. Si rien ne change, vérifiez que le player
est en ligne et que la programmation cible bien ce player (ou son groupe).

## Hors-ligne : qu'est-ce qui continue de marcher ?

Les players natifs (Linux, Raspberry Pi, Windows, Android, ChromeOS PWA) téléchargent leur
contenu et le jouent **localement**. Ils continuent donc de diffuser playlists, vidéos,
images, feeds (avec leurs vignettes en cache) même serveur ou Internet coupés. L'extension
Chrome, elle, fonctionne surtout en ligne.
