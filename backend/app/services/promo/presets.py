"""Bibliothèque de préréglages de mentions légales (§7bis).

Textes-types FR insérables/complétables par l'utilisateur — le contenu reste sous SA
responsabilité (le code n'impose ni ne juge aucune mention). `{...}` = champ à compléter.
"""

from __future__ import annotations

MENTION_PRESETS: list[dict] = [
    {"id": "offre_validite",
     "label": "Validité de l'offre",
     "text": "Offre valable du {JJ/MM} au {JJ/MM} dans la limite des stocks disponibles."},
    {"id": "stocks",
     "label": "Dans la limite des stocks",
     "text": "Dans la limite des stocks disponibles."},
    {"id": "photo",
     "label": "Photo non contractuelle",
     "text": "Photo non contractuelle."},
    {"id": "abus_alcool",
     "label": "Abus d'alcool",
     "text": "L'abus d'alcool est dangereux pour la santé, à consommer avec modération."},
    {"id": "sante",
     "label": "Manger-bouger",
     "text": "Pour votre santé, mangez au moins cinq fruits et légumes par jour. "
             "www.mangerbouger.fr"},
    {"id": "origine",
     "label": "Origine produit",
     "text": "Origine : {pays}."},
]


def list_presets() -> list[dict]:
    return MENTION_PRESETS
