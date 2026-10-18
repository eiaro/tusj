import pytest

import symbols

needs_emoji_font = pytest.mark.skipif(symbols._emoji_font_path() is None, reason="no emoji font installed")


@pytest.mark.parametrize("text, expected", [
    ("QR https://example.com", ("qr", "https://example.com")),
    ("qr   hello world", ("qr", "hello world")),
    (":)", ("emoji", "🙂")),
    ("xd", ("emoji", "😆")),
    ("<3", ("emoji", "❤️")),
    (":tada:", ("emoji", "🎉")),
    (":thumbsup:", ("emoji", "👍")),
    ("🔥", ("emoji", "🔥")),
    ("mdi:home", ("mdi", "home")),
    ("MDI:Wifi-Strength-4", ("mdi", "wifi-strength-4")),
    ("mdi:wifi_off", ("mdi", "wifi-off")),
])
def test_parse(text, expected):
    assert symbols.parse(text) == expected


@pytest.mark.parametrize("text", ["https://example.com", "hello", "QR", "QR   ", ":nosuchemoji:", "😀 hi"])
def test_parse_rejects_what_is_not_a_symbol(text):
    with pytest.raises(symbols.SymbolError) as e:
        symbols.parse(text)
    assert e.value.code == "invalid_symbol"


def _is_black_and_white(img):
    return set(img.convert("L").getdata()) <= {0, 255}


def test_qr_symbol_fits_and_is_sharp():
    img = symbols.symbol_image("QR https://example.com", 200)
    assert max(img.size) <= 200
    assert _is_black_and_white(img)


def test_mdi_symbol_is_scaled_to_size_and_black_and_white():
    img = symbols.symbol_image("mdi:home", 150)
    assert max(img.size) == 150
    assert _is_black_and_white(img)
    assert img.convert("L").getextrema() == (0, 255)


def test_unknown_mdi_icon():
    with pytest.raises(symbols.SymbolError) as e:
        symbols.symbol_image("mdi:no-such-icon", 100)
    assert e.value.code == "unknown_icon"
    assert e.value.params == {"icon": "no-such-icon"}


@needs_emoji_font
@pytest.mark.parametrize("text", [":)", ":tada:", "🔥", "❤️"])
def test_emoji_symbol_has_ink_after_thresholding(text):
    img = symbols.symbol_image(text, 150)
    assert max(img.size) == 150
    assert _is_black_and_white(img)
    # The printers threshold the image, so a light emoji must still leave dark pixels behind.
    dark = sum(1 for v in img.convert("L").getdata() if v == 0)
    assert dark > 0.05 * img.width * img.height


def test_emoji_without_font(monkeypatch):
    monkeypatch.setattr(symbols, "_emoji_font_path", lambda: None)
    with pytest.raises(symbols.SymbolError) as e:
        symbols.symbol_image("🔥", 100)
    assert e.value.code == "no_emoji_font"
