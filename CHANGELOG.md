# Changelog

All notable changes to Tusj. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-10-18

Install with one command on a Raspberry Pi, from prebuilt images; Quick label gets emoji and icons.

### Running it

- **One-command install** for a Raspberry Pi or any 64-bit Linux machine: `curl -fsSL https://raw.githubusercontent.com/eiaro/tusj/main/scripts/raspberry-pi/install.sh | bash`. It installs to `/srv/tusj`, prefers Podman and falls back to Docker (`--docker` picks Docker), and prints the right `apt` command if neither is installed. Running it again updates Tusj and keeps `config.yaml` and your own templates and plugins.
- **Prebuilt images** for `linux/amd64` and `linux/arm64` on GitHub Container Registry (`ghcr.io/eiaro/tusj-backend` and `tusj-frontend`), built by GitHub Actions after the backend tests and frontend build pass. `main` is published as `edge` and releases by their version tag (`v0.2.0`). `compose.yaml` pulls `edge` by default; set `TUSJ_IMAGE_TAG` to pin a release. Building from source still works with `--build`.

### Labels

- **Quick label** can show an emoji or an icon instead of a QR code. The *Symbol* field takes `QR https://…` for a QR code, an emoji (`🔥`, `:tada:`) or an emoticon (`:)`, `<3`), or a Material Design Icon (`mdi:home`).
- Plugins get `symbols.symbol_image()` and a `symbol` argument on `layout.qr_beside_text()`; text fields can have a `placeholder` and a `help` text. See [docs/plugins.md](docs/plugins.md).

### Upgrading

- **Quick label:** a link without `QR` in front is no longer turned into a QR code; it shows an explanation instead. Saved labels and *Print again* entries that use the old `qr` field keep working.
- **Emoji** need the `fonts-noto-color-emoji` font, which the backend image includes. Emoji are printed as black-and-white dithered images. Emoji built from several characters (such as 👨‍🍳) are drawn as separate symbols.

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

[0.2.0]: https://github.com/eiaro/tusj/releases/tag/v0.2.0
[0.1.0-alpha]: https://github.com/eiaro/tusj/releases/tag/v0.1.0-alpha
