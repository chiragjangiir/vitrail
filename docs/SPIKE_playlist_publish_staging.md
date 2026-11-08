# SPIKE — Playlist staging / "Publish" button (#1)

🇫🇷 [Version française](SPIKE_playlist_publish_staging.fr.md)

> Design spike (2026-06-07). Field feedback: playlist edits reach the screen before the editor has finished (every item mutation pushes an **immediate preemptive** `force_sync`, `playlists.py::_push_sync_org`). **Decision = robust staging (published snapshot)**: players play a PUBLISHED version; edits stay invisible until "Publish".
>
> **Verdict: GO, architecture 2 (live = published + JSON draft)** — isolates drafts WITHOUT touching the critical sync path.

## 1. Problem
`add_playlist_item` / `reorder_playlist_items` / `remove_playlist_item` / `set_item_rules` all call `_push_sync_org(db)` → `{"type":"player:force_sync"}` **without `preemptive`** = immediate application that interrupts the current item. So every sub-edit (including the creation of an Item Broadcast Rule before it is configured) goes on air immediately.

**The trap**: `_resolve_sync_payload` reads the **live state of `cms_playlist_items`**. A simple "don't push" flag isolates nothing — any resync (player reconnection, org-wide push of another object, periodic) pulls the half-edited live state.

## 2. Two architectures

### Arch 1 — the snapshot IS the source served to players
- `cms_playlists.published_snapshot` JSONB = served items; `_resolve_sync_payload` reads the snapshot instead of the live items; editing = live items (draft); Publish = snapshot ← live.
- ⚠️ **Rework of the playlist builder in `_resolve_sync_payload`** (critical path shared by governance/events/renditions/offline-first) + mandatory backfill. High risk for the wall in production.

### Arch 2 — live = published, draft = JSON working copy ✅ RECOMMENDED
- **`cms_playlist_items` stays = the PUBLISHED version** (what players see) → **`_resolve_sync_payload` UNCHANGED** (zero risk on the critical path).
- `cms_playlists.draft_items` JSONB (NULL = clean/no draft) = edits in progress.
- Edit endpoints write the **draft** (initialized from the live items on the 1st edit), **without push**.
- `POST /publish`: `cms_playlist_items` (+ rules) ← `draft_items`, clears the draft, **graceful `force_sync` push** (preemptive=false → switch at the item boundary, no more interruption).
- `POST /discard`: clears the draft (back to published).
- The editor reads the draft if it exists, otherwise the live items.

**Rec = Arch 2**: protects the wall (the path used by governance/events/renditions/offline-first stays byte-identical), same functional isolation ("published" = live items), reversible (discard). The desired "published snapshot" = realized by the live items; the draft is the delta.

## 3. Plan (Arch 2)
- **Migration**: `cms_playlists.draft_items JSONB NULL` + (derived) `has_draft_changes = draft_items IS NOT NULL`. No backfill (NULL = clean).
- **Draft model** (JSON): `[{id_media, sort_order, duration_ms, zone_index, transition_type, rules:[...]}]` (temporary id_item on the front end).
- **Edit endpoints** (add/reorder/remove/set_rules): operate on `draft_items` (init from live on the 1st edit), **remove `_push_sync_org`**, set the draft.
- **`POST /publish`**: applies `draft_items` → `cms_playlist_items`+`cms_playlist_item_rules` (replace), clears the draft, **graceful** `_push_sync_org` (add `preemptive=false` to the payload). Also triggers **conformance #2** per added item.
- **`POST /discard`**: clears `draft_items`.
- **`GET /playlists/{id}`**: `items` = draft if present otherwise live; `has_draft_changes`, `published_at`.
- **Front**: "Unpublished changes" banner + **Publish** / **Cancel** buttons; the editor works on the draft; i18n.
- **`_push_sync_org`**: add `preemptive=false` (graceful) — does it also apply to the other callers? (to check: events/embargo may want preemptive). → keep `_push_sync_org` preemptive by default, and a `_push_sync_org(db, preemptive=False)` for Publish.

## 4. Points of attention
- **Conformance #2**: today on `add_playlist_item` (live). In Arch 2, move the check to **Publish** (per draft item) — the advisory then surfaces at publication.
- **Item rules / tags**: the draft must carry the per-item rules (and tags?). Tags = `cms_playlist_item_tags` (separate) — decide whether they are staged too (otherwise they apply live). v1: stage items+rules; tags out of staging (rare mid-edit).
- **Concurrent editing**: a single draft per playlist (no multi-user on the same draft — acceptable).
- **`sync_windowed`/`sync_ready`** recomputed at publication.

## 5. Verdict
**GO Arch 2.** Medium-high effort (migration + 4 endpoints rewritten on the draft + 2 new ones + front), **contained risk** (sync path intact). Iterable: v1 = items+rules staged, tags/advanced to follow.
