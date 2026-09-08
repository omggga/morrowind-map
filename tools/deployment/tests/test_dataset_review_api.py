from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from tools.deployment.common import DeploymentError
from tools.deployment.dataset_review_api import ReleaseAPI
from tools.deployment.tests.test_dataset_github import Response, redirect


class ReviewAPITests(unittest.TestCase):
    def test_source_read_redirect_never_carries_token_to_storage(self):
        api = ReleaseAPI()
        with mock.patch('tools.deployment.dataset_review_api._credential', return_value='credential'), \
             mock.patch.object(api._opener, 'open', side_effect=[redirect('https://release-assets.githubusercontent.com/data'), Response(b'bytes')]) as opened:
            with api.read_asset('owner/source', 12) as response:
                self.assertEqual(response.read(), b'bytes')
        first, second = [call.args[0] for call in opened.call_args_list]
        self.assertEqual(first.full_url, 'https://api.github.com/repos/owner/source/releases/assets/12')
        self.assertEqual(first.get_header('Authorization'), 'Bearer credential')
        self.assertIsNone(second.get_header('Authorization'))

    def test_read_role_cannot_create_publish_or_rerun(self):
        api = ReleaseAPI()
        with mock.patch.object(api._opener, 'open') as opened:
            for action in (lambda: api.create_draft('tiles-v1/test/main/' + 'a' * 64, 'b' * 40, 'body'),
                           lambda: api.publish_release(12), lambda: api.rerun_failed_jobs(12)):
                with self.assertRaisesRegex(DeploymentError, 'cannot perform'):
                    action()
            opened.assert_not_called()

    def test_writes_only_target_canonical_repository_and_never_latest(self):
        api = ReleaseAPI(writable=True)
        with mock.patch('tools.deployment.dataset_review_api._credential', return_value=None), \
             mock.patch.object(api._opener, 'open', side_effect=lambda *a, **k: Response(b'{}')) as opened:
            api.create_draft('tiles-v1/test/main/' + 'a' * 64, 'b' * 40, 'body')
            api.publish_release(12)
        create, publish = [call.args[0] for call in opened.call_args_list]
        self.assertEqual(create.full_url, 'https://api.github.com/repos/omggga/morrowind-map/releases')
        self.assertEqual(create.method, 'POST')
        self.assertEqual(json.loads(create.data)['target_commitish'], 'b' * 40)
        self.assertTrue(json.loads(create.data)['draft'])
        self.assertTrue(json.loads(create.data)['prerelease'])
        self.assertEqual(json.loads(create.data)['make_latest'], 'false')
        self.assertEqual(publish.method, 'PATCH')
        self.assertEqual(json.loads(publish.data), {'draft': False, 'prerelease': True, 'make_latest': 'false'})

    def test_product_release_has_human_title_and_is_latest(self):
        api = ReleaseAPI(writable=True)
        with mock.patch.object(api, '_request', return_value={}) as request:
            api.create_draft('v1.0.0', 'b' * 40, 'Five validated map packages.')
            api.publish_release(12, tag='v1.0.0')
        create, publish = request.call_args_list
        self.assertEqual(create.kwargs['body']['name'], 'Morrowind Interactive Map v1.0.0')
        self.assertFalse(create.kwargs['body']['prerelease'])
        self.assertEqual(create.kwargs['body']['make_latest'], 'true')
        self.assertEqual(publish.kwargs['body'], {'draft': False, 'prerelease': False, 'make_latest': 'true'})

    def test_product_archive_names_are_bounded_safe_basenames(self):
        api = ReleaseAPI(writable=True)
        with mock.patch.object(api, '_request', return_value={}) as request:
            for name in ('morrowind.tar', 'tamriel-rebuilt.tar', 'home-of-nords-0001.tar', 'custom-map-1.0.tar', 'package-index.json'):
                api.upload_asset(12, name, Path('/unused'))
            self.assertEqual(request.call_count, 5)
            for name in ('../morrowind.tar', 'maps/morrowind.tar', 'a' * 256 + '.tar', 'map.tar.gz', 'map?x.tar'):
                with self.subTest(name=name), self.assertRaises(DeploymentError):
                    api.upload_asset(12, name, Path('/unused'))
            self.assertEqual(request.call_count, 5)

    def test_upload_stream_is_bounded_and_upload_redirect_is_rejected(self):
        api = ReleaseAPI(writable=True)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'tiles-0001.tar'
            path.write_bytes(b'archive bytes')
            captured = []
            def opened(request, **kwargs):
                captured.append((request.full_url, request.get_header('Content-length'), request.data.read()))
                return Response(b'{}')
            with mock.patch('tools.deployment.dataset_review_api._credential', return_value='credential'), \
                 mock.patch.object(api._opener, 'open', side_effect=opened):
                api.upload_asset(12, path.name, path)
            self.assertEqual(captured, [('https://uploads.github.com/repos/omggga/morrowind-map/releases/12/assets?name=tiles-0001.tar', '13', b'archive bytes')])
            with mock.patch.object(api._opener, 'open', side_effect=redirect('https://evil.invalid')):
                with self.assertRaises(DeploymentError):
                    api.upload_asset(12, path.name, path)

    def test_only_real_missing_release_is_none_and_errors_are_redacted(self):
        api = ReleaseAPI()
        with mock.patch('tools.deployment.dataset_review_api._credential', return_value=None):
            with mock.patch.object(api._opener, 'open', side_effect=[
                    HTTPError('hidden', 404, 'missing', {}, None), Response(b'[]')]):
                self.assertIsNone(api.release_by_tag('owner/repo', 'tag'))
            for error in (HTTPError('secret signed URL', 403, 'credential', {}, None), URLError('credential secret signed URL')):
                with mock.patch.object(api._opener, 'open', side_effect=error):
                    with self.assertRaises(DeploymentError) as raised:
                        api.release_by_tag('owner/repo', 'tag')
                self.assertNotIn('credential', str(raised.exception))
                self.assertNotIn('signed URL', str(raised.exception))

    def test_missing_published_tag_resolves_matching_draft_from_release_listing(self):
        api = ReleaseAPI(writable=True)
        draft = {'id': 12, 'tag_name': 'tiles-v1/test/main/' + 'a' * 64, 'draft': True}
        with mock.patch('tools.deployment.dataset_review_api._credential', return_value=None), \
             mock.patch.object(api._opener, 'open', side_effect=[
                 HTTPError('hidden', 404, 'missing', {}, None), Response(json.dumps([draft]).encode())]) as opened:
            self.assertEqual(api.release_by_tag('owner/repo', draft['tag_name']), draft)
        self.assertEqual(opened.call_args_list[1].args[0].full_url,
                         'https://api.github.com/repos/owner/repo/releases?per_page=100&page=1')

    def test_draft_lookup_paginates_and_checks_for_multiple_matches(self):
        api = ReleaseAPI(writable=True)
        first = [{'id': n + 1, 'tag_name': f'other-{n}', 'draft': False} for n in range(100)]
        draft = {'id': 101, 'tag_name': 'target', 'draft': True}
        with mock.patch.object(api, '_request', side_effect=[None, first, [draft]]) as request:
            self.assertEqual(api.release_by_tag('owner/repo', 'target'), draft)
            self.assertEqual(request.call_args_list[-1].args[0], 'repos/owner/repo/releases?per_page=100&page=2')
        first[0] = {**draft, 'id': 102}
        with mock.patch.object(api, '_request', side_effect=[None, first, [draft]]):
            with self.assertRaises(DeploymentError):
                api.release_by_tag('owner/repo', 'target')

    def test_draft_lookup_is_bounded_and_rejects_conflicting_or_invalid_records(self):
        api = ReleaseAPI(writable=True)
        for record in ({'id': True, 'tag_name': 'target', 'draft': True},
                       {'id': 12, 'tag_name': 'target', 'draft': 'true'},
                       {'id': 12, 'tag_name': 'target', 'draft': False}):
            with self.subTest(record=record), mock.patch.object(api, '_request', side_effect=[None, [record]]):
                with self.assertRaises(DeploymentError):
                    api.release_by_tag('owner/repo', 'target')
        pages = [[{'id': page * 100 + n + 1, 'tag_name': f'other-{page}-{n}', 'draft': False}
                  for n in range(100)] for page in range(11)]
        with mock.patch.object(api, '_request', side_effect=[None, *pages]) as request:
            with self.assertRaisesRegex(DeploymentError, 'limit|count'):
                api.release_by_tag('owner/repo', 'target')
            self.assertLessEqual(request.call_count, 12)

    def test_published_tag_skips_draft_listing_and_permission_errors_never_fall_back(self):
        api = ReleaseAPI()
        published = {'id': 12, 'tag_name': 'target', 'draft': False}
        with mock.patch.object(api, '_request', return_value=published) as request:
            self.assertEqual(api.release_by_tag('owner/repo', 'target'), published)
            self.assertEqual(request.call_count, 1)
        for responses in ([DeploymentError('HTTP 403')], [None, DeploymentError('HTTP 403')]):
            with mock.patch.object(api, '_request', side_effect=responses) as request:
                with self.assertRaisesRegex(DeploymentError, 'HTTP 403'):
                    api.release_by_tag('owner/repo', 'target')
                self.assertEqual(request.call_count, len(responses))

    def test_policy_confirmation_does_not_require_admin_api(self):
        api = ReleaseAPI()
        with mock.patch.object(api._opener, 'open') as opened:
            with mock.patch.dict(os.environ, {'IMMUTABLE_RELEASES_CONFIRMED': 'true'}):
                self.assertTrue(api.immutable_policy_confirmed())
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertFalse(api.immutable_policy_confirmed())
            opened.assert_not_called()

    def test_safe_repository_ids_and_upload_names_are_required(self):
        api = ReleaseAPI(writable=True)
        for repository, number in (('https://evil.invalid', 1), ('owner/repo/../other', 1), ('owner/repo', True), ('owner/repo', 0)):
            with self.assertRaises(DeploymentError):
                api.read_asset(repository, number)
        with self.assertRaises(DeploymentError):
            api.upload_asset(12, '../asset', Path('/missing'))


if __name__ == '__main__':
    unittest.main()
