#!/usr/bin/env bash
# This creates and deletes its own kind cluster. No existing context is used.
set -euo pipefail
TASK_CLUSTER_NAME="media-ci-${GITHUB_RUN_ID:-$$}"
TASK_SMOKE_DIR=$(mktemp -d)
TASK_FORWARD_PID=''
cleanup() {
  if [[ -n "$TASK_FORWARD_PID" ]]; then kill "$TASK_FORWARD_PID" 2>/dev/null || true; fi
  kind delete cluster --name "$TASK_CLUSTER_NAME" >/dev/null 2>&1 || true
  rm -rf "$TASK_SMOKE_DIR"
}
if kind get clusters | grep -Fxq "$TASK_CLUSTER_NAME"; then
  echo 'Refusing to replace an existing cluster.' >&2
  exit 1
fi
trap cleanup EXIT
TASK_NODE_IMAGE=$(python3 -c 'import yaml; print(yaml.safe_load(open("ci/cluster.yaml"))["nodeImage"])')
kind create cluster --name "$TASK_CLUSTER_NAME" --image "$TASK_NODE_IMAGE" \
  --kubeconfig "$TASK_SMOKE_DIR/kubeconfig" --wait 180s
kctl() { kubectl --kubeconfig "$TASK_SMOKE_DIR/kubeconfig" "$@"; }
kctl create namespace ingress-traefik
python3 scripts/render-ingress.py --directory "$TASK_SMOKE_DIR"
kctl apply -f "$TASK_SMOKE_DIR/traefik.yaml"
kctl -n ingress-traefik rollout status deployment/media-ingress --timeout=300s
python3 scripts/render-smoke.py > "$TASK_SMOKE_DIR/apps.yaml"
kctl apply -f "$TASK_SMOKE_DIR/apps.yaml"
for app in sonarr radarr prowlarr; do
  kctl -n media rollout status "deployment/$app" --timeout=300s
done
kctl -n ingress-traefik port-forward service/media-ingress 18080:80 > "$TASK_SMOKE_DIR/forward.log" 2>&1 &
TASK_FORWARD_PID=$!
for app in sonarr radarr prowlarr; do
  TASK_ROUTED=false
  for ((attempt=0; attempt<30; attempt++)); do
    if curl -fsS --max-time 5 -H "Host: $app.local" http://127.0.0.1:18080/ping; then
      TASK_ROUTED=true
      break
    fi
    sleep 2
  done
  if [[ "$TASK_ROUTED" != true ]]; then
    kctl -n media get pods
    echo "Traefik did not route to $app" >&2
    exit 1
  fi
done
printf '\nReal application startup and Traefik routing passed.\n'
