---
title: Roles and permissions — who can do what
section: iam
roles: []
keywords: [roles, permissions, rights, RBAC, IAM, users, groups, custom role, super-admin, org-admin, designer, scheduler, approver, campaigns, viewer, advertiser, store operator, 403, access denied, missing menu, delegate, rôles, droits]
---

# Roles and permissions — who can do what

Vitrail grants rights through **atomic permissions** of the form
`module:opération` (e.g. `media:create`, `schedules:read`). A **role** is a
bundle of permissions; a user holds one or more roles, directly
or **via a group** — the two add up.

## The two administration roles

| Role | Scope |
|---|---|
| **Super Administrator** (`CMS_SUPER_ADMIN`) | A **platform** account, not a business one: it creates organizations, manages the firmware catalog and the knowledge base. It sees no organization content. |
| **Organization Administrator** (`CMS_ORG_ADMIN`) | All rights **within their organization**. They create accounts, assign roles and build custom roles. |

An organization administrator **cannot** grant themselves the super
administrator role, nor grant it to anyone, nor copy it: the API refuses
("Role not assignable" / "Platform role not copyable"). This prohibition
covers direct assignment **and** going through a group.

## Business roles

This table lists only the rights **actually enforced by the server**: it is
**generated** from the database and the code (`scripts/gen_role_matrix.py`), never written by hand.
A permission that is held but checked nowhere grants nothing, and therefore has no place
here. Last regeneration: **2026-08-05** — 87 permissions in the catalog, **67 actually
checked**.

| Module | ADVERTISER | APPROVER | CAMPAIGN MGR | DESIGNER | GOV. APPROVER | GOV. EDITOR | GOV. DIRECTOR | REPORT VIEWER | SCHEDULER | SITE PROGR. | STORE OPER. | VIEWER |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `approvals` | submit | approve, reject, review | submit | — | approve, reject, review | submit | — | — | — | submit | — | — |
| `audio_baskets` | — | — | — | — | — | — | — | — | — | — | control, read | — |
| `campaigns` | read, report | — | create, delete, edit, publish, read, report | — | — | — | — | — | — | — | — | read |
| `events` | — | — | — | — | — | — | — | — | create, delete, edit, read, trigger | — | — | read |
| `feeds` | — | read | read | create, delete, edit, read | read | edit, read | read | — | read | read | — | read |
| `generation` | — | read | read | create, read | read | read | read | — | read | read | — | read |
| `governance` | — | — | — | — | read | read | delegate, edit, read | — | — | read | — | — |
| `media` | — | read | read | create, delete, edit, read | read | edit, read | read | — | read | read | — | read |
| `players` | — | — | read | — | — | — | read | — | read | read | — | read |
| `playlists` | — | read | — | create, edit, read | read | create, edit, read | read | — | read | create, edit, read | — | read |
| `reports` | — | — | export, read | — | — | — | — | export, read | — | — | — | read |
| `schedules` | — | — | — | — | read | — | read | — | create, delete, edit, read | create, delete, edit, read | — | read |
| `tags` | — | read | read | edit, read | read | edit, read | read | — | read | read | — | read |
| `templates` | — | — | read | create, delete, edit, read | — | — | — | — | read | — | — | read |
| `url_display` | — | read | read | create, delete, edit, read | read | edit, read | read | — | read | read | — | read |
| `users` | — | — | read | — | — | — | — | — | — | — | — | — |
| `vod` | — | — | — | — | — | — | — | — | create, delete, edit, read, trigger | — | — | read |

**Two roles grant nothing** and need not be assigned: *API User*
(`CMS_API_USER`) and *Player* (`CMS_PLAYER`). Integrations go through
**API keys** with their own scopes (`sfk_`, `sfr_`, `sfi_`) and players
through a **machine token**. They no longer appear in the interface lists.

## Governance roles (§XVIII)

**Four** roles drive **hierarchical governance** (organization → nodes → sites /
players). 🔑 What sets them apart from ordinary roles is not the list of their
permissions but their **scope**: they act only within the **subtree they
administer**, and non-governed content is **invisible to them for writing**. A
`schedules:*` without a node assignment therefore gives nothing to schedule.

- **Governance manager** (`CMS_GOVERNANCE_MANAGER`) — configures the **hierarchy**:
  `governance:read / edit / delegate` (read, edit nodes, delegate), plus read access to
  media, playlists, players and schedules to do the work. They **structure and delegate**, they do not
  publish themselves.
- **Site programmer** (`CMS_SITE_PROGRAMMER`) — **schedules playback**: full control
  of schedules (`schedules:create / edit / delete / read`) + read (media, playlists,
  players, `governance:read`). ⚠️ **Their scope does NOT come from the permission alone**: they can
  schedule only the **nodes they administer** (governance assignment). A
  `schedules:*` **without a node assignment** gives them no site to schedule.
- **Governance editor** (`CMS_GOVERNANCE_EDITOR`) — composes the **content** of their node
  (playlists, media, feeds, tags) and **submits** it for approval. ⛔ They do **not** have
  `media:delete`: a local editor does not delete a media item that headquarters uploaded.
- **Governance approver** (`CMS_GOVERNANCE_APPROVER`) — **decides** on approval requests
  within their scope (`approvals:approve / reject / review`). ⚠️ They cannot
  approve **their own** submission, and they must administer a **strict ancestor**
  node of the submitter's — otherwise a store would approve itself.

## The interface adapts to the role

Since July 2026, menus and action buttons that **cannot be used are
hidden**: an approver sees neither Players, nor Scheduling, nor Campaigns.
This is a display convenience — authorization remains **entirely server-side**.
If a user says "the menu has disappeared", it is not a malfunction: they
lack the corresponding read right.

## Creating a custom role

Settings → **Users & Roles** → *Roles* tab → **Create role**, then
**click on the role's row** to tick its permissions, grouped by
module.

Two points to know:

- a **system** role is shared by all organizations: its permissions
  are **read-only**;
- you can only grant rights you hold yourself — a delegate cannot
  build a role more powerful than themselves.

Some permissions appear **greyed out, marked "coming soon"**: they
correspond to features that are specified but not yet developed (the
SPF interactive presentation engine). Ticking them would have no effect, so
the interface forbids it.

## Delegating account management

User and group management relies on `users:*` and `groups:*`.
A custom role carrying `users:read` + `users:create` + `users:edit` therefore
lets you entrust account administration **without** giving all the
organization administrator rights. The organization administrator always
retains access, whatever the setting.

## "Access denied": where to look

1. **Which right does the action require?** The error message names it:
   "Permission denied: `media:create`".
2. **Does the user hold it?** Settings → Users & Roles → their
   account → their roles; then the role's row to see its permissions.
3. **Watch out for groups**: a right can come from a group rather than the account.
4. **A role marked "deny"** (`is_deny`) cancels the same role obtained
   elsewhere.

## Regenerating this table

The matrix above is **generated from the database and the code**, never written
by hand:

```bash
docker compose exec -T backend python scripts/gen_role_matrix.py
```

The script cross-references what a role *holds* (database) with what is *actually
checked* (code): a permission that is held but checked nowhere grants nothing,
and the table must never suggest otherwise.
