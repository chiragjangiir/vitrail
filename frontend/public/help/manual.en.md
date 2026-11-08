# Vitrail User Manual

## Welcome to Vitrail

Vitrail is a digital signage platform: you broadcast content (videos, images, web pages, news feeds, audio) to screens driven by players, from a central web interface.

### Key concepts

- **Organization**: your workspace. Content, players and users are isolated from other organizations.
- **Player**: the software installed on the device connected to a screen (Linux NUC, Raspberry Pi, Windows PC, Android box, Chromebox, BrightSign, or a simple Chrome extension). It takes its instructions from the server — never the other way around — and keeps working offline.
- **Media**: an imported asset (video, image, document) or a dynamic one (web page, feed, HDMI input).
- **Playlist**: a sequence of media played in a loop.
- **Schedule**: when and on which players a playlist is broadcast.
- **Event**: a one-off or triggered broadcast that takes priority over the normal schedule.
- **Campaign**: advertiser content inserted into your loops, sold as share of voice (retail media).

### The typical journey

1. **Enroll a player**: generate a provisioning token, install the player, it appears under Players.
2. **Import content** into the Media Library.
3. **Create a playlist** with that content.
4. **Schedule** the playlist on one or more players.

The screen shows the content a few seconds after the schedule is saved.

> Missing a menu or an action? It is probably a role question: ask your organization administrator (see "Users, roles and security").

## Players

### Enrolling a player

A player joins your organization with a **provisioning token**:

1. **Players → Provisioning** → **New token** (top bar).
2. Choose the maximum number of players and an expiration (or "No expiration").
3. Copy the token (`sfp_…`) and provide it during player installation together with the server URL.

On first start, the player exchanges the token for its permanent identity and appears under **Players**. An active token can be **revoked** (it no longer enrolls; already-enrolled players keep working) and then deleted.

### Batch provisioning and USB key

The **Generate a payload** drawer prepares the configuration of several machines at once: per-machine or shared settings, CSV import, resolution (Auto/HD/FHD/4K/8K/custom), Wi-Fi, re-attaching an existing player (searchable list). The payload is applied via USB key on prepared Linux players, or via SD card for BrightSign.

### Monitoring and remote configuration

The Players list shows the state (online / offline / scheduled standby) with the last-contact date. A player's drawer shows: machine, screen, network, timezone, media inventory, recent screenshot, decoding capabilities.

Without SSH, you can push: resolution, rotation, volume, sound, rendering engine, timezone, bandwidth cap. The **"On-screen info"** button displays a diagnostic panel directly on the player's screen (name, network, current schedule, playing media) — handy to identify a screen remotely. One-off buttons: restart the app, reboot the machine, force a resync, screenshot. The **“Bulk commands”** button in the top bar sends the same command to a whole target (organisation, site, site group, player group); a preview lists the affected screens **before** sending, and destructive commands (reboot, quit app, maintenance) require a confirmation checkbox **and your PIN**.

Two "campaign" settings also live in this drawer: **Excluded from ad campaigns** (opt-out) and the **ad occupancy cap** (see Campaigns).

### Groups and LAN sync

**Player groups** serve as broadcast targets and carry **LAN synchronization**: several players on the same local network play the same video frame-accurately (video wall, coherent ambiance). Sync is reliable when the group is **homogeneous** (same hardware) and players share the same clock (see NTP). One group member can be designated as the **NTP relay**.

### Chrome extension (no hardware)

The Chrome extension turns a browser into a player: great for testing or for an existing workstation. Load the extension (developer mode), enter the server URL and an `sfp_…` token. Limits: no LAN sync, reduced offline mode. For a real ChromeOS kiosk, use the ChromeOS PWA player.

## Sites

A **site** represents a physical location (store, branch). Each player is attached to a site.

- **Timezone**: all scheduling runs in the site's local time. An attached player is automatically aligned to the site's timezone (warning badge on mismatch, remote fix from its drawer).
- **Opening hours**: days and hours, with **dated exceptions** (holiday, inventory, special evening) and automatic closure on **public holidays** (optional regional calendar). A day without hours is closed. These hours drive screen power (see "Screens and power") and are known to the assistant ("is site X open on Sunday?").
- **NTP server**: so all players of the site share exactly the same clock (essential for LAN sync).
- **Coordinates**: place the site on the map (used by geo reports and the advertiser portal).
- **Excluded categories**: industry categories banned from advertising on this site (see Campaigns).
- The **Site groups** tab creates sets (region, banner) usable as targets in schedules, events, campaigns and updates.

