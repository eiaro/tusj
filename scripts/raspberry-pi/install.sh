#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install.sh [--docker | --podman] [--usb] [INSTALL_DIR]

Install Tusj to /srv/tusj. Podman is preferred when available; use --docker
to select Docker explicitly. INSTALL_DIR overrides the default location.

--usb  Detect connected Brother QL USB printers and give the backend container
       access to them (generates compose.usb.yaml). Rerun with --usb after
       connecting another printer.

Run from a checkout, or pipe this script from GitHub with curl. When piped,
the installer downloads the Tusj source archive before installing.
EOF
}

requested_runtime=auto
install_dir=/srv/tusj
install_dir_set=false
usb=false

while (($#)); do
  case "$1" in
    --usb)
      usb=true
      shift
      ;;
    --docker|--podman)
      runtime="${1#--}"
      if [[ "$requested_runtime" != auto && "$requested_runtime" != "$runtime" ]]; then
        printf 'Choose only one container runtime.\n' >&2
        exit 2
      fi
      requested_runtime="$runtime"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    -*)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ "$install_dir_set" == true ]]; then
        printf 'Only one install directory may be specified.\n' >&2
        usage >&2
        exit 2
      fi
      install_dir="$1"
      install_dir_set=true
      shift
      ;;
  esac
done

if (($#)); then
  printf 'Unexpected argument: %s\n' "$1" >&2
  usage >&2
  exit 2
fi

# The images are published for amd64 and arm64 only. A Raspberry Pi running a 32-bit OS
# reports armv7l/armv6l even on 64-bit hardware such as the Pi 3B+, and pulling would fail
# with an unhelpful "no matching manifest" error.
case "$(uname -m)" in
  x86_64|amd64|aarch64|arm64)
    ;;
  armv6l|armv7l|armhf)
    printf 'This is a 32-bit OS (%s). Tusj needs a 64-bit OS.\n' "$(uname -m)" >&2
    printf 'On a Raspberry Pi 3, 4 or 5, install "Raspberry Pi OS Lite (64-bit)" with Raspberry Pi Imager.\n' >&2
    exit 1
    ;;
  *)
    printf 'Warning: unsupported architecture %s; images exist for amd64 and arm64 only.\n' "$(uname -m)" >&2
    ;;
esac

source_temp=
cleanup() {
  if [[ -n "$source_temp" ]]; then
    rm -rf -- "$source_temp"
  fi
}
trap cleanup EXIT

script_path="${BASH_SOURCE[0]:-}"
if [[ -f "$script_path" ]]; then
  script_dir="$(cd -- "$(dirname -- "$script_path")" && pwd)"
  repo_root="$(cd -- "$script_dir/../.." && pwd)"
else
  if ! command -v curl >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1; then
    printf 'curl and tar are required to install from a pipe.\n' >&2
    exit 1
  fi
  source_temp="$(mktemp -d)"
  if ! curl --fail --location --silent --show-error \
    https://codeload.github.com/eiaro/tusj/tar.gz/refs/heads/main |
    tar -xz --strip-components=1 -C "$source_temp"; then
    printf 'Could not download the Tusj source archive from GitHub.\n' >&2
    exit 1
  fi
  repo_root="$source_temp"
fi

usb_script="$repo_root/scripts/raspberry-pi/usb.sh"
required_files=(compose.yaml config.example.yaml)
if [[ "$usb" == true ]]; then
  required_files+=(scripts/raspberry-pi/usb.sh)
fi
for required_file in "${required_files[@]}"; do
  if [[ ! -f "$repo_root/$required_file" ]]; then
    printf 'Required project file is missing: %s\n' "$repo_root/$required_file" >&2
    exit 1
  fi
done

compose=()
selected_runtime=

select_podman() {
  if ! command -v podman >/dev/null 2>&1; then
    return 1
  fi

  if podman compose version >/dev/null 2>&1; then
    compose=(podman compose)
  elif command -v podman-compose >/dev/null 2>&1; then
    compose=(podman-compose)
  else
    return 1
  fi

  selected_runtime=Podman
}

select_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi

  if docker compose version >/dev/null 2>&1; then
    compose=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    compose=(docker-compose)
  else
    return 1
  fi

  selected_runtime=Docker
}

