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
| **Raspberry Pi and USB** | Runs on a Pi (ARM64) with a QL-700 over USB, tested on real hardware. `install.sh --usb` finds connected QL printers and maps only those into the container. See [docs/usb-printers.md](docs/usb-printers.md). |
| **Label editor** | Design labels in the browser: text, QR codes, icons and boxes placed in mm, with a preview drawn by the backend exactly as it prints. Die-cut labels, landscape, text that shrinks to fit, and data from plugins (InvenTree parts, locations, stock items) dragged onto the label. Published designs appear on the start page and can be printed through the API. |
| **Releases** | Version number in the API and the app, release notes in [CHANGELOG.md](CHANGELOG.md), tags from `v0.1.0-alpha` to `v0.3.0`. |

---

## 🔜 Next

### Label editor

The editor is new: it works on a desktop browser, and designs made in it are the easiest way to make your own labels.

- [ ] Barcodes (Code 128, EAN) and images (logos) as elements.
- [ ] Editing on a phone or tablet. Printing designs already works there.
- [ ] Turn the YAML templates (premade food, spice jar) into editor designs, so there is one way to make labels.
- [ ] API token, so other systems can print designs without opening Tusj to everyone on the network.

### USB printers

- [ ] Report the printer's real status over USB: *printed*, or the error (empty roll, wrong tape) instead of just *sent*.
- [ ] Search for USB printers in Settings, not only in the installer.

---

## 🕐 Later

### Layout helpers for plugins

The label editor has die-cut labels, landscape and shrink to fit; Python plugins still draw on endless tape.

- [ ] Die-cut and landscape labels for plugins.
- [ ] Rotated layout for narrow endless tape (12–18 mm): text along the tape instead of words broken over many lines.
- [ ] Barcodes and images in `layout`, shared with the editor.

### InvenTree

- [ ] Stock item labels.

### Project

- [x] CI on every push: backend tests and the frontend build (GitHub Actions, before images are published).
- [ ] Frontend tests.
- [ ] Publish a `latest` image tag for stable releases. Today `compose.yaml` defaults to `edge` (built from `main`). Releases from `v0.3.0` publish `latest` too; once that image is out, make `latest` the default in `compose.yaml` and the installer.

---

## 💡 Ideas

Not decided — say so if you'd use one of these.

- **Default printer per label type** within a plugin, e.g. InvenTree parts on 29 mm and locations on 62 mm. Today the default is per plugin.
- **Print from inside InvenTree**: an InvenTree plugin that sends jobs to Tusj, as an alternative to searching in Tusj.
- **Install plugins from the app** (upload or git URL) instead of copying them into `plugins/`.
- **Keep "recent prints" across restarts.**
- **A4 reports** on an ordinary office printer over IPP/AirPrint, e.g. a parts list or a sheet of labels.
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
| Running on a Pi | In containers, with only the detected USB printers mapped in. |
| Own labels | Designed in the label editor and stored as JSON in `designs/`; Python plugins are for labels that need code, and can provide data to designs. |

## Known limitations

- Over the network a QL printer can't report back, so the status is *sent*: an empty roll or an open cover isn't detected.
- Plugins can use only what ships in the image (Pillow, httpx, qrcode, PyYAML and the standard library); anything else needs a custom image.
- Changes in the InvenTree API or barcode format could break the InvenTree plugin; its API calls are kept in one place to make that easy to fix.
