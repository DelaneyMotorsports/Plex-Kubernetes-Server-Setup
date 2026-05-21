#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════╗
# ║   Plex Kubernetes Media Stack — One-Line Installer           ║
# ║   Delaney Motorsports R&D                                    ║
# ║                                                              ║
# ║   curl -sSL https://raw.githubusercontent.com/              ║
# ║     DelaneyMotorsports/Plex-Kubernetes-Server-Setup/         ║
# ║     main/install.sh | bash                                   ║
# ╚══════════════════════════════════════════════════════════════╝
set -euo pipefail

# ── Constants ─────────────────────────────────────────────────────
REPO="https://github.com/DelaneyMotorsports/Plex-Kubernetes-Server-Setup.git"
BRANCH="${MEDIA_STACK_BRANCH:-main}"
INSTALL_DIR="${MEDIA_STACK_DIR:-$HOME/media-stack}"
K3S_URL="https://get.k3s.io"
NGINX_VER="controller-v1.10.1"
NGINX_URL="https://raw.githubusercontent.com/kubernetes/ingress-nginx/${NGINX_VER}/deploy/static/provider/baremetal/deploy.yaml"
KUBECONFIG_PATH="/etc/rancher/k3s/k3s.yaml"

# ── Colors ────────────────────────────────────────────────────────
R='\033[0;31m' G='\033[0;32m' Y='\033[1;33m' B='\033[0;34m'
BOLD='\033[1m' DIM='\033[2m' NC='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────
log()    { echo -e "  ${G}▶${NC}  $*"; }
ok()     { echo -e "  ${G}✓${NC}  $*"; }
warn()   { echo -e "  ${Y}⚠${NC}   $*"; }
die()    { echo -e "\n  ${R}✗  ERROR:${NC} $*\n" >&2; exit 1; }
header() { echo -e "\n${BOLD}$*${NC}"; }
hr()     { echo -e "${DIM}────────────────────────────────────────────────────────${NC}"; }

# Prompt with optional default. Pre-set via env var to skip prompt (CI/automation).
ask() {
    local label="$1" default="${2:-}" var="$3"
    local current="${!var:-}"
    if [[ -n "$current" ]]; then
        ok "$label: ${DIM}${current}${NC} ${DIM}(from env)${NC}"
        return
    fi
    local prompt="${BOLD}  ${label}${NC}"
    if [[ -n "$default" ]]; then
        printf "%b [%s]: " "$prompt" "$default"
        IFS= read -r value
        eval "$var='${value:-$default}'"
    else
        printf "%b: " "$prompt"
        IFS= read -r value
        while [[ -z "$value" ]]; do
            warn "This field is required."
            printf "%b: " "$prompt"
            IFS= read -r value
        done
        eval "$var='$value'"
    fi
}

# Silent prompt (secrets — no echo)
ask_secret() {
    local label="$1" var="$2"
    local current="${!var:-}"
    if [[ -n "$current" && "$current" != "CHANGE-ME" ]]; then
        ok "$label: ${DIM}******* (from env)${NC}"
        return
    fi
    local prompt="${BOLD}  ${label}${NC}"
    printf "%b: " "$prompt"
    IFS= read -rs value; echo
    while [[ -z "$value" || "$value" == "CHANGE-ME" ]]; do
        warn "This field is required."
        printf "%b: " "$prompt"
        IFS= read -rs value; echo
    done
    eval "$var='$value'"
}

need_cmd() {
    command -v "$1" &>/dev/null || die "Required command not found: $1"
}

# ── OS Detection ──────────────────────────────────────────────────
OS_ID=""
IS_PI=false
detect_os() {
    [[ -f /etc/os-release ]] && source /etc/os-release && OS_ID="${ID:-unknown}" || OS_ID="unknown"
    if [[ -f /proc/device-tree/model ]] && grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
        IS_PI=true
    fi
    log "OS: ${OS_ID}  |  Raspberry Pi: ${IS_PI}  |  Arch: $(uname -m)"
}

# ── Prerequisites ─────────────────────────────────────────────────
install_prerequisites() {
    log "Checking prerequisites..."
    local pkgs=()
    command -v git  &>/dev/null || pkgs+=(git)
    command -v curl &>/dev/null || pkgs+=(curl)
    command -v wget &>/dev/null || pkgs+=(wget)

    if [[ ${#pkgs[@]} -gt 0 ]]; then
        log "Installing: ${pkgs[*]}"
        case "$OS_ID" in
            debian|ubuntu|raspbian)
                sudo apt-get update -qq
                sudo apt-get install -y -qq "${pkgs[@]}"
                ;;
            fedora)
                sudo dnf install -y -q "${pkgs[@]}"
                ;;
            *)
                warn "Unknown OS — assuming ${pkgs[*]} are available."
                ;;
        esac
    fi
    ok "Prerequisites ready"
}

