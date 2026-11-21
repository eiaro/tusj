"""Designs made in the label editor: a label of a fixed size with elements placed in mm.

A design is stored as designs/<id>.json:

    {
      "name": {"en": "Part", "nb": "Del"},
      "icon": "🔩",
      "media": "62",               # brother_ql label id the design is made for
      "length_mm": 29,             # label length on endless tape (die-cut labels have their own)
      "orientation": "portrait",   # or "landscape": drawn sideways, e.g. text along narrow tape
      "source": "inventree.part",  # optional data source (plugin id . source id)
      "fields": [ {id, type, label, required, ...} ],   # filled in when printing
      "elements": [ {type, x, y, w, h, ...} ]           # mm from the top left of the label
    }

Text in elements may use placeholders: {title} for a field, {part.name} for a data source
variable, {today}. An element is left out when a placeholder it uses is empty (an optional field
left blank), so "Allergens: {allergens}" disappears without allergens. Fixed text can be one
string or one per language: {"en": "Made {made}", "nb": "Laget {made}"}. The label is drawn here, in the backend, for both the editor preview and the
print, so what the editor shows is what comes out of the printer.
"""
import json
import logging
import os
import re
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

import layout
import symbols
from i18n import AppError, localized
from media import DOTS_PER_MM, Media

logger = logging.getLogger(__name__)

DESIGNS_DIR = Path(os.environ.get("TUSJ_DESIGNS") or Path(__file__).resolve().parent.parent / "designs")
EXAMPLES_DIR = Path(__file__).resolve().parent / "example_designs"   # shipped in the image
EXAMPLES_SEEN = ".examples"  # in DESIGNS_DIR: examples already offered once, one name per line

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
FIELD_ID_RE = re.compile(r"^[a-z_][a-z0-9_]{0,31}$")
PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][\w.]*)\}")

FIELD_TYPES = ("text", "number", "date", "date-presets", "select", "allergens")
ELEMENT_TYPES = ("text", "qr", "symbol", "rect")
ORIENTATIONS = ("portrait", "landscape")
ALIGN = ("left", "center", "right")
VALIGN = ("top", "middle", "bottom")

PT_TO_PX = 300 / 72          # font sizes are in points, at the printer's 300 dpi
MIN_SHRINK_PX = 16           # text that is shrunk to fit never gets smaller than this (~1.4 mm)
LINE_HEIGHT = 1.15


def _invalid(message: str) -> AppError:
    return AppError(400, "invalid_design", message, reason=message)


# --- Storage ---

def _path(design_id: str) -> Path:
    if not ID_RE.match(design_id or ""):
        raise AppError(400, "invalid_design_id", f"Invalid design id '{design_id}'", id=str(design_id))
    return DESIGNS_DIR / f"{design_id}.json"


def list_designs() -> list[dict]:
    if not DESIGNS_DIR.is_dir():
        return []
    out = []
    for path in sorted(DESIGNS_DIR.glob("*.json")):
        if not ID_RE.match(path.stem):
            continue
        try:
            out.append({"id": path.stem, **json.loads(path.read_text(encoding="utf-8"))})
        except (OSError, ValueError):
            continue  # a broken file is skipped rather than taking the list down
    return out


def load(design_id: str) -> dict:
    path = _path(design_id)
    if not path.is_file():
        raise AppError(404, "design_not_found", f"Design '{design_id}' not found", id=design_id)
    return {"id": design_id, **json.loads(path.read_text(encoding="utf-8"))}


def save(design_id: str, design: dict) -> dict:
    path = _path(design_id)
    design = validate(design)
    try:
        DESIGNS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        raise AppError(500, "design_save_failed", f"Could not save design: {e}", reason=str(e))
    return {"id": design_id, **design}


