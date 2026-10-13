from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pathlib import Path
from pydantic import BaseModel
import io
import os
import yaml

import printers
from discovery import default_subnet, scan
from jobs import JobLog
from i18n import LANGUAGES, AppError, localized, normalize_language
from media import Media
from plugin_api import Plugin, RenderContext
from registry import Registry
from version import __version__

# TUSJ_CONFIG points to another config file, e.g. to try things without touching the real one.
CONFIG_FILE = Path(os.environ.get("TUSJ_CONFIG") or Path(__file__).parent.parent / "config.yaml")

registry = Registry()
jobs = JobLog()
MAX_COPIES = 50


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.load()
    registry.configure(load_config().get("plugins"))
    yield


app = FastAPI(title="Tusj API", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.to_detail()})


def load_config() -> dict:
    if CONFIG_FILE.is_dir():
        # What a container runtime leaves behind when config.yaml didn't exist at the first start.
        raise AppError(500, "config_is_directory",
                       f"{CONFIG_FILE} is a directory. Remove it and copy config.example.yaml to config.yaml.",
                       path=str(CONFIG_FILE))
    if not CONFIG_FILE.exists():
        # Start empty; printers can be added from the app, which then creates the file.
        return printers.migrate({})
    with open(CONFIG_FILE, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    # Older configs have a single `printer:`; it is rewritten as `printers:` on the next save.
    return printers.migrate(config)


def save_config(config: dict):
    # Write in place: config.yaml is a single-file bind mount, so it can't be replaced by rename.
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)
    except OSError as e:
        raise AppError(500, "config_save_failed", f"Could not save config: {e}", reason=str(e))


@app.get("/languages")
def get_languages():
    return list(LANGUAGES)


# --- Printers ---

@app.get("/printers")
def get_printers():
    return [printers.describe(p) for p in load_config()["printers"]]


@app.get("/printers/options")
def get_printer_options():
    return {"drivers": list(printers.DRIVERS), "models": printers.model_names(), "media": printers.media_options()}


@app.post("/printers")
def add_printer(data: dict):
    config = load_config()
    printer = printers.validate(data)
    printer = {"id": printers.new_id(config, printer["name"]), **printer}
    config["printers"].append(printer)
    save_config(config)
    return printers.describe(printer)


@app.put("/printers/{printer_id}")
def update_printer(printer_id: str, data: dict):
    config = load_config()
    printer = printers.find(config, printer_id)
    updated = {"id": printer_id, **printers.validate(data)}
    config["printers"][config["printers"].index(printer)] = updated
    save_config(config)
    return printers.describe(updated)


@app.delete("/printers/{printer_id}")
def delete_printer(printer_id: str):
    config = load_config()
    printer = printers.find(config, printer_id)
    if len(config["printers"]) == 1:
        raise AppError(400, "last_printer", "The last printer can't be removed")
    config["printers"].remove(printer)
    # Plugins that defaulted to it fall back to the first printer.
    for plugin_cfg in (config.get("plugins") or {}).values():
        if isinstance(plugin_cfg, dict) and plugin_cfg.get("printer") == printer_id:
            del plugin_cfg["printer"]
    save_config(config)
    return {"ok": True}


@app.post("/printers/test")
def test_printer(data: dict):
    """Test a printer as entered in the form (it doesn't have to be saved yet)."""
    printer = {"id": data.get("id") or "test", **printers.validate(data)}
    printers.driver(printer).test()
    return {"ok": True}


class ScanRequest(BaseModel):
    subnet: str = ""


def _scan_default_subnet() -> str:
    for p in load_config()["printers"]:
        if p.get("connection", "").startswith("tcp://"):
            return default_subnet(p["connection"][len("tcp://"):])
    return ""


@app.get("/scan/default")
def scan_default():
    return {"subnet": _scan_default_subnet()}


@app.post("/scan")
def scan_printers(req: ScanRequest):
    subnet = req.subnet or _scan_default_subnet()
    if not subnet:
        raise AppError(400, "subnet_missing", "No subnet given")
    return {"subnet": subnet, "printers": scan(subnet)}


# --- Label types ---

@app.get("/label-types")
def get_label_types():
    config = load_config()
    out = []
    for lt_id, entry, lt in registry.label_types():
        default = printers.default_for(config, entry.id) if config["printers"] else None
        out.append({
            "id": lt_id,
            "plugin": entry.id,
            "name": lt.name,
            "icon": lt.icon,
            "fields": lt.fields(),
            "media": {"min_width_mm": lt.media.min_width_mm, "endless": lt.media.endless,
                      "die_cut": lt.media.die_cut},
            "printer": default["id"] if default else None,
            "media_ok": bool(default) and lt.media.accepts(Media.from_label(default["media"])),
        })
    return out


@app.get("/label-types/{label_type_id}/search/{field_id}")
def search_label_type(label_type_id: str, field_id: str, q: str = "", lang: str | None = None):
    _, lt = registry.label_type(label_type_id)
    return lt.search(field_id, q, normalize_language(lang))


def render_label(label_type_id: str, values: dict, lang: str, printer_id: str | None):
    entry, lt = registry.label_type(label_type_id)
    printer = printers.resolve(load_config(), printer_id, entry.id)
    media = Media.from_label(printer["media"])
    if not lt.media.accepts(media):
        raise AppError(400, "media_not_supported", f"'{label_type_id}' can't be printed on {media.id} mm labels",
                       media=media.id)
    image = lt.render(values, RenderContext(lang=lang, media=media))
    return lt, printer, media, printers.driver(printer).prepare(image)


