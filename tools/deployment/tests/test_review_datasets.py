from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.deployment.common import DeploymentError, sha256_bytes
from tools.deployment.tests.fixtures import build_runtime, descriptor, json_bytes
from tools.deployment.review_datasets import review_datasets


def write_tree(root: Path, *, dataset_id: str = 'test-dataset', tile: bytes | None = None,
               inventory: str = 'd' * 64, places: list | None = None, names: list | None = None,
               map_key: str | None = None) -> dict:
    runtime, paths = build_runtime()
    replace = lambda value: value.replace('test-dataset', dataset_id).replace('d' * 64, inventory)
    runtime = {replace(k): v if k.endswith('.webp') else replace(v.decode()).encode() for k, v in runtime.items()}
    paths = {k: replace(v) for k, v in paths.items()}
    get = lambda key: json.loads(runtime[paths[key]])
    put = lambda key, value: runtime.__setitem__(paths[key], json_bytes(value))
    if tile is not None:
        runtime[paths['tile']] = tile
    loc = get('locations'); loc['places'] = places or []; put('locations', loc)
    locale = get('locale'); locale['places'] = names or []; put('locale', locale)
    audit = get('catalogAudit')
    for key, name in [('locations', 'locations'), ('english', 'locale')]:
        record = audit['integrity']['artifacts'][key]
        record.update(bytes=len(runtime[paths[name]]), sha256=sha256_bytes(runtime[paths[name]]))
    put('catalogAudit', audit)
    inv = get('tilesInventory'); inv.update(bytes=len(runtime[paths['tile']]), sha256=sha256_bytes(runtime[paths['tile']]))
    put('tilesInventory', inv)
    quality = get('quality'); quality['artifacts']['tiles'].update(bytes=len(runtime[paths['tilesInventory']]), sha256=sha256_bytes(runtime[paths['tilesInventory']]))
    quality['gates']['inventory']['totalBytes'] = len(runtime[paths['tile']]); put('quality', quality)
    assets = get('mapAssets'); pyramid = assets['tilePyramids'][0]
    pyramid['qualityReport'] = descriptor(paths['quality'], runtime[paths['quality']])
    pyramid['integrity']['totalBytes'] = len(runtime[paths['tile']]); put('mapAssets', assets)
    manifest = get('manifest')
    if map_key:
        manifest['mapKey'] = map_key
    for key in ['locations', 'catalogAudit']:
        manifest['artifacts'][key] = descriptor(paths[key], runtime[paths[key]])
    manifest['artifacts']['locales'][0]['artifact'] = descriptor(paths['locale'], runtime[paths['locale']])
    manifest['artifacts']['tiles']['sha256'] = sha256_bytes(runtime[paths['mapAssets']]); put('manifest', manifest)
    for url, payload in runtime.items():
        target = root / url.lstrip('/'); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(payload)
    return paths


class DatasetReviewTests(unittest.TestCase):
    def test_changed_tile_is_paired_across_inventory_and_dataset_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = b'RIFF\x04\0\0\0WEBP'
            after = before + b'changed'
            write_tree(root / 'base', dataset_id='old-26', map_key='tamriel-rebuilt', tile=before)
            write_tree(root / 'candidate', dataset_id='new-27', map_key='tamriel-rebuilt', tile=after, inventory='e' * 64)
            summary = review_datasets(base_public_root=root / 'base', candidate_public_root=root / 'candidate', output_dir=root / 'review', base_sha='a' * 40, candidate_sha='b' * 40)
            self.assertEqual(summary['counts']['tiles'], {'added': 0, 'removed': 0, 'changed': 1, 'unchanged': 0})
            change = summary['tileChanges'][0]
            self.assertEqual([change['z'], change['x'], change['y']], [0, 0, 0])
            self.assertEqual((root / 'review' / change['before']['previewImage']).read_bytes(), before)
            self.assertEqual((root / 'review' / change['after']['previewImage']).read_bytes(), after)
            self.assertEqual(summary['datasets'][0]['matchReason'], 'unique-mapKey')

    def test_places_names_field_changes_and_html_are_escaped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tree(root / 'base', places=[{'id': 'p1', 'mapPosition': [0, 0]}, {'id': 'gone'}], names=[{'placeId': 'p1', 'name': 'Before'}])
            write_tree(root / 'candidate', places=[{'id': 'p1', 'mapPosition': [1, 0]}, {'id': 'new'}], names=[{'placeId': 'p1', 'name': '<script>alert(1)</script>'}])
            summary = review_datasets(base_public_root=root / 'base', candidate_public_root=root / 'candidate', output_dir=root / 'review')
            self.assertEqual(summary['counts']['places'], {'added': 1, 'removed': 1, 'changed': 1, 'unchanged': 0})
            changed = next(c for c in summary['placeChanges'] if c['status'] == 'changed')
            self.assertIn('mapPosition', changed['changedFields'])
            self.assertIn('locales', changed['changedFields'])
            html = (root / 'review/index.html').read_text()
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>', html)

    def test_bootstrap_preview_is_bounded_but_json_is_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tree(root / 'candidate', places=[{'id': 'p1'}, {'id': 'p2'}])
            summary = review_datasets(candidate_public_root=root / 'candidate', output_dir=root / 'review', preview_limit=1)
            self.assertTrue(summary['bootstrap'])
            self.assertEqual(len(summary['placeChanges']), 2)
            self.assertEqual(summary['preview']['placesShown'], 1)
            self.assertEqual(summary['counts']['tiles']['added'], 1)
            self.assertEqual(json.loads((root / 'review/summary.json').read_text()), summary)

    def test_unchanged_tile_bytes_ignore_content_address_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tree(root / 'base')
            write_tree(root / 'candidate', inventory='e' * 64)
            summary = review_datasets(base_public_root=root / 'base', candidate_public_root=root / 'candidate', output_dir=root / 'review')
            self.assertEqual(summary['counts']['tiles']['unchanged'], 1)
            self.assertEqual(summary['tileChanges'], [])

    def test_tampered_or_symlink_data_fails_before_output(self):
        for symlink in [False, True]:
            with self.subTest(symlink=symlink), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paths = write_tree(root / 'candidate')
                tile = root / 'candidate' / paths['tile'].lstrip('/')
                if symlink:
                    target = root / 'outside'; target.write_bytes(tile.read_bytes()); tile.unlink(); tile.symlink_to(target)
                else:
                    tile.write_bytes(b'tampered')
                with self.assertRaises(DeploymentError):
                    review_datasets(candidate_public_root=root / 'candidate', output_dir=root / 'review')
                self.assertFalse((root / 'review').exists())

    def test_output_cannot_replace_inputs_or_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); write_tree(root / 'candidate')
            with self.assertRaises(DeploymentError):
                review_datasets(candidate_public_root=root / 'candidate', output_dir=root / 'candidate/review')
            (root / 'review').mkdir(); (root / 'review/index.html').write_text('keep')
            with self.assertRaises(DeploymentError):
                review_datasets(candidate_public_root=root / 'candidate', output_dir=root / 'review')
            self.assertEqual((root / 'review/index.html').read_text(), 'keep')