Hovering a site (list) shows a tooltip with its players and its 7-day ad occupancy.

## Media Library

### Importing

**Media Library → Import**: videos, images, documents (PDF). The **Free Photos** tab draws from Unsplash/Pexels with automatic attribution. A video is automatically transcoded to a universal format: the previous content keeps playing during processing, no screen ever goes black. If the organization's **renditions** policy is active, a 4K video also generates a Full HD version — each player receives the resolution suited to its screen.

### Organizing

- **Folders** and subfolders (left column), bulk move.
- **Tags**: namespace-based taxonomy (Media Library → Tags), multiple assignment, and **tag filtering at player level** (a player only plays content matching its tags).
- Search, type filter (images/videos/audio/documents/web pages), pagination.

### Managing the lifecycle

- **Replace the file** of a media without changing its identity: playlists that use it are untouched, the swap is atomic at the end of transcoding.
- **Delete safely**: the impact modal lists playlists, schedules, events and baskets using the media, plus its broadcast state, before cascade deletion.
- **Quarantine**: instantly block a media across the fleet (even offline), then unblock or purge its cache.
- **Conformance**: each video carries a verdict (ready / playable / non-conformant) about its encoding, with re-analysis and a passthrough mode (keep the original file without re-encoding).

## Templates

**Templates** define multi-zone layouts (main video + ticker + logo…). The editor works at the declared **canvas resolution** (FHD, 4K, portrait, custom LED) — choose the resolution of the target screen. A playlist bound to a template feeds its zones; a warning appears if the template resolution does not match the targeted screen.

## Playlists

1. **Playlists → New playlist**, then add media (multi-select, search, folders).
2. Set the order, the display duration of images/documents and the zone (for multi-zone templates). Videos show their **native duration** — it is read, not set.
3. Changes accumulate as a **draft**: the **Publish** button pushes them to players in one go (clean swap, never an empty state).

The editor header and each playlist card show **the number of items and the total duration** of the loop; the total follows your edits live, draft included.

### Previewing a playlist

The **play** button — on a playlist card or in the editor — runs the loop the way a screen would. On a playlist bound to a **multi-zone template**, the preview composes every zone at once, at the template's aspect ratio, each zone advancing on its own timer.

It is a preview, not a mirror of a screen: every zone starts at the beginning of its loop, and rotation, campaign spots and tag filtering are not replayed there. Feeds, web pages and HDMI inputs appear by name at their real place and size — they are produced on the screen, at playback time.

### Per-item broadcast rules

Each item can carry its own rule: days of the week, time slot, validity date range — in the player's local time. **Per-target exceptions** refine this: a given player or group plays the item under a different rule. An item without a rule is perpetual.

### Rotation playlist (N items per loop)

A playlist can be **nested inside another one** as an item (**Add a playlist** button in the editor). Its **Rotation** setting decides the behaviour:

- **All items**: the sub-playlist plays in full on every loop.
- **N per loop — in order**: N item(s) per loop, the next ones on the next loop (with 5 videos and 2 per loop: 1-2, then 3-4, then 5-1…).
- **N per loop — shuffled**: random order, but no item repeats until all have played, then it reshuffles.

Only one nesting level is allowed; a playlist referenced as a sub-playlist cannot be deleted (remove it from its parents first). Per-item rules and tags live on the **sub-playlist's own items**. Rotation stays **synchronized** across screens of a LAN group, and the **timeline simulation** shows the actual loop-by-loop sequence. If the same sub-playlist appears **several times** in one loop, all its occurrences play the **same item on the same loop** (shared draw, which guarantees determinism) — to vary within a loop, increase "Items per loop" instead.

These settings **follow the draft**, just like content: changing them raises the “Unpublished changes” banner, and the screens keep playing the published loop until you click **Publish** (or, for a governed playlist under moderation, until it is **approved**).

## Audio baskets

