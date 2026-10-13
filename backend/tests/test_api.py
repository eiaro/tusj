import yaml

PREMADE = "templates.premade_food"
JAR = "templates.spice_jar"
PREMADE_VALUES = {"title": "Blåbærsuppe", "expires": "2026-11-03", "allergens": ["milk", "celery"]}


def _types(client):
    return {lt["id"]: lt for lt in client.get("/label-types").json()}


def test_label_types(client):
    types = _types(client)
    assert {PREMADE, JAR, "quick_label.text"} <= set(types)
    for lt in types.values():
        assert lt["media_ok"] is True
        ids = [f["id"] for f in lt["fields"]]
        assert len(ids) == len(set(ids)), "field ids must be unique"

    premade = types[PREMADE]
    assert premade["plugin"] == "templates"
    assert premade["name"] == {"en": "Premade Food", "nb": "Ferdigmat"}
    assert premade["icon"] == "🍲"
    allergens = next(f for f in premade["fields"] if f["id"] == "allergens")
    assert allergens["type"] == "multi-select"
    assert len(allergens["options"]) == 14
    assert {"value": "milk", "label": {"en": "Milk", "nb": "Melk"}, "icon": "🥛"} in allergens["options"]


def test_languages(client):
    assert client.get("/languages").json() == ["en", "nb"]


def test_preview_returns_png_with_dimensions(client):
    r = client.post(f"/preview/{PREMADE}?lang=nb", json=PREMADE_VALUES)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert float(r.headers["x-label-tape-mm"]) == 62
    assert float(r.headers["x-label-printable-mm"]) == 58.9
    assert float(r.headers["x-label-feed-mm"]) == 3.0
    assert float(r.headers["x-label-length-mm"]) > 6


def test_preview_language_changes_the_label(client):
    en = client.post(f"/preview/{PREMADE}?lang=en", json=PREMADE_VALUES).content
    nb = client.post(f"/preview/{PREMADE}?lang=nb", json=PREMADE_VALUES).content
    assert en != nb


def test_errors_are_coded(client):
    r = client.post(f"/preview/{PREMADE}?lang=nb", json={"expires": "+1w"})
    assert r.status_code == 400
    assert r.json()["detail"] == {"code": "field_required", "message": "Field 'Tittel' is required",
                                  "params": {"field": "Tittel"}}

    r = client.post(f"/preview/{PREMADE}", json={"title": "x", "expires": "soon"})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "invalid_date")

    r = client.post("/preview/templates.nope", json={})
    assert (r.status_code, r.json()["detail"]["code"]) == (404, "label_type_not_found")


def test_print_sends_raster_to_configured_printer(client, sent_jobs):
    r = client.post(f"/print/{JAR}?lang=nb", json={"name": "Spisskummen"})
    assert r.json() == {"status": "sent", "printer": "default", "label_type": "Krydderglass", "copies": 1, "job": 1}
    assert len(sent_jobs) == 1
    job = sent_jobs[0]
    assert job["printer_identifier"] == "tcp://192.168.1.100"
    assert job["backend_identifier"] == "network"
    assert len(job["instructions"]) > 1000


def test_print_to_unreachable_printer(client, config_file):
    config = yaml.safe_load(config_file.read_text())
    config["printers"][0]["connection"] = "tcp://127.0.0.1:1"
    config_file.write_text(yaml.safe_dump(config))

    r = client.post(f"/print/{JAR}", json={"name": "Cumin"})
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "printer_unreachable"
    assert r.json()["detail"]["params"]["address"] == "127.0.0.1:1"


def test_quick_label_plugin(client):
    r = client.post("/preview/quick_label.text", json={"title": "Batteries", "qr": "https://example.com"})
    assert r.status_code == 200
    without_qr = client.post("/preview/quick_label.text", json={"title": "Batteries"})
    assert r.content != without_qr.content