@app.post("/preview/{label_type_id}")
def preview_label(label_type_id: str, values: dict, lang: str | None = None, printer: str | None = None):
    _, _, media, image = render_label(label_type_id, values, normalize_language(lang), printer)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    headers = {f"X-Label-{k.capitalize()}-Mm": str(v) for k, v in media.dimensions(image.height).items()}
    return Response(buf.getvalue(), media_type="image/png", headers=headers)


def do_print(label_type_id: str, values: dict, lang: str, printer: str | None, copies: int) -> dict:
    if not 1 <= copies <= MAX_COPIES:
        raise AppError(400, "invalid_copies", f"Copies must be between 1 and {MAX_COPIES}", max=MAX_COPIES)
    lt, printer_cfg, _, image = render_label(label_type_id, values, lang, printer)
    entry = {"label_type": label_type_id, "label_name": lt.name, "values": values, "lang": lang,
             "printer": printer_cfg["id"], "copies": copies}
    try:
        result = printers.print_image(printer_cfg, image, job_name=label_type_id, copies=copies)
    except AppError as e:
        jobs.add(**entry, error=e.to_detail())
        raise
    job = jobs.add(**entry, status=result["status"])
    return {**result, "printer": printer_cfg["id"], "label_type": localized(lt.name, lang), "copies": copies,
            "job": job["id"]}


@app.post("/print/{label_type_id}")
def print_label(label_type_id: str, values: dict, lang: str | None = None, printer: str | None = None,
                copies: int = 1):
    return do_print(label_type_id, values, normalize_language(lang), printer, copies)


# --- Job log ---

@app.get("/jobs")
def get_jobs():
    """The last print jobs, newest first (kept in memory; cleared on restart)."""
    return jobs.list()


@app.post("/jobs/{job_id}/reprint")
def reprint_job(job_id: int):
    job = jobs.get(job_id)
    if job is None:
        raise AppError(404, "job_not_found", f"Job {job_id} not found", job=job_id)
    # Same printer if it still exists, else the label type's default.
    config = load_config()
    printer = job["printer"] if any(p["id"] == job["printer"] for p in config["printers"]) else None
    return do_print(job["label_type"], job["values"], job["lang"], printer, job["copies"])


# --- Health ---

@app.get("/health")
def health():
    """Cheap liveness check for the container: config readable, plugins loaded."""
    config = load_config()
    return {
        "status": "ok",
        "version": __version__,
        "printers": len(config["printers"]),
        "plugin_errors": {e.id: e.error for e in registry.entries.values() if e.error},
    }


@app.get("/printers/status")
def printers_status():
    """Whether each printer answers right now (tests them all at once)."""
    return printers.check_all(load_config()["printers"])


# --- Plugins ---

def _public_settings(entry) -> dict:
    """Settings as shown in the browser: secrets are replaced by whether they are set."""
    out = {}
    for spec in entry.plugin.settings_schema:
        value = entry.settings.get(spec["id"])
        out[spec["id"]] = bool(value) if spec["type"] == "secret" else value
    return out


def _plugin_info(entry, config: dict) -> dict:
    plugin = entry.plugin
    return {
        "id": entry.id,
        "builtin": entry.source == "builtin",
        "enabled": entry.enabled,
        "error": entry.error,
        "name": plugin.name if plugin else entry.id,
        "version": plugin.version if plugin else None,
        "description": plugin.description if plugin else "",
        "settings_schema": plugin.settings_schema if plugin else [],
        "settings": _public_settings(entry) if plugin else {},
        "messages": plugin.messages if plugin else {},
        "checkable": bool(plugin) and type(plugin).check is not Plugin.check,
        # The plugin's chosen default printer, or None for "the first printer".
        "printer": ((config.get("plugins") or {}).get(entry.id) or {}).get("printer"),
    }


@app.get("/plugins")
def get_plugins():
    config = load_config()
    return [_plugin_info(e, config) for e in registry.entries.values()]


class PluginUpdate(BaseModel):
    enabled: bool | None = None
    # Secrets left out or sent as "" keep their saved value.
    settings: dict | None = None
    # A printer id, or null/"" for "the first printer". Left out = unchanged.
    printer: str | None = None


@app.put("/plugins/{plugin_id}")
def update_plugin(plugin_id: str, update: PluginUpdate):
    entry = registry.get(plugin_id)
    if entry.plugin is None:
        raise AppError(400, "plugin_broken", f"Plugin '{plugin_id}' failed to load", plugin=plugin_id)

    config = load_config()
    plugins_config = config.setdefault("plugins", {}) or {}
    config["plugins"] = plugins_config
    cfg = plugins_config.setdefault(plugin_id, {})
    if update.enabled is not None:
        cfg["enabled"] = update.enabled
    if update.settings is not None:
        saved = cfg.get("settings") or {}
        for spec in entry.plugin.settings_schema:
            sid = spec["id"]
            if sid not in update.settings:
                continue
            value = update.settings[sid]
            if spec["type"] == "secret" and value in ("", None, True):
                continue
            saved[sid] = value
        cfg["settings"] = saved
    if "printer" in update.model_fields_set:
        if update.printer:
            printers.find(config, update.printer)
            cfg["printer"] = update.printer
        else:
            cfg.pop("printer", None)
    save_config(config)

    registry.configure(config["plugins"])
    return _plugin_info(registry.get(plugin_id), config)


@app.post("/plugins/{plugin_id}/check")
def check_plugin(plugin_id: str):
    entry = registry.get(plugin_id)
    if not entry.active:
        raise AppError(400, "plugin_inactive", f"Plugin '{plugin_id}' is not active", plugin=plugin_id)
    entry.plugin.check()
    return {"ok": True}
