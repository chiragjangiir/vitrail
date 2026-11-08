---
title: Retail media campaigns (advertiser advertising)
section: content
roles: []
keywords: [campaign, retail media, advertiser, advertising, SOV, share of voice, inventory, overbooking, cap, rate, quote, achievable SOV, competitive exclusion, category, creative, max duration, approval, advertiser report, calendar, import, proof of play, CPM, monetization, campagne, annonceur]
---

# Retail media campaigns (advertiser advertising)

The **Campaigns** page turns your screens into **monetizable advertising inventory**:
an advertiser (brand) buys a **share of voice (SOV)** — a percentage of air
time — over a given period and on given screens. Vitrail automatically interleaves its
creatives into the content loop, measures actual playback (signed proofs) and
produces the quantified **advertiser report**.

## Concepts

- **Advertiser**: the client brand (page **Campaigns → Advertisers**). Creating one
  automatically opens a media library folder "Advertisers/&lt;name&gt;". An advertiser carries
  one or more **industry categories** (see competitive exclusion) and can
  receive **portal access** (see the Advertiser portal article).
- **Campaign**: period (dates + optional daily time window), SOV sold in %,
  pricing model (**SOV** or **flat fee**, indicative CPM), targets (org / site / **site
  group** / group / player — combinable) and creatives (videos or images, weighted rotation).
- **Statuses**: draft → published (**scheduled** before the start date, **live**
  during, **ended** after); pause/resume/cancel at any time. Pausing removes
  the creatives from the screens immediately. **Deleting** a campaign cleans up everything
  (playback, inventory, advertiser links revoked).
- **Opt-out**: a player marked "Excluded from advertising campaigns" (player drawer) never
  plays a creative and does not count in the inventory (checkout screen, back office).

## Inventory, caps and rates per screen

The **Inventory** panel shows the share of voice already sold per screen. When entering a
campaign, the occupancy projection warns at **80 %** and **blocks at 100 %** (an org-admin
can explicitly force it — deliberate overbooking, the shares are then reduced
proportionally). Each screen can carry:

- an **advertising occupancy cap** (player drawer, otherwise inherited from the site): a checkout
  screen capped at 20 % will never exceed 20 % advertising — the 80/100 % thresholds
  are then understood **relative to the cap**;
- a **rate** (€ for 1 % of SOV per day, inherited org → site → player): the campaign
  drawer displays an **indicative quote** (total, rated screens, days). The campaign's
  **contractual price** remains a field entered by hand — the quote helps set it.

## Achievable SOV

Selling 40 % SOV on a screen whose loop is long can be physically
impossible (only one ad per loop cycle). The **"Achievable SOV"** banner (amber)
computes the maximum reachable given the loop actually scheduled and the average duration
of the creatives, and offers **"Use X %"** in one click. The gap is also visible to the
reviewer in the approval queue.

## Competitive exclusion

Manage **industry categories** (Categories button, Advertisers page) and assign them
to advertisers (an agency can carry several). On each **site**, list the
**excluded** categories (e.g. a store under an exclusive beverage contract): campaigns of the
advertisers concerned can neither target nor play on that site — targeting, occupancy,
quote, report and portal (greyed-out sites) apply it everywhere.

## Creatives: max duration and approval

- **Maximum creative duration**: adjustable at org level (default **30 s**, empty =
  unlimited) — an over-long creative is refused when added and re-checked at publication.
- **"Creative approval required"** checkbox (org-admin): every **new creative**
  arrives **Pending** and must be approved before playback; a rejected creative never
  goes on screen. Creatives **uploaded by an advertiser** (portal) are always
  born pending. See also the **Approvals (approval workflow)** article for
  approval of the whole campaign.

## Playback and proof

Creatives are **interleaved into the existing loop** of the targeted screens, at the frequency
matching the SOV sold — without touching the playlists, and **never two spots back to
back**: at most one ad per loop cycle (anti-hammering). If the SOV sold
exceeds what the loop allows, the excess becomes **measured under-delivery** (alert
"campaign under-delivered"). Each play generates a timestamped **proof of play**,
chained (Merkle) and **signed by the screen** (Ed25519). Tip for synchronized groups (LAN
sync): target **whole** groups.

## Calendar and import

- The **Calendar** panel of the Campaigns page shows a monthly Gantt of campaigns
  with the **load per day** (amber ≥ 80 %, red > 100 %).
- **Import (JSON)**: create a complete campaign from a file (advertiser, targets
  by name, creatives by URL) — **preview (dry-run)** with occupancy projection before
  creation, publication always manual. The same import exists **via API** with a
  machine key `sfi_` (scope campaigns:import) to plug in an external tool.

## Advertiser report

**Report** button in the drawer: plays (including signed), air time, **SOV delivered
vs sold**, **hierarchical breakdown groups → sites → screens** (collapsible), per day and
per creative, amount. **White-label PDF** export (at the chosen level of detail) and **protected
public link** (password, IP allowlist) to send to the advertiser.

## Notifications

In **Settings → Notifications** (**webhook or email** channels): **campaign started**,
**campaign ended** (summary) and **campaign under-delivered** (SOV delivered below a threshold of the
sold SOV — 80 % by default, adjustable per rule).

## Ask the assistant

The assistant (and Jeanine on Telegram) answers "**how is campaign X doing?**" (status,
dates, targets, creatives) and "**the report for campaign X**" (plays, SOV delivered,
amount — reserved for accounts with the campaigns : report permission).
