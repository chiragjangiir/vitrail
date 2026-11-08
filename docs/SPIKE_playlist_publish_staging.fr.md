# SPIKE — Playlist staging / bouton « Publier » (#1)

🇬🇧 [English version](SPIKE_playlist_publish_staging.md)

> Spike de design (2026-06-07). Retour terrain Ed : l'édition de playlist part à l'écran avant qu'il ait fini (chaque mutation d'item pousse un `force_sync` **préemptif immédiat**, `playlists.py::_push_sync_org`). **Décision Ed = staging robuste (snapshot publié)** : les players jouent une version PUBLIÉE ; les éditions restent invisibles jusqu'à « Publier ».
>
> **Verdict : GO, architecture 2 (live = publié + brouillon JSON)** — isole les brouillons SANS toucher au chemin de sync critique.

## 1. Problème
`add_playlist_item` / `reorder_playlist_items` / `remove_playlist_item` / `set_item_rules` appellent tous `_push_sync_org(db)` → `{"type":"player:force_sync"}` **sans `preemptive`** = application immédiate qui interrompt l'item en cours. Donc chaque sous-édition (et la création d'une Item Broadcast Rule avant qu'elle soit configurée) diffuse aussitôt.

**Le piège** : `_resolve_sync_payload` lit l'**état live de `cms_playlist_items`**. Un simple flag « ne pas pousser » n'isole rien — toute resync (reconnexion player, push org-wide d'un autre objet, périodique) tire l'état live à moitié édité.

## 2. Deux architectures

### Arch 1 — le snapshot EST la source servie aux players
- `cms_playlists.published_snapshot` JSONB = items servis ; `_resolve_sync_payload` lit le snapshot au lieu des items live ; édition = items live (brouillon) ; Publier = snapshot ← live.
- ⚠️ **Refonte du builder playlist dans `_resolve_sync_payload`** (chemin critique partagé gouvernance/events/renditions/offline-first) + backfill obligatoire. Risque élevé pour le mur en prod.

### Arch 2 — live = publié, brouillon = copie de travail JSON ✅ RECOMMANDÉE
- **`cms_playlist_items` reste = la version PUBLIÉE** (ce que voient les players) → **`_resolve_sync_payload` INCHANGÉ** (zéro risque sur le chemin critique).
- `cms_playlists.draft_items` JSONB (NULL = propre/pas de brouillon) = éditions en cours.
- Les endpoints d'édition écrivent le **brouillon** (initialisé depuis les items live au 1er edit), **sans push**.
- `POST /publish` : `cms_playlist_items` (+ rules) ← `draft_items`, efface le brouillon, **push `force_sync` graceful** (preemptive=false → bascule à la frontière d'item, plus d'interruption).
- `POST /discard` : efface le brouillon (revient au publié).
- L'éditeur lit le brouillon s'il existe, sinon les items live.

**Reco = Arch 2** : protège le mur (le chemin que gouvernance/events/renditions/offline-first empruntent reste byte-identique), même isolation fonctionnelle (« publié » = items live), réversible (discard). Le « snapshot publié » voulu par Ed = réalisé par les items live ; le brouillon est le delta.

## 3. Plan (Arch 2)
- **Migration** : `cms_playlists.draft_items JSONB NULL` + (dérivé) `has_draft_changes = draft_items IS NOT NULL`. Aucun backfill (NULL = propre).
- **Modèle brouillon** (JSON) : `[{id_media, sort_order, duration_ms, zone_index, transition_type, rules:[...]}]` (id_item temporaire côté front).
- **Endpoints édition** (add/reorder/remove/set_rules) : opèrent sur `draft_items` (init depuis live au 1er edit), **retirent `_push_sync_org`**, posent le brouillon.
- **`POST /publish`** : applique `draft_items` → `cms_playlist_items`+`cms_playlist_item_rules` (remplace), efface brouillon, `_push_sync_org` **graceful** (ajouter `preemptive=false` au payload). Déclenche aussi la **conformité #2** par item ajouté.
- **`POST /discard`** : efface `draft_items`.
- **`GET /playlists/{id}`** : `items` = brouillon si présent sinon live ; `has_draft_changes`, `published_at`.
- **Front** : bandeau « Modifications non publiées » + boutons **Publier** / **Annuler** ; l'éditeur travaille sur le brouillon ; i18n.
- **`_push_sync_org`** : ajouter `preemptive=false` (graceful) — vaut aussi pour les autres appelants ? (à vérifier : events/embargo veulent peut-être préemptif). → garder `_push_sync_org` préemptif par défaut, et un `_push_sync_org(db, preemptive=False)` pour Publier.

## 4. Points d'attention
- **Conformité #2** : aujourd'hui sur `add_playlist_item` (live). En Arch 2, déplacer le check au **Publish** (par item du brouillon) — l'advisory remonte alors à la publication.
- **Item rules / tags** : le brouillon doit porter les règles par item (et tags ?). Tags = `cms_playlist_item_tags` (séparé) — décider s'ils sont stagés aussi (sinon ils s'appliquent live). v1 : stager items+rules ; tags hors staging (rare en pleine édition).
- **Édition concurrente** : un seul brouillon par playlist (pas de multi-utilisateur sur le même brouillon — acceptable).
- **`sync_windowed`/`sync_ready`** recalculés à la publication.

## 5. Verdict
**GO Arch 2.** Effort moyen-élevé (migration + 4 endpoints réécrits sur le brouillon + 2 nouveaux + front), **risque maîtrisé** (chemin de sync intact). Itérable : v1 = items+rules stagés, tags/avancé en suivant.
