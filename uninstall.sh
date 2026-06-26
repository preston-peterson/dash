#!/usr/bin/env bash
# =============================================================================
# dash — uninstaller
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/preston-peterson/dash/main/uninstall.sh)
#
# Stops and removes the dash container. By default your data is kept; pass
# --purge to also delete the data (links, users, TLS cert) and the install dir.
#
# Flags:
#   --dir <path>   Install directory (auto-detected from the running container if omitted)
#   --purge        Also delete ./data and the install directory
#   --rmi          Also remove the dash container image
#   -y, --yes      Non-interactive; accept all defaults
#   -h, --help     Show this help and exit
# =============================================================================
set -euo pipefail

GREEN='\033[32m\033[1m'; RED='\033[31m\033[1m'; CYAN='\033[36m\033[1m'
YELLOW='\033[33m\033[1m'; DIM='\033[2m'; RESET='\033[0m'

DIR=""
PURGE=false
RMI=false
ASSUME_YES=false

show_help() {
    cat <<'EOF'
dash — uninstaller

  bash <(curl -fsSL https://raw.githubusercontent.com/preston-peterson/dash/main/uninstall.sh)

Flags:
  --dir <path>   Install directory (auto-detected from the running container if omitted)
  --purge        Also delete ./data (links, users, TLS cert) and the install directory
  --rmi          Also remove the dash container image
  -y, --yes      Non-interactive; accept all defaults
  -h, --help     Show this help and exit
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dir)     DIR="$2"; shift 2 ;;
        --purge)   PURGE=true; shift ;;
        --rmi)     RMI=true; shift ;;
        -y|--yes)  ASSUME_YES=true; shift ;;
        -h|--help) show_help; exit 0 ;;
        *) echo -e "${RED}Unknown option: $1${RESET}" >&2; echo "Run with --help for usage" >&2; exit 1 ;;
    esac
done

log_step() { echo -e "${CYAN}[$1]${RESET} $2"; }
log_ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
log_err()  { echo -e "  ${RED}✗${RESET} $1" >&2; }
log_info() { echo -e "  ${DIM}·${RESET} $1"; }

confirm() {
    local prompt="$1" def="${2:-Y}" reply=""
    if [ "$ASSUME_YES" = true ]; then return 0; fi   # -y / --yes => yes to all
    if [ ! -t 0 ]; then [ "$def" = "Y" ]; return; fi # piped, no -y => take the default
    read -r -p "  $prompt " reply
    reply="${reply:-$def}"
    [[ "$reply" =~ ^[Yy]$ ]]
}

SUDO=""
[ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
    if [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then DOCKER="$SUDO docker"; fi
fi

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${CYAN}║              dash — uninstaller              ║${RESET}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${RESET}"
echo ""

# ---------------------------------------------------------------------------
# [1/2] Locate the install
# ---------------------------------------------------------------------------
log_step "1/2" "Locating dash..."

if [ -z "$DIR" ]; then
    DIR="$($DOCKER inspect dash --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' 2>/dev/null || true)"
fi
[ -z "$DIR" ] && DIR="$HOME/dash"
DIR="${DIR/#\~/$HOME}"

if $DOCKER ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "dash"; then
    log_ok "Found container 'dash'"
else
    log_warn "No container named 'dash' is present."
fi
if [ -f "$DIR/docker-compose.yml" ]; then
    log_info "Install directory: $DIR"
else
    log_warn "No docker-compose.yml at $DIR (use --dir if it's elsewhere)."
fi

if ! confirm "Remove dash now?${PURGE:+ (and PURGE all data)} [y/N]" N; then
    echo "  Aborted."
    exit 0
fi

# ---------------------------------------------------------------------------
# [2/2] Remove
# ---------------------------------------------------------------------------
log_step "2/2" "Removing..."

if [ -f "$DIR/docker-compose.yml" ]; then
    ( cd "$DIR" && $DOCKER compose down ) && log_ok "Stopped and removed the container"
else
    $DOCKER rm -f dash >/dev/null 2>&1 && log_ok "Removed the 'dash' container" || log_info "No container to remove"
fi

if [ "$RMI" = true ]; then
    imgs="$($DOCKER images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -E 'preston-peterson/dash|(^|/)dash:' || true)"
    if [ -n "$imgs" ]; then
        # shellcheck disable=SC2086
        $DOCKER rmi $imgs >/dev/null 2>&1 || true
        log_ok "Removed dash image(s)"
    fi
fi

if [ "$PURGE" = true ]; then
    log_warn "Purging data (links, users, TLS cert) under $DIR"
    if confirm "This permanently deletes all dash data. Continue? [y/N]" N; then
        rm -rf "$DIR/data"
        rm -f "$DIR/docker-compose.yml"
        rmdir "$DIR" 2>/dev/null && log_ok "Deleted $DIR" || log_info "Left $DIR (not empty)"
    else
        log_info "Kept data."
    fi
else
    log_info "Kept your data at $DIR/data (run with --purge to delete it)."
fi

echo ""
echo -e "${GREEN}  dash removed.${RESET}"
[ "$PURGE" = false ] && echo -e "  ${DIM}Reinstall any time and your data in $DIR/data is picked back up.${RESET}"
echo ""
