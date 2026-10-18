#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install.sh [--docker | --podman] [INSTALL_DIR]

Install Tusj to /srv/tusj. Podman is preferred when available; use --docker
to select Docker explicitly. INSTALL_DIR overrides the default location.

Run from a checkout, or pipe this script from GitHub with curl. When piped,
the installer downloads the Tusj source archive before installing.
EOF
}

requested_runtime=auto
install_dir=/srv/tusj
install_dir_set=false

while (($#)); do
  case "$1" in
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

for required_file in compose.yaml config.example.yaml; do
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

cd "$install_dir"
"${compose[@]}" pull
"${compose[@]}" up -d

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
  # Rootless Podman: "restart: unless-stopped" is carried out by podman-restart.service in
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
