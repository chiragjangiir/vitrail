# API integration guide — Vitrail CMS

🇫🇷 [Version française](API_INTEGRATION.fr.md)

> For a third-party integrator/developer. This guide is the **entry point**: the exhaustive
> reference of all endpoints is the **auto-generated Swagger** of your instance:
> `https://votre-serveur/api/docs` (ReDoc: `/api/redoc`, raw schema: `/api/openapi.json`).
> The interactive documentation can be disabled by the operator (`CMS_DOCS_ENABLED=false`).

## 1. General conventions

- **Base URL**: `https://votre-serveur/api/v1` — the whole API lives under this prefix.
  Exception: the healthcheck is `GET /health` (outside `/api/v1`).
- **Auth**: `Authorization: Bearer <jeton>` header — user JWT or API key depending on the surface.
- **Trailing slash**: "collection" endpoints are declared with a trailing slash
  (e.g. `GET /api/v1/players/`). Without it, FastAPI responds **307 Redirect** — and behind a
  reverse proxy the redirect may point to an unusable internal URL. **Keep the trailing `/`.**
- **Errors**: standard FastAPI format `{"detail": "..."}` (`detail` may be an object,
  e.g. campaign import errors `{"detail": {"errors": [...]}}` or the BYOK spending-cap 402).
- **Multi-tenant**: every resource belongs to an organisation (PostgreSQL RLS).
  A resource from another organisation responds **404** (never 403) — the very existence
  of a foreign resource is not revealed.
- **Rate limiting**: global safeguard of **600 requests/min/IP** (configurable server-side,
  `429` beyond that). Login has its own anti-brute-force: **10 failures / 5 min** per IP and
  per account → `429`. These are anti-flood safety nets, not business quotas.
- **Pagination**: **no standardised pagination** across all lists. Most list endpoints return
  the organisation's complete array; a few accept `offset`/`limit`
  (e.g. `GET /media/?offset=0&limit=500`, max 2000). Check each endpoint in the Swagger.
- **Common codes**: `401` invalid or expired token/key · `403` permission denied (RBAC),
  demo account (`demo_blocked`), expired licence (`licence_readonly`) · `404` not found or
  outside the organisation · `409` licence quota (players) · `422` invalid body · `429` rate limit.

## 2. User authentication (JWT)

| Endpoint | Role |
|---|---|
| `POST /api/v1/auth/login` | email + password (+ TOTP) → access + refresh tokens |
| `POST /api/v1/auth/refresh` | refresh token → new access token |
| `POST /api/v1/auth/revoke` | revokes a refresh token (logout) |
| `POST /api/v1/auth/totp/setup` | generates TOTP secret + QR + 10 backup codes |
| `POST /api/v1/auth/totp/verify` | confirms the secret and enables 2FA |

```bash
curl -X POST https://votre-serveur/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@exemple.com", "password": "...", "totp_code": "123456"}'
# → {"access_token": "...", "refresh_token": "...", "token_type": "bearer", "locale": "fr"}

curl https://votre-serveur/api/v1/users/me \
  -H "Authorization: Bearer <access_token>"
```

- **Lifetimes** (configurable server-side): access token **15 min**, refresh token **7 days**.
  On a `401` on the access token, call `POST /auth/refresh` with the refresh token.
