#!/usr/bin/env python3
"""Build an isolated startup/routing fixture from real application manifests."""
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[1]
resources = [yaml.safe_load((ROOT / 'k8s/base/namespace.yaml').read_text()),
             yaml.safe_load((ROOT / 'k8s/base/configmap.yaml').read_text())]
for name in ('sonarr', 'radarr', 'prowlarr'):
    directory = ROOT / 'k8s/base' / name
    deployment = yaml.safe_load((directory / 'deployment.yaml').read_text())
    pod = deployment['spec']['template']['spec']
    # Test startup/routing with disposable storage, never a real NAS or user PVC.
    pod['volumes'] = [{'name': v['name'], 'emptyDir': {}} for v in pod['volumes']]
    for container in pod['containers']:
        for mount in container.get('volumeMounts', []):
            mount.pop('subPath', None)
    resources += [deployment, yaml.safe_load((directory / 'service.yaml').read_text()),
                  yaml.safe_load((directory / 'ingress.yaml').read_text())]
print(yaml.safe_dump_all(resources, sort_keys=False))
