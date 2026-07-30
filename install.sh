#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════╗
# ║   Plex Kubernetes Media Stack — One-Line Installer           ║
# ║   Delaney Motorsports R&D                                    ║
# ║                                                              ║
# ║   curl -sSL https://raw.githubusercontent.com/              ║
# ║     DelaneyMotorsports/Plex-Kubernetes-Server-Setup/         ║
# ║     main/install.sh | bash                                   ║
# ╚══════════════════════════════════════════════════════════════╝
#
# This is a THIN bootstrap. It installs Ansible + git, clones the repo, and hands the
# whole job to Ansible (ansible/site.yml), which provisions K3s, Sealed Secrets, and
# Argo CD. From then on Argo CD reconciles the media stack from Git — no more kubectl.
#
# Machines, storage, and workloads are all defined as code:
#   • ansible/                 — the machines (K3s, NFS client, controllers)
#   • argocd/                  — the GitOps apps (self-healing)
#   • k8s/                     — the Kubernetes manifests Argo deploys
#
# To manage a fleet remotely instead of on-box, skip this script and run Ansible from
# your workstation:  cd ansible && ansible-playbook site.yml   (see ansible/README.md)
set -euo pipefail

REPO="https://github.com/DelaneyMotorsports/Plex-Kubernetes-Server-Setup.git"
BRANCH="${MEDIA_STACK_BRANCH:-main}"
INSTALL_DIR="${MEDIA_STACK_DIR:-$HOME/media-stack}"

# Optional overrides passed through to Ansible (see ansible/inventory/group_vars/all.yml):
#   NAS_IP, NAS_EXPORT_PATH, GITOPS_REPO_URL, ENABLE_TAILSCALE, TAILSCALE_AUTHKEY
EXTRA_VARS=()
[[ -n "${NAS_IP:-}" ]]            && EXTRA_VARS+=("nas_ip=${NAS_IP}")
[[ -n "${NAS_EXPORT_PATH:-}" ]]  && EXTRA_VARS+=("nas_export_path=${NAS_EXPORT_PATH}")
[[ -n "${GITOPS_REPO_URL:-}" ]]  && EXTRA_VARS+=("gitops_repo_url=${GITOPS_REPO_URL}")
[[ -n "${ENABLE_TAILSCALE:-}" ]] && EXTRA_VARS+=("enable_tailscale=${ENABLE_TAILSCALE}")
[[ -n "${TAILSCALE_AUTHKEY:-}" ]] && EXTRA_VARS+=("tailscale_authkey=${TAILSCALE_AUTHKEY}")

R='\033[0;31m' G='\033[0;32m' Y='\033[1;33m' BOLD='\033[1m' DIM='\033[2m' NC='\033[0m'
log()    { echo -e "  ${G}▶${NC}  $*"; }
ok()     { echo -e "  ${G}✓${NC}  $*"; }
warn()   { echo -e "  ${Y}⚠${NC}   $*"; }
die()    { echo -e "\n  ${R}✗  ERROR:${NC} $*\n" >&2; exit 1; }

banner() {
  echo -e "${BOLD}"
  echo "  ╔══════════════════════════════════════════════════════════╗"
  echo "  ║   Plex Kubernetes Media Stack — Ansible + Argo CD        ║"
  echo "  ║   Delaney Motorsports R&D                                ║"
  echo "  ╚══════════════════════════════════════════════════════════╝"
  echo -e "${NC}"
}

detect_os() {
  OS_ID="unknown"
  [[ -f /etc/os-release ]] && . /etc/os-release && OS_ID="${ID:-unknown}"
  log "OS: ${OS_ID}  |  Arch: $(uname -m)"
}

install_prereqs() {
  log "Installing prerequisites (git, curl, ansible)..."
  case "$OS_ID" in
    debian|ubuntu|raspbian)
      sudo apt-get update -qq
      sudo apt-get install -y -qq git curl ansible
      ;;
    fedora)
      sudo dnf install -y -q git curl ansible
      ;;
    *)
      command -v git &>/dev/null     || die "git not found and OS '$OS_ID' is unsupported for auto-install."
      command -v ansible &>/dev/null || die "ansible not found and OS '$OS_ID' is unsupported for auto-install."
      ;;
  esac
  command -v ansible-playbook &>/dev/null || die "ansible-playbook still not on PATH after install."
  ok "Prerequisites ready"
}

clone_repo() {
  if [[ -f "$INSTALL_DIR/ansible/site.yml" ]]; then
    log "Updating existing checkout at $INSTALL_DIR..."
    git -C "$INSTALL_DIR" fetch origin "$BRANCH" --quiet
    git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH" --quiet
  else
    log "Cloning repository to $INSTALL_DIR..."
    git clone --depth=1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR" --quiet
  fi
  ok "Repository ready at $INSTALL_DIR"
}

run_ansible() {
  log "Provisioning this box with Ansible (K3s + Sealed Secrets + Argo CD)..."
  local args=(-i inventory/localhost.yml site.yml)
  if [[ ${#EXTRA_VARS[@]} -gt 0 ]]; then
    args+=(-e "${EXTRA_VARS[*]}")
  fi
  ( cd "$INSTALL_DIR/ansible" && ansible-playbook "${args[@]}" )
  ok "Provisioning complete"
}

next_steps() {
  echo ""
  echo -e "${BOLD}${G}Cluster is up. Argo CD now reconciles the stack from Git.${NC}"
  echo ""
  echo -e "  ${BOLD}Two things to finish (both are commit-and-Argo-syncs):${NC}"
  echo -e "    1. Point storage at your NAS: edit ${BOLD}k8s/overlays/pi5/nas-patch.yaml${NC}"
  echo -e "       (server = NAS LAN IP, path = export) in your repo and push."
  echo -e "    2. Seal your secrets:  cp .env.example .env && edit, then"
  echo -e "       ${BOLD}./scripts/seal-secrets.sh .env${NC}  → commit k8s/base/sealed-secret.yaml"
  echo ""
  echo -e "  ${DIM}Argo CD UI password:${NC}"
  echo -e "    kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo"
  echo -e "  ${DIM}Reach the UI:${NC} kubectl -n argocd port-forward svc/argocd-server 8080:443"
  echo ""
}

main() {
  banner
  detect_os
  install_prereqs
  clone_repo
  run_ansible
  next_steps
}
main "$@"
