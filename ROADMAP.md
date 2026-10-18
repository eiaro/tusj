# Roadmap

Tusj is in **alpha**: everything below *Done* works and is tested, but expect rough edges.
Have an idea or need something here sooner? Open an issue.

**Legend:** ✅ done · 🔜 next · 🕐 later · 💡 idea, not decided

---

## ✅ Done

| | |
|---|---|
| **Kitchen labels** | Premade food (made/expiry dates, the 14 allergens) and spice jars (decorative frames), defined as YAML templates. |
| **Phone-first app** | Template-driven forms, live preview at real size, English and Norwegian, dark mode. |
| **Any tape width** | Labels are drawn for the loaded tape, 12–102 mm endless; sizes scale from a 62 mm design with a readable minimum font. |
| **Plugins** | Python plugins add label types without changing the app: fields (incl. search-as-you-type), settings with secrets, own translations. Broken plugins are isolated. See [docs/plugins.md](docs/plugins.md). |
| **InvenTree** | Part and stock location labels; the QR code uses the instance's own barcode format (`/api/barcode/generate/`, JSON fallback on older versions). Tested against a real InvenTree. |
| **Quick label** | Free text with an optional QR code, emoji or Material Design icon; also the example plugin. |
| **Several printers** | Brother QL over the network, a "save as image" printer, label size per printer, default printer per plugin, printer choice when printing, a queue per printer. |
| **Everyday use** | Copies (one job, cut between), "recent prints" with *print again*, printer status in Settings, network search for printers. |
| **Running it** | Podman/Docker containers with a healthcheck; `config.yaml` kept out of git; backend test suite (pytest). |
| **Easy install** | One `curl` command installs to `/srv/tusj` from multi-architecture images (amd64/arm64) published by GitHub Actions. |

---

## 🔜 Next

### Releases

- [x] Version number in the API and the app.
- [x] Release notes: [CHANGELOG.md](CHANGELOG.md).
- [ ] Tag `v0.1.0-alpha`.
- [ ] Tag `v0.2.0`.

### Raspberry Pi and USB printers

Tusj should run on a Raspberry Pi next to a USB printer. The USB driver is written (pyusb and `/dev/usb/lp*`) and `libusb` is in the image, but it hasn't met real hardware yet.

- [ ] Build and run the images on a Pi (ARM64).
- [ ] Verify printing over USB. Possible before the Pi too: the QL-820NWB has USB and can be passed into WSL with `usbipd-win`.
- [ ] Report the printer's real status over USB: *printed*, or the error (empty roll, wrong tape) instead of just *sent*.
- [ ] Search for USB printers in Settings (`brother_ql discover` via pyusb).
- [ ] USB in a rootless Podman container. Options, in order of preference:
  1. Mount `/dev/bus/usb` with a udev rule and group access (`--group-add keep-groups`). Survives unplugging the printer.
  2. `--device /dev/usb/lp0`. Simple, but fails if the printer isn't connected when the container starts.
  3. Fallback: run the backend directly on the Pi with systemd and keep the frontend in a container.
- [ ] Document that *Editor Lite* must be off on QL printers used over USB.

---

## 🕐 Later

### Die-cut labels and rotation

Since labels are drawn for the loaded tape, this is mostly work in the layout helpers, not a rewrite.

- [ ] Fixed-height media: draw on a fixed canvas instead of growing with the content.
- [ ] Shrink to fit: text blocks reduce their font size, then truncate with "…" at the minimum size.
- [ ] Rotation for landscape die-cut labels (e.g. 29×90).
- [ ] Rotated layout for narrow endless tape (12–18 mm): text along the tape instead of words broken over many lines.
- [ ] Preview for fixed-height labels.

### More layout helpers for plugins

- [ ] Barcodes (Code 128, EAN) via `python-barcode`.
- [ ] Images (logos, icons) on labels.
- [ ] Two-column text blocks.

### InvenTree

- [ ] Stock item labels.

### Project

- [x] CI on every push: backend tests and the frontend build (GitHub Actions, before images are published).
- [ ] Frontend tests.
- [ ] Publish a `latest` image tag for stable releases. Today only `main` is published, as `edge`, and `compose.yaml` defaults to `edge`. `v0.2.0` is the first release `latest=auto` would tag (it skips pre-releases such as `v0.1.0-alpha`). Once `v0.2.0` is published, set `flavor: latest=auto` in `.github/workflows/container-images.yml` and make `latest` the default in `compose.yaml` — in that order, or installs pull a tag that doesn't exist yet.

---

## 💡 Ideas

Not decided — say so if you'd use one of these.

- **Default printer per label type** within a plugin, e.g. InvenTree parts on 29 mm and locations on 62 mm. Today the default is per plugin.
- **Print from inside InvenTree**: an InvenTree plugin that sends jobs to Tusj, as an alternative to searching in Tusj.
- **Install plugins from the app** (upload or git URL) instead of copying them into `plugins/`.
- **Keep "recent prints" across restarts.**
- **Black/red printing** on two-colour tape (DK-22251), e.g. allergens in red.

---

## Design decisions

| Topic | Decision |
|---|---|
| Plugins | Python plugins, not only YAML: plugins need to fetch and process data. They are trusted code, installed by whoever runs Tusj. |
| Frontend | Plugins never need frontend code; the app builds forms and settings from what the backend describes. |
| InvenTree | Tusj fetches from InvenTree (search in Tusj → print). An InvenTree-side plugin is not ruled out (see *Ideas*). |
| Default printer | Per plugin, for the whole installation, not per phone. |
| Login | None for now: Tusj runs on a home network, and everyone there may change the settings. |
| Running on a Pi | Containers preferred; the backend may run directly on the Pi if USB in a container proves impractical. |

## Known limitations

- Over the network a QL printer can't report back, so the status is *sent*: an empty roll or an open cover isn't detected.
- Plugins can use only what ships in the image (Pillow, httpx, qrcode, PyYAML and the standard library); anything else needs a custom image.
- Changes in the InvenTree API or barcode format could break the InvenTree plugin; its API calls are kept in one place to make that easy to fix.
