"""Tests for the Raspberry Pi installer's --usb provisioning.

They run scripts/raspberry-pi/install.sh under bash with fake sysfs data and fake
podman/docker/systemctl/udevadm commands, so no printer or container runtime is needed.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "scripts" / "raspberry-pi" / "install.sh"
USB = REPO / "scripts" / "raspberry-pi" / "usb.sh"

BASH = next((p for p in (r"C:\Program Files\Git\bin\bash.exe",) if Path(p).exists()), None) or shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not available")


def whoami():
    # The user the installer sees; a mocked id is not reliable under Git Bash.
    return subprocess.run([BASH, "-c", "id -un"], capture_output=True, text=True).stdout.strip()


def posix(path):
    return Path(path).as_posix()


# Logs the call; MOCK_FAIL=<word> makes any call containing that word fail.
RUNTIME = (
    'if [ "$1 $2" = "compose version" ]; then exit 0; fi\n'
    'echo "NAME $*" >> "$MOCK_LOG"\n'
    'if [ -n "${MOCK_FAIL:-}" ] && [[ " $* " == *" $MOCK_FAIL "* ]]; then exit 1; fi'
)

MOCKS = {
    # Runs the command like systemd-run --scope does, after logging it.
    "systemd-run": 'echo "systemd-run $*" >> "$MOCK_LOG"\nwhile [[ "$1" == --* ]]; do shift; done\nexec "$@"',
    # Compose runtimes only log their arguments.
    "podman": RUNTIME.replace("NAME", "podman"),
    "docker": RUNTIME.replace("NAME", "docker"),
    "systemctl": 'echo "systemctl $*" >> "$MOCK_LOG"',
    "udevadm": 'echo "udevadm $*" >> "$MOCK_LOG"',
    "loginctl": 'echo yes',
    "hostname": 'echo 192.0.2.1',
    "id": 'case "$1" in -u) echo "${MOCK_UID:-1000}";; -un) echo tester;; *) /usr/bin/id "$@";; esac',
}


class Env:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.sysfs = tmp_path / "sysfs"
        self.sysfs.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.log = tmp_path / "calls.log"
        self.log.touch()
        self.install_dir = tmp_path / "srv"
        self.rules_dir = tmp_path / "udev"
        self.rules_dir.mkdir()
        self.system_units = tmp_path / "system-units"
        self.system_units.mkdir()
        self.user_units = tmp_path / "user-units"
        for name, body in MOCKS.items():
            self.mock(name, body)
        self.vars = {
            "MOCK_LOG": posix(self.log),
            "TUSJ_USB_SYSFS": posix(self.sysfs),
            "TUSJ_LSUSB": "tusj-no-such-lsusb",
            "TUSJ_USB_NO_SUDO": "1",
            "TUSJ_UDEV_RULES_DIR": posix(self.rules_dir),
            "TUSJ_SYSTEM_UNIT_DIR": posix(self.system_units),
            "TUSJ_USER_UNIT_DIR": posix(self.user_units),
        }

    def mock(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\n" + body + "\n", newline="\n")
        path.chmod(0o755)

    def sh(self, script, *args):
        # Run through bash: sysfs interface directory names contain ":", which Windows paths reject.
        subprocess.run([BASH, "-c", script, "sh", *args], check=True)

    def device(self, bus, dev, vid="04f9", pid="2042", product="QL-700", printer_class=True):
        d = f"{posix(self.sysfs)}/{bus}-{dev}"
        self.sh(
            'd=$1; mkdir -p "$d/${d##*/}:1.0"; shift; '
            'printf "%s\n" "$1" > "$d/idVendor"; printf "%s\n" "$2" > "$d/idProduct"; '
            'printf "%s\n" "$3" > "$d/product"; printf "%s\n" "$4" > "$d/busnum"; '
            'printf "%s\n" "$5" > "$d/devnum"; printf "%s\n" "$6" > "$d/${d##*/}:1.0/bInterfaceClass"',
            d, vid, pid, product, str(bus), str(dev), "07" if printer_class else "08",
        )

    def clear_devices(self):
        self.sh('rm -rf "$1"/*', posix(self.sysfs))
    def run(self, *args, uid=1000, **extra):
        env = dict(os.environ)
        env.update(self.vars)
        env.update({k: str(v) for k, v in extra.items()})
        env["MOCK_UID"] = str(uid)
        env["PATH"] = f"{self.bin}{os.pathsep}{env['PATH']}"
        env["HOME"] = posix(self.tmp / "home")
        return subprocess.run(
            [BASH, posix(INSTALL), *args, posix(self.install_dir)],
            env=env, capture_output=True, text=True, timeout=120,
        )

    def calls(self):
        return self.log.read_text().splitlines()

    @property
    def override(self):
        return self.install_dir / "compose.usb.yaml"


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_without_usb_flag_nothing_changes(env):
    env.device(1, 5)
    r = env.run("--podman")
    assert r.returncode == 0, r.stderr
    assert not env.override.exists()
    assert "podman compose pull" in env.calls()
    assert "podman compose up -d" in env.calls()
    assert not list(env.rules_dir.iterdir())


def test_no_printers(env):
    r = env.run("--podman", "--usb")
    assert r.returncode == 0, r.stderr
    assert "No supported Brother QL USB printer found" in r.stderr
    assert not env.override.exists()
    assert "podman compose -f compose.yaml up -d" in env.calls()


def test_one_printer_rootless_podman(env):
    env.device(1, 5)
    r = env.run("--podman", "--usb")
    assert r.returncode == 0, r.stderr
    assert "usb://0x04f9:0x2042" in r.stdout and "QL-700" in r.stdout
    assert env.override.read_text().splitlines()[1:] == [
        "services:",
        "  backend:",
        "    devices:",
        "      - /dev/bus/usb/001/005:/dev/bus/usb/001/005",
    ]
    assert "podman compose -f compose.yaml -f compose.usb.yaml pull" in env.calls()
    assert "podman compose -f compose.yaml -f compose.usb.yaml up -d" in env.calls()
    rules = (env.rules_dir / "99-tusj-usb.rules").read_text()
    assert f'ATTR{{idVendor}}=="04f9", ATTR{{idProduct}}=="2042", OWNER="{whoami()}", MODE="0660"' in rules
    assert "GROUP" not in rules
    unit = (env.user_units / "tusj-usb.service").read_text()
    assert "refresh --install-dir" in unit and "-- podman compose" in unit
    assert "systemctl --user enable tusj-usb.service" in env.calls()
    assert "udevadm control --reload-rules" in env.calls()


def test_multiple_printers_ignore_unsupported_devices(env):
    env.device(1, 5)
    env.device(1, 7, pid="209d", product="QL-820NWB")
    env.device(1, 8, pid="2061", product="PT-P700")  # Brother, but not a QL
    env.device(1, 9, vid="0781", pid="5567", product="QL-700 lookalike")  # other vendor
    env.device(2, 3, pid="2042", product="QL-700", printer_class=False)  # Editor Lite mode
    r = env.run("--podman", "--usb")
    assert r.returncode == 0, r.stderr
    text = env.override.read_text()
    assert text.count("/dev/bus/usb/") == 4  # two printers, host:container each
    assert "001/005" in text and "001/007" in text
    assert "001/008" not in text and "001/009" not in text and "002/003" not in text
    assert "Editor Lite" in r.stderr
    rules = (env.rules_dir / "99-tusj-usb.rules").read_text()
    assert "2042" in rules and "209d" in rules and "2061" not in rules


def test_rerun_replaces_stale_mappings_and_keeps_udev_rules(env):
    env.device(1, 5)
    env.run("--podman", "--usb")
    env.clear_devices()
    env.device(1, 6)  # same printer, new number after a reboot
    env.device(1, 7, pid="209d", product="QL-820NWB")
    r = env.run("--podman", "--usb")
    assert r.returncode == 0, r.stderr
    text = env.override.read_text()
    assert "001/005" not in text and "001/006" in text and "001/007" in text
    assert len(env.rules_dir.joinpath("99-tusj-usb.rules").read_text().splitlines()) == 3
    env.clear_devices()
    env.run("--podman", "--usb")
    assert not env.override.exists()


def test_rerun_without_usb_keeps_using_override(env):
    env.device(1, 5)
    env.run("--podman", "--usb")
    env.log.write_text("")
    r = env.run("--podman")
    assert r.returncode == 0, r.stderr
    assert "podman compose -f compose.yaml -f compose.usb.yaml up -d" in env.calls()


def test_docker_needs_no_udev_rules_and_uses_system_unit(env):
    env.device(1, 5)
    r = env.run("--docker", "--usb")
    assert r.returncode == 0, r.stderr
    assert "docker compose -f compose.yaml -f compose.usb.yaml up -d" in env.calls()
    assert not list(env.rules_dir.iterdir())
    unit = (env.system_units / "tusj-usb.service").read_text()
    assert "-- docker compose" in unit and "After=network-online.target docker.service" in unit
    assert f"User={whoami()}" in unit
    assert "systemctl enable tusj-usb.service" in env.calls()


def test_missing_detection_utilities(env):
    shutil.rmtree(env.sysfs)
    r = env.run("--podman", "--usb")
    assert r.returncode == 0, r.stderr
    assert "Cannot detect USB devices" in r.stderr
    assert not env.override.exists()


def test_lsusb_fallback(env):
    shutil.rmtree(env.sysfs)
    env.mock("lsusb", 'echo "Bus 001 Device 005: ID 04f9:2042 Brother Industries, Ltd QL-700 Label Printer"\n'
                      'echo "Bus 001 Device 006: ID 04f9:2061 Brother Industries, Ltd PT-P700"\n'
                      'echo "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub"')
    r = env.run("--podman", "--usb", TUSJ_LSUSB="lsusb")
    assert r.returncode == 0, r.stderr
    text = env.override.read_text()
    assert "/dev/bus/usb/001/005" in text and "001/006" not in text


def test_failed_permission_setup_warns_but_still_starts(env):
    env.device(1, 5)
    r = env.run("--podman", "--usb", TUSJ_UDEV_RULES_DIR=env.tmp / "missing" / "rules.d")
    assert r.returncode == 0
    assert "USB permission setup is incomplete" in r.stderr
    assert "finished with warnings" in r.stdout
    assert "podman compose -f compose.yaml -f compose.usb.yaml up -d" in env.calls()


def refresh(env, *compose, **extra):
    environ = {**os.environ, **env.vars, "PATH": f"{env.bin}{os.pathsep}{os.environ['PATH']}"}
    environ.update({k: str(v) for k, v in extra.items()})
    return subprocess.run(
        [BASH, posix(env.install_dir / "tusj-usb.sh"), "refresh", "--install-dir",
         posix(env.install_dir), "--", *(compose or ("docker", "compose"))],
        env=environ, capture_output=True, text=True, timeout=60,
    )


def test_refresh_after_reboot_with_changed_number_recreates_containers(env):
    env.device(1, 5)
    env.run("--docker", "--usb")
    env.clear_devices()
    env.device(1, 9)
    env.log.write_text("")
    r = refresh(env)
    assert r.returncode == 0, r.stderr
    assert "001/009" in env.override.read_text() and "001/005" not in env.override.read_text()
    assert env.calls() == [
        "docker compose -f compose.yaml -f compose.usb.yaml down",
        "docker compose -f compose.yaml -f compose.usb.yaml up -d",
    ]
    assert "001/009" in (env.install_dir / ".compose.usb.applied").read_text()


def test_refresh_with_unchanged_mapping_leaves_containers_alone(env):
    env.device(1, 5)
    env.run("--podman", "--usb")
    env.log.write_text("")
    r = refresh(env, "podman", "compose")
    assert r.returncode == 0, r.stderr
    assert env.calls() == []
    assert "unchanged" in r.stdout


def test_refresh_without_printers_before_and_after(env):
    env.run("--podman", "--usb")  # nothing connected: marker records "no mapping"
    env.log.write_text("")
    assert refresh(env, "podman", "compose").returncode == 0
    assert env.calls() == []
    env.device(1, 5)
    assert refresh(env, "podman", "compose").returncode == 0
    assert env.calls()[-1] == "podman compose -f compose.yaml -f compose.usb.yaml up -d"


def test_refresh_recreates_when_never_applied(env):
    # Installations made before the marker existed are recreated once.
    env.device(1, 5)
    env.run("--podman", "--usb")
    (env.install_dir / ".compose.usb.applied").unlink()
    env.log.write_text("")
    assert refresh(env, "podman", "compose").returncode == 0
    assert [c for c in env.calls() if c.endswith(" down") or c.endswith(" up -d")] == [
        "podman compose -f compose.yaml -f compose.usb.yaml down",
        "podman compose -f compose.yaml -f compose.usb.yaml up -d",
    ]


def test_refresh_propagates_compose_failure_and_retries(env):
    env.device(1, 5)
    env.run("--podman", "--usb")
    env.clear_devices()
    env.device(1, 6)
    r = refresh(env, "podman", "compose", MOCK_FAIL="up")
    assert r.returncode != 0
    assert not (env.install_dir / ".compose.usb.applied").exists()
    env.log.write_text("")
    r = refresh(env, "podman", "compose")  # next boot succeeds and recreates again
    assert r.returncode == 0, r.stderr
    assert env.calls()[-1] == "podman compose -f compose.yaml -f compose.usb.yaml up -d"
    assert (env.install_dir / ".compose.usb.applied").exists()


def test_refresh_continues_when_down_fails_but_not_when_up_fails(env):
    env.device(1, 5)
    env.run("--podman", "--usb")
    env.clear_devices()
    env.device(1, 6)
    r = refresh(env, "podman", "compose", MOCK_FAIL="down")
    assert r.returncode == 0
    assert "'down' failed" in r.stderr


def test_installer_fails_when_containers_cannot_start(env):
    env.device(1, 5)
    r = env.run("--podman", "--usb", MOCK_FAIL="up")
    assert r.returncode != 0
    assert "could not be started" in r.stderr
    assert not (env.install_dir / ".compose.usb.applied").exists()


def test_installer_rerun_is_idempotent(env):
    env.device(1, 5)
    env.run("--podman", "--usb")
    before = env.override.read_text()
    r = env.run("--podman", "--usb")
    assert r.returncode == 0, r.stderr
    assert env.override.read_text() == before
    assert (env.install_dir / ".compose.usb.applied").read_text() == before


def test_podman_runs_in_own_scope_under_systemd_only(env):
    env.device(1, 5)
    env.run("--podman", "--usb")
    env.clear_devices()
    env.device(1, 6)
    env.log.write_text("")
    assert refresh(env, "podman", "compose").returncode == 0
    assert not [c for c in env.calls() if c.startswith("systemd-run")]
    env.clear_devices()
    env.device(1, 7)
    env.log.write_text("")
    assert refresh(env, "podman", "compose", INVOCATION_ID="1").returncode == 0
    scoped = [c for c in env.calls() if c.startswith("systemd-run")]
    assert len(scoped) == 2 and all("--scope --collect" in c and "--user" in c for c in scoped)
    # Docker's daemon owns its containers; no scope needed.
    env.clear_devices()
    env.device(1, 8)
    env.log.write_text("")
    assert refresh(env, "docker", "compose", INVOCATION_ID="1").returncode == 0
    assert not [c for c in env.calls() if c.startswith("systemd-run")]


def test_boot_unit_does_not_kill_leftover_processes(env):
    env.device(1, 5)
    env.run("--podman", "--usb")
    unit = (env.user_units / "tusj-usb.service").read_text()
    assert "Type=oneshot" in unit and "RemainAfterExit=yes" in unit and "KillMode=process" in unit
    assert "After=podman-restart.service" in unit


def test_rootful_podman_unit_waits_for_podman_restart(env):
    probe = subprocess.run([BASH, "-c", "id -u"], capture_output=True, text=True,
                           env={**os.environ, "PATH": f"{env.bin}{os.pathsep}{os.environ['PATH']}", "MOCK_UID": "0"})
    if probe.stdout.strip() != "0":
        pytest.skip("this bash does not let the test fake uid 0")
    env.device(1, 5)
    r = env.run("--podman", "--usb", uid=0)
    assert r.returncode == 0, r.stderr
    unit = (env.system_units / "tusj-usb.service").read_text()
    assert "After=network-online.target podman-restart.service" in unit
    assert "KillMode=process" in unit

def test_compose_services_restart_always():
    # podman-restart.service only starts containers with restart-policy=always.
    yaml = pytest.importorskip("yaml")
    services = yaml.safe_load((REPO / "compose.yaml").read_text())["services"]
    assert {n: s["restart"] for n, s in services.items()} == {"backend": "always", "frontend": "always"}


def test_usb_override_is_compatible_with_base_compose(env):
    yaml = pytest.importorskip("yaml")
    env.device(1, 5)
    env.device(1, 7, pid="209d", product="QL-820NWB")
    assert env.run("--podman", "--usb").returncode == 0
    base = yaml.safe_load((REPO / "compose.yaml").read_text())["services"]
    override = yaml.safe_load(env.override.read_text())
    assert list(override) == ["services"] and list(override["services"]) == ["backend"]
    assert list(override["services"]["backend"]) == ["devices"]  # nothing else is overridden
    assert "devices" not in base["backend"]
    assert override["services"]["backend"]["devices"] == [
        "/dev/bus/usb/001/005:/dev/bus/usb/001/005",
        "/dev/bus/usb/001/007:/dev/bus/usb/001/007",
    ]


def test_scripts_have_valid_syntax():
    for script in (INSTALL, USB):
        r = subprocess.run([BASH, "-n", posix(script)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
