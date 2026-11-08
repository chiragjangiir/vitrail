"""Générateur de visuels promotionnels produit (Retail Media) — cf. docs/PLAN_GENERATEUR_PROMO.md.

Principe : génératif pour l'esthétique (fond), compositing DÉTERMINISTE pour le texte
(prix / % / mentions = aucune erreur tolérée). Phase 1 = moteur de templates + rendu image
Jinja2 -> Playwright, 100% local (aucun appel fal).
"""


class PromoError(Exception):
    """Erreur métier du module promo (template inconnu, conformité, rendu)."""
