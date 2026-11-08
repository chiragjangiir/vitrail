---
title: AI assistant and Jeanine (Telegram)
section: assistant
roles: []
keywords: [assistant, AI, chat, widget, Jeanine, Telegram, messaging, actions, confirmation, PIN, voice, voice message, read, intents, link, linking code, quota, BYOK, assistant OTA, IA, messagerie]
---

# AI assistant and Jeanine (Telegram)

Vitrail includes a **conversational assistant** that knows your account: it answers
about your live data, explains the product (this documentation), and can **prepare
actions** that you confirm. It comes in two forms: the **widget** in the CMS
(button at the bottom right or **Ctrl+Shift+A**) and **Jeanine**, the same assistant over
**Telegram**.

## What it can answer (read)

Players (status, disconnected, content up to date, why a screen is off),
playlists (content, duration, "who plays it"), **sites and opening hours** ("is site
X open on Sunday?"), schedules and targets, media (unclassified, never
played, proven air time), retail media campaigns (status, report), HDMI
sessions, alerts. It answers **in the language of your profile**.

## Actions (always confirmed)

The assistant **never** changes anything directly: it **prepares** the action (resolves
names, checks your permissions) and you **confirm** it with a button (widget) or a
"YES" (Telegram). Examples: add/remove a media item from a playlist, create a
playlist / a feed / an event / a schedule, restart players, take a
screenshot, turn a screen on/off, switch an HDMI input, start a VOD, set a
time zone, file media into a folder, **update the players' software (OTA,
latest stable version)**… Sensitive actions are reserved to the org-admin.

## Jeanine on Telegram

1. **Profile → "Messaging — Telegram" card**: generate your linking code and
   send `/link VOTRECODE` to the bot (direct link provided).
2. The org-admin sees and revokes linked accounts in **Settings → Messaging**.
3. Talk to it as you would to the widget: same answers, same actions, same permissions.
   Without a linked account, the bot does not answer (no cost).

### PIN code (sensitive actions)

Over messaging, a "YES" is not enough for risky actions (reboot, screen
shutdown, schedule deletion, time zone change, **OTA update**…): Jeanine
asks for your **6-digit PIN code**. Set it in **Profile → Messaging card**.
The code is valid for one action, expires after 2 minutes, locks for 15 minutes after 3 errors,
and your message is deleted from the thread. The PIN is typed **on the keyboard, never by voice**.

### Voice messages

Send a **voice message** (≤ 2 min): Jeanine transcribes it (in the language of your
profile), shows what she understood ("🎤 …"), and replies in text **and as a voice note**.
Requires the organization's AI keys (fal.ai for transcription, ElevenLabs for the
voice — Settings → AI Keys).

## Costs and quotas

The assistant uses **your organization's AI keys** (BYOK) and respects the configured AI
quota. Widget and Telegram share the same guards; an unlinked Telegram account
triggers no call.