# ── K3s ──────────────────────────────────────────────────────────
K8S_ALREADY_RUNNING=false
install_k3s() {
    # Check if any K8s cluster is already reachable
    if kubectl cluster-info &>/dev/null 2>&1; then
        K8S_ALREADY_RUNNING=true
        ok "Kubernetes cluster already reachable — skipping K3s install"
        return
    fi

    # Check if K3s binary exists but service isn't running
    if command -v k3s &>/dev/null; then
        warn "K3s is installed but cluster is not reachable. Trying to start..."
        sudo systemctl start k3s 2>/dev/null || true
        sleep 5
        if kubectl cluster-info &>/dev/null 2>&1; then
            K8S_ALREADY_RUNNING=true
            ok "K3s started"
            return
        fi
    fi

    log "Installing K3s (this takes about 60 seconds)..."
    curl -sfL "$K3S_URL" | sudo INSTALL_K3S_EXEC="server \
        --disable traefik \
        --write-kubeconfig-mode 644" sh -

    export KUBECONFIG="$KUBECONFIG_PATH"

    log "Waiting for cluster to be ready..."
    local attempts=0
    until kubectl get nodes 2>/dev/null | grep -q " Ready"; do
        sleep 3
        (( attempts++ ))
        [[ $attempts -gt 40 ]] && die "K3s did not become ready after 2 minutes. Check: sudo journalctl -u k3s"
    done

    # Set up kubeconfig for current user
    if [[ "$HOME" != "/root" ]]; then
        mkdir -p "$HOME/.kube"
        sudo cp "$KUBECONFIG_PATH" "$HOME/.kube/config"
        sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
        export KUBECONFIG="$HOME/.kube/config"
    fi

    ok "K3s ready"
}

# ── ingress-nginx ─────────────────────────────────────────────────
install_ingress() {
    if kubectl get deployment ingress-nginx-controller -n ingress-nginx &>/dev/null 2>&1; then
        ok "ingress-nginx already installed"
        return
    fi
    log "Installing ingress-nginx..."
    kubectl apply -f "$NGINX_URL"
    kubectl rollout status deployment/ingress-nginx-controller \
        -n ingress-nginx --timeout=5m
    ok "ingress-nginx ready"
}

# ── Storage ───────────────────────────────────────────────────────
MEDIA_PATH="${MEDIA_PATH:-/mnt/media}"
DOWNLOADS_PATH="${DOWNLOADS_PATH:-/mnt/downloads}"

setup_storage() {
    header "Storage Setup"
    hr
    echo -e "  The stack needs two directories on a fast drive (USB SSD recommended):"
    echo -e "    ${BOLD}/mnt/media${NC}      — your library (TV, movies, music)"
    echo -e "    ${BOLD}/mnt/downloads${NC}  — active downloads (qBittorrent scratch space)"
    echo ""

    ask "Media directory path"     "/mnt/media"      MEDIA_PATH
    ask "Downloads directory path" "/mnt/downloads"  DOWNLOADS_PATH

    echo ""
    local mount_drive="n"
    if [[ -z "${SKIP_DRIVE_PROMPT:-}" ]]; then
        printf "  ${BOLD}Mount an external drive now?${NC} (y/N): "
        IFS= read -r mount_drive
    fi

    if [[ "$mount_drive" =~ ^[Yy]$ ]]; then
        echo ""
        echo "  Available block devices:"
        lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT 2>/dev/null | grep -v "^loop" | sed 's/^/    /' || true
        echo ""
        local MEDIA_DEVICE
        ask "Device to mount (e.g. /dev/sda1)" "" MEDIA_DEVICE
        sudo mkdir -p "$MEDIA_PATH"
        if sudo mount "$MEDIA_DEVICE" "$MEDIA_PATH" 2>/dev/null; then
            ok "Drive mounted at $MEDIA_PATH"
            # Persist in fstab
            local uuid
            uuid=$(blkid -s UUID -o value "$MEDIA_DEVICE" 2>/dev/null || true)
            if [[ -n "$uuid" ]] && ! grep -q "$uuid" /etc/fstab; then
                echo "UUID=$uuid $MEDIA_PATH auto defaults,nofail 0 2" | sudo tee -a /etc/fstab >/dev/null
                ok "Added to /etc/fstab (survives reboots)"
            fi
        else
            warn "Mount failed — continuing with directory only. Fix manually after install."
        fi
    fi

    sudo mkdir -p \
        "${MEDIA_PATH}/tv" \
        "${MEDIA_PATH}/movies" \
        "${MEDIA_PATH}/music" \
        "${DOWNLOADS_PATH}/complete" \
        "${DOWNLOADS_PATH}/incomplete"

    local uid="${PUID:-$(id -u)}" gid="${PGID:-$(id -g)}"
    sudo chown -R "${uid}:${gid}" "$MEDIA_PATH" "$DOWNLOADS_PATH" 2>/dev/null \
        || warn "Could not chown $MEDIA_PATH — you may need to fix permissions manually."

    ok "Storage directories ready"
}

