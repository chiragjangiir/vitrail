# SPIKE — Noyau Scheduling & Targeting (bloc retours clients, item 1)

🇬🇧 [English version](SPIKE_scheduling_targeting_core.md)

> **But du spike** : passer du cadrage conceptuel (EVOLUTIONS.md § « Médiathèque & Programmation », items 3+4) à un **design technique prêt à coder**. Vérifier que le noyau (a) éval de règle TZ-aware + (b) résolution de cible **s'emboîte** avec les trois consommateurs : item-rules (item 4), Gouvernance §XVIII Phase 2, Retail Media (Phase 3).
>
> **Verdict du spike : GO.** Le noyau est petit, les trois consommateurs s'y emboîtent proprement, et les frottements (vocabulaire de cible divergent, fenêtres overnight, multi-TZ) sont identifiés et tranchés ci-dessous. Date : 2026-06-03.

---

## 1. Inventaire de l'existant (ce qu'on factorise)

### 1.1 Éval de règle temporelle — **dupliquée 2×, partielle**

| Lieu | Forme |
|---|---|
| `ws.py::_rule_matches(rule, now)` (l.173) | logique `always/weekly/date_range`, commentaire explicite « dupliquée pour éviter la dépendance circulaire » |
| `schedules.py` (preview des règles) | même logique, copie |
| `ws.py::_build_basket_items` (l.205) | fenêtre de validité des items de panier — **encore une** comparaison horaire ad hoc |

Vocabulaire commun = `cms_schedule_rules` : `rule_type ∈ {always, weekly, date_range}`, `days_of_week` (0=Lun…6=Dim = `datetime.weekday()`), `time_start/time_end`, `date_from/date_to`. Heure courante via `ws.py::_local_now()` → `SIGNFLOW_TZ`, **datetime naïf**.

**Bug latent confirmé** : aucune des copies ne gère une **fenêtre overnight** (`time_start > time_end`, ex. 22:00→02:00). La logique `current_time < time_start → False` exclut tout l'intervalle du soir. À corriger **dans le noyau** (un seul endroit).

### 1.2 Résolution de cible — **3 vocabulaires divergents**

| Consommateur | Stockage | `target_type` | Résolveur |
|---|---|---|---|
| Schedules | `cms_schedule_targets` (table) | `player` \| **`player_group`** | inline `ws.py::_resolve_sync_payload` (l.775-793) : player direct + via `CmsPlayerGroupMember` |
| Events | `cms_events.target_config` (JSONB) | `org` \| `player` \| **`group`** | inline `ws.py` (l.753-768) |
| Gouvernance | `cms_governance_assignments` (table) | `player` \| **`group`** \| **`site`** | `governance.py::node_players` (l.233) : player + group + site → `set[int]` |
| Tags §XVII | `cms_player_tag_filters` | — (axe **réception**, pas ciblage) | `ws.py::_filter_items_by_tags` (l.105) : filtre **par item**, pas résolution de cible |

→ Trois mots pour « groupe » (`player_group`/`group`), un seul résolveur riche (gouvernance, qui fait déjà player+group+site mais **pas tags**). **Aucun ne résout une expression de tags.**

### 1.3 Pas de colonne timezone

Ni `cms_players` ni `cms_sites` n'ont de TZ → aujourd'hui tout est `SIGNFLOW_TZ` global. Le noyau doit être **paramétré par TZ** (défaut `SIGNFLOW_TZ`) avec un hook forward-compat `site.timezone` (multi-pays = plus tard, hors spike).

---

## 2. Design du noyau

Deux services purs, sans I/O DB pour la **logique** (testables unitairement), + de fines fonctions de **chargement** côté endpoints.

### 2.1 `services/scheduling.py` — éval de règle TZ-aware

