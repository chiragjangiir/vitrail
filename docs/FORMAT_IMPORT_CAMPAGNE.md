# Format d'import de campagne (ordre d'insertion annonceur) — S6 Retail Media

> Un annonceur (ou une agence) fournit un **fichier JSON** décrivant sa campagne ; le
> scheduler l'importe dans SignFlow depuis `/campaigns` → **Importer**. L'import passe
> TOUJOURS par un **dry-run** (aperçu + projection d'occupation SOV) avant création.
> La campagne est créée en **draft** ; les créatifs pointés par URL sont téléchargés en
> tâche de fond puis passent le pipeline média normal (transcode, renditions,
> vignettes). La **publication reste manuelle** (l'enforcement surbooking s'applique).

## Endpoints

| Méthode | Route | Auth | Rôle |
|---|---|---|---|
| `POST /api/v1/campaigns/import/dry-run` | JWT `campaigns:create` **ou clé `sfi_`** | Valide l'ordre sans rien créer (annonceur matché/nouveau, cibles résolues par nom, créatifs, occupation) |
| `POST /api/v1/campaigns/import` | JWT `campaigns:create` **ou clé `sfi_`** | Crée annonceur (si nouveau) + campagne draft + créatifs (download async) |

## Import PAR API (v2 — 2026-07-12) : clés machine `sfi_`

Une agence/un annonceur pousse ses ordres d'insertion **sans compte humain** :

1. Org-admin : `/campaigns` → **Importer (JSON)** → section « Clés d'import par API »
   → créer une clé (`sfi_…`, affichée UNE seule fois ; révocable ; scope
   `campaigns:import` — la clé ne donne accès à RIEN d'autre).
2. Le client appelle les deux endpoints ci-dessus avec la clé en Bearer :

```bash
curl -X POST https://cms.example.com/api/v1/campaigns/import/dry-run \
  -H "Authorization: Bearer sfi_XXXXXXXX" \
  -H "Content-Type: application/json" \
  -d @ordre_insertion.json
# puis, si "ok": true :
curl -X POST .../api/v1/campaigns/import -H "Authorization: Bearer sfi_XXXXXXXX" \
  -H "Content-Type: application/json" -d @ordre_insertion.json
```

La campagne arrive en **draft** dans `/campaigns` (workflow normal ensuite : revue,
approbation §21 le cas échéant, publish manuel avec enforcement surbooking).
⚠️ Garde-fou durée : un créatif au-dessus de la limite org (défaut 30 s) sera
refusé au publish — les vidéos par URL n'ont leur durée qu'après téléchargement.

## Schéma

```json
{
  "version": 1,
  "advertiser": {
    "name": "Dyson",                       // matché sur l'existant (insensible casse) ou créé
    "contact_name": "Jane Buyer",          // optionnel (utilisé seulement à la création)
    "contact_email": "buy@dyson.com"       // optionnel
  },
  "campaign": {
    "name": "Dyson V12 Été 2026",
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

## Règles & gardes

- **Cibles** : chaque nom doit correspondre à EXACTEMENT une entité de l'org (sinon
  erreur `introuvable` / `ambigu` au dry-run). Types acceptés : `org`, `site`,
  `site_group` (groupes de sites S6), `group` (groupes de players), `player`.
- **Créatifs** : vidéo (`mp4 mov mkv webm avi m4v mpg mpeg ts m2ts wmv`) ou image
  (`jpg jpeg png webp gif bmp`) — déduits de l'extension de l'URL. Une **image exige
  `duration_ms`**. `weight` = rotation pondérée (défaut 1). Max 20 créatifs, 512 MiB
  par fichier.
- **Anti-SSRF** : URL http(s) publiques uniquement (IP privées/loopback/metadata
  bloquées, redirections NON suivies) — vérifié au dry-run ET re-vérifié par le worker.
- **Occupation** : le dry-run projette l'occupation SOV sur les players ciblés
  (warning ≥ 80 %, blocage > 100 %) — l'import reste possible (campagne draft), c'est
  le **publish** qui refuse le surbooking (sauf `overbook_override` org-admin).
- **Approbation des créatifs** : si le flag org est actif (S5), les créatifs importés
  naissent `pending` (revue requise avant diffusion).
- **Médiathèque** : les créatifs téléchargés sont rangés dans le dossier
  `Annonceurs/<nom>` de l'annonceur.
- Un download qui échoue → média `transcode_status='error'` + raison dans
  `metadata.download_error` (visible médiathèque) ; ré-importer ou remplacer le média.
