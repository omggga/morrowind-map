"""Bounded read-only GitHub Release transport with explicit redirect handling."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tools.deployment.common import DeploymentError, strict_json_object
from tools.deployment.dataset_packages import REPOSITORY, release_tag


API = f'https://api.github.com/repos/{REPOSITORY}/releases'
MAX_API_BYTES = 4 * 1024 * 1024
MAX_REDIRECTS = 5
STORAGE_HOSTS = frozenset({'release-assets.githubusercontent.com', 'objects.githubusercontent.com',
                           'github-releases.githubusercontent.com'})


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _credential() -> str | None:
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token and shutil.which('gh'):
        try:
            result = subprocess.run(['gh', 'auth', 'token', '--hostname', 'github.com'],
                                    capture_output=True, text=True, timeout=15, check=False)
            if result.returncode == 0:
                token = result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    if token and (not token.isascii() or any(c.isspace() or ord(c) < 32 for c in token)):
        raise DeploymentError('GitHub credential has an invalid format')
    return token


def _storage_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname in STORAGE_HOSTS
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and not parsed.fragment and '\\' not in url and not any(c.isspace() or ord(c) < 32 for c in url))
    except ValueError:
        return False


class GitHubClient:
    def __init__(self, *, anonymous: bool = False):
        self.anonymous = anonymous
        self._token: str | None = None
        self._credential_loaded = False
        self._opener = build_opener(_NoRedirect())
        self._assets: dict[str, dict] = {}

    def _open(self, url: str, *, binary: bool = False):
        # Initial destinations are always constructed from the fixed repository.
        if not url.startswith(API + '/') or urlsplit(url).netloc != 'api.github.com':
            raise DeploymentError('GitHub request is outside the canonical repository')
        if not self._credential_loaded:
            self._token = None if self.anonymous else _credential()
            self._credential_loaded = True
        headers = {'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json',
                   'User-Agent': 'morrowind-map-datasets', 'X-GitHub-Api-Version': '2026-03-10',
                   'Accept-Encoding': 'identity'}
        if self._token:
            headers['Authorization'] = 'Bearer ' + self._token
        for redirects in range(MAX_REDIRECTS + 1):
            try:
                response = self._opener.open(Request(url, headers=headers), timeout=60)
            except HTTPError as error:
                status = error.code
                location = error.headers.get('Location')
                error.close()
                if status in (301, 302, 303, 307, 308) and binary and location:
                    target = urljoin(url, location)
                    if redirects == MAX_REDIRECTS or not _storage_url(target):
                        raise DeploymentError('Release download redirect is not permitted') from None
                    url = target
                    # Never send API credentials/cookies to a redirected destination.
                    headers = {'Accept': 'application/octet-stream', 'Accept-Encoding': 'identity',
                               'User-Agent': 'morrowind-map-datasets'}
                    continue
                raise DeploymentError(f'GitHub request failed (HTTP {status}); check release availability and read access') from None
            except (OSError, URLError, ValueError) as error:
                raise DeploymentError('GitHub request failed; check network access and retry') from None
            if response.status != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity':
                response.close()
                raise DeploymentError('Unexpected GitHub response status or encoding')
            return response
        raise DeploymentError('Release download redirect limit exceeded')

    def _json(self, url: str):
        with self._open(url) as response:
            payload = response.read(MAX_API_BYTES + 1)
        if len(payload) > MAX_API_BYTES:
            raise DeploymentError('GitHub API response exceeds its byte limit')
        # The strict parser also rejects duplicate fields inside arrays.
        payload.decode('utf-8', errors='strict')
        return strict_json_object(b'{"value":' + payload + b'}', 'GitHub response')['value']

    def fetch(self, entry: dict, part: dict):
        tag = release_tag((entry['datasetId'], entry['pyramidId'], entry['inventorySha256']))
        if entry['releaseTag'] != tag or not re.fullmatch(r'tiles-[0-9]{4}\.tar', part['name']):
            raise DeploymentError('Invalid canonical release coordinates')
        if tag not in self._assets:
            release = self._json(API + '/tags/' + quote(tag, safe=''))
            if (not isinstance(release, dict) or release.get('tag_name') != tag
                    or release.get('draft') is not False or release.get('immutable') is not True
                    or type(release.get('id')) is not int or release['id'] <= 0):
                raise DeploymentError('Canonical dataset release must be published and immutable')
            assets = {}
            for page in range(1, 12):
                batch = self._json(f'{API}/{release["id"]}/assets?per_page=100&page={page}')
                if not isinstance(batch, list) or len(batch) > 100:
                    raise DeploymentError('Invalid release asset listing')
                for asset in batch:
                    if (not isinstance(asset, dict) or not isinstance(asset.get('name'), str)
                            or asset['name'] in assets or len(assets) >= 1000):
                        raise DeploymentError('Duplicate or excessive release assets')
                    assets[asset['name']] = asset
                if len(batch) < 100:
                    break
            self._assets[tag] = assets
        asset = self._assets[tag].get(part['name'], {})
        if (type(asset.get('id')) is not int or asset['id'] <= 0 or asset.get('state') != 'uploaded'
                or type(asset.get('size')) is not int or asset['size'] != part['bytes']
                or asset.get('digest') not in (None, 'sha256:' + part['sha256'])):
            raise DeploymentError('Release asset is missing or differs from the committed lock')
        return self._open(f'{API}/assets/{asset["id"]}', binary=True)
