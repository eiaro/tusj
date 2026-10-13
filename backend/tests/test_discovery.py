import pytest

import discovery
from i18n import AppError
from tests.conftest import snmp_response


def test_snmp_request_matches_known_packet():
    # SNMPv1 GET sysDescr.0, community "public", request id 1
    known = bytes.fromhex("302602010004067075626c6963a019020101020100020100300e300c06082b060102010101000500")
    assert discovery.snmp_get_request(["1.3.6.1.2.1.1.1.0"]) == known


def test_oid_multibyte_arc():
    # 2435 (Brother's enterprise number) encodes as 0x93 0x03
    assert discovery._oid("1.3.6.1.4.1.2435.2") == bytes.fromhex("06082b06010401930302")


def test_snmp_parse_response():
    assert discovery.snmp_parse_response(snmp_response(["kitchen", "Brother QL-820NWB", "Brother NC-30w"])) == [
        "kitchen", "Brother QL-820NWB", "Brother NC-30w"]
    assert discovery.snmp_parse_response(snmp_response(["x", None, "Some printer"])) == ["x", None, "Some printer"]
    assert discovery.snmp_parse_response(snmp_response(["x", "y", "z"], error_status=2)) == []


def test_scan_finds_and_identifies_printers(fake_printer):
    brother = fake_printer("127.0.0.3", snmp=["BRW-kitchen", "Brother QL-820NWB", "Brother NC-30w"])
    # Another device with the same print port open but no SNMP agent
    fake_printer("127.0.0.5", port=brother.port)

    found = discovery.scan("127.0.0.0/29", port=brother.port, snmp_port=brother.snmp_port)

    assert found == [
        {"ip": "127.0.0.3", "name": "BRW-kitchen", "model": "Brother QL-820NWB", "brother": True},
        {"ip": "127.0.0.5", "name": None, "model": None, "brother": False},
    ]


@pytest.mark.parametrize(
    "subnet, code",
    [("8.8.8.0/24", "subnet_not_private"), ("10.0.0.0/16", "subnet_too_large"), ("nonsense", "invalid_subnet")],
)
def test_scan_rejects_bad_subnets(subnet, code):
    with pytest.raises(AppError) as e:
        discovery.scan(subnet)
    assert e.value.code == code


def test_default_subnet():
    assert discovery.default_subnet("192.168.1.100") == "192.168.1.0/24"
    assert discovery.default_subnet("10.0.0.7:9100") == "10.0.0.0/24"
    assert discovery.default_subnet("printer.local") == ""


def test_scan_api(client):
    assert client.get("/scan/default").json() == {"subnet": "192.168.1.0/24"}
    r = client.post("/scan", json={"subnet": "8.8.8.0/24"})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "subnet_not_private")
