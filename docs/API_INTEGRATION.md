# Guide d'intégration API — SignFlow CMS

> Pour un intégrateur/développeur tiers. Ce guide est le **chemin d'entrée** : la référence
> exhaustive de tous les endpoints est le **Swagger auto-généré** de votre instance :
> `https://votre-serveur/api/docs` (ReDoc : `/api/redoc`, schéma brut : `/api/openapi.json`).
> La doc interactive peut être coupée par l'exploitant (`CMS_DOCS_ENABLED=false`).

## 1. Conventions générales

- **Base URL** : `https://votre-serveur/api/v1` — toute l'API vit sous ce préfixe.
  Exception : le healthcheck est `GET /health` (hors `/api/v1`).
- **Auth** : en-tête `Authorization: Bearer <jeton>` — JWT utilisateur ou clé API selon la surface.
- **Trailing slash** : les endpoints « collection » sont déclarés avec un slash final
  (ex. `GET /api/v1/players/`). Sans lui, FastAPI répond **307 Redirect** — et derrière un
  reverse-proxy la redirection peut pointer vers une URL interne inutilisable. **Gardez le `/` final.**
- **Erreurs** : format FastAPI standard `{"detail": "..."}` (le `detail` peut être un objet,
  ex. les erreurs d'import de campagne `{"detail": {"errors": [...]}}` ou le 402 plafond BYOK).
- **Multi-tenant** : chaque ressource appartient à une organisation (RLS PostgreSQL).
  Une ressource d'une autre organisation répond **404** (jamais 403) — l'existence même
  d'une ressource étrangère n'est pas révélée.
- **Rate limiting** : garde-fou global **600 requêtes/min/IP** (configurable côté serveur,
  `429` au-delà). Le login a son propre anti-brute-force : **10 échecs / 5 min** par IP et
  par compte → `429`. Ce sont des filets anti-flood, pas des quotas métier.
- **Pagination** : **pas de pagination standardisée** sur toutes les listes. La plupart des
  endpoints de liste renvoient le tableau complet de l'organisation ; quelques-uns acceptent
  `offset`/`limit` (ex. `GET /media/?offset=0&limit=500`, max 2000). Vérifiez chaque endpoint
  dans le Swagger.
- **Codes usuels** : `401` jeton/clé invalide ou expiré · `403` permission refusée (RBAC),
  compte démo (`demo_blocked`), licence expirée (`licence_readonly`) · `404` introuvable ou
  hors organisation · `409` quota licence (players) · `422` corps invalide · `429` rate limit.

## 2. Authentification utilisateur (JWT)

| Endpoint | Rôle |
|---|---|
| `POST /api/v1/auth/login` | email + mot de passe (+ TOTP) → access + refresh tokens |
| `POST /api/v1/auth/refresh` | refresh token → nouvel access token |
| `POST /api/v1/auth/revoke` | révoque un refresh token (logout) |
| `POST /api/v1/auth/totp/setup` | génère secret TOTP + QR + 10 codes de secours |
| `POST /api/v1/auth/totp/verify` | confirme le secret et active le 2FA |

```bash
curl -X POST https://votre-serveur/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@exemple.com", "password": "...", "totp_code": "123456"}'
# → {"access_token": "...", "refresh_token": "...", "token_type": "bearer", "locale": "fr"}

curl https://votre-serveur/api/v1/users/me \
  -H "Authorization: Bearer <access_token>"
```

- **Durées** (configurables serveur) : access token **15 min**, refresh token **7 jours**.
  Au `401` sur l'access token, appelez `POST /auth/refresh` avec le refresh token.
- **2FA TOTP** : obligatoire pour `CMS_SUPER_ADMIN` et `CMS_ORG_ADMIN` (et selon la politique
  de l'organisation). Passez `totp_code` (ou `backup_code`) dans le corps du login. Un code
  TOTP est **à usage unique** dans sa fenêtre (anti-rejeu). Si le 2FA est requis mais non
  enrôlé, le login répond `403` avec `{"force_2fa_setup": true, "enrolment_token": "..."}` :
  ce jeton (10 min) n'ouvre QUE `/auth/totp/setup` et `/auth/totp/verify`.
- Les droits sont portés par le RBAC (`module:opération`) — un `403` liste la permission
  manquante dans `detail`.

**Pour une intégration machine, préférez les clés API ci-dessous** : elles sont révocables,
scopées à une seule surface, et ne passent pas par le 2FA.

## 3. Clés API — les 4 préfixes

Toutes sont stockées hachées (SHA-256), la **valeur en clair n'est renvoyée qu'à la création**,
et se passent en `Authorization: Bearer <clé>`. Chaque clé n'ouvre QUE sa surface (scope unique).

| Préfixe | Usage | Création (UI) | Endpoints de gestion (org-admin) | Expiration |
|---|---|---|---|---|
| `sfr_` | Exports BI CSV (§5) | Rapports → Executive Dashboard → clés BI | `GET/POST /analytics/bi-keys`, `DELETE /analytics/bi-keys/{id}` | optionnelle (`expires_in_days`, max 3650 ; sinon permanente) |
| `sfi_` | Import de campagnes retail media | Campagnes → Importer (JSON) → « Clés d'import par API » | `GET/POST /campaigns/import-keys`, `DELETE /campaigns/import-keys/{id}` | optionnelle (idem) |
| `sfk_` | Clé **opérateur** de provisioning (installeur terrain) | Réglages → Players → Provisioning → clé opérateur | `GET/POST /orgs/{id_org}/provisioning-keys`, `POST .../{id}/revoke`, `DELETE .../{id}` | **obligatoire** (défaut 90 j, max 730) |
| `sfp_` | **Token de provisioning player** (usage machine, consommé à l'enregistrement) | Réglages → Players → Provisioning (ou généré dans un payload) | `GET/POST /orgs/{id_org}/provisioning-tokens`, `POST .../{id}/revoke`, `DELETE .../{id}` | optionnelle + `max_uses` |

- La révocation (`DELETE` sur `sfr_`/`sfi_`, `POST .../revoke` sur `sfk_`/`sfp_`) est
  immédiate ; `last_used_at` est tenu à jour pour l'audit.
- Particularité `sfr_` : acceptée **aussi en query** `?api_key=sfr_...` (voir §5).
- `sfp_` n'est pas une clé d'API à proprement parler : c'est le jeton à usage limité que le
  player échange contre son JWT machine via `POST /players/register` (voir §6).

## 4. Exports BI (CSV) — clés `sfr_`

Trois flux CSV stables pour Power BI / Tableau / Excel / Metabase. En-têtes de colonnes
**snake_case anglais, contractuels** (jamais renommés ; les colonnes nouvelles s'ajoutent en fin).

| Flux | Chemin | Contenu |
|---|---|---|
| Proof of Play brut | `GET /api/v1/analytics/export/pop.csv` | une ligne par diffusion (horodatage UTC, player, site, média, durée, signé, `screen_off`, `covered`) |
| Métriques réseau | `GET /api/v1/analytics/export/network-metrics.csv` | rollup quotidien (uptime, conformité, alertes, health score) — côté JWT, **réservé org-admin** |
| Performance contenu | `GET /api/v1/analytics/export/content.csv` | agrégat par média (diffusions, durée, portée players/sites) |

**Paramètres** : `?from=YYYY-MM-DD&until=YYYY-MM-DD` (défaut : 30 derniers jours ; max 366 jours).

**Auth** : JWT utilisateur (`reports:read`, comptes démo refusés) **ou** clé `sfr_`, en Bearer
ou en query — les connecteurs BI web ne posent pas toujours d'en-tête :

```bash
curl "https://votre-serveur/api/v1/analytics/export/pop.csv?from=2026-07-01&until=2026-07-31" \
  -H "Authorization: Bearer sfr_XXXXXXXX"
# ou (Power BI « Web », Excel...) :
curl "https://votre-serveur/api/v1/analytics/export/pop.csv?api_key=sfr_XXXXXXXX"
```

Notes : un utilisateur JWT scopé par la gouvernance §XVIII ne voit que son périmètre dans
`pop.csv` et `content.csv` ; la clé `sfr_` appartient à l'organisation et n'est pas restreinte.
Dans `pop.csv`, les lignes `screen_off=true` ou `covered=true` sont exportées (flux de preuves
brutes) mais doivent être exclues de vos totaux d'antenne ; `content.csv` les exclut déjà.

## 5. Import de campagnes (retail media) — clés `sfi_`

Deux endpoints, mêmes corps JSON (« ordre d'insertion ») :

- `POST /api/v1/campaigns/import/dry-run` — valide sans rien créer (cibles résolues, occupation SOV)
- `POST /api/v1/campaigns/import` — crée annonceur (si nouveau) + campagne **draft** + créatifs
  téléchargés en tâche de fond ; la publication reste manuelle dans le CMS.

Auth : JWT `campaigns:create` **ou** clé `sfi_` en Bearer. Le format complet du JSON, le
schéma champ par champ et les exemples sont dans **`docs/FORMAT_IMPORT_CAMPAGNE.md`** — ce
guide ne les duplique pas.

## 6. Provisioning des players — `sfk_` et `sfp_`

Surface utilisée par l'installeur terrain (§XXIX). La clé opérateur `sfk_` (ou un JWT
org-admin) donne accès uniquement à :

| Endpoint | Rôle |
|---|---|
| `GET /api/v1/provisioning/whoami` | identifie l'organisation de la clé |
| `POST /api/v1/orgs/{id_org}/provisioning-payload` | génère un **payload** : token `sfp_` + backend_url + config réseau/options (`id_player` = ré-attache à un player existant) |
| `POST /api/v1/orgs/{id_org}/provisioning-batch` | lot : N payloads (`per_machine`) ou 1 token partagé `max_uses=N` (`shared`) |
| `GET /api/v1/provisioning/players/{id_player}/status` | poll du passage online après la pose |

Le device consomme ensuite son token `sfp_` sur l'endpoint **public** :

```bash
curl -X POST https://votre-serveur/api/v1/players/register \
  -H "Content-Type: application/json" \
  -d '{"org_token": "sfp_XXXXXXXX", "player_name": "Vitrine-01",
       "player_os": "linux", "player_version": "1.5.26"}'
# → {"id_player": 42, "player_token": "<JWT player 60 j>", "expires_at": "..."}
```

Le `player_token` retourné est le JWT machine du player (renouvelé automatiquement ensuite).
La création des clés `sfk_` et des tokens `sfp_` reste réservée au JWT org-admin.

## 7. Webhooks sortants (notifications §XXII)

Le CMS **émet** des webhooks (il n'en reçoit pas). Configuration : Réglages → Notifications —
un **canal** (`channel_type: "webhook"`, config `{url, secret}`) + des **règles** qui lient un
type d'événement à un canal. Gestion par API (org-admin) : `GET/POST/PUT/DELETE
/api/v1/notifications/channels[...]`, `/rules[...]`, `POST /channels/{id}/test`, `GET /log`,
`GET /event-types`.

**Événements émis** : `player_offline`, `player_storage_full`, `deployment_failed`,
`feed_error`, `campaign_started`, `campaign_ended`, `campaign_underserved`,
`approval_requested`, `approval_approved`, `approval_rejected`,
`approval_changes_requested`, `licence_expiring`.

**Payload** (POST JSON, `Content-Type: application/json`) :

```json
{"event": "player_offline", "subject": "…", "body": "…",
 "context": {"player_name": "…", "...": "…"}, "source": "signflow"}
```

`context` porte les champs bruts propres à l'événement ; `subject`/`body` sont des textes prêts
à afficher. Livraison : 1 essai synchrone puis 4 réessais (~15 min, uniquement sur 5xx/408/429
ou erreur réseau — jamais sur un autre 4xx). Journal consultable via `GET /notifications/log`.

**Signature HMAC** — chaque canal a un secret `whsec_...` (généré côté serveur, visible dans la
config du canal, rotation via `rotate_secret: true` au PUT). En-têtes envoyés :
`X-SignFlow-Signature` (`sha256=<hex>`), `X-SignFlow-Timestamp` (epoch), `X-SignFlow-Event`,
`X-SignFlow-Attempt`. La signature couvre `"{timestamp}." + corps brut`. Vérification de
référence :

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

⚠️ Signez le corps **brut reçu** (jamais le JSON re-sérialisé) et comparez avec
`compare_digest`. Les canaux créés avant l'introduction de la signature peuvent ne pas avoir
de secret : ils reçoivent alors le POST **sans** en-têtes de signature (un secret leur est
attribué à leur première modification).

## 8. Ce qui n'existe pas encore

- **API publique « PaaS §6.3 »** (OAuth M2M client_credentials, webhooks HMAC configurables
  par app, Developer Portal) : **non livrée** — prévue Phase 4. Les clés `sfr_`/`sfi_`/`sfk_`
  ci-dessus sont les seules surfaces machine disponibles.
- **Webhooks entrants** : aucun endpoint n'accepte de push externe (les feeds sont tirés par
  le serveur).
- **Pagination standardisée** : pas d'enveloppe commune (`total`, `next`...) ; `offset`/`limit`
  seulement là où le Swagger les montre.
- **Versionnement d'API** : `/api/v1` unique, pas de header de version ni de changelog d'API
  publié — les colonnes CSV des exports BI sont le seul contrat de stabilité explicite.
