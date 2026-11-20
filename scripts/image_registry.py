"""Read public OCI manifest metadata without downloading image layers."""
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

ACCEPT = ', '.join(['application/vnd.oci.image.index.v1+json',
                    'application/vnd.docker.distribution.manifest.list.v2+json',
                    'application/vnd.oci.image.manifest.v1+json',
                    'application/vnd.docker.distribution.manifest.v2+json'])


def split_image(image):
    if '@' in image:
        image, reference = image.split('@', 1)
        if ':' in image.rsplit('/', 1)[-1]:
            image = image.rsplit(':', 1)[0]
    elif ':' in image.rsplit('/', 1)[-1]:
        image, reference = image.rsplit(':', 1)
    else:
        reference = 'latest'
    bits = image.split('/', 1)
    if '.' in bits[0] or ':' in bits[0] or bits[0] == 'localhost':
        registry, name = bits
    else:
        registry, name = 'registry-1.docker.io', image
        if '/' not in name:
            name = 'library/' + name
    if registry in ('docker.io', 'index.docker.io'):
        registry = 'registry-1.docker.io'
    if registry == 'registry-1.docker.io' and '/' not in name:
        name = 'library/' + name
    return registry, name, reference


def inspect_image(image):
    registry, name, reference = split_image(image)
    headers = {'Accept': ACCEPT, 'User-Agent': 'media-stack-image-validation'}

    def fetch(path):
        url = 'https://' + registry + '/v2/' + name + '/' + path
        try:
            response = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45)
        except urllib.error.HTTPError as exc:
            challenge = exc.headers.get('WWW-Authenticate', '')
            if exc.code != 401 or not challenge.lower().startswith('bearer '):
                raise
            auth = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
            if not auth.get('realm', '').startswith('https://'):
                raise RuntimeError('Registry supplied an insecure authentication realm')
            query = urllib.parse.urlencode({key: auth[key] for key in ('service', 'scope') if key in auth})
            with urllib.request.urlopen(auth['realm'] + '?' + query, timeout=45) as token_response:
                token = json.load(token_response)
            headers['Authorization'] = 'Bearer ' + (token.get('token') or token['access_token'])
            response = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45)
        with response:
            body = response.read()
            actual = 'sha256:' + hashlib.sha256(body).hexdigest()
            digest = response.headers.get('Docker-Content-Digest') or actual
            if digest != actual:
                raise RuntimeError('Registry manifest bytes do not match its declared digest')
            return json.loads(body), digest

    manifest, digest = fetch('manifests/' + urllib.parse.quote(reference, safe=':'))
    if reference.startswith('sha256:') and reference != digest:
        raise RuntimeError('Registry returned a different digest than the requested immutable image')
    if 'manifests' in manifest:
        platforms = sorted({p['platform']['os'] + '/' + p['platform']['architecture']
                            for p in manifest['manifests'] if p.get('platform', {}).get('os') not in (None, 'unknown')})
    else:
        config, _ = fetch('blobs/' + manifest['config']['digest'])
        platforms = [config['os'] + '/' + config['architecture']]
    return {'image': image, 'digest': digest, 'platforms': platforms}
