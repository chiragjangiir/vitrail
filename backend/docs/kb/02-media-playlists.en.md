---
title: Media and playlists
section: content
roles: [CMS_ORG_ADMIN, CMS_DESIGNER, CMS_SCHEDULER]
keywords: [media, import, upload, video, image, playlist, encoding, rendition, transcoding, rotation, sub-playlist, nested, one item per loop, random, shuffle, preview, view, player, multi-zone, template, zones, layout, média, sous-playlist, aperçu]
---

# Media and playlists

## Import a media

1. Go to **Media**.
2. Click **Import** (top bar) and select your files (video, image,
   document). You can also draw from **Free Photos** (Unsplash / Pexels).
3. On import, a video is automatically transcoded into a universal format (H.264).
   Content keeps being broadcast during processing; no screen goes black.

### Adaptive renditions

If your organization enables the renditions policy (for example "Auto FHD"), an
imported 4K video also generates a Full HD version. Each player then receives the
resolution suited to its screen and its decoding power — a 1080p screen does not
need the 4K stream. This reduces bandwidth and avoids stuttering.

### Replace a media's file

You can replace the file of an existing media without changing its identity: it remains
referenced by the same playlists. The old content keeps being broadcast until the
new transcoding is finished (atomic switchover).

## Create a playlist

1. Go to **Playlists** and click **New playlist**.
2. Add media (the same media can be added to several playlists).
   Multi-selection lets you add several media at once.
3. Set the display duration of each image and the order of the items.
4. A playlist plays in a loop on the players that broadcast it.

## Preview a playlist before scheduling it

The **play** button — on a playlist's card or in its editor — runs through the loop
the way a screen would, without leaving the page.

If the playlist sits on a **multi-zone template**, the preview composes **all zones
at the same time**, at the template's aspect ratio, each zone advancing on its own timer — which
is what a screen does. A single-zone template keeps the usual full-screen preview.

It is a preview, not a mirror of a screen, and it is best to know this before relying on it:
each zone starts from the **beginning of its loop** (and not from the position a screen would be at
that moment), and **"N per loop" rotation**, **campaign spots** and **tag
filtering** are not replayed in it — those three depend on the player, which a preview does not have.
**Feeds, web pages and HDMI inputs** are named at their real place and real size,
without being rendered: they are produced on the screen, at broadcast time.

To know the actual run of a day on a given screen, use the **day
simulation** (Schedules) or a player's **compiled schedule**, which are authoritative.

## Playlist rotation (sub-playlist "N items per loop")

A playlist can be **nested inside another** as an item (**"Add a
playlist"** button in the editor, next to "Add media"). The behavior depends on the
**Rotation** setting of the nested playlist ("Rotation" section of its editor):

- **All items** (default): the sub-playlist plays in full on each loop.
- **N per loop — in order**: only N item(s) play on each loop; on the next loop,
  the following ones (circular cursor). Example with 5 videos and 2 per loop:
  videos 1-2, then 3-4, then 5-1, etc.
- **N per loop — random (no repeats)**: shuffled order, but no item is
  replayed until all have played; the shuffle then starts again.

Useful points:

- The **"Items per loop"** field sets N (default 1).
- These settings **follow the draft**, like the content: changing them shows
  the "Unpublished changes" banner, and screens keep playing the
  published loop until you click **Publish** (or, for a governed playlist
  under moderation, until **approval**). "Cancel" reverts to the published loop.
- **A single nesting level**: a sub-playlist cannot contain another one.
- A playlist used as a sub-playlist cannot be deleted while it is
  referenced (first remove it from its parent playlists).
- Broadcast rules and per-item tags are set on the items **of the sub-playlist**
  (they are the ones actually served to the players).
- Rotation is **synchronized**: two screens of the same LAN group play the same item
  at the same moment, and the **timeline simulation** shows the actual run loop by loop.
- If the **same sub-playlist appears several times** in a loop, all its
  occurrences play **the same item on the same loop** (they share the draw — this is what
  guarantees determinism and sync). To hear different items within
  the same loop, rather increase "Items per loop" or create two distinct
  sub-playlists.
- Proof of Play is recorded for each actual play of
  each item, as for a regular media.

## Delete a media safely

Before deleting a media, Vitrail displays its **impact**: playlists, schedules,
events and audio baskets that use it, and whether it is currently being broadcast. Cascade
deletion can remove the media from playlists, delete playlists that became empty and
cancel orphaned events. Read the modal before confirming.
