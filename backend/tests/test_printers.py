"""Printers: config migration, CRUD API, drivers, default printer per plugin, queueing."""
import io
import threading
import time

import pytest
import yaml
from PIL import Image

import main
import printers

FILE_PRINTER = {"name": "Arkiv (PNG)", "driver": "file", "media": "29"}


def _config(config_file):
    return yaml.safe_load(config_file.read_text())


# --- Config migration ---

def test_old_single_printer_config_is_migrated(client, config_file):
    config_file.write_text(yaml.safe_dump({
        "printer": {"ip": "192.168.1.50", "width_mm": 62, "model": "QL-820NWB", "label": "62"},
    }))
    assert client.get("/printers").json() == [{
        "id": "default", "name": "QL-820NWB", "driver": "brother_ql", "connection": "tcp://192.168.1.50",
        "model": "QL-820NWB", "media": "62", "media_info": {"tape_mm": 62, "endless": True},
    }]
    # Reading doesn't rewrite the file; the next save does.
    assert "printer" in _config(config_file)
    client.post("/printers", json=FILE_PRINTER)
    saved = _config(config_file)
    assert "printer" not in saved and [p["id"] for p in saved["printers"]] == ["default", "arkiv-png"]


# --- Options and validation ---

def test_options(client):
    options = client.get("/printers/options").json()
    assert options["drivers"] == ["brother_ql", "file"]
    assert "QL-820NWB" in options["models"]
    media = {m["id"]: m for m in options["media"]}
    assert media["62"] == {"id": "62", "tape_mm": 62, "length_mm": None, "endless": True, "two_color": False,
                           "supported": True}
    assert media["62red"]["two_color"] is True
    assert media["62x29"]["supported"] is False


BROTHER = {"name": "Verksted", "driver": "brother_ql", "connection": "tcp://10.0.0.5", "model": "QL-700",
           "media": "62"}


@pytest.mark.parametrize("change, code", [
    ({"name": " "}, "printer_name_required"),
    ({"driver": "zebra"}, "unknown_driver"),
    ({"media": "63"}, "unknown_media"),
    ({"model": "QL-9000"}, "unknown_model"),
    ({"connection": "10.0.0.5"}, "invalid_connection"),
    ({"connection": "http://10.0.0.5"}, "invalid_connection"),
    ({"connection": "tcp://300.1.1.1"}, "invalid_host"),
    ({"connection": "tcp://10.0.0.5:99999"}, "invalid_port"),
    ({"connection": "tcp://a/b"}, "invalid_host"),
    ({"connection": "usb://04f9:209d"}, "invalid_connection"),
    ({"connection": "file:///etc/passwd"}, "invalid_connection"),
])
def test_invalid_printers_are_rejected(client, config_file, change, code):
    before = config_file.read_text()
    r = client.post("/printers", json={**BROTHER, **change})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, code)
    assert config_file.read_text() == before


@pytest.mark.parametrize("connection", [
    "tcp://10.0.0.5", "tcp://printer.local:9100", "usb://0x04f9:0x209d", "usb://0x04f9:0x209d/000F1Z401370",
    "file:///dev/usb/lp0",
])
def test_valid_connections(client, connection):
    r = client.post("/printers", json={**BROTHER, "connection": connection})
    assert r.status_code == 200 and r.json()["connection"] == connection


def test_file_printer_needs_no_connection_or_model(client):
    r = client.post("/printers", json={**FILE_PRINTER, "connection": "ignored", "model": "ignored"})
    assert r.json() == {"id": "arkiv-png", "name": "Arkiv (PNG)", "driver": "file", "media": "29",
                        "media_info": {"tape_mm": 29, "endless": True}}


# --- CRUD ---

def test_ids_are_unique_slugs(client):
    ids = [client.post("/printers", json={**FILE_PRINTER, "name": "Kjøkken på loftet"}).json()["id"] for _ in range(3)]
    assert ids == ["kjokken-pa-loftet", "kjokken-pa-loftet-2", "kjokken-pa-loftet-3"]


