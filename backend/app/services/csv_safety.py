"""Neutralisation de l'injection de formule dans les CSV exportés (audit 2026-06-25).

Un tableur traite une cellule commençant par `=`, `+`, `-` ou `@` comme une FORMULE. Un nom
de média ou une action de journal contrôlés par un utilisateur peuvent donc devenir du code
exécuté chez la personne qui ouvre l'export. Le préfixe apostrophe force le texte.

La fonction vivait en TROIS copies (`pop`, `bi_export`, `reports`), qui se citaient l'une
l'autre en commentaire — elles sont restées identiques, mais rien ne le garantissait. Elle
est ici, en un seul endroit, au moment où l'export du journal d'audit en devient le
quatrième consommateur.
"""

from __future__ import annotations

#: Caractères qui font basculer une cellule en formule côté tableur.
FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    s = "" if value is None else str(value)
    if s and s[0] in FORMULA_TRIGGERS:
        return "'" + s
    return s
