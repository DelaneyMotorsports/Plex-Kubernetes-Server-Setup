#!/usr/bin/env bash
# Full bootstrap of the media stack on a fresh cluster.
# Run this once on initial setup. For subsequent changes, use:
#   kubectl apply -k k8s/overlays/pi5/
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

for file in k8s/base/storage/media-pv.yaml k8s/overlays/${OVERLAY}/node-selector-patch.yaml; do
  if grep -q "CHANGE-ME-NODE-NAME" "$file"; then
    echo "Error: $file still has CHANGE-ME-NODE-NAME placeholder."
    echo "       Run: kubectl get nodes -o name | cut -d/ -f2"
    exit 1
  fi
done

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
deployments=(gluetun-qbittorrent prowlarr sonarr radarr bazarr overseerr plex flaresolverr)
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
