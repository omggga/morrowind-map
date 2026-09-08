"""Deterministic per-map tile packages; no network or publication side effects."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import re
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Sequence

from tools.deployment.common import (
    DeploymentError, absolute_directory, canonical_json_bytes, require_integer,
    require_mapping, require_sequence, require_sha256, require_string, safe_file,
    strict_json_object,
)
from tools.deployment.upload_datasets import (
    PlannedFile, build_dataset_plan, build_metadata_plan,
)


REPOSITORY = 'omggga/morrowind-map'
FORMAT = 'ustar-v1'
MAX_ARCHIVE_BYTES = 2_147_483_648 - 10_000_000
MAX_TILE_BYTES = 512 * 1024 * 1024
MAX_TILES = 500_000
MAX_TOTAL_BYTES = 20 * 1024 * 1024 * 1024
MAX_TILE_SETS = 100
MAX_PARTS = 999  # Leave one of GitHub's 1000 asset slots for package-index.json.
MAX_LOCK_BYTES = 32 * 1024 * 1024
RECORD_BYTES = 10240
_ID = re.compile(r'[a-z0-9]+(?:[.-][a-z0-9]+)*')
_TILE_PATH = re.compile(r'tiles/(?:0|[1-9][0-9]*)/(?:0|[1-9][0-9]*)/(?:0|[1-9][0-9]*)\.webp')


@dataclass(frozen=True)
class TileSet:
    dataset_id: str
    pyramid_id: str
    inventory_sha256: str
    tiles: tuple[PlannedFile, ...]

    @property
    def key(self) -> tuple[str, str, str]:
        return self.dataset_id, self.pyramid_id, self.inventory_sha256

    @property
    def package_path(self) -> Path:
        return Path(*self.key)

    @property
    def generated_path(self) -> Path:
        return Path(self.dataset_id) / self.inventory_sha256


def _identifier(value: object, label: str) -> str:
    result = require_string(value, label)
    if len(result) > 128 or not _ID.fullmatch(result) or result.endswith('.lock'):
        raise DeploymentError(f'{label} is not a supported Git-ref-safe identifier')
    return result


def _integer(value: object, label: str, maximum: int, minimum: int = 1) -> int:
    result = require_integer(value, label, minimum=minimum)
    if result > maximum:
        raise DeploymentError(f'{label} exceeds {maximum}')
    return result


def _object(value: object, keys: set[str], label: str) -> dict[str, Any]:
    result = dict(require_mapping(value, label))
    if set(result) != keys:
        raise DeploymentError(f'{label} has missing or unexpected fields')
    return result


def release_tag(key: tuple[str, str, str]) -> str:
    dataset_id, pyramid_id, inventory = key
    return '/'.join(('tiles-v1', _identifier(dataset_id, 'datasetId'),
                     _identifier(pyramid_id, 'pyramidId'), require_sha256(inventory, 'inventorySha256')))


def _entry_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return entry['datasetId'], entry['pyramidId'], entry['inventorySha256']


def parse_lock(payload: bytes) -> dict[str, Any]:
    """Validate the transport schema plus identity, uniqueness and part ordering."""
    if len(payload) > MAX_LOCK_BYTES:
        raise DeploymentError('Transport lock exceeds its byte limit')
    try:
        payload.decode('utf-8', errors='strict')
    except UnicodeDecodeError as error:
        raise DeploymentError('Transport lock must be UTF-8 JSON') from error
    lock = _object(strict_json_object(payload, 'transport lock'),
                   {'schemaVersion', 'repository', 'tileSets'}, 'transport lock')
    if type(lock['schemaVersion']) is not int or lock['schemaVersion'] != 1:
        raise DeploymentError('Unsupported transport lock schemaVersion')
    if lock['repository'] != REPOSITORY:
        raise DeploymentError('Transport lock must use the canonical repository')
    entries = require_sequence(lock['tileSets'], 'tileSets')
    if not 1 <= len(entries) <= MAX_TILE_SETS:
        raise DeploymentError('Transport lock tileSets count is out of bounds')
    identities: set[tuple[str, str]] = set()
    total_tiles = total_bytes = 0
    for raw in entries:
        entry = _object(raw, {'datasetId', 'pyramidId', 'inventorySha256', 'format', 'releaseTag', 'parts'}, 'tile set')
        key = (_identifier(entry['datasetId'], 'datasetId'),
               _identifier(entry['pyramidId'], 'pyramidId'),
               require_sha256(entry['inventorySha256'], 'inventorySha256'))
        if key[:2] in identities:
            raise DeploymentError('Duplicate tile set identity')
        identities.add(key[:2])
        if entry['format'] != FORMAT or entry['releaseTag'] != release_tag(key):
            raise DeploymentError('Tile set format or releaseTag differs from its identity')
        parts = require_sequence(entry['parts'], 'parts')
        if not 1 <= len(parts) <= MAX_PARTS:
            raise DeploymentError('Package part count is out of bounds')
        for number, raw_part in enumerate(parts, 1):
            part = _object(raw_part, {'name', 'sha256', 'bytes', 'tileCount', 'unpackedBytes'}, 'part')
            if part['name'] != f'tiles-{number:04d}.tar':
                raise DeploymentError('Package part names must be contiguous and ordered')
            require_sha256(part['sha256'], 'part.sha256')
            size = _integer(part['bytes'], 'part.bytes', MAX_ARCHIVE_BYTES, RECORD_BYTES)
            if size % RECORD_BYTES:
                raise DeploymentError('Part bytes must include complete USTAR record padding')
            total_tiles += _integer(part['tileCount'], 'part.tileCount', MAX_TILES)
            unpacked = _integer(part['unpackedBytes'], 'part.unpackedBytes', MAX_ARCHIVE_BYTES)
            if unpacked >= size:
                raise DeploymentError('Part unpackedBytes leaves no space for tar headers')
            total_bytes += unpacked
    if total_tiles > MAX_TILES or total_bytes > MAX_TOTAL_BYTES:
        raise DeploymentError('Transport lock exceeds the trusted graph limits')
    return lock


def _tile_sets(plan: dict[str, Any]) -> tuple[TileSet, ...]:
    """Consume the existing planner's verified metadata, not an alternate inventory."""
    if len(plan['files']) > MAX_TILES or plan['totalBytes'] > MAX_TOTAL_BYTES:
        raise DeploymentError('Dataset graph exceeds package limits')
    result = []
    seen: set[tuple[str, str]] = set()
    for dataset in plan['datasets']:
        if dataset['staticRasters']:
            raise DeploymentError('ustar-v1 packages support tile pyramids, not static rasters')
        for pyramid in dataset['tilePyramids']:
            dataset_id = _identifier(dataset['datasetId'], 'datasetId')
            pyramid_id = _identifier(pyramid['id'], 'pyramidId')
            identity = dataset_id, pyramid_id
            if identity in seen:
                raise DeploymentError('Duplicate active pyramid identity')
            seen.add(identity)
            inventory = require_sha256(pyramid['inventorySha256'], 'inventorySha256')
            prefix = f'{dataset_id}/{inventory}/'
            tiles = tuple(PlannedFile(f['path'][len(prefix):], f['bytes'], f['sha256'])
                          for f in plan['files'] if f['path'].startswith(prefix))
            if len(tiles) != pyramid['tileCount'] or sum(t.byte_count for t in tiles) != pyramid['totalBytes']:
                raise DeploymentError('Package tile set differs from the verified inventory')
            for tile in tiles:
                _tile_header(tile)
            result.append(TileSet(dataset_id, pyramid_id, inventory, tuple(sorted(tiles, key=lambda t: t.path))))
    if not 1 <= len(result) <= MAX_TILE_SETS:
        raise DeploymentError('Active tile set count is out of bounds')
    return tuple(sorted(result, key=lambda item: item.key))


