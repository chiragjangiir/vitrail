"""Retail Media × templates MULTI-ZONES (P3.6) — l'angle mort de facturation.

L'injection des créatifs était **coupée** dès qu'un template portait 2 zones ou plus, avec
le commentaire « multi-zones = backlog ». Or **aucun service ne connaissait cette notion** —
mesuré le 2026-08-06 : `campaign_eligible_players`, l'occupancy-check, le SOV et le devis
comptent ces écrans comme **vendables**. Un annonceur pouvait donc être facturé pour des
écrans qui ne diffuseraient jamais son spot, et son rapport de sous-diffusion l'aurait
constaté sans que personne ne sache pourquoi.

Décision d'Ed : le comportement est **choisi par template** (`campaign_placement`, migr
0124), parce que les deux usages existent — la vitrine veut le plein écran (seul mode
cohérent avec la tarification au SOV), le menu board ne peut pas se permettre d'effacer
toutes ses zones pendant 10 s.

Ce que ces tests figent :
  1. le spot est injecté dans la **zone principale**, jamais dans une zone arbitraire ;
  2. le **mode voyage jusqu'au player** (`campaign.fullscreen`) — sans lui, le player ne
     peut pas savoir s'il doit recouvrir l'écran ou rester dans sa zone ;
  3. les items des **autres zones sont préservés** (un bandeau d'actualités ne disparaît
     pas parce qu'une campagne est active) ;
  4. sans zone principale servie, on ne touche à rien.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import ws


class _Tpl:
    def __init__(self, placement: str):
        self.campaign_placement = placement


def _items() -> list[dict]:
    """Deux zones servies : la principale (0) et un bandeau (1)."""
    return [
        {"id_item": 1, "zone_index": 0, "duration_ms": 10000},
        {"id_item": 2, "zone_index": 0, "duration_ms": 10000},
        {"id_item": 3, "zone_index": 1, "duration_ms": 5000},
    ]


def _fake_inject(spot: dict | None):
    """Remplace l'injection mono-zone : renvoie la liste reçue + un spot, ou l'objet REÇU
    tel quel quand il n'y a rien à servir (c'est ainsi que le vrai service signale « aucun
    créatif » — l'identité de l'objet est le signal)."""
    async def _f(db, player, items, now, *a, **k):
        if spot is None:
            return items
        return [*items, {**spot}]
    return _f


@pytest.mark.asyncio
async def test_spot_lands_in_the_MAIN_zone_not_an_arbitrary_one(monkeypatch) -> None:
    """En multi-zones, `items` mélange toutes les zones : injecter dans la liste à plat
    placerait le spot dans un bandeau d'actualités."""
    monkeypatch.setattr(ws, "_inject_campaign_items",
                        _fake_inject({"id_item": 99, "campaign": {"id_campaign": 7, "id_creative": 3}}))
    out = await ws._inject_campaign_items_multizone(
        None, SimpleNamespace(id_player=1), _items(), datetime.now(timezone.utc), _Tpl("fullscreen"))

    spots = [i for i in out if i.get("campaign")]
    assert len(spots) == 1
    assert spots[0]["zone_index"] == 0        # zone PRINCIPALE


@pytest.mark.asyncio
async def test_fullscreen_mode_travels_to_the_player(monkeypatch) -> None:
    """Sans ce marquage, le player ne peut pas savoir s'il doit recouvrir tout l'écran —
    et retomberait sur un comportement par défaut, donc diffuserait autre chose que ce qui
    a été vendu."""
    monkeypatch.setattr(ws, "_inject_campaign_items",
                        _fake_inject({"id_item": 99, "campaign": {"id_campaign": 7, "id_creative": 3}}))
    out = await ws._inject_campaign_items_multizone(
        None, SimpleNamespace(id_player=1), _items(), datetime.now(timezone.utc), _Tpl("fullscreen"))
    assert [i for i in out if i.get("campaign")][0]["campaign"]["fullscreen"] is True


@pytest.mark.asyncio
async def test_zone_mode_keeps_the_spot_inside_the_main_zone(monkeypatch) -> None:
    """Le cas du menu board : le spot passe dans la zone principale, le reste continue."""
    monkeypatch.setattr(ws, "_inject_campaign_items",
                        _fake_inject({"id_item": 99, "campaign": {"id_campaign": 7, "id_creative": 3}}))
    out = await ws._inject_campaign_items_multizone(
        None, SimpleNamespace(id_player=1), _items(), datetime.now(timezone.utc), _Tpl("zone"))
    spot = [i for i in out if i.get("campaign")][0]
    assert spot["campaign"]["fullscreen"] is False
    assert spot["zone_index"] == 0


