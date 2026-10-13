"""Languages, localized template values, and coded errors the frontend can translate."""
from datetime import date

LANGUAGES = ("en", "nb")
DEFAULT_LANGUAGE = "en"

# Month names are spelled out on English labels so 03/04 can't be read either way.
_EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def normalize_language(lang: str | None) -> str:
    lang = (lang or "").lower().split("-")[0]
    if lang in ("no", "nn"):
        lang = "nb"
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def localized(value, lang: str):
    """Template text is either a plain string or a {language: text} map."""
    if isinstance(value, dict):
        return value.get(lang) or value.get(DEFAULT_LANGUAGE) or next(iter(value.values()), "")
    return value


def format_date(d: date, lang: str) -> str:
    if lang == "nb":
        return d.strftime("%d.%m.%Y")
    return f"{d.day} {_EN_MONTHS[d.month - 1]} {d.year}"


class AppError(Exception):
    """An error with a stable code + params for the frontend to translate, and an English message."""

    def __init__(self, status: int, code: str, message: str, **params):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.params = params

    def to_detail(self) -> dict:
        return {"code": self.code, "message": self.message, "params": self.params}
