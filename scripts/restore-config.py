#!/usr/bin/env python3
"""Restore through a one-shot Kubernetes Job while Argo and apps are paused."""
import argparse
import json
import subprocess
import sys
import time

STATE = 'media-recovery-state'
NAMESPACE = 'media'


def kubectl(*args, data=None):
    result = subprocess.run(['kubectl', *args], input=None if data is None else
                            json.dumps(data), text=True, capture_output=True, check=True)
    return result.stdout


def get(kind, namespace=NAMESPACE):
    return json.loads(kubectl('-n', namespace, 'get', kind, '-o', 'json'))


def patch(kind, name, data, namespace=NAMESPACE):
    kubectl('-n', namespace, 'patch', kind, name, '--type=merge', '-p', json.dumps(data))


def save_state(state):
    kubectl('apply', '-f', '-', data={
        'apiVersion': 'v1', 'kind': 'ConfigMap',
        'metadata': {'name': STATE, 'namespace': NAMESPACE},
        'data': {'state.json': json.dumps(state)}})


def resume():
    state = json.loads(get('configmap/' + STATE)['data']['state.json'])
    job = get('job/' + state['job'])
    if job.get('status', {}).get('succeeded', 0) < 1:
        raise RuntimeError('Restore did not succeed; apps remain stopped')
    for name, replicas in state['replicas'].items():
        patch('deployment', name, {'spec': {'replicas': replicas}})
    patch('cronjob', 'config-backup', {'spec': {'suspend': state['suspend']}})
    # Resume child reconciliation before its parent, after data is restored.
    for app in reversed(state['applications']):
        patch('application', app['name'], {'spec': {'syncPolicy': app['syncPolicy']}}, 'argocd')
    kubectl('-n', NAMESPACE, 'delete', 'configmap', STATE)
    print('Original replica counts, backup schedule, and Argo policies restored.')


def prepare(snapshot, overwrite, retry=False):
    existing = any(x['metadata']['name'] == STATE for x in get('configmaps')['items'])
    if existing and not retry:
        raise RuntimeError('Recovery already in progress; inspect its Job before retrying')
    if retry and not existing:
        raise RuntimeError('No saved recovery state exists for --retry')
    if any(j.get('status', {}).get('active', 0) for j in get('jobs')['items']):
        raise RuntimeError('A Job is still active in media; let it finish before restoring')
    applications = []
    # An existing cluster has Argo; a fresh recovery can be run before Argo bootstrap.
    argo = subprocess.run(['kubectl', '-n', 'argocd', 'get', 'applications', '-o', 'json'],
                          capture_output=True, text=True)
    if argo.returncode and not any(reason in argo.stderr for reason in
                                   ('NotFound', "doesn't have a resource type")):
        raise RuntimeError('Cannot inspect Argo; refusing to restore without pausing reconciliation')
    if argo.returncode == 0:
        apps = {a['metadata']['name']: a for a in json.loads(argo.stdout)['items']}
        for name in ('root', 'media-stack'):
            if name in apps:
                applications.append({'name': name, 'syncPolicy':
                                     apps[name]['spec'].get('syncPolicy', {})})
    deployments = get('deployments')['items']
    schedule = get('cronjob/config-backup')
    name = 'config-restore-' + str(int(time.time()))
    if retry:
        state = json.loads(get('configmap/' + STATE)['data']['state.json'])
        if any(d['spec'].get('replicas', 1) for d in deployments):
            raise RuntimeError('A workload is running; stop it before retrying recovery')
        applications = state['applications']
        state['job'] = name
    else:
        state = {'job': name, 'applications': applications,
                 'replicas': {d['metadata']['name']: d['spec'].get('replicas', 1)
                              for d in deployments},
                 'suspend': schedule['spec'].get('suspend', False)}
    save_state(state)
    for app in applications:
        patch('application', app['name'], {'spec': {'syncPolicy': {'automated': None}}}, 'argocd')
    # An in-flight Argo operation can otherwise race the scale-down.
    deadline = time.monotonic() + 300
    while any(get('application/' + a['name'], 'argocd').get('status', {}).get(
            'operationState', {}).get('phase') in ('Running', 'Terminating')
              for a in applications):
        if time.monotonic() > deadline:
            raise RuntimeError('Argo operation still running; reconciliation remains paused')
        time.sleep(2)
    patch('cronjob', 'config-backup', {'spec': {'suspend': True}})
    if deployments:
        kubectl('-n', NAMESPACE, 'scale', 'deployment', '--all', '--replicas=0')
    if get('pods')['items']:
        kubectl('-n', NAMESPACE, 'wait', '--for=delete', 'pod', '--all', '--timeout=300s')
    job = json.loads(kubectl('-n', NAMESPACE, 'create', 'job', name,
                            '--from=cronjob/config-backup', '--dry-run=client', '-o', 'json'))
    pod = job['spec']['template']['spec']
    container = pod['containers'][0]
    container['args'] = ['restore', '--snapshot', snapshot]
    container.setdefault('env', []).append({'name': 'RESTORE_OVERWRITE',
                                          'value': 'true' if overwrite else 'false'})
    for mount in container['volumeMounts']:
        if mount['mountPath'].startswith('/config-volumes/'):
            mount['readOnly'] = False
    # Do not grant the restore pod access to sealing keys in the Kubernetes API.
    pod['automountServiceAccountToken'] = False
    kubectl('apply', '-f', '-', data=job)
    print('Started ' + name + '. Workloads remain stopped until --resume succeeds.')
    kubectl('-n', NAMESPACE, 'wait', '--for=condition=complete', 'job/' + name,
            '--timeout=7200s')
    print('Restore complete. Review Job logs, then run: ./scripts/restore-config.py --resume')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', default='latest')
    parser.add_argument('--overwrite', action='store_true', help='replace nonempty config volumes')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry', action='store_true')
    args = parser.parse_args()
    try:
        resume() if args.resume else prepare(args.snapshot, args.overwrite, args.retry)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stderr, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
