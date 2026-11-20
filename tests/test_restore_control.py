import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('restore_control', ROOT / 'scripts/restore-config.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class RestoreControlTests(unittest.TestCase):
    def setUp(self):
        cron = yaml.safe_load((ROOT / 'k8s/base/backup/cronjob.yaml').read_text())
        self.job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': 'fixture'},
                    'spec': copy.deepcopy(cron['spec']['jobTemplate']['spec'])}
        self.actions = []
        self.state = None
        self.applied_job = None
        self.succeeded = 1
        self.apps = [{'metadata': {'name': name}, 'spec': {'syncPolicy': {'automated': {
            'prune': True, 'selfHeal': True}}}} for name in ('root', 'media-stack')]

    def get(self, kind, namespace='media'):
        if kind == 'configmaps': return {'items': []}
        if kind == 'jobs': return {'items': []}
        if kind == 'deployments': return {'items': [
            {'metadata': {'name': 'sonarr'}, 'spec': {'replicas': 1}},
            {'metadata': {'name': 'radarr'}, 'spec': {'replicas': 0}}]}
        if kind == 'cronjob/config-backup': return {'spec': {'suspend': False}}
        if kind.startswith('application/'): return {'status': {'operationState': {'phase': 'Succeeded'}}}
        if kind == 'pods': return {'items': []}
        if kind == 'configmap/' + control.STATE: return {'data': {'state.json': json.dumps(self.state)}}
        if kind.startswith('job/'): return {'status': {'succeeded': self.succeeded}}
        raise AssertionError(kind)

    def kubectl(self, *args, data=None):
        self.actions.append((args, data))
        if data and data['kind'] == 'ConfigMap':
            self.state = json.loads(data['data']['state.json'])
        if data and data['kind'] == 'Job': self.applied_job = data
        if 'create' in args and 'job' in args:
            return json.dumps(self.job)
        return ''

    def contexts(self):
        return (patch.object(control, 'get', side_effect=self.get),
                patch.object(control, 'kubectl', side_effect=self.kubectl),
                patch.object(control.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout=json.dumps({'items': self.apps}), stderr='')))

    def test_restore_stops_apps_before_writes_and_removes_api_token(self):
        a, b, c = self.contexts()
        with a, b, c:
            control.prepare('fixture-snapshot', False)
        scale = next(i for i, (args, _) in enumerate(self.actions) if 'scale' in args)
        apply_job = next(i for i, (_, data) in enumerate(self.actions) if data and data['kind'] == 'Job')
        self.assertLess(scale, apply_job)
        policies = [args for args, _ in self.actions if 'patch' in args and 'application' in args]
        self.assertEqual([p[4] for p in policies], ['root', 'media-stack'])
        pod = self.applied_job['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        container = pod['containers'][0]
        self.assertEqual(container['args'], ['restore', '--snapshot', 'fixture-snapshot'])
        self.assertTrue(all(not m['readOnly'] for m in container['volumeMounts']
                            if m['mountPath'].startswith('/config-volumes/')))
        self.assertEqual(self.state['replicas']['radarr'], 0)

    def test_failed_restore_cannot_resume(self):
        self.state = {'job': 'failed', 'replicas': {'sonarr': 1}, 'applications': [], 'suspend': False}
        self.succeeded = 0
        with patch.object(control, 'get', side_effect=self.get), \
                patch.object(control, 'kubectl', side_effect=self.kubectl):
            with self.assertRaisesRegex(RuntimeError, 'did not succeed'):
                control.resume()
        self.assertEqual(self.actions, [])

    def test_successful_resume_preserves_disabled_replica_and_policies(self):
        self.state = {'job': 'succeeded', 'replicas': {'sonarr': 1, 'radarr': 0}, 'suspend': False,
                      'applications': [{'name': a['metadata']['name'], 'syncPolicy': a['spec']['syncPolicy']}
                                       for a in self.apps]}
        with patch.object(control, 'get', side_effect=self.get), \
                patch.object(control, 'kubectl', side_effect=self.kubectl):
            control.resume()
        replica_patches = [args for args, _ in self.actions if 'patch' in args and 'deployment' in args]
        self.assertEqual(json.loads(replica_patches[1][-1])['spec']['replicas'], 0)
        argo_patches = [args for args, _ in self.actions if 'patch' in args and 'application' in args]
        self.assertEqual([p[4] for p in argo_patches], ['media-stack', 'root'])

    def test_unreadable_argo_state_aborts_before_any_write(self):
        a, b, _ = self.contexts()
        with a, b, patch.object(control.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout='', stderr='Forbidden')):
            with self.assertRaisesRegex(RuntimeError, 'Cannot inspect Argo'):
                control.prepare('snapshot', False)
        self.assertEqual(self.actions, [])


if __name__ == '__main__':
    unittest.main()
