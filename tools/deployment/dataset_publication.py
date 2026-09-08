"""Publish receipt-bound packages without executing or extracting candidate content."""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

from tools.deployment.common import DeploymentError, canonical_json_bytes
from tools.deployment.dataset_packages import REPOSITORY, _lock, is_product_release, parse_lock


def _positive_id(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise DeploymentError(f'{label} must be a positive integer')
    return value


def _release(release: dict, release_id: int, tag: str | None = None) -> None:
    if release.get('id') != release_id or type(release.get('draft')) is not bool:
        raise DeploymentError('Release identity or state changed')
    if tag is not None and release.get('tag_name') != tag:
        raise DeploymentError('Canonical release tag changed')


def _asset(asset: dict, name: str, size: int, sha256: str) -> int:
    asset_id = _positive_id(asset.get('id'), 'Asset ID')
    if asset.get('name') != name or type(asset.get('size')) is not int or asset['size'] != size:
        raise DeploymentError('Release asset name or size differs from the reviewed package')
    if asset.get('state') != 'uploaded':
        raise DeploymentError('Release asset upload is not complete')
    if asset.get('digest') not in (None, 'sha256:' + sha256):
        raise DeploymentError('Release asset digest differs from the reviewed package')
    return asset_id


def _stream(api: Any, repo: str, asset_id: int, size: int, sha256: str,
            output: BinaryIO | None = None) -> None:
    """Always bound downloads, including when GitHub supplies a matching digest."""
    digest = hashlib.sha256()
    received = 0
    try:
        with api.read_asset(repo, asset_id) as source:
            while True:
                chunk = source.read(min(1024 * 1024, size - received + 1))
                if not chunk:
                    break
                received += len(chunk)
                if received > size:
                    raise DeploymentError('Release asset exceeds its reviewed byte count')
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
    except DeploymentError:
        raise
    except Exception:
        raise DeploymentError('Release asset transfer failed; retry publication') from None
    if received != size or digest.hexdigest() != sha256:
        raise DeploymentError('Release asset bytes differ from the reviewed package')


def _source(api: Any, package: dict) -> dict[str, dict]:
    source = package['source']
    repo, release_id = source['repository'], _positive_id(source['releaseId'], 'Source release ID')
    if not isinstance(repo, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise DeploymentError('Invalid source repository')
    _release(api.release_by_id(repo, release_id), release_id)
    current = api.list_assets(repo, release_id)
    by_id = {_positive_id(a.get('id'), 'Source asset ID'): a for a in current}
    if len(by_id) != len(current):
        raise DeploymentError('Duplicate source asset IDs')
    expected = {p['name']: p for p in package['entry']['parts']}
    references = source['assets']
    if len(references) != len(expected) or {a['name'] for a in references} != set(expected):
        raise DeploymentError('Source assets do not cover the reviewed package')
    result = {}
    for reference in references:
        part = expected[reference['name']]
        asset_id = _positive_id(reference['assetId'], 'Reviewed source asset ID')
        asset_name = reference['assetName']
        if not isinstance(asset_name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,254}', asset_name):
            raise DeploymentError('Source asset name must be a safe basename')
        if reference['sha256'] != part['sha256'] or reference['bytes'] != part['bytes']:
            raise DeploymentError('Source asset receipt differs from the transport descriptor')
        asset = by_id.get(asset_id)
        if asset is None:
            raise DeploymentError('Reviewed source asset was removed or replaced')
        _asset(asset, asset_name, part['bytes'], part['sha256'])
        if reference['apiDigest'] is not None and reference['apiDigest'] != asset.get('digest'):
            raise DeploymentError('Reviewed source API digest changed')
        result[part['name']] = asset
    return result


def _canonical_assets(api: Any, release: dict, expected: dict[str, dict], *, complete: bool) -> dict[str, dict]:
    assets = api.list_assets(REPOSITORY, release['id'])
    by_name = {asset['name']: asset for asset in assets}
    if len(by_name) != len(assets) or len({asset.get('id') for asset in assets}) != len(assets):
        raise DeploymentError('Canonical release has duplicate assets')
    if set(by_name) - set(expected) or (complete and set(by_name) != set(expected)):
        raise DeploymentError('Canonical release has an unexpected or incomplete asset set')
    for name, asset in by_name.items():
        part = expected[name]
        asset_id = _asset(asset, name, part['bytes'], part['sha256'])
        if asset.get('digest') is None:
            _stream(api, REPOSITORY, asset_id, part['bytes'], part['sha256'])
    return by_name


def _immutable(api: Any) -> None:
    if api.immutable_policy_confirmed() is not True:
        raise DeploymentError('Canonical repository immutable release policy must be confirmed')


def publish_packages(packages: list[dict], *, api: Any, work_root: Path, tool_sha: str) -> list[dict]:
    """Copy only reviewed bytes, resume matching drafts and never mutate published releases.

    The caller validates receipt provenance before invoking this function. Source
    membership and bytes are checked again here because draft assets can change
    between review and publication. Only one archive occupies temporary disk.
    """
    if not re.fullmatch(r'[0-9a-f]{40}', tool_sha):
        raise DeploymentError('Publication requires the full trusted tool commit SHA')
    if not packages:
        return []
    groups = {}
    for package in packages:
        parse_lock(canonical_json_bytes(_lock([package['entry']])))
        groups.setdefault(package['entry']['releaseTag'], []).append(package)
    # Metadata preflight covers every source and destination before the first write.
    sources = {id(package): _source(api, package) for package in packages}
    prepared = []
    for tag, group in groups.items():
        selected = _lock([package['entry'] for package in group])
        parse_lock(canonical_json_bytes(selected))
        index_lock = selected
        if is_product_release(tag):
            index_lock = group[0].get('index')
            if not isinstance(index_lock, dict):
                raise DeploymentError('Product publication requires its complete reviewed package index')
            parse_lock(canonical_json_bytes(index_lock))
            if (index_lock['schemaVersion'] != 2
                    or any(entry['releaseTag'] != tag for entry in index_lock['tileSets'])
                    or any(package.get('index') != index_lock or package['entry'] not in index_lock['tileSets']
                           for package in group)):
                raise DeploymentError('Product publication packages disagree with their complete reviewed index')
        index = canonical_json_bytes(index_lock)
        expected = {}
        for indexed_entry in index_lock['tileSets']:
            for part in indexed_entry['parts']:
                if part['name'] in expected:
                    raise DeploymentError('Duplicate publication archive name')
                expected[part['name']] = part
        expected['package-index.json'] = {'name': 'package-index.json', 'bytes': len(index),
                                         'sha256': hashlib.sha256(index).hexdigest()}
        release = api.release_by_tag(REPOSITORY, tag)
        assets = {}
        if release is not None:
            _release(release, _positive_id(release.get('id'), 'Canonical release ID'), tag)
            if not release['draft'] and release.get('immutable') is not True:
                raise DeploymentError('Published canonical release is not immutable')
            assets = _canonical_assets(api, release, expected, complete=not release['draft'])
        if ((release is None or release['draft']) and selected != _lock(index_lock['tileSets'])):
            raise DeploymentError('Product publication requires every map from the complete reviewed index')
        prepared.append((tag, group, index, expected, release, assets))
    _immutable(api)
    if work_root.is_symlink():
        raise DeploymentError('Publication work directory must not be a symlink')
    work_root.mkdir(parents=True, exist_ok=True)
    results = []
    for tag, group, index, expected, release, assets in prepared:
        with tempfile.TemporaryDirectory(prefix='dataset-publication-', dir=work_root) as temporary:
            directory = Path(temporary)
            for package in group:
                entry, source = package['entry'], package['source']
                source_assets = sources[id(package)]
                for part in entry['parts']:
                    # Re-read membership at the point of use, not only at preflight.
                    current_source = _source(api, package)
                    asset = current_source[part['name']]
                    if any(asset.get(field) != source_assets[part['name']].get(field)
                           for field in ('id', 'name', 'size', 'state', 'digest')):
                        raise DeploymentError('Reviewed source metadata changed during publication')
                    path = directory / part['name']
                    with path.open('xb') as output:
                        _stream(api, source['repository'], asset['id'], part['bytes'], part['sha256'], output)
                    if part['name'] not in assets:
                        _immutable(api)
                        if release is None:
                            release = api.create_draft(tag, tool_sha,
                                                       'Validated map packages. Contents are pinned by package-index.json.')
                            _release(release, _positive_id(release.get('id'), 'Canonical release ID'), tag)
                            if release['draft'] is not True:
                                raise DeploymentError('New canonical release is not a draft')
                        uploaded = api.upload_asset(release['id'], part['name'], path)
                        _asset(uploaded, part['name'], part['bytes'], part['sha256'])
                        assets = _canonical_assets(api, release, expected, complete=False)
                        if assets.get(part['name'], {}).get('id') != uploaded['id']:
                            raise DeploymentError('Uploaded asset does not match refreshed release membership')
                    path.unlink()
            if 'package-index.json' not in assets:
                path = directory / 'package-index.json'
                path.write_bytes(index)
                _immutable(api)
                uploaded = api.upload_asset(release['id'], path.name, path)
                _asset(uploaded, path.name, len(index), expected[path.name]['sha256'])
                assets = _canonical_assets(api, release, expected, complete=True)
                if assets.get(path.name, {}).get('id') != uploaded['id']:
                    raise DeploymentError('Uploaded index does not match refreshed release membership')
            if release['draft']:
                _immutable(api)
                _canonical_assets(api, release, expected, complete=True)
                api.publish_release(release['id'], tag=tag)
            release_id = release['id']
            release = api.release_by_id(REPOSITORY, release_id)
            _release(release, release_id, tag)
            if release['draft'] or release.get('immutable') is not True:
                raise DeploymentError('Canonical publication did not produce an immutable release')
            _immutable(api)
            assets = _canonical_assets(api, release, expected, complete=True)
        for package in group:
            entry = package['entry']
            names = [part['name'] for part in entry['parts']] + ['package-index.json']
            results.append({'entry': entry, 'releaseId': release['id'], 'assets': [
                {'name': name, 'assetId': assets[name]['id'], 'sha256': expected[name]['sha256'],
                 'bytes': expected[name]['bytes']} for name in names]})
    return results
