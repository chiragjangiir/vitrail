---
title: Audio baskets — in-store music and messages
section: audio
roles: []
keywords: [audio, audio baskets, music, ambience, jingle, message, emergency, ducking, mix, ratio, weight, random, shuffle, recurrence, every N tracks, every N minutes, audio schedule, audio player, sound, volume, store panel, store control, listen, preview, playback rule, mandatory, national, regional, local, style, paniers audio, musique]
---

# Audio baskets — in-store music and messages

An **audio basket** is a pool of sound content that a screen (or a player
without a screen) draws from continuously: a background music playlist, a set of promotional
announcements, a chain jingle. The **Audio Baskets** page is used to compose them; it is
**Scheduling** that then decides which players play them, through an *audio
schedule*.

A basket is therefore not assigned to a screen from this page: you compose the content here, you
publish elsewhere. It is the same separation as for visual playlists — composing and
publishing are two distinct actions.

## The five types, and why the type matters

| Type | Role |
|---|---|
| **Music** | the continuous background sound |
| **Ambience** | atmospheric soundscape, same logic as music |
| **Message** | a spoken announcement (promotion, customer information) |
| **Jingle** | the chain's sound identity, at regular intervals |
| **Emergency** | priority announcement (evacuation, recall) |

The type is not just for sorting: it determines **who lowers whose volume**. *Message*,
*jingle* and *emergency* baskets lower the music while they speak; *music* and *ambience*
baskets undergo this reduction. This is **ducking**.

## Ducking

Without it, a spoken announcement would overlap the music and become unintelligible.
Three settings, on the basket that **undergoes** the reduction:

- **music volume during the message** (in %);
- **fade in** and **fade out** (in milliseconds) — a sharp cut sounds
  like a technical fault, a fade of a few hundred milliseconds goes unnoticed.

## Composing a basket

**Add content** opens a search drawer over the whole audio media library, with
preview: you can select several items at once, and tracks already present are
flagged. Each item then carries:

- a **weight** — the higher it is, the more often the track comes back;
- **random** or sequential order, at basket level;
- an optional **playback rule**: days of the week and time slot, in the site's
  local time. Without a rule, the track always plays. This is what lets an announcement
  come out only at peak hours, or Christmas music stop on its own.

**Listen to the basket** chains the active tracks as the player will: it is the only
honest way to judge a sequence before sending it to the store.

## Jingle recurrence

A *jingle* basket does not play in a loop but **at intervals**, either:

- **every N tracks** — the sound identity returns at a rhythm tied to the content;
- **every N minutes** — the rhythm is tied to the clock.

## Scope and mixing between levels

A basket has a **scope** — *national*, *regional*, *local* or *style* — and a **mix
ratio** bounded by a minimum and a maximum. These guardrails are at the heart of the matter in a
network: a store can adjust the share of its local music, but **never** go
below the minimum or exceed the maximum set above it.

The **Mandatory** checkbox goes further: it locks the ratio for lower levels.
A mandatory chain jingle at 10 % will play at 10 % in every store, with no
possible discussion on site.

A basket can also be attached to a **governance node** (see the Governance article):
it then no longer belongs to the whole organization but to that level, which alone can
modify it.

## The store panel

A store manager does not need a CMS account to act on the sound ambience:
a local panel, reachable on the store network, lets them adjust the mix within the
allowed limits and trigger an announcement. It keeps working even if the
central server is unreachable.

## What is measured

Every actual play — music, ambience, message, jingle — reports a signed **proof of
play**, exactly like visual content. This is what makes it possible to bill an advertiser's audio
spot and prove it played, to the second.

## Frequently asked questions

**"The music does not lower during announcements."** Check the type of both baskets:
only a *message*, *jingle* or *emergency* basket triggers ducking, and only *music* and
*ambience* undergo it. A message filed by mistake as *music* will not lower anything.

**"A store cannot change its mix."** It is probably a *mandatory* basket,
or a minimum/maximum set at a higher level. The lock is intentional.

**"I delete a basket and the product refuses."** It is used by an ongoing
playback. The message names what holds it; you can confirm, and the basket will then be
removed from those playbacks.

**"Nothing comes out of the player."** A composed basket does not play on its own: you need an
**audio schedule** in Scheduling that targets this player. Composing and publishing are
two distinct actions.