def add_examples() -> None:
    """Copy shipped example designs into DESIGNS_DIR the first time each one is seen, so new
    examples show up after an update but one you deleted or changed is left alone."""
    examples = sorted(EXAMPLES_DIR.glob("*.json")) if EXAMPLES_DIR.is_dir() else []
    if not examples:
        return
    seen_file = DESIGNS_DIR / EXAMPLES_SEEN
    try:
        seen = set(seen_file.read_text(encoding="utf-8").split()) if seen_file.is_file() else set()
        new = [e for e in examples if e.name not in seen]
        if not new:
            return
        DESIGNS_DIR.mkdir(parents=True, exist_ok=True)
        for example in new:
            target = DESIGNS_DIR / example.name
            if not target.exists():
                shutil.copyfile(example, target)
        seen_file.write_text("".join(f"{n}\n" for n in sorted(seen | {e.name for e in new})), encoding="utf-8")
    except OSError:
        logger.exception("Could not add example designs to %s", DESIGNS_DIR)


def delete(design_id: str) -> None:
    path = _path(design_id)
    if not path.is_file():
        raise AppError(404, "design_not_found", f"Design '{design_id}' not found", id=design_id)
    path.unlink()


# --- Validation ---

def has_text(value) -> bool:
    """True for non-blank text, or a {language: text} map with at least one non-blank entry."""
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, dict) and bool(value) and all(isinstance(v, str) for v in value.values()) \
        and any(v.strip() for v in value.values())


def _text(value, what: str) -> str | dict:
    if has_text(value):
        return value
    raise _invalid(f"{what} must be text or a {{language: text}} map")


def _number(el: dict, key: str, lo: float, hi: float, default=None) -> float:
    value = el.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise _invalid(f"'{key}' must be a number between {lo} and {hi}")
    return value


def _choice(el: dict, key: str, choices: tuple, default: str) -> str:
    value = el.get(key, default)
    if value not in choices:
        raise _invalid(f"'{key}' must be one of {', '.join(choices)}")
    return value


