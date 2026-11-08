# Hierarchical governance & delegation

🇫🇷 [Version française](guide-gouvernance.fr.md)

*Vitrail · Hierarchical governance*

User guide — concepts, step-by-step configuration, and test scenario.

> The up-to-date reference is the **in-app user manual** ("User manual" menu, "Hierarchical governance" section): it follows the product with every release and contains a complete "store entrance and exit" example. This guide remains useful for the concepts and the test scenario.

**Hierarchical governance** lets a multi-level retail network (e.g. *Group → Region → Store*) **delegate scheduling** to each level, while guaranteeing that a lower level can **never** modify the content of a higher level. For each screen, the server then compiles a **programme merged in layers** (national → local) under budget and pre-emption constraints.

> **In one sentence**
>
> A programme ("schedule") can be attached to a **governance node**. All the programmes of the nodes a screen depends on are **stacked and merged** at playback time; only the **administrators** of a node (or of a parent node) can modify them.

## 1. Concepts

The governance tree is **independent** of the organisation tree. It models your delegation topology:

```
Node 0 — National (Group)
  ├── Node 1 — North Region
  │     ├── Node 2 — Lille Store
  │     └── Node 2 — Roubaix Store
  └── Node 1 — South Region
        └── Node 2 — Marseille Store
```

| Concept | Description |
|---------|-------------|
| 🌳 **Node** | A level of the tree (national, regional, store…). Carries a **level** (0 = root) computed automatically. |
| 🖥️ **Targets** | The **players / groups / sites** attached to a node. This is what says "this screen depends on this node". |
| 🛡️ **Administrators** | The **users** allowed to edit the programmes of the node **and of its subtree**. A national admin can edit everything below. |
| ⚖️ **Delegation rules** | The **constraints** applied to the node's content at playback time: time budget per cycle, number of items per round, pre-emption… |

## 2. How a screen receives its content

For a screen attached to a *store* node, the server gathers the programmes **active right now** for that node **and all its parents**, sorts them by level (**national first**), then applies the delegation rules. The result: a **compiled cycle**.

| Level | Layer | Status | Content |
|-------|-------|--------|---------|
| 0 | **National** | 🔒 inherited — read-only for the store | `Spot_A · 30s`, `Spot_B · 20s` |
| 1 | **Regional** | 🔒 inherited | `Promo_Region · 15s` |
| 2 | **Store** | editable here | `Store_Offer · 10s` |

→ Played cycle: `Spot_A → Spot_B → Promo_Region → Store_Offer` (then loops), positioned on the wall clock like a normal programme.

This is exactly what the **layered preview** shows on the Governance page ("Compiled programme" card). Higher levels appear **greyed out with a padlock** (inherited), the local level in blue.

### Delegation rules

| Rule | Parameter | Effect on the compiled cycle |
|------|-----------|------------------------------|
| `time_budget` | `sec_per_cycle` | Airtime seconds granted to the node **per compiled cycle** (an **absolute** volume, independent of what the other levels place); beyond that, the node's trailing items are trimmed. |
| `item_count` | `max_per_cycle`, `mode` | Number of content items the node places **per round**. Its items **rotate** from one round to the next (sequential or random) instead of always replaying the same ones. |
| `time_window` | `start`, `end`, `days` | The layer is only active within this time range. |
| `preemptive` | — | This node **interrupts** all lower-level content while it is active. |

*A node carries **only one rule per type**: to change a budget or a time range, edit the existing rule (or delete it) rather than stacking a second one.*

> **Soft vs strict cut (`soft_cut`)**
>
> When the per-cycle budget is exceeded: **soft** (default) = the overflowing item goes to the end (the overrun is flagged); **strict** = the overflowing item is removed from the cycle.

## 3. Who can modify what — immutability

A programme attached to a node can only be modified by the **administrators of that node or of one of its parents**. Otherwise the API returns **403** and the message is shown in the editor.

| User | Can edit… |
|------|-----------|
| Admin of the **National** node | National + Region + Stores (**the whole subtree**) ✓ |
| Admin of the **Store** node | Only their store. Not the regional or national level. ✗ (403) |
| **Organisation administrator** | Everything, without being a node admin (bypass). ✓ |
| Programme **without a node** | No governance constraint (as before). ✓ |

> **⚠️ A node without an administrator**
>
> If a node has **no** administrator, only **organisation admins** can edit its programmes. Remember to assign at least one administrator to each delegated node.

## 4. Step-by-step configuration

1. **Build the tree** — `/governance` page → *New root node*, then *Add a sub-node* to create Region, Store… Give it a type (international / national / regional / department / store…) if useful.
2. **Attach the screens** — On the leaf node (store), **Targets** section → add the **players**, **groups** or **sites** that depend on it.
3. **Designate the administrators** — **Node administrators** section → choose the users allowed to edit this node and its subtree.
4. **(Optional) Set rules** — **Delegation rules** section → add a time budget per cycle, a number of items per round, a time window, pre-emption.
5. **Create the programmes per layer** — `/schedules` page → when creating/editing a programme, choose the **Governance node** in the selector. National content on the national node, local offer on the store, etc.
6. **Check the result** — Back on `/governance` → **Compiled programme** card → select a player of the node: you see the stacked layers and the final cycle.

## 5. Guided test scenario

1. **Tree** — Create `National`, then a sub-node `Store A`.
2. **Target** — On `Store A`, attach one of your players.
3. **Programmes** — In `/schedules`, create two *Always* programmes: one on `National` (priority 80), the other on `Store A` (priority 10).
4. **Preview** — In `/governance` → **Compiled programme** card → choose the player: you should see **2 layers**, National (greyed/padlock) **above** the Store.
5. **Pre-emption** — Add the `preemptive` rule on `National`: the Store layer switches to **"pre-empted"** and disappears from the cycle while the national layer is active.
6. **Immutability** — With a user who is **not an admin** of the node (and not an org admin), try to edit the National programme: you should get a **403** with the error message in the drawer. Then assign them as node admin → the edit goes through.

## 6. Good to know / limitations

- **Fully opt-in.** A player **not attached** to a node (or with no active governed programme) keeps the current behaviour: its regular programmes apply normally.
- **Deterministic budgets.** Budgets are applied by **compiling the cycle** (no real-time counter) — screens stay stateless, consistent with the wall clock. The displayed *budget status* is therefore a **planned** consumption.
- **LAN sync.** Two screens of the same wall under different layers do not have the same effective content at certain times → they are then **not frame-synchronisable**. Reserve this for independent screens.
- **Audio.** The layer engine applies to **visual content**; audio baskets keep their own resolution.

---

Vitrail — Digital Signage · Hierarchical governance (engine, live sync, layered view, immutability).
