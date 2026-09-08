from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tools.deployment.common import DeploymentError, canonical_json_bytes
from tools.deployment.dataset_packages import REPOSITORY, _lock, product_part_name
from tools.deployment.dataset_review_workflow import digest, finish_review, freeze, prepare_review, promote_review
from tools.deployment.tests import test_dataset_packages as fixtures
from tools.deployment.upload_datasets import build_dataset_plan


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.DatasetPackageTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root, self.public, self.fixture = fixture.root, fixture.public, fixture
        self.plan = build_dataset_plan(public_root=self.public)
        lock_path = Path(fixture.bootstrap()['lockPath'])
        self.lock = json.loads(lock_path.read_bytes())
        self.entry = self.lock['tileSets'][0]
        self.git('init', '--quiet')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.root / '.gitignore').write_text('local-data/\nwork*/\n')
        (self.root / 'config').mkdir()
        (self.root / 'config/dataset-upload-plan.json').write_bytes(canonical_json_bytes(self.plan))
        tile = self.public / fixture.paths['tile'].lstrip('/')
        payload = tile.read_bytes()
        tile.write_text(f'version https://git-lfs.github.com/spec/v1\noid sha256:{hashlib.sha256(payload).hexdigest()}\nsize {len(payload)}\n')
        self.base = self.commit()
        tile.unlink()
        (self.root / 'config/dataset-releases.lock.json').write_bytes(lock_path.read_bytes())
        self.head = self.commit()
        self.pr = {'number': 17, 'state': 'open', 'head': {'sha': self.head},
                   'base': {'sha': self.base, 'ref': 'main', 'repo': {'full_name': REPOSITORY}}}
        self.release = {'id': 101, 'tag_name': self.entry['releaseTag'], 'draft': False, 'immutable': True}
        self.assets = []
        self.payloads = {}
        directory = fixture.output.joinpath(*(self.entry[k] for k in ('datasetId', 'pyramidId', 'inventorySha256')))
        for number, name in enumerate(('package-index.json', 'tiles-0001.tar'), 1):
            payload = (directory / name).read_bytes()
            self.payloads[number] = payload
            self.assets.append({'id': number, 'name': name, 'size': len(payload), 'state': 'uploaded',
                                'digest': 'sha256:' + hashlib.sha256(payload).hexdigest()})
        self.checks = []

    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(self.root), *args],
                                       stderr=subprocess.STDOUT).decode().strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '--quiet', '-m', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def get_pull(self, number):
        return copy.deepcopy(self.pr)

    def release_by_tag(self, repository, tag):
        return self.release

    def release_by_id(self, repository, release_id):
        return self.release

    def list_assets(self, repository, release_id):
        return self.assets

    def read_asset(self, repository, asset_id):
        return io.BytesIO(self.payloads[asset_id])

    def immutable_policy_confirmed(self):
        return True

    def create_check(self, payload):
        self.checks.append(payload)

    def context(self, bootstrap=False, bootstrap_release_tag=''):
        return freeze(api=self, pr_number=0 if bootstrap else 17, bootstrap_sha=self.base if bootstrap else '',
                      expected_head='' if bootstrap else self.head, expected_base='' if bootstrap else self.base,
                      tool_sha=self.head, run_id=123, run_attempt=1, sources=b'[]', legacy_transport='releases',
                      bootstrap_release_tag=bootstrap_release_tag)

    def prepare(self, context=None, work='work'):
        def fetch(root, reference, **kwargs):
            self.assertNotIn('lfs', kwargs)
            (self.root / '.git/FETCH_HEAD').write_text(self.head + '\n')
        with mock.patch('tools.deployment.dataset_review_workflow._fetch', side_effect=fetch):
            return prepare_review(repo_root=self.root, work_root=self.root / work,
                                  context=context or self.context(), api=self)

    def test_migration_review_hydrates_legacy_base_without_lfs_and_never_executes_candidate(self):
        marker = self.root / 'executed'
        code = self.root / 'tools/__init__.py'
        code.parent.mkdir()
        code.write_text(f'from pathlib import Path; Path({str(marker)!r}).touch()')
        self.head = self.commit()
        self.pr['head']['sha'] = self.head
        receipt = self.prepare()
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / '.git/lfs/objects').exists())
        self.assertEqual(receipt['headGraphSha256'], self.plan['graphSha256'])
        self.assertEqual(receipt['baseGraphSha256'], self.plan['graphSha256'])
        self.assertIsNone(receipt['baseLockSha256'])
        self.assertEqual(len(receipt['packages']), 1)
        summary = json.loads((self.root / 'work/report/summary.json').read_bytes())
        self.assertEqual(summary['counts']['tiles']['changed'], 0)
        self.assertEqual(summary['counts']['tiles']['added'], 0)

    def test_bootstrap_derives_descriptor_from_its_own_legacy_baseline(self):
        receipt = self.prepare(self.context(bootstrap=True))
        self.assertEqual(receipt['mode'], 'bootstrap')
        self.assertIsNone(receipt['prNumber'])
        self.assertIsNone(receipt['headLockSha256'])
        self.assertEqual(receipt['headGraphSha256'], self.plan['graphSha256'])
        self.assertEqual(receipt['packages'][0]['entry'], self.entry)

    def test_publication_and_durable_success_binding_follow_complete_review(self):
        receipt = self.prepare()
        receipt_path = self.root / 'work/report/receipt.json'
        binding = promote_review(receipt_path=receipt_path, receipt_sha=digest(receipt),
                                 work_root=self.root / 'work-publication', api=self,
                                 tool_sha=self.head, run_id=123, run_attempt=1)
        self.assertEqual(binding['publicationSha256'], digest(json.loads((self.root / 'work-publication/result/publication.json').read_bytes())))
        result = finish_review(api=self, pr_number=17, head_sha=self.head, run_id=123, run_attempt=1,
                               tool_sha=self.head, success=True, receipt_sha=digest(receipt),
                               binding_path=self.root / 'work-publication/result/binding.json')
        self.assertTrue(result)
        self.assertEqual(self.checks[0]['conclusion'], 'success')
        self.assertNotIn('bootstrapReleaseTag', binding)
        self.assertEqual(self.checks[0]['external_id'], f'dataset-review:123:1:{digest(receipt)}')
        self.assertEqual(json.loads(self.checks[0]['output']['text']), binding)

    def test_receipt_tampering_or_wrong_attempt_prevents_publication(self):
        receipt = self.prepare()
        path = self.root / 'work/report/receipt.json'
        with mock.patch('tools.deployment.dataset_review_workflow.publish_packages') as publish:
            for checksum, attempt in (('a' * 64, 1), (digest(receipt), 2)):
                with self.assertRaises(DeploymentError):
                    promote_review(receipt_path=path, receipt_sha=checksum, work_root=self.root / 'work-pub',
                                   api=self, tool_sha=self.head, run_id=123, run_attempt=attempt)
            publish.assert_not_called()

    def test_stale_head_or_base_fails_before_publication_and_success_check(self):
        receipt = self.prepare()
        self.pr['head']['sha'] = 'a' * 40
        with mock.patch('tools.deployment.dataset_review_workflow.publish_packages') as publish:
            with self.assertRaisesRegex(DeploymentError, 'changed'):
                promote_review(receipt_path=self.root / 'work/report/receipt.json', receipt_sha=digest(receipt),
                               work_root=self.root / 'work-pub', api=self, tool_sha=self.head, run_id=123, run_attempt=1)
            publish.assert_not_called()
        self.assertFalse(finish_review(api=self, pr_number=17, head_sha=self.head, run_id=123, run_attempt=1,
                                      tool_sha=self.head, success=True, receipt_sha=digest(receipt),
                                      binding_path=self.root / 'missing.json'))
        self.assertEqual(self.checks[-1]['conclusion'], 'failure')

    def test_failed_review_never_attaches_success_and_bootstrap_has_no_pr_check(self):
        self.assertFalse(finish_review(api=self, pr_number=17, head_sha=self.head, run_id=123, run_attempt=1,
                                      tool_sha=self.head, success=False))
        self.assertNotIn('text', self.checks[-1]['output'])
        self.assertTrue(finish_review(api=self, pr_number=0, head_sha=self.base, run_id=123, run_attempt=1,
                                     tool_sha=self.head, success=True))
        self.assertEqual(len(self.checks), 1)

    def test_product_pin_is_receipt_bound_and_unchanged_inventory_can_use_two_versions(self):
        releases, assets_by_release, payloads = {}, {}, {}
        for number, tag in enumerate(('v1.0.0', 'v1.1.0'), 10):
            entry = copy.deepcopy(self.entry)
            entry['releaseTag'] = tag
            entry['parts'][0]['name'] = product_part_name(entry['datasetId'], 1, 1)
            index = _lock([entry])
            index_bytes = canonical_json_bytes(index)
            releases[tag] = dict(self.release, id=number, tag_name=tag)
            assets_by_release[number] = [
                dict(self.assets[0], id=number * 10, size=len(index_bytes),
                     digest='sha256:' + hashlib.sha256(index_bytes).hexdigest()),
                dict(self.assets[1], id=number * 10 + 1, name=entry['parts'][0]['name']),
            ]
            payloads[number * 10] = index_bytes
            payloads[number * 10 + 1] = self.payloads[2]
        (self.root / 'config/dataset-releases.lock.json').write_bytes(canonical_json_bytes(index))
        self.head = self.commit()
        self.pr['head']['sha'] = self.head
        self.release_by_tag = lambda repository, tag: releases.get(tag)
        self.list_assets = lambda repository, release_id: assets_by_release[release_id]
        self.read_asset = lambda repository, asset_id: io.BytesIO(payloads[asset_id])
        receipt = self.prepare(self.context(bootstrap_release_tag='v1.0.0'))
        self.assertEqual(receipt['bootstrapReleaseTag'], 'v1.0.0')
        self.assertEqual(receipt['headGraphSha256'], receipt['baseGraphSha256'])
        self.assertEqual({p['entry']['releaseTag'] for p in receipt['packages']}, {'v1.0.0', 'v1.1.0'})
        self.assertTrue(all(p['index']['schemaVersion'] == 2 for p in receipt['packages']))
        self.assertFalse((self.root / '.git/lfs/objects').exists())

    def test_freeze_rejects_unsafe_bootstrap_release_pin(self):
        for tag in ('latest', 'v1.0', '../v1.0.0', None):
            with self.subTest(tag=tag), self.assertRaises(DeploymentError):
                self.context(bootstrap_release_tag=tag)

    def test_freeze_rejects_ambiguous_unsafe_sources_or_wrong_base(self):
        with self.assertRaises(DeploymentError):
            freeze(api=self, pr_number=17, bootstrap_sha=self.base, tool_sha=self.head,
                   expected_head=self.head, expected_base=self.base,
                   run_id=123, run_attempt=1, sources=b'[]', legacy_transport='releases')
        for head, base in [('', self.base), (self.head, ''), ('0' * 40, self.base), (self.head, '0' * 40)]:
            with self.subTest(head=head, base=base), self.assertRaises(DeploymentError):
                freeze(api=self, pr_number=17, bootstrap_sha='', tool_sha=self.head,
                       expected_head=head, expected_base=base,
                       run_id=123, run_attempt=1, sources=b'[]', legacy_transport='releases')
        self.pr['base']['ref'] = 'other'
        with self.assertRaises(DeploymentError):
            self.context()


if __name__ == '__main__':
    unittest.main()
