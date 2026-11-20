import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('validator', ROOT / 'scripts/validate-manifests.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ManifestValidationTests(unittest.TestCase):
    def setUp(self):
        self.deployment = {'kind': 'Deployment', 'metadata': {'name': 'app', 'namespace': 'media'},
                           'spec': {'template': {'metadata': {'labels': {'app': 'app'}},
                                                'spec': {'containers': [{'name': 'app'}]}}}}
        self.service = {'kind': 'Service', 'metadata': {'name': 'app', 'namespace': 'media'},
                        'spec': {'selector': {'app': 'app'}, 'ports': [{'port': 80}]}}
        self.ingress = {'kind': 'Ingress', 'metadata': {'name': 'app', 'namespace': 'media'},
                        'spec': {'ingressClassName': 'traefik', 'rules': [{'http': {'paths': [
                            {'backend': {'service': {'name': 'app', 'port': {'number': 80}}}}]}}]}}
        self.resources = [self.deployment, self.service, self.ingress]

    def test_valid_routing(self):
        self.assertEqual(validator.validate(self.resources), 3)

    def test_missing_backend_and_wrong_service_port_fail(self):
        with self.assertRaisesRegex(ValueError, 'Missing Service'):
            validator.validate([self.deployment, self.ingress])
        self.service['spec']['ports'][0]['port'] = 81
        with self.assertRaisesRegex(ValueError, 'missing Service port'):
            validator.validate(self.resources)

    def test_missing_storage_and_wrong_selector_fail(self):
        self.deployment['spec']['template']['spec']['volumes'] = [
            {'name': 'config', 'persistentVolumeClaim': {'claimName': 'missing'}}]
        with self.assertRaisesRegex(ValueError, 'Missing PersistentVolumeClaim'):
            validator.validate(self.resources)
        self.deployment['spec']['template']['spec'].pop('volumes')
        self.service['spec']['selector']['app'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'selector matches no Deployment'):
            validator.validate(self.resources)

    def test_template_allowance_is_narrow_and_deployment_check_is_strict(self):
        self.deployment['spec']['template']['spec']['nodeSelector'] = {
            'kubernetes.io/hostname': 'CHANGE-ME-NODE-NAME'}
        with self.assertRaisesRegex(ValueError, 'Unresolved placeholder'):
            validator.validate(self.resources)
        self.assertEqual(validator.validate(self.resources, allow_template_values=True), 3)
        self.deployment['metadata']['name'] = 'CHANGE-ME-other'
        with self.assertRaisesRegex(ValueError, 'Unresolved placeholder'):
            validator.validate(self.resources, allow_template_values=True)

    def test_duplicate_and_retired_ingress_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate resource'):
            validator.validate(self.resources + [copy.deepcopy(self.service)])
        self.ingress['spec']['ingressClassName'] = 'nginx'
        with self.assertRaisesRegex(ValueError, 'unsupported controller'):
            validator.validate(self.resources)


if __name__ == '__main__':
    unittest.main()
