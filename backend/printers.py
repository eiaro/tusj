"""Configured printers: config handling, validation, drivers and one print queue per printer.

Config (config.yaml):

    printers:
      - id: kitchen
        name: Kitchen
        driver: brother_ql          # or "file"
        connection: tcp://192.168.1.100 # tcp://host[:port] | usb://0x04f9:0x209d[/serial] | file:///dev/usb/lp0
        model: QL-820NWB
        media: "62"
    plugins:
      inventree: {printer: kitchen} # default printer per plugin; else the first printer
"""
import ipaddress
import re
import socket
import threading
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from brother_ql.backends.helpers import send
from brother_ql.conversion import convert
from brother_ql.labels import FormFactor, LabelsManager
from brother_ql.models import ModelsManager
from brother_ql.raster import BrotherQLRaster
from PIL import Image

from i18n import AppError
from media import Media

PRINTS_DIR = Path(__file__).resolve().parent.parent / "prints"
DRIVERS = ("brother_ql", "file")
NETWORK_PORT = 9100

HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$")
USB_RE = re.compile(r"^usb://0x[0-9a-fA-F]{4}:0x[0-9a-fA-F]{4}(/[\w.-]+)?$")
LP_RE = re.compile(r"^file:///dev/usb/lp\d+$")


# --- Config ---

def migrate(config: dict) -> dict:
    """Turn the old single `printer:` section into a `printers:` list (in place)."""
    if "printers" not in config and isinstance(config.get("printer"), dict):
        old = config.pop("printer")
        config["printers"] = [{
            "id": "default",
            "name": old.get("model", "Printer"),
            "driver": "brother_ql",
            "connection": f"tcp://{old['ip']}",
            "model": old.get("model", "QL-820NWB"),
            "media": str(old.get("label", "62")),
        }]
    config.setdefault("printers", [])
    return config


def find(config: dict, printer_id: str) -> dict:
    for p in config["printers"]:
        if p["id"] == printer_id:
            return p
    raise AppError(404, "printer_not_found", f"Printer '{printer_id}' not found", printer=printer_id)


def default_for(config: dict, plugin_id: str | None) -> dict:
    """The plugin's default printer if it still exists, else the first printer."""
    if not config["printers"]:
        raise AppError(400, "no_printer", "No printer is set up")
    wanted = ((config.get("plugins") or {}).get(plugin_id) or {}).get("printer") if plugin_id else None
    for p in config["printers"]:
        if p["id"] == wanted:
            return p
    return config["printers"][0]


def resolve(config: dict, printer_id: str | None, plugin_id: str | None) -> dict:
    return find(config, printer_id) if printer_id else default_for(config, plugin_id)


def _slug(name: str) -> str:
    name = name.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-") or "printer"


def new_id(config: dict, name: str) -> str:
    base, taken = _slug(name), {p["id"] for p in config["printers"]}
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def validate_network_address(address: str) -> str:
    """host[:port] where host is an IPv4 address or hostname."""
    address = address.strip()
    host, _, port = address.partition(":")
    if "/" in address or not host:
        raise AppError(400, "invalid_host", f"Not a valid IP address or hostname: '{address}'")
    if port and not (port.isdigit() and 0 < int(port) < 65536):
        raise AppError(400, "invalid_port", f"Invalid port: '{port}'")
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        if not HOST_RE.match(host) or host.replace(".", "").isdigit():
            raise AppError(400, "invalid_host", f"Not a valid IP address or hostname: '{host}'")
    return address


def validate(data: dict) -> dict:
    """Check and normalise a printer as submitted from the settings page (without id)."""
    name = str(data.get("name") or "").strip()
    if not name:
        raise AppError(400, "printer_name_required", "The printer needs a name")
    driver = data.get("driver")
    if driver not in DRIVERS:
        raise AppError(400, "unknown_driver", f"Unknown printer driver '{driver}'", driver=str(driver))
    media = str(data.get("media") or "")
    Media.from_label(media)  # raises unknown_media
    out = {"name": name, "driver": driver, "media": media}

    if driver == "brother_ql":
        model = data.get("model")
        if model not in model_names():
            raise AppError(400, "unknown_model", f"Unknown printer model '{model}'", model=str(model))
        connection = str(data.get("connection") or "").strip()
        if connection.startswith("tcp://"):
            connection = "tcp://" + validate_network_address(connection[len("tcp://"):])
        elif not (USB_RE.match(connection) or LP_RE.match(connection)):
            raise AppError(400, "invalid_connection", f"Invalid connection '{connection}'", connection=connection)
        out.update(model=model, connection=connection)
    return out


# --- Options for the settings page ---

def model_names() -> list[str]:
    return [m.identifier for m in ModelsManager().iter_elements()]


def media_options() -> list[dict]:
    out = []
    for label in LabelsManager().iter_elements():
        endless = label.form_factor == FormFactor.ENDLESS
        out.append({
            "id": label.identifier,
            "tape_mm": label.tape_size[0],
            "length_mm": None if endless else label.tape_size[1],
            "endless": endless,
            "two_color": Media.from_label(label.identifier).two_color,
            # Die-cut rendering comes in phase 6.
            "supported": endless,
        })
    return out


