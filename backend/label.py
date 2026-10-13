"""Render a YAML template + filled-in fields to a label image."""
import calendar
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

import layout
from i18n import DEFAULT_LANGUAGE, AppError, format_date, localized
from layout import FONT_BOLD, FONT_REGULAR, Scale, TextFlow
from media import Media

DEFAULT_MEDIA = Media.from_label("62")


ALLERGENS_FILE = Path(__file__).parent / "allergens.yaml"


@lru_cache(maxsize=1)
def load_allergens() -> list[dict]:
    with open(ALLERGENS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def allergen_name(allergen_id: str, lang: str) -> str:
    for a in load_allergens():
        if a["id"] == allergen_id:
            return localized(a["name"], lang)
    return allergen_id


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def resolve_date(value: str, today: date | None = None) -> date:
    """Accept 'today', a relative preset like '+3d'/'+1w'/'+2m'/'+1y', or an ISO date."""
    today = today or date.today()
    value = str(value).strip()
    if value == "today":
        return today
    m = re.fullmatch(r"\+(\d+)([dwmy])", value)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit == "d":
            return today + timedelta(days=n)
        if unit == "w":
            return today + timedelta(weeks=n)
        if unit == "m":
            return _add_months(today, n)
        return _add_months(today, 12 * n)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise AppError(400, "invalid_date", f"Invalid date: '{value}'", value=value)


def resolve_fields(template: dict, fields: dict, lang: str = DEFAULT_LANGUAGE) -> list[tuple[dict, object]]:
    """Validate input (keyed by field id) against the template; return (field_spec, value)
    pairs with empty ones dropped."""
    resolved = []
    for spec in template["fields"]:
        value = fields.get(spec["id"])
        if value in (None, "", []):
            value = spec.get("default")
        if value in (None, "", []):
            if spec.get("required"):
                label = localized(spec["label"], lang)
                raise AppError(400, "field_required", f"Field '{label}' is required", field=label)
            continue

        if spec["type"] in ("date", "date-presets"):
            value = resolve_date(value)
        elif spec["type"] == "allergens":
            if isinstance(value, str):
                value = [value]
            value = [str(v) for v in value]
        else:
            value = str(value)
        resolved.append((spec, value))
    return resolved




def render(template: dict, fields: dict, lang: str = DEFAULT_LANGUAGE, media: Media = DEFAULT_MEDIA) -> Image.Image:
    resolved = resolve_fields(template, fields, lang)
    if not media.endless:
        raise AppError(400, "media_not_supported", f"Die-cut labels ('{media.id}') are not supported yet",
                       media=media.id)

    border = template.get("border")
    if border == "none":
        border = None
    if border not in layout.BORDER_STYLES:
        raise ValueError(f"Unknown border style '{border}' in template '{template.get('name')}'")

    s = Scale(media.width_px)
    pad = layout.border_padding(border, s)
    line_gap = s.px(10, 4)

    img = layout.endless_canvas(media.width_px)
    draw = ImageDraw.Draw(img)
    flow = TextFlow(draw, x=pad, y=pad, width=media.width_px - 2 * pad, line_gap=line_gap,
                    centered=template.get("style") == "container")

    for i, (spec, value) in enumerate(resolved):
        kind = spec["type"]
        label = localized(spec["label"], lang)
        if kind == "text":
            # The first text field is the headline.
            if i == 0:
                headline = layout.fit_font(draw, value, FONT_BOLD, s.px(96, layout.MIN_FONT_PX),
                                           s.px(48, layout.MIN_FONT_PX), flow.width)
                flow.text(value, headline)
                flow.space(line_gap)
            else:
                flow.text(value, s.font(FONT_REGULAR, 36))
        elif kind in ("date", "date-presets"):
            flow.text(f"{label}: {format_date(value, lang)}", s.font(FONT_REGULAR, 40))
        elif kind == "allergens":
            names = ", ".join(allergen_name(a, lang) for a in value)
            flow.text(f"{label}: {names}", s.font(FONT_BOLD, 36))

    height = max(flow.bottom + pad, s.px(120, 40))
    img = img.crop((0, 0, media.width_px, height))
    layout.draw_border(img, border, s)
    return img