def test_update_printer(client, config_file):
    r = client.put("/printers/default", json={**BROTHER, "name": "Kjøkken", "connection": "tcp://192.168.1.50"})
    assert r.json()["id"] == "default" and r.json()["connection"] == "tcp://192.168.1.50"
    assert _config(config_file)["printers"][0]["name"] == "Kjøkken"
    r = client.put("/printers/nope", json=BROTHER)
    assert (r.status_code, r.json()["detail"]["code"]) == (404, "printer_not_found")


def test_delete_printer_and_clean_plugin_defaults(client, config_file):
    client.post("/printers", json=FILE_PRINTER)
    client.put("/plugins/quick_label", json={"printer": "arkiv-png"})
    assert client.delete("/printers/arkiv-png").json() == {"ok": True}
    config = _config(config_file)
    assert [p["id"] for p in config["printers"]] == ["default"]
    assert "printer" not in config["plugins"]["quick_label"]


def test_last_printer_cannot_be_deleted(client):
    r = client.delete("/printers/default")
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "last_printer")


# --- Testing connections ---

def test_test_network_printer(client, fake_printer):
    p = fake_printer()
    assert client.post("/printers/test", json={**BROTHER, "connection": f"tcp://{p.address}"}).json() == {"ok": True}
    r = client.post("/printers/test", json={**BROTHER, "connection": "tcp://127.0.0.1:1"})
    assert (r.status_code, r.json()["detail"]["code"]) == (502, "printer_unreachable")


def test_test_missing_lp_device(client):
    r = client.post("/printers/test", json={**BROTHER, "connection": "file:///dev/usb/lp9"})
    assert r.json()["detail"]["code"] == "printer_unreachable"


def test_test_usb_without_device(client, monkeypatch):
    import usb.core

    monkeypatch.setattr(usb.core, "find", lambda **kw: None)
    r = client.post("/printers/test", json={**BROTHER, "connection": "usb://0x04f9:0x209d"})
    assert r.json()["detail"]["code"] == "printer_unreachable"

    def no_backend(**kw):
        raise usb.core.NoBackendError("No backend available")

    monkeypatch.setattr(usb.core, "find", no_backend)
    r = client.post("/printers/test", json={**BROTHER, "connection": "usb://0x04f9:0x209d"})
    assert r.json()["detail"]["code"] == "usb_unavailable"


def test_test_file_printer(client):
    assert client.post("/printers/test", json=FILE_PRINTER).json() == {"ok": True}


# --- Printing ---

def test_file_printer_saves_png(client, prints_dir):
    client.post("/printers", json=FILE_PRINTER)
    r = client.post("/print/quick_label.text?printer=arkiv-png", json={"title": "Batteries"})
    body = r.json()
    assert body["status"] == "saved" and body["printer"] == "arkiv-png"
    files = list((prints_dir / "arkiv-png").glob("*.png"))
    assert len(files) == 1 and files[0].name.endswith("_quick-label-text.png")


def test_default_printer_per_plugin_and_override(client, sent_jobs, prints_dir):
    client.post("/printers", json=FILE_PRINTER)
    assert client.put("/plugins/quick_label", json={"printer": "arkiv-png"}).json()["printer"] == "arkiv-png"

    types = {lt["id"]: lt for lt in client.get("/label-types").json()}
    assert types["quick_label.text"]["printer"] == "arkiv-png"
    assert types["templates.spice_jar"]["printer"] == "default"

    assert client.post("/print/quick_label.text", json={"title": "A"}).json()["printer"] == "arkiv-png"
    assert client.post("/print/templates.spice_jar", json={"name": "B"}).json()["printer"] == "default"
    assert client.post("/print/quick_label.text?printer=default", json={"title": "C"}).json()["printer"] == "default"
    assert len(sent_jobs) == 2

    # Back to "first printer"
    assert client.put("/plugins/quick_label", json={"printer": None}).json()["printer"] is None
    r = client.put("/plugins/quick_label", json={"printer": "nope"})
    assert r.json()["detail"]["code"] == "printer_not_found"


