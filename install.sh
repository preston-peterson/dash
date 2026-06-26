#!/usr/bin/env bash
# =============================================================================
# dash — one-line installer
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/preston-peterson/dash/main/install.sh)
#
# Sets up dash (a self-hosted home-lab dashboard) as a Docker Compose service:
# checks for Docker, writes a compose file, pulls the image, starts it, and
# prints where to open it. Safe to re-run.
#
# Flags:
#   --dir <path>        Install directory (default: ~/dash)
#   --port <n>          Host HTTPS port (default: 8443)
#   --image <ref>       Container image (default: ghcr.io/preston-peterson/dash:latest)
#   --build             Build from source (git clone) instead of pulling the image
#   --tls-hosts <list>  Comma-separated hostnames/IPs for the TLS cert SAN
#   --update-repo <r>   GitHub owner/repo for update notifications (default: upstream)
#   -y, --yes           Non-interactive; accept all defaults
#   -h, --help          Show this help and exit
# =============================================================================
set -euo pipefail

GREEN='\033[32m\033[1m'; RED='\033[31m\033[1m'; CYAN='\033[36m\033[1m'
YELLOW='\033[33m\033[1m'; DIM='\033[2m'; RESET='\033[0m'

REPO="preston-peterson/dash"
DEFAULT_IMAGE="ghcr.io/preston-peterson/dash:latest"

DIR="$HOME/dash"
PORT="8443"
IMAGE="$DEFAULT_IMAGE"
BUILD=false
TLS_HOSTS=""
UPDATE_REPO="$REPO"
ASSUME_YES=false
# Track which values came from flags so we don't re-prompt for them.
DIR_SET=false; PORT_SET=false; TLS_HOSTS_SET=false

show_help() {
    cat <<'EOF'
dash — one-line installer

  bash <(curl -fsSL https://raw.githubusercontent.com/preston-peterson/dash/main/install.sh)

Flags:
  --dir <path>        Install directory (default: ~/dash)
  --port <n>          Host HTTPS port (default: 8443)
  --image <ref>       Container image (default: ghcr.io/preston-peterson/dash:latest)
  --build             Build from source (git clone) instead of pulling the image
  --tls-hosts <list>  Comma-separated hostnames/IPs for the TLS cert SAN
  --update-repo <r>   GitHub owner/repo for update notifications
  -y, --yes           Non-interactive; accept all defaults
  -h, --help          Show this help and exit
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dir)         DIR="$2"; DIR_SET=true; shift 2 ;;
        --port)        PORT="$2"; PORT_SET=true; shift 2 ;;
        --image)       IMAGE="$2"; shift 2 ;;
        --build)       BUILD=true; shift ;;
        --tls-hosts)   TLS_HOSTS="$2"; TLS_HOSTS_SET=true; shift 2 ;;
        --update-repo) UPDATE_REPO="$2"; shift 2 ;;
        -y|--yes)      ASSUME_YES=true; shift ;;
        -h|--help)     show_help; exit 0 ;;
        *) echo -e "${RED}Unknown option: $1${RESET}" >&2; echo "Run with --help for usage" >&2; exit 1 ;;
    esac
done

