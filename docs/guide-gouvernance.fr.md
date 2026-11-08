# Gouvernance hiérarchique & délégation

🇬🇧 [English version](guide-gouvernance.md)

*Vitrail · Gouvernance hiérarchique*

Guide d'utilisation — concepts, configuration pas à pas, et scénario de test.

> La référence à jour est le **manuel utilisateur in-app** (menu « Manuel utilisateur », section « Gouvernance hiérarchique ») : il suit le produit à chaque version et contient un exemple complet « entrée et sortie de magasin ». Ce guide reste utile pour les concepts et le scénario de test.

La **gouvernance hiérarchique** permet à une enseigne multi-niveaux (ex. *Groupe → Région → Magasin*) de **déléguer la programmation** à chaque échelon, tout en garantissant qu'un niveau inférieur ne peut **jamais** modifier le contenu d'un niveau supérieur. Le serveur compile alors, pour chaque écran, un **programme fusionné en couches** (national → local) sous contraintes de budget et de préemption.

> **En une phrase**
>
> Un programme (« schedule ») peut être rattaché à un **nœud de gouvernance**. Tous les programmes des nœuds dont dépend un écran sont **empilés et fusionnés** à la diffusion ; seuls les **administrateurs** d'un nœud (ou d'un nœud parent) peuvent les modifier.

## 1. Les concepts

L'arbre de gouvernance est **indépendant** de l'arbre des organisations. Il modélise votre topologie de délégation :

```
Nœud 0 — National (Groupe)
  ├── Nœud 1 — Région Nord
  │     ├── Nœud 2 — Magasin Lille
  │     └── Nœud 2 — Magasin Roubaix
  └── Nœud 1 — Région Sud
        └── Nœud 2 — Magasin Marseille
```

| Concept | Description |
|---------|-------------|
| 🌳 **Nœud** | Un échelon de l'arbre (national, régional, magasin…). Porte un **niveau** (0 = racine) calculé automatiquement. |
| 🖥️ **Cibles** | Les **players / groupes / sites** rattachés à un nœud. C'est ce qui dit « cet écran dépend de ce nœud ». |
| 🛡️ **Administrateurs** | Les **utilisateurs** autorisés à éditer les programmes du nœud **et de son sous-arbre**. Un admin national édite tout en dessous. |
| ⚖️ **Règles de délégation** | Les **contraintes** appliquées au contenu du nœud à la diffusion : budget temps par cycle, nombre d'items par tour, préemption… |

## 2. Comment un écran reçoit son contenu

