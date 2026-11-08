---
title: Getting started with Vitrail
section: getting-started
roles: []
keywords: [getting started, onboarding, first steps, dashboard, organization, roles, démarrage, prise en main]
---

# Getting started with Vitrail

Vitrail is a digital signage platform: you broadcast content (videos, images, web
pages, news feeds) on screens driven by players, from a centralized web
interface.

## The key concepts

- **Organization**: your workspace. All your content, players and users are isolated
  within it (no other organization can see your data).
- **Player**: the software installed on the device connected to a screen (NUC, Raspberry Pi,
  Windows PC, Android box, Chromebox, or a simple Chrome extension). It receives its
  instructions from the server — never the other way round — and keeps working offline.
- **Media**: imported content (video, image, document) or dynamic content (web page, feed).
- **Playlist**: a sequence of media played in a loop.
- **Schedule**: when and on which players a playlist is broadcast.
- **Event**: a one-off or triggered broadcast that takes priority over the normal
  schedule (promotion, announcement, hourly spot).

## The typical journey

1. **Enroll a player**: generate a provisioning token, install the player on the
   device, and it appears in the Players list.
2. **Import content** into Media.
3. **Create a playlist** with that content.
4. **Schedule** the playlist on one or more players.

The screen displays the content within a few seconds once the schedule is saved.

## Roles and permissions

Vitrail manages roles (Org Admin, Designer, Scheduler, Approver, Report
Viewer, Store Operator…). Each role grants access to a subset of modules.
If a menu or an action is missing, it is probably a matter of role:
ask your organization administrator to assign it to you.
