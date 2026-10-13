import socket
import threading

import pytest
import yaml
from fastapi.testclient import TestClient

import discovery
import main

TEST_CONFIG = {
    "printers": [
        {"id": "default", "name": "Kitchen", "driver": "brother_ql", "connection": "tcp://192.168.1.100",
         "model": "QL-820NWB", "media": "62"},
    ],
}


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """A throwaway config.yaml, so tests never touch the real one."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(TEST_CONFIG, sort_keys=False))
    monkeypatch.setattr(main, "CONFIG_FILE", path)
    return path


@pytest.fixture
def client(config_file):
    # The context manager runs startup, which loads and configures plugins.
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def sent_jobs(monkeypatch):
    """Capture print jobs instead of sending them to a printer."""
    import printers

    jobs = []

    def fake_send(**kwargs):
        jobs.append(kwargs)
        return {"outcome": "sent", "did_print": False}

    monkeypatch.setattr(printers, "send", fake_send)
    return jobs


@pytest.fixture(autouse=True)
def prints_dir(tmp_path, monkeypatch):
    """File printers write here instead of the repo's prints/."""
    import printers

    path = tmp_path / "prints"
    monkeypatch.setattr(printers, "PRINTS_DIR", path)
    return path


def _serve_tcp(host: str, port: int = 0) -> socket.socket:
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(16)

    def accept_loop():
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            conn.close()

    threading.Thread(target=accept_loop, daemon=True).start()
    return sock


def snmp_response(values: list[str | None], error_status: int = 0) -> bytes:
    """A GetResponse carrying `values` for discovery.OIDS, in order (None = noSuchObject)."""
    tlv, oid, integer = discovery._tlv, discovery._oid, discovery._int
    varbinds = b"".join(
        tlv(0x30, oid(o) + (tlv(0x04, v.encode()) if v is not None else b"\x80\x00"))
        for o, v in zip(discovery.OIDS.values(), values)
    )
    pdu = tlv(0xA2, integer(1) + integer(error_status) + integer(0) + tlv(0x30, varbinds))
    return tlv(0x30, integer(0) + tlv(0x04, b"public") + pdu)


class FakePrinter:
    """Listens on a TCP 'print port' and optionally answers SNMP like a Brother printer."""

    def __init__(self, host: str, snmp_values: list[str | None] | None, port: int = 0):
        self.host = host
        self.tcp = _serve_tcp(host, port)
        self.port = self.tcp.getsockname()[1]
        self.udp = None
        self.snmp_port = None
        if snmp_values is not None:
            self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp.bind((host, 0))
            self.snmp_port = self.udp.getsockname()[1]
            threading.Thread(target=self._snmp_loop, args=(snmp_response(snmp_values),), daemon=True).start()

    def _snmp_loop(self, response: bytes):
        while True:
            try:
                _, addr = self.udp.recvfrom(4096)
            except OSError:
                return
            self.udp.sendto(response, addr)

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    def close(self):
        self.tcp.close()
        if self.udp:
            self.udp.close()


@pytest.fixture
def fake_printer():
    """Factory: fake_printer(host="127.0.0.3", snmp=["name", "model", "descr"] or None, port=0)."""
    printers = []

    def make(host: str = "127.0.0.1", snmp: list[str | None] | None = None, port: int = 0) -> FakePrinter:
        p = FakePrinter(host, snmp, port)
        printers.append(p)
        return p

    yield make
    for p in printers:
        p.close()


@pytest.fixture(autouse=True)
def empty_job_log():
    main.jobs.clear()
