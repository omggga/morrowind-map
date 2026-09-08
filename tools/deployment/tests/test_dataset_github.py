from __future__ import annotations

import io
import json
import os
import subprocess
import unittest
from email.message import Message
from unittest import mock
from urllib.error import HTTPError, URLError

from tools.deployment.common import DeploymentError
from tools.deployment.dataset_github import API, MAX_API_BYTES, GitHubClient, _credential
from tools.deployment.dataset_packages import release_tag


class Response(io.BytesIO):
    status = 200
    headers = {}


def redirect(url, status=302):
    headers = Message()
    headers['Location'] = url
    return HTTPError('https://redacted.invalid', status, 'redirect', headers, None)


class GitHubDownloadTests(unittest.TestCase):
    def setUp(self):
        key = ('test-map', 'main', 'a' * 64)
        self.entry = dict(zip(('datasetId', 'pyramidId', 'inventorySha256'), key))
        self.entry['releaseTag'] = release_tag(key)
        self.part = {'name': 'tiles-0001.tar', 'sha256': 'b' * 64, 'bytes': 10240}
        self.release = {'id': 10, 'tag_name': release_tag(key), 'draft': False, 'immutable': True}
        self.asset = {'id': 20, 'name': self.part['name'], 'state': 'uploaded', 'size': 10240,
                      'digest': 'sha256:' + self.part['sha256']}

    def test_product_release_fetches_short_names_from_one_exact_tag(self):
        client = GitHubClient(anonymous=True)
        release = {**self.release, 'tag_name': 'v1.0.0'}
        entry = {**self.entry, 'releaseTag': 'v1.0.0'}
        first = {**self.part, 'name': 'morrowind.tar'}
        second = {**self.part, 'name': 'tamriel-rebuilt.tar'}
        assets = [{**self.asset, 'name': first['name']}, {**self.asset, 'id': 21, 'name': second['name']}]
        with mock.patch.object(client, '_json', side_effect=[release, assets]) as metadata, \
             mock.patch.object(client, '_open', side_effect=lambda *a, **k: Response(b'archive')) as stream:
            client.fetch(entry, first).close()
            client.fetch(entry, second).close()
        self.assertEqual(metadata.call_count, 2)
        self.assertEqual(metadata.call_args_list[0].args[0], API + '/tags/v1.0.0')
        self.assertEqual([call.args[0] for call in stream.call_args_list], [API + '/assets/20', API + '/assets/21'])

    def test_authenticated_api_redirect_drops_credentials_at_storage(self):
        client = GitHubClient()
        responses = [Response(json.dumps(self.release).encode()), Response(json.dumps([self.asset]).encode()),
                     redirect('https://release-assets.githubusercontent.com/asset?signature=private'), Response(b'archive')]
        with mock.patch('tools.deployment.dataset_github._credential', return_value='secret'), \
             mock.patch.object(client._opener, 'open', side_effect=responses) as opened:
            with client.fetch(self.entry, self.part) as response:
                self.assertEqual(response.read(), b'archive')
        requests = [c.args[0] for c in opened.call_args_list]
        self.assertEqual(requests[0].full_url, API + '/tags/tiles-v1%2Ftest-map%2Fmain%2F' + 'a' * 64)
        self.assertEqual(requests[1].full_url, API + '/10/assets?per_page=100&page=1')
        self.assertEqual(requests[2].full_url, API + '/assets/20')
        for request in requests[:3]:
            self.assertEqual(request.get_header('Authorization'), 'Bearer secret')
        self.assertIsNone(requests[3].get_header('Authorization'))
        self.assertIsNone(requests[3].get_header('Cookie'))

    def test_anonymous_never_reads_credentials_or_requires_gh(self):
        client = GitHubClient(anonymous=True)
        with mock.patch('tools.deployment.dataset_github._credential') as credential, \
             mock.patch.object(client._opener, 'open', return_value=Response(b'ok')) as opened:
            with client._open(API + '/assets/20', binary=True):
                pass
        credential.assert_not_called()
        self.assertIsNone(opened.call_args.args[0].get_header('Authorization'))

    def test_redirects_reject_http_foreign_hosts_api_bounce_and_credentials(self):
        for url in ('http://release-assets.githubusercontent.com/asset', 'https://evil.invalid/asset',
                    'https://release-assets.githubusercontent.com.evil.invalid/asset', API + '/assets/21',
                    'https://user@release-assets.githubusercontent.com/asset',
                    'https://release-assets.githubusercontent.com:444/asset',
                    'file:///tmp/package', 'https://release-assets.githubusercontent.com/asset#fragment'):
            client = GitHubClient(anonymous=True)
            with self.subTest(url=url), mock.patch.object(client._opener, 'open', side_effect=redirect(url)):
                with self.assertRaisesRegex(DeploymentError, 'redirect is not permitted'):
                    client._open(API + '/assets/20', binary=True)

    def test_redirect_count_is_bounded_and_metadata_never_redirects(self):
        client = GitHubClient(anonymous=True)
        target = 'https://release-assets.githubusercontent.com/asset'
        with mock.patch.object(client._opener, 'open', side_effect=lambda *a, **k: (_ for _ in ()).throw(redirect(target))) as opened:
            with self.assertRaises(DeploymentError):
                client._open(API + '/assets/20', binary=True)
            self.assertEqual(opened.call_count, 6)
        with mock.patch.object(client._opener, 'open', side_effect=redirect(target)) as opened:
            with self.assertRaises(DeploymentError):
                client._open(API + '/tags/test')
            self.assertEqual(opened.call_count, 1)

    def test_api_errors_do_not_disclose_token_or_signed_url(self):
        client = GitHubClient(anonymous=True)
        for error in (URLError('secret-token https://signed.invalid'),
                      HTTPError('https://signed.invalid', 403, 'secret-token', {}, None)):
            with mock.patch.object(client._opener, 'open', side_effect=error):
                with self.assertRaises(DeploymentError) as raised:
                    client._open(API + '/assets/20')
            self.assertNotIn('secret-token', str(raised.exception))
            self.assertNotIn('signed.invalid', str(raised.exception))

    def test_canonical_release_and_asset_identity_are_required(self):
        for field, value in (('draft', True), ('immutable', False), ('tag_name', 'wrong'), ('id', True)):
            client = GitHubClient(anonymous=True)
            with self.subTest(field=field), mock.patch.object(client, '_json', return_value={**self.release, field: value}):
                with self.assertRaises(DeploymentError):
                    client.fetch(self.entry, self.part)
        for field, value in (('digest', 'sha256:' + 'c' * 64), ('size', 1), ('id', True), ('state', 'new'), ('name', 'other.tar')):
            client = GitHubClient(anonymous=True)
            with self.subTest(field=field), mock.patch.object(client, '_json', side_effect=[self.release, [{**self.asset, field: value}]]):
                with self.assertRaises(DeploymentError):
                    client.fetch(self.entry, self.part)

    def test_asset_pagination_finds_later_part_and_rejects_duplicate_names(self):
        first = [{**self.asset, 'name': f'unused-{i}'} for i in range(100)]
        client = GitHubClient(anonymous=True)
        with mock.patch.object(client, '_json', side_effect=[self.release, first, [self.asset]]) as metadata, \
             mock.patch.object(client, '_open', return_value=Response(b'archive')):
            client.fetch(self.entry, self.part).close()
        self.assertEqual(metadata.call_args.args[0], API + '/10/assets?per_page=100&page=2')
        client = GitHubClient(anonymous=True)
        with mock.patch.object(client, '_json', side_effect=[self.release, [self.asset, self.asset]]):
            with self.assertRaisesRegex(DeploymentError, 'Duplicate'):
                client.fetch(self.entry, self.part)

    def test_api_json_and_request_destination_are_bounded(self):
        client = GitHubClient(anonymous=True)
        for payload in (b'x' * (MAX_API_BYTES + 1), b'{"id":1,"id":2}'):
            with mock.patch.object(client, '_open', return_value=Response(payload)):
                with self.assertRaises(DeploymentError):
                    client._json(API + '/tags/test')
        with self.assertRaises(DeploymentError):
            client._open('https://api.github.com/repos/other/repo/releases/assets/20')

    def test_existing_auth_and_environment_tokens_are_read_without_logging(self):
        with mock.patch.dict(os.environ, {'GH_TOKEN': 'environment-token'}, clear=True), \
             mock.patch('tools.deployment.dataset_github.subprocess.run') as command:
            self.assertEqual(_credential(), 'environment-token')
        command.assert_not_called()
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch('tools.deployment.dataset_github.shutil.which', return_value='/fixture/gh'), \
             mock.patch('tools.deployment.dataset_github.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'stored-token\n', '')) as command:
            self.assertEqual(_credential(), 'stored-token')
        self.assertEqual(command.call_args.args[0], ['gh', 'auth', 'token', '--hostname', 'github.com'])
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch('tools.deployment.dataset_github.shutil.which', return_value=None):
            self.assertIsNone(_credential())


if __name__ == '__main__':
    unittest.main()
