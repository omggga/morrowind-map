"""Narrow GitHub API for trusted dataset review and protected publication."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, build_opener

from tools.deployment.common import DeploymentError, canonical_json_bytes, strict_json_object
from tools.deployment.dataset_github import MAX_API_BYTES, MAX_REDIRECTS, _credential, _NoRedirect, _storage_url
from tools.deployment.dataset_packages import MAX_ARCHIVE_BYTES, REPOSITORY, is_product_release


def repository(value: str) -> str:
    if (not isinstance(value, str) or len(value) > 200
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', value)
            or '..' in value):
        raise DeploymentError('Source repository must be a safe GitHub owner/name')
    return value


def positive_id(value: int) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise DeploymentError('GitHub object ID must be a positive bounded integer')
    return value


class ReleaseAPI:
    def __init__(self, *, writable: bool = False):
        self.writable = writable
        self._opener = build_opener(_NoRedirect())
        self._token = None
        self._loaded = False

    def _request(self, path: str, *, method='GET', body=None, binary=False,
                 upload: Path | None = None, missing=False):
        if method != 'GET' and not self.writable:
            raise DeploymentError('Review credentials cannot perform publication writes')
        if not self._loaded:
            self._token = _credential()
            self._loaded = True
        host = 'uploads.github.com' if upload is not None else 'api.github.com'
        url = f'https://{host}/{path}'
        headers = {'User-Agent': 'morrowind-map-dataset-review', 'Accept-Encoding': 'identity',
                   'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2026-03-10'}
        if self._token:
            headers['Authorization'] = 'Bearer ' + self._token
        data = None if body is None else canonical_json_bytes(body)
        stream = None
        if upload is not None:
            if upload.is_symlink() or not upload.is_file() or not 0 < upload.stat().st_size <= MAX_ARCHIVE_BYTES:
                raise DeploymentError('Upload must be a bounded regular package file')
            headers.update({'Content-Type': 'application/octet-stream', 'Content-Length': str(upload.stat().st_size)})
            stream = upload.open('rb')
            data = stream
        elif data is not None:
            headers['Content-Type'] = 'application/json'
        try:
            for redirects in range(MAX_REDIRECTS + 1):
                try:
                    response = self._opener.open(Request(url, headers=headers, data=data, method=method), timeout=120)
                except HTTPError as error:
                    status, location = error.code, error.headers.get('Location')
                    error.close()
                    if status == 404 and missing and redirects == 0:
                        return None
                    if method == 'GET' and binary and status in (301, 302, 303, 307, 308) and location:
                        target = urljoin(url, location)
                        if redirects == MAX_REDIRECTS or not _storage_url(target):
                            raise DeploymentError('Release asset redirect is not permitted') from None
                        url = target
                        headers = {'User-Agent': 'morrowind-map-dataset-review', 'Accept-Encoding': 'identity',
                                   'Accept': 'application/octet-stream'}
                        continue
                    raise DeploymentError(f'GitHub dataset request failed (HTTP {status}); check coordinates and permissions') from None
                except (OSError, URLError, ValueError):
                    raise DeploymentError('GitHub dataset request failed; retry after checking network access') from None
                if response.status not in (200, 201) or response.headers.get('Content-Encoding', 'identity') != 'identity':
                    response.close()
                    raise DeploymentError('Unexpected GitHub response status or encoding')
                if binary:
                    return response
                with response:
                    payload = response.read(MAX_API_BYTES + 1)
                if len(payload) > MAX_API_BYTES:
                    raise DeploymentError('GitHub dataset metadata exceeds its byte limit')
                if not payload and method != 'GET':
                    return {}
                return strict_json_object(b'{"value":' + payload + b'}', 'GitHub dataset response')['value']
        finally:
            if stream is not None:
                stream.close()
        raise DeploymentError('GitHub dataset redirect limit exceeded')

    def release_by_tag(self, repo: str, tag: str):
        if not isinstance(tag, str) or len(tag) > 400:
            raise DeploymentError('Release tag is invalid')
        prefix = f'repos/{repository(repo)}/releases'
        release = self._request(f'{prefix}/tags/{quote(tag, safe="")}', missing=True)
        if release is not None:
            if (not isinstance(release, dict) or release.get('tag_name') != tag
                    or type(release.get('draft')) is not bool):
                raise DeploymentError('Release tag lookup returned a conflicting identity or state')
            positive_id(release.get('id'))
            return release
        # The tag endpoint returns published releases only. Drafts remain
        # discoverable in the authenticated listing, including after a partial
        # upload. Scan the bounded listing fully before selecting a unique draft.
        matched = None
        seen = set()
        for page in range(1, 12):
            batch = self._request(f'{prefix}?per_page=100&page={page}')
            if not isinstance(batch, list) or len(batch) > 100 or len(seen) + len(batch) > 1000:
                raise DeploymentError('Release listing count exceeds its limit')
            for item in batch:
                if (not isinstance(item, dict) or not isinstance(item.get('tag_name'), str)
                        or type(item.get('draft')) is not bool):
                    raise DeploymentError('Release listing contains an invalid identity or state')
                release_id = positive_id(item.get('id'))
                if release_id in seen:
                    raise DeploymentError('Release listing contains a duplicate identity')
                seen.add(release_id)
                if item['tag_name'] == tag:
                    if item['draft'] is not True or matched is not None:
                        raise DeploymentError('Release listing contains conflicting matches for this tag')
                    matched = item
            if len(batch) < 100:
                return matched
        raise DeploymentError('Release listing pagination exceeded its limit')

    def release_by_id(self, repo: str, release_id: int):
        return self._request(f'repos/{repository(repo)}/releases/{positive_id(release_id)}')

    def list_assets(self, repo: str, release_id: int) -> list[dict]:
        prefix = f'repos/{repository(repo)}/releases/{positive_id(release_id)}/assets'
        assets = []
        for page in range(1, 12):
            batch = self._request(f'{prefix}?per_page=100&page={page}')
            if not isinstance(batch, list) or len(batch) > 100 or len(assets) + len(batch) > 1000:
                raise DeploymentError('Release asset count is invalid')
            assets.extend(batch)
            if len(batch) < 100:
                return assets
        raise DeploymentError('Release asset pagination exceeded its limit')

    def read_asset(self, repo: str, asset_id: int):
        return self._request(f'repos/{repository(repo)}/releases/assets/{positive_id(asset_id)}', binary=True)

    def immutable_policy_confirmed(self) -> bool:
        # The settings endpoint requires Administration:read, unavailable to the
        # workflow's minimal token. This is the protected environment's maintainer
        # preflight confirmation, not a live settings query. Every published
        # release must additionally return immutable=true before success.
        return os.environ.get('IMMUTABLE_RELEASES_CONFIRMED') == 'true'

    def create_draft(self, tag: str, tool_sha: str, body: str):
        if not re.fullmatch(r'[a-f0-9]{40}', tool_sha):
            raise DeploymentError('Draft target must be the trusted tool commit')
        product = is_product_release(tag)
        payload = {'tag_name': tag, 'target_commitish': tool_sha, 'draft': True,
                   'prerelease': not product, 'make_latest': 'true' if product else 'false',
                   'generate_release_notes': False, 'body': body}
        if product:
            payload['name'] = f'Morrowind Interactive Map {tag}'
        return self._request(f'repos/{REPOSITORY}/releases', method='POST', body=payload)

    def upload_asset(self, release_id: int, name: str, path: Path):
        if (not isinstance(name, str) or len(name) > 144
                or not re.fullmatch(r'(?:[a-z0-9]+(?:[.-][a-z0-9]+)*\.tar|package-index\.json)', name)):
            raise DeploymentError('Canonical release asset name is invalid')
        return self._request(f'repos/{REPOSITORY}/releases/{positive_id(release_id)}/assets?name={quote(name)}',
                             method='POST', upload=path)

    def publish_release(self, release_id: int, *, tag: str | None = None):
        product = tag is not None and is_product_release(tag)
        return self._request(f'repos/{REPOSITORY}/releases/{positive_id(release_id)}', method='PATCH',
                             body={'draft': False, 'prerelease': not product,
                                   'make_latest': 'true' if product else 'false'})

    def get_pull(self, number: int):
        return self._request(f'repos/{REPOSITORY}/pulls/{positive_id(number)}')

    def get_pull_merge_sha(self, number: int) -> str:
        # REST 2026-03-10 removed merge_commit_sha from PR responses. The
        # canonical PR timeline still identifies the actual merged commit.
        prefix = f'repos/{REPOSITORY}/issues/{positive_id(number)}/timeline'
        merged = None
        count = 0
        for page in range(1, 12):
            batch = self._request(f'{prefix}?per_page=100&page={page}')
            if not isinstance(batch, list) or len(batch) > 100 or count + len(batch) > 1000:
                raise DeploymentError('PR timeline count exceeds its limit')
            count += len(batch)
            for event in batch:
                if not isinstance(event, dict) or not isinstance(event.get('event'), str):
                    raise DeploymentError('PR timeline contains an invalid event')
                if event['event'] == 'merged':
                    revision = event.get('commit_id')
                    if merged is not None or not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision):
                        raise DeploymentError('PR timeline contains conflicting or invalid merge events')
                    merged = revision
            if len(batch) < 100:
                if merged is None:
                    raise DeploymentError('PR timeline does not identify a merge commit')
                return merged
        raise DeploymentError('PR timeline pagination exceeded its limit')

    def get_commit(self, revision: str):
        if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision):
            raise DeploymentError('Commit lookup requires a full lowercase commit SHA')
        return self._request(f'repos/{REPOSITORY}/git/commits/{revision}')

    def create_check(self, payload: dict):
        return self._request(f'repos/{REPOSITORY}/check-runs', method='POST', body=payload)

    def get_run(self, run_id: int):
        return self._request(f'repos/{REPOSITORY}/actions/runs/{positive_id(run_id)}')

    def list_checks(self, head_sha: str):
        if not re.fullmatch(r'[a-f0-9]{40}', head_sha):
            raise DeploymentError('Check lookup requires a commit SHA')
        checks = []
        for page in range(1, 12):
            result = self._request(f'repos/{REPOSITORY}/commits/{head_sha}/check-runs'
                                   f'?check_name=Dataset%20review%20%28trusted%29&filter=all&per_page=100&page={page}')
            batch = result.get('check_runs') if isinstance(result, dict) else None
            if not isinstance(batch, list) or len(batch) > 100 or len(checks) + len(batch) > 1000:
                raise DeploymentError('Check run count is invalid')
            checks.extend(batch)
            if len(batch) < 100:
                return checks
        raise DeploymentError('Check pagination limit exceeded')

    def rerun_failed_jobs(self, run_id: int):
        return self._request(f'repos/{REPOSITORY}/actions/runs/{positive_id(run_id)}/rerun-failed-jobs', method='POST')
