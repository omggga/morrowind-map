from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import unittest

from tools.deployment.common import DeploymentError, canonical_json_bytes
from tools.deployment.dataset_packages import REPOSITORY
from tools.deployment.dataset_review_sources import parse_sources, restore_snapshot
from tools.deployment.tests import test_dataset_packages as package_fixtures
from tools.deployment.upload_datasets import build_dataset_plan


class ReviewSourcesTests(unittest.TestCase):
    def setUp(self):
        fixture = package_fixtures.DatasetPackageTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root, self.public = fixture.root, fixture.public
        self.before = build_dataset_plan(public_root=self.public)
        result = fixture.bootstrap()
        self.lock_path = self.root / 'snapshot-lock.json'
        shutil.copyfile(result['lockPath'], self.lock_path)
        self.lock = json.loads(self.lock_path.read_bytes())
        self.entry = self.lock['tileSets'][0]
        self.release = {'id': 123, 'draft': False, 'immutable': True, 'tag_name': self.entry['releaseTag']}
        self.mapping = {key: self.entry[key] for key in ('datasetId', 'pyramidId', 'inventorySha256')}
        self.mapping.update(repository='fork-owner/packages', releaseId=456, assetPrefix='map-one-')
        self.payloads = {}
        self.assets = []
        base = fixture.output.joinpath(*(self.entry[key] for key in ('datasetId', 'pyramidId', 'inventorySha256')))
        for asset_id, name in enumerate(('package-index.json', 'tiles-0001.tar'), 1):
            payload = (base / name).read_bytes()
            self.payloads[asset_id] = payload
            self.assets.append({'id': asset_id, 'name': name, 'size': len(payload), 'state': 'uploaded',
                                'digest': 'sha256:' + hashlib.sha256(payload).hexdigest()})
        self.calls = []
        for path in self.public.rglob('tiles'):
            if path.is_dir():
                shutil.rmtree(path)

    def release_by_tag(self, repository, tag):
        self.calls.append(('tag', repository, tag))
        return self.release

    def release_by_id(self, repository, release_id):
        self.calls.append(('id', repository, release_id))
        return {'id': release_id, 'draft': False, 'immutable': False}

    def list_assets(self, repository, release_id):
        self.calls.append(('assets', repository, release_id))
        return self.assets

    def read_asset(self, repository, asset_id):
        self.calls.append(('read', repository, asset_id))
        return io.BytesIO(self.payloads[asset_id])

    def restore(self, *, sources=None, legacy=False):
        return restore_snapshot(public_root=self.public, lock_path=None if legacy else self.lock_path,
                                sources=sources or [], api=self, cache_root=self.root / 'cache')

    def mapped(self):
        self.release = None
        for asset in self.assets:
            asset['name'] = self.mapping['assetPrefix'] + asset['name']

    def test_mapping_parser_bounds_and_exact_fields(self):
        self.assertEqual(parse_sources(canonical_json_bytes([self.mapping])), [self.mapping])
        self.assertEqual(parse_sources(b'[]'), [])
        variants = [dict(self.mapping, releaseId=True), dict(self.mapping, releaseId=1.5),
                    dict(self.mapping, releaseId=0), dict(self.mapping, assetPrefix='../'),
                    dict(self.mapping, assetPrefix='_bootstrap-'), dict(self.mapping, assetPrefix='.staging-'),
                    dict(self.mapping, assetPrefix='-map-'),
                    dict(self.mapping, assetPrefix='x/y'), dict(self.mapping, assetPrefix='x..y'),
                    dict(self.mapping, assetPrefix='x' * 181), dict(self.mapping, repository='../evil'),
                    dict(self.mapping, repository='https://github.com/a/b'),
                    dict(self.mapping, datasetId='a.lock'), dict(self.mapping, unexpected='value')]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(DeploymentError):
                parse_sources(canonical_json_bytes([variant]))
        for payload in (b'{}', b'null', b'[NaN]', b'[{}]', b' ' * (128 * 1024 + 1),
                        canonical_json_bytes([self.mapping] * 101),
                        canonical_json_bytes([self.mapping] * 2),
                        '[{"x":1,"x":2}]'.encode(), '[]'.encode('utf-16')):
            with self.subTest(payload=payload[:40]), self.assertRaises(DeploymentError):
                parse_sources(payload)

    def test_canonical_release_reuses_committed_descriptor_without_reading_remote_index(self):
        self.payloads[1] = b'untrusted replacement lock'
        result = self.restore(sources=[self.mapping])
        self.assertEqual(result['lock'], self.lock)
        self.assertEqual(result['packages'][0]['source']['repository'], REPOSITORY)
        self.assertFalse(any(call[0] == 'id' for call in self.calls))
        self.assertEqual([c for c in self.calls if c[0] == 'read'], [('read', REPOSITORY, 2)])
        self.assertEqual(build_dataset_plan(public_root=self.public), self.before)
        self.assertFalse(list((self.root / 'cache').rglob('*.tar')))

    def test_explicit_mapping_restores_missing_canonical_and_pins_actual_asset_names(self):
        self.mapped()
        result = self.restore(sources=[self.mapping])
        source = result['packages'][0]['source']
        self.assertEqual(source['releaseId'], 456)
        self.assertEqual(source['assets'][0]['assetName'], 'map-one-tiles-0001.tar')
        self.assertEqual(source['assets'][0]['name'], 'tiles-0001.tar')
        self.assertEqual(build_dataset_plan(public_root=self.public), self.before)

    def test_bootstrap_index_is_bound_to_own_inventory(self):
        self.mapped()
        result = self.restore(sources=[self.mapping], legacy=True)
        self.assertEqual(result['lock'], self.lock)
        self.assertEqual([c[2] for c in self.calls if c[0] == 'read'], [1, 2])

    def test_legacy_index_with_other_inventory_fails_before_archive_download(self):
        wrong = copy.deepcopy(self.lock)
        wrong['tileSets'][0]['inventorySha256'] = 'a' * 64
        wrong['tileSets'][0]['releaseTag'] = self.entry['releaseTag'].rsplit('/', 1)[0] + '/' + 'a' * 64
        payload = canonical_json_bytes(wrong)
        self.payloads[1] = payload
        self.assets[0].update(size=len(payload), digest=None)
        with self.assertRaises(DeploymentError):
            self.restore(legacy=True)
        self.assertEqual([c[2] for c in self.calls if c[0] == 'read'], [1])

    def test_missing_mapping_or_asset_fails_before_archive_fetch(self):
        self.release = None
        with self.assertRaisesRegex(DeploymentError, 'explicit review source'):
            self.restore()
        self.mapped()
        self.assets.pop()
        with self.assertRaisesRegex(DeploymentError, 'Missing review archive'):
            self.restore(sources=[self.mapping])
        self.assertFalse(any(c[0] == 'read' for c in self.calls))

    def test_missing_second_map_is_detected_before_downloading_first_map(self):
        # Recreate the first map's input so the existing packer can construct
        # a two-map lock, then export only metadata again.
        self.restore()
        self.fixture.add_map('z-second-map', [self.fixture.webp(24)])
        result = self.fixture.bootstrap()
        shutil.copyfile(result['lockPath'], self.lock_path)
        for path in self.public.rglob('tiles'):
            if path.is_dir():
                shutil.rmtree(path)
        self.calls.clear()
        original = self.release_by_tag
        self.release_by_tag = lambda repository, tag: original(repository, tag) if tag == self.entry['releaseTag'] else None
        with self.assertRaisesRegex(DeploymentError, 'explicit review source'):
            self.restore()
        self.assertFalse(any(c[0] == 'read' for c in self.calls))
        self.assertFalse(list(self.public.rglob('tiles')))

    def test_changed_source_bytes_fail_hash_validation_without_installing(self):
        self.mapped()
        self.payloads[2] = b'x' * len(self.payloads[2])
        with self.assertRaisesRegex(DeploymentError, 'SHA-256 differs'):
            self.restore(sources=[self.mapping])
        self.assertFalse(list(self.public.rglob('tiles')))

    def test_invalid_or_mutable_canonical_release_fails_closed(self):
        for field, value in (('immutable', False), ('id', True), ('tag_name', 'other')):
            original = self.release[field]
            self.release[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(DeploymentError, 'published and immutable'):
                self.restore(sources=[self.mapping])
            self.release[field] = original
        self.assertFalse(any(c[0] == 'read' for c in self.calls))

    def test_canonical_draft_uses_explicit_source_for_publication_retry(self):
        draft = dict(self.release, draft=True, immutable=False)
        self.mapped()
        self.release = draft
        result = self.restore(sources=[self.mapping])
        self.assertEqual(result['packages'][0]['source']['releaseId'], self.mapping['releaseId'])
        self.assertEqual(build_dataset_plan(public_root=self.public), self.before)

    def test_canonical_draft_without_explicit_source_fails_closed(self):
        self.release.update(draft=True, immutable=False)
        with self.assertRaisesRegex(DeploymentError, 'published and immutable'):
            self.restore()
        self.assertFalse(any(c[0] == 'read' for c in self.calls))

    def test_bad_asset_digest_and_duplicate_asset_ids_fail_preflight(self):
        self.assets[1]['digest'] = 'sha256:' + 'a' * 64
        with self.assertRaisesRegex(DeploymentError, 'API digest differs'):
            self.restore()
        self.assets[1]['digest'] = None
        self.assets[1]['id'] = self.assets[0]['id']
        with self.assertRaisesRegex(DeploymentError, 'duplicate'):
            self.restore()
        self.assertFalse(any(c[0] == 'read' for c in self.calls))

    def test_sources_for_another_snapshot_are_rejected(self):
        self.mapping['inventorySha256'] = 'a' * 64
        with self.assertRaisesRegex(DeploymentError, 'does not belong'):
            self.restore(sources=[self.mapping])
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