runtime_available=false
case "$requested_runtime" in
  podman)
    select_podman && runtime_available=true
    ;;
  docker)
    select_docker && runtime_available=true
    ;;
  auto)
    if select_podman; then
      runtime_available=true
    elif select_docker; then
      runtime_available=true
    fi
    ;;
esac

if [[ "$runtime_available" != true ]]; then
  printf 'No usable %s installation with Compose was found.\n' \
    "$([[ "$requested_runtime" == auto ]] && printf 'Podman or Docker' || printf '%s' "$requested_runtime")" >&2
  printf 'Install Podman: sudo apt update && sudo apt install -y podman podman-compose\n' >&2
  printf 'Or install Docker: sudo apt update && sudo apt install -y docker.io docker-compose\n' >&2
  exit 1
fi

if ! mkdir -p "$install_dir"; then
  printf 'Cannot create %s. Make it writable by the current user, then rerun this script.\n' \
    "$install_dir" >&2
  exit 1
fi
install_dir="$(cd -- "$install_dir" && pwd)"

# templates/ and plugins/ are meant to be edited. When updating, keep a copy of any
# shipped file that was changed locally before replacing it; files you added are left alone.
stamp="$(date +%Y%m%d-%H%M%S)"
backups=()
for user_dir in plugins templates; do
  while IFS= read -r -d '' new_file; do
    rel="${new_file#"$repo_root/"}"
    old_file="$install_dir/$rel"
    if [[ -f "$old_file" ]] && ! cmp -s "$new_file" "$old_file"; then
      cp -p "$old_file" "$old_file.local-$stamp"
      backups+=("$rel.local-$stamp")
    fi
  done < <(find "$repo_root/$user_dir" -type f -not -path '*/__pycache__/*' -print0)
done

for app_dir in backend frontend plugins templates; do
  cp -a "$repo_root/$app_dir" "$install_dir/"
done

