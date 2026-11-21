"""Built-in plugin: every design published from the label editor becomes a label type.

Printing a design works like any other label: POST /print/designs.<design id> with the field
values, plus "<source id>": "<record id>" when the design shows data from a data source.
"""
from datetime import date

import design as designs
import label
from i18n import AppError, format_date, localized
from media import Media
from plugin_api import LabelType, MediaRequirements, Plugin, RenderContext, field, option, resolve_values


class ExactMedia(MediaRequirements):
    """A design is drawn for one label size and prints only on that."""

    def __init__(self, media_id: str):
        media = Media.from_label(media_id)
        super().__init__(min_width_mm=media.tape_mm, endless=media.endless, die_cut=not media.endless)
        object.__setattr__(self, "media_id", media_id)

    def accepts(self, media: Media) -> bool:
        return media.id == self.media_id


def _form_field(spec: dict) -> dict:
    """A design field as the print form needs it (allergens are a multi-select with icons)."""
    spec = dict(spec)
    if spec["type"] == "allergens":
        spec["type"] = "multi-select"
        spec["options"] = [option(a["id"], a["name"], icon=a["icon"]) for a in label.load_allergens()]
    return spec


def _format(spec: dict, value, lang: str) -> str:
    if isinstance(value, date):
        return format_date(value, lang)
    if spec["type"] == "allergens":
        return ", ".join(label.allergen_name(a, lang) for a in value)
    if spec["type"] == "select":
        labels = {o["value"]: o.get("label", o["value"]) for o in spec.get("options", [])}
        return localized(labels.get(value, value), lang)
    return str(value)


def sample_value(spec: dict, lang: str) -> str:
    """What the editor shows for a field before anything is typed in."""
    kind = spec["type"]
    if kind == "date":
        return format_date(date.today(), lang)
    if kind == "date-presets":
        return format_date(label.resolve_date(spec["presets"][0]), lang)
    if kind == "allergens":
        return ", ".join(label.allergen_name(a, lang) for a in ("milk", "gluten"))
    if kind == "select" and spec.get("options"):
        return localized(spec["options"][0].get("label", spec["options"][0]["value"]), lang)
    if kind == "number":
        return "12"
    return localized(spec.get("placeholder") or spec["label"], lang)


class DesignLabel(LabelType):
    def __init__(self, plugin: "DesignsPlugin", design: dict, source):
        self.plugin = plugin
        self.design = design
        self.source = source  # DataSource or None
        self.id = design["id"]
        self.name = design["name"]
        self.icon = design.get("icon") or "🏷️"
        self.media = ExactMedia(design["media"])

    def fields(self) -> list[dict]:
        out = []
        if self.source:
            out.append(field(self.source.id, "lookup", self.source.name, required=True,
                             placeholder=self.source.placeholder or None))
        return out + [_form_field(f) for f in self.design["fields"]]

    def search(self, field_id, query, lang):
        if self.source and field_id == self.source.id and query.strip():
            return self.source.search(query, lang)
        return []

    def render(self, values, ctx: RenderContext):
        return designs.render(self.design, self.plugin.values_for(self.design, values, ctx.lang), ctx.media, ctx.lang)


class DesignsPlugin(Plugin):
    id = "designs"
    name = {"en": "Label editor", "nb": "Etikett-editor"}
    version = "0.1.0"
    description = {
        "en": "Labels designed in the label editor.",
        "nb": "Etiketter laget i etikett-editoren.",
    }

    registry = None  # set by Registry.load(), to reach other plugins' data sources

    def use_registry(self, registry):
        self.registry = registry

    def source_for(self, design: dict):
        """The design's data source, or None. Raises if it is set but not available."""
        if not design.get("source"):
            return None
        return self.registry.data_source(design["source"])[1]

    def values_for(self, design: dict, values: dict, lang: str, sample: bool = False) -> dict[str, str]:
        """Placeholder values for a design. With sample=True (the editor), anything not given
        is filled with sample text instead of raising 'required'."""
        out = {"today": format_date(date.today(), lang)}
        specs = design["fields"]
        for spec in specs:
            out[spec["id"]] = ""  # known but empty until filled in
        if sample:
            given = {k: v for k, v in values.items() if v not in (None, "", [])}
            for spec in specs:
                out[spec["id"]] = sample_value(spec, lang)
            specs = [{**s, "required": False} for s in specs if s["id"] in given]
            values = given
        resolved = resolve_values([_form_field(s) for s in specs], values, lang)
        for spec in specs:
            if spec["id"] in resolved:
                out[spec["id"]] = _format(spec, resolved[spec["id"]], lang)

        source = self.source_for(design)
        if source:
            record = values.get(source.id)
            if record not in (None, ""):
                data = source.fetch(str(record), lang)
            elif sample:
                data = {v["id"]: v.get("sample", "") for v in source.variables()}
            else:
                name = localized(source.name, lang)
                raise AppError(400, "field_required", f"Field '{name}' is required", field=name)
            for key, value in data.items():
                out[f"{source.id}.{key}"] = "" if value is None else str(value)
        return out

    def label_types(self) -> list[LabelType]:
        out = []
        for d in designs.list_designs():
            try:
                design = {"id": d["id"], **designs.validate(d)}
                source = self.source_for(design)
            except Exception:
                continue  # invalid, or its data source plugin is off: not offered for printing
            out.append(DesignLabel(self, design, source))
        return out


plugin = DesignsPlugin()