**Audio baskets** provide in-store background audio, independent from visual content: background music, jingles at intervals or fixed times, with automatic **ducking** (music lowers during a jingle). Each player has an **audio role**: standard content (video sound), audio only, or mixed (background audio + muted videos). The **store control panel** (LAN) lets on-site staff act without a CMS account. Each basket card shows **the number of tracks and the total duration**. SACEM-style reports rely on proven plays.

## Scheduling

A **schedule** says what to broadcast (a playlist), where (players, groups, sites, site groups, tags) and when (days, slots, validity range, priority).

1. **Scheduling** → create a rule, choose playlist, targets and time window.
2. The players update within seconds.
3. The **unified calendar** overlays visual and audio programs, events and campaigns (icon legend). Filter by type (All/Visual/Audio/Events/Campaigns pills) or by **target** (site group, site, player); the **CSV export** follows the active filters. When rules overlap, the highest **priority** wins.

Multi-level networks (head office, regions, stores) compose their scheduling with **Hierarchical governance** — see the dedicated section below.

## Hierarchical governance (multi-site networks)

**Governance** is for networks where several levels decide what is shown: a head office, regions, stores. Each level composes **its** share of the schedule, and screens play the **sum** of the levels they depend on. A single-site installation does not need it: with no node, nothing changes (the “Owning node” field is not even displayed).

### The five notions

- **The node** is a level of the organisation. Its **level** in the tree (root = 0) sets the national → local order, not its “type”, which is only a label.
- **The scope** is the set of screens a node drives: you attach screens, screen groups, sites or site groups to it. A node's scope **includes that of its descendants** — attaching sites to the store nodes is enough.
- **The layer**: every schedule attached to a node produces a layer. A screen compiles all the layers of the nodes it depends on. That is what the “Compiled program” column shows, **for that screen and at that moment**.
- **The rule** says how much each level may take. The most used is “**items per turn**”: with 1, each level places one item per turn and **rotates** its content.
- **The node administrator** decides for that node. ⚠️ A permission is **never** enough: it is this assignment that grants write access.

### Who can do what

A node administrator acts on **their node and its whole subtree**. They see the levels above **read-only** and do **not see** neighbouring branches at all. Three actions always move up one level: **detaching** content from governance, **removing moderation** or **lifting a restriction**, and **approving** a submission — the approver must administer a **parent** node, and nobody approves their own submission. Creating a **root** node is reserved to the organisation administrator.

- **Governance — Director**: builds the structure — nodes, scopes, administrators, rules. Reads content, does not produce it.
- **Governance — Programmer**: creates the **schedules** and **playlists** of their nodes, submits for approval.
- **Governance — Editor**: produces content (playlists, media) and submits it. Deletes no media, does not schedule.
- **Governance — Approver**: approves, rejects or requests changes on their subtree.

These four roles carry a **scope semantics**: their holder only acts within their subtree, and **ungoverned content is invisible to them**.

### Governed content

A playlist, a media, a template, an event and a VOD configuration can belong to a node (“Owning node” field). With no node, the object belongs to the organisation and behaves as before. An attached object can only be edited by the administrators of its node or of a parent node; if the node is marked **“Content subject to approval”**, you **submit** instead of publishing, and approval publishes. This moderation is **inherited downwards**.

⚠️ **Two costly misunderstandings.** Attaching a playlist to a node decides **who edits it**; it does **not broadcast it** — broadcasting comes from a **schedule** attached to the same node. And the **role** says what you may do, the **administrator assignment** says **where**.

### Targeting only part of a node's screens

By default, a schedule attached to a node plays on **all** its screens. To target only some of them, add **targets**: they **narrow** the scope, never widen it, and a lower level can never narrow an **inherited** layer. A target that keeps no screen is rejected by name, and the number of screens kept is displayed. **Leaving a schedule with no target is often the right choice**: it then covers its whole node, including sites added later.

### Worked example: store entrance and exit

Goal: in every store, the **entrance** and **exit** screens play one item **more** than the others, and the store manager changes their own content and schedules.

**The tree** — `National` → `Dpt-01` → `Site-01`, `Site-02`.

**The scope** — attach **the site** to the store node. The department and the national node have **no assignment**: they inherit from the subtree.

**Two screen groups** — “Entrances” holds the entrance screen of **every** store, “Exits” the exits. The group marks the screen's **role**, the node marks the **store**: crossing both designates the right screen, without creating one group per store.