# ── Interactive Config ────────────────────────────────────────────
TZ="${TZ:-}"
PUID="${PUID:-}"
PGID="${PGID:-}"
WIREGUARD_PRIVATE_KEY="${WIREGUARD_PRIVATE_KEY:-}"
WIREGUARD_ADDRESSES="${WIREGUARD_ADDRESSES:-}"
SERVER_REGIONS="${SERVER_REGIONS:-}"
PLEX_CLAIM="${PLEX_CLAIM:-}"

collect_config() {
    header "Configuration"
    hr
    echo -e "  ${DIM}Secrets are not echoed to the terminal.${NC}"
    echo -e "  ${DIM}Skip prompts by pre-setting env vars — see .env.example.${NC}"
    echo ""

    # Auto-detect sensible defaults
    local default_tz default_puid default_pgid
    default_tz=$(timedatectl show --property=Timezone --value 2>/dev/null \
        || cat /etc/timezone 2>/dev/null \
        || echo "UTC")
    default_puid=$(id -u)
    default_pgid=$(id -g)

    ask "Timezone"          "$default_tz"    TZ
    ask "User ID  (PUID)"   "$default_puid"  PUID
    ask "Group ID (PGID)"   "$default_pgid"  PGID

    echo ""
    echo -e "  ${B}NordVPN WireGuard keys:${NC}"
    echo -e "  ${DIM}NordVPN App → Settings → Set up NordVPN manually → WireGuard → Generate key${NC}"
    ask_secret "WireGuard Private Key"             WIREGUARD_PRIVATE_KEY
    ask        "WireGuard Address (e.g. 10.5.0.2/32)" "" WIREGUARD_ADDRESSES
    ask        "VPN Server Region"  "Europe"       SERVER_REGIONS

    echo ""
    echo -e "  ${B}Plex claim token:${NC}"
    echo -e "  ${DIM}Visit https://plex.tv/claim — token is valid for 4 minutes.${NC}"
    echo -e "  ${Y}  Get this token AFTER you start this step — deploy happens soon.${NC}"
    echo ""
    ask_secret "Plex Claim Token"  PLEX_CLAIM

    ok "Configuration collected"
}

# ── Clone / Update Repo ───────────────────────────────────────────
clone_repo() {
    if [[ -f "$INSTALL_DIR/k8s/base/kustomization.yaml" ]]; then
        log "Updating existing install at $INSTALL_DIR..."
        git -C "$INSTALL_DIR" fetch origin "$BRANCH" --quiet
        git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH" --quiet
    else
        log "Cloning repository to $INSTALL_DIR..."
        git clone --depth=1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR" --quiet
    fi
    ok "Repository ready at $INSTALL_DIR"
}

# ── Substitute Config Values ──────────────────────────────────────
NODE_NAME=""
configure_stack() {
    NODE_NAME=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}' 2>/dev/null \
        || hostname)
    log "Configuring for node: ${NODE_NAME}"

    # Node name placeholders
    sed -i "s/CHANGE-ME-NODE-NAME/${NODE_NAME}/g" \
        "$INSTALL_DIR/k8s/base/storage/media-pv.yaml" \
        "$INSTALL_DIR/k8s/overlays/pi5/node-selector-patch.yaml"

    # Storage paths
    sed -i "s|path: /mnt/media$|path: ${MEDIA_PATH}|g" \
        "$INSTALL_DIR/k8s/base/storage/media-pv.yaml"
    sed -i "s|path: /mnt/downloads$|path: ${DOWNLOADS_PATH}|g" \
        "$INSTALL_DIR/k8s/base/storage/media-pv.yaml"

    # ConfigMap values
    local cfgmap="$INSTALL_DIR/k8s/base/configmap.yaml"
    sed -i "s|TZ: \"America/New_York\"|TZ: \"${TZ}\"|g"               "$cfgmap"
    sed -i "s|PUID: \"1000\"|PUID: \"${PUID}\"|g"                     "$cfgmap"
    sed -i "s|PGID: \"1000\"|PGID: \"${PGID}\"|g"                     "$cfgmap"
    sed -i "s|SERVER_REGIONS: \"Europe\"|SERVER_REGIONS: \"${SERVER_REGIONS}\"|g" "$cfgmap"

    ok "Configuration applied"
}

