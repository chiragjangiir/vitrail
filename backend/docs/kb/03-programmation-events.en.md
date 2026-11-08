---
title: Scheduling and events
section: scheduling
roles: [CMS_ORG_ADMIN, CMS_SCHEDULER]
keywords: [scheduling, schedule, planning, timetable, time slot, event, broadcast, priority, spot, trigger, calendar, filter, target, export, programmation, horaire]
---

# Scheduling and events

## The unified calendar

The **Scheduling** page shows a calendar (week and month views) that overlays everything
that broadcasts: **visual schedules**, **audio schedules**, **events** and
**Retail Media campaigns**. A four-family legend (distinct icons: lightning =
event, megaphone = campaign, note = audio) helps tell them apart.

- **Type filter**: the "All / Visual / Audio / Events / Campaigns" pills
  restrict the display to one family.
- **Target filter**: the "All targets" button opens a search by
  **site group, site or player** — the calendar then only shows what actually
  affects that target (resolution uses the same engine as the broadcast).
- **CSV export**: the Export button downloads exactly what is displayed, filters
  included (type of each row, content, days, time slot, validity).
- The type of a new schedule (visual or audio) is chosen **in the creation
  form** ("Program type").

## Schedule a playlist

A **schedule** says *what* to broadcast, *where* (which players or groups) and
*when* (time ranges, days, dates).

1. Go to **Scheduling** and create a rule.
2. Choose the playlist, the targets (players or groups), and the time window.
3. Save: the affected players update within a few seconds.

If a playlist uses a template whose resolution does not match the target screen,
a warning is displayed at assignment.

## Events: priority broadcasts

An **event** temporarily takes priority over the normal schedule. Useful for a
promotion, an announcement, or a message triggered by a sensor or a condition.

- An event can broadcast **a playlist** or **a single media**.
- It has an activity window; at the end, the player automatically returns to its
  normal schedule.
- Targets can **mix types** within the same event: "this site" **plus**
  "these 3 screens" **plus** "this group", as campaigns do. Selections
  made under different types add up — the event targets their union, and the
  form summary names everything that is selected. Choosing "Entire
  organization", on the other hand, replaces all other selections.

### Event (re)activated mid-window: switchover may be delayed

Players never broadcast a media they have not finished downloading (no black
screen): an event **(re)activated mid-window** with a media never distributed can
therefore take **a few minutes** to appear on players downloading large
files (4K) — they continue their schedule then switch as soon as the file is ready.
Activate or plan the event **in advance**: pre-loading distributes the media before
the time and the switchover is instant. Once the media is cached (recurring event), the
following occurrences switch without delay.

### Hourly spot (scheduled "play once" event)

To have a message play at regular intervals (for example once every 30 minutes)
rather than in a continuous loop, create a **Scheduled** event with the **"Play
once"** option. The hourly spot recurrence field only appears in this combination
(scheduled event + play once). The player then plays the spot once per time slot, then
waits for the next slot.

## Synchronization between screens (LAN Sync)

Several players on the same local network can play a video synchronized frame
by frame (video wall, consistent ambiance). Synchronization is reliable when the
players of the group are **homogeneous** (same hardware and same configuration). Mixing very
different devices within the same synchronized group can cause offsets.
