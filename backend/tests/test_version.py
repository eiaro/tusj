import json
import re
from pathlib import Path

from version import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", __version__)


def test_frontend_and_backend_versions_match():
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == __version__


def test_api_reports_version(client):
    assert client.get("/openapi.json").json()["info"]["version"] == __version__
    assert client.get("/health").json()["version"] == __version__