**The content** — each store owns **its own** playlists: local, entrance, exit. 🔑 A playlist shared between two stores can only be edited by its owner — the other manager cannot even read it.

**The schedules** — one per node, plus two per store:

- **National** — schedule "SC National", **no target**: every screen in the network.
- **Dpt-01** — schedule "SC Dpt", **no target**: every screen in the department.
- **Site-01** — schedule "SC Site-01", targeted at the store's screens: local content.
- **Site-01** — schedule "SC Entrance Site-01", targeted at group "Entrances": the entrance only.
- **Site-01** — schedule "SC Exit Site-01", targeted at group "Exits": the exit only.

With “items per turn = 1” on each node, ordinary screens play **3 items per turn** (national + department + local) and both the entrance and the exit play **4**.

**Adding a store** then takes five steps: create the node under the department, attach the site to it, create its three playlists, create its three schedules, add its entrance screen to the “Entrances” group and its exit screen to the “Exits” group. The national and department schedules need no change.

### Composing a scope at scale

The **“Add screens”** button opens a **server-side** search: filter by kind (screen, screen group, site, site group), select **several targets at once**, and each row states **how many screens it represents**. A screen still attached to **no** node is offered and **labelled**: that is how a forgotten installation becomes visible and repairable.

### Reorganising and diagnosing

A node can be **moved** under another parent: paths, levels and broadcasting of its whole subtree follow. It cannot be moved under one of its own descendants, nor into a branch you do not administer.

When a screen's preview is empty, the message **names the cause**: no node, no schedule on the node, inactive schedule, no playlist, **no time rule** (it will never be active), or outside its window at that moment.

## Events

An **event** temporarily takes priority over the schedule: promotion, announcement, triggered content.

- Content: a playlist or a single media. Target: org, site, group or player — and types can be **mixed** within one event ("this site" + "these 3 screens", like campaigns): selections add up, and the recap names everything included. "Entire organization" overrides the other selections.
- Types: **manual** (triggered on demand), **scheduled** (date/time window, optionally recurring).
- **Hourly spot**: on a scheduled event set to "Play once", enable fixed-interval repetition (e.g. one spot every 30 minutes). The field only appears in that combination.
- **Reference timezone** (scheduled event): it defines what "18:00" means. Defaults to the server timezone. On a network spanning several countries, set it explicitly — an event fires at **one single instant**, not at 18:00 in every country. The timezone is shown next to the schedule in the list.
- ⚠️ Not to be confused with the **embargo**, which is an **absolute** instant (UTC): it does not depend on any timezone and is unaffected by this setting.
- **"Keep screens on"** option: keeps the display alive during the event even outside opening hours (special evening).
- When it ends, the player returns exactly to its schedule (current time).
- An event **(re)activated mid-window** with a media file never distributed before may take a few minutes to appear (the player downloads the file first — never a black screen). Activate/schedule in advance for an instant switch.

## On-demand broadcast (VOD)

The **On-Demand** page broadcasts content immediately, on top of the schedule, without touching playlists. A **VOD config** groups media and a target: either **selected players** (from the same site) or an **entire site** — in which case any player added to the site later is picked up automatically; media are pre-downloaded, so triggering is instant: **Once** or **Loop** (until Stop). The `vod : trigger` permission alone is enough for a "store" account. Afterwards, the schedule resumes at the current time.

> **BrightSign** specifics: start and stop can take **up to 2 seconds** (on-device local relay) — this is normal. During playback the playlist is suspended (a single hardware video stream on these players) and then resumes at the current time. The initial pre-download can take a while for 4K files: until a media file is cached, it streams (delayed start).

## HDMI input

The **"HDMI input"** media shows whatever source is plugged into the player's HDMI input (TV decoder, box, console) — purely local playback. Compatible: BrightSign with a physical HDMI input (XT, 4K114x, XD1230 ranges).

- **In a playlist**: a slot switches to the source then resumes the playlist; players without an input skip the item. Without a signal, the screen shows "No Signal Detected" (never a black screen).
- **On demand**: via a VOD config, **Switch to HDMI / Back to playlist** buttons (resume at current time).
- **Local page**: each compatible BrightSign serves `http://<ip>:8888/control` — switch/return from any phone in the store, no account or server needed (activation + PIN per player).
- Safeguards: a switch left active is ended when the screen powers off; every session is traced (audit + signed proof of play with the real duration).

