"""Turn a short text into a label symbol: a QR code, an emoji or a Material Design Icon.

    QR https://example.com   QR code (the text after "QR" is encoded)
    :)  :D  <3               an emoticon
    :smile:  :thumbsup:      an emoji shortcode
    😀                       an emoji typed or pasted directly
    mdi:home                 a Material Design Icon (https://pictogrammers.com/library/mdi/)

Everything is returned as black on white and already reduced to pure black and white: the
printers threshold the image, which would make the light parts of a colour emoji vanish.
"""
import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

import emoji
from PIL import Image, ImageDraw, ImageFont

import layout

logger = logging.getLogger(__name__)

MDI_DIR = Path(__file__).parent / "assets" / "mdi"

# Colour emoji fonts are bitmap fonts with one fixed size (Noto) or scalable (Segoe UI Emoji).
# Both are drawn at this size and scaled down, which also keeps the edges smooth.
EMOJI_RENDER_PX = 109
EMOJI_FONT_CANDIDATES = [
    os.environ.get("TUSJ_EMOJI_FONT", ""),
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "NotoColorEmoji.ttf",
    "/mnt/c/Windows/Fonts/seguiemj.ttf",
    "C:/Windows/Fonts/seguiemj.ttf",
]

EMOTICONS = {
    ":)": "🙂", ":-)": "🙂", "(:": "🙂", ":]": "🙂",
    ":D": "😀", ":-D": "😀", "xD": "😆", "XD": "😆",
    ";)": "😉", ";-)": "😉",
    ":(": "🙁", ":-(": "🙁", ":[": "🙁",
    ":'(": "😢", ":,(": "😢",
    ":P": "😛", ":p": "😛", ":-P": "😛",
    ":O": "😮", ":o": "😮", ":-O": "😮",
    ":|": "😐", ":-|": "😐",
    ":/": "😕", ":-/": "😕",
    ":*": "😘", ":-*": "😘",
    "B)": "😎", "8)": "😎", "B-)": "😎",
    "<3": "❤️", "</3": "💔",
}
_EMOTICONS_BY_LOWERCASE = {k.lower(): v for k, v in EMOTICONS.items()}

_QR_PREFIX = re.compile(r"^qr(?:\s+|$)", re.IGNORECASE)
_MDI_PREFIX = re.compile(r"^mdi:\s*(.*)$", re.IGNORECASE)


class SymbolError(ValueError):
    """The text is not a symbol. `code` is one of invalid_symbol, unknown_icon, no_emoji_font."""

    def __init__(self, code: str, message: str, **params):
        super().__init__(message)
        self.code = code
        self.params = params


def parse(text: str) -> tuple[str, str]:
    """('qr', data), ('emoji', characters) or ('mdi', icon name). Raises SymbolError."""
    text = text.strip()
    qr = _QR_PREFIX.match(text)
    if qr:
        data = text[qr.end():].strip()
        if not data:
            raise SymbolError("invalid_symbol", "Nothing to encode after 'QR'", symbol=text)
        return "qr", data

    icon = _MDI_PREFIX.match(text)
    if icon:
        return "mdi", icon.group(1).strip().lower().replace("_", "-")

    emoticon = _EMOTICONS_BY_LOWERCASE.get(text.lower())
    if emoticon:
        return "emoji", emoticon

    if text.startswith(":") and text.endswith(":") and len(text) > 2:
        resolved = emoji.emojize(text, language="alias")
        if resolved != text:
            return "emoji", resolved

    if emoji.purely_emoji(text):
        return "emoji", text

    raise SymbolError("invalid_symbol", f"'{text}' is not a symbol", symbol=text)


@lru_cache(maxsize=None)
def _mdi_names() -> dict[str, str]:
    return json.loads((MDI_DIR / "names.json").read_text())


@lru_cache(maxsize=None)
def _emoji_font_path() -> str | None:
    for path in EMOJI_FONT_CANDIDATES:
        if not path:
            continue
        try:
            ImageFont.truetype(path, EMOJI_RENDER_PX)
            logger.info("Using emoji font %s", path)
            return path
        except OSError:
            continue
    return None


def _fit_square(img: Image.Image, size_px: int) -> Image.Image:
    """Crop to the ink, scale to fit a size_px square and centre on white."""
    box = img.getbbox()
    if box is None:
        raise SymbolError("invalid_symbol", "The symbol has no visible shape")
    img = img.crop(box)
    ratio = min(size_px / img.width, size_px / img.height)
    return img.resize((max(1, round(img.width * ratio)), max(1, round(img.height * ratio))), Image.LANCZOS)


def _on_white(img: Image.Image, size_px: int, *, dither: bool) -> Image.Image:
    img = _fit_square(img, size_px)
    background = Image.new("RGBA", img.size, "white")
    gray = Image.alpha_composite(background, img.convert("RGBA")).convert("L")
    mono = gray.convert("1") if dither else gray.point(lambda v: 255 if v >= 128 else 0).convert("1")
    return mono.convert("RGB")


def emoji_image(characters: str, size_px: int) -> Image.Image:
    path = _emoji_font_path()
    if path is None:
        raise SymbolError("no_emoji_font", "No emoji font is installed (fonts-noto-color-emoji)")
    # The variation selector asks for the emoji form; without a text shaper it would be drawn as a box.
    characters = characters.replace("\ufe0f", "")
    font = ImageFont.truetype(path, EMOJI_RENDER_PX)
    canvas = Image.new("RGBA", (EMOJI_RENDER_PX * max(len(characters), 1) * 2, EMOJI_RENDER_PX * 2), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((EMOJI_RENDER_PX // 2, EMOJI_RENDER_PX // 2), characters, font=font,
                                embedded_color=True)
    return _on_white(canvas, size_px, dither=True)


def mdi_image(name: str, size_px: int) -> Image.Image:
    codepoint = _mdi_names().get(name)
    if codepoint is None:
        raise SymbolError("unknown_icon", f"Unknown icon 'mdi:{name}'", icon=name)
    font = ImageFont.truetype(str(MDI_DIR / "materialdesignicons-webfont.ttf"), 512)
    canvas = Image.new("RGBA", (768, 768), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((128, 128), chr(int(codepoint, 16)), font=font, fill="black")
    return _on_white(canvas, size_px, dither=False)


def symbol_image(text: str, max_size_px: int) -> Image.Image:
    """The symbol described by `text`, no larger than max_size_px, on white."""
    kind, payload = parse(text)
    if kind == "qr":
        return layout.qr_image(payload, max_size_px)
    if kind == "mdi":
        return mdi_image(payload, max_size_px)
    return emoji_image(payload, max_size_px)
