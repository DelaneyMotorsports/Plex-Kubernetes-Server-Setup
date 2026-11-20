#!/usr/bin/env python3
"""Check pinned image references, or explicitly refresh the public image lock."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import re
import sys
import yaml
from image_registry import inspect_image, split_image

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'ci/images.lock.json'


def references(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'image' and isinstance(child, str): yield child
            else: yield from references(child)
    elif isinstance(value, list):
        for child in value: yield from references(child)


def identity(image):
    return split_image(image)


def source_files():
    return sorted((ROOT / 'k8s').rglob('*.yaml'))


def check(lock):
    allowed = {identity(entry['reference']) for entry in lock['images'].values()}
    found = 0
    for path in source_files():
        for doc in yaml.safe_load_all(path.read_text()):
            for image in references(doc):
                if '@sha256:' not in image or identity(image) not in allowed:
                    raise RuntimeError('Image is not in the immutable lock: ' + image)
                found += 1
    variables = yaml.safe_load((ROOT / 'ansible/inventory/group_vars/all.yml').read_text())
    traefik = 'docker.io/traefik@' + variables['traefik_image_digest']
    if identity(traefik) not in allowed:
        raise RuntimeError('Traefik digest is not in the image lock')
    if not found:
        raise RuntimeError('No workload images checked')
    print(f'Checked {found} workload references and the Traefik image against the immutable lock')


def refresh(lock):
    def resolve(item):
        name, entry = item
        result = inspect_image(entry['source'])
        if not {'linux/amd64', 'linux/arm64'} <= set(result['platforms']):
            raise RuntimeError('Source lost AMD64/ARM64 support: ' + name)
        reference = entry['source'].removesuffix(':latest') + '@' + result['digest']
        return name, {**entry, 'reference': reference, 'digest': result['digest'],
                      'platforms': result['platforms']}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        updated = dict(pool.map(resolve, lock['images'].items()))
    # Resolve everything before changing a file. This command never commits or pushes.
    replacements = {identity(entry['reference']): updated[name]['reference']
                    for name, entry in lock['images'].items()}
    file_updates = {}
    for path in source_files():
        text = path.read_text()
        for doc in yaml.safe_load_all(text):
            for old in set(references(doc)):
                text = text.replace(old, replacements[identity(old)])
        file_updates[path] = text
    traefik = next(e for e in updated.values() if identity(e['reference'])[:2] ==
                   ('registry-1.docker.io', 'library/traefik'))
    variables = ROOT / 'ansible/inventory/group_vars/all.yml'
    file_updates[variables] = re.sub(r'^traefik_image_digest:.*$',
                               'traefik_image_digest: "' + traefik['digest'] + '"',
                               variables.read_text(), flags=re.MULTILINE)
    lock['images'] = updated
    file_updates[LOCK] = json.dumps(lock, indent=2) + '\n'
    for path, text in file_updates.items():
        path.write_text(text)
    check(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text())
    if args.refresh: refresh(lock)
    else: check(lock)


if __name__ == '__main__':
    main()