if ((${#backups[@]})); then
  printf 'These files had local changes and were replaced by the new version. Your versions are kept as:\n'
  printf '  %s\n' "${backups[@]}"
  printf 'To keep your own label types across updates, give them new file names.\n'
fi
cp "$repo_root/compose.yaml" "$install_dir/compose.yaml"
if [[ ! -e "$install_dir/config.yaml" ]]; then
  cp "$repo_root/config.example.yaml" "$install_dir/config.yaml"
elif [[ ! -f "$install_dir/config.yaml" ]]; then
  printf '%s exists but is not a regular file; refusing to start Tusj.\n' \
    "$install_dir/config.yaml" >&2
  exit 1
fi
mkdir -p "$install_dir/prints"

printf 'Installed Tusj files in %s using %s.\n' "$install_dir" "$selected_runtime"

usb_override=compose.usb.yaml
usb_problems=0
if [[ -f "$usb_script" ]]; then
  # Also used at boot by the unit below, and kept current on every update.
  cp "$usb_script" "$install_dir/tusj-usb.sh"
  chmod 0755 "$install_dir/tusj-usb.sh"
fi

if [[ "$usb" == true ]]; then
  # shellcheck source=usb.sh
  source "$usb_script"
  cat <<EOF

USB printers: scanning for connected Brother QL printers. Tusj will write
$install_dir/$usb_override, which maps only those device nodes into the backend
container (no privileged mode, no other USB devices).
EOF
  usb_printers=()
  while IFS= read -r usb_line; do
    [[ -n "$usb_line" ]] && usb_printers+=("$usb_line")
  done < <(usb_scan)

  if ((${#usb_printers[@]} == 0)); then
    printf 'No supported Brother QL USB printer found. Connect it, switch it on, and rerun with --usb.\n' >&2
    printf 'Removing any earlier USB mapping; network printers are not affected.\n' >&2
    usb_problems=1
  else
    printf 'Detected:\n'
    for usb_line in "${usb_printers[@]}"; do
      IFS=$'\t' read -r usb_vid usb_pid usb_model usb_path <<<"$usb_line"
      printf '  %s  usb://0x%s:0x%s  %s\n' "$usb_model" "$usb_vid" "$usb_pid" "$usb_path"
    done
  fi
  if ! usb_write_override "$install_dir/$usb_override" "${usb_printers[@]}"; then
    printf 'Could not write %s/%s.\n' "$install_dir" "$usb_override" >&2
    exit 1
  fi

  if ((${#usb_printers[@]})); then
    usb_user="$(id -un)"
    if [[ "$selected_runtime" == Podman && "$(id -u)" != 0 ]]; then
      printf 'Rootless Podman: the container runs as %s, so a udev rule will make these printers owned by %s.\n' \
        "$usb_user" "$usb_user"
      if ! { usb_setup_udev "$usb_user" "${usb_printers[@]}" && usb_check_access "${usb_printers[@]}"; }; then
        printf 'USB permission setup is incomplete. See docs/usb-printers.md ("Diagnosing").\n' >&2
        usb_problems=1
      fi
      usb_scope=user
    else
      printf '%s runs the backend as root, so no permission changes are needed.\n' "$selected_runtime"
      usb_scope=system
    fi
    # The device numbers change when the Pi reboots, so refresh the mapping at boot.
    if ! usb_install_boot_unit "$usb_scope" "$install_dir" "${compose[@]}"; then
      printf 'Could not install %s; after a reboot rerun install.sh --usb to refresh the USB mapping.\n' \
        "$usb_unit_name" >&2
      usb_problems=1
    fi
  fi
fi

cd "$install_dir"
compose_files=()
if [[ -f "$usb_override" ]]; then
  compose_files=(-f compose.yaml -f "$usb_override")
  if [[ "$usb" != true ]]; then
    printf 'Using the existing %s. Run with --usb to refresh the printer list.\n' "$usb_override"
  fi
fi
"${compose[@]}" "${compose_files[@]}" pull
if [[ "$usb" == true ]]; then
  # Recreate the containers so the new device mapping takes effect.
  if ! usb_apply "$install_dir" force "${compose[@]}"; then
    printf 'Tusj could not be started with the USB mapping; see the messages above.\n' >&2
    exit 1
  fi
else
  "${compose[@]}" "${compose_files[@]}" up -d
fi

# Start Tusj again after a reboot or power cut.
user="${USER:-$(id -un)}"
restart_ok=true
restart_hint() {
  restart_ok=false
  printf '\nCould not enable podman-restart.service. After a reboot, start Tusj with:\n  cd %s && %s up -d\n' \
    "$install_dir" "${compose[*]}"
}
if [[ "$selected_runtime" == Podman && "$(id -u)" == 0 ]]; then
  # Rootful Podman: the system-wide service restarts containers at boot.
  systemctl enable --now podman-restart.service >/dev/null 2>&1 || restart_hint
elif [[ "$selected_runtime" == Podman ]]; then
  # Rootless Podman: podman-restart.service starts only containers whose restart policy is
  # "always" (not "unless-stopped"), which is why compose.yaml uses "restart: always". It runs in
  # the user's systemd instance, which only runs at boot when lingering is enabled.
  if [[ "$(loginctl show-user "$user" --property=Linger --value 2>/dev/null)" != yes ]]; then
    if loginctl enable-linger "$user" 2>/dev/null || sudo -n loginctl enable-linger "$user" 2>/dev/null; then
      printf 'Enabled lingering for %s, so Tusj can start at boot.\n' "$user"
    else
      restart_ok=false
      printf '\nTo start Tusj automatically after a reboot, run once:\n  sudo loginctl enable-linger %s\n' "$user"
    fi
  fi
  systemctl --user enable --now podman-restart.service >/dev/null 2>&1 || restart_hint
elif [[ "$selected_runtime" == Docker ]]; then
  # Docker restarts the containers itself, as long as the Docker service starts at boot.
  if command -v systemctl >/dev/null 2>&1 && ! systemctl is-enabled --quiet docker 2>/dev/null; then
    restart_ok=false
    printf '\nTo start Tusj automatically after a reboot, run once:\n  sudo systemctl enable docker\n'
  fi
fi
if [[ "$restart_ok" == true ]]; then
  printf 'Tusj will start automatically after a reboot.\n'
fi

address="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
printf '\nTusj is starting. Open http://%s:8080\n' "${address:-<raspberry-pi-address>}"
if [[ "$usb" == true ]]; then
  if ((usb_problems)); then
    printf 'USB setup finished with warnings (see above).\n'
  else
    printf 'In Tusj, add the printer with the connection shown above, e.g. usb://0x04f9:0x2042.\n'
  fi
fi
