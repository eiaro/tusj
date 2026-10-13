"""Copies, the job log, reprinting and health checks."""
import pytest

import main
import printers
from version import __version__

FILE_PRINTER = {"name": "Arkiv", "driver": "file", "media": "62"}


def test_copies_go_in_one_job_with_a_cut_each(client, sent_jobs, monkeypatch):
    converted = []
    real_convert = printers.convert

    def spy(**kwargs):
        converted.append(kwargs)
        return real_convert(**kwargs)

    monkeypatch.setattr(printers, "convert", spy)
    three = client.post("/print/quick_label.text?copies=3", json={"title": "x"})
    assert three.json()["copies"] == 3
    assert len(sent_jobs) == 1
    assert len(converted[0]["images"]) == 3 and converted[0]["cut"] is True


@pytest.mark.parametrize("copies", [0, -1, 51])
def test_copies_out_of_range(client, sent_jobs, copies):
    r = client.post(f"/print/quick_label.text?copies={copies}", json={"title": "x"})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "invalid_copies")
    assert r.json()["detail"]["params"] == {"max": 50}
    assert sent_jobs == []


def test_file_printer_names_copies(client, prints_dir):
    client.post("/printers", json=FILE_PRINTER)
    client.post("/print/quick_label.text?printer=arkiv&copies=4", json={"title": "x"})
    (png,) = (prints_dir / "arkiv").glob("*.png")
    assert png.name.endswith("_quick-label-text_x4.png")


def test_job_log(client, sent_jobs, monkeypatch):
    client.post("/print/templates.spice_jar?lang=nb", json={"name": "Spisskummen"})
    client.post("/print/quick_label.text?copies=2", json={"title": "Batteries"})

    def refuse(**kwargs):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(printers, "send", refuse)
    assert client.post("/print/quick_label.text", json={"title": "Fails"}).status_code == 502

    # Input errors are not print jobs
    client.post("/print/quick_label.text", json={})

    log = client.get("/jobs").json()
    assert [j["id"] for j in log] == [3, 2, 1]  # newest first
    failed, copies, first = log
    assert first["label_type"] == "templates.spice_jar"
    assert first["label_name"] == {"en": "Spice Jar", "nb": "Krydderglass"}
    assert first["values"] == {"name": "Spisskummen"} and first["lang"] == "nb"
    assert first["status"] == "sent" and first["error"] is None and first["printer"] == "default"
    assert copies["copies"] == 2
    assert failed["status"] is None and failed["error"]["code"] == "printer_unreachable"
    assert first["time"].endswith("+00:00")


def test_job_log_keeps_the_last_50(client, sent_jobs):
    log = main.jobs
    for i in range(55):
        log.add(label_type="x", label_name="x", values={}, lang="en", printer="default", copies=1, status="sent")
    assert len(client.get("/jobs").json()) == 50
    assert client.get("/jobs").json()[0]["id"] == 55


def test_reprint(client, sent_jobs):
    job = client.post("/print/quick_label.text?copies=2", json={"title": "Again"}).json()["job"]
    r = client.post(f"/jobs/{job}/reprint")
    assert r.status_code == 200 and r.json()["copies"] == 2 and r.json()["job"] == job + 1
    assert len(sent_jobs) == 2 and sent_jobs[0]["instructions"] == sent_jobs[1]["instructions"]

    r = client.post("/jobs/999/reprint")
    assert (r.status_code, r.json()["detail"]["code"]) == (404, "job_not_found")


def test_reprint_falls_back_when_the_printer_is_gone(client, sent_jobs, prints_dir):
    client.post("/printers", json=FILE_PRINTER)
    job = client.post("/print/quick_label.text?printer=arkiv", json={"title": "x"}).json()["job"]
    client.delete("/printers/arkiv")
    assert client.post(f"/jobs/{job}/reprint").json()["printer"] == "default"


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "version": __version__, "printers": 1, "plugin_errors": {}}


def test_printers_status(client, fake_printer, config_file):
    up = fake_printer()
    client.put("/printers/default", json={"name": "Up", "driver": "brother_ql", "connection": f"tcp://{up.address}",
                                         "model": "QL-820NWB", "media": "62"})
    client.post("/printers", json={"name": "Down", "driver": "brother_ql", "connection": "tcp://127.0.0.1:1",
                                   "model": "QL-820NWB", "media": "62"})
    client.post("/printers", json=FILE_PRINTER)
    status = {s["id"]: s for s in client.get("/printers/status").json()}
    assert status["default"] == {"id": "default", "ok": True, "error": None}
    assert status["down"]["ok"] is False and status["down"]["error"]["code"] == "printer_unreachable"
    assert status["arkiv"]["ok"] is True


def test_status_checks_run_in_parallel(monkeypatch):
    import time

    def slow_test(self):
        time.sleep(0.3)

    monkeypatch.setattr(printers.FileDriver, "test", slow_test)
    configs = [{"id": f"p{i}", "name": "p", "driver": "file", "media": "62"} for i in range(5)]
    start = time.monotonic()
    assert all(s["ok"] for s in printers.check_all(configs))
    assert time.monotonic() - start < 1.0