- **TOTP 2FA**: mandatory for `CMS_SUPER_ADMIN` and `CMS_ORG_ADMIN` (and depending on the
  organisation's policy). Pass `totp_code` (or `backup_code`) in the login body. A TOTP code is
  **single-use** within its window (anti-replay). If 2FA is required but not enrolled, login
  responds `403` with `{"force_2fa_setup": true, "enrolment_token": "..."}`:
  this token (10 min) opens ONLY `/auth/totp/setup` and `/auth/totp/verify`.
- Rights are carried by RBAC (`module:opération`) — a `403` lists the missing permission
  in `detail`.

**For a machine integration, prefer the API keys below**: they are revocable, scoped to a
single surface, and do not go through 2FA.

## 3. API keys — the 4 prefixes

All are stored hashed (SHA-256), the **plaintext value is returned only at creation**, and they
are passed as `Authorization: Bearer <clé>`. Each key opens ONLY its own surface (single scope).

| Prefix | Use | Creation (UI) | Management endpoints (org-admin) | Expiry |
|---|---|---|---|---|
| `sfr_` | BI CSV exports (§5) | Reports → Executive Dashboard → BI keys | `GET/POST /analytics/bi-keys`, `DELETE /analytics/bi-keys/{id}` | optional (`expires_in_days`, max 3650; otherwise permanent) |
| `sfi_` | Retail media campaign import | Campaigns → Import (JSON) → "API import keys" | `GET/POST /campaigns/import-keys`, `DELETE /campaigns/import-keys/{id}` | optional (same) |
| `sfk_` | Provisioning **operator** key (field installer) | Settings → Players → Provisioning → operator key | `GET/POST /orgs/{id_org}/provisioning-keys`, `POST .../{id}/revoke`, `DELETE .../{id}` | **mandatory** (default 90 d, max 730) |
| `sfp_` | **Player provisioning token** (machine use, consumed at registration) | Settings → Players → Provisioning (or generated in a payload) | `GET/POST /orgs/{id_org}/provisioning-tokens`, `POST .../{id}/revoke`, `DELETE .../{id}` | optional + `max_uses` |

- Revocation (`DELETE` on `sfr_`/`sfi_`, `POST .../revoke` on `sfk_`/`sfp_`) is
  immediate; `last_used_at` is kept up to date for auditing.
- `sfr_` specificity: also accepted **in the query string** `?api_key=sfr_...` (see §5).
- `sfp_` is not an API key strictly speaking: it is the limited-use token that the player
  exchanges for its machine JWT via `POST /players/register` (see §6).

## 4. BI exports (CSV) — `sfr_` keys

Three stable CSV feeds for Power BI / Tableau / Excel / Metabase. Column headers are
**English snake_case and contractual** (never renamed; new columns are appended at the end).

| Feed | Path | Content |
|---|---|---|
| Raw Proof of Play | `GET /api/v1/analytics/export/pop.csv` | one row per play (UTC timestamp, player, site, media, duration, signed, `screen_off`, `covered`) |
| Network metrics | `GET /api/v1/analytics/export/network-metrics.csv` | daily rollup (uptime, compliance, alerts, health score) — with a JWT, **org-admin only** |
| Content performance | `GET /api/v1/analytics/export/content.csv` | aggregate per media (plays, duration, player/site reach) |

**Parameters**: `?from=YYYY-MM-DD&until=YYYY-MM-DD` (default: last 30 days; max 366 days).

**Auth**: user JWT (`reports:read`, demo accounts refused) **or** `sfr_` key, as Bearer
or in the query string — web BI connectors do not always set a header:

```bash
curl "https://votre-serveur/api/v1/analytics/export/pop.csv?from=2026-07-01&until=2026-07-31" \
  -H "Authorization: Bearer sfr_XXXXXXXX"
# ou (Power BI « Web », Excel...) :
curl "https://votre-serveur/api/v1/analytics/export/pop.csv?api_key=sfr_XXXXXXXX"
```

(The second form is for Power BI "Web", Excel, etc.)

Notes: a JWT user scoped by governance §XVIII only sees their own perimeter in
`pop.csv` and `content.csv`; the `sfr_` key belongs to the organisation and is not restricted.
In `pop.csv`, rows with `screen_off=true` or `covered=true` are exported (raw proof feed) but
must be excluded from your airtime totals; `content.csv` already excludes them.

## 5. Campaign import (retail media) — `sfi_` keys

Two endpoints, same JSON body ("insertion order"):

- `POST /api/v1/campaigns/import/dry-run` — validates without creating anything (resolved targets, SOV occupancy)
- `POST /api/v1/campaigns/import` — creates the advertiser (if new) + a **draft** campaign +
  creatives downloaded in the background; publishing remains manual in the CMS.

Auth: JWT `campaigns:create` **or** `sfi_` key as Bearer. The full JSON format, the
field-by-field schema and the examples are in **`docs/FORMAT_IMPORT_CAMPAGNE.md`** — this
guide does not duplicate them.

## 6. Player provisioning — `sfk_` and `sfp_`

Surface used by the field installer (§XXIX). The `sfk_` operator key (or an org-admin JWT)
gives access only to:

| Endpoint | Role |
|---|---|
| `GET /api/v1/provisioning/whoami` | identifies the key's organisation |
| `POST /api/v1/orgs/{id_org}/provisioning-payload` | generates a **payload**: `sfp_` token + backend_url + network config/options (`id_player` = re-attach to an existing player) |
| `POST /api/v1/orgs/{id_org}/provisioning-batch` | batch: N payloads (`per_machine`) or 1 shared token `max_uses=N` (`shared`) |
| `GET /api/v1/provisioning/players/{id_player}/status` | polls for the player coming online after installation |

The device then consumes its `sfp_` token on the **public** endpoint:

```bash
curl -X POST https://votre-serveur/api/v1/players/register \
  -H "Content-Type: application/json" \
  -d '{"org_token": "sfp_XXXXXXXX", "player_name": "Vitrine-01",
       "player_os": "linux", "player_version": "1.5.26"}'
# → {"id_player": 42, "player_token": "<JWT player 60 j>", "expires_at": "..."}
```

The returned `player_token` is the player's machine JWT (valid 60 days, then renewed
automatically). Creating `sfk_` keys and `sfp_` tokens remains reserved to the org-admin JWT.