def describe(cfg: dict) -> dict:
    """A printer as sent to the browser, with its media details."""
    media = Media.from_label(cfg["media"])
    return {**cfg, "media_info": {"tape_mm": media.tape_mm, "endless": media.endless}}


# --- Drivers ---

class Driver:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.media = Media.from_label(cfg["media"])

    def prepare(self, image: Image.Image) -> Image.Image:
        """Adjust a rendered label to what the printer can actually print. Used for both the
        preview and the print, so the preview shows what comes out."""
        return image

    def print(self, image: Image.Image, job_name: str, copies: int = 1) -> dict:
        raise NotImplementedError

    def test(self) -> None:
        """Raise AppError if the printer can't be reached."""


class BrotherQLDriver(Driver):
    @property
    def backend(self) -> str:
        conn = self.cfg["connection"]
        if conn.startswith("tcp://"):
            return "network"
        if conn.startswith("usb://"):
            return "pyusb"
        return "linux_kernel"

    def prepare(self, image):
        # QL printers refuse labels shorter than a model-specific minimum (150 dots ≈ 12.7 mm
        # on most, 295 on some): pad short endless labels, keeping the content centred.
        min_length = ModelsManager()[self.cfg["model"]].min_max_length_dots[0]
        if not self.media.endless or image.height >= min_length:
            return image
        padded = Image.new("RGB", (image.width, min_length), "white")
        padded.paste(image, (0, (min_length - image.height) // 2))
        return padded

    def _unreachable(self, e: Exception) -> AppError:
        return AppError(502, "printer_unreachable", f"Could not reach printer at {self.cfg['connection']}: {e}",
                        address=self.cfg["connection"].removeprefix("tcp://"), reason=str(e))

    def print(self, image, job_name, copies=1):
        qlr = BrotherQLRaster(self.cfg["model"])
        qlr.exception_on_warning = True
        # One job with a cut after each copy.
        instructions = convert(qlr=qlr, images=[image] * copies, label=self.media.id, rotate="0", threshold=70,
                               dither=False, compress=True, cut=True)
        try:
            result = send(instructions=instructions, printer_identifier=self.cfg["connection"],
                          backend_identifier=self.backend, blocking=True)
        except AppError:
            raise
        except Exception as e:  # OSError for network/lp, usb.core errors for pyusb
            raise self._unreachable(e)

        # The network backend can't read printer state back, so it only ever reports "sent".
        if result.get("outcome") == "error":
            errors = (result.get("printer_state") or {}).get("errors") or []
            raise AppError(502, "printer_error", f"The printer reported: {', '.join(errors) or 'an error'}",
                           errors=", ".join(errors))
        return {"status": "printed" if result.get("did_print") else "sent"}

    def test(self):
        conn = self.cfg["connection"]
        if conn.startswith("tcp://"):
            host, _, port = conn[len("tcp://"):].partition(":")
            try:
                with socket.create_connection((host, int(port or NETWORK_PORT)), timeout=3):
                    return
            except OSError as e:
                raise self._unreachable(e)
        if conn.startswith("file://"):
            if not Path(conn[len("file://"):]).exists():
                raise self._unreachable(FileNotFoundError(conn[len("file://"):]))
            return
        # USB: look the device up by vendor:product id.
        try:
            import usb.core

            vendor, product = (int(x, 16) for x in conn[len("usb://"):].split("/")[0].split(":"))
            if usb.core.find(idVendor=vendor, idProduct=product) is None:
                raise self._unreachable(LookupError("device not connected"))
        except AppError:
            raise
        except Exception as e:  # e.g. usb.core.NoBackendError when libusb is missing
            raise AppError(502, "usb_unavailable", f"USB is not available: {e}", reason=str(e))


class FileDriver(Driver):
    """Saves labels as PNG files in prints/<printer id>/ instead of printing them."""

    def print(self, image, job_name, copies=1):
        folder = PRINTS_DIR / self.cfg["id"]
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        # One image, with the number of copies in the name rather than identical files.
        suffix = f"_x{copies}" if copies > 1 else ""
        path = folder / f"{stamp}_{_slug(job_name)}{suffix}.png"
        image.save(path)
        return {"status": "saved", "file": str(path.relative_to(PRINTS_DIR.parent))}


def driver(cfg: dict) -> Driver:
    return {"brother_ql": BrotherQLDriver, "file": FileDriver}[cfg["driver"]](cfg)


# One lock per printer: concurrent jobs to the same printer go one at a time.
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def print_image(cfg: dict, image: Image.Image, job_name: str, copies: int = 1) -> dict:
    with _locks_guard:
        lock = _locks[cfg["id"]]
    with lock:
        return driver(cfg).print(image, job_name, copies)


def check_all(configs: list[dict]) -> list[dict]:
    """Test every printer at once: [{id, ok, error}] where error is a coded error detail."""
    def check(cfg):
        try:
            driver(cfg).test()
            return {"id": cfg["id"], "ok": True, "error": None}
        except AppError as e:
            return {"id": cfg["id"], "ok": False, "error": e.to_detail()}

    with ThreadPoolExecutor(max_workers=max(1, len(configs))) as pool:
        return list(pool.map(check, configs))
