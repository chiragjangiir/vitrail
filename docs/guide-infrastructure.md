# Server, bandwidth, storage & encoding sizing

🇫🇷 [Version française](guide-infrastructure.fr.md)

*Vitrail · Infrastructure · Capacity planning*

By fleet size — < 200, 200–500, 500–1000, 1000+ players. With assumptions and worked examples.

This guide sizes the Vitrail infrastructure according to fleet size. The architectural point that changes everything: thanks to **download-then-play** (players cache media and play it **locally**, never streamed), the load looks nothing like a "streaming" CMS. Three resources are sized **independently**, and each follows a different driver.

> **The 3 sizing truths**
>
> 1. **Bandwidth** → follows **content volume × refresh frequency**, in bursts, not the number of players.
> 2. **Object storage** → follows **catalogue size**, barely the number of players.
> 3. **Encoding** → follows the **ingestion rate (uploads)**, not the number of players. GPU >> CPU.

## Contents

1. [The two load planes](#1-the-two-load-planes)
2. [Reference assumptions](#2-reference-assumptions)
3. [Bandwidth](#3-bandwidth)
4. [Storage (3 layers)](#4-storage--three-layers)
5. [Encoding (cores & GPU)](#5-encoding--cores--gpu)
6. [Server summary by tier](#6-server-summary-by-tier)
7. [3 complete costed scenarios](#7-three-complete-costed-scenarios)
8. [Scaling levers](#8-scaling-levers-by-cost-effectiveness)

## 1. The two load planes

All Vitrail load falls into two categories that have nothing in common:

| Plane | Content | Depends on | Verdict |
|-------|---------|------------|---------|
| **Control** | Persistent WebSocket, heartbeats, sync, commands, proof-of-play | Number of players | **Negligible.** 1000 players ≈ a few hundred kbps + ~700 PG writes/s. **Never the bottleneck.** |
| **Content** | Media distribution from object storage to players | Volume × players × refresh × **window** | **The only real sizing factor.** In bursts (not a continuous stream). |

> **Key takeaway**
>
> You do **not** size bandwidth at `N × video bitrate` (that is the streaming model). You size it to **distribute the content within the update window**. That is what makes Vitrail much lighter — and cheaper — than a conventional CMS.

## 2. Reference assumptions

All the examples below start from these values. **Adapt them to your reality**: it is these values, not the number of players, that drive the figures.

| Parameter | Value used | Note |
|-----------|------------|------|
| Content-set per player (`R`) | **500 MB** (FHD fleet) · **2 GB** (heavy 4K fleet) | Total media cached by one screen |
| Average master size of an asset | **70 MB** (FHD) · **180 MB** (4K HEVC ~30 s) | Mix of images + videos |
| Renditions factor | **×1.5** | master + FHD + HD720 + thumbnail (`auto_fhd`) |
| Propagation window (`T`) | **4 h** (overnight push) | Accepted delay for new content to reach the whole fleet |
| Plays / day / player | **~3000** | Opening hours, playlist loop |
| Proof-of-play retention | **90 days** hot | Beyond that → Parquet archiving / partition drop |
| Provisioning over averages | **×2 to ×3** | To absorb peaks |

## 3. Bandwidth

```
Average BW (Mbps) = ( N players × R MB/player ) × 8 / ( T window in seconds )
```

| Tier | Calculation (R=500 MB, T=4 h) | Average | To provision |
|------|-------------------------------|---------|--------------|
| < 200 | 200 × 500 / 14400 | ~55 Mbps | **100–200 Mbps** symmetric · business fibre link |
| 200–500 | 500 × 500 / 14400 | ~140 Mbps | **300–500 Mbps** *or CDN (→ ~100 Mbps origin)* |
| 500–1000 | 1000 × 500 / 14400 | ~280 Mbps | **CDN practically mandatory** · otherwise ~1 Gbps |
| 1000+ | CDN edge | — | Origin **independent** of the number of players · CDN absorbs the egress |

> **⚡ The lever that changes everything: the propagation window**
>
> - 1000 players × 500 MB in **4 h** → 500,000 MB × 8 / 14,400 s = **~280 Mbps** (manageable)
> - The same in **15 min** → 500,000 × 8 / 900 = **~4,440 Mbps** (≈ 4.4 Gbps!)
>
> → For scheduled content, keep wide windows (overnight). Reserve fast propagation for lightweight triggers (events, VOD) that are **already pre-cached**.

> **Pitfall: several screens per site**
>
> LAN sync handles **playback synchronisation**, **not** content sharing: 4 screens in the same store each pull their own copy from the server. A **CDN** or a **per-site cache** removes this redundancy — a major gain when there are many screens per location.

## 4. Storage — three layers

| Layer | Role |
|-------|------|
| 🗄️ **Object storage** | MinIO / S3: master + renditions + thumbnails. Scales with the **catalogue**, barely with the number of players. |
| 🐘 **Postgres database** | Metadata (small) + **partitioned logs** (proof-of-play, audience, audit). Scales with players **× time**. |
| 💾 **Player side** | Local cache of the content-set. **2–3×** the content-set (old + new during the swap) + OS. |

```
Object storage ≈ Nb assets × avg master size × renditions factor (~1.5)
DB / year      ≈ N players × plays/day × ~0.3 KB × retention days   (proof-of-play dominant)
Player disk    ≈ R × 2–3  + OS
```

| Tier | Object storage (media) | Postgres DB | Player side |
|------|------------------------|-------------|-------------|
| < 200 | Catalogue 0.3–1k assets → **30–150 GB**<br>*Provision 500 GB–1 TB NVMe, local MinIO OK* | ~50–100 GB<br>*PoP ~15 GB/year* | RPi 32–64 GB · mini-PC 128–256 GB<br>*⚠ Android box with 16–32 GB eMMC = limiting factor* |
| 200–500 | 0.2–1 TB → **1–2 TB**<br>*Start externalising (S3/GCS)* | ~100–200 GB<br>*PoP ~40 GB/year + retention* | same · 128–256 GB SSD |
| 500–1000 | 0.5–3 TB → **S3/GCS + lifecycle**<br>*No more local MinIO* | ~200–400 GB<br>*Managed PG + partition drop* | 256 GB for a 4K fleet |
| 1000+ | Multi-TB → tens of TB<br>*S3 + hot/cold tiering + CDN* | 0.5–1 TB+<br>*Replicas + Parquet archiving* | 256 GB+ · watch Android eMMC |

> **The real storage pitfall = Android boxes**
>
> The eMMC of a TV box (16–32 GB, soldered, not expandable) fills up long before the server does: a 4K content-set of 2–4 GB × 2–3 (atomic swap) does not fit on 16 GB. → For **4K**, prefer SSD mini-PCs, or boxes with microSD/USB. Priority-aware cache eviction is already in place on the player side.

## 5. Encoding — cores & GPU

Encoding (ffmpeg transcode on the `celery-media` worker) scales with **ingestion volume**, not with the number of players. It is a **separable** tier: you add encoding nodes that consume the same Celery/Redis queue, without touching the backend or the DB.

> **GPU vs software: an order of magnitude (measured)**
>
> Burst of 10 videos, one of them 2 GB, on an RTX 5050:
>
> - **Software** libx264/x265 → **CPU load ~370**, server brought to its knees
> - **GPU NVENC** → NVENC encoder at 100 %, **GPU compute 6 %, CPU load ~2**
>
> The NVENC ASIC encodes **outside the CPU cores** → with a GPU, the sizing factor becomes the **GPU**, not the cores.

### Budget per concurrent stream

| Mode | FHD H.264 | 4K HEVC |
|------|-----------|---------|
| **Software (x264/x265)** | ~4–6 cores/stream to stay > real time | 16+ cores/stream **and still slower than real time** → avoid |
| **GPU NVENC** | dozens of 1080p streams > real time / card | several simultaneous 4K HEVC streams / card |

*⚠ GPU limit: consumer GeForce cards cap concurrent NVENC sessions (~3 to 8 depending on the driver); pro/datacenter **T4 / L4 cards are uncapped** — which matters as soon as you encode a lot in parallel, continuously.*

### Recommendation by tier

| Tier | Recommended encoding | Cores to reserve |
|------|----------------------|------------------|
| < 200 | **1 NVENC GPU** (even consumer-grade) on the server | GPU: ~2 cores. *Without GPU: 8–12 dedicated cores, FHD only* |
| 200–500 | **1 GPU** (T4/L4 for 4K or sustained parallel work) | 2–4 cores · no more software 4K |
| 500–1000 | **Dedicated encoding node** with GPU (1× L4/T4) | 4–8 cores on the node (muxing/IO) |
| 1000+ | **Horizontal encoding pool** (N GPU nodes) | scale the pool according to the ingestion rate |

> **3 variables that drive the encoding tier**
>
> 1. Ingestion rate (GB uploaded / window) — the real driver
> 2. Number of renditions (**2–3 encodes per file**, not one)
> 3. Share of 4K HEVC (expensive) vs FHD H.264 (light)
>
> *The anti-overload safeguards (adaptive concurrency, `nice 19`, prefetch/acks_late, isolated media worker) already prevent a burst from bringing the server down.*

## 6. Server summary by tier

| Tier | Deployment | App / DB / storage | Encoding | Bandwidth |
|------|------------|--------------------|----------|-----------|
| < 200 | **On-prem, 1 server** or 1 cloud VM — everything co-located in Docker | 8 vCPU · 32 GB RAM · 0.5–1 TB NVMe | +1 NVENC GPU | 100–200 Mbps symmetric |
| 200–500 | Beefy on-prem **or** cloud · move object storage out | 16 vCPU · 64 GB RAM · 1–2 TB · DB separable | 1 GPU (T4/L4) | 300–500 Mbps **or CDN** |
| 500–1000 | **Cloud / hybrid** · CDN practically mandatory | App ×2 behind LB (8–16 vCPU) · managed PG 8 vCPU/32 GB · managed Redis · S3+CDN | Dedicated GPU node | Low origin (CDN) |
| 1000+ | **Cloud-native, horizontal scaling** · CDN mandatory | Multiple backends (sharded WS, Redis fan-out) · PG + replicas · Redis cluster · S3+tiering | GPU pool | CDN edge · origin ∝ catalogue |

*Beyond ~100k players, the `EventBus` is designed to move from Redis Streams to Kafka (the interface is already abstracted).*

## 7. Three complete costed scenarios

### Scenario A — Retail chain, 150 players, FHD

**Assumptions:** 150 screens · 500 MB content-set · catalogue of 600 FHD assets · weekly overnight refresh (50 new assets/week) · 4 h push.

- **BW**: 150 × 500 MB × 8 / 14,400 s = **~42 Mbps** avg → provision **100 Mbps**
- **Object storage**: 600 × 70 MB × 1.5 = **~63 GB** → provision **500 GB NVMe** (local MinIO)
- **DB**: 150 × 3000 × 0.3 KB × 90 d = ~12 GB PoP → **~40 GB** DB
- **Encoding**: 50 FHD assets/week → **1 consumer GPU** empties the queue in minutes (or 8 software cores)
- **Player**: 500 MB × 3 + OS ≈ 2 GB → RPi 32 GB or mini-PC, no problem

→ **1 on-prem server**: 8 vCPU, 32 GB RAM, 500 GB NVMe, 1 NVENC GPU, 100 Mbps link.

### Scenario B — Mixed network, 400 players

**Assumptions:** 400 screens · 700 MB content-set (FHD mix + some 4K) · catalogue of 1500 assets · twice-weekly refresh · 4 h push.

- **BW**: 400 × 700 MB × 8 / 14,400 s = **~155 Mbps** avg → **300–400 Mbps** or CDN
- **Object storage**: 1500 × 70 MB × 1.5 = **~158 GB** → provision **1 TB**, S3 advised
- **DB**: 400 × 3000 × 0.3 KB × 90 d = ~32 GB PoP → **~80 GB** DB
- **Encoding**: 4K mix → **1 T4/L4 GPU**, separate `celery-media` worker
- **Player**: 700 MB × 3 ≈ 2.1 GB → mini-PC 128 GB SSD

→ **Beefy server or cloud**: 16 vCPU, 64 GB RAM, 1 TB, T4/L4 GPU, 400 Mbps link + CDN recommended.

### Scenario C — Large 4K network, 1200 players

**Assumptions:** 1200 screens · 2 GB content-set (4K) · catalogue of 4000 assets (4K HEVC masters) · frequent refresh · 4 h push · CDN.

- **BW** without CDN: 1200 × 2000 MB × 8 / 14,400 s = **~1.3 Gbps** → **CDN mandatory** (the origin only fills the CDN)
- **Object storage**: 4000 × 180 MB × 1.5 = **~1.08 TB** → provision **2–3 TB S3** + lifecycle
- **DB**: 1200 × 3000 × 0.3 KB × 90 d = ~97 GB PoP → **~250 GB** DB, managed PG + replicas
- **Encoding**: large 4K HEVC → **pool of dedicated L4 GPU nodes**
- **Player**: 2 GB × 3 + OS ≈ 7 GB → **mini-PC 256 GB SSD** (no 16 GB eMMC box)

→ **Cloud-native**: backends ×N behind LB, managed PG + replicas, Redis cluster, S3 + tiering, **CDN**, L4 GPU pool for encoding.

## 8. Scaling levers (by cost-effectiveness)

1. **CDN in front of media** (CloudFront / Cloudflare / Bunny in front of S3/MinIO) — by far the biggest gain, removes ~90 % of origin egress. *To be wired up: the player uses S3v4 signed URLs, which are CDN-compatible but not yet connected to one.*
2. **Externalised object storage** (S3/GCS) instead of local MinIO.
3. **Retention + partition drops** (pg_partman, already partitioned) — bounds the DB. PoP is the only big grower.
4. **Managed Postgres** (heartbeats + partitioned tables scale well; delegate maintenance).
5. **Horizontal backends** (Redis fan-out per `player:{id}` channel already allows it).
6. **Separate GPU encoding pool**, scaled on the ingestion rate (independent of app/DB).
7. **Per-site cache / cold lifecycle / hash dedup** — additional gains in multi-tenant setups.

> **Three corrections not to forget**
>
> 1. Below 500 players, the server **must** have an NVENC GPU — otherwise reserve 8–12 cores *on top* just for encoding (and forget 4K).
> 2. From 500+, **physically separate** the GPU encoding node from the app/DB node.
> 3. In the cloud, use **media GPU instances (L4/T4)** for encoding, not large CPU instances.

---

**Vitrail — Infrastructure sizing guide.** The figures depend on your actual profile (catalogue size, ingestion rate, share of 4K, acceptable propagation window, number of screens per site). Recalculate with your own values using the formulas in sections 3 to 5. Indicative document — to be refined with a load test before any deployment of > 500 players.
