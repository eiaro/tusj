from datetime import date

import pytest

import label
from i18n import AppError

PREMADE = {
    "name": "Premade",
    "style": "info",
    "fields": [
        {"id": "title", "type": "text", "label": {"en": "Title", "nb": "Tittel"}, "required": True},
        {"id": "made", "type": "date", "label": "Made", "default": "today"},
        {"id": "expires", "type": "date-presets", "label": "Expires", "required": True, "presets": ["+1w"]},
        {"id": "allergens", "type": "allergens", "label": "Allergens"},
    ],
}

JAR = {
    "name": "Jar",
    "style": "container",
    "fields": [{"id": "name", "type": "text", "label": "Name", "required": True}],
}

TODAY = date(2026, 1, 31)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("today", TODAY),
        ("+3d", date(2026, 2, 3)),
        ("+2w", date(2026, 2, 14)),
        ("+1m", date(2026, 2, 28)),  # clamped to the end of February
        ("+13m", date(2027, 2, 28)),
        ("+1y", date(2027, 1, 31)),
        ("2026-05-01", date(2026, 5, 1)),
    ],
)
def test_resolve_date(value, expected):
    assert label.resolve_date(value, TODAY) == expected


@pytest.mark.parametrize("value", ["soon", "+3x", "31.01.2026", ""])
def test_resolve_date_rejects_garbage(value):
    with pytest.raises(AppError) as e:
        label.resolve_date(value, TODAY)
    assert e.value.code == "invalid_date"


def test_resolve_fields_applies_defaults_and_drops_empty():
    resolved = label.resolve_fields(PREMADE, {"title": "Soup", "expires": "+1w", "allergens": []})
    by_id = {spec["id"]: value for spec, value in resolved}
    assert by_id["title"] == "Soup"
    assert by_id["made"] == date.today()
    assert "allergens" not in by_id


def test_required_field_error_uses_localized_label():
    with pytest.raises(AppError) as e:
        label.resolve_fields(PREMADE, {"expires": "+1w"}, lang="nb")
    assert e.value.code == "field_required"
    assert e.value.params == {"field": "Tittel"}


def test_render_is_full_width_and_grows_with_content():
    short = label.render(PREMADE, {"title": "Soup", "expires": "+1w"})
    long = label.render(PREMADE, {"title": "Soup " * 12, "expires": "+1w", "allergens": ["milk", "celery"]})
    assert short.width == long.width == label.DEFAULT_MEDIA.width_px
    assert long.height > short.height


@pytest.mark.parametrize("border", [None, "none", "simple", "double", "ornate"])
def test_render_borders(border):
    image = label.render({**JAR, "border": border}, {"name": "Cumin"})
    assert image.width == label.DEFAULT_MEDIA.width_px


def test_unknown_border_is_rejected():
    with pytest.raises(ValueError):
        label.render({**JAR, "border": "zigzag"}, {"name": "Cumin"})


def test_allergen_names_are_translated():
    assert label.allergen_name("milk", "en") == "Milk"
    assert label.allergen_name("milk", "nb") == "Melk"
    assert label.allergen_name("unknown-id", "nb") == "unknown-id"


def test_allergen_ids_are_unique_and_translated():
    allergens = label.load_allergens()
    assert len(allergens) == 14
    assert len({a["id"] for a in allergens}) == 14
    assert all({"en", "nb"} <= a["name"].keys() for a in allergens)
