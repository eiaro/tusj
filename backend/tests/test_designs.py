"""Designs from the label editor: format, rendering, publishing and printing."""
import io
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

import design
from media import DOTS_PER_MM, Media
from tests.test_inventree import inventree, qr_payloads  # noqa: F401 (fixtures)

EXAMPLES = Path(__file__).resolve().parent.parent / "example_designs"


def simple(**overrides) -> dict:
    d = {
        "name": {"en": "Jar", "nb": "Glass"},
        "icon": "🫙",
        "media": "62",
        "length_mm": 20,
        "fields": [
            {"id": "title", "type": "text", "label": "Title", "required": True},
            {"id": "note", "type": "text", "label": "Note"},
        ],
        "elements": [
            {"type": "text", "x": 2, "y": 2, "w": 50, "h": 8, "text": "{title}", "size": 20, "bold": True},
            {"type": "text", "x": 2, "y": 11, "w": 50, "h": 6, "text": {"en": "Note: {note}", "nb": "Merk: {note}"}},
            {"type": "rect", "x": 0.5, "y": 0.5, "w": 57, "h": 19, "stroke": 0.5},
        ],
    }
    return {**d, **overrides}


def png(response) -> Image.Image:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    return Image.open(io.BytesIO(response.content))


def test_examples_are_valid():
    for path in EXAMPLES.glob("*.json"):
        design.validate(json.loads(path.read_text(encoding="utf-8")))


def test_preview_has_the_exact_label_size(client):
    img = png(client.post("/designs/preview", json={"design": simple(), "values": {"title": "Salt"}}))
    assert img.size == (Media.from_label("62").width_px, round(20 * DOTS_PER_MM))


def test_unnamed_design_previews_but_does_not_save(client):
    d = simple(name={"en": "", "nb": ""})
    assert png(client.post("/designs/preview", json={"design": d})).size[0] > 0
    assert client.post("/designs/values", json={"design": d}).json()["title"]
    assert client.put("/designs/jar", json=d).status_code == 400


def test_preview_fills_in_sample_text_and_values(client):
    sample = client.post("/designs/preview", json={"design": simple(), "values": {}}).content
    typed = client.post("/designs/preview", json={"design": simple(), "values": {"title": "Salt"}}).content
    assert sample != typed


def test_empty_placeholder_hides_the_element():
    media = Media.from_label("62")
    d = design.validate(simple())
    without = design.render(d, {"title": "Salt", "note": ""}, media)
    with_note = design.render(d, {"title": "Salt", "note": "Coarse"}, media)
    assert without.tobytes() != with_note.tobytes()
    assert design.fill("Note: {note}", {"note": ""}) is None
    assert design.fill("{typo} and {title}", {"title": "Salt"}) == "{typo} and Salt"


def test_text_per_language(client):
    values = {"title": "Salt", "note": "x"}
    en = client.post("/designs/preview?lang=en", json={"design": simple(), "values": values}).content
    nb = client.post("/designs/preview?lang=nb", json={"design": simple(), "values": values}).content
    assert en != nb


def test_text_is_clipped_to_its_box():
    media = Media.from_label("62")
    d = design.validate(simple(elements=[
        {"type": "text", "x": 10, "y": 5, "w": 10, "h": 5, "text": "W" * 200, "size": 40, "fit": "none"}]))
    img = design.render(d, {"title": "x"}, media).convert("L")
    box = (round(10 * DOTS_PER_MM), round(5 * DOTS_PER_MM), round(20 * DOTS_PER_MM), round(10 * DOTS_PER_MM))
    outside = img.crop((0, 0, img.width, box[1] - 2))
    assert outside.getextrema() == (255, 255), "nothing drawn above the box"
    assert img.crop(box).getextrema()[0] == 0, "text drawn inside the box"


def test_landscape_is_turned_for_the_printer(client):
    d = simple(orientation="landscape", length_mm=80, elements=[])
    as_seen = png(client.post("/designs/preview?as_designed=true", json={"design": d}))
    printed = png(client.post("/designs/preview", json={"design": d}))
    width = Media.from_label("62").width_px
    assert printed.size == (width, round(80 * DOTS_PER_MM))
    assert as_seen.size == (round(80 * DOTS_PER_MM), width)


def test_die_cut_label_has_the_label_size(client):
    d = simple(media="29x90", elements=[{"type": "text", "x": 1, "y": 1, "w": 20, "h": 10, "text": "{title}"}])
    del d["length_mm"]
    media = Media.from_label("29x90")
    assert png(client.post("/designs/preview", json={"design": d})).size == (media.width_px, media.height_px)


@pytest.mark.parametrize("change, code", [
    ({"elements": [{"type": "circle", "x": 0, "y": 0, "w": 1, "h": 1}]}, "invalid_design"),
    ({"elements": [{"type": "text", "x": 0, "y": 0, "w": 0, "h": 1}]}, "invalid_design"),
    ({"fields": [{"id": "Bad Id", "type": "text", "label": "x"}]}, "invalid_design"),
    ({"fields": [{"id": "a", "type": "text", "label": "x"}, {"id": "a", "type": "text", "label": "y"}]},
     "invalid_design"),
    ({"media": "nope"}, "unknown_media"),
    ({"length_mm": None}, "invalid_design"),
])
def test_invalid_designs_are_refused(client, change, code):
    r = client.post("/designs/preview", json={"design": simple(**change)})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, code)


def test_qr_too_small_is_reported(client):
    d = simple(elements=[{"type": "qr", "x": 1, "y": 1, "w": 2, "h": 2, "data": "x" * 300}])
    r = client.post("/designs/preview", json={"design": d})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "qr_too_small")


