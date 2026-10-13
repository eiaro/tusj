import pytest
from PIL import Image, ImageDraw

import label
import layout
from i18n import AppError
from media import Media

JAR = {
    "name": "Jar",
    "style": "container",
    "border": "ornate",
    "fields": [
        {"id": "name", "type": "text", "label": "Name", "required": True},
        {"id": "expires", "type": "date-presets", "label": "Expires", "presets": ["+1y"]},
    ],
}
PREMADE = {
    "name": "Premade",
    "style": "info",
    "fields": [
        {"id": "title", "type": "text", "label": "Title", "required": True},
        {"id": "allergens", "type": "allergens", "label": "Allergens"},
    ],
}


def _draw():
    return ImageDraw.Draw(Image.new("RGB", (10, 10)))


def test_media_from_label():
    m = Media.from_label("62")
    assert (m.tape_mm, m.width_px, m.height_px, m.feed_px, m.endless) == (62, 696, None, 35, True)
    assert round(m.printable_mm, 1) == 58.9

    die_cut = Media.from_label("62x29")
    assert die_cut.endless is False and die_cut.height_px == 271 and die_cut.feed_px == 0

    assert Media.from_label("62red").two_color is True


def test_unknown_media():
    with pytest.raises(AppError) as e:
        Media.from_label("63")
    assert e.value.code == "unknown_media"


def test_dimensions_endless():
    dims = Media.from_label("62").dimensions(image_height_px=236)
    assert dims == {"tape": 62, "printable": 58.9, "length": 25.9, "feed": 3.0}


def test_scale():
    s = layout.Scale(696)
    assert s.px(24) == 24
    small = layout.Scale(306)  # 29 mm
    assert small.px(24) == 11
    assert small.px(24, 16) == 16
    assert small.font(layout.FONT_REGULAR, 36).size == layout.MIN_FONT_PX


def test_wrap_breaks_words_wider_than_the_column():
    draw = _draw()
    fnt = layout.font(layout.FONT_REGULAR, 30)
    lines = layout.wrap(draw, "Allergens: Supercalifragilistic", fnt, 100)
    assert len(lines) > 2
    assert all(draw.textlength(line, font=fnt) <= 100 for line in lines)
    assert "".join(lines).replace(" ", "") == "Allergens:Supercalifragilistic"


@pytest.mark.parametrize("media_id", ["12", "29", "38", "50", "54", "62", "102"])
@pytest.mark.parametrize("template, fields", [
    (JAR, {"name": "Smoked paprika from La Vera", "expires": "+1y"}),
    (PREMADE, {"title": "Carrot soup", "allergens": ["milk", "celery", "crustaceans"]}),
])
def test_render_fits_every_endless_width(media_id, template, fields):
    media = Media.from_label(media_id)
    image = label.render(template, fields, media=media)
    assert image.width == media.width_px
    assert 0 < image.height < 4000
    # Nothing is drawn in the outermost pixel columns, i.e. no text runs off the edge
    # (borders start a few px in).
    gray = image.convert("L")
    for x in (0, image.width - 1):
        assert min(gray.getpixel((x, y)) for y in range(image.height)) == 255, f"ink at x={x}"


def test_descenders_are_not_cut_off():
    """A last line with g/p/y must keep its descenders when the text is cropped to flow.bottom."""
    img = Image.new("RGB", (400, 200), "white")
    draw = ImageDraw.Draw(img)
    fnt = layout.font(layout.FONT_REGULAR, 40)
    flow = layout.TextFlow(draw, x=0, y=0, width=400, line_gap=10)
    flow.text("gjpqy", fnt)
    ink = img.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
    assert flow.bottom >= ink[3]


def test_qr_beside_text_keeps_descenders():
    s = layout.Scale(696)
    img = layout.qr_beside_text(696, s, "https://example.com", [("Charged gypsy", s.font(layout.FONT_REGULAR, 34))])
    gray = img.convert("L")
    # The bottom padding row stays blank: nothing was cropped into the text.
    pad = s.px(24, 6)
    assert min(gray.getpixel((x, img.height - pad)) for x in range(img.width)) == 255


def test_die_cut_is_rejected_for_now():
    with pytest.raises(AppError) as e:
        label.render(JAR, {"name": "Cumin"}, media=Media.from_label("62x29"))
    assert e.value.code == "media_not_supported"
