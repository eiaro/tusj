"""Example plugin: a free-text label with an optional symbol (QR code, emoji or icon).

Shows the moving parts of a plugin: a LabelType with fields, value validation via
resolve_values(), plugin error messages, and drawing with the shared layout helpers.
"""
from plugin_api import (FONT_BOLD, FONT_REGULAR, LabelType, Plugin, RenderContext, field, layout, resolve_values,
                        symbols)


class QuickLabel(LabelType):
    id = "text"
    name = {"en": "Quick label", "nb": "Hurtigetikett"}
    icon = "✏️"

    def __init__(self, plugin):
        self.plugin = plugin

    def fields(self):
        return [
            field("title", "text", {"en": "Text", "nb": "Tekst"}, required=True),
            field("subtitle", "text", {"en": "Small text", "nb": "Liten tekst"}),
            field("symbol", "text", {"en": "Symbol", "nb": "Symbol"},
                  placeholder="QR https://…  ·  :)  ·  mdi:home",
                  help={"en": "QR followed by a link or text makes a QR code. Or an emoji (:) or :tada:) "
                              "or a Material Design Icon (mdi:home).",
                        "nb": "QR etterfulgt av en lenke eller tekst lager en QR-kode. Eller en emoji (:) eller "
                              ":tada:) eller et Material Design-ikon (mdi:home)."}),
        ]

    def symbol_image(self, values, ctx: RenderContext):
        # Labels saved before the field was renamed have a bare link in "qr".
        text = values.get("symbol") or (f"QR {values['qr']}" if values.get("qr") else None)
        if not text:
            return None
        try:
            return symbols.symbol_image(text, int(ctx.media.width_px * 1 / 3))
        except symbols.SymbolError as e:
            raise self.plugin.error(e.code, str(e), **e.params)
        except ValueError as e:
            # A QR code that is too big for the tape.
            raise self.plugin.error("symbol_too_big", str(e))

    def render(self, values, ctx: RenderContext):
        v = resolve_values(self.fields(), values, ctx.lang)
        s = ctx.scale

        def headline(draw, width):
            return layout.fit_font(draw, v["title"], FONT_BOLD, s.px(80, layout.MIN_FONT_PX),
                                   s.px(40, layout.MIN_FONT_PX), width)

        return layout.qr_beside_text(ctx.media.width_px, s, None, [
            (v["title"], headline),
            (v.get("subtitle"), s.font(FONT_REGULAR, 34)),
        ], symbol=self.symbol_image(values, ctx))


class QuickLabelPlugin(Plugin):
    id = "quick_label"
    name = {"en": "Quick label", "nb": "Hurtigetikett"}
    version = "1.1.0"
    description = {
        "en": "Free text with an optional QR code, emoji or icon. Also an example of how to write a plugin.",
        "nb": "Fri tekst med valgfri QR-kode, emoji eller ikon. Også et eksempel på hvordan man skriver en plugin.",
    }
    messages = {
        "en": {"errors": {
            "invalid_symbol": "“{symbol}” isn't a symbol. Use QR followed by a link, an emoji such as :) or :tada:, "
                              "or an icon such as mdi:home.",
            "unknown_icon": "There is no icon called “mdi:{icon}”. Browse them at pictogrammers.com/library/mdi.",
            "no_emoji_font": "This server has no emoji font installed (fonts-noto-color-emoji).",
            "symbol_too_big": "The QR code is too large for this tape. Use a shorter text.",
        }},
        "nb": {"errors": {
            "invalid_symbol": "«{symbol}» er ikke et symbol. Bruk QR etterfulgt av en lenke, en emoji som :) eller "
                              ":tada:, eller et ikon som mdi:home.",
            "unknown_icon": "Fant ikke ikonet «mdi:{icon}». Se alle på pictogrammers.com/library/mdi.",
            "no_emoji_font": "Serveren har ingen emoji-skrifttype installert (fonts-noto-color-emoji).",
            "symbol_too_big": "QR-koden er for stor for denne teipen. Bruk en kortere tekst.",
        }},
    }

    def label_types(self):
        return [QuickLabel(self)]


plugin = QuickLabelPlugin()