@pytest.mark.asyncio
async def test_other_zones_are_preserved(monkeypatch) -> None:
    """Un bandeau d'actualités ne doit pas disparaître parce qu'une campagne est active."""
    monkeypatch.setattr(ws, "_inject_campaign_items",
                        _fake_inject({"id_item": 99, "campaign": {"id_campaign": 7, "id_creative": 3}}))
    out = await ws._inject_campaign_items_multizone(
        None, SimpleNamespace(id_player=1), _items(), datetime.now(timezone.utc), _Tpl("fullscreen"))

    zone1 = [i for i in out if i.get("zone_index") == 1]
    assert [i["id_item"] for i in zone1] == [3]
    # Et les items maison de la zone principale sont toujours là, dans l'ordre.
    zone0_home = [i["id_item"] for i in out if i.get("zone_index") == 0 and not i.get("campaign")]
    assert zone0_home == [1, 2]


@pytest.mark.asyncio
async def test_no_creative_to_serve_changes_nothing(monkeypatch) -> None:
    """Défensif : aucune campagne live → la boucle maison doit être rendue TELLE QUELLE."""
    monkeypatch.setattr(ws, "_inject_campaign_items", _fake_inject(None))
    src = _items()
    out = await ws._inject_campaign_items_multizone(
        None, SimpleNamespace(id_player=1), src, datetime.now(timezone.utc), _Tpl("fullscreen"))
    assert out is src


@pytest.mark.asyncio
async def test_without_a_main_zone_nothing_is_touched(monkeypatch) -> None:
    """Un template dont la zone 0 n'est pas servie n'a aucune horloge où placer un spot."""
    monkeypatch.setattr(ws, "_inject_campaign_items",
                        _fake_inject({"id_item": 99, "campaign": {"id_campaign": 7, "id_creative": 3}}))
    only_side = [{"id_item": 3, "zone_index": 1, "duration_ms": 5000}]
    out = await ws._inject_campaign_items_multizone(
        None, SimpleNamespace(id_player=1), only_side, datetime.now(timezone.utc), _Tpl("fullscreen"))
    assert out is only_side


@pytest.mark.asyncio
async def test_an_unknown_placement_falls_back_to_fullscreen(monkeypatch) -> None:
    """La base verrouille les valeurs (CHECK), mais le code ne doit pas supposer qu'elle a
    toujours raison : un mode inconnu retombe sur le plein écran, qui est le mode VENDU."""
    monkeypatch.setattr(ws, "_inject_campaign_items",
                        _fake_inject({"id_item": 99, "campaign": {"id_campaign": 7, "id_creative": 3}}))
    for bogus in ("", None, "n_importe_quoi"):
        out = await ws._inject_campaign_items_multizone(
            None, SimpleNamespace(id_player=1), _items(), datetime.now(timezone.utc), _Tpl(bogus))
        assert [i for i in out if i.get("campaign")][0]["campaign"]["fullscreen"] is True


def test_the_multizone_exclusion_is_really_gone() -> None:
    """Anti-régression : la garde `not is_multizone` avait coupé l'injection pendant des
    mois, avec un commentaire « backlog » qui la faisait passer pour un choix.

    Une garde comme celle-là se ré-ajoute facilement « pour débugger » et ne se remarque
    pas : rien ne casse, des écrans cessent simplement d'être servis pendant qu'on continue
    de les facturer. On la fige donc dans le sens INVERSE.
    """
    import inspect

    src = inspect.getsource(ws)
    assert "and not is_multizone" not in src, (
        "l'exclusion du multi-zones est revenue : les écrans concernés seraient de nouveau "
        "vendables mais jamais servis"
    )
    # Et les deux chemins existent bien, côte à côte.
    # ⚠️ On s'ancre sur le COMMENTAIRE de la section 4d : `if active_event is None:` apparaît
    # ailleurs dans le fichier (résolution des cibles), et chercher la première occurrence
    # faisait échouer ce test sur un code parfaitement juste.
    i = src.index("4d. Retail Media")
    bloc = src[i:i + 1400]
    assert "_inject_campaign_items_multizone(" in bloc
    assert "if not is_multizone:" in bloc