## Feeds and web pages

### Feeds (news streams)

A **feed** is a source polled by the server: RSS/Atom, Google News, YouTube, weather, crypto, finance, social networks (via the feed proxy). Display modes: scrolling ticker, carousel, grid, full-screen article, split layout, list, social wall, chart. Options: **AI summary** of articles (one line readable from afar), **moderation** (approve each article before broadcast), thumbnails cached on the player (works offline).

### Web pages (URL Display)

Show a web page on screen: **WebView** mode (live rendering on the player) or **server capture** (the server screenshots the page periodically — for pages that refuse embedding or need server-side authentication). A web page is a media like any other: tags, playlists, scheduling.

## AI generation

Vitrail generates images, videos, music and voice-overs from a description. The generated media joins the library normally.

- **Prerequisite**: your organization's AI keys (**Settings → AI Keys**) — fal.ai (images/videos/music/voice), ElevenLabs (pro audio), Anthropic (prompt assistant and Studio). You pay your own provider; without a key the feature is inactive.
- **Where**: Media Library → **Generate (AI)** for one asset; **Studio** for a full campaign from a brief (concepts per format, total cost shown before generating).
- **Prompts**: models work in English — the **prompt assistant** turns your idea (any language) into an optimized English prompt + negative prompt. Keep it simple: subject + action + style; for video add camera and light; never meta-instructions ("promotional content…" ends up drawn in the image).
- **Editing**: background removal, instruction-based retouching, multiple variations, image → video (describe only the motion).
- A **cost estimate** is shown before each generation.

## Promo generator

The **Promo generator** builds a promotional poster (image or short video) from a product, a price and a layout. The result lands in the media library and plays like any other media.

- **Where**: Media Library → **Promo generator**.
- **A six-step path**: **Who is it for?** · **The product** · **Text and price** · **Layout** · **Background** · **Free edits**. Only one step is open at a time so all its fields fit on screen; collapsed, a step **shows its value**. Open them in any order.
- **"Who is it for?" comes first**: your own brand or an advertiser — the **brand kit follows from the answer** (colours, font, logo, notices) instead of being picked.
- **Start from a product URL**: paste a product page address and the name, price and photo are extracted. Everything stays editable — it helps you type, it is not a source of truth.
- **The price is required.** **Generate** stays off until it is filled, and the banner under the preview says what is missing **and takes you to the right step**. The same banner reports legibility problems, re-checked by the server before producing.
- **AI only makes the background** (and cuts out the product). Price, discount, name and legal notices are composited from what you typed — so they are exact.
- **Chain visuals**: "Redo with another product" keeps brand, layout, background and notices; **presets** recall a full configuration.

### Series mode — one layout, N products

The **Single visual / Series** toggle at the top replaces the preview with a **table**: one row per visual. The path on the left still defines what is **common** (brand, layout, background, notices, currency); the table only carries what **varies** — product, slogan, price, was-price, discount.

- **Three ways to fill it, all combinable**: add a row by hand, **import a CSV**, or **paste from a spreadsheet** (Excel, Google Sheets). Headers are recognised in English and French, in any order. ⚠️ With no recognised header, columns are read **in order** and the screen says so — check the table.
- **Importing adds**, it does not replace: you can import two files, or top up by hand.
- **A row without a price does not stop the series**: it is highlighted, named in the warning, and skipped. The button says how many visuals will actually run.
- Each visual is **named after its product**, otherwise they would all land in the media library under the same name.

## Brand kits

A **brand kit** declares a brand's colours, font, logo, legal notices and tone once and for all. The **Promo generator** then uses it to pre-fill every visual.

- **Two scopes**: one kit for your **organisation**, and one per **advertiser**. When a visual is made for an advertiser, that advertiser's kit applies; otherwise the organisation's does.
- **Where**: Promo generator → **Brand kits and fonts** button in the top bar. Organisation administrators only.
- **A kit only replaces what it declares**: a colour left unchecked means "the kit says nothing", and the template keeps its own. That is what lets you impose a single accent colour without overwriting the rest.
- **It pre-fills, it does not lock**: on a given visual, what you type wins over the kit. Legal notices are copied in once — clear them deliberately and they will not come back.
- **The logo and brand name are never drawn by AI**: a generated background only receives the palette and the tone, as an atmosphere to aim for. Logo, brand name and legal notices are placed afterwards by the compositing engine, so they are exact. The "Place the brand logo" button adds it as a movable layer.
- As long as no kit exists, nothing changes: visuals keep their template's colours.

