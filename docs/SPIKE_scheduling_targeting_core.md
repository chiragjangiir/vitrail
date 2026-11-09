# SPIKE — Scheduling & Targeting core (customer feedback block, item 1)

🇫🇷 [Version française](SPIKE_scheduling_targeting_core.fr.md)

> **Goal of the spike**: move from the conceptual framing (« Médiathèque & Programmation », items 3+4) to a **technical design ready to code**. Check that the core (a) TZ-aware rule evaluation + (b) target resolution **fits together** with the three consumers: item-rules (item 4), Governance §XVIII Phase 2, Retail Media (Phase 3).
>
> **Spike verdict: GO.** The core is small, the three consumers fit into it cleanly, and the friction points (divergent target vocabulary, overnight windows, multi-TZ) are identified and settled below. Date: 2026-06-03.

---

## 1. Inventory of the existing code (what we factor out)

### 1.1 Time rule evaluation — **duplicated 2×, partial**

| Location | Form |
|---|---|
| `ws.py::_rule_matches(rule, now)` (l.173) | `always/weekly/date_range` logic, explicit comment "duplicated to avoid the circular dependency" |
| `schedules.py` (rule preview) | same logic, copy |
| `ws.py::_build_basket_items` (l.205) | validity window of basket items — **yet another** ad hoc time comparison |

Common vocabulary = `cms_schedule_rules`: `rule_type ∈ {always, weekly, date_range}`, `days_of_week` (0=Mon…6=Sun = `datetime.weekday()`), `time_start/time_end`, `date_from/date_to`. Current time via `ws.py::_local_now()` → `SIGNFLOW_TZ`, **naive datetime**.

**Latent bug confirmed**: none of the copies handles an **overnight window** (`time_start > time_end`, e.g. 22:00→02:00). The logic `current_time < time_start → False` excludes the whole evening interval. To be fixed **in the core** (a single place).

### 1.2 Target resolution — **3 divergent vocabularies**

| Consumer | Storage | `target_type` | Resolver |
|---|---|---|---|
| Schedules | `cms_schedule_targets` (table) | `player` \| **`player_group`** | inline `ws.py::_resolve_sync_payload` (l.775-793): direct player + via `CmsPlayerGroupMember` |
| Events | `cms_events.target_config` (JSONB) | `org` \| `player` \| **`group`** | inline `ws.py` (l.753-768) |
| Governance | `cms_governance_assignments` (table) | `player` \| **`group`** \| **`site`** | `governance.py::node_players` (l.233): player + group + site → `set[int]` |
| Tags §XVII | `cms_player_tag_filters` | — (**reception** axis, not targeting) | `ws.py::_filter_items_by_tags` (l.105): filters **per item**, not target resolution |

→ Three words for "group" (`player_group`/`group`), a single rich resolver (governance, which already does player+group+site but **not tags**). **None of them resolves a tag expression.**

### 1.3 No timezone column

