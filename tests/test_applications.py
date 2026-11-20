from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def pod(app):
    return yaml.safe_load((ROOT / 'k8s/base' / app / 'deployment.yaml').read_text())['spec']['template']['spec']


class ApplicationTests(unittest.TestCase):
    def test_unusable_services_do_not_enter_default_stack(self):
        base = yaml.safe_load((ROOT / 'k8s/base/kustomization.yaml').read_text())
        for app in ('sub-zero', 'theposterdb', 'mediux', 'scannarr', 'janitorr', 'varken'):
            self.assertNotIn(app + '/', base['resources'])

    def test_tdarr_database_is_persistent_and_included_in_backup(self):
        spec = pod('tdarr')
        mount = next(m for m in spec['containers'][0]['volumeMounts'] if m['mountPath'] == '/app/server')
        volume = next(v for v in spec['volumes'] if v['name'] == mount['name'])
        self.assertEqual(volume['persistentVolumeClaim']['claimName'], 'tdarr-server-pvc')
        backup = yaml.safe_load((ROOT / 'k8s/base/backup/cronjob.yaml').read_text())
        mounts = backup['spec']['jobTemplate']['spec']['template']['spec']['containers'][0]['volumeMounts']
        self.assertTrue(any(m['mountPath'] == '/config-volumes/tdarr-server-pvc' and m['readOnly'] for m in mounts))

    def test_recyclarr_uses_upstream_default_entrypoint(self):
        spec = pod('recyclarr')
        self.assertNotIn('args', spec['containers'][0])
        self.assertEqual(spec['securityContext']['runAsUser'], 1000)

    def test_posterr_and_unpackerr_persist_actual_config_locations(self):
        mounts = {m['mountPath'] for m in pod('posterr')['containers'][0]['volumeMounts']}
        self.assertTrue({'/usr/src/app/config', '/usr/src/app/public/custom'} <= mounts)
        unpackerr = pod('unpackerr')['containers'][0]
        self.assertIn('/config', {m['mountPath'] for m in unpackerr['volumeMounts']})
        env = {e['name']: e for e in unpackerr['env']}
        self.assertNotIn('UN_QBIT_0_URL', env)
        self.assertIn('secretKeyRef', env['UN_SONARR_0_API_KEY']['valueFrom'])


if __name__ == '__main__':
    unittest.main()