## Campaigns (retail media)

The **Campaigns** page sells your screens as advertising inventory: an advertiser buys a **share of voice (SOV)** — a percentage of airtime — over a period and a set of screens.

### Advertisers and competitive exclusion

Create your **advertisers** (Advertisers page): each gets a media folder "Advertisers/<name>" and one or more **industry categories**. On each **site**, list the **excluded** categories: the advertisers concerned can neither target nor broadcast on that site (enforced in targeting, occupancy, quotes, reports, portal and delivery).

### Creating and publishing a campaign

A campaign = period (+ optional daily time window), **SOV sold in %**, price (SOV-based or flat, entered manually — an **indicative quote** is computed from per-screen rates), targets (cumulative: org, sites, site groups, groups, players) and creatives (videos/images, weighted rotation). Statuses: draft → published (upcoming / live / ended), pause (immediate removal from screens), resume, cancel.

- **Inventory**: the occupancy projection warns at 80% and blocks at 100% of each screen's **cap** (cap adjustable per player or site — e.g. checkout screen limited to 20%); an org-admin can force it (accepted overbooking).
- **Rates**: € per 1% of SOV per day, inherited org → site → player.
- **Achievable SOV**: an amber banner warns when the requested SOV exceeds what the actually scheduled loop allows, with a "Use X%" button.
- **Max creative duration**: adjustable per org (default 30 s) — refused on add and re-checked at publish.
- **Creative approval** (optional, per org): every new creative starts "Pending" and must be approved before broadcast.
- **Calendar**: monthly Gantt of campaigns with per-day load (amber/red).
- **Import**: a full campaign from a JSON file (dry-run preview, created as draft, manual publish), also available **via API** with an `sfi_` key.

### Delivery, proof and report

Creatives are **inserted into the existing loop** at the frequency matching the sold SOV — never two spots back to back (at most one ad per loop cycle; the excess becomes measured, alerted under-delivery). Every pass emits a **proof of play signed** by the screen. The **advertiser report** gives passes, airtime, served vs sold SOV, hierarchical breakdown groups → sites → screens, amount — **white-label PDF** export and a **protected public link** (password, IP allowlist). Notifications: campaign started / ended / **under-served**.

## Advertiser portal

The **portal** (`/portal`) is your advertisers' white-label space: each one only sees **their own** campaigns.

- **Opening access**: advertiser drawer → Portal access section → invite by email (initial password shown only once). An advertiser account always lands on the portal, never in the CMS.
- **The advertiser can**: follow their campaigns and reports (PDF), **create a campaign** (sites on a map — sites incompatible with their category are grayed out —, period, SOV or **Exclusive** = 100%, aggregated availability ok/tight/full and a **live quote**), upload creatives (adjustable quotas, default 20 files / 1024 MB — always reviewed before broadcast), **submit for validation**, fix and resubmit when changes are requested, save **site lists**, pick their **language** (5 available).
- If the organization enables **"Per-screen selection (portal)"**, the advertiser can tick individual screens within each site.
- A **bell** informs them of decisions (plus an email if you tick it at decision time).

## Validations (approvals)

The **Validations** page centralizes approval requests — currently campaigns (submitted from the CMS or the portal).

1. **Submit**: "Submit for approval" (one active request per resource). A campaign under review cannot be published.
2. **Review**: the reviewer sees everything — playable creatives, advertiser, period, requested and achievable SOV, quote, named targets, projected occupancy with the detail of campaigns already in place.
3. **Decision**: approve / reject / request changes (reason required), with an **email to the advertiser** option (ticked by default). Approval also approves the request's pending creatives.
4. **Resubmission** after fixes; history preserved.

Reviewers (`approvals` permissions) see the whole organization's queue and a **bell** in the top bar; **CSV/PDF exports** of the queue; requests in a terminal status can be removed from the list (audit trace kept).

## Reports and analytics

