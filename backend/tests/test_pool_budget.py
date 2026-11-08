"""Budget de connexions PostgreSQL face au multi-worker (P3.12).

Passer uvicorn à plusieurs workers parallélise les résolutions de programme — c'est le
levier contre la rafale de reconnexions. Mais chaque processus ouvre ses pools, et la
réserve PostgreSQL est commune à tout le serveur. Ces tests figent le calcul et le refus.

Ce qu'ils défendent : le mode de défaillance est sournois. Une configuration trop large
fonctionne parfaitement au repos — mesuré en production, le pool applicatif tient **zéro**
connexion quand rien ne se passe — et n'échoue qu'au moment de la rafale, c'est-à-dire
exactement quand on comptait sur elle.
"""

import pytest

from app.db.session import assert_pool_budget_fits, connections_per_process


def test_both_pools_are_counted():
    """Un processus backend ouvre DEUX pools : l'applicatif et celui du rôle BYPASSRLS.

    Le cadrage de P3.12 annonçait « 4 workers = 120 connexions » en ne comptant que le
    premier. Avec les valeurs par défaut c'est 45 par processus, donc 180 à 4 workers —
    pour un budget réel de 97. Ce test est là pour que ce chiffre ne se re-sous-estime pas.
    """
    assert connections_per_process(10, 20, 5, 10) == 45
    assert connections_per_process(10, 20, 0, 0) == 30, "sans le pool worker, on sous-compte"


def test_default_configuration_fits():
    """Le réglage livré (1 worker, pools par défaut) doit passer, sinon le backend refuse
    de démarrer chez tout le monde."""
    assert_pool_budget_fits(1, connections_per_process(10, 20, 5, 10), 60)


def test_four_workers_at_default_pools_is_refused():
    """Le piège exact : augmenter WEB_CONCURRENCY sans toucher aux pools."""
    with pytest.raises(RuntimeError, match="180"):
        assert_pool_budget_fits(4, connections_per_process(10, 20, 5, 10), 60)


def test_four_workers_fits_once_pools_are_reduced():
    """Le multi-worker reste ACCESSIBLE : c'est un dimensionnement, pas une interdiction."""
    assert_pool_budget_fits(4, connections_per_process(5, 5, 2, 3), 60)


def test_refusal_names_the_levers():
    """Une garde qui refuse sans dire quoi régler coûte plus cher que pas de garde."""
    with pytest.raises(RuntimeError) as exc:
        assert_pool_budget_fits(4, connections_per_process(10, 20, 5, 10), 60)
    message = str(exc.value)
    for lever in ("WEB_CONCURRENCY", "CMS_DB_POOL_SIZE", "CMS_DB_CONNECTION_BUDGET",
                  "max_connections"):
        assert lever in message


def test_exactly_at_budget_is_allowed():
    """La borne est un plafond atteignable, pas une marge implicite de plus."""
    assert_pool_budget_fits(2, connections_per_process(10, 10, 5, 5), 60)
    with pytest.raises(RuntimeError):
        assert_pool_budget_fits(2, connections_per_process(10, 10, 5, 6), 60)
