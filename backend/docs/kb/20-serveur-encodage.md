---
title: Page Serveur et durée des encodages
section: exploitation
roles: []
keywords: [serveur, encodage, transcodage, ffmpeg, GPU, accélération matérielle, NVENC, VAAPI, lent, long, file d'attente, queue, décision requise, awaiting_decision, estimation, étalonnage, bandes, 20 minutes, 4 heures, définition inférieure, 1080p, 720p, downscale, barre de progression, débit, disque de travail, worker média, stockage, capacité]
---

# Page Serveur et durée des encodages

Chaque vidéo importée est **ré-encodée** pour que tous les écrans du parc puissent la lire.
C'est la tâche la plus lourde du serveur, et de loin : selon la machine et la source, elle
prend quelques secondes ou plusieurs heures. La page **Serveur** (`/settings/server`) sert à
savoir *pourquoi*, et le mécanisme d'estimation sert à ne pas le découvrir trop tard.

## Ce que montre la page Serveur

**Capacité d'encodage.** La ligne qui explique presque tout : *accélération matérielle
active* ou *aucune accélération matérielle*. Sans carte graphique exploitable, les encodages
tournent sur le processeur et sont **bien plus lents** — un facteur 5 à 10 sur une vidéo 4K.
La page indique aussi les encodeurs retenus pour H.264 et HEVC, et le nombre de cœurs.

**Débits constatés.** Les vitesses réellement mesurées lors des encodages précédents, par
encodeur. C'est une observation, pas une promesse : elle vient de vos propres fichiers.

**Disque de travail.** L'espace libre là où le worker écrit ses fichiers temporaires. Un
disque plein fait échouer les encodages sans que la cause soit évidente ailleurs.

**File d'encodage.** Ce qui est en cours, en attente, ou en attente d'une décision.

> **« Aucun worker média ne répond. »** Ce message n'est pas un détail d'affichage : il
> signifie qu'aucun encodage ne peut aboutir. Les informations de cette page viennent du
> **worker** et non du serveur web — c'est lui qui possède ffmpeg et voit le matériel. Quand
> il ne répond pas, la page le **dit** plutôt que d'afficher des valeurs périmées.

## Qui voit cette page

Le **détenteur de la licence** : le super-admin de la plateforme, ou l'administrateur d'une
organisation sur un serveur qui n'a pas de super-admin. Sur un serveur d'intégrateur, un
administrateur de marque n'y a pas accès et ne voit donc pas la file d'attente d'un autre
client. Si votre serveur est administré par un prestataire, l'écran vous l'indique : la
capacité et la file relèvent de son exploitation, vos contenus sont traités normalement.

## Les trois bandes de durée

Avant de lancer un encodage, le serveur **mesure** : il encode une dizaine de secondes de
**votre** fichier avec la commande exacte qui sera utilisée, puis extrapole. Une mire de
test s'encoderait bien plus vite qu'un vrai plan — on promettrait 15 minutes pour en prendre
40.

| Durée estimée | Ce qui se passe |
|---|---|
| **moins de 20 minutes** | l'encodage part tout seul |
| **entre 20 minutes et 4 heures** | **vous décidez** : le média attend, marqué *Décision requise* |
| **plus de 4 heures** | refusé par défaut ; un administrateur peut passer outre |

**Un refus n'est pas une impasse.** L'écran propose d'encoder en **définition inférieure**
(1080p, 720p), chacune avec sa propre estimation : une 4K de 4 heures devient souvent une
1080p de 25 minutes. Le média reste visible et filtrable dans la médiathèque tant que la
décision n'est pas prise.

> **Si la mesure est impossible, rien n'est bloqué.** Le serveur ne refuse jamais un
> encodage sur une estimation qu'il n'a pas pu faire — un contrôle qui ne sait pas conclure
> ne décide pas.

## La barre de progression

Pendant l'encodage, le tiroir du média affiche l'avancement réel et une estimation du temps
restant, puis une phase de **finalisation** (envoi vers le stockage, contrôle de conformité)
— sans elle, une barre bloquée à 99 % se lirait comme un plantage. Si le worker meurt, la
barre **disparaît** au lieu de rester figée : c'est le bon mode de panne, il vous dit qu'il
n'y a plus personne au travail.

## Questions fréquentes

**« Mon encodage dure depuis des heures. »** Ouvrez la page Serveur : si l'accélération
matérielle est absente, c'est l'explication la plus probable. Comparez la durée écoulée à
l'estimation affichée au lancement.

**« J'ai importé une vidéo, rien ne se passe. »** Regardez la médiathèque : le média est
peut-être en *Décision requise*. Il attend votre arbitrage, il n'est pas en panne.

**« Pourquoi ma 4K est-elle si lente ? »** Au-delà de la Full HD, le produit encode en HEVC,
plus lourd que le H.264. Sur un serveur sans carte graphique, c'est le cas le plus coûteux
qui existe — d'où les bandes de durée.

**« La vitesse annoncée ne correspond pas. »** L'estimation vient d'un échantillon de votre
propre fichier : une source dont la complexité varie beaucoup (plans fixes puis mouvement)
s'écarte davantage. La bande de décision existe pour ça.
