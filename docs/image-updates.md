# Reproducible application images

Every application, addon, backup container and Traefik image is pinned to an
immutable multi-platform manifest-index digest. The index retains both AMD64 and
ARM64 variants, so a Pi and an x86 node select their own image from the same pin.
`IfNotPresent` avoids unnecessary re-fetches; the digest, not a mutable tag,
determines which bytes the runtime uses.

`ci/images.lock.json` records source references, pinned references and verified
platforms. A source may track `latest` for explicitly requested updates, but
runtime manifests do not deploy a floating latest tag. Traefik's chart version,
image version and image digest are pinned separately in Ansible inventory.

Check the lock without a network call:

```bash
python3 scripts/lock-images.py --check
```

To request updates, inspect upstream release notes, adjust a source version in the
lock when necessary, and explicitly refresh:

```bash
python3 scripts/lock-images.py --refresh
./scripts/validate.sh
git diff
```

Refresh queries all sources and requires published AMD64/ARM64 variants before
writing changes. It updates workload references and the Traefik image digest.
When changing Traefik versions, also update `traefik_image_version` and verify the
chart's version compatibility. Review the resulting diff, run startup/recovery
checks, then create a normal commit with the established author/committer identity.
No update command commits, pushes, or adds another contributor automatically.

CI rejects unpinned or unreviewed rendered images, checks actual registry manifest
bytes against their SHA256 digest, and checks architecture availability. A pin
provides reproducibility, not a claim that an old image has no vulnerabilities;
updates still need regular review. To roll back, restore both manifests and lock
metadata from the selected prior Git revision and resync deliberately. Database
schema migrations can require restoring the matching config snapshot too.
