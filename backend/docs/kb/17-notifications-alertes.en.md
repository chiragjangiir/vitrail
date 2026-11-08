---
title: Notifications and alerts
section: settings
roles: [CMS_ORG_ADMIN]
keywords: [notification, alert, webhook, email, channel, rule, player offline, feed error, failed deployment, campaign, approval, threshold, alerte, canal, règle]
---

# Notifications and alerts

**Settings → Notifications**: Vitrail pushes alerts to your tools when an
important event occurs. A **channel** defines *where* to send; a **rule** defines
*what* to send and under which conditions.

## Channels

- **Webhook**: JSON POST to the URL of your choice (Slack, Teams, n8n, monitoring…).
- **Email**: up to 20 recipients per channel — all alerts can be sent
  by email (the platform's SMTP server is used).

## Available events

- **Player offline**: a player no longer responds (shutdowns scheduled by
  auto-power are recognized — "scheduled standby" does **not** trigger an alert;
  a fleet not woken up after opening time does).
- **Feed error**: a news source no longer responds (with automatic recovery).
- **Failed deployment**: an OTA update failed on some players.
- **Campaigns**: started, ended (summary), **under-delivered** (SOV delivered below a threshold of the
  sold SOV — 80 % by default, adjustable per rule).
- **Approvals**: request submitted, approved, rejected, changes requested.

## Rules

Each rule links events to a channel, with its parameters (thresholds, delays).
Test a channel with the test-send button before relying on it.
