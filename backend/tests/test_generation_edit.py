"""
Tests des capacités d'ÉDITION de génération (inspirées bylo.ai, 2026-06-25) :
détourage (suppression de fond) = modèle image `prompt_optional`+`no_image_size`.

Couvre la logique pure (payload réduit + extraction d'image `image` singulier) sans réseau.
"""

from app.services.generation import catalog, fal


# ── Catalogue ────────────────────────────────────────────────────────────────

def test_birefnet_is_an_edit_model():
    m = catalog.get_model("fal-ai/birefnet")
    assert m is not None
    assert m["kind"] == "image" and m["op"] == "edit"
    assert m["input"] == "image"          # exige une image de référence
    assert m["prompt_optional"] is True
    assert m["no_image_size"] is True


# ── Construction du payload ──────────────────────────────────────────────────

def test_edit_payload_omits_canvas_and_empty_prompt():
    m = catalog.get_model("fal-ai/birefnet")
    payload = fal._build_image_payload("", m, "16:9", {}, None, None)
    assert "image_size" not in payload      # le détourage préserve les dimensions
    assert "num_images" not in payload
    assert "prompt" not in payload          # prompt vide + prompt_optional → non envoyé


def test_generation_payload_keeps_canvas_and_prompt():
    m = catalog.get_model("fal-ai/flux/schnell")
    payload = fal._build_image_payload("un chat", m, "1:1", {}, None, None)
    assert payload["prompt"] == "un chat"
    assert payload["num_images"] == 1
    assert "image_size" in payload


# ── Extraction de l'image (réponses fal variables) ───────────────────────────

def test_extract_image_handles_images_array():
    assert fal._extract_image({"images": [{"url": "http://x/a.png"}]})["url"] == "http://x/a.png"


def test_extract_image_handles_single_image_key():
    # birefnet renvoie {"image": {...}} (singulier) au lieu du tableau `images`.
    assert fal._extract_image({"image": {"url": "http://x/cut.png"}})["url"] == "http://x/cut.png"


def test_extract_image_raises_when_missing():
    import pytest

    from app.services.generation import GenerationError
    with pytest.raises(GenerationError):
        fal._extract_image({"foo": "bar"})
