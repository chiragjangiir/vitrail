---
title: Rôles et permissions — qui peut faire quoi
section: iam
roles: []
keywords: [rôles, permissions, droits, RBAC, IAM, utilisateurs, groupes, rôle personnalisé, custom role, super-admin, org-admin, designer, scheduler, approbateur, campagnes, viewer, annonceur, opérateur magasin, 403, accès refusé, menu manquant, déléguer]
---

# Rôles et permissions — qui peut faire quoi

SignFlow accorde les droits par **permissions atomiques** de la forme
`module:opération` (ex. `media:create`, `schedules:read`). Un **rôle** est un
paquet de permissions ; un utilisateur porte un ou plusieurs rôles, directement
ou **via un groupe** — les deux se cumulent.

## Les deux rôles d'administration

| Rôle | Portée |
|---|---|
| **Super administrateur** (`CMS_SUPER_ADMIN`) | Compte **plateforme**, pas métier : il crée les organisations, gère le catalogue firmware et la base de connaissances. Il ne voit aucun contenu d'organisation. |
| **Administrateur d'organisation** (`CMS_ORG_ADMIN`) | Tous les droits **dans son organisation**. C'est lui qui crée les comptes, assigne les rôles et fabrique les rôles personnalisés. |

Un administrateur d'organisation **ne peut pas** s'attribuer le rôle super
administrateur, ni l'attribuer à quelqu'un, ni le copier : l'API refuse
(« Rôle non assignable » / « Rôle plateforme non copiable »). Cette interdiction
couvre l'assignation directe **et** le passage par un groupe.

## Les rôles métier

Ce tableau ne liste que les droits **réellement appliqués par le serveur** : il est
**généré** depuis la base et le code (`scripts/gen_role_matrix.py`), jamais écrit à la main.
Une permission détenue mais vérifiée nulle part n'accorde rien, et n'a donc pas sa place
ici. Dernière régénération : **2026-08-05** — 87 permissions au catalogue, **67 réellement
vérifiées**.

| Module | ANNONCEUR | APPROBATEUR | RESP. CAMPAGNES | DESIGNER | GOUV. VALIDEUR | GOUV. ÉDITEUR | GOUV. DIRECTEUR | LECTEUR RAPPORTS | PROGRAMMATEUR | PROGR. SITE | OPÉR. MAGASIN | OBSERVATEUR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `approvals` | soumettre | approuver, rejeter, examiner | soumettre | — | approuver, rejeter, examiner | soumettre | — | — | — | soumettre | — | — |
| `audio_baskets` | — | — | — | — | — | — | — | — | — | — | piloter, lire | — |
| `campaigns` | lire, rapport | — | créer, supprimer, modifier, publier, lire, rapport | — | — | — | — | — | — | — | — | lire |
| `events` | — | — | — | — | — | — | — | — | créer, supprimer, modifier, lire, déclencher | — | — | lire |
| `feeds` | — | lire | lire | créer, supprimer, modifier, lire | lire | modifier, lire | lire | — | lire | lire | — | lire |
| `generation` | — | lire | lire | créer, lire | lire | lire | lire | — | lire | lire | — | lire |
| `governance` | — | — | — | — | lire | lire | déléguer, modifier, lire | — | — | lire | — | — |
| `media` | — | lire | lire | créer, supprimer, modifier, lire | lire | modifier, lire | lire | — | lire | lire | — | lire |
| `players` | — | — | lire | — | — | — | lire | — | lire | lire | — | lire |
| `playlists` | — | lire | — | créer, modifier, lire | lire | créer, modifier, lire | lire | — | lire | créer, modifier, lire | — | lire |
| `reports` | — | — | exporter, lire | — | — | — | — | exporter, lire | — | — | — | lire |
| `schedules` | — | — | — | — | lire | — | lire | — | créer, supprimer, modifier, lire | créer, supprimer, modifier, lire | — | lire |
| `tags` | — | lire | lire | modifier, lire | lire | modifier, lire | lire | — | lire | lire | — | lire |
| `templates` | — | — | lire | créer, supprimer, modifier, lire | — | — | — | — | lire | — | — | lire |
| `url_display` | — | lire | lire | créer, supprimer, modifier, lire | lire | modifier, lire | lire | — | lire | lire | — | lire |
| `users` | — | — | lire | — | — | — | — | — | — | — | — | — |
| `vod` | — | — | — | — | — | — | — | — | créer, supprimer, modifier, lire, déclencher | — | — | lire |

**Deux rôles n'accordent rien** et n'ont pas à être attribués : *Utilisateur API*
(`CMS_API_USER`) et *Player* (`CMS_PLAYER`). Les intégrations passent par des
**clés API** avec leurs propres portées (`sfk_`, `sfr_`, `sfi_`) et les players
par un **jeton machine**. Ils n'apparaissent plus dans les listes de l'interface.