def _validate_field(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise _invalid("Each field must be an object")
    fid = spec.get("id")
    if not isinstance(fid, str) or not FIELD_ID_RE.match(fid) or fid == "today":
        raise _invalid(f"Invalid field id '{fid}' (lowercase letters, digits and _)")
    if spec.get("type") not in FIELD_TYPES:
        raise _invalid(f"Field '{fid}' has an unknown type '{spec.get('type')}'")
    out = {**spec, "label": _text(spec.get("label"), f"The label of field '{fid}'"),
           "required": bool(spec.get("required", False))}
    if spec["type"] == "date-presets":
        presets = spec.get("presets") or []
        if not presets or not all(isinstance(p, str) and re.match(r"^\+\d+[dwmy]$", p) for p in presets):
            raise _invalid(f"Field '{fid}' needs presets like +3d, +1w, +1m, +1y")
    if spec["type"] == "select":
        options = spec.get("options") or []
        if not options or not all(isinstance(o, dict) and o.get("value") for o in options):
            raise _invalid(f"Field '{fid}' needs options")
    return out


def _validate_element(el: dict, frame: tuple[float, float]) -> dict:
    if not isinstance(el, dict) or el.get("type") not in ELEMENT_TYPES:
        raise _invalid(f"Unknown element type '{el.get('type') if isinstance(el, dict) else el}'")
    fw, fh = frame
    out = dict(el)
    out["x"] = _number(el, "x", -fw, fw)
    out["y"] = _number(el, "y", -fh, fh)
    out["w"] = _number(el, "w", 0.1, 2 * fw)
    out["h"] = _number(el, "h", 0.1, 2 * fh)
    kind = el["type"]
    if kind == "text":
        if "text" in el and not (isinstance(el["text"], str) or (
                isinstance(el["text"], dict) and all(isinstance(v, str) for v in el["text"].values()))):
            raise _invalid("'text' must be text or a {language: text} map")
        out["size"] = _number(el, "size", 4, 300, 12)
        out["bold"] = bool(el.get("bold", False))
        out["align"] = _choice(el, "align", ALIGN, "left")
        out["valign"] = _choice(el, "valign", VALIGN, "top")
        out["fit"] = _choice(el, "fit", ("shrink", "none"), "shrink")
    elif kind == "qr":
        if not isinstance(el.get("data", ""), str):
            raise _invalid("'data' must be text")
    elif kind == "symbol":
        if not isinstance(el.get("value", ""), str):
            raise _invalid("'value' must be text")
    elif kind == "rect":
        out["stroke"] = _number(el, "stroke", 0, 20, 0.5)
        out["radius"] = _number(el, "radius", 0, 50, 0)
        out["fill"] = bool(el.get("fill", False))
    return out


def validate(design: dict) -> dict:
    """Check a design as submitted by the editor; returns it normalised (without id)."""
    if not isinstance(design, dict):
        raise _invalid("A design must be an object")
    design = {k: v for k, v in design.items() if k != "id"}
    out = {"name": _text(design.get("name"), "The name"), "icon": str(design.get("icon") or "🏷️")[:8]}

    media = Media.from_label(str(design.get("media") or ""))
    out["media"] = media.id
    if media.endless:
        out["length_mm"] = _number(design, "length_mm", 5, 1000)
    out["orientation"] = _choice(design, "orientation", ORIENTATIONS, "portrait")

    source = design.get("source") or None
    if source is not None and not (isinstance(source, str) and re.match(r"^[\w-]+\.[\w-]+$", source)):
        raise _invalid(f"Invalid data source '{source}'")
    out["source"] = source

    fields = design.get("fields") or []
    if not isinstance(fields, list):
        raise _invalid("'fields' must be a list")
    out["fields"] = [_validate_field(f) for f in fields]
    ids = [f["id"] for f in out["fields"]] + ([source.split(".", 1)[1]] if source else [])
    if len(ids) != len(set(ids)):
        raise _invalid("Field ids must be unique (and differ from the data source)")

    elements = design.get("elements") or []
    if not isinstance(elements, list):
        raise _invalid("'elements' must be a list")
    frame = frame_mm({**out}, media)
    out["elements"] = [_validate_element(e, frame) for e in elements]
    return out


# --- Geometry ---

def frame_mm(design: dict, media: Media) -> tuple[float, float]:
    """Width and height of the label in mm as the editor shows it (after orientation)."""
    across = media.width_px / DOTS_PER_MM
    along = design["length_mm"] if media.endless else media.height_px / DOTS_PER_MM
    return (along, across) if design.get("orientation") == "landscape" else (across, along)


def media_info(media: Media) -> dict:
    return {
        "id": media.id,
        "tape_mm": media.tape_mm,
        "printable_mm": round(media.width_px / DOTS_PER_MM, 2),
        "endless": media.endless,
        "length_mm": None if media.endless else round(media.height_px / DOTS_PER_MM, 2),
        "two_color": media.two_color,
    }


# --- Rendering ---

def fill(text: str, values: dict[str, str]) -> str | None:
    """Replace {placeholders}. Unknown ones are left as they are, so typos show on the label;
    None if a known one is empty (the element is then left out)."""
    used = [m.group(1) for m in PLACEHOLDER_RE.finditer(text)]
    if any(name in values and not values[name] for name in used):
        return None
    return PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def _px(mm: float) -> int:
    return round(mm * DOTS_PER_MM)


def _text_layout(draw, text: str, role: str, size_px: int, width: int):
    fnt = layout.font(role, size_px)
    lines = []
    for paragraph in text.split("\n"):
        lines.extend(layout.wrap(draw, paragraph, fnt, width) or [""])
    ascent, descent = fnt.getmetrics()
    line_h = round((ascent + descent) * LINE_HEIGHT)
    height = line_h * (len(lines) - 1) + ascent + descent
    return fnt, lines, line_h, height


def _draw_text(img: Image.Image, el: dict, text: str):
    x, y, w, h = _px(el["x"]), _px(el["y"]), max(1, _px(el["w"])), max(1, _px(el["h"]))
    role = layout.FONT_BOLD if el.get("bold") else layout.FONT_REGULAR
    # Drawn into a mask of the box, so text that doesn't fit is clipped to it.
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    size = max(1, round(el.get("size", 12) * PT_TO_PX))
    fnt, lines, line_h, height = _text_layout(draw, text, role, size, w)
    if el.get("fit", "shrink") == "shrink":
        step = max(1, size // 30)
        while height > h and size - step >= MIN_SHRINK_PX:
            size -= step
            fnt, lines, line_h, height = _text_layout(draw, text, role, size, w)

    valign = el.get("valign", "top")
    top = 0 if valign == "top" else (h - height) // 2 if valign == "middle" else h - height
    for i, line in enumerate(lines):
        width = draw.textlength(line, font=fnt)
        align = el.get("align", "left")
        left = 0 if align == "left" else (w - width) / 2 if align == "center" else w - width
        draw.text((left, top + i * line_h), line, font=fnt, fill=255)
    img.paste("black", (x, y), mask)


def _paste_centered(img: Image.Image, el: dict, picture: Image.Image):
    x, y, w, h = _px(el["x"]), _px(el["y"]), _px(el["w"]), _px(el["h"])
    img.paste(picture, (x + (w - picture.width) // 2, y + (h - picture.height) // 2))


def _draw_qr(img: Image.Image, el: dict, data: str):
    size = min(_px(el["w"]), _px(el["h"]))
    try:
        qr = layout.qr_image(data, size)
    except ValueError:
        raise AppError(400, "qr_too_small", "The QR code has too much data for its size; make it larger",
                       size_mm=round(min(el["w"], el["h"]), 1))
    _paste_centered(img, el, qr)


def _draw_symbol(img: Image.Image, el: dict, value: str):
    _paste_centered(img, el, symbols.symbol_image(value, min(_px(el["w"]), _px(el["h"]))))


def _draw_rect(img: Image.Image, el: dict):
    draw = ImageDraw.Draw(img)
    x, y = _px(el["x"]), _px(el["y"])
    box = (x, y, x + max(1, _px(el["w"])) - 1, y + max(1, _px(el["h"])) - 1)
    stroke = max(1, _px(el.get("stroke", 0.5))) if el.get("stroke", 0.5) > 0 else 0
    radius = _px(el.get("radius", 0))
    if el.get("fill"):
        draw.rounded_rectangle(box, radius=radius, fill="black")
    elif stroke:
        draw.rounded_rectangle(box, radius=radius, outline="black", width=stroke)


def render(design: dict, values: dict[str, str], media: Media, lang: str = "en", turn: bool = True) -> Image.Image:
    """Draw the design with placeholder values for the loaded media. Elements whose text or
    data is empty after filling in placeholders are left out."""
    if media.id != design["media"]:
        raise AppError(400, "media_not_supported", f"This design is made for {design['media']} labels",
                       media=media.id)
    across = media.width_px
    along = _px(design["length_mm"]) if media.endless else media.height_px
    landscape = design.get("orientation") == "landscape"
    img = Image.new("RGB", (along, across) if landscape else (across, along), "white")
    for el in design["elements"]:
        kind = el["type"]
        if kind == "rect":
            _draw_rect(img, el)
            continue
        content = fill(localized(el.get({"text": "text", "qr": "data", "symbol": "value"}[kind], ""), lang), values)
        if not content or not content.strip():
            continue
        if kind == "text":
            _draw_text(img, el, content.strip("\n"))
        elif kind == "qr":
            _draw_qr(img, el, content.strip())
        else:
            _draw_symbol(img, el, content.strip())
    # Landscape designs are drawn as seen and turned to run along the tape (turn=False: as seen,
    # for the editor).
    return img.transpose(Image.Transpose.ROTATE_270) if landscape and turn else img
