"""Agent conversationnel de l'AI Assistant (§XXVII).

Boucle d'outils (function-calling OpenAI) au-dessus de LiteLLM — qui route vers
claude-sonnet-4-6. Choix d'implémentation : plutôt que de coupler le code à l'API
`create_react_agent` de LangGraph (qui change vite entre versions majeures), on pilote
directement l'API OpenAI-compatible de LiteLLM (même pattern httpx que `feed_ai.py`),
ce qui est robuste, sans dépendance lourde supplémentaire, et déployable sans rebuild.

Garanties §XXVII :
  - **2 outils en LECTURE SEULE** : `search_documentation` (RAG, filtré par rôle) et
    `query_tenant_data` (5 intents tenant, RLS) — aucun chemin d'écriture, aucun SQL généré.
  - **max N étapes** (garde-fou anti-boucle, `CMS_ASSISTANT_MAX_STEPS`).
  - **réponse forcée dans la locale de l'utilisateur** (§XXVIII.6) via le prompt système.

`run_agent` est un générateur asynchrone qui émet les fragments de texte de la réponse
finale (pour le streaming SSE). L'usage de tokens est accumulé dans `usage_out`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.ai_credentials import sdk_model_name
from app.services.assistant_actions import (
    ACTION_PERMISSIONS,
    check_action_permission,
    resolve_action,
)
from app.services.assistant_tools import (
    TENANT_INTENTS,
    query_tenant_data,
    search_documentation,
)

logger = logging.getLogger(__name__)

_LOCALE_NAMES = {
    "fr": "français",
    "en": "English",
    "es": "español",
    "de": "Deutsch",
    "it": "italiano",
    "nl": "Nederlands",
    "pt": "português",
}


def build_system_prompt(locale: str, roles: list[str], page_context: dict | None) -> str:
    """Prompt système : rôle de l'agent + LANGUE DE RÉPONSE forcée + contexte de page."""
    lang = _LOCALE_NAMES.get((locale or "en")[:2], "English")
    ctx = ""
    if page_context:
        page = page_context.get("page") or page_context.get("path")
        if page:
            ctx = f"\nL'utilisateur consulte actuellement la page : {page}."
    role_str = ", ".join(roles) if roles else "aucun rôle particulier"
    return (
        "Tu es l'assistant intégré de Vitrail, une plateforme d'affichage dynamique "
        "(digital signage). Tu aides les utilisateurs à comprendre et utiliser le produit.\n\n"
        f"RÈGLE ABSOLUE : réponds TOUJOURS et UNIQUEMENT en {lang} (locale « {locale} »), "
        "quelle que soit la langue de la documentation ou des données consultées.\n\n"
        "Pour répondre :\n"
        "- Utilise `search_documentation` pour les questions sur le fonctionnement du produit.\n"
        "- Utilise `query_tenant_data` pour des infos en direct sur le compte : players "
        "(liste/statut, quels déconnectés, quels à jour de contenu), playlists, paniers audio, "
        "événements, programmations et leurs cibles, médias, alertes, état du réseau, "
        "campagnes retail media (statut, diffusion, rapport annonceur).\n"
        "- Pour MODIFIER quelque chose (ajouter/retirer un média d'une playlist, créer une "
        "playlist, ajouter tous les contenus d'un tag à une playlist, créer un feed RSS, "
        "ajouter/retirer une piste d'un panier audio, créer un événement, retirer un feed de "
        "toutes les playlists qui l'utilisent, redémarrer/rebooter des players ou un groupe, "
        "forcer une resynchro, demander une capture d'écran, lancer une vidéo VOD, renommer un "
        "player, créer/modifier/supprimer un programme et gérer ses cibles, régler la règle de "
        "diffusion d'un item de playlist, taguer un média, activer/retirer un panier audio sur "
        "des players, configurer un panier audio (aléatoire/jingle/ducking), allumer/éteindre "
        "ou changer la source de l'écran physique de players/groupe/site, mettre à jour le "
        "logiciel des players — OTA — vers la dernière version stable), "
        "utilise les outils `propose_*`. "
        "Ils ne FONT rien : ils PRÉPARENT l'action. L'utilisateur devra la CONFIRMER d'un "
        "bouton. Ne prétends JAMAIS qu'une action est déjà faite ; dis que tu l'as préparée "
        "et invite à confirmer. Si l'outil renvoie une erreur (introuvable ou ambigu), "
        "explique-le et demande une précision. N'invente jamais d'URL de feed.\n"
        "- En dehors de ces outils `propose_*`, tu es en LECTURE SEULE : tu ne peux rien "
        "créer/modifier/supprimer d'autre. Si on te le demande, explique comment faire.\n"
        "- Si tu ne sais pas, dis-le simplement plutôt que d'inventer.\n"
        "- Sois concis et concret.\n\n"
        f"Rôles de l'utilisateur : {role_str}.{ctx}"
    )


