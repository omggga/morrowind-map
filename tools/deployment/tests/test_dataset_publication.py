from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.deployment.common import DeploymentError, canonical_json_bytes
from tools.deployment.dataset_packages import REPOSITORY, _lock, release_tag
from tools.deployment.dataset_publication import publish_packages


class FakeAPI:
    def __init__(self):
        self.releases = {}
        self.assets = {}
        self.payloads = {}
        self.writes = []
        self.policy_confirmed = True
        self.publish_immutable = True
        self.digests = True
        self.next_id = 100

    def add_release(self, repo, tag, *, draft=False, immutable=False):
        self.next_id += 1
        release = {'id': self.next_id, 'tag_name': tag, 'draft': draft, 'immutable': immutable}
        self.releases[repo, release['id']] = release
        self.assets[repo, release['id']] = []
        return copy.deepcopy(release)

    def add_asset(self, repo, release_id, name, payload):
        self.next_id += 1
        asset = {'id': self.next_id, 'name': name, 'size': len(payload), 'state': 'uploaded',
                 'digest': 'sha256:' + hashlib.sha256(payload).hexdigest() if self.digests else None}
        self.assets[repo, release_id].append(asset)
        self.payloads[repo, asset['id']] = payload
        return copy.deepcopy(asset)

    def release_by_tag(self, repo, tag):
        return next((copy.deepcopy(r) for (owner, _), r in self.releases.items()
                     if owner == repo and r['tag_name'] == tag), None)

    def release_by_id(self, repo, release_id):
        return copy.deepcopy(self.releases[repo, release_id])

    def list_assets(self, repo, release_id):
        return copy.deepcopy(self.assets[repo, release_id])

    def read_asset(self, repo, asset_id):
        return io.BytesIO(self.payloads[repo, asset_id])

    def immutable_policy_confirmed(self):
        return self.policy_confirmed

    def create_draft(self, tag, tool_sha, body):
        self.writes.append(('create', tag, tool_sha))
        return self.add_release(REPOSITORY, tag, draft=True)

    def upload_asset(self, release_id, name, path):
        self.writes.append(('upload', name))
        return self.add_asset(REPOSITORY, release_id, name, path.read_bytes())

    def publish_release(self, release_id, *, tag=None):
        self.writes.append(('publish', release_id))
        release = self.releases[REPOSITORY, release_id]
        release.update(draft=False, immutable=self.publish_immutable)
        return copy.deepcopy(release)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.api = FakeAPI()
        payload = b'x' * 10240
        part = {'name': 'tiles-0001.tar', 'sha256': hashlib.sha256(payload).hexdigest(),
                'bytes': len(payload), 'tileCount': 1, 'unpackedBytes': 12}
        self.entry = {'datasetId': 'test-map', 'pyramidId': 'main', 'inventorySha256': 'a' * 64,
                      'format': 'ustar-v1', 'releaseTag': release_tag(('test-map', 'main', 'a' * 64)),
                      'parts': [part]}
        source = self.api.add_release('contributor/maps', 'proposal')
        asset = self.api.add_asset('contributor/maps', source['id'], 'proposed-map.tar', payload)
        self.package = {'entry': self.entry, 'source': {'repository': 'contributor/maps',
                        'releaseId': source['id'], 'assets': [{**part, 'assetName': asset['name'],
                        'assetId': asset['id'], 'apiDigest': asset['digest']}]}}
        self.package['source']['assets'][0].pop('tileCount')
        self.package['source']['assets'][0].pop('unpackedBytes')

    def publish(self):
        return publish_packages([self.package], api=self.api, work_root=self.root, tool_sha='b' * 40)

    def canonical(self, *, draft=False, immutable=True):
        release = self.api.add_release(REPOSITORY, self.entry['releaseTag'], draft=draft, immutable=immutable)
        for part in self.entry['parts']:
            self.api.add_asset(REPOSITORY, release['id'], part['name'], b'x' * part['bytes'])
        index = canonical_json_bytes({'schemaVersion': 1, 'repository': REPOSITORY, 'tileSets': [self.entry]})
        self.api.add_asset(REPOSITORY, release['id'], 'package-index.json', index)
        return release

    def product_packages(self):
        packages = []
        for dataset, name in [('original-goty-test', 'morrowind.tar'), ('poison-song-test', 'tamriel-rebuilt.tar')]:
            package = copy.deepcopy(self.package)
            package['entry'].update(datasetId=dataset, releaseTag='v1.0.0')
            package['entry']['parts'][0]['name'] = name
            package['source']['assets'][0]['name'] = name
            packages.append(package)
        index = _lock([package['entry'] for package in packages])
        for package in packages:
            package['index'] = copy.deepcopy(index)
        return packages

    def publish_product(self, packages=None):
        return publish_packages(self.product_packages() if packages is None else packages,
                                api=self.api, work_root=self.root, tool_sha='b' * 40)

    def test_product_maps_share_one_release_and_complete_index(self):
        packages = self.product_packages()
        result = self.publish_product(packages)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['releaseId'], result[1]['releaseId'])
        self.assertEqual([write[0] for write in self.api.writes],
                         ['create', 'upload', 'upload', 'upload', 'publish'])
        release_id = result[0]['releaseId']
        assets = self.api.list_assets(REPOSITORY, release_id)
        self.assertEqual({asset['name'] for asset in assets},
                         {'morrowind.tar', 'tamriel-rebuilt.tar', 'package-index.json'})
        index = next(asset for asset in assets if asset['name'] == 'package-index.json')
        payload = json.loads(self.api.payloads[REPOSITORY, index['id']])
        self.assertEqual(payload['schemaVersion'], 2)
        self.assertEqual({entry['datasetId'] for entry in payload['tileSets']}, {'original-goty-test', 'poison-song-test'})
        for record in result:
            self.assertEqual({asset['name'] for asset in record['assets']},
                             {record['entry']['parts'][0]['name'], 'package-index.json'})
        self.api.writes.clear()
        self.assertEqual(self.publish_product(packages), result)
        self.assertEqual(self.api.writes, [])

    def test_product_retry_resumes_only_missing_map_and_index(self):
        original = self.api.upload_asset
        def interrupt(release_id, name, path):
            if name == 'tamriel-rebuilt.tar':
                raise DeploymentError('Interrupted second map upload')
            return original(release_id, name, path)
        with mock.patch.object(self.api, 'upload_asset', side_effect=interrupt):
            with self.assertRaisesRegex(DeploymentError, 'Interrupted'):
                self.publish_product()
        self.api.writes.clear()
        self.publish_product()
        self.assertEqual(self.api.writes[:2], [('upload', 'tamriel-rebuilt.tar'), ('upload', 'package-index.json')])
        self.assertEqual(self.api.writes[2][0], 'publish')

    def test_product_conflicts_are_rejected_before_writes(self):
        for conflict in ('identity', 'name', 'index'):
            packages = self.product_packages()
            if conflict == 'identity':
                packages[1]['entry']['datasetId'] = packages[0]['entry']['datasetId']
            elif conflict == 'name':
                packages[1]['entry']['parts'][0]['name'] = packages[0]['entry']['parts'][0]['name']
            else:
                packages[1]['index']['tileSets'].pop()
            with self.subTest(conflict=conflict), self.assertRaises(DeploymentError):
                self.publish_product(packages)
            self.assertEqual(self.api.writes, [])

    def test_product_existing_immutable_release_reuses_selected_map_with_full_index(self):
        first = self.publish_product()
        self.api.writes.clear()
        result = self.publish_product(self.product_packages()[:1])
        self.assertEqual(result, first[:1])
        self.assertEqual(self.api.writes, [])

    def test_product_cannot_publish_partial_reviewed_index(self):
        with self.assertRaisesRegex(DeploymentError, 'every map'):
            self.publish_product(self.product_packages()[:1])
        self.assertEqual(self.api.writes, [])

    def test_product_existing_index_cannot_drop_a_map(self):
        self.publish_product()
        self.api.writes.clear()
        packages = self.product_packages()[:1]
        packages[0]['index'] = _lock([packages[0]['entry']])
        with self.assertRaises(DeploymentError):
            self.publish_product(packages)
        self.assertEqual(self.api.writes, [])

    def test_legacy_and_product_coordinates_can_coexist_for_migration(self):
        self.canonical()
        result = self.publish_product([self.package, *self.product_packages()])
        self.assertEqual(len(result), 3)
        self.assertNotEqual(result[0]['releaseId'], result[1]['releaseId'])

    def test_later_release_conflict_is_rejected_before_any_group_writes(self):
        release = self.canonical()
        self.api.add_asset(REPOSITORY, release['id'], 'unexpected.txt', b'conflict')
        with self.assertRaises(DeploymentError):
            self.publish_product([*self.product_packages(), self.package])
        self.assertEqual(self.api.writes, [])

    def test_product_partial_draft_cannot_be_published_from_subset(self):
        draft = self.api.add_release(REPOSITORY, 'v1.0.0', draft=True)
        self.api.add_asset(REPOSITORY, draft['id'], 'morrowind.tar', b'x' * 10240)
        with self.assertRaisesRegex(DeploymentError, 'every map'):
            self.publish_product(self.product_packages()[:1])
        self.assertEqual(self.api.writes, [])

    def test_product_publication_requires_immutable_release(self):
        self.api.publish_immutable = False
        with self.assertRaisesRegex(DeploymentError, 'did not produce an immutable release'):
            self.publish_product()

    def test_publishes_then_reuses_immutable_release_without_writes(self):
        first = self.publish()
        self.assertEqual([x[0] for x in self.api.writes], ['create', 'upload', 'upload', 'publish'])
        self.api.writes.clear()
        self.assertEqual(self.publish(), first)
        self.assertEqual(self.api.writes, [])
        self.assertFalse(list(self.root.iterdir()))

    def test_missing_api_digests_are_downloaded_and_hashed(self):
        self.api.digests = False
        self.canonical()
        result = self.publish()
        self.assertEqual(len(result), 1)
        self.assertEqual(self.api.writes, [])

    def test_missing_canonical_digest_cannot_hide_corrupt_bytes(self):
        self.api.digests = False
        release = self.canonical()
        asset = self.api.assets[REPOSITORY, release['id']][0]
        self.api.payloads[REPOSITORY, asset['id']] = b'z' * 10240
        with self.assertRaises(DeploymentError):
            self.publish()
        self.assertEqual(self.api.writes, [])

    def test_source_receipt_without_digest_accepts_later_matching_api_digest(self):
        self.package['source']['assets'][0]['apiDigest'] = None
        self.publish()

    def test_interrupted_index_upload_leaves_reusable_draft(self):
        original = self.api.upload_asset
        def interrupt(release_id, name, path):
            if name == 'package-index.json':
                raise DeploymentError('Interrupted upload')
            return original(release_id, name, path)
        with mock.patch.object(self.api, 'upload_asset', side_effect=interrupt):
            with self.assertRaises(DeploymentError):
                self.publish()
        self.api.writes.clear()
        self.publish()
        self.assertEqual([x[0] for x in self.api.writes], ['upload', 'publish'])

    def test_retry_uploads_only_missing_draft_assets(self):
        draft = self.canonical(draft=True, immutable=False)
        self.api.assets[REPOSITORY, draft['id']].pop()
        self.publish()
        self.assertEqual([x[0] for x in self.api.writes], ['upload', 'publish'])

    def test_conflicting_draft_is_never_overwritten(self):
        draft = self.canonical(draft=True, immutable=False)
        self.api.assets[REPOSITORY, draft['id']][0]['digest'] = 'sha256:' + 'f' * 64
        with self.assertRaises(DeploymentError):
            self.publish()
        self.assertEqual(self.api.writes, [])

    def test_published_release_requires_complete_exact_asset_set(self):
        release = self.canonical()
        self.api.add_asset(REPOSITORY, release['id'], 'unexpected.txt', b'no')
        with self.assertRaises(DeploymentError):
            self.publish()
        self.assertEqual(self.api.writes, [])

    def test_source_replacement_and_metadata_changes_fail_before_writes(self):
        source = self.package['source']
        original = copy.deepcopy(self.api.assets['contributor/maps', source['releaseId']][0])
        for field, value in [('id', 999), ('name', 'renamed.tar'), ('size', 1),
                             ('state', 'starter'), ('digest', None)]:
            with self.subTest(field=field):
                self.api.assets['contributor/maps', source['releaseId']][0] = {**original, field: value}
                with self.assertRaises(DeploymentError):
                    self.publish()
                self.assertEqual(self.api.writes, [])

    def test_changed_source_bytes_fail_even_with_unchanged_api_digest(self):
        asset_id = self.package['source']['assets'][0]['assetId']
        self.api.payloads['contributor/maps', asset_id] = b'z' * 10240
        with self.assertRaises(DeploymentError):
            self.publish()
        self.assertNotIn('publish', [x[0] for x in self.api.writes])
        self.assertFalse(list(self.root.iterdir()))

    def test_short_and_oversized_source_streams_fail_before_writes(self):
        asset_id = self.package['source']['assets'][0]['assetId']
        for payload in (b'x' * 10239, b'x' * 10241):
            with self.subTest(size=len(payload)):
                self.api.payloads['contributor/maps', asset_id] = payload
                with self.assertRaises(DeploymentError):
                    self.publish()
                self.assertEqual(self.api.writes, [])

    def test_stream_errors_do_not_expose_signed_urls(self):
        with mock.patch.object(self.api, 'read_asset', side_effect=OSError('https://secret.invalid/token')):
            with self.assertRaisesRegex(DeploymentError, '^Release asset transfer failed; retry publication$'):
                self.publish()
        self.assertEqual(self.api.writes, [])

    def test_policy_confirmation_required_before_writes(self):
        self.api.policy_confirmed = False
        with self.assertRaisesRegex(DeploymentError, 'policy must be confirmed'):
            self.publish()
        self.assertEqual(self.api.writes, [])

    def test_confirmed_policy_does_not_accept_mutable_publication(self):
        self.api.policy_confirmed = True
        self.api.publish_immutable = False
        with self.assertRaisesRegex(DeploymentError, 'did not produce an immutable release'):
            self.publish()
        self.assertIn('publish', [write[0] for write in self.api.writes])

    def test_published_mutable_release_is_not_reused(self):
        self.canonical(immutable=False)
        with self.assertRaises(DeploymentError):
            self.publish()
        self.assertEqual(self.api.writes, [])

    def test_canonical_source_can_be_reused_without_uploads(self):
        release = self.canonical()
        asset = self.api.list_assets(REPOSITORY, release['id'])[0]
        source = self.package['source']
        source.update(repository=REPOSITORY, releaseId=release['id'])
        source['assets'][0].update(assetName=asset['name'], assetId=asset['id'], apiDigest=asset['digest'])
        self.publish()
        self.assertEqual(self.api.writes, [])


if __name__ == '__main__':
    unittest.main()