def read_tile_sets(*, public_root: Path) -> tuple[TileSet, ...]:
    return _tile_sets(build_metadata_plan(public_root=public_root))


def validate_lock(lock: dict[str, Any], tile_sets: Sequence[TileSet]) -> None:
    """Bind every descriptor to the selected snapshot before touching an archive."""
    lock = parse_lock(canonical_json_bytes(lock))
    actual = {_entry_key(entry): entry for entry in lock['tileSets']}
    expected = {tile_set.key: tile_set for tile_set in tile_sets}
    if set(actual) != set(expected):
        raise DeploymentError('Transport lock has missing, unused or mismatched inventories')
    for key, tile_set in expected.items():
        offset = 0
        for part in actual[key]['parts']:
            count = part['tileCount']
            tiles = tile_set.tiles[offset:offset + count]
            if len(tiles) != count or sum(t.byte_count for t in tiles) != part['unpackedBytes']:
                raise DeploymentError('Package part count/bytes differ from the committed inventory')
            if archive_size(tiles) != part['bytes']:
                raise DeploymentError('Package part tar length differs from the committed inventory')
            offset += count
        if offset != len(tile_set.tiles):
            raise DeploymentError('Package parts do not cover the full inventory')


def _tile_header(tile: PlannedFile) -> bytes:
    if not _TILE_PATH.fullmatch(tile.path):
        raise DeploymentError('Only canonical tiles/z/x/y.webp paths can be packaged')
    _integer(tile.byte_count, 'tile bytes', MAX_TILE_BYTES)
    require_sha256(tile.sha256, 'tile SHA-256')
    info = tarfile.TarInfo(tile.path)
    info.mode = 0o644
    info.size = tile.byte_count
    info.uid = info.gid = info.mtime = 0
    info.uname = info.gname = ''
    try:
        return info.tobuf(format=tarfile.USTAR_FORMAT, encoding='ascii', errors='strict')
    except (ValueError, UnicodeError) as error:
        raise DeploymentError('Tile path does not fit the USTAR encoding') from error


