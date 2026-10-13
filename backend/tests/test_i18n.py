from datetime import date

import pytest

from i18n import format_date, localized, normalize_language


@pytest.mark.parametrize(
    "lang, expected",
    [("en", "en"), ("en-GB", "en"), ("nb", "nb"), ("no", "nb"), ("nn-NO", "nb"), ("sv", "en"), (None, "en"), ("", "en")],
)
def test_normalize_language(lang, expected):
    assert normalize_language(lang) == expected


def test_localized():
    assert localized("Plain", "nb") == "Plain"
    assert localized({"en": "Title", "nb": "Tittel"}, "nb") == "Tittel"
    assert localized({"en": "Title"}, "nb") == "Title"  # falls back to English
    assert localized({"de": "Titel"}, "nb") == "Titel"  # then to whatever exists


def test_format_date():
    d = date(2026, 4, 3)
    assert format_date(d, "en") == "3 Apr 2026"
    assert format_date(d, "nb") == "03.04.2026"
