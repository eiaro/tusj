"""Built-in plugin: one label type per YAML file in templates/ (premade food, spice jar, ...)."""
from pathlib import Path

import yaml

import label
from plugin_api import LabelType, Plugin, RenderContext, option

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

# Icon when a template doesn't set one, by layout style.
STYLE_ICONS = {"container": "🫙", "info": "🍲"}


def _allergen_options() -> list[dict]:
    return [option(a["id"], a["name"], icon=a["icon"]) for a in label.load_allergens()]


class TemplateLabel(LabelType):
    def __init__(self, template_id: str, template: dict):
        self.id = template_id
        self.template = template
        self.name = template["name"]
        self.icon = template.get("icon") or STYLE_ICONS.get(template.get("style"), "🏷️")

    def fields(self) -> list[dict]:
        out = []
        for spec in self.template["fields"]:
            spec = dict(spec)
            # The allergen list is a multi-select with icons as far as the form is concerned.
            if spec["type"] == "allergens":
                spec["type"] = "multi-select"
                spec["options"] = _allergen_options()
            out.append(spec)
        return out

    def render(self, values: dict, ctx: RenderContext):
        return label.render(self.template, values, lang=ctx.lang, media=ctx.media)


class TemplatesPlugin(Plugin):
    id = "templates"
    name = {"en": "Kitchen templates", "nb": "Kjøkkenmaler"}
    version = "1.0.0"
    description = {
        "en": "Labels defined as YAML files in the templates folder.",
        "nb": "Etiketter definert som YAML-filer i templates-mappen.",
    }

    def __init__(self, templates_dir: Path = TEMPLATES_DIR):
        self.templates_dir = templates_dir

    def label_types(self) -> list[LabelType]:
        types = []
        for path in sorted(self.templates_dir.glob("*.yaml")):
            with open(path, encoding="utf-8") as f:
                types.append(TemplateLabel(path.stem, yaml.safe_load(f)))
        return types


plugin = TemplatesPlugin()
