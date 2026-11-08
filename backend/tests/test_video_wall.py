"""Tests — géométrie de mur d'écrans + compensation de bezel (service pur video_wall).

Couvre : paire panoramique 1×2 (cas validé HW bureau), 2×2 (joints H+V), gap_scale (fine-tune),
mono-écran (no-op), grille invalide, helper player_wall_rect + replis gracieux.
"""

import math

import pytest

from app.services.video_wall import (
    bezel_overscan,
    compute_wall_layout,
    player_wall_rect,
    player_wall_transform,
)


def _cell(row, col, w=528.0, h=297.0, bl=4.5, br=4.5, bt=4.5, bb=4.5):
    return {
        "row": row, "col": col, "panel_w_mm": w, "panel_h_mm": h,
        "bezel_left_mm": bl, "bezel_right_mm": br, "bezel_top_mm": bt, "bezel_bottom_mm": bb,
    }


# ── 1×2 paire panoramique (cas validé HW riri/fifi) ──────────────────────────

def test_panoramic_pair_1x2():
    cells = [_cell(0, 0), _cell(0, 1)]
    layout = compute_wall_layout(cols=2, rows=1, cells=cells)
    # canvas = 528 + 528 + (4.5+4.5) = 1065 mm ; chaque dalle = 528/1065 = 0.495775
    left, right = layout[(0, 0)], layout[(0, 1)]
    assert left["x"] == 0.0
    assert left["y"] == 0.0 and left["h"] == 1.0
    assert left["w"] == pytest.approx(528 / 1065, abs=1e-5)
    # le 2e écran démarre après sa dalle + le joint de 9 mm
    assert right["x"] == pytest.approx((528 + 9) / 1065, abs=1e-5)
    assert right["w"] == pytest.approx(528 / 1065, abs=1e-5)
    # la bande cachée (joint) = 9/1065 ≈ 0.845 % entre les deux
    hidden = right["x"] - (left["x"] + left["w"])
    assert hidden == pytest.approx(9 / 1065, abs=1e-5)


def test_pair_covers_full_height():
    layout = compute_wall_layout(2, 1, [_cell(0, 0), _cell(0, 1)])
    for rect in layout.values():
        assert rect["y"] == 0.0 and rect["h"] == 1.0


# ── 2×2 (joints horizontaux ET verticaux) ────────────────────────────────────

def test_grid_2x2_seams_both_axes():
    cells = [_cell(r, c) for r in range(2) for c in range(2)]
    layout = compute_wall_layout(cols=2, rows=2, cells=cells)
    # canvas_w = 1065, canvas_h = 297+297+9 = 603
    tl, tr, bl, br = layout[(0, 0)], layout[(0, 1)], layout[(1, 0)], layout[(1, 1)]
    assert tl["x"] == 0.0 and tl["y"] == 0.0
    assert tr["x"] == pytest.approx((528 + 9) / 1065, abs=1e-5)
    assert bl["y"] == pytest.approx((297 + 9) / 603, abs=1e-5)
    assert br["x"] == tr["x"] and br["y"] == bl["y"]
    # toutes les dalles ont la même taille normalisée
    for rect in layout.values():
        assert rect["w"] == pytest.approx(528 / 1065, abs=1e-5)
        assert rect["h"] == pytest.approx(297 / 603, abs=1e-5)


# ── gap_scale (slider de fine-tune) ──────────────────────────────────────────

def test_gap_scale_widens_seam():
    base = compute_wall_layout(2, 1, [_cell(0, 0), _cell(0, 1)], gap_scale=1.0)
    over = compute_wall_layout(2, 1, [_cell(0, 0), _cell(0, 1)], gap_scale=2.0)
    # plus de gap_scale → joint masqué plus large → 2e écran décalé plus loin
    assert over[(0, 1)]["x"] > base[(0, 1)]["x"]


def test_gap_scale_one_equals_default():
    a = compute_wall_layout(2, 1, [_cell(0, 0), _cell(0, 1)])
    b = compute_wall_layout(2, 1, [_cell(0, 0), _cell(0, 1)], gap_scale=1.0)
    assert a == b


# ── mono-écran : plein cadre, aucun joint ────────────────────────────────────

def test_single_screen_full_frame():
    layout = compute_wall_layout(1, 1, [_cell(0, 0)])
    assert layout[(0, 0)] == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}


def test_no_bezels_tiles_seamless():
    cells = [_cell(0, 0, bl=0, br=0), _cell(0, 1, bl=0, br=0)]
    layout = compute_wall_layout(2, 1, cells)
    # sans bezel : pas de bande cachée, jointif exact
    assert layout[(0, 1)]["x"] == pytest.approx(layout[(0, 0)]["w"], abs=1e-6)


# ── validation ───────────────────────────────────────────────────────────────

def test_invalid_grid_raises():
    with pytest.raises(ValueError):
        compute_wall_layout(0, 1, [_cell(0, 0)])


def test_no_valid_cells_raises():
    with pytest.raises(ValueError):
        compute_wall_layout(2, 1, [{"row": 5, "col": 9, "panel_w_mm": 100, "panel_h_mm": 100}])


