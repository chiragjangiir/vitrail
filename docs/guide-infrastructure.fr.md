# Dimensionnement serveur, bande passante, stockage & encodage

🇬🇧 [English version](guide-infrastructure.md)

*Vitrail · Infrastructure · Capacity planning*

Par palier de parc — < 200, 200–500, 500–1000, 1000+ players. Avec hypothèses et exemples chiffrés.

Ce guide dimensionne l'infrastructure Vitrail selon la taille du parc. Le point d'architecture qui change tout : grâce au **download-then-play** (les players cachent les médias et les lisent **en local**, jamais en streaming), la charge ne ressemble pas à celle d'un CMS « streaming ». Trois ressources se dimensionnent **indépendamment**, et chacune suit un driver différent.

> **Les 3 vérités de dimensionnement**
>
> 1. **Bande passante** → suit le **volume de contenu × fréquence de refresh**, par rafales, pas le nb de players.
> 2. **Stockage objet** → suit la **taille du catalogue**, quasi pas le nb de players.
> 3. **Encodage** → suit le **débit d'ingestion (uploads)**, pas le nb de players. GPU >> CPU.

## Sommaire

1. [Les deux plans de charge](#1-les-deux-plans-de-charge)
2. [Hypothèses de référence](#2-hypothèses-de-référence)
3. [Bande passante](#3-bande-passante)
4. [Stockage (3 couches)](#4-stockage--trois-couches)
5. [Encodage (cœurs & GPU)](#5-encodage--cœurs--gpu)
6. [Synthèse serveur par palier](#6-synthèse-serveur-par-palier)
7. [3 scénarios complets chiffrés](#7-trois-scénarios-complets-chiffrés)
8. [Leviers de scaling](#8-leviers-de-scaling-ordre-de-rentabilité)

## 1. Les deux plans de charge

Toute la charge Vitrail se range dans deux catégories qui n'ont rien à voir :

| Plan | Contenu | Dépend de | Verdict |
|------|---------|-----------|---------|
| **Contrôle** | WebSocket persistant, heartbeats, sync, commandes, proof-of-play | Nb de players | **Négligeable.** 1000 players ≈ qq centaines de kbps + ~700 écritures PG/s. **Jamais le goulot.** |
| **Contenu** | Distribution des médias depuis l'object storage vers les players | Volume × players × refresh × **fenêtre** | **Le seul vrai dimensionnant.** Par rafales (pas un flux continu). |

> **À retenir**
>
> On **ne** dimensionne **pas** la bande passante à `N × débit vidéo` (ça, c'est le modèle streaming). On la dimensionne pour **distribuer le contenu dans la fenêtre de mise à jour**. C'est ce qui rend Vitrail beaucoup plus léger — et moins cher — qu'un CMS classique.

## 2. Hypothèses de référence

Tous les exemples ci-dessous partent de ces valeurs. **Adaptez-les à votre réalité** : ce sont elles, et non le nombre de players, qui pilotent les chiffres.

| Paramètre | Valeur retenue | Note |
|-----------|----------------|------|
| Content-set par player (`R`) | **500 Mo** (parc FHD) · **2 Go** (parc 4K lourd) | Total des médias cachés par un écran |
| Taille master moyenne d'un asset | **70 Mo** (FHD) · **180 Mo** (4K HEVC ~30 s) | Mix images + vidéos |
| Facteur renditions | **×1,5** | master + FHD + HD720 + miniature (`auto_fhd`) |
| Fenêtre de propagation (`T`) | **4 h** (push de nuit) | Délai accepté pour qu'un nouveau contenu touche tout le parc |
| Plays / jour / player | **~3000** | Heures d'ouverture, boucle de playlist |
| Rétention proof-of-play | **90 jours** chauds | Au-delà → archivage Parquet / drop de partition |
| Provision sur les moyennes | **×2 à ×3** | Pour absorber les pics |

## 3. Bande passante

```
BP moyenne (Mbps) = ( N players × R Mo/player ) × 8 / ( T fenêtre en secondes )
```

| Palier | Calcul (R=500 Mo, T=4 h) | Moyenne | À provisionner |
|--------|--------------------------|---------|----------------|
| < 200 | 200 × 500 / 14400 | ~55 Mbps | **100–200 Mbps** symétrique · lien fibre pro |
| 200–500 | 500 × 500 / 14400 | ~140 Mbps | **300–500 Mbps** *ou CDN (→ ~100 Mbps origine)* |
| 500–1000 | 1000 × 500 / 14400 | ~280 Mbps | **CDN quasi obligatoire** · sinon ~1 Gbps |
| 1000+ | CDN edge | — | Origine **indépendante** du nb de players · CDN absorbe l'egress |

> **⚡ Le levier qui change tout : la fenêtre de propagation**
>
> - 1000 players × 500 Mo en **4 h** → 500 000 Mo × 8 / 14 400 s = **~280 Mbps** (gérable)
> - Les mêmes en **15 min** → 500 000 × 8 / 900 = **~4 440 Mbps** (≈ 4,4 Gbps !)
>
> → Pour le contenu programmé, gardez des fenêtres larges (nuit). Réservez la propagation rapide aux triggers légers (events, VOD) qui sont **déjà pré-cachés**.

> **Piège : plusieurs écrans par site**
>
> Le LAN sync gère la **synchro de lecture**, **pas** le partage de contenu : 4 écrans d'un même magasin tirent chacun leur copie depuis le serveur. Un **CDN** ou un **cache par site** élimine cette redondance — gain majeur quand il y a beaucoup d'écrans par lieu.

## 4. Stockage — trois couches

| Couche | Rôle |
|--------|------|
| 🗄️ **Object storage** | MinIO / S3 : master + renditions + miniatures. Scale avec le **catalogue**, ~pas le nb de players. |
| 🐘 **Base Postgres** | Métadonnées (petit) + **logs partitionnés** (proof-of-play, audience, audit). Scale avec players **× temps**. |
| 💾 **Côté player** | Cache local du content-set. **2–3×** le content-set (ancien + nouveau pendant le swap) + OS. |

```
Object storage ≈ Nb assets × taille master moy × facteur renditions (~1,5)
DB / an        ≈ N players × plays/jour × ~0,3 Ko × jours de rétention   (proof-of-play dominant)
Disque player  ≈ R × 2–3  + OS
```

| Palier | Object storage (médias) | DB Postgres | Côté player |
|--------|-------------------------|-------------|-------------|
| < 200 | Catalogue 0,3–1k assets → **30–150 Go**<br>*Provision 500 Go–1 To NVMe, MinIO local OK* | ~50–100 Go<br>*PoP ~15 Go/an* | RPi 32–64 Go · mini-PC 128–256 Go<br>*⚠ box Android 16–32 Go eMMC = facteur limitant* |
| 200–500 | 0,2–1 To → **1–2 To**<br>*Commencer à externaliser (S3/GCS)* | ~100–200 Go<br>*PoP ~40 Go/an + rétention* | idem · 128–256 Go SSD |
| 500–1000 | 0,5–3 To → **S3/GCS + lifecycle**<br>*Plus de MinIO local* | ~200–400 Go<br>*PG managé + drop de partition* | 256 Go si parc 4K |
| 1000+ | Multi-To → dizaines de To<br>*S3 + tiering chaud/froid + CDN* | 0,5–1 To+<br>*Réplicas + archivage Parquet* | 256 Go+ · surveiller les eMMC Android |

> **Le vrai piège stockage = les box Android**
>
> L'eMMC d'une box TV (16–32 Go, soudé, non extensible) sature bien avant le serveur : un content-set 4K de 2–4 Go × 2–3 (swap atomique) ne tient pas sur 16 Go. → Pour le **4K**, privilégier des mini-PC à SSD, ou des box avec microSD/USB. L'éviction de cache priority-aware est déjà en place côté player.

## 5. Encodage — cœurs & GPU

L'encodage (transcode ffmpeg sur le worker `celery-media`) scale avec le **volume d'ingestion**, pas avec le nombre de players. C'est un tier **séparable** : on ajoute des nœuds d'encodage qui tirent la même file Celery/Redis, sans toucher au backend ni à la DB.

> **GPU vs software : un ordre de grandeur (mesuré)**
>
> Burst de 10 vidéos dont une de 2 Go, sur une RTX 5050 :
>
> - **Software** libx264/x265 → **load CPU ~370**, serveur à genoux
> - **GPU NVENC** → encodeur NVENC 100 %, **GPU compute 6 %, load CPU ~2**
>
> L'ASIC NVENC encode **hors des cœurs CPU** → avec GPU, le dimensionnant devient le **GPU**, pas les cœurs.

### Budget par flux concurrent

| Mode | FHD H.264 | 4K HEVC |
|------|-----------|---------|
| **Software (x264/x265)** | ~4–6 cœurs/flux pour rester > temps réel | 16+ cœurs/flux **et toujours plus lent que le temps réel** → à éviter |
| **GPU NVENC** | dizaines de flux 1080p > temps réel / carte | plusieurs flux 4K HEVC simultanés / carte |

*⚠ Limite GPU : les GeForce grand public plafonnent les sessions NVENC concurrentes (~3 à 8 selon le driver) ; les cartes pro/datacenter **T4 / L4 sont déplafonnées** — ce qui compte dès qu'on encode beaucoup en parallèle, en continu.*

### Recommandation par palier

| Palier | Encodage recommandé | Cœurs à réserver |
|--------|---------------------|------------------|
| < 200 | **1 GPU NVENC** (même grand public) sur le serveur | GPU : ~2 cœurs. *Sans GPU : 8–12 cœurs dédiés, FHD only* |
| 200–500 | **1 GPU** (T4/L4 si 4K ou parallèle soutenu) | 2–4 cœurs · plus de 4K software |
| 500–1000 | **Nœud d'encodage dédié** avec GPU (1× L4/T4) | 4–8 cœurs sur le nœud (muxing/IO) |
| 1000+ | **Pool d'encodage horizontal** (N nœuds GPU) | scale le pool selon le débit d'ingestion |

> **3 variables qui pilotent le tier encode**
>
> 1. Débit d'ingestion (Go uploadés / fenêtre) — le vrai driver
> 2. Nb de renditions (**2–3 encodes par fichier**, pas un)
> 3. Part de 4K HEVC (coûteux) vs FHD H.264 (léger)
>
> *Les garde-fous anti-surcharge (concurrence adaptative, `nice 19`, prefetch/acks_late, worker média isolé) empêchent déjà un burst de faire tomber le serveur.*

## 6. Synthèse serveur par palier

| Palier | Déploiement | App / DB / storage | Encodage | Bande passante |
|--------|-------------|--------------------|----------|----------------|
| < 200 | **On-prem 1 serveur** ou 1 VM cloud — tout co-localisé en Docker | 8 vCPU · 32 Go RAM · 0,5–1 To NVMe | +1 GPU NVENC | 100–200 Mbps symétrique |
| 200–500 | On-prem costaud **ou** cloud · sortir l'object storage | 16 vCPU · 64 Go RAM · 1–2 To · DB séparable | 1 GPU (T4/L4) | 300–500 Mbps **ou CDN** |
| 500–1000 | **Cloud / hybride** · CDN quasi obligatoire | App ×2 derrière LB (8–16 vCPU) · PG managé 8 vCPU/32 Go · Redis managé · S3+CDN | Nœud GPU dédié | Origine faible (CDN) |
| 1000+ | **Cloud-native, scale horizontal** · CDN obligatoire | Backends multiples (WS shardés, fan-out Redis) · PG + réplicas · Redis cluster · S3+tiering | Pool GPU | CDN edge · origine ∝ catalogue |

*Au-delà de ~100k players, l'`EventBus` est prévu pour passer de Redis Streams à Kafka (interface déjà abstraite).*

## 7. Trois scénarios complets chiffrés

### Scénario A — Chaîne retail, 150 players, FHD

**Hypothèses :** 150 écrans · content-set 500 Mo · catalogue 600 assets FHD · refresh hebdo de nuit (50 nouveaux assets/sem) · push 4 h.

- **BP** : 150 × 500 Mo × 8 / 14 400 s = **~42 Mbps** moy → provision **100 Mbps**
- **Object storage** : 600 × 70 Mo × 1,5 = **~63 Go** → provision **500 Go NVMe** (MinIO local)
- **DB** : 150 × 3000 × 0,3 Ko × 90 j = ~12 Go PoP → **~40 Go** DB
- **Encodage** : 50 assets FHD/sem → **1 GPU grand public** vide la file en minutes (ou 8 cœurs software)
- **Player** : 500 Mo × 3 + OS ≈ 2 Go → RPi 32 Go ou mini-PC, sans souci

→ **1 serveur on-prem** : 8 vCPU, 32 Go RAM, 500 Go NVMe, 1 GPU NVENC, lien 100 Mbps.

### Scénario B — Réseau mixte, 400 players

**Hypothèses :** 400 écrans · content-set 700 Mo (mix FHD + un peu de 4K) · catalogue 1500 assets · refresh bi-hebdo · push 4 h.

- **BP** : 400 × 700 Mo × 8 / 14 400 s = **~155 Mbps** moy → **300–400 Mbps** ou CDN
- **Object storage** : 1500 × 70 Mo × 1,5 = **~158 Go** → provision **1 To**, S3 conseillé
- **DB** : 400 × 3000 × 0,3 Ko × 90 j = ~32 Go PoP → **~80 Go** DB
- **Encodage** : mix 4K → **1 GPU T4/L4**, worker `celery-media` séparé
- **Player** : 700 Mo × 3 ≈ 2,1 Go → mini-PC 128 Go SSD

→ **Serveur costaud ou cloud** : 16 vCPU, 64 Go RAM, 1 To, GPU T4/L4, lien 400 Mbps + CDN recommandé.

### Scénario C — Grand réseau 4K, 1200 players

**Hypothèses :** 1200 écrans · content-set 2 Go (4K) · catalogue 4000 assets (master 4K HEVC) · refresh fréquent · push 4 h · CDN.

- **BP** sans CDN : 1200 × 2000 Mo × 8 / 14 400 s = **~1,3 Gbps** → **CDN obligatoire** (origine ne fait que remplir le CDN)
- **Object storage** : 4000 × 180 Mo × 1,5 = **~1,08 To** → provision **2–3 To S3** + lifecycle
- **DB** : 1200 × 3000 × 0,3 Ko × 90 j = ~97 Go PoP → **~250 Go** DB, PG managé + réplicas
- **Encodage** : 4K HEVC volumineux → **pool de nœuds GPU L4** dédiés
- **Player** : 2 Go × 3 + OS ≈ 7 Go → **mini-PC 256 Go SSD** (pas de box 16 Go eMMC)

→ **Cloud-native** : backends ×N derrière LB, PG managé + réplicas, Redis cluster, S3 + tiering, **CDN**, pool GPU L4 pour l'encodage.

## 8. Leviers de scaling (ordre de rentabilité)

1. **CDN devant les médias** (CloudFront / Cloudflare / Bunny devant S3/MinIO) — de loin le plus gros gain, retire ~90 % de l'egress origine. *À brancher : le player sert des URLs signées S3v4, compatibles CDN mais pas encore câblées.*
2. **Object storage externalisé** (S3/GCS) au lieu de MinIO local.
3. **Rétention + drop de partitions** (pg_partman, déjà partitionné) — borne la DB. PoP = seul gros grossissant.
4. **Postgres managé** (heartbeats + tables partitionnées montent bien, déléguer la maintenance).
5. **Backends horizontaux** (le fan-out Redis par canal `player:{id}` le permet déjà).
6. **Pool d'encodage GPU** séparé, scalé sur le débit d'ingestion (indépendant de l'app/DB).
7. **Cache par site / lifecycle froid / dédup par hash** — gains additionnels en multi-tenant.

> **Trois corrections à ne pas oublier**
>
> 1. Sous 500 players, le serveur **doit** avoir un GPU NVENC — sinon réserver 8–12 cœurs *en plus* rien que pour l'encodage (et oublier le 4K).
> 2. Dès 500+, **séparer physiquement** le nœud d'encodage GPU du nœud app/DB.
> 3. En cloud, prendre des instances **GPU média (L4/T4)** pour l'encodage, pas des grosses instances CPU.

---

**Vitrail — Guide de dimensionnement infrastructure.** Les chiffres dépendent de votre profil réel (taille de catalogue, débit d'ingestion, part de 4K, fenêtre de propagation acceptable, nb d'écrans par site). Recalculez avec vos valeurs via les formules des sections 3 à 5. Document indicatif — à affiner par un test de charge avant un déploiement > 500 players.
