---
title: Time zone and time synchronization (NTP)
section: players
roles: [CMS_ORG_ADMIN]
keywords: [time zone, timezone, time, NTP, clock, synchronization, offset, wrong time, site, chrony, fuseau horaire, heure, horloge]
---

# Time zone and time synchronization (NTP)

All scheduling (playlists, events, screen power) runs in the **site's local
time**. Two settings ensure that players and server agree on the time.

## The site's time zone is the reference

Each site has a **time zone** (Sites → your site). It drives the broadcast
and auto-power hours. When a player is **attached to a site** (or the site's
time zone changes), Vitrail **automatically aligns the player's clock** with that time zone — useful
for a cloned player or one coming from another country.

## View and correct a player's time zone

In the player drawer, **Device** section, the "Time zone" line shows the device's
actual time zone, with a **warning badge if it does not match the site**. You can
change it remotely; the player applies and confirms (green tick when the new value has been
reported back). Platform specifics:
- **Linux / Raspberry Pi / Android**: full list of time zones (e.g. Europe/Paris).
- **Windows**: list of canonical Windows time zones (one per zone — Monaco is displayed for
  example via the Central European time zone).
- **BrightSign**: system-specific labels (e.g. **CET** = equivalent to Europe/Paris, the
  badge recognizes it); the device **restarts** to apply.
- **ChromeOS / Chrome extension**: managed by Google policy / the system, not controllable.

## NTP server per site

So that all players of a site share exactly the same clock (essential for
LAN synchronization between screens), fill in an **NTP server** on the site (IP or host
name — often the site's Vitrail server). Each player applies it automatically:
- Linux / Raspberry Pi: via chrony;
- Windows: via the Windows Time service;
- BrightSign: via its native network configuration.

A player that already has its own NTP configuration (NTP relay of a LAN synchronization
group) keeps it: it takes precedence over the site setting.
