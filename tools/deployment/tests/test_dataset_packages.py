from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from tools.deployment.common import DeploymentError, canonical_json_bytes
from tools.deployment.tests.fixtures import TILE_HASH, build_runtime, descriptor, write_dist
from tools.deployment.upload_datasets import PlannedFile, build_dataset_plan, build_metadata_plan
from tools.deployment.dataset_packages import (
    MAX_ARCHIVE_BYTES,
    product_part_name,
    archive_size,
    main,
    pack_datasets,
    pack_tile_set,
    parse_lock,
    plan_parts,
    read_tile_sets,
    validate_lock,
    verify_packages,
)


class DatasetPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.public = self.root / 'apps/web/public'
        self.paths = write_dist(self.public)
        self.output = self.root / 'local-data/packages'

    def bootstrap(self) -> dict:
        return pack_datasets(repo_root=self.root, selector='all', bootstrap=True)

    def add_map(self, dataset_id: str, payloads: list[bytes]) -> dict[str, str]:
        """Bind a synthetic map's metadata to its independently supplied tile bytes."""
        inventory_id = hashlib.sha256(b''.join(payloads)).hexdigest()
        runtime, paths = build_runtime()
        def replace(value: str) -> str:
            return value.replace('test-dataset', dataset_id).replace(TILE_HASH, inventory_id)
        runtime = {replace(url): payload if url.endswith('.webp') else replace(payload.decode()).encode()
                   for url, payload in runtime.items()}
        paths = {key: replace(value) for key, value in paths.items()}
        records = []
        for y, payload in enumerate(payloads):
            relative = f'tiles/0/0/{y}.webp'
            runtime[f'/datasets/generated/{dataset_id}/{inventory_id}/{relative}'] = payload
            records.append({'path': relative, 'z': 0, 'x': 0, 'y': y,
                            'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()})
        inventory = b''.join(canonical_json_bytes(r) for r in records)
        runtime[paths['tilesInventory']] = inventory
        quality = json.loads(runtime[paths['quality']])
        quality['artifacts']['tiles'] = {'path': 'tiles.ndjson', 'bytes': len(inventory),
                                        'sha256': hashlib.sha256(inventory).hexdigest()}
        quality['gates']['inventory'].update(tileCount=len(payloads), totalBytes=sum(map(len, payloads)),
                                             inventoryFileSha256=hashlib.sha256(inventory).hexdigest())
        runtime[paths['quality']] = canonical_json_bytes(quality)
        assets = json.loads(runtime[paths['mapAssets']])
        pyramid = assets['tilePyramids'][0]
        pyramid['qualityReport'] = descriptor(paths['quality'], runtime[paths['quality']])
        pyramid['integrity'].update(tileCount=len(payloads), totalBytes=sum(map(len, payloads)),
                                    inventoryFileSha256=hashlib.sha256(inventory).hexdigest())
        runtime[paths['mapAssets']] = canonical_json_bytes(assets)
        manifest = json.loads(runtime[paths['manifest']])
        audit = json.loads(runtime[paths['catalogAudit']])
        for key, name in [('locations', 'locations'), ('locale', 'english')]:
            binding = audit['integrity']['artifacts'][name]
            binding.update(bytes=len(runtime[paths[key]]), sha256=hashlib.sha256(runtime[paths[key]]).hexdigest())
        runtime[paths['catalogAudit']] = canonical_json_bytes(audit)
        for key in ['locations', 'catalogAudit']:
            manifest['artifacts'][key] = descriptor(paths[key], runtime[paths[key]])
        manifest['artifacts']['locales'][0]['artifact'] = descriptor(paths['locale'], runtime[paths['locale']])
        manifest['artifacts']['tiles']['sha256'] = hashlib.sha256(runtime[paths['mapAssets']]).hexdigest()
        manifest['mapKey'] = dataset_id
        runtime[paths['manifest']] = canonical_json_bytes(manifest)
        index_path = self.public / 'datasets/index.json'
        index = json.loads(index_path.read_bytes())
        index['datasets'] = [e for e in index['datasets'] if e['datasetId'] != dataset_id]
        index['datasets'].append({'datasetId': dataset_id, 'manifestUrl': paths['manifest'],
                                  'order': len(index['datasets'])})
        runtime['/datasets/index.json'] = canonical_json_bytes(index)
        for url, payload in runtime.items():
            target = self.public / url.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        return paths

    @staticmethod
    def webp(size: int, fill: bytes = b'x') -> bytes:
        return b'RIFF' + (size - 8).to_bytes(4, 'little') + b'WEBP' + fill * (size - 12)

    def test_metadata_plan_preserves_graph_without_tile_payloads(self) -> None:
        ready = build_dataset_plan(public_root=self.public)
        tile = self.public / self.paths['tile'].lstrip('/')
        tile.unlink()
        self.assertEqual(build_metadata_plan(public_root=self.public), ready)
        with self.assertRaises(DeploymentError):
            build_dataset_plan(public_root=self.public)

    def test_bootstrap_is_deterministic_and_never_creates_active_lock(self) -> None:
        first = self.bootstrap()
        archive = next(self.output.rglob('tiles-0001.tar'))
        original = archive.read_bytes()
        tile = self.public / self.paths['tile'].lstrip('/')
        os.utime(tile, (123456789, 123456789))
        tile.chmod(0o600)
        shutil.rmtree(self.output)
        second = self.bootstrap()
        self.assertEqual(first, second)
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(len(original), 10240)
        lock = json.loads((self.output / 'dataset-releases.lock.json').read_bytes())
        part = lock['tileSets'][0]['parts'][0]
        self.assertEqual(part['sha256'], hashlib.sha256(original).hexdigest())
        self.assertFalse((self.root / 'config/dataset-releases.lock.json').exists())
        with tarfile.open(archive) as packed:
            members = packed.getmembers()
            self.assertEqual([m.name for m in members], ['tiles/0/0/0.webp'])
            member = members[0]
            self.assertEqual((member.mode, member.uid, member.gid, member.mtime), (0o644, 0, 0, 0))
            self.assertEqual((member.uname, member.gname, member.pax_headers), ('', '', {}))
            self.assertEqual(packed.extractfile(member).read(), tile.read_bytes())
        verify_packages(public_root=self.public, package_root=self.output,
                        lock_path=self.output / 'dataset-releases.lock.json')

    def test_archive_tampering_and_truncation_fail_verification(self) -> None:
        self.bootstrap()
        archive = next(self.output.rglob('tiles-0001.tar'))
        original = archive.read_bytes()
        for payload in (original[:-1], original[:512] + b'X' + original[513:]):
            with self.subTest(size=len(payload)):
                archive.write_bytes(payload)
                with self.assertRaises(DeploymentError):
                    verify_packages(public_root=self.public, package_root=self.output,
                                    lock_path=self.output / 'dataset-releases.lock.json')

    def test_lock_rejects_unknown_fields_unsafe_ids_and_identity_mismatch(self) -> None:
        self.bootstrap()
        lock = json.loads((self.output / 'dataset-releases.lock.json').read_bytes())
        invalid = []
        changed = copy.deepcopy(lock); changed['unexpected'] = True; invalid.append(changed)
        changed = copy.deepcopy(lock); changed['schemaVersion'] = True; invalid.append(changed)
        changed = copy.deepcopy(lock); changed['tileSets'][0]['datasetId'] = '../escape'; invalid.append(changed)
        changed = copy.deepcopy(lock); changed['tileSets'][0]['releaseTag'] = 'latest'; invalid.append(changed)
        changed = copy.deepcopy(lock); changed['tileSets'] *= 2; invalid.append(changed)
        changed = copy.deepcopy(lock); changed['tileSets'][0]['parts'][0]['bytes'] = MAX_ARCHIVE_BYTES + 1; invalid.append(changed)
        changed = copy.deepcopy(lock); changed['tileSets'][0]['parts'][0]['name'] = 'tiles-0002.tar'; invalid.append(changed)
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(DeploymentError):
                    parse_lock(canonical_json_bytes(candidate))
        with self.assertRaises(DeploymentError):
            parse_lock(json.dumps(lock).encode('utf-16'))
        with self.assertRaises(DeploymentError):
            parse_lock(canonical_json_bytes(lock).replace(b'"schemaVersion":1', b'"schemaVersion":1,"schemaVersion":1'))

    def test_untracked_inputs_and_stale_snapshots_do_not_enter_archive(self) -> None:
        inputs = self.root / 'local-data/inputs'
        inputs.mkdir(parents=True)
        (inputs / 'source.esm').write_bytes(b'private fixture')
        self.bootstrap()
        self.assertEqual(len(list(self.output.rglob('*.tar'))), 1)
        with tarfile.open(next(self.output.rglob('*.tar'))) as packed:
            self.assertEqual(packed.getnames(), ['tiles/0/0/0.webp'])

    def test_bad_ready_tile_stops_before_any_output(self) -> None:
        (self.public / self.paths['tile'].lstrip('/')).write_bytes(b'corrupt')
        with self.assertRaises(DeploymentError):
            self.bootstrap()
        self.assertFalse(self.output.exists())

    def test_active_lock_requires_bootstrap_and_matching_inventory(self) -> None:
        with self.assertRaisesRegex(DeploymentError, 'bootstrap'):
            pack_datasets(repo_root=self.root, selector='all')
        self.bootstrap()
        active = self.root / 'config/dataset-releases.lock.json'
        active.parent.mkdir()
        active.write_bytes((self.output / 'dataset-releases.lock.json').read_bytes())
        before = active.read_bytes()
        pack_datasets(repo_root=self.root, selector='test-dataset')
        self.assertEqual(before, active.read_bytes())

    def test_inventory_parts_reserve_ustar_end_padding(self) -> None:
        tile_set = read_tile_sets(public_root=self.public)[0]
        # A 12-byte tile occupies 512 header + 512 payload + 1024 end bytes,
        # rounded to one 10240-byte tar record, not just the payload length.
        self.assertEqual(len(plan_parts(tile_set.tiles, max_archive_bytes=10240)), 1)
        with self.assertRaises(DeploymentError):
            plan_parts(tile_set.tiles, max_archive_bytes=10239)

    def test_multipart_archives_extract_independently_with_complete_coverage(self) -> None:
        self.add_map('split-map', [self.webp(6000, b'a'), self.webp(6000, b'b')])
        tile_set = next(t for t in read_tile_sets(public_root=self.public) if t.dataset_id == 'split-map')
        entry = pack_tile_set(tile_set, generated_root=self.public / 'datasets/generated',
                              package_root=self.output, max_archive_bytes=10240)
        self.assertEqual([p['name'] for p in entry['parts']], ['tiles-0001.tar', 'tiles-0002.tar'])
        self.assertEqual([p['bytes'] for p in entry['parts']], [10240, 10240])
        names = []
        for part in entry['parts']:
            with tarfile.open(self.output / tile_set.package_path / part['name']) as archive:
                self.assertEqual(len(archive.getmembers()), 1)
                member = archive.getmembers()[0]
                names.append(member.name)
                self.assertEqual(len(archive.extractfile(member).read()), 6000)
        self.assertEqual(names, ['tiles/0/0/0.webp', 'tiles/0/0/1.webp'])

    def test_size_boundary_is_near_two_gib_without_allocating_large_files(self) -> None:
        # Four 512 MiB tiles cross the agreed ceiling once tar overhead is included.
        tiles = [PlannedFile(f'tiles/0/0/{i}.webp', 512 * 1024 * 1024, 'a' * 64) for i in range(4)]
        parts = plan_parts(tiles)
        self.assertEqual([len(part) for part in parts], [3, 1])
        self.assertTrue(all(archive_size(part) <= 2_137_483_648 for part in parts))
        with self.assertRaises(DeploymentError):
            plan_parts(tiles, max_archive_bytes=2_147_483_648)

    def test_one_map_update_preserves_every_other_descriptor(self) -> None:
        self.add_map('second-map', [self.webp(30)])
        self.bootstrap()
        active = self.root / 'config/dataset-releases.lock.json'
        active.parent.mkdir()
        active.write_bytes((self.output / 'dataset-releases.lock.json').read_bytes())
        before = json.loads(active.read_bytes())
        self.add_map('second-map', [self.webp(31)])
        result = pack_datasets(repo_root=self.root, selector='second-map')
        self.assertEqual((result['packed'], result['reused']), (1, 1))
        after = json.loads(active.read_bytes())
        stable = lambda lock: next(e for e in lock['tileSets'] if e['datasetId'] == 'test-dataset')
        self.assertEqual(stable(before), stable(after))
        verify_packages(public_root=self.public, package_root=self.output, lock_path=active)

    def test_catalog_only_update_needs_no_new_local_archive(self) -> None:
        self.bootstrap()
        active = self.root / 'config/dataset-releases.lock.json'
        active.parent.mkdir()
        active.write_bytes((self.output / 'dataset-releases.lock.json').read_bytes())
        before = active.read_bytes()
        manifest_path = self.public / self.paths['manifest'].lstrip('/')
        manifest = json.loads(manifest_path.read_bytes())
        manifest['title'] = {'en': 'A metadata-only edit'}
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        for archive in self.output.rglob('*.tar'):
            archive.unlink()
        result = pack_datasets(repo_root=self.root, selector='test-dataset')
        self.assertEqual((result['packed'], result['reused']), (0, 1))
        self.assertEqual(before, active.read_bytes())
        self.assertEqual(list(self.output.rglob('*.tar')), [])

    def test_failed_selection_preserves_active_lock(self) -> None:
        self.add_map('second-map', [self.webp(30)])
        self.bootstrap()
        active = self.root / 'config/dataset-releases.lock.json'
        active.parent.mkdir()
        active.write_bytes((self.output / 'dataset-releases.lock.json').read_bytes())
        before = active.read_bytes()
        self.add_map('second-map', [self.webp(31)])
        with self.assertRaisesRegex(DeploymentError, 'Unselected map'):
            pack_datasets(repo_root=self.root, selector='test-dataset')
        self.assertEqual(before, active.read_bytes())

    def test_manifest_inventory_binding_is_still_verified_before_download(self) -> None:
        (self.public / self.paths['tile'].lstrip('/')).unlink()
        (self.public / self.paths['tilesInventory'].lstrip('/')).write_bytes(b'{}\n')
        with self.assertRaises(DeploymentError):
            build_metadata_plan(public_root=self.public)

    def test_lock_must_match_all_active_inventories_and_part_totals(self) -> None:
        self.bootstrap()
        lock = json.loads((self.output / 'dataset-releases.lock.json').read_bytes())
        tiles = read_tile_sets(public_root=self.public)
        candidate = copy.deepcopy(lock)
        candidate['tileSets'][0]['parts'][0]['tileCount'] += 1
        with self.assertRaises(DeploymentError):
            validate_lock(candidate, tiles)
        self.add_map('second-map', [self.webp(30)])
        with self.assertRaisesRegex(DeploymentError, 'missing, unused or mismatched'):
            validate_lock(lock, read_tile_sets(public_root=self.public))

    def test_canonical_archive_members_checked_even_with_matching_archive_hash(self) -> None:
        self.bootstrap()
        lock_path = self.output / 'dataset-releases.lock.json'
        lock = json.loads(lock_path.read_bytes())
        archive = next(self.output.rglob('*.tar'))
        original = archive.read_bytes()
        for payload in (b'../escape' + original[9:], original[:156] + b'2' + original[157:],
                        original[:524] + b'X' + original[525:]):
            with self.subTest(payload=payload[:12]):
                archive.write_bytes(payload)
                lock['tileSets'][0]['parts'][0]['sha256'] = hashlib.sha256(payload).hexdigest()
                lock_path.write_bytes(canonical_json_bytes(lock))
                with self.assertRaises(DeploymentError):
                    verify_packages(public_root=self.public, package_root=self.output, lock_path=lock_path)

    def test_source_and_output_symlinks_are_rejected(self) -> None:
        tile = self.public / self.paths['tile'].lstrip('/')
        original = tile.read_bytes()
        target = self.root / 'outside.webp'
        target.write_bytes(original)
        tile.unlink()
        tile.symlink_to(target)
        with self.assertRaises(DeploymentError):
            self.bootstrap()
        tile.unlink()
        tile.write_bytes(original)
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'local-data').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(DeploymentError, 'symlink'):
            self.bootstrap()
        self.assertEqual(list(outside.iterdir()), [])

    def test_cli_bootstrap_and_verify_do_not_need_git_metadata(self) -> None:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(['pack', 'all', '--bootstrap', '--release', 'v1.0.0', '--repo-root', str(self.root)]), 0)
            self.assertEqual(main(['verify', '--public-root', str(self.public),
                                   '--package-root', str(self.output / 'releases/v1.0.0'), '--lock',
                                   str(self.output / 'dataset-releases.lock.json')]), 0)
            self.assertEqual(main(['pack', 'missing-map', '--release', 'v1.0.0', '--repo-root', str(self.root)]), 1)
        self.assertFalse((self.root / '.git').exists())

    def test_product_release_has_one_index_and_short_archives_for_all_maps(self) -> None:
        self.add_map('poison-song-26.08', [self.webp(30)])
        before = build_dataset_plan(public_root=self.public)
        result = pack_datasets(repo_root=self.root, selector='all', bootstrap=True, release='v1.0.0')
        package_root = Path(result['packageRoot'])
        self.assertEqual(sorted(p.name for p in package_root.iterdir()),
                         ['package-index.json', 'tamriel-rebuilt.tar', 'test-dataset.tar'])
        lock = parse_lock((package_root / 'package-index.json').read_bytes())
        self.assertEqual(lock['schemaVersion'], 2)
        self.assertEqual({e['releaseTag'] for e in lock['tileSets']}, {'v1.0.0'})
        self.assertEqual(Path(result['lockPath']).read_bytes(), (package_root / 'package-index.json').read_bytes())
        self.assertFalse((self.root / 'config/dataset-releases.lock.json').exists())
        self.assertEqual(pack_datasets(repo_root=self.root, selector='all', bootstrap=True, release='v1.0.0'), result)
        from tools.deployment.download_datasets import download_datasets
        for path in self.public.rglob('tiles'):
            if path.is_dir():
                shutil.rmtree(path)
        class LocalRelease:
            def fetch(self, entry, part):
                return (package_root / part['name']).open('rb')
        restored = download_datasets(repo_root=self.root, lock_path=Path(result['lockPath']), client=LocalRelease())
        self.assertEqual(restored['downloaded'], 2)
        self.assertEqual(build_dataset_plan(public_root=self.public), before)

    def test_product_version_cannot_be_reused_for_changed_inventory(self) -> None:
        self.add_map('second-map', [self.webp(30)])
        result = pack_datasets(repo_root=self.root, selector='all', bootstrap=True, release='v1.0.0')
        before = Path(result['lockPath']).read_bytes()
        self.add_map('second-map', [self.webp(31)])
        with self.assertRaises(DeploymentError):
            pack_datasets(repo_root=self.root, selector='all', bootstrap=True, release='v1.0.0')
        self.assertEqual(Path(result['lockPath']).read_bytes(), before)
        changed = pack_datasets(repo_root=self.root, selector='all', bootstrap=True, release='v1.0.1')
        after = parse_lock(Path(changed['lockPath']).read_bytes())
        prior = parse_lock(before)
        old_stable = next(e for e in prior['tileSets'] if e['datasetId'] == 'test-dataset')
        new_stable = next(e for e in after['tileSets'] if e['datasetId'] == 'test-dataset')
        self.assertEqual(old_stable['parts'], new_stable['parts'])
        self.assertEqual({e['releaseTag'] for e in after['tileSets']}, {'v1.0.1'})

    def test_product_lock_rejects_unsafe_versions_mixed_tags_and_archive_collisions(self) -> None:
        self.add_map('second-map', [self.webp(30)])
        result = pack_datasets(repo_root=self.root, selector='all', bootstrap=True, release='v1.0.0')
        lock = parse_lock(Path(result['lockPath']).read_bytes())
        for tag in ('latest', '../v1.0.0', 'v01.0.0', 'v1.0', 'v1.0.0-rc1', 'v1.0.0\n'):
            invalid = copy.deepcopy(lock)
            for entry in invalid['tileSets']:
                entry['releaseTag'] = tag
            with self.subTest(tag=tag), self.assertRaises(DeploymentError):
                parse_lock(canonical_json_bytes(invalid))
        invalid = copy.deepcopy(lock)
        invalid['tileSets'][0]['releaseTag'] = 'v1.0.1'
        with self.assertRaisesRegex(DeploymentError, 'same product release'):
            parse_lock(canonical_json_bytes(invalid))
        invalid = copy.deepcopy(lock)
        invalid['tileSets'][0]['parts'][0]['name'] = '../escape.tar'
        with self.assertRaises(DeploymentError):
            parse_lock(canonical_json_bytes(invalid))
        self.assertEqual(product_part_name('poison-song-26.08', 1, 2), 'tamriel-rebuilt-0001.tar')
        self.assertEqual(product_part_name('poison-song-26.08', 2, 2), 'tamriel-rebuilt-0002.tar')
        invalid = copy.deepcopy(lock)
        for number, entry in enumerate(invalid['tileSets']):
            entry['datasetId'] = f'poison-song-26.0{number}'
            entry['parts'][0]['name'] = 'tamriel-rebuilt.tar'
        with self.assertRaisesRegex(DeploymentError, 'duplicate'):
            parse_lock(canonical_json_bytes(invalid))


if __name__ == '__main__':
    unittest.main()