```python
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from app.core.config import settings

@dataclass(frozen=True)
class TimeRule:
    """Règle temporelle normalisée — découplée de l'ORM (schedule OU item-rule)."""
    rule_type: str               # always | weekly | date_range
    days_of_week: list[int] | None = None   # 0=Lun … 6=Dim
    time_start: time | None = None
    time_end: time | None = None
    date_from: date | None = None
    date_to: date | None = None

def local_now(tz_name: str | None = None) -> datetime:
    """Instant courant en heure locale (naïf). Défaut SIGNFLOW_TZ. Repli UTC si TZ inconnue."""
    ...

def rule_active_at(rule: TimeRule, now_local: datetime) -> bool:
    """Vrai si `now_local` (déjà en TZ cible) tombe dans la règle.
    Gère les fenêtres OVERNIGHT (time_start > time_end → l'intervalle enjambe minuit)."""
    ...

def rules_active_at(rules: list[TimeRule], now_local: datetime) -> bool:
    """OR sur une liste de règles (un schedule/item a N règles, actif si l'une matche)."""
    return any(rule_active_at(r, now_local) for r in rules)
```

Règle overnight (le fix) : si `time_start` et `time_end` sont posés **et** `time_start > time_end`, le créneau est `[time_start, 24h[ ∪ [0h, time_end]`. Pour `weekly` avec overnight, `days_of_week` désigne le jour de **début** du créneau (décision : simple et suffisant pour le cas « bar ouvert 22h-2h »).

Adaptateurs ORM (dans le module, pas dans la logique pure) :
```python
def time_rule_from_schedule(r: CmsScheduleRule) -> TimeRule: ...
def time_rule_from_item_rule(r: CmsPlaylistItemRule) -> TimeRule: ...
```

`ws.py::_rule_matches` et la preview de `schedules.py` deviennent des appels à `rule_active_at(time_rule_from_schedule(r), now)`. **La duplication disparaît.**

### 2.2 `services/targeting.py` — résolution de cible étendue

