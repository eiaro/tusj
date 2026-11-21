"""InvenTree: print part and stock location labels with a scannable QR code.

Search for a part or location in Tusj, and the label gets its name, IPN/path and a QR code
in your InvenTree's own barcode format (asked from InvenTree via /api/barcode/generate/,
falling back to the classic JSON format {"part": 12} on older versions).
"""
import json
import re
import time

import httpx

from plugin_api import FONT_BOLD, FONT_REGULAR, DataSource, LabelType, MediaRequirements, Plugin, field, layout, \
    option, resolve_values, setting, variable

TIMEOUT = 8
CACHE_SECONDS = 60
SEARCH_LIMIT = 15


class InvenTreeClient:
    def __init__(self, plugin: "InvenTreePlugin", url: str, token: str, verify_tls: bool, transport=None):
        self.plugin = plugin
        self.http = httpx.Client(
            base_url=url.rstrip("/"),
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            timeout=TIMEOUT,
            verify=verify_tls,
            transport=transport,
        )
        self._cache: dict[str, tuple[float, object]] = {}

    def request(self, method: str, path: str, **kwargs):
        try:
            r = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise self.plugin.error("unreachable", f"Could not reach InvenTree: {e}", 502, reason=str(e))
        if r.status_code in (401, 403):
            raise self.plugin.error("auth_failed", "InvenTree rejected the API token", 502)
        if r.status_code == 404:
            raise self.plugin.error("not_found", f"Not found in InvenTree: {path}", 404)
        if r.status_code >= 400:
            raise self.plugin.error("http_error", f"InvenTree answered {r.status_code} for {path}", 502,
                                    status=r.status_code)
        try:
            return r.json()
        except ValueError:
            raise self.plugin.error("http_error", f"InvenTree sent something that is not JSON for {path}", 502,
                                    status=r.status_code)

    def get(self, path: str, **params):
        return self.request("GET", path, params=params or None)

    def cached(self, key: str, fetch):
        """Previews re-render on every keystroke; don't hit InvenTree for the same object each time."""
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        value = fetch()
        self._cache[key] = (time.monotonic(), value)
        return value

    def search(self, path: str, query: str, **params) -> list[dict]:
        data = self.get(path, search=query, limit=SEARCH_LIMIT, **params)
        # Paginated ({count, results}) when limit is given; a plain list on some versions.
        return data["results"] if isinstance(data, dict) else data

    def barcode(self, model: str, pk: int) -> str:
        def fetch():
            try:
                return self.request("POST", "/api/barcode/generate/", json={"model": model, "pk": pk})["barcode"]
            except Exception as e:
                # Older InvenTree without the endpoint: use the classic internal JSON format.
                if getattr(e, "code", "") in ("inventree.not_found", "inventree.http_error") or isinstance(e, KeyError):
                    return json.dumps({model: pk})
                raise
        return self.cached(f"barcode:{model}:{pk}", fetch)

    def web_url(self, kind: str, pk: int) -> str:
        """Link to the object in InvenTree's web UI: /web/... since the new UI (0.15), the classic
        pages before that. kind is part, stock/location or stock/item."""
        def version():
            try:
                found = re.match(r"(\d+)\.(\d+)", str(self.get("/api/").get("version", "")))
            except Exception:
                found = None
            return (int(found[1]), int(found[2])) if found else (1, 0)
        base = str(self.http.base_url).rstrip("/")
        if self.cached("version", version) >= (0, 15):
            return f"{base}/web/{kind}/{pk}/"
        return f"{base}/{kind}/{pk}/"

    def parameter_templates(self) -> list[dict]:
        """Part parameter templates (Length, Thread, ...), so designs can show them. Empty if
        InvenTree can't be asked, so the editor still opens."""
        def fetch():
            try:
                data = self.get("/api/part/parameter/template/")
            except Exception:
                return []
            return data["results"] if isinstance(data, dict) else data
        return self.cached("parameter-templates", fetch)

    def part_parameters(self, pk: int) -> list[dict]:
        def fetch():
            try:
                data = self.get("/api/part/parameter/", part=pk, template_detail="true")
            except Exception as e:
                if getattr(e, "code", "") == "inventree.not_found":
                    return []  # an InvenTree without part parameters
                raise
            return data["results"] if isinstance(data, dict) else data
        return self.cached(f"parameters:{pk}", fetch)


