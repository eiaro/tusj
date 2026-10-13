# Changelog

All notable changes to Tusj. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0-alpha] — 2026-10-13

The first public version: label printing from your phone to a Brother QL printer, for the kitchen and the workshop.

### Labels

- **Premade food**: title, made date, expiry from presets (+3 days … +1 month) or a custom date, and the 14 EU allergens.
- **Spice jar**: large centred name in a frame (`simple`, `double` or `ornate`), optional expiry.
- **Quick label**: free text, small text and an optional QR code.
- **InvenTree part and stock location**: search as you type; the QR code uses your InvenTree's own barcode format, so the InvenTree app can scan it.
- Your own labels as **YAML templates** in `templates/`, or as **Python plugins** in `plugins/` — see [docs/plugins.md](docs/plugins.md).
- Labels are drawn for the tape that is loaded, from 12 mm to 102 mm endless tape. Short labels are padded to the printer's minimum length.

### App

- Phone-first web app: pick a label type, fill in the form, check the preview at real size, print.
- Copies (1–50), printer choice when printing, and a "recent prints" list with **Print again**.
- English and Norwegian Bokmål; labels print in the language you use. Dark mode follows the device.
- Settings: printers (add, edit, remove, test, network search), plugins (on/off, settings, test, default printer), language.

### Printers

- Brother QL over the network; USB (`usb://…`) and Linux device (`/dev/usb/lp*`) connections are included but not yet tested on hardware.
- A "save as image" printer that writes PNGs instead of printing.
- Several printers, a default printer per plugin, one print queue per printer, and a status check per printer.

### Running it

- Two containers (backend and nginx frontend) for Podman or Docker, with a healthcheck.
- Settings in `config.yaml`, which is not tracked by git; `config.example.yaml` shows the format.
- REST API with interactive docs at `/docs`; `GET /health` reports the version.

### Known limitations

- USB printing is untested on real hardware.
- Over the network the printer can't report back, so an empty roll or open cover isn't detected.
- Die-cut labels aren't supported; narrow tape (12 mm) has no rotated layout yet.
- No login: anyone on your network can change the settings.
- "Recent prints" is cleared when the backend restarts.

See the [roadmap](ROADMAP.md) for what's next.

[0.1.0-alpha]: https://github.com/eiaro/tusj/releases/tag/v0.1.0-alpha