# ── Schémas des outils (function-calling) ─────────────────────────────────────

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "search_documentation",
            "description": (
                "Recherche dans la documentation produit de Vitrail (prise en main, players, "
                "médias, playlists, programmation, feeds, dépannage). À utiliser pour toute "
                "question sur le fonctionnement de la plateforme."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "La question/les mots-clés à rechercher dans la doc.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_tenant_data",
            "description": (
                "Interroge en LECTURE SEULE les données en direct du compte de l'utilisateur. "
                "Utilise l'un des intents prédéfinis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": list(TENANT_INTENTS),
                        "description": (
                            "L'information demandée. explain_player_power = pourquoi un "
                            "écran est éteint / un player hors ligne (veille programmée ?) ; "
                            "media_airtime = temps d'antenne prouvé d'un média (PoP) ; "
                            "list_hdmi_sessions = historique des bascules d'entrée HDMI ; "
                            "playlist_details = contenu/durée/programmation d'UNE playlist "
                            "(filters.playlist requis) ; list_sites = les sites du compte "
                            "(combien, fuseaux, players rattachés, HORAIRES D'OUVERTURE "
                            "jour par jour + exceptions/fériés — « le site X est-il "
                            "ouvert le dimanche ? ») ; list_players_status "
                            "accepte filters.site pour les players d'un site donné ; "
                            "campaign_status = état des campagnes retail media (toutes, ou "
                            "filters.campaign pour le détail d'une seule : statut, dates, "
                            "SOV vendu, cibles, créatifs) ; campaign_report = chiffres du "
                            "rapport annonceur d'une campagne (passages prouvés, SOV servi, "
                            "montant — filters.campaign requis)."
                        ),
                    },
                    "filters": {
                        "type": "object",
                        "description": "Filtres selon l'intent.",
                        "properties": {
                            "player": {"type": "string",
                                       "description": "Nom du player (explain_player_power)."},
                            "media": {"type": "string",
                                      "description": "Nom du média (media_airtime)."},
                            "playlist": {"type": "string",
                                         "description": "Nom de la playlist (playlist_details)."},
                            "campaign": {"type": "string",
                                         "description": "Nom de la campagne "
                                                        "(campaign_status, campaign_report)."},
                            "site": {"type": "string",
                                     "description": "Nom du site (list_players_status)."},
                            "days": {"type": "integer",
                                     "description": "Période en jours (défaut 7, max 90)."},
                        },
                    },
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_add_playlist_item",
            "description": (
                "PRÉPARE (sans exécuter) l'ajout d'un média à une playlist. L'utilisateur devra "
                "confirmer. Renvoie une proposition ou une erreur (introuvable/ambigu)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "playlist": {"type": "string", "description": "Nom de la playlist cible."},
                    "media": {"type": "string", "description": "Nom du média à ajouter."},
                    "zone": {
                        "type": "integer",
                        "description": "Numéro de zone (1 = première zone). Défaut 1.",
                    },
                    "duration_seconds": {
                        "type": "number",
                        "description": "Durée d'affichage en secondes (optionnel, pour une image).",
                    },
                },
                "required": ["playlist", "media"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_remove_playlist_item",
            "description": (
                "PRÉPARE (sans exécuter) le retrait d'un média d'une playlist. L'utilisateur "
                "devra confirmer. Renvoie une proposition ou une erreur."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "playlist": {"type": "string", "description": "Nom de la playlist."},
                    "media": {"type": "string", "description": "Nom du média à retirer."},
                },
                "required": ["playlist", "media"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_create_playlist",
            "description": "PRÉPARE (sans exécuter) la création d'une playlist. À confirmer.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Nom de la playlist."}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_add_tagged_content_to_playlist",
            "description": (
                "PRÉPARE (sans exécuter) l'ajout de TOUS les contenus visuels portant un tag "
                "donné à une playlist. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "playlist": {"type": "string", "description": "Nom de la playlist cible."},
                    "tag": {"type": "string", "description": "Valeur du tag (ex. « promo »)."},
                },
                "required": ["playlist", "tag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_create_feed",
            "description": (
                "PRÉPARE (sans exécuter) la création d'un feed d'actualité RSS. Donne `source` "
                "(nom d'une chaîne connue, ex. « BFM Info », « BBC », « CNN ») OU `url` (URL RSS "
                "exacte). N'invente JAMAIS d'URL : si la source est inconnue, demande l'URL. "
                "À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Nom de la source (catalogue)."},
                    "url": {"type": "string",
                            "description": "URL RSS exacte (si pas au catalogue)."},
                    "name": {"type": "string", "description": "Nom du feed (optionnel)."},
                    "display_mode": {"type": "string",
                                     "description": "Mode d'affichage (défaut ticker)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_add_audio_track",
            "description": (
                "PRÉPARE (sans exécuter) l'ajout d'une piste audio à un panier. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "basket": {"type": "string", "description": "Nom du panier audio."},
                    "media": {"type": "string", "description": "Nom de la piste audio."},
                },
                "required": ["basket", "media"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_remove_audio_track",
            "description": (
                "PRÉPARE (sans exécuter) le retrait d'une piste d'un panier audio. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "basket": {"type": "string", "description": "Nom du panier audio."},
                    "media": {"type": "string", "description": "Nom de la piste audio."},
                },
                "required": ["basket", "media"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_create_event",
            "description": (
                "PRÉPARE (sans exécuter) la création d'un ÉVÉNEMENT manuel (override déclenché à "
                "la demande) qui diffuse une playlist ou un média visuel. Ciblage : toute "
                "l'organisation par défaut, ou un groupe/player nommé. L'événement est créé "
                "INACTIF (à déclencher ensuite). À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nom de l'événement."},
                    "content": {
                        "type": "string",
                        "description": "Nom de la playlist OU du média à diffuser.",
                    },
                    "target": {
                        "type": "string",
                        "description": "Cible : « tous » (org), ou un nom de groupe/player.",
                    },
                    "duration_seconds": {
                        "type": "number",
                        "description": "Durée en secondes (optionnel ; sinon indéfinie).",
                    },
                    "keep_screens_on": {
                        "type": "boolean",
                        "description": (
                            "true = les écrans des players ciblés restent ALLUMÉS pendant "
                            "l'événement, même hors horaires d'ouverture (ex. soirée "
                            "exceptionnelle)."
                        ),
                    },
                },
                "required": ["name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_remove_feed_from_active_playlists",
            "description": (
                "PRÉPARE (sans exécuter) le retrait d'un FEED (page/flux d'actualité) de TOUTES "
                "les playlists qui l'utilisent, en une seule opération. Renvoie un récapitulatif "
                "d'impact (playlists concernées + état de diffusion) à montrer avant confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "feed": {"type": "string", "description": "Nom du feed à retirer."},
                },
                "required": ["feed"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_play_vod",
            "description": (
                "PRÉPARE (sans exécuter) le lancement d'une vidéo VOD (à la demande). Le média "
                "doit appartenir à une liste VOD. Cible opt. = un player/groupe parmi ceux de la "
                "VOD (sinon tous). Mode : once (une fois) | loop (en boucle) | stop. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "media": {"type": "string", "description": "Nom de la vidéo/du média VOD."},
                    "target": {"type": "string",
                               "description": "Player/groupe cible, ou « tous » (défaut)."},
                    "mode": {"type": "string", "enum": ["once", "loop", "stop"],
                             "description": "once (défaut) | loop | stop."},
                },
                "required": ["media"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_rename_player",
            "description": "PRÉPARE (sans exécuter) le renommage d'un player. À confirmer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player": {"type": "string", "description": "Nom actuel du player."},
                    "new_name": {"type": "string", "description": "Nouveau nom."},
                },
                "required": ["player", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_create_schedule",
            "description": (
                "PRÉPARE (sans exécuter) la création d'un PROGRAMME : diffuser une playlist sur "
                "une cible (player ou groupe) selon une règle horaire. Donne les jours et/ou la "
                "plage horaire et/ou la plage de dates ; sans règle = diffusion permanente. "
                "À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nom du programme."},
                    "playlist": {"type": "string", "description": "Playlist à diffuser."},
                    "target": {"type": "string", "description": "Player ou groupe cible."},
                    "days": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Jours (ex. ['lun','mar'] ou ['mon'..'sun']). Optionnel.",
                    },
                    "time_start": {"type": "string",
                                   "description": "Heure de début « HH:MM ». Optionnel."},
                    "time_end": {"type": "string",
                                 "description": "Heure de fin « HH:MM ». Optionnel."},
                    "date_from": {"type": "string", "description": "Date de début ISO. Optionnel."},
                    "date_to": {"type": "string", "description": "Date de fin ISO. Optionnel."},
                    "priority": {"type": "integer",
                                 "description": "Priorité (défaut 0). Optionnel."},
                },
                "required": ["name", "playlist", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_set_playlist_item_rules",
            "description": (
                "PRÉPARE (sans exécuter) la règle de diffusion d'un média DANS une playlist "
                "(jours / plage horaire / plage de dates). S'applique à toutes ses occurrences "
                "(ou à une zone précise). Sans contrainte = diffusion permanente. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "playlist": {"type": "string", "description": "Nom de la playlist."},
                    "media": {"type": "string", "description": "Média concerné dans la playlist."},
                    "zone": {"type": "integer", "description": "Zone (1 = première). Optionnel."},
                    "target": {"type": "string",
                               "description": "Restreindre à un player/groupe précis. Optionnel."},
                    "days": {"type": "array", "items": {"type": "string"},
                             "description": "Jours (ex. ['lun','mar']). Optionnel."},
                    "time_start": {"type": "string", "description": "Début « HH:MM ». Optionnel."},
                    "time_end": {"type": "string", "description": "Fin « HH:MM ». Optionnel."},
                    "date_from": {"type": "string", "description": "Date début ISO. Optionnel."},
                    "date_to": {"type": "string", "description": "Date fin ISO. Optionnel."},
                },
                "required": ["playlist", "media"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_assign_basket_to_players",
            "description": (
                "PRÉPARE (sans exécuter) l'activation d'un panier audio sur des players "
                "(player, groupe, ou « tous »), avec un ratio de mix optionnel (0–100, défaut 50). "
                "À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "basket": {"type": "string", "description": "Nom du panier audio."},
                    "target": {"type": "string", "description": "Player, groupe, ou « tous »."},
                    "mix_ratio": {"type": "integer",
                                  "description": "Ratio de mix 0–100 (défaut 50). Optionnel."},
                },
                "required": ["basket", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_configure_audio_basket",
            "description": (
                "PRÉPARE (sans exécuter) la config d'un panier audio : aléatoire, fréquence du "
                "jingle (mode tracks/minutes + valeur), ducking (musique à X % pendant les "
                "annonces), bornes de mix min/max, activation. Patch partiel. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "basket": {"type": "string", "description": "Nom du panier audio."},
                    "shuffle": {"type": "boolean", "description": "Lecture aléatoire. Optionnel."},
                    "trigger_mode": {"type": "string", "enum": ["tracks", "minutes"],
                                     "description": "Récurrence du jingle. Optionnel."},
                    "trigger_value": {"type": "integer",
                                      "description": "Toutes les N pistes/minutes. Optionnel."},
                    "ducking_pct": {"type": "integer",
                                    "description": "Niveau musique 0–100 % pendant une annonce."},
                    "min_ratio": {"type": "integer", "description": "Borne min de mix. Optionnel."},
                    "max_ratio": {"type": "integer", "description": "Borne max de mix. Optionnel."},
                    "active": {"type": "boolean", "description": "Activer/désactiver. Optionnel."},
                },
                "required": ["basket"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_unassign_basket_from_players",
            "description": (
                "PRÉPARE (sans exécuter) le retrait d'un panier audio de players "
                "(player, groupe, ou « tous »). À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "basket": {"type": "string", "description": "Nom du panier audio."},
                    "target": {"type": "string", "description": "Player, groupe, ou « tous »."},
                },
                "required": ["basket", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_tag_media",
            "description": (
                "PRÉPARE (sans exécuter) le tag d'un média. Le tag (namespace + valeur) est créé "
                "s'il n'existe pas. Ex. namespace « Promo », valeur « soldes ». À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "media": {"type": "string", "description": "Nom du média à taguer."},
                    "value": {"type": "string", "description": "Valeur du tag (ex. « promo »)."},
                    "namespace": {"type": "string",
                                  "description": "Catégorie de tag (défaut « Général »)."},
                },
                "required": ["media", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_screen_power",
            "description": (
                "PRÉPARE (sans exécuter) l'allumage/extinction de l'ÉCRAN PHYSIQUE (RS232/IP) des "
                "players d'une cible (player/groupe/site/tous). N'agit QUE sur les players "
                "configurés pour piloter un écran ; les autres sont listés et ignorés. "
                "Réservé à l'administrateur. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string",
                               "description": "Player, groupe, site, ou « tous »."},
                    "state": {"type": "string", "enum": ["on", "off"],
                              "description": "on = allumer, off = éteindre."},
                },
                "required": ["target", "state"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_screen_set_input",
            "description": (
                "PRÉPARE (sans exécuter) le changement de SOURCE de l'écran physique (RS232/IP) "
                "des players d'une cible. N'agit que sur les players équipés (les autres sont "
                "ignorés). Réservé à l'administrateur. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string",
                               "description": "Player, groupe, site, ou « tous »."},
                    "source": {"type": "string", "enum": ["hdmi1", "hdmi2", "dp", "pc"],
                               "description": "Source d'entrée."},
                },
                "required": ["target", "source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_update_schedule",
            "description": (
                "PRÉPARE (sans exécuter) la modification d'un programme existant (patch partiel : "
                "playlist, priorité, activation, validité, horaires). Ne change que ce qui est "
                "fourni. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "schedule": {"type": "string", "description": "Nom du programme."},
                    "playlist": {"type": "string", "description": "Nouvelle playlist. Optionnel."},
                    "priority": {"type": "integer", "description": "Nouvelle priorité. Optionnel."},
                    "active": {"type": "boolean", "description": "Activer/désactiver. Optionnel."},
                    "valid_from": {"type": "string", "description": "Date début ISO. Optionnel."},
                    "valid_until": {"type": "string", "description": "Date fin ISO. Optionnel."},
                    "days": {"type": "array", "items": {"type": "string"},
                             "description": "Jours de la nouvelle règle. Optionnel."},
                    "time_start": {"type": "string", "description": "Début « HH:MM ». Optionnel."},
                    "time_end": {"type": "string", "description": "Fin « HH:MM ». Optionnel."},
                },
                "required": ["schedule"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_add_schedule_target",
            "description": ("PRÉPARE (sans exécuter) l'ajout d'une cible (player/groupe) à un "
                            "programme. À confirmer."),
            "parameters": {
                "type": "object",
                "properties": {
                    "schedule": {"type": "string", "description": "Nom du programme."},
                    "target": {"type": "string", "description": "Player ou groupe à ajouter."},
                },
                "required": ["schedule", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_remove_schedule_target",
            "description": ("PRÉPARE (sans exécuter) le retrait d'une cible (player/groupe) d'un "
                            "programme. À confirmer."),
            "parameters": {
                "type": "object",
                "properties": {
                    "schedule": {"type": "string", "description": "Nom du programme."},
                    "target": {"type": "string", "description": "Player ou groupe à retirer."},
                },
                "required": ["schedule", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_delete_schedule",
            "description": ("PRÉPARE (sans exécuter) la suppression d'un programme par son "
                            "nom. À confirmer."),
            "parameters": {
                "type": "object",
                "properties": {
                    "schedule": {"type": "string", "description": "Nom du programme à supprimer."},
                },
                "required": ["schedule"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_hdmi_switch",
            "description": (
                "PRÉPARE (sans exécuter) la bascule d'un écran sur son ENTRÉE HDMI physique "
                "(source externe : décodeur TV, box, console…) ou le retour à la playlist. "
                "Uniquement les players BrightSign à entrée HDMI (XT/4K1142/XD1230) — les "
                "autres sont ignorés. Réservé à l'administrateur. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string",
                               "description": ("Nom d'un player, d'un groupe, d'un site, "
                                               "ou « tous ».")},
                    "mode": {"type": "string", "enum": ["start", "stop"],
                             "description": ("start = basculer sur HDMI ; stop = revenir "
                                             "à la playlist.")},
                },
                "required": ["target", "mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_set_player_timezone",
            "description": (
                "PRÉPARE (sans exécuter) le réglage du fuseau horaire de l'OS d'UN player "
                "(ex. un player à la mauvaise heure — comparer device_timezone et "
                "site_timezone via list_players_status). Réservé à l'administrateur. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Nom du player (un seul)."},
                    "timezone": {"type": "string",
                                 "description": ("Fuseau : IANA (Europe/Paris) pour linux/rpi/"
                                                 "android ; canonique Windows ; libellé natif "
                                                 "BrightSign (CET…).")},
                },
                "required": ["target", "timezone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_update_players",
            "description": (
                "PRÉPARE (sans exécuter) la MISE À JOUR LOGICIELLE (OTA) de players vers la "
                "dernière version STABLE de leur plateforme (catalogue Réglages → Mises à "
                "jour). Les players déjà à jour sont ignorés ; pas de version précise ni de "
                "canal beta ici (utiliser l'interface pour un déploiement canary/planifié). "
                "Réservé à l'administrateur. À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string",
                               "description": ("Nom d'un player, d'un groupe, d'un site, "
                                               "ou « tous ».")},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_move_media_to_folder",
            "description": (
                "PRÉPARE (sans exécuter) le rangement de médias dans un DOSSIER existant de la "
                "médiathèque : un média par nom/motif, ou tous les médias non classés "
                "(unfiled=true). À confirmer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "description": "Nom du dossier de destination."},
                    "media": {"type": "string",
                              "description": "Nom/motif du ou des médias (ignoré si unfiled)."},
                    "unfiled": {"type": "boolean",
                                "description": "true = tous les médias non classés."},
                },
                "required": ["folder"],
            },
        },
    },
    *[
        {
            "type": "function",
            "function": {
                "name": f"propose_{a}",
                "description": (
                    f"PRÉPARE (sans exécuter) : {desc}. Cible = un player, un groupe, ou "
                    "« tous » (toute l'org). Réservé à l'administrateur. À confirmer."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "Nom d'un player, d'un groupe, ou « tous ».",
                        }
                    },
                    "required": ["target"],
                },
            },
        }
        for a, desc in (
            ("restart_player_app", "redémarrer l'application du/des player(s)"),
            ("reboot_player", "redémarrer (reboot OS) le/les player(s)"),
            ("force_resync", "forcer la resynchronisation du contenu"),
            ("player_screenshot", "demander une capture d'écran"),
            ("toggle_overlay", "afficher/masquer les infos diagnostic à l'écran"),
            ("set_maintenance", "afficher l'écran de maintenance"),
        )
    ],
]


async def _dispatch_tool(
    db: AsyncSession,
    id_org: int,
    id_user: int,
    roles: list[str],
    proposals_out: list[dict],
    name: str,
    args: dict,
) -> object:
    """Exécute un outil de lecture, ou PRÉPARE une action d'écriture (jamais exécutée ici).
    Jamais d'exception remontée au modèle."""
    try:
        if name == "search_documentation":
            return await search_documentation(db, args.get("query", ""), roles=roles)
        if name == "query_tenant_data":
            return await query_tenant_data(db, id_org, args.get("intent", ""),
                                           args.get("filters"), id_user=id_user)
        if name.startswith("propose_"):
            action_type = name[len("propose_"):]
            if action_type not in ACTION_PERMISSIONS:
                return {"error": f"action inconnue : {action_type}"}
            if not await check_action_permission(db, id_user, action_type):
                return {"error": "Vous n'avez pas la permission d'effectuer cette action."}
            res = await resolve_action(db, id_org, action_type, args)
            if "error" in res:
                return res
            # On collecte l'étape RÉSOLUE (sans signer ici) : toutes les étapes du tour de
            # conversation sont regroupées en UN SEUL lot signé par l'endpoint chat → une
            # seule confirmation utilisateur, exécution avec publish différé (execute_batch).
            proposals_out.append({
                "action_type": action_type,
                "params": res["params"],
                "description": res["description"],
                "warnings": res.get("warnings", []),
            })
            return {
                "status": "proposal_ready",
                "description": res["description"],
                "warnings": res.get("warnings", []),
                "note": "Action PRÉPARÉE — demande à l'utilisateur de la CONFIRMER. Ne dis pas "
                        "qu'elle est déjà faite.",
            }
        return {"error": f"outil inconnu : {name}"}
    except Exception as exc:  # noqa: BLE001
        logger.info("assistant tool %s a échoué: %s", name, exc)
        return {"error": "outil indisponible"}


def _headers() -> dict[str, str]:
    if settings.CMS_LITELLM_API_KEY:
        return {"Authorization": f"Bearer {settings.CMS_LITELLM_API_KEY}"}
    return {}


async def _chat(
    client: httpx.AsyncClient, messages: list[dict], *, byok_key: str | None = None
) -> dict:
    """Un tour de chat. Si `byok_key` (clé Anthropic propre à l'org) → appel DIRECT via le
    SDK litellm en process (le client paie). Sinon → proxy LiteLLM (clé plateforme, inchangé)."""
    if byok_key:
        import litellm  # dépendance déjà déclarée (>=1.40)

        resp = await litellm.acompletion(
            model=sdk_model_name(settings.CMS_ASSISTANT_MODEL),
            messages=messages,
            tools=TOOL_SPECS,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=800,
            api_key=byok_key,
            drop_params=True,
        )
        return resp.model_dump()

    resp = await client.post(
        f"{settings.CMS_LITELLM_URL.rstrip('/')}/v1/chat/completions",
        headers=_headers(),
        json={
            "model": settings.CMS_ASSISTANT_MODEL,
            "messages": messages,
            "tools": TOOL_SPECS,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 800,
        },
    )
    resp.raise_for_status()
    return resp.json()


def _chunk_text(text: str, size: int = 24) -> list[str]:
    """Découpe le texte final en petits fragments pour un rendu SSE progressif."""
    words = text.split(" ")
    out, buf = [], ""
    for w in words:
        buf = (buf + " " + w) if buf else w
        if len(buf) >= size:
            out.append(buf + " ")
            buf = ""
    if buf:
        out.append(buf)
    return out


async def run_agent(
    db: AsyncSession,
    *,
    id_org: int,
    id_user: int,
    roles: list[str],
    locale: str,
    messages: list[dict],
    page_context: dict | None = None,
    usage_out: dict | None = None,
    proposals_out: list[dict] | None = None,
    byok_key: str | None = None,
) -> AsyncIterator[str]:
    """Pilote la boucle d'outils et émet les fragments de la réponse finale (SSE).

    `messages` = historique [{role, content}] SANS le prompt système (ajouté ici).
    Les actions d'écriture préparées sont collectées dans `proposals_out` (non exécutées).
    """
    if proposals_out is None:
        proposals_out = []
    convo = [{"role": "system", "content": build_system_prompt(locale, roles, page_context)}]
    convo.extend(messages)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for _ in range(max(1, settings.CMS_ASSISTANT_MAX_STEPS)):
                data = await _chat(client, convo, byok_key=byok_key)
                if usage_out is not None and (u := data.get("usage")):
                    usage_out["total"] = usage_out.get("total", 0) + (u.get("total_tokens") or 0)

                msg = data["choices"][0]["message"]
                tool_calls = msg.get("tool_calls")
                if not tool_calls:
                    for frag in _chunk_text(msg.get("content") or ""):
                        yield frag
                    return

                # Le modèle veut des outils → on les exécute et on reboucle
                convo.append(
                    {"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls}
                )
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = await _dispatch_tool(
                        db, id_org, id_user, roles, proposals_out, fn.get("name", ""), args
                    )
                    convo.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )

            # Garde-fou max étapes atteint → réponse de repli
            yield (
                "Je n'ai pas pu finaliser ma réponse. Pouvez-vous reformuler votre question ?"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("run_agent a échoué: %s", exc)
        yield "L'assistant est momentanément indisponible. Réessayez dans un instant."