abspath() { local p="${1/#\~/$HOME}"; case "$p" in /*) echo "$p" ;; *) echo "$(pwd)/$p" ;; esac; }
DIR="$(abspath "$DIR")"

log_step() { echo -e "${CYAN}[$1]${RESET} $2"; }
log_ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
log_err()  { echo -e "  ${RED}✗${RESET} $1" >&2; }
log_info() { echo -e "  ${DIM}·${RESET} $1"; }

# Read with a default. Non-interactive (piped, or -y) silently takes the default.
ask_default() {
    local prompt="$1" default="$2" __var="$3" input=""
    if [ "$ASSUME_YES" = true ] || [ ! -t 0 ]; then printf -v "$__var" '%s' "$default"; return 0; fi
    if [ -n "$default" ]; then read -r -p "  $prompt [$default]: " input; else read -r -p "  $prompt: " input; fi
    printf -v "$__var" '%s' "${input:-$default}"
}

# Yes/No confirm. Non-interactive returns the default.
confirm() {
    local prompt="$1" def="${2:-Y}" reply=""
    if [ "$ASSUME_YES" = true ]; then return 0; fi   # -y / --yes => yes to all
    if [ ! -t 0 ]; then [ "$def" = "Y" ]; return; fi # piped, no -y => take the default
    read -r -p "  $prompt " reply
    reply="${reply:-$def}"
    [[ "$reply" =~ ^[Yy]$ ]]
}

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${CYAN}║               dash — installer               ║${RESET}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${RESET}"
echo ""

# ---------------------------------------------------------------------------
# [1/6] Platform
# ---------------------------------------------------------------------------
log_step "1/6" "Checking platform..."
OS_PRETTY="unknown"
[ -r /etc/os-release ] && eval "$(. /etc/os-release; printf 'OS_PRETTY=%q\n' "${PRETTY_NAME:-unknown}")"
log_info "Detected: $OS_PRETTY ($(uname -m))"
case "$(uname -s)" in
    Linux)  log_ok "Linux" ;;
    Darwin) log_ok "macOS (needs Docker Desktop)" ;;
    *)      log_warn "Unrecognized OS — Docker is still required" ;;
esac

SUDO=""
[ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"

# ---------------------------------------------------------------------------
# [2/6] Docker + Compose
# ---------------------------------------------------------------------------
log_step "2/6" "Checking Docker..."
if ! command -v docker >/dev/null 2>&1; then
    log_warn "Docker is not installed."
    if [ "$(uname -s)" = "Linux" ] && confirm "Install Docker now via get.docker.com? [Y/n]" Y; then
        curl -fsSL https://get.docker.com | $SUDO sh
        $SUDO systemctl enable --now docker 2>/dev/null || true
        [ "$(id -u)" -ne 0 ] && $SUDO usermod -aG docker "$USER" 2>/dev/null || true
        log_ok "Docker installed"
        log_warn "Log out/in later so 'docker' works without sudo (group membership)."
    else
        log_err "Docker is required: https://docs.docker.com/engine/install/"
        exit 1
    fi
fi

DOCKER="docker"; NEED_SUDO_DOCKER=false
if ! docker info >/dev/null 2>&1; then
    if [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then
        DOCKER="$SUDO docker"; NEED_SUDO_DOCKER=true
        log_info "Using sudo for docker (you're not in the 'docker' group yet)"
    else
        log_err "Docker daemon not reachable. Start it: ${SUDO:+$SUDO }systemctl start docker"
        exit 1
    fi
fi
if ! $DOCKER compose version >/dev/null 2>&1; then
    log_err "The Docker Compose plugin is missing."
    log_err "Install it (Debian/Ubuntu): ${SUDO:+$SUDO }apt-get install -y docker-compose-v2"
    exit 1
fi
log_ok "Docker $($DOCKER --version | sed 's/Docker version //; s/,.*//') · Compose $($DOCKER compose version --short 2>/dev/null || echo ok)"
# Offer to add the user to the docker group so they can manage dash without sudo.
GROUP_ADDED=false
if [ "$NEED_SUDO_DOCKER" = true ] && [ "$(id -u)" -ne 0 ]; then
    if confirm "Add '$USER' to the 'docker' group so you can manage dash without sudo? [Y/n]" Y; then
        if $SUDO usermod -aG docker "$USER" 2>/dev/null; then
            GROUP_ADDED=true
            log_ok "Added $USER to the docker group — log out/in (or run 'newgrp docker') to use docker without sudo"
        else
            log_warn "Couldn't change the docker group; you'll keep using sudo for docker."
        fi
    fi
fi

# How docker should appear in the commands we record/print: include sudo when this
# host needs it AND the user didn't just join the docker group (which removes the
# need after they log back in).
DOCKER_DISPLAY="docker"
if [ "$NEED_SUDO_DOCKER" = true ] && [ "$GROUP_ADDED" != true ]; then
    DOCKER_DISPLAY="sudo docker"
fi

# ---------------------------------------------------------------------------
# [3/6] Existing install
# ---------------------------------------------------------------------------
log_step "3/6" "Checking for an existing dash install..."
if $DOCKER ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "dash"; then
    log_warn "A container named 'dash' already exists."
    log_info "To update: cd <dir> && $DOCKER_DISPLAY compose pull && $DOCKER_DISPLAY compose up -d"
    confirm "Reconfigure / redeploy anyway? [y/N]" N || { echo "  Aborted."; exit 0; }
fi
if [ -e "$DIR/docker-compose.yml" ]; then
    log_warn "$DIR/docker-compose.yml exists and will be overwritten."
    confirm "Continue? [y/N]" N || { echo "  Aborted."; exit 0; }
fi
log_ok "Ready"

# ---------------------------------------------------------------------------
# [4/6] Configuration
# ---------------------------------------------------------------------------
log_step "4/6" "Configuration..."
[ "$DIR_SET" = true ]  || ask_default "Install directory" "$DIR" DIR
DIR="$(abspath "$DIR")"
[ "$PORT_SET" = true ] || ask_default "Web UI port (https)" "$PORT" PORT
[ "$TLS_HOSTS_SET" = true ] || ask_default "This server's hostname/IP for the HTTPS cert (Enter to skip)" "$TLS_HOSTS" TLS_HOSTS
# Update notifications always point at the upstream repo (override with --update-repo on a fork).
[ -n "$UPDATE_REPO" ] && log_info "Update notifications check: $UPDATE_REPO"

# ---------------------------------------------------------------------------
# [5/6] Write compose + data dir
# ---------------------------------------------------------------------------
log_step "5/6" "Writing $DIR/docker-compose.yml..."
mkdir -p "$DIR/data"

if [ "$BUILD" = true ]; then
    if [ ! -f "$DIR/Dockerfile" ]; then
        log_info "Cloning source for --build..."
        git clone --depth 1 "https://github.com/${REPO}.git" "$DIR/.src" \
            || { log_err "git clone failed (private repo needs access)"; exit 1; }
        cp -r "$DIR/.src/." "$DIR/" && rm -rf "$DIR/.src"
    fi
    SOURCE_LINE="build: ."
else
    SOURCE_LINE="image: ${IMAGE}"
fi

{
    echo "services:"
    echo "  dashboard:"
    echo "    ${SOURCE_LINE}"
    echo "    container_name: dash"
    echo "    ports:"
    echo "      - \"${PORT}:8443\""
    echo "    volumes:"
    echo "      - ./data:/data"
    echo "    restart: unless-stopped"
    echo "    environment:"
    echo "      - DASH_DB_PATH=/data/dashboard.db"
    [ -n "$TLS_HOSTS" ]   && echo "      - DASH_TLS_HOSTS=${TLS_HOSTS}"
    [ -n "$UPDATE_REPO" ] && echo "      - DASH_UPDATE_REPO=${UPDATE_REPO}"
    # Record this install's directory (and whether sudo is needed) so the in-app
    # "update available" notice shows the exact command to run on this host.
    [ -n "$UPDATE_REPO" ] && echo "      - DASH_UPDATE_COMMAND=cd ${DIR} && ${DOCKER_DISPLAY} compose pull && ${DOCKER_DISPLAY} compose up -d"
} > "$DIR/docker-compose.yml"
log_ok "Wrote compose file"

# ---------------------------------------------------------------------------
# [6/6] Start + wait
# ---------------------------------------------------------------------------
log_step "6/6" "Starting dash..."
if [ "$BUILD" = true ]; then
    ( cd "$DIR" && $DOCKER compose up -d --build )
else
    # Pull first so re-running the installer also picks up a newer image.
    ( cd "$DIR" && $DOCKER compose pull && $DOCKER compose up -d )
fi

log_info "Waiting for dash to answer on https://localhost:${PORT} ..."
ok=false
for _ in $(seq 1 30); do
    if curl -ks "https://localhost:${PORT}/api/me" >/dev/null 2>&1; then ok=true; break; fi
    sleep 1
done

SERVER_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '/src/{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
[ -z "$SERVER_IP" ] && SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -z "$SERVER_IP" ] && SERVER_IP="localhost"

