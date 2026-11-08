---
title: Turning screens on and off (auto-power)
section: players
roles: [CMS_ORG_ADMIN]
keywords: [screen, power, power on, power off, opening hours, auto-power, standby, RS232, CEC, shutdown, wake up, schedule, closing, energy, offline, allumage, extinction, heures d'ouverture]
---

# Turning screens on and off (auto-power)

Vitrail can **turn your screens on and off automatically** according to the site's opening
hours: no more screens left on all night, no more forgetting to turn them back on in the morning. The player
itself stays powered on and connected — only the screen is controlled.

## How to enable it

1. Fill in the site's **opening hours** (Sites → your site): days, hours,
   exceptions by date (public holidays, events).
2. Enable the site's **auto-power**, with optional **margins**: turn on a little before
   opening (lead) and turn off a little after closing (lag).
3. On each player (drawer → Display), choose the **power mode**:
   - **Follow the site's opening hours** (recommended);
   - **Custom window**: the player's own hours (e.g. shop window lit later) —
     without the site's margins;
   - **Always on**; or **Manual** (no automatic control).

## How the screen is controlled

Depending on the equipment, the player uses (in this order of preference):
- an RS232 or IP **display controller** (professional screens);
- **HDMI-CEC** (compatible TVs);
- failing that, the **"video output" fallback**: the player cuts its video signal and the screen goes
  into standby (to be enabled in the player's display configuration). Works on Linux,
  Raspberry Pi, Windows, Android and BrightSign.

## It also works without a server (offline)

Each player receives its **power windows for 14 days** in advance (site local
time, margins and exceptions included). If the server is unreachable for more than a few minutes,
the player **controls its screen by itself**; on reconnection, the desired state is re-applied
automatically. A player that restarts during an outage also recovers its windows.

## Manual command and exceptions

- The **Turn screen on / Turn screen off** buttons of the player drawer are **one-off**: the
  schedule takes over again at the next time slot. For a lasting shutdown, switch the player
  to **Manual** mode.
- An **event** can tick "Keep screens on" to maintain the display during
  an exceptional broadcast outside opening hours.

## Alerts: the night no longer rings

A player whose screen is turned off by the schedule may appear **offline** (some
devices, such as Android boxes, also cut their network in standby). In this case it is
marked **"Scheduled standby"** — no alert, no critical status. However, if a
player has **not come back** a few minutes after opening time, a "fleet not
woken up" alert is raised.
