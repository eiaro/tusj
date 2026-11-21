# Your own plugins

Put your own plugins here, one folder per plugin with a `plugin.py` (see
[docs/plugins.md](../docs/plugins.md)). This folder is mounted into the backend container.

The plugins that ship with Tusj (InvenTree, Quick label) are part of the backend image, in
[`backend/bundled_plugins/`](../backend/bundled_plugins). A folder here with the same name as a
bundled plugin is ignored.