Vocabulaire canonique unique : **`player | group | site | tags`** (+ `org` = sucre = tout l'org).

```python
@dataclass(frozen=True)
class Target:
    target_type: str            # player | group | site | tags | org
    target_id: int | None = None        # player/group/site
    tag_expr: dict | None = None         # pour 'tags' : {namespace_key: [values], ...} (AND inter-ns, OR intra-ns)

async def players_for_target(db, id_org: int, target: Target) -> set[int]:
    """Étend une cible en ensemble d'id_player. Réutilise la logique governance.node_players."""

async def player_matches_target(db, id_org: int, id_player: int, target: Target) -> bool:
    """Sens inverse (le chemin chaud de ws.py : 'ce player est-il visé ?').
    Évite de matérialiser tout l'org pour 'org'/'tags'. Cache les groupes/site/tags du player."""
```

- `group` accepte aussi l'alias **`player_group`** (compat `cms_schedule_targets` existant — **zéro migration de données**, le résolveur normalise).
- `tags` réutilise la **mécanique inverse** de `_filter_items_by_tags` mais appliquée au **profil tags du player** (les `cms_player_tag_filters` + tags hérités) vs une `tag_expr` de cible. ⚠️ Sémantique à NE PAS confondre :
  - **Tags §XVII actuels = filtre de réception** (« ce player n'accepte que les items `lang=fr` »).
  - **Tags comme cible (nouveau) = sélection d'audience** (« cette campagne vise les players taggés `region=PACA` »).
  - Les deux lisent la même taxonomie mais répondent à deux questions. Le noyau expose `player_has_tags(db, id_player, tag_expr)` partagé.

`players_for_target` pour `group/site` = extraction directe de `governance.node_players` (à déplacer/partager — la gouvernance l'importera au lieu de l'inverse).

---

## 3. Item 4 — `cms_playlist_item_rules` (le 1er consommateur)

### 3.1 Modèle (migration 0029)

```
cms_playlist_item_rules
  id_item_rule   BIGSERIAL PK
  id_item        BIGINT FK cms_playlist_items(id_item) ON DELETE CASCADE, INDEX
  scope          VARCHAR(20) NOT NULL DEFAULT 'default'   -- default | player | player_group
  target_id      BIGINT NULL              -- player/group selon scope ; NULL si default
  -- 6 champs miroir de cms_schedule_rules :
  rule_type      VARCHAR(20) NOT NULL DEFAULT 'weekly'
  days_of_week   INT[] NULL
  time_start     TIME NULL
  time_end       TIME NULL
  date_from      DATE NULL
  date_to        DATE NULL
  created_at     TIMESTAMPTZ DEFAULT now()
```

`scope` reste volontairement `default|player|player_group` (et **pas** `site/tags`) en P1/P2 : un item-rule est une exception locale au niveau d'une playlist, le ciblage riche (site/tags) vit au niveau schedule/campagne. (Si besoin plus tard, le `Target` du noyau est déjà prêt.)

### 3.2 Algorithme de résolution (dans `ws.py`, là où on filtre déjà par tags)

Emplacement : **après** `_filter_items_by_tags` (l.943), **avant** le wall-clock (l.945) — même couche logique (« quels items ce player voit maintenant »).

```
pour chaque item retenu :
    rules = item_rules[id_item]
    si rules vide            → item PERPÉTUEL, gardé
    sinon :
        # jeu le plus spécifique présent : player > player_group(du player) > default
        pertinents = rules where scope match le player, par spécificité décroissante
        groupe = premier niveau de spécificité non vide
        gardé SSI rules_active_at(groupe, local_now())   # heure LOCALE
```

« le plus spécifique l'emporte » = si une règle `player` existe pour cet item+player, elle **remplace** les règles `default` (override, pas union). Sinon `player_group`, sinon `default`.

**P1** = uniquement `scope=default` (récurrence + validité ; couvre ~90 % : « cet item ne joue que Sam/Dim 9-18h »). **P2** = override `player`/`player_group`. Le modèle porte déjà `scope` dès P1 → P2 = pur ajout d'UI + d'une branche de résolution.

### 3.3 Les 3 primitives temporelles restent distinctes (à matérialiser dans l'UI)

| Primitive | Sémantique | Stockage | Existant ? |
|---|---|---|---|
| **Embargo** | instant **absolu UTC** (lancement mondial synchronisé) | `cms_media.not_before_utc` / `embargo_event_id` | ✅ |
| **Règle par item** | **heure locale** wall-clock (fenêtre récurrente d'un item) | `cms_playlist_item_rules` | 🆕 item 4 |
| **Schedule** | dayparting heure locale (programme→players) | `cms_schedule_rules` | ✅ |

Embargo = `effective_embargo > now_utc` (l.916, **inchangé**, comparaison UTC). Règle par item = `rule_active_at(..., local_now())` (**locale**). Ne **jamais** fusionner ces deux comparaisons.

---

## 4. Emboîtement avec Gouvernance §XVIII Phase 2 (la vérif clé du spike)

Le moteur Phase 2 = **compiled-schedule multi-couches** : pour un player, empiler les couches qui le visent (par nœud de gouvernance), résoudre budgets/préemption, produire le programme effectif. La question du spike : **le noyau le porte-t-il sans dupliquer ?**

**Oui.** Décomposition :

1. **« quelles couches visent ce player »** = `targeting.player_matches_target` appliqué aux assignations de chaque nœud du sous-arbre. → noyau (b).
2. **« cette couche est-elle active maintenant »** = `scheduling.rules_active_at` sur la fenêtre de la couche (les `cms_delegation_rules` de type `time_window` portent déjà `time_start/end` ; à exprimer en `TimeRule`). → noyau (a).
3. **budgets / préemption / position-lock** = **delta propre à la gouvernance** (PAS dans le noyau) : compteurs `time_budget`/`item_count`/`frequency_cap`, bandes de priorité, immutabilité par couche. Le noyau fournit les **prédicats** (qui + quand), la gouvernance fournit l'**arbitrage** (combien + qui gagne).

→ **Modèle mental validé** : *la gouvernance EST le moteur de couches ; une item-rule est une couche dégénérée (1 playlist, 1 fenêtre, pas de budget) ; un schedule est une couche ; une campagne Retail Media est une couche + monétisation.* Tous consomment les deux mêmes prédicats. Le noyau est la frontière correcte.

**Conséquence d'ordonnancement** : faire noyau (3) + item-rules (4) **avant** le Sprint 2.7 dé-risque réellement le gros sprint — la Phase 2 n'aura plus qu'à écrire l'arbitrage (budgets/préemption), pas la résolution qui/quand.

---

## 5. Réutilisation Retail Media (Phase 3) — confirmation

Une campagne = `Target` (where) + `list[TimeRule]` (flight `date_range` + dayparts `weekly`) + créatif (média). **100 % du « où + quand » = le noyau.** Le delta Retail Media (à NE PAS confondre avec du reuse) : Share-of-Voice/rotation/fréquence (moteur d'**insertion** %, pas du on/off), inventaire/booking/anti-survente, annonceur+facturation+PoP Merkle (`cms_proof_of_play` ✅), validation créatifs (Approval §XXI ✅), pacing. Tables `cms_campaigns/_creatives/_targets` déjà miroir de schedule_targets. → en figeant le `Target` canonique maintenant, `cms_campaign_targets` s'y aligne « gratuitement ».

---

## 6. Plan d'implémentation (post-spike)

| Étape | Contenu | Migration | Tests |
|---|---|---|---|
| **N1** ✅ | `services/scheduling.py` (TimeRule + `rule_active_at` **avec overnight** + adaptateurs). Rebranché `ws._rule_matches` + `schedules._rule_matches` + `ws._local_now`. **Bonus** : `current-schedule` corrigé (UTC naïf → `local_now()`). | — | ✅ 11 tests purs (always/weekly/date_range/**overnight**/bornes incluses) |
| **N2** ✅ | `services/targeting.py` (`Target`, `players_for_target(s)`, `player_matches_target`, `player_has_tags`). Rebranché `governance.node_players` + `schedules._resolve_player_ids`. Alias `player_group`→`group` (zéro migration). | — | ✅ 8 tests (player/group/site/tags/org, alias, garde org, sens inverse) |

> **N1+N2 livrés le 2026-06-03** : +19 tests, **230 passed**. Reste I1 (item-rules P1, migr 0029) → I2.
| **I1** | item-rules **P1** : migration 0029, CRUD `cms_playlist_item_rules` (scope=default), résolution dans `ws.py` (après tags, avant wall-clock), UI éditeur playlist (badge « règle » + drawer fenêtre/validité), `sync_ready` impacté (un item time-boxé ⇒ contenu effectif variable ⇒ warning LAN). | **0029** | item perpétuel gardé, item hors-fenêtre retiré, embargo≠règle |
| **I2** | item-rules **P2** : override `player`/`player_group` (spécificité), UI override par cible. | — | override gagne sur default, fallback en cascade |

**Effort** : N1+N2 = petit (factorisation + 1 fix overnight + 1 résolveur tags). I1 = petit sprint. I2 = ajout incrémental.

---

## 7. Points d'honnêteté / décisions à acter

1. **Synchro LAN ↔ règles divergentes** : deux players d'un même mur sous des item-rules/cibles différentes ont un **contenu effectif différent** sur certains créneaux → **pas frame-synchronisables** alors. OK magasins séparés ; **à interdire/avertir sur un mur d'images** (le `sync_ready` doit lever un warning si une playlist ciblant un `lan_sync_group` contient des item-rules non-`default`).
2. **Lisibilité UI** : deux niveaux de programmation (schedule **et** item) — l'éditeur doit rendre l'**intersection** lisible (« cet item joue Sam/Dim 9-18h, **dans la limite** du programme matin »).
3. **Vocabulaire de cible** : on **garde** `cms_schedule_targets.target_type='player_group'` en base (zéro migration), le noyau normalise via alias. Acté.
4. **Multi-TZ** : hors spike. Noyau paramétré par TZ (défaut `SIGNFLOW_TZ`), hook `site.timezone` à brancher le jour du multi-pays sans retoucher la logique.
5. **Overnight `weekly`** : `days_of_week` = jour de **début** du créneau (le créneau peut déborder sur le lendemain). Acté (suffit au cas réel).

> **Décision attendue avant de coder** : valider le séquençage N1→N2→I1(P1)→I2(P2) et la convention overnight (point 5). Le reste est tranché.