# ── Deploy ────────────────────────────────────────────────────────
deploy() {
    log "Creating namespace..."
    kubectl create namespace media --dry-run=client -o yaml | kubectl apply -f - >/dev/null

    log "Creating secrets..."
    kubectl create secret generic media-stack-secret \
        --namespace media \
        --from-literal=WIREGUARD_PRIVATE_KEY="$WIREGUARD_PRIVATE_KEY" \
        --from-literal=WIREGUARD_ADDRESSES="$WIREGUARD_ADDRESSES" \
        --from-literal=PLEX_CLAIM="$PLEX_CLAIM" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    ok "Secrets created"

    log "Deploying media stack..."
    kubectl apply -k "$INSTALL_DIR/k8s/overlays/pi5/" >/dev/null
    ok "Manifests applied"

    echo ""
    log "Waiting for services (2-5 minutes on first pull)..."
    local services=(plex sonarr radarr prowlarr bazarr overseerr gluetun-qbittorrent)
    for svc in "${services[@]}"; do
        printf "    %-30s" "$svc"
        if kubectl rollout status deployment/"$svc" -n media --timeout=5m &>/dev/null; then
            echo -e "${G}ready${NC}"
        else
            echo -e "${Y}slow start — check: kubectl logs -n media deploy/$svc${NC}"
        fi
    done
}

# ── Success Banner ────────────────────────────────────────────────
print_success() {
    local node_ip
    node_ip=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null \
        || hostname -I | awk '{print $1}')

    echo ""
    echo -e "${BOLD}${G}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${G}║   Installation Complete!                                 ║${NC}"
    echo -e "${BOLD}${G}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Add to ${BOLD}/etc/hosts${NC} on any device that needs access:"
    echo ""
    echo -e "    ${DIM}$node_ip  plex.local sonarr.local radarr.local${NC}"
    echo -e "    ${DIM}$node_ip  prowlarr.local bazarr.local overseerr.local qbittorrent.local${NC}"
    echo ""
    echo -e "  ${BOLD}Services:${NC}"
    echo -e "    Plex          http://plex.local:32400/web"
    echo -e "    Sonarr        http://sonarr.local"
    echo -e "    Radarr        http://radarr.local"
    echo -e "    Prowlarr      http://prowlarr.local"
    echo -e "    Bazarr        http://bazarr.local"
    echo -e "    Overseerr     http://overseerr.local"
    echo -e "    qBittorrent   http://qbittorrent.local"
    echo ""
    echo -e "  ${BOLD}Next steps:${NC}"
    echo -e "    1. Configure Prowlarr — add indexers"
    echo -e "    2. Point Sonarr + Radarr at Prowlarr (sync indexers automatically)"
    echo -e "    3. Add qBittorrent to Sonarr + Radarr (host: qbittorrent, port: 8080)"
    echo -e "    4. Connect Bazarr to Sonarr + Radarr"
    echo -e "    5. Set up Overseerr — connect to Plex, Sonarr, Radarr"
    echo ""
    echo -e "  ${DIM}Check status: kubectl get pods -n media${NC}"
    echo -e "  ${DIM}View logs:    kubectl logs -n media deploy/<service>${NC}"
    echo ""
}

# ── Entrypoint ────────────────────────────────────────────────────
banner() {
    echo ""
    echo -e "${BOLD}"
    echo "  ╔══════════════════════════════════════════════════════════╗"
    echo "  ║   Plex Kubernetes Media Stack                            ║"
    echo "  ║   Delaney Motorsports R&D                                ║"
    echo "  ╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo -e "  Installs a full self-hosted media stack on Kubernetes."
    echo -e "  ${DIM}Plex · Sonarr · Radarr · Prowlarr · Bazarr · Overseerr · qBittorrent + WireGuard VPN${NC}"
    echo ""
}

main() {
    banner
    detect_os
    install_prerequisites
    collect_config         # ask for secrets before any long-running steps
    clone_repo
    install_k3s
    install_ingress
    setup_storage
    configure_stack
    deploy
    print_success
}

main "$@"
