#!/usr/bin/env python3
"""Check that rendered workload images publish both supported architectures."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import sys
import yaml
from image_registry import inspect_image, split_image


def images(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'image' and isinstance(child, str):
                yield child
            else:
                yield from images(child)
    elif isinstance(value, list):
        for child in value:
            yield from images(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests', nargs='+', type=Path)
    parser.add_argument('--require-digests', action='store_true')
    args = parser.parse_args()
    refs = sorted({i for path in args.manifests for doc in yaml.safe_load_all(path.read_text()) for i in images(doc)})
    lock_path = Path(__file__).resolve().parents[1] / 'ci/images.lock.json'
    allowed = {split_image(entry['reference']) for entry in json.loads(lock_path.read_text())['images'].values()} if lock_path.exists() else set()
    errors = []
    def check(ref):
        try:
            if args.require_digests and '@sha256:' not in ref:
                raise RuntimeError('immutable manifest digest required')
            if args.require_digests and split_image(ref) not in allowed:
                raise RuntimeError('rendered image is not in the reviewed image lock')
            result = inspect_image(ref)
            if not {'linux/amd64', 'linux/arm64'} <= set(result['platforms']):
                raise RuntimeError('AMD64 and ARM64 images must both be published')
            return result
        except Exception as exc:
            return {'image': ref, 'error': str(exc)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(check, refs):
            print(json.dumps(result))
            if 'error' in result:
                errors.append(result)
    if errors or not refs:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
