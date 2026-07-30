#!/usr/bin/env bash
# Direct (non-GitOps) apply of the media stack to a cluster you already have.
#
# The RECOMMENDED path is Ansible + Argo CD (see install.sh / ansible/), which deploys
# this same stack and then keeps it self-healing. Use this script only when you want a
# one-shot kubectl apply without Argo — e.g. for local testing.
#
# For subsequent changes in this mode:  kubectl apply -k k8s/overlays/pi5/
set -euo pipefail

OVERLAY="${1:-pi5}"
NAMESPACE="media"

# ── 1. Preflight checks
echo "==> Checking prerequisites..."

for cmd in kubectl; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "Error: $cmd not found. Install it and try again."
    exit 1
  fi
done

if ! kubectl cluster-info &>/dev/null; then
  echo "Error: Cannot reach the Kubernetes cluster. Check your kubeconfig."
  exit 1
fi

echo "    Cluster reachable."

# ── 2. Verify .env and node name placeholders
if [[ ! -f .env ]]; then
  echo "Error: .env not found. Copy .env.example, fill in your values, then re-run."
  exit 1
fi

# Storage is now NFS from the NAS (no node affinity) — only the compute node-selector
# patch still needs the node name filled in.
NODE_PATCH="k8s/overlays/${OVERLAY}/node-selector-patch.yaml"
if grep -q "CHANGE-ME-NODE-NAME" "$NODE_PATCH"; then
  echo "Error: $NODE_PATCH still has CHANGE-ME-NODE-NAME placeholder."
  echo "       Run: kubectl get nodes -o name | cut -d/ -f2"
  exit 1
fi

# Remind about NAS wiring (non-fatal — the default may already be correct).
if grep -q "192.168.1.50" "k8s/overlays/${OVERLAY}/nas-patch.yaml" 2>/dev/null; then
  echo "Note: k8s/overlays/${OVERLAY}/nas-patch.yaml still uses the sample NAS IP 192.168.1.50."
  echo "      Edit it to your NAS LAN IP + export path if that isn't right."
fi

# ── 3. Create namespace
echo "==> Creating namespace: $NAMESPACE"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# ── 4. Apply secrets
echo "==> Creating secrets from .env..."
./scripts/create-secrets.sh .env

# ── 5. Apply kustomize overlay
echo "==> Applying k8s/overlays/${OVERLAY}/ ..."
kubectl apply -k "k8s/overlays/${OVERLAY}/"

# ── 6. Wait for deployments
echo "==> Waiting for all deployments to be ready (this may take a few minutes)..."
deployments=(gluetun-qbittorrent prowlarr sonarr radarr bazarr overseerr plex)
for deploy in "${deployments[@]}"; do
  echo "    Waiting for $deploy..."
  kubectl rollout status deployment/"$deploy" -n "$NAMESPACE" --timeout=5m || {
    echo "    Warning: $deploy did not become ready within 5m. Check: kubectl logs -n $NAMESPACE deploy/$deploy"
  }
done

echo ""
echo "==> Bootstrap complete!"
echo ""
echo "Add these entries to /etc/hosts (or your local DNS):"
node_ip=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
echo "  $node_ip  plex.local sonarr.local radarr.local prowlarr.local"
echo "  $node_ip  bazarr.local overseerr.local qbittorrent.local"
