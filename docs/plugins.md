# Writing a Tusj plugin

A plugin adds one or more **label types** to Tusj without changing the app. It is a folder in `plugins/` with a `plugin.py`:

```
plugins/
  my_plugin/
    plugin.py
```

Tusj loads every `plugins/*/plugin.py` on startup (restart the backend after adding or changing a plugin). A plugin that fails to load is listed under **Settings → Plugins** with its error; the rest of the app keeps working.

> Plugins are ordinary Python code running inside the backend. Only install plugins you trust.

## A minimal plugin

```python
from PIL import ImageDraw
from plugin_api import FONT_BOLD, LabelType, Plugin, TextFlow, field, layout, resolve_values


class BoxLabel(LabelType):
    id = "box"                                   # unique within the plugin
    name = {"en": "Storage box", "nb": "Lagerboks"}
    icon = "📦"

    def fields(self):
        return [field("contents", "text", {"en": "Contents", "nb": "Innhold"}, required=True)]

    def render(self, values, ctx):
        v = resolve_values(self.fields(), values, ctx.lang)   # validates and converts
        s, width = ctx.scale, ctx.media.width_px
        pad = s.px(24, 6)

        img = layout.endless_canvas(width)
        draw = ImageDraw.Draw(img)
        flow = TextFlow(draw, x=pad, y=pad, width=width - 2 * pad, line_gap=s.px(10, 4))
        flow.text(v["contents"], s.font(FONT_BOLD, 72))
        return img.crop((0, 0, width, flow.bottom + pad))


class BoxPlugin(Plugin):
    id = "boxes"
    name = {"en": "Boxes", "nb": "Bokser"}
    version = "1.0.0"

    def label_types(self):
        return [BoxLabel()]


plugin = BoxPlugin()          # Tusj looks for this name
```

The label type's id in the API is `<plugin id>.<label type id>`, here `boxes.box`.

`plugins/quick_label/plugin.py` is a slightly larger example (QR code beside text). `plugins/inventree/plugin.py` shows settings, a `check()`, lookup fields backed by a web API, caching and plugin error messages.

## Text and translations

Anything shown to users (names, field labels, option labels, setting labels, help text) is either a plain string or a `{language: text}` map. Missing languages fall back to English. In `render()`, use `ctx.text(value)` to pick the right language and `ctx.date(d)` to format a date the way the label's language expects.

## Fields

Create fields with `field(id, type, label, required=False, default=None, **extra)`:

| Type | Value sent to `render()` (after `resolve_values`) | Extra keys |
|---|---|---|
| `text` | `str` | `placeholder=...`, `help=...` (a hint under the field) |
| `number` | `int` or `float` | `min`, `max`, `step` |
| `date` | `datetime.date` | `default="today"` |
| `date-presets` | `datetime.date` | `presets=["+3d", "+1w", "+1m", "+1y"]` |
| `select` | `str` (an option value) | `options=[option(...), ...]` |
| `multi-select` | `list[str]` | `options=[option(..., icon="🥛"), ...]` (icons show as a grid) |
| `lookup` | `str` (the chosen option's value) | `placeholder=...` |

`option(value, label, icon=None, description=None)` describes a choice.

A **lookup** field searches as the user types. Implement `search()` on the label type:

```python
def search(self, field_id, query, lang):
    parts = my_api.find_parts(query)
    return [option(str(p.id), p.name, description=p.ipn) for p in parts[:10]]
```

`render()` receives the chosen option's `value`, so fetch whatever else you need from there.

`resolve_values(fields, values, lang)` checks required fields, converts types and validates choices, raising the same coded errors as the built-in labels. Fields left empty are omitted from the result.

## Drawing

`render(values, ctx)` returns a Pillow image exactly `ctx.media.width_px` wide. For endless tape the height is up to you: draw on `layout.endless_canvas(width)` and crop. `ctx.media` also has `tape_mm`, `endless`, `height_px` (die-cut) and `two_color`.

Sizes in Tusj are designed for 62 mm tape (696 px wide) and scaled to the actual tape with `ctx.scale`:

- `ctx.scale.px(base, minimum)` scales a length, e.g. a margin.
- `ctx.scale.font(FONT_REGULAR | FONT_BOLD, base_size)` gives a scaled font that never goes below a readable minimum.

Helpers in `layout`:

| Helper | What it does |
|---|---|
| `TextFlow(draw, x, y, width, line_gap, centered=False)` | Writes wrapped text top to bottom; `.text()`, `.space()`, `.bottom` |
| `fit_font(draw, text, role, max_size, min_size, max_width)` | Largest font size that fits the text on one line |
| `wrap(draw, text, font, max_width)` | Word wrap (breaks overlong words) |
| `qr_image(data, max_size_px)` | Sharp black-on-white QR code |
| `qr_beside_text(width, scale, qr_data, lines, symbol=None)` | Complete label: QR (or a ready-made `symbol` image) on the left, text lines on the right, vertically centred (used by Quick label and InvenTree) |
| `symbols.symbol_image(text, max_size_px)` | A QR code, emoji or Material Design Icon from text like `QR https://…`, `:tada:` or `mdi:home`, as black-and-white. Raises `symbols.SymbolError` (with a `code`) for text that isn't a symbol |
| `border_padding(style, scale)` / `draw_border(img, style, scale)` | The built-in frames: `simple`, `double`, `ornate` |
| `endless_canvas(width)` | Tall white scratch canvas |

Set `media = MediaRequirements(min_width_mm=29)` on a label type if it needs a minimum tape width; it is then greyed out when the loaded tape is too narrow.

## Settings

Plugins that need configuration (a server URL, an API token) declare a schema; Tusj builds the form under **Settings → Plugins** and stores the values in `config.yaml`:

```python
from plugin_api import Plugin, setting

class MyPlugin(Plugin):
    settings_schema = [
        setting("url", "url", {"en": "Server URL", "nb": "Server-URL"}, required=True),
        setting("token", "secret", {"en": "API token", "nb": "API-nøkkel"}),
        setting("verify_tls", "boolean", {"en": "Verify TLS certificate"}, default=True),
    ]

    def setup(self, settings):
        # Called on startup and whenever settings are saved.
        self.settings = settings

    def check(self):
        # Optional: adds a "Test" button. Raise an error if something is wrong.
        if not self.settings.get("token"):
            raise self.error("no_token", "Token missing")
```

Setting types are `text`, `url`, `secret` and `boolean`. Secrets are never sent back to the browser.

## Errors

Raise `self.error(code, message, status=400, **params)` from a plugin (or `PluginError(plugin_id, ...)` from a label type). The browser shows `message` unless the plugin provides a translation:

```python
messages = {
    "en": {"errors": {"no_token": "Enter an API token first"}},
    "nb": {"errors": {"no_token": "Legg inn en API-nøkkel først"}},
}
```

`{param}` placeholders in messages are filled from the error's params.

## Dependencies

Plugins can use what the Tusj image ships with: Pillow, httpx, qrcode, PyYAML and the Python standard library. A plugin that needs more requires a custom image (add the package to `backend/requirements.txt` and rebuild).

## Running it

- **Containers:** `plugins/` is mounted into the backend container (see `compose.yaml`); restart the backend after changes: `podman compose restart backend`.
- **Development:** restart uvicorn, or touch a backend file if it runs with `--reload`.
