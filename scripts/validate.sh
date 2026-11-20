#!/usr/bin/env bash
# No cluster writes. The smoke-cluster test is a separate, disposable-cluster job.
set -euo pipefail
TASK_RENDER_DIR="${RUNNER_TEMP:-/tmp}/media-rendered"
mkdir -p "$TASK_RENDER_DIR"
for overlay in k8s/overlays/*/; do
  name=$(basename "$overlay")
  kustomize build "$overlay" > "$TASK_RENDER_DIR/$name.yaml"
  python3 scripts/validate-manifests.py --allow-template-values "$TASK_RENDER_DIR/$name.yaml"
done
for addon in k8s/addons/*/; do
  name=$(basename "$addon")
  kustomize build "$addon" > "$TASK_RENDER_DIR/addon-$name.yaml"
done
python3 scripts/render-ingress.py --directory "$TASK_RENDER_DIR"
# CRDs are checked separately against checksum-pinned upstream OpenAPI schemas.
# Any other missing schema is an error; there is no ignore-missing-schemas bypass.
kubeconform -strict -kubernetes-version 1.31.0 -summary \
  -skip Application,AppProject,SealedSecret \
  "$TASK_RENDER_DIR"/*.yaml argocd/root.yaml argocd/apps/*.yaml
python3 scripts/validate-custom-resources.py "$TASK_RENDER_DIR"/*.yaml argocd/root.yaml argocd/apps/*.yaml
python3 -m unittest discover -s tests -v
shellcheck -x install.sh scripts/*.sh
(
  cd ansible
  ansible-playbook -i inventory/hosts.yml site.yml --syntax-check
  ansible-playbook -i inventory/hosts.yml add-node.yml --syntax-check
  ansible-playbook -i inventory/hosts.yml reset.yml --syntax-check
  ansible-lint
)