- **Executive Dashboard**: network KPIs, **Network Health Score**, trends — site/group filters, **white-label PDF** export (your logo), **scheduled email** delivery.
- Specialized dashboards: NOC (fleet health), content, geo (site map), audience.
- **Proof of Play**: every play is recorded, chained (Merkle) and **signed by the player** — integrity check and exportable **certificate**. Music-rights reports rely on it.
- **Share links**: publish a read-only report protected by password and IP allowlist for a client or management.
- **BI connectors**: three CSV streams (`sfr_` API key) for Power BI, Tableau, Excel, Metabase.

## Notifications

**Settings → Notifications**: **channels** (JSON webhook or **email**, up to 20 recipients) and **rules** binding events to them: player offline (scheduled standby does not ring; a fleet not awake after opening does), feed error, failed OTA deployment, campaigns (started/ended/under-served), validations (submitted/approved/rejected/changes). A test-send button on every channel.

## AI assistant and Jeanine

The **assistant** (bottom-right button or **Ctrl+Shift+A**) knows your account and this documentation, and answers in your language.

- **Reading**: players (status, why a screen is off), playlists ("who plays it"), sites and **opening hours**, schedules, media (proven airtime, never played), campaigns (status, report), HDMI sessions, alerts.
- **Actions**: it **prepares** (never executes alone) — add/remove playlist media, create a playlist/feed/event/schedule, restart players, screenshot, screen on/off, HDMI switch, VOD, timezone, file media into folders, **OTA player updates** (latest stable version). You confirm with a button; sensitive actions are org-admin only.
- **Jeanine (Telegram)**: the same assistant over messaging. Link your account from **Profile → Messaging card** (`/link CODE` to the bot); the org-admin manages linked accounts in Settings → Messaging. Sensitive actions (reboot, screen off, schedule deletion, OTA…) require your **6-digit PIN code** (set in your profile; one action, 2 minutes, locked after 3 errors, message erased from the thread — never spoken aloud).
- **Voice**: send a voice message (≤ 2 min) — transcription in your profile language, text reply + voice note (fal.ai and ElevenLabs keys required).
- Costs: the assistant uses **your organization's AI keys** and respects its quota.

## Player updates (OTA)

**Settings → Updates** drives remote updates for every player type. **No automatic update without your approval.**

- **Inventory**: current vs latest version **per platform**, combined filters (OS, version, state, site, group).
- **Catalog**: your published versions (SemVer, channel, platform).
- **Import a version** (Linux/RPi/Windows/Android): by **URL** or by **file** (.tar.gz/.apk) — platform and version are **auto-detected**, with a preview before confirming; the archive is stored on your server, players download it from there.
- **Served versions** (BrightSign/ChromeOS): these players get their code **with the server update**; **declare** the served version to make it deployable. **Pinning**: updating the server does **not** advance a player until you deploy the version to it — ideal for testing on a sandbox before the fleet.
- **Recommended flow**: publish as **Beta** (invisible to the fleet) → deploy to a test group → **Promote to stable** → roll out widely.
- **Deployment**: version + targets (player, group, site, tags, org) + strategy (immediate, gradual, scheduled) + **time windows** (download / install in local time — no reboot in the middle of the day). Per-player tracking (downloading → staged → installing → success/failure), progress ring, pause/resume/cancel. An offline player applies on return.
- **Via the assistant**: "update the players" offers the latest stable of each platform to outdated players (org-admin; PIN over Telegram).

## Screens and power

Vitrail turns your screens on and off according to the **site's opening hours** — the player stays on, only the screen is driven.

1. Fill in the site's hours (with exceptions and public holidays) and enable **auto-power** (optional lead/lag margins).
2. On each player: **Follow site hours** (recommended), custom window, always on, or manual.
3. Driving method depends on equipment: **RS232/IP** controller (professional screens), **HDMI-CEC**, or the **video-output cut** fallback (the screen goes to standby).

Each player knows its power windows **14 days ahead**: if the server is unreachable, it drives its screen on its own. A player switched off by the program is marked **"Scheduled standby"** — no alert; if it has not come back after opening time, an alert fires. The drawer's On/Off buttons are one-off; an event can "keep screens on".

## Server and encoding times

Every uploaded video is **re-encoded** so that every screen can play it — by far the heaviest task the server performs. The **Settings → Server** page tells you why it takes the time it takes.