Pour un écran rattaché à un nœud *magasin*, le serveur rassemble les programmes **actifs maintenant** de ce nœud **et de tous ses parents**, les trie par niveau (**national d'abord**), puis applique les règles de délégation. Résultat : un **cycle compilé**.

| Niveau | Couche | Statut | Contenus |
|--------|--------|--------|----------|
| 0 | **National** | 🔒 hérité — lecture seule pour le magasin | `Spot_A · 30s`, `Spot_B · 20s` |
| 1 | **Régional** | 🔒 hérité | `Promo_Région · 15s` |
| 2 | **Magasin** | éditable ici | `Offre_Magasin · 10s` |

→ Cycle diffusé : `Spot_A → Spot_B → Promo_Région → Offre_Magasin` (puis boucle), positionné à l'horloge murale comme un programme normal.

C'est exactement ce que montre l'**aperçu en couches** dans la page Gouvernance (carte « Programme compilé »). Les niveaux supérieurs y apparaissent **grisés avec un cadenas** (hérités), le niveau local en bleu.

### Les règles de délégation

| Règle | Paramètre | Effet sur le cycle compilé |
|-------|-----------|----------------------------|
| `time_budget` | `sec_per_cycle` | Secondes d'antenne accordées au nœud **par cycle compilé** (volume **absolu**, indépendant de ce que placent les autres niveaux) ; au-delà, les items de queue du nœud sont rognés. |
| `item_count` | `max_per_cycle`, `mode` | Nombre de contenus que le nœud place **par tour**. Ses contenus **tournent** d'un tour à l'autre (séquentiel ou aléatoire) au lieu de rejouer toujours les mêmes. |
| `time_window` | `start`, `end`, `days` | La couche n'est active que dans cette plage horaire. |
| `preemptive` | — | Ce nœud **interrompt** tout contenu de niveau inférieur tant qu'il est actif. |

*Un nœud ne porte qu'**une seule règle par type** : pour changer un budget ou une plage, on modifie la règle existante (ou on la supprime) plutôt que d'en empiler une seconde.*

> **Coupure douce vs stricte (`soft_cut`)**
>
> Quand le budget par cycle est dépassé : **douce** (par défaut) = l'item qui déborde va au bout (le dépassement est signalé) ; **stricte** = l'item qui déborde est retiré du cycle.

## 3. Qui peut modifier quoi — l'immutabilité

Un programme rattaché à un nœud n'est modifiable que par les **administrateurs de ce nœud ou d'un de ses parents**. Sinon l'API renvoie **403** et le message s'affiche dans l'éditeur.

| Utilisateur | Peut éditer… |
|-------------|--------------|
| Admin du nœud **National** | National + Région + Magasins (**tout le sous-arbre**) ✓ |
| Admin du nœud **Magasin** | Uniquement son magasin. Pas le régional ni le national. ✗ (403) |
| **Administrateur de l'organisation** | Tout, sans être admin de nœud (contournement). ✓ |
| Programme **sans nœud** | Aucune contrainte de gouvernance (comme avant). ✓ |

> **⚠️ Un nœud sans administrateur**
>
> Si un nœud n'a **aucun** administrateur, seuls les **admins de l'organisation** peuvent éditer ses programmes. Pensez à affecter au moins un administrateur par nœud délégué.

## 4. Configuration pas à pas

1. **Construire l'arbre** — Page `/governance` → *Nouveau nœud racine*, puis *Ajouter un sous-nœud* pour créer Région, Magasin… Donnez un type (international / national / regional / department / store…) si utile.
2. **Rattacher les écrans** — Sur le nœud feuille (magasin), section **Cibles** → ajoutez les **players**, **groupes** ou **sites** qui en dépendent.
3. **Désigner les administrateurs** — Section **Administrateurs du nœud** → choisissez les utilisateurs autorisés à éditer ce nœud et son sous-arbre.
4. **(Optionnel) Poser des règles** — Section **Règles de délégation** → ajoutez un budget temps par cycle, un nombre d'items par tour, une plage horaire, la préemption.
5. **Créer les programmes par couche** — Page `/schedules` → à la création/édition d'un programme, choisissez le **Nœud de gouvernance** dans le sélecteur. National sur le nœud national, offre locale sur le magasin, etc.
6. **Vérifier le rendu** — Retour sur `/governance` → carte **Programme compilé** → sélectionnez un player du nœud : vous voyez les couches empilées et le cycle final.

## 5. Scénario de test guidé

1. **Arbre** — Créez `National`, puis un sous-nœud `Magasin A`.
2. **Cible** — Sur `Magasin A`, rattachez l'un de vos players.
3. **Programmes** — Dans `/schedules`, créez deux programmes *Toujours* : l'un sur `National` (priorité 80), l'autre sur `Magasin A` (priorité 10).
4. **Aperçu** — Dans `/governance` → carte **Programme compilé** → choisissez le player : vous devez voir **2 couches**, National (grisé/cadenas) **au-dessus** du Magasin.
5. **Préemption** — Ajoutez la règle `preemptive` sur `National` : la couche Magasin passe en **« préempté »** et disparaît du cycle tant que le national est actif.
6. **Immutabilité** — Avec un utilisateur **non admin** du nœud (et non org-admin), tentez d'éditer le programme National : vous devez obtenir un **403** avec le message d'erreur dans le drawer. Affectez-le ensuite comme admin du nœud → l'édition passe.

## 6. Bon à savoir / limites

- **Opt-in total.** Un player **non rattaché** à un nœud (ou sans programme gouverné actif) garde le comportement actuel : ses programmes classiques s'appliquent normalement.
- **Budgets déterministes.** Les budgets sont appliqués en **compilant le cycle** (pas de compteur temps réel) — les écrans restent sans état, cohérent avec l'horloge murale. L'*état de budget* affiché est donc une consommation **planifiée**.
- **Synchro LAN.** Deux écrans d'un même mur sous des couches différentes n'ont pas le même contenu effectif à certains moments → ils ne sont alors **pas synchronisables image par image**. À réserver aux écrans indépendants.
- **Audio.** Le moteur de couches concerne le **contenu visuel** ; les paniers audio gardent leur propre résolution.

---

Vitrail — Digital Signage · Gouvernance hiérarchique (moteur, sync live, vue en couches, immutabilité).
