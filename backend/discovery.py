"""Find printers on the LAN: scan a subnet for the raw print port, then ask each hit for its
model over SNMP. Unicast only, so it works from inside a NAT'ed container where broadcast
and mDNS don't reach the LAN."""
import ipaddress
import itertools
import socket
from concurrent.futures import ThreadPoolExecutor

from i18n import AppError

PRINT_PORT = 9100
MAX_HOSTS = 1024

# sysName.0 and hrDeviceDescr.1 (Brother reports e.g. "Brother QL-820NWB" there), sysDescr.0
OIDS = {
    "name": "1.3.6.1.2.1.1.5.0",
    "model": "1.3.6.1.2.1.25.3.2.1.3.1",
    "description": "1.3.6.1.2.1.1.1.0",
}


def parse_subnet(subnet: str) -> ipaddress.IPv4Network:
    try:
        net = ipaddress.IPv4Network(subnet.strip(), strict=False)
    except ValueError:
        raise AppError(400, "invalid_subnet", f"Invalid subnet: '{subnet}'", subnet=subnet)
    if not net.is_private:
        raise AppError(400, "subnet_not_private", "Only private networks can be scanned")
    if net.num_addresses > MAX_HOSTS:
        raise AppError(400, "subnet_too_large", f"Subnet too large (max {MAX_HOSTS} addresses, e.g. a /24)", max=MAX_HOSTS)
    return net


def default_subnet(printer_address: str) -> str:
    """The /24 around the configured printer address, if it is an IPv4 address."""
    host = printer_address.partition(":")[0]
    try:
        return str(ipaddress.IPv4Network(f"{host}/24", strict=False))
    except ValueError:
        return ""


# --- Minimal SNMPv1 GET (BER encoding) ---

def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _len(len(value)) + value


def _int(n: int) -> bytes:
    return _tlv(0x02, n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))


def _oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.split(".")]
    out = bytearray([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        chunk = [p & 0x7F]
        while p := p >> 7:
            chunk.append(0x80 | (p & 0x7F))
        out += bytes(reversed(chunk))
    return _tlv(0x06, bytes(out))


def snmp_get_request(oids: list[str], community: str = "public", request_id: int = 1) -> bytes:
    varbinds = b"".join(_tlv(0x30, _oid(o) + b"\x05\x00") for o in oids)
    pdu = _tlv(0xA0, _int(request_id) + _int(0) + _int(0) + _tlv(0x30, varbinds))
    return _tlv(0x30, _int(0) + _tlv(0x04, community.encode()) + pdu)


def _read_tlv(data: bytes, i: int) -> tuple[int, bytes, int]:
    tag, n = data[i], data[i + 1]
    i += 2
    if n & 0x80:
        size = n & 0x7F
        n = int.from_bytes(data[i:i + size], "big")
        i += size
    return tag, data[i:i + n], i + n


def _children(data: bytes):
    i = 0
    while i < len(data):
        tag, value, i = _read_tlv(data, i)
        yield tag, value


def snmp_parse_response(data: bytes) -> list[str | None]:
    """Values of the varbinds in a GetResponse, in order; None for non-string/missing values."""
    _, message, _ = _read_tlv(data, 0)
    _, _, pdu = list(_children(message))
    pdu_fields = list(_children(pdu[1]))
    _, error_status = pdu_fields[1]
    if int.from_bytes(error_status, "big") != 0:
        return []
    values = []
    for _, varbind in _children(pdu_fields[3][1]):
        _, (tag, value) = list(_children(varbind))
        values.append(value.decode("utf-8", "replace").strip() if tag == 0x04 else None)
    return values


def snmp_get(host: str, oids: list[str], timeout: float = 1.0, port: int = 161) -> list[str | None]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(snmp_get_request(oids), (host, port))
        data, _ = s.recvfrom(4096)
    return snmp_parse_response(data)


# --- Scan ---

def _port_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _identify(host: str, snmp_port: int) -> dict:
    info = {"ip": host, "name": None, "model": None}
    try:
        values = snmp_get(host, list(OIDS.values()), port=snmp_port)
        found = dict(itertools.zip_longest(OIDS, values))
        info["name"] = found["name"] or None
        info["model"] = found["model"] or found["description"] or None
    except (OSError, ValueError, IndexError):
        pass  # SNMP off or unparseable; the open print port is still worth listing
    info["brother"] = "brother" in (info["model"] or "").lower()
    return info


def scan(subnet: str, port: int = PRINT_PORT, timeout: float = 0.6, snmp_port: int = 161) -> list[dict]:
    net = parse_subnet(subnet)
    hosts = [str(h) for h in (net.hosts() if net.num_addresses > 2 else net)]
    with ThreadPoolExecutor(max_workers=128) as pool:
        open_hosts = [h for h, ok in zip(hosts, pool.map(lambda h: _port_open(h, port, timeout), hosts)) if ok]
        found = list(pool.map(lambda h: _identify(h, snmp_port), open_hosts))
    # Brother printers first, then by address.
    return sorted(found, key=lambda d: (not d["brother"], ipaddress.IPv4Address(d["ip"])))