**Encoding capacity** — the line that explains almost everything: **hardware acceleration active** or not. With no usable graphics card, encoding runs on the CPU and is far slower. **Measured throughput** = the speeds actually observed on your own files. **Work disk** = free space where the worker writes its temporary files.

> **“No media worker is responding”** is not a display detail: no encode can complete. This information comes from the **worker**, not from the web server — when it goes silent, the page says so instead of showing stale values.

**Before starting an encode, the server measures**: it encodes about ten seconds of **your** file with the exact command that will be used, then extrapolates. Three cases: **under 20 min**, it starts on its own · **20 min to 4 h**, you decide and the media waits as **Decision required** · **over 4 h**, it is refused by default, an administrator being able to override. A refusal is not a dead end: the screen offers to encode at a **lower resolution**, each with its own estimate.

This page is reserved for the **licence holder**. If your server is run by a provider, the screen tells you so: capacity and queue are part of their operations, your content is processed normally.

## Users, roles and security

**Built-in roles** — this list contains only the rights the server **actually enforces**:

- **Organization admin**: everything, within their organization.
- **Designer**: media and templates (create/edit/delete), playlists (create/edit).
- **Scheduler**: schedules, events and VOD (create/edit/trigger); read players, playlists, media.
- **Campaign manager**: campaigns end to end (create, publish, reports); read media, templates, reports.
- **Approver**: review, approve or reject requests; read media, playlists, templates.
- **Report viewer**: reports, read only.
- **Store operator**: control their store's audio baskets.
- **Governance manager**: configure the governance hierarchy (nodes, delegations); read content.
- **Governance editor**: compose the content of their node (playlists, media, feeds) and submit it for approval; **deletes no media**.
- **Governance approver**: decide on the approval requests of their scope; **never their own submission**, and only from a node above.
- **Site programmer**: schedule playback for the **nodes they administer** (their scope comes from their node assignment, not the permission alone).
- **Viewer**: read-only across the board.
- **Advertiser (portal)**: their own campaigns and reports, from the portal.

> **Menus adapt to the role**: anything a user cannot use is hidden. A missing menu means a missing read permission, not a fault.

> The **API user** and **Player** roles grant nothing and are no longer offered: integrations use **API keys**, players use a **machine token**.

> **Custom role**: create it, then **click its row** to tick its permissions. System roles are read-only; permissions greyed out as coming soon belong to features not built yet.

- **Settings → Users & Roles**: users, **groups** (group roles add to the account's own; scoped org/site/player group) and **custom roles** made of atomic `module : operation` permissions (see the list above).
- Deleting a user is a **deactivation** (the email stays reserved); deleting an advertiser account unlinks it from the portal.
- **2FA (TOTP)**: per-user, enforced for administrators.
- **API keys**: BI exports (`sfr_`), campaign import (`sfi_`) — value shown once, revocable.
- **Settings → Security**: session policy, login attempts.
- Every sensitive action is traced in the **audit log**.

## Profile and preferences

**Settings → Profile**: name, email, password, **interface language** (French, English, Spanish, Portuguese, German — the assistant and emails follow), light/dark theme (top-bar button), 2FA, **Messaging — Telegram card** (Jeanine link + the sensitive-actions **PIN code**), re-enabling help bubbles.

## Quick troubleshooting

- **Player offline**: check power, network, server URL. Outside opening hours, "Scheduled standby" is normal (auto-power switched the screen off; some boxes also cut their network).
- **"No Signal Detected"**: the plugged HDMI source emits nothing (off, unplugged) — the image returns by itself when the signal is back.
- **"Media unavailable"**: player not up to date for this content type, or server transcoding not finished.
- **Black/frozen screen**: check transcoding; on a synchronized wall, keep the group homogeneous; "On-screen info" shows the diagnostic on site.
- **No sound**: check the player's audio role (standard / audio only / mixed), the pushed volume and mute.
- **Content not updating**: player online? Does the schedule really target this player/group? Any change normally pushes an immediate sync.
- **Offline**: native players play their content locally (playlists, videos, cached feeds) even with the server down; the Chrome extension depends more on the network.

> Need more? Ask the assistant (Ctrl+Shift+A) — it knows this manual and the state of your account.
