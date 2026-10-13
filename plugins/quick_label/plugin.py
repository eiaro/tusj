"""Example plugin: a free-text label with an optional QR code.

Shows the moving parts of a plugin: a LabelType with fields, value validation via
resolve_values(), and drawing with the shared layout helpers.
"""
from plugin_api import FONT_BOLD, FONT_REGULAR, LabelType, Plugin, RenderContext, field, layout, resolve_values


class QuickLabel(LabelType):
    id = "text"
    name = {"en": "Quick label", "nb": "Hurtigetikett"}
    icon = "✏️"

    def fields(self):
        return [
            field("title", "text", {"en": "Text", "nb": "Tekst"}, required=True),
            field("subtitle", "text", {"en": "Small text", "nb": "Liten tekst"}),
            field("qr", "text", {"en": "QR code (link or text)", "nb": "QR-kode (lenke eller tekst)"}),
        ]

    def render(self, values, ctx: RenderContext):
        v = resolve_values(self.fields(), values, ctx.lang)
        s = ctx.scale

        def headline(draw, width):
            return layout.fit_font(draw, v["title"], FONT_BOLD, s.px(80, layout.MIN_FONT_PX),
                                   s.px(40, layout.MIN_FONT_PX), width)

        return layout.qr_beside_text(ctx.media.width_px, s, v.get("qr"), [
            (v["title"], headline),
            (v.get("subtitle"), s.font(FONT_REGULAR, 34)),
        ])


class QuickLabelPlugin(Plugin):
    id = "quick_label"
    name = {"en": "Quick label", "nb": "Hurtigetikett"}
    version = "1.0.0"
    description = {
        "en": "Free text with an optional QR code. Also an example of how to write a plugin.",
        "nb": "Fri tekst med valgfri QR-kode. Også et eksempel på hvordan man skriver en plugin.",
    }

    def label_types(self):
        return [QuickLabel()]


plugin = QuickLabelPlugin()