def test_missing_panel_dims_raises():
    with pytest.raises(ValueError):
        compute_wall_layout(1, 1, [{"row": 0, "col": 0}])


# ── helper player_wall_rect (repli gracieux, ne lève jamais) ──────────────────

def test_player_wall_rect_ok():
    wall = {
        "cols": 2, "rows": 1,
        "cells": [_cell(0, 0), _cell(0, 1)],
        "cell": {"row": 0, "col": 1},
    }
    rect = player_wall_rect(wall)
    assert rect is not None
    assert rect["x"] == pytest.approx((528 + 9) / 1065, abs=1e-5)


def test_player_wall_rect_none_when_no_wall():
    assert player_wall_rect(None) is None
    assert player_wall_rect({}) is None
    assert player_wall_rect({"cols": 2, "rows": 1, "cells": []}) is None


def test_player_wall_rect_graceful_on_bad_cell():
    # cellule hors grille / mur incohérent → None (ne casse pas le sync)
    wall = {"cols": 2, "rows": 1, "cells": [_cell(0, 0)], "cell": {"row": 9, "col": 9}}
    assert player_wall_rect(wall) is None


# ── bezel_overscan (mode B, geste validé HW) ─────────────────────────────────

def test_overscan_pair_left_screen():
    # écran gauche d'une paire 1×2 : voisin à droite → ancre à gauche, overscan = bezel droit
    ov = bezel_overscan(rows=1, cols=2, row=0, col=0, panel_w_mm=528, panel_h_mm=297,
                        bezel_left_mm=4.5, bezel_right_mm=4.5)
    assert ov["mode"] == "overscan"
    assert ov["align_x"] == -1        # ancre gauche → pousse vers la droite (joint intérieur)
    assert ov["align_y"] == 0         # pas de voisin vertical
    assert ov["scale_x"] == pytest.approx(1 + 4.5 / 528, abs=1e-5)
    assert ov["scale_y"] == 1.0
    # zoom mpv attendu = log2(scale) ≈ 0.0122 (valeur validée bureau)
    assert math.log2(ov["scale_x"]) == pytest.approx(0.0122, abs=5e-4)


def test_overscan_right_screen_anchors_right():
    ov = bezel_overscan(1, 2, 0, 1, 528, 297, bezel_left_mm=4.5, bezel_right_mm=4.5)
    assert ov["align_x"] == 1         # voisin à gauche → ancre droite
    assert ov["scale_x"] == pytest.approx(1 + 4.5 / 528, abs=1e-5)


def test_overscan_middle_screen_centered():
    # écran central d'une ligne 1×3 : voisins des deux côtés → centré, overscan double
    ov = bezel_overscan(1, 3, 0, 1, 528, 297, bezel_left_mm=4.5, bezel_right_mm=4.5)
    assert ov["align_x"] == 0
    assert ov["scale_x"] == pytest.approx(1 + 9 / 528, abs=1e-5)   # bezel gauche + droit


def test_overscan_2x2_corner_two_axes():
    # coin haut-gauche d'un 2×2 : voisins à droite ET en bas → ancre haut-gauche, overscan x+y
    ov = bezel_overscan(2, 2, 0, 0, 528, 297, bezel_left_mm=4.5, bezel_right_mm=4.5,
                        bezel_top_mm=4.5, bezel_bottom_mm=4.5)
    assert ov["align_x"] == -1 and ov["align_y"] == -1
    assert ov["scale_x"] == pytest.approx(1 + 4.5 / 528, abs=1e-5)
    assert ov["scale_y"] == pytest.approx(1 + 4.5 / 297, abs=1e-5)


def test_overscan_gap_scale_increases():
    base = bezel_overscan(1, 2, 0, 0, 528, 297, bezel_right_mm=4.5)
    over = bezel_overscan(1, 2, 0, 0, 528, 297, bezel_right_mm=4.5, gap_scale=2.0)
    assert over["scale_x"] > base["scale_x"]


# ── player_wall_transform (dispatcher mode B / mode A) ────────────────────────

def test_wall_transform_overscan_default():
    wall = {"rows": 1, "cols": 2, "cell": {"row": 0, "col": 0},
            "panel_w_mm": 528, "panel_h_mm": 297, "bezel_left_mm": 4.5, "bezel_right_mm": 4.5}
    tf = player_wall_transform(wall)
    assert tf["mode"] == "overscan" and tf["align_x"] == -1


def test_wall_transform_crop_mode():
    wall = {"mode": "crop", "rows": 1, "cols": 2, "cell": {"row": 0, "col": 1},
            "cells": [_cell(0, 0), _cell(0, 1)]}
    tf = player_wall_transform(wall)
    assert tf["mode"] == "crop"
    assert "x" in tf and tf["x"] == pytest.approx((528 + 9) / 1065, abs=1e-5)


def test_wall_transform_none_when_absent_or_bad():
    assert player_wall_transform(None) is None
    assert player_wall_transform({}) is None
    # overscan sans dalle → None
    assert player_wall_transform({"rows": 1, "cols": 2, "cell": {"row": 0, "col": 0}}) is None
