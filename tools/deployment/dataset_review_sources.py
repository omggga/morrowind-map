"""Hydrate trusted review snapshots from explicitly pinned Release asset IDs."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from tools.deployment.common import DeploymentError, canonical_json_bytes, strict_json_object
from tools.deployment.dataset_packages import (
    MAX_LOCK_BYTES, REPOSITORY, _entry_key, _read_lock, _real_directory,
    parse_lock, read_tile_sets, release_tag, validate_lock,
)
from tools.deployment.download_datasets import download_datasets


MAX_SOURCES_BYTES = 128 * 1024
_REPOSITORY = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}')
_PREFIX = re.compile(r'(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,179})?')
_DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


def parse_sources(payload: bytes) -> list[dict]:
    """Read bounded, explicit staging coordinates; never accept URLs or paths."""
    if len(payload) > MAX_SOURCES_BYTES:
        raise DeploymentError('Review source mapping exceeds its byte limit')
    try:
        payload.decode('utf-8', errors='strict')
    except UnicodeDecodeError as error:
        raise DeploymentError('Review sources must be UTF-8 JSON') from error
    sources = strict_json_object(b'{"sources":' + payload + b'}', 'review sources')['sources']
    if not isinstance(sources, list) or len(sources) > 100:
        raise DeploymentError('Review sources must be an array of at most 100 records')
    keys = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != {
            'datasetId', 'pyramidId', 'inventorySha256', 'repository', 'releaseId', 'assetPrefix',
        }:
            raise DeploymentError('Review source has missing or unexpected fields')
        key = _entry_key(source)
        release_tag(key)
        if key in keys:
            raise DeploymentError('Duplicate review source identity')
        keys.add(key)
        repository, prefix = source['repository'], source['assetPrefix']
        if (not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository)
                or '..' in repository or repository.endswith('/.') or repository.endswith('/-')):
            raise DeploymentError('Review source repository is not a safe owner/name')
        if not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix) or '..' in prefix:
            raise DeploymentError('Review source assetPrefix is not a safe basename prefix')
        if type(source['releaseId']) is not int or source['releaseId'] <= 0:
            raise DeploymentError('Review source releaseId must be a positive integer')
    return sources


def _release_source(api, key: tuple, mapping: dict | None) -> tuple[str, dict, str]:
    tag = release_tag(key)
    release = api.release_by_tag(REPOSITORY, tag)
    if (isinstance(release, dict) and release.get('draft') is True and mapping is not None
            and release.get('tag_name') == tag and type(release.get('id')) is int
            and release['id'] > 0):
        # A previous publication can leave a resumable draft. Review must still
        # verify the explicitly mapped source, never trust the partial draft.
        release = None
    if release is not None:
        if (not isinstance(release, dict) or release.get('draft') is not False
                or release.get('immutable') is not True or release.get('tag_name') != tag
                or type(release.get('id')) is not int or release['id'] <= 0):
            raise DeploymentError('Canonical review release must be published and immutable')
        return REPOSITORY, release, ''
    if mapping is None:
        raise DeploymentError('Missing canonical package; an explicit review source mapping is required')
    release = api.release_by_id(mapping['repository'], mapping['releaseId'])
    if (not isinstance(release, dict) or release.get('draft') is not False
            or type(release.get('id')) is not int or release['id'] != mapping['releaseId']):
        raise DeploymentError('Mapped review release must be published and match its numeric ID')
    return mapping['repository'], release, mapping['assetPrefix']


def _assets(api, repository: str, release_id: int) -> dict:
    listing = api.list_assets(repository, release_id)
    if not isinstance(listing, list) or len(listing) > 1000:
        raise DeploymentError('Invalid review Release asset listing')
    assets = {}
    ids = set()
    for asset in listing:
        if (not isinstance(asset, dict) or not isinstance(asset.get('name'), str)
                or asset['name'] in assets or type(asset.get('id')) is not int
                or asset['id'] <= 0 or asset['id'] in ids
                or type(asset.get('size')) is not int or asset['size'] < 0
                or asset.get('state') != 'uploaded'):
            raise DeploymentError('Invalid or duplicate review Release asset')
        digest = asset.get('digest')
        if digest is not None and (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
            raise DeploymentError('Invalid review Release asset digest')
        assets[asset['name']] = asset
        ids.add(asset['id'])
    return assets


def _index(api, repository: str, assets: dict, prefix: str, tile_set) -> dict:
    asset = assets.get(prefix + 'package-index.json')
    if asset is None or not 0 < asset['size'] <= MAX_LOCK_BYTES:
        raise DeploymentError('Missing or oversized review package-index.json')
    with api.read_asset(repository, asset['id']) as response:
        payload = response.read(asset['size'] + 1)
    if len(payload) != asset['size']:
        raise DeploymentError('Review package index length differs from its listed size')
    if asset.get('digest') is not None:
        import hashlib
        if asset['digest'] != 'sha256:' + hashlib.sha256(payload).hexdigest():
            raise DeploymentError('Review package index differs from its API digest')
    lock = parse_lock(payload)
    validate_lock(lock, [tile_set])
    return lock['tileSets'][0]


class _PinnedClient:
    def __init__(self, api, packages: list):
        self.api = api
        self.sources = {}
        for package in packages:
            for asset in package['source']['assets']:
                self.sources[(_entry_key(package['entry']), asset['name'])] = (
                    package['source']['repository'], asset['assetId'],
                )

    def fetch(self, entry: dict, part: dict):
        repository, asset_id = self.sources[(_entry_key(entry), part['name'])]
        return self.api.read_asset(repository, asset_id)


def restore_snapshot(*, public_root: Path, lock_path: Path | None, sources: list,
                     api, cache_root: Path) -> dict:
    """Preflight every source, then restore against this snapshot's own inventory."""
    sources = parse_sources(canonical_json_bytes(sources))
    tile_sets = read_tile_sets(public_root=public_root)
    mappings = {_entry_key(source): source for source in sources}
    if set(mappings) - {tile_set.key for tile_set in tile_sets}:
        raise DeploymentError('Review source mapping does not belong to this snapshot')
    committed = _read_lock(lock_path) if lock_path is not None else None
    if committed is not None:
        validate_lock(committed, tile_sets)
    entries = {_entry_key(entry): entry for entry in committed['tileSets']} if committed else {}
    packages = []
    for tile_set in tile_sets:
        repository, release, prefix = _release_source(api, tile_set.key, mappings.get(tile_set.key))
        assets = _assets(api, repository, release['id'])
        # Legacy/bootstrap snapshots derive only the descriptor for their own
        # verified inventory. Normal snapshots never fetch a replacement lock.
        entry = entries.get(tile_set.key)
        if entry is None:
            entry = _index(api, repository, assets, prefix, tile_set)
        pinned = []
        for part in entry['parts']:
            asset_name = prefix + part['name']
            asset = assets.get(asset_name)
            if asset is None or asset['size'] != part['bytes']:
                raise DeploymentError('Missing review archive or size differs from the transport lock')
            digest = asset.get('digest')
            if digest is not None and digest != 'sha256:' + part['sha256']:
                raise DeploymentError('Review archive API digest differs from the transport lock')
            pinned.append({'name': part['name'], 'assetName': asset_name, 'assetId': asset['id'],
                           'sha256': part['sha256'], 'bytes': part['bytes'], 'apiDigest': digest})
        packages.append({'entry': entry, 'source': {
            'repository': repository, 'releaseId': release['id'], 'assets': pinned,
        }})
    lock = {'schemaVersion': 1, 'repository': REPOSITORY,
            'tileSets': [package['entry'] for package in packages]}
    validate_lock(lock, tile_sets)
    cache = _real_directory(Path(cache_root))
    with tempfile.TemporaryDirectory(prefix='.review-lock-', dir=cache) as temporary:
        effective_lock = Path(temporary) / 'dataset-releases.lock.json'
        effective_lock.write_bytes(canonical_json_bytes(lock))
        download_datasets(repo_root=cache, public_root=public_root, cache_root=cache,
                          lock_path=effective_lock, client=_PinnedClient(api, packages), keep_cache=False)
    return {'lock': lock, 'packages': packages}
