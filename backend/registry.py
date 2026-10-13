"""Finds, loads and configures plugins. A plugin that fails to load or set up is reported
with its error and skipped; it never takes the rest of the app down."""
import importlib
import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path

from i18n import AppError
from plugin_api import LabelType, Plugin

logger = logging.getLogger(__name__)

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"
BUILTIN_MODULES = ["builtin_plugins.templates"]


@dataclass
class PluginEntry:
    id: str
    source: str                       # "builtin" or the plugin directory
    plugin: Plugin | None = None
    enabled: bool = True
    error: str | None = None
    settings: dict = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.plugin is not None and self.enabled and self.error is None


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


class Registry:
    def __init__(self, plugins_dir: Path = PLUGINS_DIR, builtin_modules: list[str] = BUILTIN_MODULES):
        self.plugins_dir = plugins_dir
        self.builtin_modules = builtin_modules
        self.entries: dict[str, PluginEntry] = {}

    # --- Loading ---

    def load(self):
        self.entries = {}
        for name in self.builtin_modules:
            self._add(name.rsplit(".", 1)[-1], "builtin", lambda name=name: importlib.import_module(name))
        if self.plugins_dir.is_dir():
            for path in sorted(self.plugins_dir.iterdir()):
                if (path / "plugin.py").is_file():
                    self._add(path.name, str(path), lambda path=path: self._import_file(path))

    def _import_file(self, path: Path):
        spec = importlib.util.spec_from_file_location(f"tusj_plugins.{path.name}", path / "plugin.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _add(self, fallback_id: str, source: str, importer):
        try:
            module = importer()
            plugin = getattr(module, "plugin", None)
            if not isinstance(plugin, Plugin):
                raise TypeError("plugin.py must define `plugin = <Plugin subclass>()`")
            if not plugin.id:
                raise ValueError("plugin.id is empty")
            if plugin.id in self.entries:
                raise ValueError(f"duplicate plugin id '{plugin.id}' (also in {self.entries[plugin.id].source})")
            self.entries[plugin.id] = PluginEntry(plugin.id, source, plugin)
        except Exception as e:
            logger.exception("Failed to load plugin from %s", source)
            key = fallback_id if fallback_id not in self.entries else f"{fallback_id}@{source}"
            self.entries[key] = PluginEntry(key, source, error=_describe(e))

    # --- Configuration ---

    def configure(self, plugins_config: dict | None):
        """Apply the `plugins:` section of config.yaml: enabled flag and settings per plugin."""
        plugins_config = plugins_config or {}
        for entry in self.entries.values():
            if entry.plugin is None:
                continue
            cfg = plugins_config.get(entry.id) or {}
            entry.enabled = cfg.get("enabled", True)
            defaults = {s["id"]: s.get("default") for s in entry.plugin.settings_schema}
            entry.settings = {**defaults, **(cfg.get("settings") or {})}
            entry.error = None
            if entry.enabled:
                try:
                    entry.plugin.setup(dict(entry.settings))
                except Exception as e:
                    logger.exception("Failed to set up plugin %s", entry.id)
                    entry.error = _describe(e)

    # --- Lookup ---

    def get(self, plugin_id: str) -> PluginEntry:
        if plugin_id not in self.entries:
            raise AppError(404, "plugin_not_found", f"Plugin '{plugin_id}' not found", plugin=plugin_id)
        return self.entries[plugin_id]

    def label_types(self) -> list[tuple[str, PluginEntry, LabelType]]:
        """(full id, plugin entry, label type) for every active plugin. Full ids are
        '<plugin id>.<label type id>'."""
        out = []
        for entry in self.entries.values():
            if not entry.active:
                continue
            try:
                for lt in entry.plugin.label_types():
                    out.append((f"{entry.id}.{lt.id}", entry, lt))
            except Exception as e:
                logger.exception("Plugin %s failed to list label types", entry.id)
                entry.error = _describe(e)
        return out

    def label_type(self, full_id: str) -> tuple[PluginEntry, LabelType]:
        for lt_id, entry, lt in self.label_types():
            if lt_id == full_id:
                return entry, lt
        raise AppError(404, "label_type_not_found", f"Label type '{full_id}' not found", label_type=full_id)
