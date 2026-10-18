"""Drawing helpers shared by label renderers: fonts, text flow, fitting, borders.

Sizes are designed for 62 mm tape (696 px printable at 300 dpi) and scaled to the media
in use with Scale.px(), so one design works from 12 mm to 102 mm tape.
"""
import logging
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

REFERENCE_WIDTH = 696
# Smallest font that is still comfortably readable on a thermal label (~2 mm).
MIN_FONT_PX = 24

FONT_REGULAR = "regular"
FONT_BOLD = "bold"

# Tried in order. DejaVu is installed in the container; the Windows fonts cover local
# development on Windows and in WSL. TUSJ_FONT / TUSJ_FONT_BOLD override.
FONT_CANDIDATES = {
    FONT_REGULAR: [
        os.environ.get("TUSJ_FONT", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
        "/mnt/c/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
    FONT_BOLD: [
        os.environ.get("TUSJ_FONT_BOLD", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
        "/mnt/c/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
}


@lru_cache(maxsize=None)
def _font_path(role: str) -> str | None:
    for path in FONT_CANDIDATES[role]:
        if not path:
            continue
        try:
            ImageFont.truetype(path, 10)
            logger.info("Using %s font %s", role, path)
            return path
        except OSError:
            continue
    # Pillow's built-in font has no bold and no æøå.
    logger.error("No %s font found, falling back to Pillow's default font (no æøå). "
                 "Install fonts-dejavu-core or set TUSJ_FONT.", role)
    return None


@lru_cache(maxsize=None)
def font(role: str, size: int) -> ImageFont.FreeTypeFont:
    path = _font_path(role)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)


class Scale:
    """Converts sizes designed for 62 mm tape to the current media width."""

    def __init__(self, width_px: int):
        self.width_px = width_px
        self.factor = width_px / REFERENCE_WIDTH

    def px(self, base: float, minimum: int = 1) -> int:
        return max(minimum, round(base * self.factor))

    def font(self, role: str, base_size: int) -> ImageFont.FreeTypeFont:
        return font(role, self.px(base_size, MIN_FONT_PX))


def _split_long_word(draw: ImageDraw.ImageDraw, word: str, fnt, max_width: int) -> list[str]:
    """Break a word that is wider than the column into pieces that fit (narrow tape)."""
    pieces, piece = [], ""
    for ch in word:
        if piece and draw.textlength(piece + ch, font=fnt) > max_width:
            pieces.append(piece)
            piece = ch
        else:
            piece += ch
    return pieces + [piece] if piece else pieces


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    """Greedy word wrap; words wider than max_width are broken across lines."""
    lines, line = [], ""
    for word in text.split():
        if draw.textlength(word, font=fnt) > max_width:
            if line:
                lines.append(line)
            *full, line = _split_long_word(draw, word, fnt, max_width)
            lines.extend(full)
            continue
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=fnt) <= max_width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit_font(draw: ImageDraw.ImageDraw, text: str, role: str, max_size: int, min_size: int, max_width: int):
    """Largest font size where the text fits on one line, else min_size (and it will wrap)."""
    step = max(1, round(max_size / 24))
    for size in range(max_size, min_size, -step):
        fnt = font(role, size)
        if draw.textlength(text, font=fnt) <= max_width:
            return fnt
    return font(role, min_size)


class TextFlow:
    """Lays text out top to bottom inside a column, wrapping as needed."""

    def __init__(self, draw: ImageDraw.ImageDraw, x: int, y: int, width: int, line_gap: int, centered: bool = False):
        self.draw = draw
        self.x = x
        self.y = y
        self.width = width
        self.line_gap = line_gap
        self.centered = centered
        self._ink_bottom = y

    def text(self, text: str, fnt, fill="black"):
        for part in wrap(self.draw, text, fnt, self.width):
            if self.centered:
                x = self.x + (self.width - self.draw.textlength(part, font=fnt)) / 2
            else:
                x = self.x
            self.draw.text((x, self.y), part, font=fnt, fill=fill)
            # Descenders (g, p, y) reach below font.size; remember how far the ink goes.
            self._ink_bottom = max(self._ink_bottom, self.draw.textbbox((x, self.y), part, font=fnt)[3])
            self.y += fnt.size + self.line_gap

    def space(self, px: int):
        self.y += px

    @property
    def bottom(self) -> int:
        """y just below the last line of text, including descenders (without the trailing gap)."""
        return max(self.y - self.line_gap, self._ink_bottom)


def qr_image(data: str, max_size_px: int, error_correction: str = "M") -> Image.Image:
    """A black-on-white QR code no larger than max_size_px, with whole-pixel modules so it
    stays sharp on the printer, and no quiet zone (leave margin around it yourself)."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q

    levels = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}
    qr = qrcode.QRCode(error_correction=levels[error_correction], border=0, box_size=1)
    qr.add_data(data)
    qr.make(fit=True)
    modules = qr.modules_count
    box = max_size_px // modules
    if box < 2:
        raise ValueError(f"QR code with {modules} modules does not fit in {max_size_px} px")
    img = qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
    return img.resize((modules * box, modules * box), Image.NEAREST)


def qr_beside_text(width_px: int, scale: "Scale", qr_data: str | None, lines: list, qr_fraction: float = 1 / 3,
                   min_height_px: int = 0, symbol: Image.Image | None = None) -> Image.Image:
    """An endless-tape label with a QR code on the left and text on the right, both
    vertically centred. `lines` is a list of (text, font) where font is a FreeTypeFont or
    a callable (draw, column_width) -> FreeTypeFont, e.g. to fit a headline to the column.
    `symbol` is a ready-made image (e.g. from symbols.symbol_image) shown instead of a QR code.
    Without qr_data or symbol the text uses the full width."""
    pad, gap, line_gap = scale.px(24, 6), scale.px(20, 6), scale.px(10, 4)
    qr = symbol if symbol is not None else qr_image(qr_data, int(width_px * qr_fraction)) if qr_data else None
    text_x = pad + (qr.width + gap if qr else 0)
    column = width_px - text_x - pad

    text = endless_canvas(column)
    draw = ImageDraw.Draw(text)
    flow = TextFlow(draw, x=0, y=0, width=column, line_gap=line_gap)
    for content, fnt in lines:
        if content:
            flow.text(content, fnt(draw, column) if callable(fnt) else fnt)
    text = text.crop((0, 0, column, max(flow.bottom, 1)))

    content_h = max(text.height, qr.height if qr else 0, min_height_px - 2 * pad)
    img = Image.new("RGB", (width_px, content_h + 2 * pad), "white")
    if qr:
        img.paste(qr, (pad, pad + (content_h - qr.height) // 2))
    img.paste(text, (text_x, pad + (content_h - text.height) // 2))
    return img


def endless_canvas(width_px: int, max_height_px: int = 4000) -> Image.Image:
    """A tall scratch canvas for endless tape; crop it to the used height when done."""
    return Image.new("RGB", (width_px, max_height_px), "white")


# --- Borders ---

BORDER_STYLES = (None, "simple", "double", "ornate")

# Distance from the label edge to the content per border style, at reference width.
_BORDER_PADDING = {None: 24, "simple": 36, "double": 44, "ornate": 52}


def border_padding(style: str | None, scale: Scale) -> int:
    return scale.px(_BORDER_PADDING[style], 6)


def _diamond(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float):
    draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill="black")


def draw_border(img: Image.Image, style: str | None, scale: Scale):
    if style is None:
        return
    draw = ImageDraw.Draw(img)
    w, h = img.size
    p = scale.px
    if style == "simple":
        draw.rounded_rectangle((p(8), p(8), w - 1 - p(8), h - 1 - p(8)), radius=p(16), outline="black", width=p(4, 2))
    elif style == "double":
        draw.rounded_rectangle((p(6), p(6), w - 1 - p(6), h - 1 - p(6)), radius=p(18), outline="black", width=p(5, 2))
        draw.rounded_rectangle((p(18), p(18), w - 1 - p(18), h - 1 - p(18)), radius=p(10), outline="black", width=p(2))
    elif style == "ornate":
        draw.rounded_rectangle((p(6), p(6), w - 1 - p(6), h - 1 - p(6)), radius=p(22), outline="black", width=p(5, 2))
        draw.rounded_rectangle((p(20), p(20), w - 1 - p(20), h - 1 - p(20)), radius=p(12), outline="black", width=p(2))
        # Break the outer frame at the middle of the top and bottom edges with a diamond.
        for y in (p(8), h - 1 - p(8)):
            draw.rectangle((w / 2 - p(26), y - p(6), w / 2 + p(26), y + p(6)), fill="white")
            _diamond(draw, w / 2, y, p(11))
            _diamond(draw, w / 2 - p(20), y, p(4))
            _diamond(draw, w / 2 + p(20), y, p(4))
        # Small diamonds tucked into the inner corners.
        for cx in (p(34), w - 1 - p(34)):
            for cy in (p(34), h - 1 - p(34)):
                _diamond(draw, cx, cy, p(6))
    else:
        raise ValueError(f"Unknown border style '{style}'")