def test_publish_list_print_and_delete(client, designs_dir, sent_jobs):
    assert client.get("/designs").json() == []
    r = client.put("/designs/jar", json=simple())
    assert r.status_code == 200 and r.json()["id"] == "jar"
    assert json.loads((designs_dir / "jar.json").read_text(encoding="utf-8"))["name"] == {"en": "Jar", "nb": "Glass"}
    assert [d["id"] for d in client.get("/designs").json()] == ["jar"]

    types = {lt["id"]: lt for lt in client.get("/label-types").json()}
    jar = types["designs.jar"]
    assert jar["media"]["id"] == "62" and jar["media_ok"] is True
    assert [f["id"] for f in jar["fields"]] == ["title", "note"]

    r = client.post("/print/designs.jar", json={"title": "Salt"})
    assert r.status_code == 200, r.text
    assert len(sent_jobs) == 1

    r = client.post("/print/designs.jar", json={})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "field_required")

    assert client.delete("/designs/jar").json() == {"ok": True}
    assert "designs.jar" not in {lt["id"] for lt in client.get("/label-types").json()}
    assert client.get("/designs/jar").status_code == 404


def test_design_for_other_media_is_not_offered(client):
    client.put("/designs/small", json=simple(media="29", length_mm=20, elements=[]))
    lt = next(lt for lt in client.get("/label-types").json() if lt["id"] == "designs.small")
    assert lt["media_ok"] is False
    r = client.post("/print/designs.small", json={"title": "x"})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "media_not_supported")


def test_bad_ids_are_refused(client):
    assert client.put("/designs/..%2Fescape", json=simple()).status_code in (400, 404)
    r = client.put("/designs/Bad Name", json=simple())
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "invalid_design_id")


def test_allergens_and_dates_are_formatted(client):
    d = simple(fields=[
        {"id": "made", "type": "date", "label": "Made", "default": "today"},
        {"id": "allergens", "type": "allergens", "label": "Allergens"},
    ], elements=[{"type": "text", "x": 1, "y": 1, "w": 55, "h": 15, "text": "{made} {allergens}"}])
    client.put("/designs/food", json=d)
    allergens = next(f for f in next(lt for lt in client.get("/label-types").json()
                                     if lt["id"] == "designs.food")["fields"] if f["id"] == "allergens")
    assert allergens["type"] == "multi-select" and len(allergens["options"]) == 14

    from builtin_plugins.designs import plugin
    values = plugin.values_for(design.validate(d), {"made": "2026-11-18", "allergens": ["milk", "eggs"]}, "nb")
    assert values["made"] == "18.11.2026"
    assert values["allergens"] == "Melk, Egg"


# --- Data sources (InvenTree) ---

def test_meta_lists_inventree_sources(client):
    meta = client.get("/designs/meta").json()
    sources = {s["id"]: s for s in meta["sources"]}
    assert {"inventree.part", "inventree.location", "inventree.stockitem"} <= set(sources)
    assert "barcode" in {v["id"] for v in sources["inventree.part"]["variables"]}
    assert any(m["id"] == "62" and m["endless"] for m in meta["media"])


def part_design() -> dict:
    return json.loads((EXAMPLES / "inventree-part.json").read_text(encoding="utf-8"))


def test_inventree_design_previews_with_samples(client, qr_payloads):
    png(client.post("/designs/preview", json={"design": part_design()}))
    assert qr_payloads == ['{"part": 12}']


def test_inventree_design_prints_a_real_part(inventree, client, sent_jobs, qr_payloads):  # noqa: F811
    client.put("/designs/part", json=part_design())
    lt = next(lt for lt in client.get("/label-types").json() if lt["id"] == "designs.part")
    assert lt["fields"][0]["id"] == "part" and lt["fields"][0]["type"] == "lookup"

    hits = client.get("/label-types/designs.part/search/part?q=resistor").json()
    assert [h["value"] for h in hits] == ["12", "13"]
    assert client.get("/designs/sources/inventree.part/search?q=10k").json()[0]["value"] == "12"

    # What an InvenTree machine driver would send: the part's id.
    r = client.post("/print/designs.part", json={"part": 12})
    assert r.status_code == 200, r.text
    assert qr_payloads == ["INV-PA12"]
    assert len(sent_jobs) == 1


def test_design_needs_its_data_source(client):
    client.put("/designs/part", json=part_design())
    client.put("/plugins/inventree", json={"enabled": False})
    assert "designs.part" not in {lt["id"] for lt in client.get("/label-types").json()}
    r = client.post("/designs/preview", json={"design": part_design()})
    assert (r.status_code, r.json()["detail"]["code"]) == (404, "data_source_not_found")


def test_examples_are_added_once(designs_dir, monkeypatch):
    monkeypatch.setattr(design, "EXAMPLES_DIR", EXAMPLES)
    design.add_examples()
    names = sorted(p.name for p in EXAMPLES.glob("*.json"))
    assert sorted(p.name for p in designs_dir.glob("*.json")) == names

    # A deleted example stays deleted, and an edited one is left alone.
    (designs_dir / names[0]).unlink()
    (designs_dir / names[1]).write_text("{}", encoding="utf-8")
    design.add_examples()
    assert not (designs_dir / names[0]).exists()
    assert (designs_dir / names[1]).read_text(encoding="utf-8") == "{}"


def test_values_show_what_each_placeholder_holds(client):
    r = client.post("/designs/values?lang=en", json={"design": simple(), "values": {"title": "Salt"}})
    assert r.status_code == 200, r.text
    values = r.json()
    assert values["title"] == "Salt"
    assert values["note"] == "Note"  # sample text until something is typed in
    assert values["today"]