## Les rôles de gouvernance (§XVIII)

**Quatre** rôles pilotent la **gouvernance hiérarchique** (organisation → nœuds → sites /
players). 🔑 Ce qui les distingue des rôles ordinaires n'est pas la liste de leurs
permissions mais leur **portée** : ils n'agissent que dans le **sous-arbre dont ils sont
administrateurs**, et le contenu non gouverné leur est **invisible en écriture**. Un
`schedules:*` sans affectation de nœud ne donne donc rien à programmer.

- **Gestionnaire de gouvernance** (`CMS_GOVERNANCE_MANAGER`) — configure la **hiérarchie** :
  `governance:read / edit / delegate` (lire, modifier les nœuds, déléguer), plus la lecture de
  médias, playlists, players et programmations pour travailler. Il **structure et délègue**, il ne
  diffuse pas lui-même.
- **Programmateur de site** (`CMS_SITE_PROGRAMMER`) — **programme la diffusion** : contrôle complet
  des programmations (`schedules:create / edit / delete / read`) + lecture (médias, playlists,
  players, `governance:read`). ⚠️ **Sa portée ne vient PAS de la permission seule** : il ne peut
  programmer que les **nœuds dont il est administrateur** (affectation de gouvernance). Un
  `schedules:*` **sans affectation de nœud** ne lui donne aucun site à programmer.
- **Éditeur de gouvernance** (`CMS_GOVERNANCE_EDITOR`) — compose le **contenu** de son nœud
  (playlists, médias, flux, tags) et **soumet** à l'approbation. ⛔ Il n'a **pas**
  `media:delete` : un éditeur local ne supprime pas un média que le siège a déposé.
- **Valideur de gouvernance** (`CMS_GOVERNANCE_APPROVER`) — **tranche** les demandes
  d'approbation de son périmètre (`approvals:approve / reject / review`). ⚠️ Il ne peut pas
  valider **sa propre** soumission, et il doit être administrateur d'un nœud **ancêtre
  strict** de celui qui soumet — sinon un magasin s'auto-validerait.

## L'interface s'adapte au rôle

Depuis juillet 2026, les menus et les boutons d'action **inutilisables sont
masqués** : un approbateur ne voit ni Players, ni Programmation, ni Campagnes.
C'est un confort d'affichage — l'autorisation reste **entièrement côté serveur**.
Si un utilisateur dit « le menu a disparu », ce n'est pas une panne : il lui
manque le droit de lecture correspondant.

## Créer un rôle personnalisé

Réglages → **Utilisateurs & Rôles** → onglet *Rôles* → **Créer un rôle**, puis
**cliquer sur la ligne du rôle** pour cocher ses permissions, regroupées par
module.

Deux points à connaître :

- un rôle **système** est partagé par toutes les organisations : ses permissions
  sont en **lecture seule** ;
- on ne peut accorder que des droits qu'on détient soi-même — un délégué ne peut
  pas fabriquer un rôle plus puissant que lui.

Certaines permissions apparaissent **grisées, marquées « à venir »** : elles
correspondent à des fonctionnalités spécifiées mais pas encore développées (le
moteur de présentations interactives SPF). Les cocher n'aurait aucun effet, donc
l'interface l'interdit.

## Déléguer la gestion des comptes

La gestion des utilisateurs et des groupes s'appuie sur `users:*` et `groups:*`.
Un rôle personnalisé portant `users:read` + `users:create` + `users:edit` permet
donc de confier l'administration des comptes **sans** donner tous les droits
d'administrateur d'organisation. L'administrateur d'organisation conserve
toujours l'accès, quel que soit le réglage.

## « Accès refusé » : par où chercher

1. **Quel droit exige l'action ?** Le message d'erreur le nomme :
   « Permission refusée : `media:create` ».
2. **L'utilisateur le détient-il ?** Réglages → Utilisateurs & Rôles → son
   compte → ses rôles ; puis la ligne du rôle pour voir ses permissions.
3. **Attention aux groupes** : un droit peut venir d'un groupe et non du compte.
4. **Un rôle marqué « refus »** (`is_deny`) annule le même rôle obtenu par
   ailleurs.

## Régénérer ce tableau

La matrice ci-dessus est **générée depuis la base et le code**, jamais écrite à
la main :

```bash
docker compose exec -T backend python scripts/gen_role_matrix.py
```

Le script croise ce qu'un rôle *détient* (base) avec ce qui est *réellement
vérifié* (code) : une permission détenue mais vérifiée nulle part n'accorde rien,
et le tableau ne doit jamais laisser croire le contraire.
