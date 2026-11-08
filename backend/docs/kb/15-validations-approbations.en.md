---
title: Approvals (approval workflow)
section: workflow
roles: []
keywords: [approval, validation, approve, workflow, review, submit, reject, changes requested, resubmit, queue, reviewer, campaign, reason, export, decision email, governed playlist, owner node, governance, moderation, read-only, validation, approbation]
---

# Approvals (approval workflow)

The **Approvals** page (`/approvals`, under Campaigns in the menu) centralizes
**approval requests**: a submitted resource cannot be published until a
reviewer has approved it. The circuit applies to **retail media campaigns**
(submitted from the CMS or by an advertiser from the portal) and to **governed
playlists** (hierarchical governance §XVIII, see "Playlists under moderation"
below).

## The circuit

1. **Submit**: "Submit for approval" button (campaign drawer) or automatic
   submission from the advertiser portal. Only one **active** request per resource.
2. **Review**: the request appears in the reviewers' queue with all the context —
   **viewable** creatives (built-in player), advertiser, period, requested SOV and
   **achievable SOV**, rate/quote, named targets, **projected occupancy** of the screens
   with the detail of campaigns already in place.
3. **Decision**: **Approve**, **Reject** or **Request changes** — the reason
   is **mandatory** for a rejection or a change request. The "Notify
   the advertiser by email" checkbox (ticked by default) sends a summary of the decision to the
   advertiser's portal accounts, in their language.
4. **Resubmission**: after "changes requested", the submitter fixes and
   resubmits; the history (timeline + comments) is kept.
5. **Publication**: a campaign **under review cannot be published**; an approved campaign
   is published normally (approving the request **also approves its pending
   creatives** — a creative added afterwards goes back into creative review).

## Who approves?

Accounts holding the **approvals : approve / reject** permissions (org-admin and the
Approver role by default). Reviewers see the **queue of the whole organization**; a
submitter sees only **their own** requests. A **bell** in the top bar signals
pending requests.

## Managing the queue

- **Count badges** per status (under review, urgent < 48 h from the deadline…),
  search, filter.
- **CSV / PDF exports** of the queue (with reasons), current filter respected.
- **Clean-up**: requests in a terminal status (approved, rejected, cancelled, published)
  can be removed from the list — the trace remains in the audit log.
- **Deleting the resource** purges its requests.

## Playlists under moderation (hierarchical governance)

A playlist or a media item can belong to a **governance node** ("Owner
node" field in the playlist settings / the media panel). Two effects:

- **Restricted writing**: only the administrators of that node — or of a **parent** node
  — can modify or delete the content. Lower levels see it **read-only**
  (understanding what plays above oneself is part of the job);
  a **sibling** node does not see it at all.
- **Moderation**: if the node carries "**Content subject to approval**" (checkbox in the
  Governance page, inherited by nodes created below it), direct publication is
  **refused**. The button becomes "**Submit for approval**": it is the approval
  that **publishes the draft**. The reviewer sees the **preview of the submitted draft** (items,
  durations, thumbnails) in their queue.

The **moderators** are the administrators of the nearest **parent node** (the
hierarchy is the approval org chart: a store's content is approved by its
region), falling back to org-admins if no ancestor has an administrator. Removing
moderation from a node is reserved to an administrator of a **parent** node — a node cannot
exempt itself from moderation.

## Targeting only PART of a node's screens

By default, a schedule attached to a node plays on **all** the screens of that node and
of its subtree. To target only some of them — the classic case "entrance screens" vs
"butcher aisle" in the same store — add **targets** to the schedule (Scheduling
page): they **narrow** the node's scope.

- Targets can only **remove** screens, never add any: a governed
  schedule never leaves its node.
- **No target = the whole node.** This is the default behavior, nothing to do.
- In practice: create a **player group** "Entrances" and set **a single target** for
  the whole chain, instead of targeting store by store.
- A target that keeps **no** screen of the node is **refused on save**,
  and named. The number of screens actually kept is displayed next to the selector.
- A lower level can **never** narrow an **inherited** layer: the store does not
  decide that the national playlist skips its butcher screen.
- The Governance page flags the node's screens that **no local schedule targets** —
  useful to spot a new screen forgotten in its group (it receives only the inheritance).

## Not to be confused

The "**Creative approval required**" checkbox (Campaigns page) is a
**per-creative** control: it moderates each file added to an already approved campaign. The
workflow in this article approves the **whole campaign** (commercial + content) before
publication. The two combine naturally.
