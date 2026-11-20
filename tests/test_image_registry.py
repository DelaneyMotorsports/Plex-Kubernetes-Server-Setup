import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('image_registry', ROOT / 'scripts/image_registry.py')
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)


class ImageReferenceTests(unittest.TestCase):
    def test_docker_official_images_include_library_namespace(self):
        self.assertEqual(registry.split_image('docker.io/traefik:v3.7.18'),
                         ('registry-1.docker.io', 'library/traefik', 'v3.7.18'))
        self.assertEqual(registry.split_image('python:3.12-alpine'),
                         ('registry-1.docker.io', 'library/python', '3.12-alpine'))

    def test_tag_with_immutable_digest_uses_digest_not_tag(self):
        self.assertEqual(registry.split_image('ghcr.io/example/app:1@sha256:abcd'),
                         ('ghcr.io', 'example/app', 'sha256:abcd'))

    def test_namespaced_image_and_registry_port_are_preserved(self):
        self.assertEqual(registry.split_image('golift/unpackerr:1'),
                         ('registry-1.docker.io', 'golift/unpackerr', '1'))
        self.assertEqual(registry.split_image('registry.example:5000/team/app:1'),
                         ('registry.example:5000', 'team/app', '1'))


if __name__ == '__main__':
    unittest.main()
