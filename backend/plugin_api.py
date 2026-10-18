"""Everything a Tusj plugin needs. Plugins import from here and nowhere else in the backend:

    from plugin_api import Plugin, LabelType, RenderContext, field, layout

A plugin is a directory `plugins/<id>/` containing `plugin.py`, which defines a module-level
`plugin` object (an instance of a Plugin subclass). See plugins/quick_label for an example.

Text shown to users (names, field labels, option labels) is either a plain string or a
{language: text} map, e.g. {"en": "Title", "nb": "Tittel"}.
"""
from dataclasses import dataclass, field as dc_field
from datetime import date
from typing import Any

from PIL import Image

import layout
import symbols
from i18n import AppError, format_date, localized
from layout import FONT_BOLD, FONT_REGULAR, Scale, TextFlow
from media import Media

__all__ = [
    "Plugin", "LabelType", "RenderContext", "MediaRequirements", "PluginError",
    "field", "option", "setting", "resolve_values", "layout", "symbols", "Media", "Scale", "TextFlow", "FONT_BOLD",
    "FONT_REGULAR",
]

Text = str | dict[str, str]

FIELD_TYPES = ("text", "number", "date", "date-presets", "select", "multi-select", "lookup")
SETTING_TYPES = ("text", "url", "secret", "boolean")


def field(id: str, type: str, label: Text, *, required: bool = False, default: Any = None, **extra) -> dict:
    """A form field.

    Extra keys per type:
      date-presets  presets: ["+3d", "+1w", "+1m", "+1y"]
      select        options: [option(...), ...]
      multi-select  options: [option(..., icon="🥛"), ...]
      number        min, max, step
      lookup        placeholder: Text  (values come from LabelType.search())
      text          placeholder: Text, help: Text (a hint shown under the field)
    """
    if type not in FIELD_TYPES:
        raise ValueError(f"Unknown field type '{type}'")
    spec = {"id": id, "type": type, "label": label, "required": required, **extra}
    if default is not None:
        spec["default"] = default
    return spec


def option(value: str, label: Text, *, icon: str | None = None, description: Text | None = None) -> dict:
    opt = {"value": value, "label": label}
    if icon:
        opt["icon"] = icon
    if description:
        opt["description"] = description
    return opt


def setting(id: str, type: str, label: Text, *, required: bool = False, default: Any = None,
            help: Text | None = None) -> dict:
    """A plugin setting shown under Settings. Values of type 'secret' are never sent back to
    the browser."""
    if type not in SETTING_TYPES:
        raise ValueError(f"Unknown setting type '{type}'")
    spec = {"id": id, "type": type, "label": label, "required": required}
    if default is not None:
        spec["default"] = default
    if help:
        spec["help"] = help
    return spec


def _empty(value) -> bool:
    return value is None or value == "" or value == []


def resolve_values(fields: list[dict], values: dict, lang: str) -> dict:
    """Validate submitted values against field specs and convert them: dates become
    datetime.date, numbers int/float, multi-select a list. Empty optional fields are left out.
    Raises AppError (field_required / invalid_date / invalid_value) like the built-in labels."""
    from label import resolve_date  # local import: label imports layout, which is fine, but keep this module light

    out = {}
    for spec in fields:
        fid, kind = spec["id"], spec["type"]
        value = values.get(fid)
        if _empty(value):
            value = spec.get("default")
        name = localized(spec["label"], lang)
        if _empty(value):
            if spec.get("required"):
                raise AppError(400, "field_required", f"Field '{name}' is required", field=name)
            continue

        allowed = {o["value"] for o in spec.get("options", [])}
        if kind in ("date", "date-presets"):
            value = resolve_date(value)
        elif kind == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise AppError(400, "invalid_value", f"'{value}' is not a number for '{name}'", field=name)
            value = int(value) if value.is_integer() else value
            if ("min" in spec and value < spec["min"]) or ("max" in spec and value > spec["max"]):
                raise AppError(400, "invalid_value", f"{value} is out of range for '{name}'", field=name)
        elif kind == "select":
            value = str(value)
            if allowed and value not in allowed:
                raise AppError(400, "invalid_value", f"'{value}' is not a valid choice for '{name}'", field=name)
        elif kind == "multi-select":
            value = [str(v) for v in (value if isinstance(value, list) else [value])]
            if allowed and not set(value) <= allowed:
                raise AppError(400, "invalid_value", f"Invalid choice for '{name}'", field=name)
            if not value:
                continue
        else:
            value = str(value)
        out[fid] = value
    return out


@dataclass(frozen=True)
class MediaRequirements:
    min_width_mm: float = 0
    endless: bool = True
    die_cut: bool = False

    def accepts(self, media: Media) -> bool:
        if media.tape_mm < self.min_width_mm:
            return False
        return self.endless if media.endless else self.die_cut


class PluginError(AppError):
    """A coded error from a plugin. The frontend looks the code up under the plugin's own
    messages (plugins.<plugin id>.errors.<code>) and falls back to `message`."""

    def __init__(self, plugin_id: str, code: str, message: str, status: int = 400, **params):
        super().__init__(status, f"{plugin_id}.{code}", message, **params)


@dataclass
class RenderContext:
    lang: str
    media: Media
    scale: Scale = dc_field(init=False)

    def __post_init__(self):
        self.scale = Scale(self.media.width_px)

    def text(self, value: Text) -> str:
        return localized(value, self.lang)

    def date(self, d: date) -> str:
        return format_date(d, self.lang)


class LabelType:
    """One kind of label offered by a plugin. Subclass and override."""

    id: str = ""                    # unique within the plugin
    name: Text = ""
    icon: str = "🏷️"
    media = MediaRequirements()

    def fields(self) -> list[dict]:
        return []

    def search(self, field_id: str, query: str, lang: str) -> list[dict]:
        """Options for a 'lookup' field matching `query`."""
        return []

    def render(self, values: dict, ctx: RenderContext) -> Image.Image:
        raise NotImplementedError


class Plugin:
    """Base class for plugins. Subclass, set the attributes, override what you need."""

    id: str = ""
    name: Text = ""
    version: str = "0.1.0"
    description: Text = ""
    settings_schema: list[dict] = []
    # Extra UI strings, merged into the frontend under plugins.<id>, e.g.
    # {"en": {"errors": {"auth_failed": "Wrong API token"}}, "nb": {...}}
    messages: dict[str, dict] = {}

    def setup(self, settings: dict) -> None:
        """Called on startup and whenever the plugin's settings are saved."""
        self.settings = settings

    def check(self) -> None:
        """Optional 'Test' button under Settings: raise PluginError if something is wrong."""

    def label_types(self) -> list[LabelType]:
        return []

    def error(self, code: str, message: str, status: int = 400, **params) -> PluginError:
        return PluginError(self.id, code, message, status, **params)
