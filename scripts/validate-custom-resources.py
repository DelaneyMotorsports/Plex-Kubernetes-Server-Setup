#!/usr/bin/env python3
"""Validate repository CRs against checksum-pinned upstream CRD schemas."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import yaml
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[1]


def schema_for(spec):
    with urllib.request.urlopen(spec['url'], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise RuntimeError('Upstream CRD checksum changed: ' + spec['url'])
    crd = next(d for d in yaml.safe_load_all(data) if d and d.get('kind') == 'CustomResourceDefinition'
               and d['spec']['names']['kind'] == spec['kind'])
    schema = next(v['schema']['openAPIV3Schema'] for v in crd['spec']['versions'] if v['name'] == spec['version'])
    def nullable(value):
        if isinstance(value, dict):
            if value.get('nullable') and isinstance(value.get('type'), str):
                value['type'] = [value['type'], 'null']
            for child in value.values(): nullable(child)
        elif isinstance(value, list):
            for child in value: nullable(child)
    nullable(schema)
    return schema


def main():
    specs = json.loads((ROOT / 'ci/custom-resources.json').read_text())
    validators = {name: Draft7Validator(schema_for(spec)) for name, spec in specs.items()}
    checked = 0
    for filename in sys.argv[1:]:
        for resource in yaml.safe_load_all(Path(filename).read_text()):
            if not resource: continue
            key = resource.get('apiVersion', '') + '/' + resource.get('kind', '')
            if resource.get('kind') in {s['kind'] for s in specs.values()} and key not in validators:
                raise RuntimeError('No pinned schema for custom resource version: ' + key)
            if key in validators:
                validators[key].validate(resource)
                checked += 1
    if not checked:
        raise RuntimeError('No custom resources were validated')
    print(f'Validated {checked} custom resources against pinned upstream schemas')


if __name__ == '__main__':
    main()
