#!/usr/bin/env bash
# Quick health check of the media stack.
set -euo pipefail

NAMESPACE="media"

echo "==> Pod status"
kubectl get pods -n "$NAMESPACE" -o wide

echo ""
echo "==> PVC status"
kubectl get pvc -n "$NAMESPACE"

echo ""
echo "==> Services"
kubectl get svc -n "$NAMESPACE"

echo ""
echo "==> Ingresses"
kubectl get ingress -n "$NAMESPACE"

echo ""
echo "==> Recent events (warnings only)"
kubectl get events -n "$NAMESPACE" --field-selector type=Warning --sort-by='.lastTimestamp' | tail -20
