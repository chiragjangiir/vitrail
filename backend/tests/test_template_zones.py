"""Tests §25.4 — zones de template : bloc `template` du payload de sync.

`_build_template_block` est pur (pas de DB) : il découpe les items par `zone_index`
et calcule le wall-clock PAR zone. Un template mono-zone (ou sans zone) n'émet rien
(le player garde son chemin mono-zone : LAN/mpv/VOD intacts)."""


from app.api.v1.endpoints.ws import _build_template_block
from app.models.template import CmsTemplate


def _tmpl(zones):
    return CmsTemplate(
        id_template=7,
        id_org=1,
        template_name="T",
        layout={"layout_type": "split_v", "zones": zones},
    )


def _item(id_item, zone_index, duration_ms=3000):
    return {"id_item": id_item, "zone_index": zone_index, "duration_ms": duration_ms,
            "media": {"id_media": id_item}}


def test_single_zone_template_emits_nothing():
    """Un template à une seule zone = plein écran → pas de bloc multi-zones."""
    tmpl = _tmpl([{"index": 0, "x": 0, "y": 0, "w": 1920, "h": 1080, "label": "Main"}])
    assert _build_template_block(tmpl, [_item(1, 0)], "wall_clock", 0, 0) is None


def test_two_zones_split_items_by_zone_index():
    zones = [
        {"index": 0, "x": 0, "y": 0, "w": 960, "h": 1080, "label": "Left"},
        {"index": 1, "x": 960, "y": 0, "w": 960, "h": 1080, "label": "Right"},
    ]
    items = [_item(1, 0), _item(2, 1), _item(3, 0), _item(4, 1)]
    block = _build_template_block(_tmpl(zones), items, "loop", 0, 0)
    assert block is not None
    assert block["canvas_width"] == 1920 and block["canvas_height"] == 1080
    assert block["layout_type"] == "split_v"
    z0, z1 = block["zones"]
    assert [it["id_item"] for it in z0["items"]] == [1, 3]
    assert [it["id_item"] for it in z1["items"]] == [2, 4]
    assert z0["x"] == 0 and z1["x"] == 960
    # sync_mode=loop → démarrage à 0 pour chaque zone
    assert z0["start_index"] == 0 and z0["start_offset_ms"] == 0


def test_wall_clock_per_zone_independent():
    """Chaque zone calcule son propre wall-clock sur SON sous-ensemble d'items."""
    zones = [
        {"index": 0, "x": 0, "y": 0, "w": 1920, "h": 540, "label": "Top"},
        {"index": 1, "x": 0, "y": 540, "w": 1920, "h": 540, "label": "Bottom"},
    ]
    # Zone 0 : 2 items de 3s (total 6s). Zone 1 : 1 item de 4s (total 4s).
    items = [_item(1, 0, 3000), _item(2, 0, 3000), _item(3, 1, 4000)]
    # now=7000ms après ref : zone0 → 7000 % 6000 = 1000 → index 0, offset 1000.
    #                          zone1 → 7000 % 4000 = 3000 → index 0, offset 3000.
    block = _build_template_block(_tmpl(zones), items, "wall_clock", 0, 7000)
    z0, z1 = block["zones"]
    assert (z0["start_index"], z0["start_offset_ms"]) == (0, 1000)
    assert (z1["start_index"], z1["start_offset_ms"]) == (0, 3000)


def test_custom_canvas_dimensions_emitted():
    """La résolution/orientation du canvas (portrait 1080×1920) est propagée au bloc."""
    zones = [
        {"index": 0, "x": 0, "y": 0, "w": 1080, "h": 960, "label": "Top"},
        {"index": 1, "x": 0, "y": 960, "w": 1080, "h": 960, "label": "Bottom"},
    ]
    tmpl = CmsTemplate(
        id_template=7, id_org=1, template_name="Portrait",
        layout={"layout_type": "split_h", "canvas_width": 1080,
                "canvas_height": 1920, "zones": zones},
    )
    block = _build_template_block(tmpl, [_item(1, 0), _item(2, 1)], "loop", 0, 0)
    assert block["canvas_width"] == 1080 and block["canvas_height"] == 1920


def test_layout_config_preserves_canvas():
    """Le schéma LayoutConfig conserve canvas_width/height (pas droppés à la sauvegarde)."""
    from app.schemas.template import LayoutConfig
    lc = LayoutConfig(**{"layout_type": "full", "canvas_width": 3840,
                         "canvas_height": 2160, "zones": []})
    d = lc.model_dump()
    assert d["canvas_width"] == 3840 and d["canvas_height"] == 2160


def test_orphan_items_dropped():
    """Un item pointant une zone inexistante (zone supprimée) est ignoré, pas crashé."""
    zones = [
        {"index": 0, "x": 0, "y": 0, "w": 960, "h": 1080, "label": "L"},
        {"index": 1, "x": 960, "y": 0, "w": 960, "h": 1080, "label": "R"},
    ]
    items = [_item(1, 0), _item(2, 5)]  # zone_index=5 n'existe pas
    block = _build_template_block(_tmpl(zones), items, "loop", 0, 0)
    all_ids = [it["id_item"] for z in block["zones"] for it in z["items"]]
    assert all_ids == [1]
