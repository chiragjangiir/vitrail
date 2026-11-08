# SPIKE — URL Display (Sprint 2.8, §XXV.2)

> Décision d'architecture + plan d'implémentation. Établi 2026-06 avec Ed.
> Périmètre validé : **webview d'abord** (pas de pod Playwright), intégration **plein écran
> schedulable ET zone de template**, **offline-first + sonde d'accès + repli/alerte** inclus.

## Décision d'architecture : `url_display` = un MÉDIA (réutilise `cms_media`)

Plutôt que la table dédiée `cms_url_display_configs` de la spec + un `id_url_display` nullable
sur les items (qui imposerait de câbler le « média OU url » dans playlists/events/draft/sync/
pickers UI), on modélise un site web comme **un média natif** :

- `cms_media` row : `media_type = 'url_display'`, `storage_key = NULL` (pas de fichier),
  l'URL + la config webview vivent dans `metadata` JSONB.
- **Réutilisation maximale** : il apparaît dans la médiathèque, les pickers de playlist/event,
  le scheduling, le targeting, la sync — **sans toucher** à ces machineries (un item référence
  toujours `id_media`). C'est exactement le « comme un média » demandé, et la spec §25.1 le
  présente déjà comme « un type de contenu natif complémentaire aux types existants ».
- RBAC : réutilise le module **`media`** (create/read/edit/delete) → pas de nouveau module.
- **Pas de migration** pour la Phase 1 (`media_type` = `String(30)` libre ; aucune perm neuve).

Coût = des **gardes défensives** « si `media_type == 'url_display'` : pas de fichier » sur les
chemins qui supposent un objet MinIO (transcode, conformité, renditions, replace, delete-files,
taille servie, prefetch/offline-first, barrière LAN visuelle). Toutes triviales et localisées.

`metadata` d'un url_display :
```json
{
  "url": "https://example.com/dashboard",
  "render_mode": "webview",
  "refresh_interval_s": 0,
  "zoom": 1.0,
  "scroll_mode": "none",
  "scroll_speed_px_s": 50,
  "interaction_blocked": true,
  "custom_css": "",
  "hide_selectors": [],
  "reachability": { "enabled": true, "timeout_s": 8 }
}
```

> `screenshot_server` (itération suivante) : on ajoutera les champs de capture
> (`screenshot_s3`, `last_capture_at`, `last_error`, `status`) dans `metadata` (ou une table
> side `cms_url_display_captures` si ça grossit) + le service Playwright + queue `cms_screenshot`.

## Offline-first + sonde d'accès (exigence Ed)

- **Offline-first** : la config voyage dans l'état de sync **persisté** côté player → serveur
  coupé, le player **continue d'afficher le site** (s'il y a accès). Rien à cacher (pas de fichier).
- **Sonde d'accès** (player, webview) : avant affichage + à chaque refresh, test d'accès à l'URL
  (`fetch` HEAD/no-cors borné par `timeout_s`). **Inaccessible → on saute l'item** (`onError` →
  item suivant de la playlist) **+ alerte** `url_display_unreachable` au serveur.
- **Alerte** (v1, §XXII Notifications pas encore bâti) : message WS entrant
  `{type:'player:event', event:'url_display_unreachable', id_media, url}` → `cms_audit_log`
  (file côté player si serveur down, vidée à la reconnexion). Évolution = vraies notifications 2.11.

## Plan d'implémentation

### Phase 1 — plein écran schedulable (webview)
1. **Backend** `endpoints/url_display.py` : `GET/POST/PUT/DELETE /url-display` (perms `media:*`),
   crée/édite un `cms_media` type `url_display` (validation URL https, métadonnées). Router enregistré.
2. **Gardes** : transcode/conformité/renditions/replace/delete-files/served_size/prefetch/LAN-barrier
   skip `url_display` (pas de fichier).
3. **Sync** `ws.py` : dans les builders d'items, branche `url_display` → émet
   `{media_type:'url_display', url: metadata.url, url_config: metadata}` sans `get_signed_url`/cache_key.
4. **Alerte entrante** `ws.py` : handler `player:event url_display_unreachable` → audit log.
5. **Renderers (5)** : rendu iframe sandboxé (étend le chemin `html_package`) + refresh + scroll +
   `interaction_blocked` + **sonde d'accès → skip + alerte WS**.
6. **Frontend** : page `/url-display` (liste + drawer : nom, url, mode, refresh, scroll, zoom,
   sandbox, timeout sonde) ; le média url_display apparaît dans les pickers existants. Nav + i18n.
7. **Tests** : création url_display ; sync émet l'item avec l'URL live (sans URL signée) ; garde
   transcode ; handler d'alerte écrit l'audit.

### Phase 2 — zone dans l'éditeur de templates (WYSIWYG)
Permettre à une **zone** de template d'héberger un média `url_display`. Touche l'éditeur de
templates (§2.3) + le rendu multi-zones du player. Fait **après** validation de la Phase 1.
