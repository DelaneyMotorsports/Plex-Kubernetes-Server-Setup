import importlib.util
from pathlib import Path
import unittest
import yaml
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resource_budget', ROOT / 'scripts/resource-budget.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BudgetTests(unittest.TestCase):
    def test_native_sidecar_and_normal_init_have_different_memory_accounting(self):
        pod = {'containers': [{'resources': {'limits': {'memory': '512Mi'}}}],
               'initContainers': [
                   {'restartPolicy': 'Always', 'resources': {'limits': {'memory': '128Mi'}}},
                   {'resources': {'limits': {'memory': '1Gi'}}}]}
        self.assertEqual(module.pod_memory(pod, 'limits'), 1152)
        pod['initContainers'][1]['resources']['limits']['memory'] = '32Mi'
        self.assertEqual(module.pod_memory(pod, 'limits'), 640)

    def test_default_profile_excludes_optional_transcoders_and_automation(self):
        base = yaml.safe_load((ROOT / 'k8s/base/kustomization.yaml').read_text())
        for name in ('tdarr', 'ersatztv', 'kometa', 'posterr', 'recyclarr', 'profilarr', 'unpackerr'):
            self.assertNotIn(name + '/', base['resources'])
            self.assertTrue((ROOT / 'k8s/addons' / name / 'kustomization.yaml').exists())

    def test_backup_peak_is_added_once(self):
        documents = [
            {'kind': 'Deployment', 'metadata': {'name': 'app'}, 'spec': {'replicas': 2, 'template': {'spec': {
                'containers': [{'resources': {'requests': {'memory': '64Mi'}, 'limits': {'memory': '256Mi'}}}]}}}},
            {'kind': 'CronJob', 'metadata': {'name': 'config-backup'}, 'spec': {'jobTemplate': {'spec': {'template': {'spec': {
                'containers': [{'resources': {'limits': {'memory': '512Mi'}}}]}}}}}}]
        result = module.budget(documents)
        self.assertEqual(result['steadyLimitMi'], 512)
        self.assertEqual(result['peakWithBackupMi'], 1024)


if __name__ == '__main__':
    unittest.main()