def param_key(name: str) -> str:
    """Placeholder-safe id for a parameter name: 'Thread size' -> 'param.thread_size'."""
    return "param." + (re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_") or "x")


def param_text(value, units) -> str:
    value = "" if value is None else str(value).strip()
    return f"{value} {units}".strip() if value and units else value


class PartLabel(LabelType):
    id = "part"
    name = {"en": "InvenTree part", "nb": "InvenTree-del"}
    icon = "🔩"
    media = MediaRequirements(min_width_mm=29)

    def __init__(self, plugin: "InvenTreePlugin"):
        self.plugin = plugin

    def fields(self):
        return [
            field("part", "lookup", {"en": "Part", "nb": "Del"}, required=True,
                  placeholder={"en": "Search name, IPN or description…", "nb": "Søk på navn, IPN eller beskrivelse…"}),
            field("description", "select", {"en": "Description", "nb": "Beskrivelse"}, default="show",
                  required=True, options=[option("show", {"en": "Show", "nb": "Vis"}),
                                          option("hide", {"en": "Hide", "nb": "Skjul"})]),
        ]

    def search(self, field_id, query, lang):
        if field_id != "part" or not query.strip():
            return []
        parts = self.plugin.client().search("/api/part/", query, active="true")
        return [
            option(str(p["pk"]), p.get("full_name") or p["name"],
                   description=" · ".join(x for x in (p.get("IPN"), p.get("description")) if x) or None)
            for p in parts
        ]

    def render(self, values, ctx):
        v = resolve_values(self.fields(), values, ctx.lang)
        client = self.plugin.client()
        pk = self.plugin.pk(v["part"])
        part = client.cached(f"part:{pk}", lambda: client.get(f"/api/part/{pk}/"))
        s = ctx.scale
        name = part.get("full_name") or part["name"]

        def headline(draw, width):
            return layout.fit_font(draw, name, FONT_BOLD, s.px(72, layout.MIN_FONT_PX), s.px(40, layout.MIN_FONT_PX),
                                   width)

        return layout.qr_beside_text(ctx.media.width_px, s, client.barcode("part", pk), [
            (name, headline),
            (part.get("IPN"), s.font(FONT_REGULAR, 36)),
            (part.get("description") if v["description"] == "show" else None, s.font(FONT_REGULAR, 28)),
        ])


class LocationLabel(LabelType):
    id = "location"
    name = {"en": "InvenTree location", "nb": "InvenTree-plassering"}
    icon = "🗄️"
    media = MediaRequirements(min_width_mm=29)

    def __init__(self, plugin: "InvenTreePlugin"):
        self.plugin = plugin

    def fields(self):
        return [
            field("location", "lookup", {"en": "Location", "nb": "Plassering"}, required=True,
                  placeholder={"en": "Search locations…", "nb": "Søk etter plassering…"}),
        ]

    def search(self, field_id, query, lang):
        if field_id != "location" or not query.strip():
            return []
        locations = self.plugin.client().search("/api/stock/location/", query)
        return [option(str(loc["pk"]), loc["name"], description=loc.get("pathstring") or None) for loc in locations]

    def render(self, values, ctx):
        v = resolve_values(self.fields(), values, ctx.lang)
        client = self.plugin.client()
        pk = self.plugin.pk(v["location"])
        loc = client.cached(f"location:{pk}", lambda: client.get(f"/api/stock/location/{pk}/"))
        s = ctx.scale
        path = loc.get("pathstring")

        def headline(draw, width):
            return layout.fit_font(draw, loc["name"], FONT_BOLD, s.px(88, layout.MIN_FONT_PX),
                                   s.px(44, layout.MIN_FONT_PX), width)

        return layout.qr_beside_text(ctx.media.width_px, s, client.barcode("stocklocation", pk), [
            (loc["name"], headline),
            (path if path and path != loc["name"] else None, s.font(FONT_REGULAR, 30)),
        ])


# --- Data for the label editor ---

class PartSource(DataSource):
    id = "part"
    name = {"en": "InvenTree part", "nb": "InvenTree-del"}
    icon = "🔩"
    placeholder = {"en": "Search name, IPN or description…", "nb": "Søk på navn, IPN eller beskrivelse…"}

    def __init__(self, plugin: "InvenTreePlugin"):
        self.plugin = plugin

    def variables(self):
        return [
            variable("name", {"en": "Name", "nb": "Navn"}, sample="M3x8 screw"),
            variable("full_name", {"en": "Full name", "nb": "Fullt navn"}, sample="M3x8 screw | DIN 912"),
            variable("ipn", "IPN", sample="SCR-0308"),
            variable("description", {"en": "Description", "nb": "Beskrivelse"}, sample="Socket head cap screw, steel"),
            variable("revision", {"en": "Revision", "nb": "Revisjon"}, sample="B"),
            variable("category", {"en": "Category", "nb": "Kategori"}, sample="Fasteners/Screws"),
            variable("units", {"en": "Units", "nb": "Enhet"}, sample="pcs"),
            variable("keywords", {"en": "Keywords", "nb": "Nøkkelord"}, sample="m3 bolt"),
            variable("location", {"en": "Default location", "nb": "Standardplassering"}, sample="Drawer 3"),
            variable("barcode", {"en": "Barcode (for QR)", "nb": "Strekkode (til QR)"}, sample='{"part": 12}'),
            variable("url", {"en": "Link to InvenTree (for QR)", "nb": "Lenke til InvenTree (til QR)"},
                     sample=self.plugin.sample_url("part", 12)),
            variable("pk", "ID", sample="12"),
            *self.parameter_variables(),
        ]

    def parameter_variables(self):
        if self.plugin._client is None:
            return []
        out, seen = [], set()
        for t in self.plugin.client().parameter_templates():
            key = param_key(t.get("name"))
            if key in seen:
                continue
            seen.add(key)
            units = t.get("units") or ""
            label = f"{t.get('name')} ({units})" if units else str(t.get("name"))
            out.append(variable(key, {"en": f"Parameter: {label}", "nb": f"Parameter: {label}"},
                                sample=param_text("…", units)))
        return out

    def search(self, query, lang):
        return PartLabel(self.plugin).search("part", query, lang)

    def fetch(self, value, lang):
        client = self.plugin.client()
        pk = self.plugin.pk(value)
        part = client.cached(f"part-detail:{pk}", lambda: client.get(f"/api/part/{pk}/", category_detail="true",
                                                                     location_detail="true"))
        category = part.get("category_detail") or {}
        default_location = part.get("default_location_detail") or {}
        # Every known parameter, empty where this part has none: an element showing it is left out.
        params = {v["id"]: "" for v in self.parameter_variables()}
        for p in client.part_parameters(pk):
            t = p.get("template_detail") or {}
            params[param_key(t.get("name") or p.get("name") or "")] = param_text(p.get("data"), t.get("units"))
        return {
            **params,
            "name": part.get("name"),
            "full_name": part.get("full_name") or part.get("name"),
            "ipn": part.get("IPN"),
            "description": part.get("description"),
            "revision": part.get("revision"),
            "category": category.get("pathstring") or category.get("name"),
            "units": part.get("units"),
            "keywords": part.get("keywords"),
            "location": default_location.get("pathstring") or default_location.get("name"),
            "barcode": client.barcode("part", pk),
            "url": client.web_url("part", pk),
            "pk": pk,
        }


class LocationSource(DataSource):
    id = "location"
    name = {"en": "InvenTree location", "nb": "InvenTree-plassering"}
    icon = "🗄️"
    placeholder = {"en": "Search locations…", "nb": "Søk etter plassering…"}

    def __init__(self, plugin: "InvenTreePlugin"):
        self.plugin = plugin

    def variables(self):
        return [
            variable("name", {"en": "Name", "nb": "Navn"}, sample="Drawer 3"),
            variable("path", {"en": "Path", "nb": "Sti"}, sample="Workshop/Cabinet A/Drawer 3"),
            variable("description", {"en": "Description", "nb": "Beskrivelse"}, sample="Small screws"),
            variable("parent", {"en": "Parent location", "nb": "Overordnet plassering"}, sample="Cabinet A"),
            variable("items", {"en": "Stock items here", "nb": "Lagervarer her"}, sample="12"),
            variable("barcode", {"en": "Barcode (for QR)", "nb": "Strekkode (til QR)"}, sample='{"stocklocation": 7}'),
            variable("url", {"en": "Link to InvenTree (for QR)", "nb": "Lenke til InvenTree (til QR)"},
                     sample=self.plugin.sample_url("stock/location", 7)),
            variable("pk", "ID", sample="7"),
        ]

    def search(self, query, lang):
        return LocationLabel(self.plugin).search("location", query, lang)

    def fetch(self, value, lang):
        client = self.plugin.client()
        pk = self.plugin.pk(value)
        loc = client.cached(f"location:{pk}", lambda: client.get(f"/api/stock/location/{pk}/"))
        return {
            "name": loc.get("name"),
            "path": loc.get("pathstring") or loc.get("name"),
            "description": loc.get("description"),
            "parent": _parent(loc.get("pathstring")),
            "items": loc.get("items"),
            "barcode": client.barcode("stocklocation", pk),
            "url": client.web_url("stock/location", pk),
            "pk": pk,
        }


class StockItemSource(DataSource):
    id = "stockitem"
    name = {"en": "InvenTree stock item", "nb": "InvenTree-lagervare"}
    icon = "📦"
    placeholder = {"en": "Search part, serial or batch…", "nb": "Søk på del, serienummer eller batch…"}

    def __init__(self, plugin: "InvenTreePlugin"):
        self.plugin = plugin

    def variables(self):
        return [
            variable("part", {"en": "Part name", "nb": "Delnavn"}, sample="M3x8 screw"),
            variable("ipn", "IPN", sample="SCR-0308"),
            variable("quantity", {"en": "Quantity", "nb": "Antall"}, sample="250"),
            variable("serial", {"en": "Serial number", "nb": "Serienummer"}, sample=""),
            variable("batch", "Batch", sample="2026-11"),
            variable("location", {"en": "Location", "nb": "Plassering"}, sample="Workshop/Cabinet A/Drawer 3"),
            variable("expiry", {"en": "Expiry date", "nb": "Utløpsdato"}, sample="2027-06-30"),
            variable("status", "Status", sample="OK"),
            variable("barcode", {"en": "Barcode (for QR)", "nb": "Strekkode (til QR)"}, sample='{"stockitem": 42}'),
            variable("url", {"en": "Link to InvenTree (for QR)", "nb": "Lenke til InvenTree (til QR)"},
                     sample=self.plugin.sample_url("stock/item", 42)),
            variable("pk", "ID", sample="42"),
        ]

    def search(self, query, lang):
        if not query.strip():
            return []
        items = self.plugin.client().search("/api/stock/", query, part_detail="true", location_detail="true")
        out = []
        for item in items:
            part = item.get("part_detail") or {}
            loc = item.get("location_detail") or {}
            what = f"#{item['serial']}" if item.get("serial") else f"× {_quantity(item.get('quantity'))}"
            out.append(option(str(item["pk"]), f"{part.get('full_name') or part.get('name') or item.get('part')} {what}",
                              description=loc.get("pathstring") or None))
        return out

    def fetch(self, value, lang):
        client = self.plugin.client()
        pk = self.plugin.pk(value)
        item = client.cached(f"stock:{pk}", lambda: client.get(f"/api/stock/{pk}/", part_detail="true",
                                                               location_detail="true"))
        part = item.get("part_detail") or {}
        loc = item.get("location_detail") or {}
        return {
            "part": part.get("full_name") or part.get("name"),
            "ipn": part.get("IPN"),
            "quantity": _quantity(item.get("quantity")),
            "serial": item.get("serial"),
            "batch": item.get("batch"),
            "location": loc.get("pathstring") or loc.get("name"),
            "expiry": item.get("expiry_date"),
            "status": item.get("status_text") or "",
            "barcode": client.barcode("stockitem", pk),
            "url": client.web_url("stock/item", pk),
            "pk": pk,
        }


def _parent(path) -> str:
    parts = str(path or "").split("/")
    return parts[-2] if len(parts) > 1 else ""


def _quantity(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return str(int(number)) if number.is_integer() else f"{number:g}"


class InvenTreePlugin(Plugin):
    id = "inventree"
    name = "InvenTree"
    version = "1.0.0"
    description = {
        "en": "Labels for InvenTree parts and stock locations, with a QR code the InvenTree app can scan.",
        "nb": "Etiketter for deler og lagerplasseringer i InvenTree, med QR-kode InvenTree-appen kan skanne.",
    }
    settings_schema = [
        setting("url", "url", {"en": "InvenTree address", "nb": "InvenTree-adresse"}, required=True,
                help={"en": "e.g. https://inventree.example.com", "nb": "f.eks. https://inventree.example.com"}),
        setting("token", "secret", {"en": "API token", "nb": "API-nøkkel"}, required=True,
                help={"en": "In InvenTree: user menu → Account settings → Access tokens.",
                      "nb": "I InvenTree: brukermenyen → Kontoinnstillinger → Tilgangsnøkler."}),
        setting("verify_tls", "boolean", {"en": "Verify TLS certificate", "nb": "Sjekk TLS-sertifikat"}, default=True,
                help={"en": "Turn off only for a self-signed certificate on your own network.",
                      "nb": "Slå bare av ved selvsignert sertifikat på eget nett."}),
    ]
    messages = {
        "en": {"errors": {
            "not_configured": "Set the InvenTree address and API token under Settings → Plugins",
            "unreachable": "Could not reach InvenTree",
            "auth_failed": "InvenTree rejected the API token",
            "not_found": "Not found in InvenTree",
            "http_error": "InvenTree answered with an error ({status})",
        }},
        "nb": {"errors": {
            "not_configured": "Legg inn InvenTree-adresse og API-nøkkel under Innstillinger → Plugins",
            "unreachable": "Fikk ikke kontakt med InvenTree",
            "auth_failed": "InvenTree godtok ikke API-nøkkelen",
            "not_found": "Fant det ikke i InvenTree",
            "http_error": "InvenTree svarte med en feil ({status})",
        }},
    }

    # Tests swap in an httpx.MockTransport here.
    transport = None

    def setup(self, settings):
        self.settings = settings
        self._client = None
        if settings.get("url") and settings.get("token"):
            self._client = InvenTreeClient(self, settings["url"], settings["token"],
                                           bool(settings.get("verify_tls", True)), self.transport)

    def client(self) -> InvenTreeClient:
        if self._client is None:
            raise self.error("not_configured", "InvenTree address and API token are not set")
        return self._client

    def pk(self, value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            raise self.error("not_found", f"Not an InvenTree id: {value!r}", 404)

    def sample_url(self, kind: str, pk: int) -> str:
        """What a link looks like before a record is picked: on this InvenTree when it is set up,
        without asking it (the editor lists variables often)."""
        base = str(getattr(self, "settings", {}).get("url") or "https://inventree.example.com").rstrip("/")
        return f"{base}/web/{kind}/{pk}/"

    def check(self):
        self.client().get("/api/user/me/")

    def label_types(self):
        return [PartLabel(self), LocationLabel(self)]

    def data_sources(self):
        return [PartSource(self), LocationSource(self), StockItemSource(self)]


plugin = InvenTreePlugin()
