"""Restore every active map from pinned Release archives without Git or a renderer."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.client
import os
import shutil
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

from tools.deployment.common import DeploymentError, canonical_json_bytes, safe_file
from tools.deployment.dataset_github import GitHubClient
from tools.deployment.dataset_packages import (
    TileSet, _copy_tile, _entry_key, _hash_file, _read_lock, _real_directory,
    read_part, read_tile_sets, validate_lock,
)
from tools.deployment.upload_datasets import build_dataset_plan


@contextmanager
def _exclusive(path: Path):
    # Directory locks keep synchronization files out of the served public tree.
    _real_directory(path)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _installed(tile_set: TileSet, generated: Path) -> bool:
    root = generated / tile_set.generated_path
    tile_root = root / 'tiles'
    if not tile_root.exists() and not tile_root.is_symlink():
        return False
    # Reject symlinks instead of treating them as damaged cache contents.
    for parent in (tile_root, *tile_root.parents):
        if parent.is_symlink():
            raise DeploymentError('Installed tile tree contains a symlink')
    if not tile_root.is_dir():
        raise DeploymentError('Installed tile root must be a directory')
    expected = {tile.path for tile in tile_set.tiles}
    actual = set()
    for directory, names, files in os.walk(tile_root, followlinks=False):
        for name in (*names, *files):
            path = Path(directory) / name
            if path.is_symlink():
                raise DeploymentError('Installed tile tree contains a symlink')
        for name in files:
            path = Path(directory) / name
            if not path.is_file():
                raise DeploymentError('Installed tile tree contains a special file')
            actual.add(path.relative_to(root).as_posix())
            if len(actual) > len(expected):
                return False
    if actual != expected:
        return False
    for tile in tile_set.tiles:
        path = safe_file(root, Path(tile.path), 'installed tile')
        if path.stat().st_size != tile.byte_count:
            return False
        try:
            with path.open('rb') as source:
                _copy_tile(source, None, tile)
        except DeploymentError:
            return False
    return True


def _cached_part(cache: Path, entry: dict, part: dict, client) -> tuple[Path, bool]:
    target = cache / (part['sha256'] + '.tar')
    partial = cache / (part['sha256'] + '.part')
    for path in (target, partial):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise DeploymentError('Archive cache entry must be a regular file')
    if target.exists():
        if target.stat().st_size == part['bytes'] and _hash_file(target) == part['sha256']:
            return target, False
        target.unlink()
    partial.unlink(missing_ok=True)
    if shutil.disk_usage(cache).free < part['bytes']:
        raise DeploymentError('Insufficient free space for the package archive')
    count = 0
    digest = hashlib.sha256()
    try:
        with client.fetch(entry, part) as response, partial.open('xb') as output:
            while block := response.read(min(1024 * 1024, part['bytes'] - count + 1)):
                count += len(block)
                if count > part['bytes']:
                    raise DeploymentError('Downloaded archive exceeds its locked byte limit')
                digest.update(block)
                output.write(block)
        if count != part['bytes'] or digest.hexdigest() != part['sha256']:
            raise DeploymentError('Downloaded archive length or SHA-256 differs from the lock')
        os.replace(partial, target)
    except (OSError, EOFError, http.client.HTTPException):
        raise DeploymentError('Package transfer failed; retry the download') from None
    finally:
        partial.unlink(missing_ok=True)
    return target, True


def _install_map(tile_set: TileSet, entry: dict, generated: Path, cache: Path,
                 client, keep_cache: bool) -> int:
    destination = generated / tile_set.generated_path
    _real_directory(destination)
    needed = sum(tile.byte_count for tile in tile_set.tiles) + max(p['bytes'] for p in entry['parts'])
    if shutil.disk_usage(destination).free < needed:
        raise DeploymentError('Insufficient free space to verify and install the map')
    downloaded = 0
    # A killed process may leave this directory behind. Keep it outside the
    # active inventory prefix so a later retry can still validate that prefix.
    with tempfile.TemporaryDirectory(prefix='.download-', dir=destination.parent) as raw:
        staging = Path(raw)
        offset = 0
        for part in entry['parts']:
            path, fetched = _cached_part(cache, entry, part, client)
            downloaded += int(fetched)
            tiles = tile_set.tiles[offset:offset + part['tileCount']]
            read_part(path, tiles, part, output_root=staging)
            offset += len(tiles)
            if not keep_cache:
                path.unlink()
        target = destination / 'tiles'
        # Retain an existing incomplete tree until the entire replacement verifies.
        # Valid trees have already been reused; other content-addressed versions
        # and other maps are never removed.
        backup = staging / 'previous-tiles'
        if target.exists():
            os.rename(target, backup)
        try:
            os.rename(staging / 'tiles', target)
        except OSError:
            if backup.exists():
                os.rename(backup, target)
            raise
    return downloaded


def download_datasets(*, repo_root: Path, cache_root: Path | None = None,
                      public_root: Path | None = None, lock_path: Path | None = None,
                      client=None, anonymous: bool = False, keep_cache: bool = True) -> dict:
    root = Path(repo_root).resolve(strict=True)
    public = Path(public_root) if public_root is not None else root / 'apps/web/public'
    public = _real_directory(public)
    lock_path = Path(lock_path) if lock_path is not None else root / 'config/dataset-releases.lock.json'
    if not lock_path.exists() and not lock_path.is_symlink():
        raise DeploymentError('No active Release lock; restore config/dataset-releases.lock.json from this snapshot before downloading')
    # Both the destination and shared cache are serialized, even if callers choose
    # different caches or several source-ZIP workspaces share one cache.
    cache = Path(cache_root) if cache_root is not None else root / 'local-data/cache/dataset-releases'
    cache = Path(os.path.abspath(cache))
    if public == cache or public in cache.parents or cache in public.parents:
        raise DeploymentError('Archive cache and public tree must be separate directories')
    cache = _real_directory(cache)
    with ExitStack() as locks:
        # Consistent ordering also handles callers that share several directories.
        for directory in sorted((public, cache)):
            locks.enter_context(_exclusive(directory))
        tile_sets = read_tile_sets(public_root=public)
        lock = _read_lock(lock_path)
        validate_lock(lock, tile_sets)
        entries = {_entry_key(e): e for e in lock['tileSets']}
        generated = public / 'datasets/generated'
        _real_directory(generated)
        client = client if client is not None else GitHubClient(anonymous=anonymous)
        reused = installed = downloaded = 0
        for tile_set in tile_sets:
            if _installed(tile_set, generated):
                reused += 1
                continue
            downloaded += _install_map(tile_set, entries[tile_set.key], generated, cache, client, keep_cache)
            installed += 1
        plan = build_dataset_plan(public_root=public)
        return {'graphSha256': plan['graphSha256'], 'tileSets': len(tile_sets),
                'installed': installed, 'reused': reused, 'downloaded': downloaded}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--public-root', type=Path, help='Metadata destination for an exported snapshot')
    parser.add_argument('--lock', type=Path, help='The selected snapshot transport lock')
    parser.add_argument('--cache-root', type=Path)
    parser.add_argument('--anonymous', action='store_true', help='Never read GitHub credentials')
    parser.add_argument('--discard-cache', action='store_true', help='Discard each archive after verified extraction')
    args = parser.parse_args(argv)
    try:
        result = download_datasets(repo_root=args.repo_root, public_root=args.public_root,
                                   lock_path=args.lock, cache_root=args.cache_root,
                                   anonymous=args.anonymous, keep_cache=not args.discard_cache)
    except (DeploymentError, OSError, ValueError) as error:
        # Transport exceptions may contain signed URLs; expose only our own messages.
        message = str(error) if isinstance(error, DeploymentError) else 'Dataset restore failed; check local paths and retry'
        print(f'Dataset download: {message}', file=sys.stderr)
        return 1
    print(canonical_json_bytes(result).decode(), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
