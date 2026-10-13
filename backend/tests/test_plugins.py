"""Plugin loading, configuration, settings API and the plugin helper functions."""
import textwrap
from datetime import date

import pytest
import yaml

import main
from i18n import AppError
from plugin_api import field, option, resolve_values
from registry import Registry

GOOD_PLUGIN = '''
from PIL import Image
from plugin_api import LabelType, Plugin, field, setting, option, resolve_values

class Box(LabelType):
    id = "box"
    name = "Box"
    def fields(self):
        return [field("code", "lookup", "Code", required=True)]
    def search(self, field_id, query, lang):
        return [option(c, c.upper()) for c in ("abc", "abd", "xyz") if c.startswith(query)]
    def render(self, values, ctx):
        resolve_values(self.fields(), values, ctx.lang)
        return Image.new("RGB", (ctx.media.width_px, 100), "white")

class Good(Plugin):
    id = "good"
    name = "Good"
    settings_schema = [
        setting("url", "url", "URL", required=True),
        setting("token", "secret", "Token"),
        setting("verbose", "boolean", "Verbose", default=False),
    ]
    def setup(self, settings):
        if settings.get("url") == "explode":
            raise RuntimeError("bad url")
        self.settings = settings
    def check(self):
        if not self.settings.get("token"):
            raise self.error("no_token", "Token missing")
    def label_types(self):
        return [Box()]

plugin = Good()
'''


def _write_plugin(root, name, source):
    d = root / name
    d.mkdir()
    (d / "plugin.py").write_text(textwrap.dedent(source))


@pytest.fixture
def plugins_dir(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    _write_plugin(root, "good", GOOD_PLUGIN)
    _write_plugin(root, "syntax_error", "def broken(:\n")
    _write_plugin(root, "no_plugin_object", "x = 1\n")
    _write_plugin(root, "zz_dupe", GOOD_PLUGIN)  # same id as "good"; loads after it (alphabetical)
    (root / "not_a_plugin").mkdir()          # no plugin.py: ignored
    return root


@pytest.fixture
def registry(plugins_dir):
    r = Registry(plugins_dir=plugins_dir)
    r.load()
    r.configure({})
    return r


def test_broken_plugins_are_isolated(registry):
    assert registry.get("templates").active
    assert registry.get("good").active
    assert "SyntaxError" in registry.get("syntax_error").error
    assert "must define" in registry.get("no_plugin_object").error
    dupe = next(e for k, e in registry.entries.items() if k.startswith("zz_dupe"))
    assert "duplicate plugin id 'good'" in dupe.error
    assert "not_a_plugin" not in registry.entries

    ids = [lt_id for lt_id, _, _ in registry.label_types()]
    assert "good.box" in ids and "templates.premade_food" in ids


def test_disabled_plugins_offer_no_label_types(registry):
    registry.configure({"good": {"enabled": False}})
    assert not registry.get("good").active
    assert "good.box" not in [lt_id for lt_id, _, _ in registry.label_types()]


def test_setup_failure_marks_plugin(registry):
    registry.configure({"good": {"settings": {"url": "explode"}}})
    assert registry.get("good").error == "RuntimeError: bad url"
    assert not registry.get("good").active


def test_settings_defaults(registry):
    registry.configure({"good": {"settings": {"url": "https://x"}}})
    assert registry.get("good").settings == {"url": "https://x", "token": None, "verbose": False}


# --- API ---

@pytest.fixture
def plugin_client(client, plugins_dir, monkeypatch):
    r = Registry(plugins_dir=plugins_dir)
    r.load()
    r.configure({})
    monkeypatch.setattr(main, "registry", r)
    return client


def test_plugins_api_lists_plugins_and_errors(plugin_client):
    plugins = {p["id"]: p for p in plugin_client.get("/plugins").json()}
    assert plugins["templates"]["builtin"] is True
    assert plugins["good"]["checkable"] is True
    assert plugins["templates"]["checkable"] is False
    assert plugins["syntax_error"]["error"].startswith("SyntaxError")


def test_secrets_are_never_returned_and_kept_when_blank(plugin_client, config_file):
    r = plugin_client.put("/plugins/good", json={"settings": {"url": "https://inv", "token": "s3cret"}})
    assert r.status_code == 200
    assert r.json()["settings"] == {"url": "https://inv", "token": True, "verbose": False}
    assert "s3cret" not in r.text

    # Saving again without a token (or with "") keeps the stored one
    r = plugin_client.put("/plugins/good", json={"settings": {"url": "https://inv2", "token": ""}})
    assert r.json()["settings"]["token"] is True
    saved = yaml.safe_load(config_file.read_text())["plugins"]["good"]["settings"]
    assert saved == {"url": "https://inv2", "token": "s3cret"}
    assert "s3cret" not in plugin_client.get("/plugins").text


def test_enable_disable_via_api(plugin_client, config_file):
    plugin_client.put("/plugins/good", json={"enabled": False})
    assert "good.box" not in [lt["id"] for lt in plugin_client.get("/label-types").json()]
    assert yaml.safe_load(config_file.read_text())["plugins"]["good"]["enabled"] is False
    plugin_client.put("/plugins/good", json={"enabled": True})
    assert "good.box" in [lt["id"] for lt in plugin_client.get("/label-types").json()]


def test_check_returns_plugin_error_codes(plugin_client):
    r = plugin_client.post("/plugins/good/check")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "good.no_token"
    plugin_client.put("/plugins/good", json={"settings": {"token": "t"}})
    assert plugin_client.post("/plugins/good/check").json() == {"ok": True}


def test_lookup_search_and_render(plugin_client):
    r = plugin_client.get("/label-types/good.box/search/code?q=ab")
    assert r.json() == [{"value": "abc", "label": "ABC"}, {"value": "abd", "label": "ABD"}]
    assert plugin_client.post("/preview/good.box", json={"code": "abc"}).status_code == 200
    r = plugin_client.post("/preview/good.box", json={})
    assert r.json()["detail"]["code"] == "field_required"


def test_unknown_plugin(plugin_client):
    r = plugin_client.put("/plugins/nope", json={"enabled": True})
    assert (r.status_code, r.json()["detail"]["code"]) == (404, "plugin_not_found")


# --- resolve_values ---

FIELDS = [
    field("name", "text", "Name", required=True),
    field("count", "number", "Count", min=1, max=10),
    field("when", "date-presets", "When", presets=["+1w"]),
    field("size", "select", "Size", options=[option("s", "S"), option("l", "L")], default="s"),
    field("tags", "multi-select", "Tags", options=[option("a", "A"), option("b", "B")]),
]


def test_resolve_values_converts():
    out = resolve_values(FIELDS, {"name": "x", "count": "3", "when": "2026-01-02", "tags": ["a"]}, "en")
    assert out == {"name": "x", "count": 3, "when": date(2026, 1, 2), "size": "s", "tags": ["a"]}


@pytest.mark.parametrize("values, code", [
    ({}, "field_required"),
    ({"name": "x", "count": "lots"}, "invalid_value"),
    ({"name": "x", "count": 11}, "invalid_value"),
    ({"name": "x", "size": "xl"}, "invalid_value"),
    ({"name": "x", "tags": ["a", "z"]}, "invalid_value"),
    ({"name": "x", "when": "soon"}, "invalid_date"),
])
def test_resolve_values_rejects(values, code):
    with pytest.raises(AppError) as e:
        resolve_values(FIELDS, values, "en")
    assert e.value.code == code


def test_unknown_field_type():
    with pytest.raises(ValueError):
        field("x", "colour", "X")
