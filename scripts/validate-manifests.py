#!/usr/bin/env python3
"""Validate resource references and deploy-time configuration in rendered YAML."""
import argparse
from pathlib import Path
import sys
import yaml

EXTERNAL_SECRETS = {'config-backup-secret', 'unpackerr-secret'}


def validate(resources, allow_template_values=False):
    objects = {}
    for item in resources:
        if not item: continue
        metadata = item.get('metadata', {})
        key = (item['kind'], metadata.get('namespace', ''), metadata['name'])
        if key in objects:
            raise ValueError('Duplicate resource: ' + str(key))
        objects[key] = item
    def need(kind, namespace, name):
        if (kind, namespace, name) not in objects:
            raise ValueError(f'Missing {kind} {namespace}/{name}')
    def placeholders(value, path=()):
        if isinstance(value, dict):
            for key, child in value.items(): placeholders(child, path + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value): placeholders(child, path + (index,))
        elif isinstance(value, str) and 'CHANGE-ME' in value:
            if not (allow_template_values and value == 'CHANGE-ME-NODE-NAME'
                    and path[-2:] == ('nodeSelector', 'kubernetes.io/hostname')):
                raise ValueError('Unresolved placeholder at ' + '.'.join(map(str, path)))
    secrets = {(ns, name) for kind, ns, name in objects if kind in ('Secret', 'SealedSecret')}
    for (kind, namespace, name), item in objects.items():
        placeholders(item)
        if kind == 'SealedSecret' and not allow_template_values and not item['spec'].get('encryptedData'):
            raise ValueError('Seal the application credentials before deployment')
        if kind == 'Deployment':
            pod = item['spec']['template']['spec']
        elif kind == 'CronJob':
            pod = item['spec']['jobTemplate']['spec']['template']['spec']
        else:
            pod = None
        if pod:
            volumes = {v['name']: v for v in pod.get('volumes', [])}
            for volume in volumes.values():
                if 'persistentVolumeClaim' in volume:
                    need('PersistentVolumeClaim', namespace, volume['persistentVolumeClaim']['claimName'])
                if 'configMap' in volume:
                    need('ConfigMap', namespace, volume['configMap']['name'])
            for container in pod.get('containers', []) + pod.get('initContainers', []):
                for mount in container.get('volumeMounts', []):
                    if mount['name'] not in volumes:
                        raise ValueError('Unknown volume mount in ' + name)
                for env in container.get('envFrom', []):
                    if 'configMapRef' in env:
                        need('ConfigMap', namespace, env['configMapRef']['name'])
                refs = [e['secretRef']['name'] for e in container.get('envFrom', []) if 'secretRef' in e]
                refs += [e['valueFrom']['secretKeyRef']['name'] for e in container.get('env', [])
                         if 'secretKeyRef' in e.get('valueFrom', {})]
                for ref in refs:
                    if (namespace, ref) not in secrets and ref not in EXTERNAL_SECRETS:
                        raise ValueError('Unknown Secret reference: ' + ref)
        if kind == 'Ingress':
            if item['spec'].get('ingressClassName') != 'traefik':
                raise ValueError('Ingress uses an unsupported controller: ' + name)
            if any(k.startswith('nginx.ingress.kubernetes.io/') for k in item['metadata'].get('annotations', {})):
                raise ValueError('Retired NGINX annotation: ' + name)
            for rule in item['spec'].get('rules', []):
                for path in rule.get('http', {}).get('paths', []):
                    service = path['backend']['service']
                    need('Service', namespace, service['name'])
                    target = objects[('Service', namespace, service['name'])]
                    if service['port'].get('number') not in {p['port'] for p in target['spec']['ports']}:
                        raise ValueError('Ingress points at a missing Service port: ' + name)
        if kind == 'Service' and item['spec'].get('selector'):
            selector = item['spec']['selector']
            deployments = [d for (k, ns, _), d in objects.items() if k == 'Deployment' and ns == namespace]
            if not any(all(d['spec']['template']['metadata']['labels'].get(k) == v
                           for k, v in selector.items()) for d in deployments):
                raise ValueError('Service selector matches no Deployment: ' + name)
    return len(objects)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests', nargs='+', type=Path)
    parser.add_argument('--allow-template-values', action='store_true',
                        help='CI only: allow the documented node placeholder and unsealed template')
    args = parser.parse_args()
    resources = [d for p in args.manifests for d in yaml.safe_load_all(p.read_text())]
    print('Validated', validate(resources, args.allow_template_values), 'resource references')


if __name__ == '__main__':
    main()
