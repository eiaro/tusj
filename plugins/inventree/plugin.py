"""InvenTree: print part and stock location labels with a scannable QR code.

Search for a part or location in Tusj, and the label gets its name, IPN/path and a QR code
in your InvenTree's own barcode format (asked from InvenTree via /api/barcode/generate/,
falling back to the classic JSON format {"part": 12} on older versions).
"""
import json
import time

import httpx

from plugin_api import FONT_BOLD, FONT_REGULAR, LabelType, MediaRequirements, Plugin, field, layout, option, \
    resolve_values, setting

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

    def check(self):
        self.client().get("/api/user/me/")

    def label_types(self):
        return [PartLabel(self), LocationLabel(self)]


plugin = InvenTreePlugin()
