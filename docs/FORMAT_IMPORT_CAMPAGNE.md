# Campaign import format (advertiser insertion order) — S6 Retail Media

🇫🇷 [Version française](FORMAT_IMPORT_CAMPAGNE.fr.md)

> An advertiser (or an agency) provides a **JSON file** describing its campaign; the
> scheduler imports it into Vitrail from `/campaigns` → **Import**. The import ALWAYS goes
> through a **dry-run** (preview + SOV occupancy projection) before creation.
> The campaign is created as a **draft**; creatives referenced by URL are downloaded in the
> background and then go through the normal media pipeline (transcode, renditions,
> thumbnails). **Publishing remains manual** (overbooking enforcement applies).

## Endpoints

| Method | Route | Auth | Role |
|---|---|---|---|
| `POST /api/v1/campaigns/import/dry-run` | JWT `campaigns:create` **or `sfi_` key** | Validates the order without creating anything (advertiser matched/new, targets resolved by name, creatives, occupancy) |
| `POST /api/v1/campaigns/import` | JWT `campaigns:create` **or `sfi_` key** | Creates the advertiser (if new) + draft campaign + creatives (async download) |

## Import VIA API (v2): `sfi_` machine keys

An agency/advertiser pushes its insertion orders **without a human account**:

1. Org-admin: `/campaigns` → **Import (JSON)** → "API import keys" section
   → create a key (`sfi_…`, shown ONLY once; revocable; scope
   `campaigns:import` — the key gives access to NOTHING else).
2. The client calls the two endpoints above with the key as Bearer:

```bash
curl -X POST https://cms.example.com/api/v1/campaigns/import/dry-run \
  -H "Authorization: Bearer sfi_XXXXXXXX" \
  -H "Content-Type: application/json" \
  -d @ordre_insertion.json
# puis, si "ok": true :
curl -X POST .../api/v1/campaigns/import -H "Authorization: Bearer sfi_XXXXXXXX" \
  -H "Content-Type: application/json" -d @ordre_insertion.json
```

(Run the second call only if the dry-run returns `"ok": true`.)

The campaign arrives as a **draft** in `/campaigns` (normal workflow afterwards: review,
approval §21 where applicable, manual publish with overbooking enforcement).
⚠️ Duration safeguard: a creative above the org limit (default 30 s) will be
refused at publish — videos given by URL only have a known duration after download.

## Schema

```json
{
  "version": 1,
  "advertiser": {
    "name": "Brightwell",                       // matché sur l'existant (insensible casse) ou créé
    "contact_name": "Jane Buyer",          // optionnel (utilisé seulement à la création)
    "contact_email": "buy@dyson.com"       // optionnel
  },
  "campaign": {
    "name": "Brightwell V12 Été 2026",
    "starts_on": "2026-08-01",             // dates ISO (YYYY-MM-DD)
    "ends_on": "2026-08-31",
    "daily_hours": {"start": "09:00", "end": "20:00"},   // optionnel — fenêtre quotidienne
    "sov_percent": 15,                     // part de voix vendue (0 < x ≤ 100)
    "pricing_model": "sov",                // sov | flat | cpm
    "price_amount": 2500,                  // optionnel
    "price_currency": "EUR",
    "cpm_rate": null,                      // optionnel (CPM indicatif)
    "priority": 50
  },
  "targets": [                             // ≥ 1 — cibles par NOM, résolues à l'import
    {"type": "site_group", "name": "Sud-Ouest"},
    {"type": "site", "name": "Store Bordeaux"},
    {"type": "group", "name": "Vitrines"},
    {"type": "player", "name": "Écran entrée"},
    {"type": "org"}                        // toute l'organisation (name ignoré)
  ],
  "creatives": [                           // 1 à 20 — URL publiques https (http accepté)
    {"url": "https://cdn.dyson.com/spots/v12-15s.mp4", "weight": 2},
    {"url": "https://cdn.dyson.com/spots/v12-visuel.jpg", "duration_ms": 10000, "weight": 1,
     "name": "Visuel V12"}                 // nom d'affichage optionnel (défaut : fichier de l'URL)
  ]
}
```

Field notes (the comments in the schema above):

- `advertiser.name`: matched against existing advertisers (case-insensitive) or created;
  `contact_name` and `contact_email` are optional (used only at creation).
- `starts_on` / `ends_on`: ISO dates (YYYY-MM-DD); `daily_hours`: optional daily window.
- `sov_percent`: share of voice sold (0 < x ≤ 100); `pricing_model`: `sov` | `flat` | `cpm`;
  `price_amount` optional; `cpm_rate` optional (indicative CPM).
- `targets`: ≥ 1 — targets by NAME, resolved at import; `{"type": "org"}` = the whole
  organisation (`name` ignored).
- `creatives`: 1 to 20 — public https URLs (http accepted); `name` is an optional display name
  (default: the file name from the URL).

## Rules & safeguards

- **Targets**: each name must match EXACTLY one entity of the org (otherwise a
  `introuvable` (not found) / `ambigu` (ambiguous) error at dry-run). Accepted types: `org`,
  `site`, `site_group` (S6 site groups), `group` (player groups), `player`.
- **Creatives**: video (`mp4 mov mkv webm avi m4v mpg mpeg ts m2ts wmv`) or image
  (`jpg jpeg png webp gif bmp`) — inferred from the URL's extension. An **image requires
  `duration_ms`**. `weight` = weighted rotation (default 1). Max 20 creatives, 512 MiB
  per file.
- **Anti-SSRF**: public http(s) URLs only (private/loopback/metadata IPs
  blocked, redirects NOT followed) — checked at dry-run AND re-checked by the worker.
- **Occupancy**: the dry-run projects SOV occupancy on the targeted players
  (warning ≥ 80 %, blocking > 100 %) — the import is still possible (draft campaign); it is
  the **publish** that refuses overbooking (except with org-admin `overbook_override`).
- **Creative approval**: if the org flag is active (S5), imported creatives
  are born `pending` (review required before playout).
- **Media library**: downloaded creatives are stored in the advertiser's
  `Annonceurs/<nom>` folder.
- A failed download → media `transcode_status='error'` + reason in
  `metadata.download_error` (visible in the media library); re-import or replace the media.
