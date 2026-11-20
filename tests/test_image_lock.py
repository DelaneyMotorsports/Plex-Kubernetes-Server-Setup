import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('lock_images', ROOT / 'scripts/lock-images.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.path.pop(0)


class ImageLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = 'sha256:' + 'a' * 64
        self.new = 'sha256:' + 'b' * 64
        self.manifest = self.root / 'workload.yaml'
        self.manifest.write_text('image: ghcr.io/example/app:1@' + self.old + '\n')
        self.variables = self.root / 'ansible/inventory/group_vars/all.yml'
        self.variables.parent.mkdir(parents=True)
        self.variables.write_text('traefik_image_digest: "' + self.old + '"\n')
        self.lockfile = self.root / 'images.lock.json'
        self.lock = {'format': 1, 'images': {source: {'source': source,
                     'reference': source + '@' + self.old, 'digest': self.old,
                     'platforms': ['linux/amd64', 'linux/arm64']}
                     for source in ['ghcr.io/example/app:1', 'docker.io/traefik:v3.7.18']}}
        self.lockfile.write_text(json.dumps(self.lock))

    def tearDown(self):
        self.temp.cleanup()

    def setup_patches(self):
        return (patch.object(module, 'ROOT', self.root), patch.object(module, 'LOCK', self.lockfile),
                patch.object(module, 'source_files', return_value=[self.manifest]))

    def test_floating_reference_is_rejected(self):
        self.manifest.write_text('image: ghcr.io/example/app:1\n')
        a, b, c = self.setup_patches()
        with a, b, c:
            with self.assertRaisesRegex(RuntimeError, 'immutable lock'):
                module.check(self.lock)

    def test_refresh_updates_workload_and_controller_together(self):
        a, b, c = self.setup_patches()
        with a, b, c, patch.object(module, 'inspect_image', return_value={
                'digest': self.new, 'platforms': ['linux/amd64', 'linux/arm64']}):
            module.refresh(self.lock)
        self.assertIn(self.new, self.manifest.read_text())
        self.assertEqual(yaml.safe_load(self.variables.read_text())['traefik_image_digest'], self.new)
        self.assertEqual(json.loads(self.lockfile.read_text())['images']['ghcr.io/example/app:1']['digest'], self.new)

    def test_architecture_regression_leaves_all_files_untouched(self):
        before = self.manifest.read_text()
        a, b, c = self.setup_patches()
        with a, b, c, patch.object(module, 'inspect_image', return_value={
                'digest': self.new, 'platforms': ['linux/amd64']}):
            with self.assertRaisesRegex(RuntimeError, 'lost AMD64/ARM64'):
                module.refresh(self.lock)
        self.assertEqual(self.manifest.read_text(), before)
        self.assertIn(self.old, self.variables.read_text())

    def test_unknown_local_reference_fails_before_changing_earlier_files(self):
        other = self.root / 'unknown.yaml'
        other.write_text('image: ghcr.io/unreviewed/app:1@' + self.old + '\n')
        a, b, _ = self.setup_patches()
        before = self.manifest.read_text()
        with a, b, patch.object(module, 'source_files', return_value=[self.manifest, other]), \
                patch.object(module, 'inspect_image', return_value={
                    'digest': self.new, 'platforms': ['linux/amd64', 'linux/arm64']}):
            with self.assertRaises(KeyError):
                module.refresh(self.lock)
        self.assertEqual(self.manifest.read_text(), before)
        self.assertIn(self.old, self.variables.read_text())


if __name__ == '__main__':
    unittest.main()