## 7. Outgoing webhooks (notifications §XXII)

The CMS **sends** webhooks (it does not receive any). Configuration: Settings → Notifications —
a **channel** (`channel_type: "webhook"`, config `{url, secret}`) + **rules** that link an
event type to a channel. Management via API (org-admin): `GET/POST/PUT/DELETE
/api/v1/notifications/channels[...]`, `/rules[...]`, `POST /channels/{id}/test`, `GET /log`,
`GET /event-types`.

**Events emitted**: `player_offline`, `player_storage_full`, `deployment_failed`,
`feed_error`, `campaign_started`, `campaign_ended`, `campaign_underserved`,
`approval_requested`, `approval_approved`, `approval_rejected`,
`approval_changes_requested`, `licence_expiring`.

**Payload** (JSON POST, `Content-Type: application/json`):

```json
{"event": "player_offline", "subject": "…", "body": "…",
 "context": {"player_name": "…", "...": "…"}, "source": "signflow"}
```

`context` carries the raw fields specific to the event; `subject`/`body` are ready-to-display
texts. Delivery: 1 synchronous attempt then 4 retries (~15 min, only on 5xx/408/429 or network
error — never on another 4xx). Log available via `GET /notifications/log`.

**HMAC signature** — each channel has a `whsec_...` secret (generated server-side, visible in the
channel config, rotated via `rotate_secret: true` on PUT). Headers sent:
`X-SignFlow-Signature` (`sha256=<hex>`), `X-SignFlow-Timestamp` (epoch), `X-SignFlow-Event`,
`X-SignFlow-Attempt`. The signature covers `"{timestamp}." + raw body`. Reference
verification:

```python
import hmac, hashlib, time

def signflow_webhook_is_authentic(secret, headers, raw_body, tolerance=300):
    ts  = headers.get("X-SignFlow-Timestamp", "")
    sig = headers.get("X-SignFlow-Signature", "")
    if not ts.isdigit() or abs(time.time() - int(ts)) > tolerance:
        return False                      # trop vieux (ou daté du futur) = rejeu
    expected = "sha256=" + hmac.new(
        secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)   # jamais `==`
```

(A timestamp that is too old, or dated in the future, is treated as a replay; never compare with
`==`.)

⚠️ Sign the **raw body as received** (never the re-serialised JSON) and compare with
`compare_digest`. Channels created before the signature was introduced may have no secret:
they then receive the POST **without** signature headers (a secret is assigned to them on their
first modification).

## 8. What does not exist yet

- **Public "PaaS §6.3" API** (OAuth M2M client_credentials, per-app configurable HMAC webhooks,
  Developer Portal): **not delivered** — planned for Phase 4. The `sfr_`/`sfi_`/`sfk_` keys
  above are the only machine surfaces available.
- **Incoming webhooks**: no endpoint accepts external pushes (feeds are pulled by the server).
- **Standardised pagination**: no common envelope (`total`, `next`...); `offset`/`limit`
  only where the Swagger shows them.
- **API versioning**: a single `/api/v1`, no version header and no published API changelog —
  the BI export CSV columns are the only explicit stability contract.
