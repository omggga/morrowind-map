from __future__ import annotations

import io
import copy
import hashlib
import json
import shutil
import tarfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tools.deployment.common import DeploymentError, canonical_json_bytes
from tools.deployment.dataset_packages import pack_tile_set, read_tile_sets
from tools.deployment.download_datasets import download_datasets
from tools.deployment.tests import test_dataset_packages as package_fixtures
from tools.deployment.upload_datasets import build_dataset_plan


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = package_fixtures.DatasetPackageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.public = self.fixture.public
        self.before = build_dataset_plan(public_root=self.public)
        result = self.fixture.bootstrap()
        self.lock = json.loads(Path(result['lockPath']).read_bytes())
        (self.root / 'config').mkdir()
        shutil.copyfile(result['lockPath'], self.root / 'config/dataset-releases.lock.json')
        self.calls = []

    def fetch(self, entry, part):
        self.calls.append(part['sha256'])
        path = self.fixture.output / entry['datasetId'] / entry['pyramidId'] / entry['inventorySha256'] / part['name']
        return io.BytesIO(path.read_bytes())

    def remove_tiles(self):
        for path in self.public.rglob('tiles'):
            if path.is_dir():
                shutil.rmtree(path)

    def test_source_zip_download_restores_graph_and_reuses_installed_maps(self):
        self.remove_tiles()
        result = download_datasets(repo_root=self.root, client=self)
        self.assertEqual(result['downloaded'], 1)
        self.assertEqual(build_dataset_plan(public_root=self.public), self.before)
        self.assertFalse((self.root / '.git').exists())
        result = download_datasets(repo_root=self.root, client=self)
        self.assertEqual(result['reused'], 1)
        self.assertEqual(len(self.calls), 1)

    def test_corrupt_cache_and_interrupted_part_are_replaced(self):
        self.remove_tiles()
        cache = self.root / 'cache'
        cache.mkdir()
        digest = self.lock['tileSets'][0]['parts'][0]['sha256']
        (cache / (digest + '.tar')).write_bytes(b'broken')
        (cache / (digest + '.part')).write_bytes(b'interrupted')
        download_datasets(repo_root=self.root, cache_root=cache, client=self)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(list(cache.glob('*.part')))
        self.remove_tiles()
        download_datasets(repo_root=self.root, cache_root=cache, client=self)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(build_dataset_plan(public_root=self.public), self.before)

    def test_failed_transfer_publishes_nothing_and_retry_restores_graph(self):
        self.remove_tiles()
        original = self.fetch
        for payload in (b'', b'x' * 10240, b'x' * 10241):
            with self.subTest(size=len(payload)), mock.patch.object(self, 'fetch', return_value=io.BytesIO(payload)):
                with self.assertRaises(DeploymentError):
                    download_datasets(repo_root=self.root, client=self)
            self.assertFalse(list(self.public.rglob('tiles')))
            self.assertFalse(list((self.root / 'local-data/cache').rglob('*.part')))
        class Interrupted(io.BytesIO):
            def read(self, size=-1):
                if self.tell():
                    raise OSError('interrupted signed URL must not be logged')
                return super().read(512)
        with mock.patch.object(self, 'fetch', side_effect=lambda e, p: Interrupted(original(e, p).read())):
            with self.assertRaisesRegex(DeploymentError, '^Package transfer failed; retry the download$'):
                download_datasets(repo_root=self.root, client=self)
        download_datasets(repo_root=self.root, client=self)
        self.assertEqual(build_dataset_plan(public_root=self.public), self.before)

    def test_invalid_archive_headers_are_never_installed_even_with_matching_archive_hash(self):
        entry = self.lock['tileSets'][0]
        part = entry['parts'][0]
        payload = self.fetch(entry, part).read()
        self.calls.clear()
        self.remove_tiles()
        for name, kind, mode in (('../escape', tarfile.REGTYPE, 0o644), ('/escape', tarfile.REGTYPE, 0o644),
                                 ('tiles\\escape', tarfile.REGTYPE, 0o644), ('tiles/0/0/0.webp', tarfile.SYMTYPE, 0o644),
                                 ('tiles/0/0/0.webp', tarfile.LNKTYPE, 0o644), ('tiles/0/0/0.webp', tarfile.REGTYPE, 0o755),
                                 ('tiles/0/0/0.webp', tarfile.FIFOTYPE, 0o644)):
            header = tarfile.TarInfo(name)
            header.size = 12
            header.type, header.mode = kind, mode
            damaged = header.tobuf(tarfile.USTAR_FORMAT) + payload[512:]
            changed = copy.deepcopy(self.lock)
            changed['tileSets'][0]['parts'][0]['sha256'] = hashlib.sha256(damaged).hexdigest()
            (self.root / 'config/dataset-releases.lock.json').write_bytes(canonical_json_bytes(changed))
            with self.subTest(name=name, kind=kind, mode=mode), mock.patch.object(self, 'fetch', return_value=io.BytesIO(damaged)):
                with self.assertRaisesRegex(DeploymentError, 'canonical USTAR'):
                    download_datasets(repo_root=self.root, client=self)
            self.assertFalse(list(self.public.rglob('tiles')))
            self.assertFalse(list(self.public.rglob('.download-*')))

    def test_all_maps_restore_and_retry_preserves_already_installed_map(self):
        self.fixture.add_map('z-second-map', [self.fixture.webp(24)])
        result = self.fixture.bootstrap()
        shutil.copyfile(result['lockPath'], self.root / 'config/dataset-releases.lock.json')
        before = build_dataset_plan(public_root=self.public)
        self.remove_tiles()
        original = self.fetch
        def failing(entry, part):
            if entry['datasetId'] == 'z-second-map':
                raise DeploymentError('second map unavailable')
            return original(entry, part)
        with mock.patch.object(self, 'fetch', side_effect=failing):
            with self.assertRaisesRegex(DeploymentError, 'second map unavailable'):
                download_datasets(repo_root=self.root, client=self)
        self.assertTrue((self.public / self.fixture.paths['tile'].lstrip('/')).is_file())
        result = download_datasets(repo_root=self.root, client=self)
        self.assertEqual(result['reused'], 1)
        self.assertEqual(build_dataset_plan(public_root=self.public), before)

    def test_default_restores_all_five_maps_and_ignores_abandoned_staging(self):
        for name in ('second-map', 'third-map', 'fourth-map', 'fifth-map'):
            self.fixture.add_map(name, [self.fixture.webp(24)])
        result = self.fixture.bootstrap()
        shutil.copyfile(result['lockPath'], self.root / 'config/dataset-releases.lock.json')
        before = build_dataset_plan(public_root=self.public)
        self.remove_tiles()
        abandoned = self.public / 'datasets/generated/test-dataset/.download-interrupted/tiles/broken'
        abandoned.parent.mkdir(parents=True)
        abandoned.write_bytes(b'incomplete')
        result = download_datasets(repo_root=self.root, client=self)
        self.assertEqual(result['installed'], 5)
        self.assertEqual(build_dataset_plan(public_root=self.public), before)
        self.assertEqual(download_datasets(repo_root=self.root, client=self)['reused'], 5)

    def test_corrupt_installed_tile_is_replaced_only_after_verified_download(self):
        tile = self.public / self.fixture.paths['tile'].lstrip('/')
        tile.write_bytes(b'corrupted old bytes')
        with mock.patch.object(self, 'fetch', return_value=io.BytesIO(b'broken archive')):
            with self.assertRaises(DeploymentError):
                download_datasets(repo_root=self.root, client=self)
        self.assertEqual(tile.read_bytes(), b'corrupted old bytes')
        download_datasets(repo_root=self.root, client=self)
        self.assertEqual(build_dataset_plan(public_root=self.public), self.before)

    def test_cli_restores_a_source_zip_from_verified_cache(self):
        import subprocess
        download_datasets(repo_root=self.root, client=self)
        # Populate the cache, then use the public CLI without Git or network.
        self.remove_tiles()
        download_datasets(repo_root=self.root, client=self)
        self.remove_tiles()
        result = subprocess.run(['python3', '-m', 'tools.deployment.download_datasets',
                                 '--repo-root', str(self.root), '--anonymous'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['installed'], 1)
        self.assertEqual(build_dataset_plan(public_root=self.public), self.before)

    def test_exported_commit_restores_using_its_own_lock_and_plan(self):
        from tools.deployment.git_datasets import export_revision
        from tools.deployment.tests import test_git_datasets as git_fixtures
        fixture = git_fixtures.ReleaseSnapshotTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        revision = fixture.release_fixture()
        public = fixture.root / 'exported-public'
        export_revision(repo_root=fixture.repo, revision=revision, output_public_root=public)
        def fetch(entry, part):
            return (fixture.root / 'packages' / entry['datasetId'] / entry['pyramidId'] /
                    entry['inventorySha256'] / part['name']).open('rb')
        client = mock.Mock(fetch=fetch)
        # Working-tree metadata is deliberately invalid; only the exported commit matters.
        (fixture.repo / 'config/dataset-releases.lock.json').write_text('{}')
        result = download_datasets(repo_root=fixture.repo, public_root=public,
                                   lock_path=public / 'config/dataset-releases.lock.json', client=client)
        expected = json.loads((public / 'config/dataset-upload-plan.json').read_bytes())
        self.assertEqual(result['graphSha256'], expected['graphSha256'])
        self.assertEqual(build_dataset_plan(public_root=public), expected)

    def test_multipart_extracts_every_tile_and_can_discard_cache(self):
        self.fixture.add_map('test-dataset', [self.fixture.webp(6000), self.fixture.webp(6000, b'y')])
        before = build_dataset_plan(public_root=self.public)
        tile_set, = read_tile_sets(public_root=self.public)
        entry = pack_tile_set(tile_set, generated_root=self.public / 'datasets/generated',
                              package_root=self.fixture.output, max_archive_bytes=10240)
        lock = {**self.lock, 'tileSets': [entry]}
        (self.root / 'config/dataset-releases.lock.json').write_bytes(canonical_json_bytes(lock))
        self.remove_tiles()
        result = download_datasets(repo_root=self.root, client=self, keep_cache=False)
        self.assertEqual(result['downloaded'], 2)
        self.assertEqual(build_dataset_plan(public_root=self.public), before)
        self.assertFalse(list((self.root / 'local-data/cache').rglob('*.tar')))

    def test_concurrent_installs_fetch_once_and_never_mix_files(self):
        self.remove_tiles()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: download_datasets(repo_root=self.root, client=self), range(2)))
        self.assertEqual(sum(r['installed'] for r in results), 1)
        self.assertEqual(sum(r['reused'] for r in results), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(build_dataset_plan(public_root=self.public), self.before)

    def test_cache_cannot_overlap_public_tree_or_deadlock_on_same_directory(self):
        for cache in (self.public, self.public / 'cache', self.public.parent,
                      self.public / '..' / 'public'):
            with self.subTest(cache=cache), self.assertRaisesRegex(DeploymentError, 'separate directories'):
                download_datasets(repo_root=self.root, cache_root=cache, client=self)

    def test_malformed_lock_does_not_use_network_or_fall_back_to_lfs(self):
        (self.root / 'config/dataset-releases.lock.json').write_text('{}')
        with self.assertRaises(DeploymentError):
            download_datasets(repo_root=self.root, client=self)
        self.assertFalse(self.calls)

    def test_installed_and_cache_symlinks_are_rejected(self):
        tile = self.public / self.fixture.paths['tile'].lstrip('/')
        tile.unlink()
        tile.symlink_to(self.root / 'outside')
        with self.assertRaisesRegex(DeploymentError, 'symlink'):
            download_datasets(repo_root=self.root, client=self)
        self.assertFalse(self.calls)
        tile.unlink()
        cache = self.root / 'cache'
        cache.mkdir()
        digest = self.lock['tileSets'][0]['parts'][0]['sha256']
        (cache / (digest + '.part')).symlink_to(self.root / 'outside')
        with self.assertRaisesRegex(DeploymentError, 'regular file'):
            download_datasets(repo_root=self.root, cache_root=cache, client=self)
        self.assertFalse((self.root / 'outside').exists())


if __name__ == '__main__':
    unittest.main()
