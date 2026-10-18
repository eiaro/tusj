# USB printers on a Raspberry Pi

Network printers need nothing special. For a USB Brother QL printer, run the installer with `--usb`:

```bash
./scripts/raspberry-pi/install.sh --usb            # or: ... | bash -s -- --usb
./scripts/raspberry-pi/install.sh --usb --docker   # choose a runtime as usual
```

Then add the printer in Tusj with the connection the installer printed, for example `usb://0x04f9:0x2042` (Brother QL-700). The installer never edits `config.yaml`.

## What `--usb` does

1. **Scans** `/sys/bus/usb/devices` (falling back to `lsusb`) for Brother (`04f9`) devices whose name is a `QL-…` model and, from sysfs, that expose a USB *printer* interface — the same test `brother_ql`'s PyUSB backend uses. P-touch printers, other vendors and a QL stuck in Editor Lite mode are ignored (the last one is reported).
2. **Writes `compose.usb.yaml`** in the install directory, mapping each printer's node, e.g. `/dev/bus/usb/001/005`, to the *same path* in the backend container. `compose.yaml` is untouched. The file is rewritten from scratch on every run and deleted when no printer is found, so old paths never linger. The installer then runs Compose with `-f compose.yaml -f compose.usb.yaml` for `pull` and `up -d`. A later plain `install.sh` (without `--usb`) keeps using an existing `compose.usb.yaml`.
3. **Sets permissions** (see below).
4. **Installs a small boot unit** (see "Reboots").

No `privileged: true`, no container socket, no other USB devices.

### Why the same path

libusb (used by PyUSB) enumerates devices through `/sys/bus/usb/devices`, which is visible in the container, and then opens `/dev/bus/usb/<bus>/<device>` using the numbers from sysfs. So the container needs the node at the identical path; a udev symlink or a renamed node would not be found.

## Permissions

| | Docker (or rootful Podman) | Rootless Podman |
|---|---|---|
| Backend runs as | root | your user (container root maps to you) |
| Device node access | root can open it | **you** must be able to open it |
| Needs | nothing | a udev rule |

For rootless Podman the installer writes `/etc/udev/rules.d/99-tusj-usb.rules` with one line per printer *model* (exact vendor and product ID):

```
SUBSYSTEM=="usb", ATTR{idVendor}=="04f9", ATTR{idProduct}=="2042", OWNER="pi", MODE="0660"
```

It makes your user the owner of those devices only (mode 0660) and then reloads udev. A group such as `plugdev` is not used: rootless Podman drops supplementary groups inside the container unless `keep-groups` is configured, and it only applies to new login sessions. Existing lines in the rules file are kept, so a printer that is switched off during a rerun keeps its rule.

Everything needing root is announced ("Installing … (needs root)") and runs through `sudo` (no prompt when there is no terminal, so non-interactive runs use `sudo -n`). If that fails, the installer prints a warning, still starts Tusj, and ends with "USB setup finished with warnings"; fix the cause and rerun.

## Adding another printer

Connect it, switch it on and rerun `install.sh --usb`. The whole mapping is regenerated and the backend container is recreated (a few seconds of downtime).

## Reboots

Linux renumbers USB devices at boot, so `/dev/bus/usb/001/005` may become `001/006`. Containers hold the path they were created with, so they must be recreated when it changes. To handle this without a daemon, `--usb` installs a one-shot unit, `tusj-usb.service`, that runs `<install dir>/tusj-usb.sh refresh` after `podman-restart.service` (or `docker.service`) has started the containers:

1. It rescans and rewrites `compose.usb.yaml`.
2. It compares the result with `.compose.usb.applied`, the mapping the containers were last created with.
3. **Unchanged:** it does nothing, and the runtime's own restart handling stays in charge. **Changed (or marker missing):** it runs `compose down` then `compose up -d`. Removing first avoids podman-compose name conflicts. Your `config.yaml`, templates, plugins and `prints/` are bind mounts and are not touched.
4. A failing `down`/`up` makes the unit fail and removes the marker, so the next run retries (`systemctl status tusj-usb.service`).

**Restart policy.** `compose.yaml` uses `restart: always` for both containers. Rootless Podman's `podman-restart.service` starts at boot only containers with the `always` policy; with `unless-stopped` they stayed stopped after a reboot even though the USB refresh found nothing to change. Docker and rootful Podman behave the same with either policy. A side effect: containers you stopped manually before a shutdown also start again after the reboot. If you stop Tusj deliberately, use `compose down`. Containers created by an older version keep the old policy until they are recreated, so rerun `install.sh --usb` once after updating.

Design notes: the unit is `Type=oneshot` with `RemainAfterExit=yes`. Under systemd, Podman is started through `systemd-run --scope`, so conmon and the rootless network helpers live in their own scope instead of the unit's cgroup. A oneshot unit's cgroup is cleaned up when the unit finishes, which killed conmon and left ports 8000/8080 refusing connections. `KillMode=process` is set as a second safety net, not as the fix; `podman-restart.service` is left enabled. The `--usb` installer run uses the same recreate step, so rerunning it applies a new mapping once.

Rootless Podman uses a *user* unit in `~/.config/systemd/user` (it runs at boot because the installer enables lingering). Docker and rootful Podman use a system unit in `/etc/systemd/system` (installed with `sudo`). If you added a `KillMode=process` drop-in by hand, it is no longer needed and can be removed.
Limitations: a printer that is off or not yet enumerated at boot is not mapped until you switch it on and run `./tusj-usb.sh refresh -- podman compose` (or `docker compose`) in the install directory, or rerun the installer. Unplugging and replugging a printer also changes its number and needs the same refresh. There is no hotplug support.

## Diagnosing

```bash
./tusj-usb.sh scan                       # what the installer sees (run in the install dir)
lsusb | grep -i brother                  # is it connected? QL-700 shows as 04f9:2042
ls -l /dev/bus/usb/001/005               # owner and mode (rootless Podman: must be you, rw)
cat /srv/tusj/compose.usb.yaml           # the path must match the line above
podman compose -f compose.yaml -f compose.usb.yaml logs backend
podman exec tusj_backend_1 ls -l /dev/bus/usb/001/005   # use `docker exec` for Docker
systemctl --user status tusj-usb.service                # system-wide: without --user
```

- *Printer not found by `--usb`:* switch it on; on a QL-700 turn Editor Lite off (hold the button until its lamp goes out).
- *"usb_unavailable" / access denied in Tusj with rootless Podman:* the device is not owned by you. Check `/etc/udev/rules.d/99-tusj-usb.rules`, run `sudo udevadm trigger --action=change --subsystem-match=usb`, or replug the printer.
- *Container won't start after a reboot or replug:* the path changed; run the refresh command above.

## Manual test on Raspberry Pi OS (64-bit)

The automated tests (`backend/tests/test_installer_usb.py`) mock sysfs and the container tools. On real hardware, check each of these with Podman and again with `--docker`:

1. No printer connected: `install.sh --usb` warns, creates no `compose.usb.yaml`, Tusj starts.
2. One QL connected: the printer is listed, `compose.usb.yaml` has its node, a test label prints with `usb://0x04f9:0x<pid>`.
3. Two printers: both listed and both print. Unplug one and rerun: its mapping disappears.
4. `sudo reboot`: after boot, `compose.usb.yaml` has the current device number and printing still works (check `tusj-usb.service`).
5. Plain `install.sh` (no `--usb`) on the same machine keeps USB working.
