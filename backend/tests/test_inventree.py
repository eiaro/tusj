"""The InvenTree plugin against a fake InvenTree API (httpx.MockTransport)."""
import json

import httpx
import pytest

import layout
import main
from media import Media
from registry import Registry

TOKEN = "inv-token"
PARTS = [
    {"pk": 12, "name": "Resistor 10k", "full_name": "Resistor 10k", "IPN": "R-10K", "description": "0603 1%",
     "active": True},
    {"pk": 13, "name": "Resistor 1k", "full_name": "Resistor 1k", "IPN": None, "description": "", "active": True},
]
LOCATIONS = [{"pk": 3, "name": "Drawer 3", "pathstring": "Workshop/Shelf A/Drawer 3"}]


class FakeInvenTree:
    def __init__(self, barcode_endpoint=True):
        self.barcode_endpoint = barcode_endpoint
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        self.calls.append((request.method, path))
        if request.headers.get("Authorization") != f"Token {TOKEN}":
            return httpx.Response(401, json={"detail": "Invalid token."})
        if path == "/api/user/me/":
            return httpx.Response(200, json={"username": "tester"})
        if path == "/api/part/":
            q = params.get("search", "").lower()
            hits = [p for p in PARTS if q in p["name"].lower()]
            return httpx.Response(200, json={"count": len(hits), "results": hits[: int(params.get("limit", 50))]})
        if path.startswith("/api/part/"):
            pk = int(path.split("/")[3])
            part = next((p for p in PARTS if p["pk"] == pk), None)
            return httpx.Response(200, json=part) if part else httpx.Response(404, json={"detail": "Not found."})
        if path == "/api/stock/location/":
            q = params.get("search", "").lower()
            return httpx.Response(200, json=[loc for loc in LOCATIONS if q in loc["name"].lower()])  # unpaginated
        if path.startswith("/api/stock/location/"):
            pk = int(path.split("/")[4])
            loc = next((x for x in LOCATIONS if x["pk"] == pk), None)
            return httpx.Response(200, json=loc) if loc else httpx.Response(404, json={"detail": "Not found."})
        if path == "/api/barcode/generate/" and self.barcode_endpoint:
            body = json.loads(request.content)
            prefix = {"part": "PA", "stocklocation": "SL"}[body["model"]]
            return httpx.Response(200, json={"barcode": f"INV-{prefix}{body['pk']}"})
        return httpx.Response(404, json={"detail": "Not found."})


@pytest.fixture
def inventree(monkeypatch, client, config_file):
    """Configure the real plugins/inventree against a fake server; returns (fake, client)."""
    fake = FakeInvenTree()
    registry = Registry()
    registry.load()
    registry.get("inventree").plugin.transport = httpx.MockTransport(fake)
    registry.configure({"inventree": {"settings": {"url": "https://inv.test/", "token": TOKEN}}})
    monkeypatch.setattr(main, "registry", registry)
    return fake


@pytest.fixture
def qr_payloads(monkeypatch):
    seen = []
    real = layout.qr_image

    def spy(data, *args, **kwargs):
        seen.append(data)
        return real(data, *args, **kwargs)

    monkeypatch.setattr(layout, "qr_image", spy)
    return seen


def test_not_configured(client):
    r = client.post("/preview/inventree.part", json={"part": "12"})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "inventree.not_configured")
    r = client.post("/plugins/inventree/check")
    assert r.json()["detail"]["code"] == "inventree.not_configured"


def test_label_types_and_settings(client):
    ids = [lt["id"] for lt in client.get("/label-types").json()]
    assert "inventree.part" in ids and "inventree.location" in ids
    plugin = next(p for p in client.get("/plugins").json() if p["id"] == "inventree")
    assert [s["id"] for s in plugin["settings_schema"]] == ["url", "token", "verify_tls"]
    assert plugin["checkable"] is True
    assert "auth_failed" in plugin["messages"]["nb"]["errors"]


def test_check(inventree, client):
    assert client.post("/plugins/inventree/check").json() == {"ok": True}


def test_wrong_token(inventree, client):
    main.registry.configure({"inventree": {"settings": {"url": "https://inv.test", "token": "nope"}}})
    r = client.post("/plugins/inventree/check")
    assert r.json()["detail"]["code"] == "inventree.auth_failed"


def test_unreachable(client, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    registry = Registry()
    registry.load()
    registry.get("inventree").plugin.transport = httpx.MockTransport(refuse)
    registry.configure({"inventree": {"settings": {"url": "https://inv.test", "token": TOKEN}}})
    monkeypatch.setattr(main, "registry", registry)
    r = client.post("/plugins/inventree/check")
    assert (r.status_code, r.json()["detail"]["code"]) == (502, "inventree.unreachable")


def test_search_parts(inventree, client):
    r = client.get("/label-types/inventree.part/search/part?q=resistor")
    assert r.json() == [
        {"value": "12", "label": "Resistor 10k", "description": "R-10K · 0603 1%"},
        {"value": "13", "label": "Resistor 1k"},
    ]
    assert client.get("/label-types/inventree.part/search/part?q=").json() == []


def test_search_locations_unpaginated(inventree, client):
    r = client.get("/label-types/inventree.location/search/location?q=drawer")
    assert r.json() == [{"value": "3", "label": "Drawer 3", "description": "Workshop/Shelf A/Drawer 3"}]


def test_part_label_uses_inventree_barcode_format(inventree, client, qr_payloads):
    r = client.post("/preview/inventree.part", json={"part": "12"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert qr_payloads == ["INV-PA12"]


def test_location_label(inventree, client, qr_payloads):
    assert client.post("/preview/inventree.location", json={"location": "3"}).status_code == 200
    assert qr_payloads == ["INV-SL3"]


def test_falls_back_to_json_barcode_on_old_inventree(inventree, client, qr_payloads):
    inventree.barcode_endpoint = False
    client.post("/preview/inventree.part", json={"part": "12"})
    client.post("/preview/inventree.location", json={"location": "3"})
    assert qr_payloads == ['{"part": 12}', '{"stocklocation": 3}']


def test_previews_are_cached(inventree, client):
    for _ in range(3):
        client.post("/preview/inventree.part", json={"part": "12", "description": "hide"})
    assert inventree.calls.count(("GET", "/api/part/12/")) == 1
    assert inventree.calls.count(("POST", "/api/barcode/generate/")) == 1


def test_unknown_part(inventree, client):
    r = client.post("/preview/inventree.part", json={"part": "999"})
    assert (r.status_code, r.json()["detail"]["code"]) == (404, "inventree.not_found")
    r = client.post("/preview/inventree.part", json={"part": "abc"})
    assert r.json()["detail"]["code"] == "inventree.not_found"


def test_print(inventree, client, sent_jobs):
    r = client.post("/print/inventree.part?lang=nb", json={"part": "12"})
    assert r.json() == {"status": "sent", "printer": "default", "label_type": "InvenTree-del", "copies": 1, "job": 1}
    assert len(sent_jobs) == 1


def test_needs_at_least_29mm():
    registry = Registry()
    registry.load()
    lt = next(t for t in registry.get("inventree").plugin.label_types() if t.id == "part")
    assert lt.media.accepts(Media.from_label("29"))
    assert not lt.media.accepts(Media.from_label("12"))