echo ""
if [ "$ok" = true ]; then
    echo -e "${GREEN}══════════════════════════════════════════════${RESET}"
    echo -e "${GREEN}  dash is up and running!${RESET}"
    echo -e "${GREEN}══════════════════════════════════════════════${RESET}"
else
    echo -e "${YELLOW}  Started, but it didn't answer the health check yet.${RESET}"
    echo -e "  Watch logs:  cd $DIR && $DOCKER compose logs -f"
fi
echo ""
echo -e "  Open: ${CYAN}https://${SERVER_IP}:${PORT}${RESET}   ${DIM}(or https://localhost:${PORT})${RESET}"
echo -e "  ${DIM}Self-signed cert — accept the one-time browser warning.${RESET}"
echo ""
echo -e "  ${YELLOW}First visit:${RESET} create your admin account."
echo ""
echo "  Directory: $DIR"
echo -e "  Data:      $DIR/data   ${DIM}(links, users, TLS cert — back this up)${RESET}"
echo "  Update:    cd $DIR && $DOCKER_DISPLAY compose pull && $DOCKER_DISPLAY compose up -d"
echo "  Logs:      cd $DIR && $DOCKER_DISPLAY compose logs -f"
echo "  Stop:      cd $DIR && $DOCKER_DISPLAY compose down"
echo ""
