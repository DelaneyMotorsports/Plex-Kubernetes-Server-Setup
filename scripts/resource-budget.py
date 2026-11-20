#!/usr/bin/env python3
"""Report steady application memory plus the scheduled backup peak."""
import argparse
import json
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[1]


def memory_mi(quantity):
    value = str(quantity)
    if value.endswith('Gi'): return float(value[:-2]) * 1024
    if value.endswith('Mi'): return float(value[:-2])
    if value.endswith('Ki'): return float(value[:-2]) / 1024
    return float(value) / 1024**2


def pod_memory(pod, field):
    containers = pod.get('containers', []) + [c for c in pod.get('initContainers', [])
                                              if c.get('restartPolicy') == 'Always']
    steady = sum(memory_mi(c.get('resources', {}).get(field, {}).get('memory', '0')) for c in containers)
    running_sidecars = 0
    init_peak = 0
    for container in pod.get('initContainers', []):
        amount = memory_mi(container.get('resources', {}).get(field, {}).get('memory', '0'))
        if container.get('restartPolicy') == 'Always':
            running_sidecars += amount
            init_peak = max(init_peak, running_sidecars)
        else:
            init_peak = max(init_peak, running_sidecars + amount)
    return max(steady, init_peak)


def budget(documents):
    steady = []
    backup = 0
    for doc in documents:
        if not doc: continue
        if doc['kind'] == 'Deployment':
            pod = doc['spec']['template']['spec']
            replicas = doc['spec'].get('replicas', 1)
            steady.append({'application': doc['metadata']['name'],
                           'requestMi': pod_memory(pod, 'requests') * replicas,
                           'limitMi': pod_memory(pod, 'limits') * replicas})
        elif doc['kind'] == 'CronJob' and doc['metadata']['name'] == 'config-backup':
            backup = pod_memory(doc['spec']['jobTemplate']['spec']['template']['spec'], 'limits')
    total = sum(row['limitMi'] for row in steady)
    return {'steadyRequestMi': sum(row['requestMi'] for row in steady),
            'steadyLimitMi': total, 'peakWithBackupMi': total + backup,
            'deployments': steady}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests', nargs='+', type=Path)
    args = parser.parse_args()
    result = budget([doc for path in args.manifests for doc in yaml.safe_load_all(path.read_text())])
    policy = json.loads((ROOT / 'ci/pi5-budget.json').read_text())
    if result['steadyLimitMi'] > policy['steadyLimitMi'] or result['peakWithBackupMi'] > policy['peakWithBackupMi']:
        raise RuntimeError('Pi 5 memory budget exceeded; review enabled apps and their limits')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