Neither `cms_players` nor `cms_sites` has a TZ → today everything is global `SIGNFLOW_TZ`. The core must be **parameterized by TZ** (default `SIGNFLOW_TZ`) with a forward-compatible `site.timezone` hook (multi-country = later, out of the spike's scope).

---

## 2. Core design

Two pure services, with no DB I/O in the **logic** (unit-testable), + thin **loading** functions on the endpoint side.

### 2.1 `services/scheduling.py` — TZ-aware rule evaluation

```python
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from app.core.config import settings

@dataclass(frozen=True)
class TimeRule:
    """Règle temporelle normalisée — découplée de l'ORM (schedule OU item-rule)."""
    rule_type: str               # always | weekly | date_range
    days_of_week: list[int] | None = None   # 0=Lun … 6=Dim
    time_start: time | None = None
    time_end: time | None = None
    date_from: date | None = None
    date_to: date | None = None

def local_now(tz_name: str | None = None) -> datetime:
    """Instant courant en heure locale (naïf). Défaut SIGNFLOW_TZ. Repli UTC si TZ inconnue."""
    ...

def rule_active_at(rule: TimeRule, now_local: datetime) -> bool:
    """Vrai si `now_local` (déjà en TZ cible) tombe dans la règle.
    Gère les fenêtres OVERNIGHT (time_start > time_end → l'intervalle enjambe minuit)."""
    ...

def rules_active_at(rules: list[TimeRule], now_local: datetime) -> bool:
    """OR sur une liste de règles (un schedule/item a N règles, actif si l'une matche)."""
    return any(rule_active_at(r, now_local) for r in rules)
```

Overnight rule (the fix): if `time_start` and `time_end` are set **and** `time_start > time_end`, the slot is `[time_start, 24h[ ∪ [0h, time_end]`. For `weekly` with overnight, `days_of_week` designates the **start** day of the slot (decision: simple and sufficient for the "bar open 10pm-2am" case).

ORM adapters (in the module, not in the pure logic):
```python
def time_rule_from_schedule(r: CmsScheduleRule) -> TimeRule: ...
def time_rule_from_item_rule(r: CmsPlaylistItemRule) -> TimeRule: ...
```

`ws.py::_rule_matches` and the `schedules.py` preview become calls to `rule_active_at(time_rule_from_schedule(r), now)`. **The duplication disappears.**

### 2.2 `services/targeting.py` — extended target resolution

Single canonical vocabulary: **`player | group | site | tags`** (+ `org` = sugar = the whole org).

```python
@dataclass(frozen=True)
class Target:
    target_type: str            # player | group | site | tags | org
    target_id: int | None = None        # player/group/site
    tag_expr: dict | None = None         # pour 'tags' : {namespace_key: [values], ...} (AND inter-ns, OR intra-ns)

async def players_for_target(db, id_org: int, target: Target) -> set[int]:
    """Étend une cible en ensemble d'id_player. Réutilise la logique governance.node_players."""

async def player_matches_target(db, id_org: int, id_player: int, target: Target) -> bool:
    """Sens inverse (le chemin chaud de ws.py : 'ce player est-il visé ?').
    Évite de matérialiser tout l'org pour 'org'/'tags'. Cache les groupes/site/tags du player."""
```

- `group` also accepts the alias **`player_group`** (compatibility with the existing `cms_schedule_targets` — **zero data migration**, the resolver normalizes).
- `tags` reuses the **reverse mechanism** of `_filter_items_by_tags` but applied to the **player's tag profile** (the `cms_player_tag_filters` + inherited tags) vs a target `tag_expr`. ⚠️ Semantics NOT to be confused:
  - **Current §XVII tags = reception filter** ("this player only accepts items `lang=fr`").
  - **Tags as a target (new) = audience selection** ("this campaign targets players tagged `region=PACA`").
  - Both read the same taxonomy but answer two questions. The core exposes a shared `player_has_tags(db, id_player, tag_expr)`.

`players_for_target` for `group/site` = direct extraction of `governance.node_players` (to be moved/shared — governance will import it instead of the reverse).

---

## 3. Item 4 — `cms_playlist_item_rules` (the 1st consumer)

### 3.1 Model (migration 0029)

```
cms_playlist_item_rules
  id_item_rule   BIGSERIAL PK
  id_item        BIGINT FK cms_playlist_items(id_item) ON DELETE CASCADE, INDEX
  scope          VARCHAR(20) NOT NULL DEFAULT 'default'   -- default | player | player_group
  target_id      BIGINT NULL              -- player/group selon scope ; NULL si default
  -- 6 champs miroir de cms_schedule_rules :
  rule_type      VARCHAR(20) NOT NULL DEFAULT 'weekly'
  days_of_week   INT[] NULL
  time_start     TIME NULL
  time_end       TIME NULL
  date_from      DATE NULL
  date_to        DATE NULL
  created_at     TIMESTAMPTZ DEFAULT now()
```

`scope` deliberately stays `default|player|player_group` (and **not** `site/tags`) in P1/P2: an item-rule is a local exception at the level of a playlist, rich targeting (site/tags) lives at the schedule/campaign level. (If needed later, the core's `Target` is already ready.)

### 3.2 Resolution algorithm (in `ws.py`, where we already filter by tags)

Location: **after** `_filter_items_by_tags` (l.943), **before** the wall-clock (l.945) — same logical layer ("which items this player sees now").

```
pour chaque item retenu :
    rules = item_rules[id_item]
    si rules vide            → item PERPÉTUEL, gardé
    sinon :
        # jeu le plus spécifique présent : player > player_group(du player) > default
        pertinents = rules where scope match le player, par spécificité décroissante
        groupe = premier niveau de spécificité non vide
        gardé SSI rules_active_at(groupe, local_now())   # heure LOCALE
```

(In English: for each retained item, if it has no rules it is PERPETUAL and kept; otherwise take the most specific rule set present — player > player_group (of the player) > default — and keep the item IF AND ONLY IF `rules_active_at(that set, local_now())`, in LOCAL time.)

"The most specific wins" = if a `player` rule exists for this item+player, it **replaces** the `default` rules (override, not union). Otherwise `player_group`, otherwise `default`.

**P1** = only `scope=default` (recurrence + validity; covers ~90%: "this item only plays Sat/Sun 9am-6pm"). **P2** = `player`/`player_group` override. The model already carries `scope` from P1 → P2 = a pure addition of UI + one resolution branch.

### 3.3 The 3 time primitives stay distinct (to make explicit in the UI)

| Primitive | Semantics | Storage | Exists? |
|---|---|---|---|
| **Embargo** | **absolute UTC** instant (synchronized global launch) | `cms_media.not_before_utc` / `embargo_event_id` | ✅ |
| **Per-item rule** | **local time** wall-clock (recurring window of an item) | `cms_playlist_item_rules` | 🆕 item 4 |
| **Schedule** | local-time dayparting (program→players) | `cms_schedule_rules` | ✅ |

Embargo = `effective_embargo > now_utc` (l.916, **unchanged**, UTC comparison). Per-item rule = `rule_active_at(..., local_now())` (**local**). **Never** merge these two comparisons.

---

## 4. Fit with Governance §XVIII Phase 2 (the key check of the spike)

The Phase 2 engine = **multi-layer compiled schedule**: for a player, stack the layers that target it (per governance node), resolve budgets/preemption, produce the effective program. The spike's question: **does the core support it without duplication?**

**Yes.** Breakdown:

1. **"which layers target this player"** = `targeting.player_matches_target` applied to the assignments of each node in the subtree. → core (b).
2. **"is this layer active now"** = `scheduling.rules_active_at` on the layer's window (`cms_delegation_rules` of type `time_window` already carry `time_start/end`; to be expressed as `TimeRule`). → core (a).
3. **budgets / preemption / position-lock** = **governance-specific delta** (NOT in the core): `time_budget`/`item_count`/`frequency_cap` counters, priority bands, per-layer immutability. The core provides the **predicates** (who + when), governance provides the **arbitration** (how much + who wins).

→ **Mental model validated**: *governance IS the layer engine; an item-rule is a degenerate layer (1 playlist, 1 window, no budget); a schedule is a layer; a Retail Media campaign is a layer + monetization.* All consume the same two predicates. The core is the right boundary.

**Ordering consequence**: doing core (3) + item-rules (4) **before** Sprint 2.7 genuinely de-risks the big sprint — Phase 2 will only have to write the arbitration (budgets/preemption), not the who/when resolution.

---

## 5. Retail Media reuse (Phase 3) — confirmation

A campaign = `Target` (where) + `list[TimeRule]` (`date_range` flight + `weekly` dayparts) + creative (media). **100% of the "where + when" = the core.** The Retail Media delta (NOT to be confused with reuse): Share-of-Voice/rotation/frequency (a % **insertion** engine, not on/off), inventory/booking/anti-overselling, advertiser+billing+Merkle PoP (`cms_proof_of_play` ✅), creative validation (Approval §XXI ✅), pacing. Tables `cms_campaigns/_creatives/_targets` already mirror schedule_targets. → by freezing the canonical `Target` now, `cms_campaign_targets` aligns with it "for free".

---

## 6. Implementation plan (post-spike)

| Step | Content | Migration | Tests |
|---|---|---|---|
| **N1** ✅ | `services/scheduling.py` (TimeRule + `rule_active_at` **with overnight** + adapters). Re-wired `ws._rule_matches` + `schedules._rule_matches` + `ws._local_now`. **Bonus**: `current-schedule` fixed (naive UTC → `local_now()`). | — | ✅ 11 pure tests (always/weekly/date_range/**overnight**/inclusive bounds) |
| **N2** ✅ | `services/targeting.py` (`Target`, `players_for_target(s)`, `player_matches_target`, `player_has_tags`). Re-wired `governance.node_players` + `schedules._resolve_player_ids`. Alias `player_group`→`group` (zero migration). | — | ✅ 8 tests (player/group/site/tags/org, alias, org guard, reverse direction) |

> **N1+N2 delivered on 2026-06-03**: +19 tests, **230 passed**. Remaining: I1 (item-rules P1, migr 0029) → I2.
| **I1** | item-rules **P1**: migration 0029, CRUD `cms_playlist_item_rules` (scope=default), resolution in `ws.py` (after tags, before wall-clock), playlist editor UI ("rule" badge + window/validity drawer), `sync_ready` impacted (a time-boxed item ⇒ variable effective content ⇒ LAN warning). | **0029** | perpetual item kept, out-of-window item removed, embargo≠rule |
| **I2** | item-rules **P2**: `player`/`player_group` override (specificity), per-target override UI. | — | override wins over default, cascading fallback |

**Effort**: N1+N2 = small (factoring + 1 overnight fix + 1 tags resolver). I1 = small sprint. I2 = incremental addition.

---

## 7. Honesty points / decisions to record

1. **LAN sync ↔ divergent rules**: two players of the same wall under different item-rules/targets have **different effective content** on some slots → **not frame-synchronizable** then. OK for separate stores; **to be forbidden/warned on a video wall** (`sync_ready` must raise a warning if a playlist targeting a `lan_sync_group` contains non-`default` item-rules).
2. **UI readability**: two scheduling levels (schedule **and** item) — the editor must make the **intersection** readable ("this item plays Sat/Sun 9am-6pm, **within** the morning program").
3. **Target vocabulary**: we **keep** `cms_schedule_targets.target_type='player_group'` in the database (zero migration), the core normalizes via alias. Recorded.
4. **Multi-TZ**: out of the spike's scope. Core parameterized by TZ (default `SIGNFLOW_TZ`), `site.timezone` hook to wire in the day multi-country arrives, without touching the logic.
5. **Overnight `weekly`**: `days_of_week` = **start** day of the slot (the slot may spill into the next day). Recorded (sufficient for the real case).

> **Decision expected before coding**: validate the N1→N2→I1(P1)→I2(P2) sequencing and the overnight convention (point 5). The rest is settled.