def _padded(size: int, block: int) -> int:
    return ((size + block - 1) // block) * block


def archive_size(tiles: Sequence[PlannedFile]) -> int:
    return _padded(sum(512 + _padded(t.byte_count, 512) for t in tiles) + 1024, RECORD_BYTES)


def plan_parts(tiles: Sequence[PlannedFile], *, max_archive_bytes: int = MAX_ARCHIVE_BYTES) -> tuple[tuple[PlannedFile, ...], ...]:
    """Split at whole files; a smaller bound is useful for fixture verification."""
    _integer(max_archive_bytes, 'archive limit', MAX_ARCHIVE_BYTES, RECORD_BYTES)
    if not tiles or len(tiles) > MAX_TILES:
        raise DeploymentError('Package inventory count is out of bounds')
    parts: list[tuple[PlannedFile, ...]] = []
    current: list[PlannedFile] = []
    used = 0
    previous = ''
    for tile in tiles:
        _tile_header(tile)
        if tile.path <= previous:
            raise DeploymentError('Package inventory paths must be unique and sorted')
        previous = tile.path
        cost = 512 + _padded(tile.byte_count, 512)
        if _padded(cost + 1024, RECORD_BYTES) > max_archive_bytes:
            raise DeploymentError('A single tile exceeds the finished archive limit')
        if current and _padded(used + cost + 1024, RECORD_BYTES) > max_archive_bytes:
            parts.append(tuple(current))
            current, used = [], 0
        current.append(tile)
        used += cost
    parts.append(tuple(current))
    if len(parts) > MAX_PARTS:
        raise DeploymentError('Too many package parts for one GitHub release')
    return tuple(parts)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _copy_tile(source: BinaryIO, target: BinaryIO | None, tile: PlannedFile) -> None:
    remaining = tile.byte_count
    digest = hashlib.sha256()
    header = b''
    while remaining:
        block = source.read(min(1024 * 1024, remaining))
        if not block:
            raise DeploymentError(f'Truncated tile: {tile.path}')
        if len(header) < 12:
            header = (header + block)[:12]
        digest.update(block)
        if target is not None:
            target.write(block)
        remaining -= len(block)
    if digest.hexdigest() != tile.sha256:
        raise DeploymentError(f'Tile SHA-256 differs: {tile.path}')
    if len(header) < 12 or header[:4] != b'RIFF' or header[8:12] != b'WEBP':
        raise DeploymentError(f'Tile is not WebP: {tile.path}')
    if int.from_bytes(header[4:8], 'little') + 8 != tile.byte_count:
        raise DeploymentError(f'WebP RIFF size differs: {tile.path}')


def _real_directory(path: Path) -> Path:
    """Create an output directory without following any existing symlink component."""
    path = Path(os.path.abspath(path))
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise DeploymentError(f'Package output contains a symlink: {parent}')
        if parent.exists() and not parent.is_dir():
            raise DeploymentError(f'Package output is not a directory: {parent}')
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_lock(path: Path) -> dict[str, Any]:
    file = safe_file(path.parent, Path(path.name), 'transport lock')
    if file.stat().st_size > MAX_LOCK_BYTES:
        raise DeploymentError('Transport lock exceeds its byte limit')
    return parse_lock(file.read_bytes())


def _write_json(path: Path, value: object) -> None:
    _real_directory(path.parent)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise DeploymentError('JSON output must be a regular file')
    fd, name = tempfile.mkstemp(prefix='.package-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(canonical_json_bytes(value))
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _lock(entries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {'schemaVersion': 1, 'repository': REPOSITORY,
            'tileSets': sorted(entries, key=_entry_key)}


def _verify_entry(tile_set: TileSet, entry: dict[str, Any], package_root: Path) -> None:
    validate_lock(_lock([entry]), [tile_set])
    offset = 0
    for part in entry['parts']:
        path = safe_file(package_root, tile_set.package_path / part['name'], 'package archive')
        if path.stat().st_size != part['bytes'] or _hash_file(path) != part['sha256']:
            raise DeploymentError('Package archive length or SHA-256 differs from the lock')
        tiles = tile_set.tiles[offset:offset + part['tileCount']]
        with path.open('rb') as source:
            for tile in tiles:
                if source.read(512) != _tile_header(tile):
                    raise DeploymentError('Archive member is not the expected canonical USTAR tile')
                _copy_tile(source, None, tile)
                padding = _padded(tile.byte_count, 512) - tile.byte_count
                if source.read(padding) != b'\0' * padding:
                    raise DeploymentError('Archive tile padding is invalid')
            tail = part['bytes'] - source.tell()
            if source.read(tail + 1) != b'\0' * tail:
                raise DeploymentError('Archive end records or trailing bytes are invalid')
        offset += len(tiles)


def verify_packages(*, public_root: Path, package_root: Path, lock_path: Path) -> dict[str, Any]:
    """Verify local archives against metadata without installing or extracting files."""
    tile_sets = read_tile_sets(public_root=public_root)
    lock = _read_lock(lock_path)
    validate_lock(lock, tile_sets)
    entries = {_entry_key(entry): entry for entry in lock['tileSets']}
    package_root = absolute_directory(package_root, 'package root')
    for tile_set in tile_sets:
        _verify_entry(tile_set, entries[tile_set.key], package_root)
    return {'tileSets': len(tile_sets), 'parts': sum(len(e['parts']) for e in entries.values()), 'verified': True}


def pack_tile_set(tile_set: TileSet, *, generated_root: Path, package_root: Path,
                  max_archive_bytes: int = MAX_ARCHIVE_BYTES) -> dict[str, Any]:
    """Write a complete immutable local package before exposing its descriptor."""
    tag = release_tag(tile_set.key)
    parts = plan_parts(tile_set.tiles, max_archive_bytes=max_archive_bytes)
    package_root = _real_directory(package_root)
    destination = package_root / tile_set.package_path
    _real_directory(destination.parent)
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise DeploymentError('Existing package is not a real directory')
        existing = _read_lock(destination / 'package-index.json')
        validate_lock(existing, [tile_set])
        _verify_entry(tile_set, existing['tileSets'][0], package_root)
        return existing['tileSets'][0]
    needed = sum(archive_size(part) for part in parts)
    if shutil.disk_usage(package_root).free < needed:
        raise DeploymentError('Insufficient free space for the map package')
    entry = {'datasetId': tile_set.dataset_id, 'pyramidId': tile_set.pyramid_id,
             'inventorySha256': tile_set.inventory_sha256, 'format': FORMAT,
             'releaseTag': tag, 'parts': []}
    with tempfile.TemporaryDirectory(prefix='.pack-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        for number, tiles in enumerate(parts, 1):
            name = f'tiles-{number:04d}.tar'
            path = stage / name
            with path.open('wb') as output:
                for tile in tiles:
                    output.write(_tile_header(tile))
                    source_path = safe_file(generated_root, tile_set.generated_path / tile.path, 'ready tile')
                    with source_path.open('rb') as source:
                        _copy_tile(source, output, tile)
                        if source.read(1):
                            raise DeploymentError('Ready tile grew during packaging')
                    output.write(b'\0' * (_padded(tile.byte_count, 512) - tile.byte_count))
                output.write(b'\0' * (archive_size(tiles) - output.tell()))
            size = path.stat().st_size
            if size != archive_size(tiles) or size > max_archive_bytes:
                raise DeploymentError('Completed archive exceeds its planned byte limit')
            entry['parts'].append({'name': name, 'sha256': _hash_file(path), 'bytes': size,
                                   'tileCount': len(tiles), 'unpackedBytes': sum(t.byte_count for t in tiles)})
        validate_lock(_lock([entry]), [tile_set])
        (stage / 'package-index.json').write_bytes(canonical_json_bytes(_lock([entry])))
        os.rename(stage, destination)
    _verify_entry(tile_set, entry, package_root)
    return entry


def pack_datasets(*, repo_root: Path, selector: str, bootstrap: bool = False) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=True)
    public = root / 'apps/web/public'
    if bootstrap and selector != 'all':
        raise DeploymentError('Bootstrap packs all active maps; use selector all')
    active_lock = root / 'config/dataset-releases.lock.json'
    if not bootstrap and not active_lock.exists():
        raise DeploymentError('No active transport lock; use pack all --bootstrap to write ignored descriptors')
    plan = build_dataset_plan(public_root=public)
    tile_sets = _tile_sets(plan)
    selected = set()
    for dataset in plan['datasets']:
        manifest_path = safe_file(public, Path(dataset['manifest']['url'].lstrip('/')), 'manifest')
        manifest = strict_json_object(manifest_path.read_bytes(), 'manifest')
        if selector in ('all', dataset['datasetId'], manifest.get('mapKey')):
            selected.add(dataset['datasetId'])
    if not selected:
        raise DeploymentError(f'No active map matches {selector!r}')
    if selector != 'all' and len(selected) != 1:
        raise DeploymentError('Map selector is ambiguous')
    # Locking is local and does not activate an application dataset or publish a release.
    output = _real_directory(root / 'local-data/packages')
    lock_file = output / '.pack.lock'
    if lock_file.is_symlink():
        raise DeploymentError('Package lock must not be a symlink')
    with lock_file.open('a') as process_lock:
        fcntl.flock(process_lock, fcntl.LOCK_EX)
        previous = {} if bootstrap else {_entry_key(e): e for e in _read_lock(active_lock)['tileSets']}
        entries = []
        packed = reused = 0
        for tile_set in tile_sets:
            old = previous.get(tile_set.key)
            if old is not None:
                validate_lock(_lock([old]), [tile_set])
                entries.append(old)
                reused += 1
            elif tile_set.dataset_id in selected:
                entries.append(pack_tile_set(tile_set, generated_root=public / 'datasets/generated', package_root=output))
                packed += 1
            else:
                raise DeploymentError('Unselected map has no matching package; pack all changed maps')
        lock = _lock(entries)
        validate_lock(lock, tile_sets)
        target = output / 'dataset-releases.lock.json' if bootstrap else active_lock
        _write_json(target, lock)
        return {'lockPath': str(target), 'tileSets': len(tile_sets), 'packed': packed, 'reused': reused}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest='command', required=True)
    pack = subcommands.add_parser('pack', help='Pack ready map tiles without publishing')
    pack.add_argument('map', help='An active map key/dataset ID, or all')
    pack.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    pack.add_argument('--bootstrap', action='store_true', help='Pack all maps and write only ignored descriptors')
    verify = subcommands.add_parser('verify', help='Verify packages against a complete snapshot')
    verify.add_argument('--public-root', type=Path, default=Path('apps/web/public'))
    verify.add_argument('--package-root', type=Path, default=Path('local-data/packages'))
    verify.add_argument('--lock', type=Path, default=Path('config/dataset-releases.lock.json'))
    args = parser.parse_args(argv)
    try:
        if args.command == 'pack':
            result = pack_datasets(repo_root=args.repo_root, selector=args.map, bootstrap=args.bootstrap)
        else:
            result = verify_packages(public_root=args.public_root, package_root=args.package_root, lock_path=args.lock)
    except (DeploymentError, OSError, ValueError) as error:
        print(f'Dataset packages: {error}', file=sys.stderr)
        return 1
    print(canonical_json_bytes(result).decode(), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