def test_preview_uses_the_printers_media(client):
    client.post("/printers", json=FILE_PRINTER)  # 29 mm
    wide = client.post("/preview/quick_label.text?printer=default", json={"title": "Hello"})
    narrow = client.post("/preview/quick_label.text?printer=arkiv-png", json={"title": "Hello"})
    assert float(wide.headers["x-label-tape-mm"]) == 62
    assert float(narrow.headers["x-label-tape-mm"]) == 29


def test_label_type_too_wide_for_printer(client):
    client.post("/printers", json={**FILE_PRINTER, "media": "12"})
    r = client.post("/preview/inventree.part?printer=arkiv-png", json={"part": "1"})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "media_not_supported")


def test_unknown_printer(client):
    r = client.post("/preview/quick_label.text?printer=nope", json={"title": "x"})
    assert (r.status_code, r.json()["detail"]["code"]) == (404, "printer_not_found")


# --- Brother driver details ---

@pytest.mark.parametrize("connection, backend", [
    ("tcp://10.0.0.5", "network"), ("usb://0x04f9:0x209d", "pyusb"), ("file:///dev/usb/lp0", "linux_kernel"),
])
def test_backend_selection(connection, backend):
    assert printers.BrotherQLDriver({**BROTHER, "id": "x", "connection": connection}).backend == backend


def test_usb_status_is_reported(client, monkeypatch, config_file):
    client.put("/printers/default", json={**BROTHER, "connection": "usb://0x04f9:0x209d"})

    monkeypatch.setattr(printers, "send", lambda **kw: {"outcome": "printed", "did_print": True})
    assert client.post("/print/quick_label.text", json={"title": "x"}).json()["status"] == "printed"

    monkeypatch.setattr(printers, "send", lambda **kw: {
        "outcome": "error", "did_print": False, "printer_state": {"errors": ["No media when printing"]}})
    r = client.post("/print/quick_label.text", json={"title": "x"})
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "printer_error"
    assert r.json()["detail"]["params"] == {"errors": "No media when printing"}


@pytest.mark.parametrize("model, min_length", [("QL-820NWB", 150), ("QL-500", 295)])
def test_short_labels_are_padded_to_the_printers_minimum(client, sent_jobs, model, min_length):
    client.put("/printers/default", json={**BROTHER, "model": model})
    r = client.post("/preview/quick_label.text", json={"title": "x"})

    assert Image.open(io.BytesIO(r.content)).height == min_length
    assert client.post("/print/quick_label.text", json={"title": "x"}).status_code == 200


def test_file_printer_keeps_short_labels(client, prints_dir):
    client.post("/printers", json=FILE_PRINTER)
    r = client.post("/preview/quick_label.text?printer=arkiv-png", json={"title": "x"})

    assert Image.open(io.BytesIO(r.content)).height < 150


def test_jobs_to_one_printer_run_one_at_a_time(client, monkeypatch):
    active, overlap = [], []

    def slow_send(**kwargs):
        active.append(1)
        if len(active) > 1:
            overlap.append(True)
        time.sleep(0.05)
        active.pop()
        return {"outcome": "sent", "did_print": False}

    monkeypatch.setattr(printers, "send", slow_send)
    threads = [threading.Thread(target=lambda: client.post("/print/quick_label.text", json={"title": "x"}))
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlap == []


def test_scan_default_subnet_from_first_network_printer(client):
    assert client.get("/scan/default").json() == {"subnet": "192.168.1.0/24"}


def test_missing_config_starts_empty_and_is_created_on_save(client, config_file):
    config_file.unlink()
    assert client.get("/printers").json() == []
    assert client.get("/health").json()["printers"] == 0
    r = client.post("/preview/quick_label.text", json={"title": "x"})
    assert r.json()["detail"]["code"] == "no_printer"
    client.post("/printers", json=FILE_PRINTER)
    assert [p["id"] for p in yaml.safe_load(config_file.read_text())["printers"]] == ["arkiv-png"]


def test_config_path_that_is_a_directory(client, config_file):
    config_file.unlink()
    config_file.mkdir()
    r = client.get("/printers")
    assert (r.status_code, r.json()["detail"]["code"]) == (500, "config_is_directory")
