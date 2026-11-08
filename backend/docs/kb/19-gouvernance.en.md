---
title: Hierarchical governance (multi-site networks)
section: gouvernance
roles: []
keywords: [governance, hierarchy, node, national, regional, department, store, site, chain, network, multi-site, layer, compiled program, delegation, rule, item_count, budget, cap, restriction, lock, scope, node administrator, node admin, entrance, exit, player group, moderation, approval, attach, orphan, move a node, re-parenting, director, programmer, editor, approver, governed content, read-only, subtree, gouvernance, nœud, magasin]
---

# Hierarchical governance (multi-site networks)

**Governance** (page `/governance`) is for networks where several levels decide
what is displayed: a headquarters, regions, stores. Each level composes **its** part
of the program, and the screens play the **sum** of the levels they depend on — without
anyone being able to overwrite someone else's content.

A single-site installation does not need it: without a node, the product behaves
exactly as before (the "Owner node" selector is not even displayed).

## The five notions

**The node** is a level of the organization (National, Department, Store). Nodes
form a tree; it is the **level** (root = 0) that sets the national → local order in
the final program, not the node's "type", which is only a label.

**The scope** of a node is the set of screens it drives. It is composed by
attaching **targets**: a screen, a group of screens, a site, a site group. A
node's scope **includes that of its descendants**: attaching the sites to the store
nodes is enough, the department and the national level cover them automatically.

**The layer**: each schedule attached to a node produces a layer. A screen compiles
all the layers of the nodes it depends on, from national to local. This is what the
"Compiled program" column of the Governance page shows — for **this screen** and at **this
moment**, with the real playback engine, but before filtering by tags, campaigns and
time anchoring.

**The rule** says how much each level may take. The most used is **"number of
items per cycle"** (`item_count`): with 1, each level places one item per cycle, and
its items **rotate** from one cycle to the next instead of always replaying the same one. There are
also the time budget, the time window and preemption.

**The node administrator** is the person who decides for that node. ⚠️ A permission
is **never** enough: it is this assignment that authorizes writing. A user who
holds "schedules: edit" without administering any node cannot modify
any governed schedule.

## Who can do what

A node's administrator acts on **their node and its whole subtree**. They see the nodes
above them **read-only** (understanding what comes from national is part of the
job) and do **not see at all** the sibling branches: content, structure and screens
of a neighboring store return "not found" to them.

Three actions always go up one level:

- **removing content from governance** ("detaching" it);
- **removing moderation** from a node or **lifting a restriction** on its rules;
- **approving** a submission — the approver must administer a **parent** node, and
  nobody approves their own submission.

Creating a **root** node is reserved to the organization administrator.

## The four governance roles

| Role | What it does |
|---|---|
| **Governance — Director** | Builds the structure: nodes, scopes, administrators, rules and caps. Sees the content, does not produce it. |
| **Governance — Programmer** | Creates the **schedules** and **playlists** of their nodes, submits for approval. |
| **Governance — Editor** | Produces the content (playlists, media) and submits it. **Deletes no media**, does not schedule. |
| **Governance — Approver** | Approves, rejects or requests changes within their subtree. Produces nothing. |

These four roles carry **scope semantics**: their holder acts only within
their subtree, **and non-governed content is invisible to them**. A "Programmer" therefore
sees neither the organization's playlists nor its schedules — only those of the nodes
they administer. This is intentional: without it, the restriction would stop at the border of
governance.

## Governed content

A **playlist**, a **media item**, a **template**, an **event** and a **VOD
configuration** can belong to a node ("Owner node" field). Without a node, the object
belongs to the organization and behaves as before.

An attached object can only be modified by the administrators of its node or of a parent
node. If the node is marked **"Content subject to approval"**, direct publication
is refused: you **submit for approval**, and it is the approval that publishes. This
moderation is **inherited downwards** — unticking it on a store is pointless if the
national level requires it.

⚠️ **Two costly misunderstandings.** Attaching a playlist to a node decides **who
edits it**; it does not **play it** — playback comes from a **schedule** attached to the
same node. And the **role** says what you can do, the **administrator assignment** says
**where**.

## Targeting part of a node's screens

By default, a schedule attached to a node plays on **all** the node's screens. To
target only some of them, add **targets** to it: they **narrow** the scope,
they never widen it, and a lower level can never narrow an inherited
layer. A target that keeps no screen of the node is refused on save, and
named.

**Leaving a schedule without a target is often the right choice**: it then covers its whole
node, including sites added later. A national schedule targeted site by site
silently forgets every new store.

## Full example: store entrance and exit

Real need: in each store, the **entrance** screen and the **exit** screen play some
content **in addition** to the other screens, and the store manager must be able to change
their content and schedules themselves.

**The tree** — `National TOTO` → `Dpt-01` → `Dpt-01/Site-01` and `Dpt-01/Site-02`.

**The scope** — **the site** is attached to the store node (`Site-01` to the node
`Dpt-01/Site-01`). The department and the national level have **no assignment**: they
inherit from the subtree. It is simpler and it never goes stale.

**The two screen groups** — an **"Entrance shop"** group containing the entrance
screen **of every** store, and an **"Exit Shop"** group for the exits. The group
marks the screen's **role**, the node marks the **store**: crossing the two
designates the right screen, without ever creating one group per store.

**The content** — each node owns its playlists. The store has three: its local
playlist, its entrance one, its exit one. 🔑 **Each store must own its
own**: a playlist shared between two stores can only be modified by its
owner, and the other manager cannot even read it.

**The schedules** — one per node, plus two per store:

| Node | Schedule | Target | Effect |
|---|---|---|---|
| National TOTO | SC National | *(none)* | all screens of the network |
| Dpt-01 | SC Dpt | *(none)* | all screens of the department |
| Dpt-01/Site-01 | SC Site-01 | the store's 5 screens | local content |
| Dpt-01/Site-01 | SC Entrance Site-01 | "Entrance shop" group | the entrance only |
| Dpt-01/Site-01 | SC Exit Site-01 | "Exit Shop" group | the exit only |

**The rules** — `item_count = 1` on each node: each level places one item per
cycle and rotates its items.

**The measured result**: ordinary screens play **3 items per cycle** (national
+ department + local), the entrance and the exit play **4**. Each store
manager modifies their three playlists and their three schedules, is refused those of the
neighboring store, and reads without modifying those of the national level and the department.

**Adding a store** then takes five actions: create the node under the department,
attach the site to it, create its three playlists, create its three schedules, and add its
entrance screen to the "Entrance shop" group and its exit screen to "Exit Shop". The
national and department schedules need not be touched — they have no target.

## Composing a scope at scale

The **"Add screens"** button of the Targets card opens a **server-side**
search: you filter by kind (screen, screen group, site, site group), you
select **several targets at once**, and each row announces **the number of screens
it represents** — essential as soon as sites and groups are mixed. A screen not yet
attached to **any** node is offered and **labeled**: this is how an installation
oversight becomes visible and gets fixed. A screen governed **elsewhere** does not appear.

## Reorganizing

A node can be **moved** under another parent: the paths and levels of its whole
subtree are recomputed, and the screens concerned recompile. You cannot move a
node under itself or under one of its descendants, nor graft it into a branch you
do not administer.

## Diagnosis: "no active layer"

When a screen's preview is empty, the message names the cause: no node for this screen,
no schedule on the node, inactive schedule, schedule without a playlist, schedule **without a
time rule** (it will never be active), or outside its window at this moment. The most
frequent cause is the first one: a playlist attached to a node plays nothing until
a **schedule** is attached to the same node.
