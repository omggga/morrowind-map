"""Trusted review orchestration: candidate Git objects are data, never executable code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from tools.deployment.common import DeploymentError, canonical_json_bytes, require_sha256, strict_json_object
from tools.deployment.dataset_packages import MAX_LOCK_BYTES, REPOSITORY, _entry_key, _real_directory, read_tile_sets
from tools.deployment.dataset_publication import publish_packages
from tools.deployment.dataset_review_api import ReleaseAPI, positive_id
from tools.deployment.dataset_review_sources import parse_sources, restore_snapshot
from tools.deployment.git_datasets import GitDatasetError, _git, _git_env, check_revision, export_revision
from tools.deployment.review_datasets import review_datasets
from tools.deployment.upload_datasets import build_dataset_plan


def digest(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{40}', value):
        raise DeploymentError('Expected a full lowercase commit SHA')
    return value


def _read(path: Path, maximum=MAX_LOCK_BYTES) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise DeploymentError('Review document must be a bounded regular file')
    return strict_json_object(path.read_bytes(), 'review document')


def _write(path: Path, value) -> None:
    _real_directory(path.parent)
    if path.exists() or path.is_symlink():
        raise DeploymentError('Review output already exists; use a fresh work directory')
    path.write_bytes(canonical_json_bytes(value))


def _pull(api, number: int) -> tuple[str, str]:
    pr = api.get_pull(positive_id(number))
    if not isinstance(pr, dict) or type(pr.get('number')) is not int or pr['number'] != number:
        raise DeploymentError('Review requires a matching PR identity')
    base, head_record = pr.get('base'), pr.get('head')
    if (not isinstance(base, dict) or not isinstance(head_record, dict)
            or base.get('ref') != 'main' or not isinstance(base.get('repo'), dict)
            or base['repo'].get('full_name') != REPOSITORY):
        raise DeploymentError('Review requires a PR into this repository main')
    head = sha(head_record.get('sha'))
    if pr.get('state') == 'open' and pr.get('merged') is False:
        return head, sha(base.get('sha'))
    if pr.get('state') != 'closed' or pr.get('merged') is not True:
        raise DeploymentError('Review requires an open or merged PR, not an unmerged closed PR')
    merge_sha = sha(api.get_pull_merge_sha(number))
    merge = api.get_commit(merge_sha)
    parents = merge.get('parents') if isinstance(merge, dict) else None
    if (not isinstance(merge, dict) or merge.get('sha') != merge_sha
            or not isinstance(parents, list) or len(parents) != 2
            or not all(isinstance(parent, dict) for parent in parents)
            or parents[1].get('sha') != head):
        raise DeploymentError('Merged PR must identify a two-parent merge commit with its exact head')
    # The live base branch may advance after merging. The deployment gate also
    # binds to this immutable first parent, never to the current branch tip.
    return head, sha(parents[0].get('sha'))


def freeze(*, api, pr_number: int, bootstrap_sha: str, tool_sha: str,
           run_id: int, run_attempt: int, sources: bytes,
           expected_head: str, expected_base: str) -> dict:
    sha(tool_sha)
    positive_id(run_id)
    positive_id(run_attempt)
    mapping = parse_sources(sources)
    if pr_number and bootstrap_sha or not pr_number and not bootstrap_sha:
        raise DeploymentError('Select exactly one PR number or bootstrap commit')
    if pr_number:
        head, base = _pull(api, pr_number)
        if (head, base) != (sha(expected_head), sha(expected_base)):
            raise DeploymentError('PR differs from the dispatch head/base; refresh both SHAs and start a new review')
    else:
        if expected_head or expected_base:
            raise DeploymentError('Bootstrap must not include PR head/base inputs')
        head, base = sha(bootstrap_sha), None
    return {'schemaVersion': 2, 'repository': REPOSITORY, 'prNumber': pr_number or None,
            'headSha': head, 'baseSha': base, 'toolSha': tool_sha, 'runId': run_id,
            'runAttempt': run_attempt, 'sources': mapping, 'sourceMappingSha256': digest(mapping),
            'mode': 'pull-request' if pr_number else 'bootstrap'}


def _context(context: dict) -> None:
    if set(context) != {'schemaVersion', 'repository', 'prNumber', 'headSha', 'baseSha', 'toolSha',
                        'runId', 'runAttempt', 'sources', 'sourceMappingSha256', 'mode'}:
        raise DeploymentError('Frozen review context has unexpected fields')
    if type(context['schemaVersion']) is not int or context['schemaVersion'] != 2 or context['repository'] != REPOSITORY:
        raise DeploymentError('Frozen review context is invalid')
    for field in ('headSha', 'toolSha'):
        sha(context[field])
    if context['mode'] == 'pull-request':
        positive_id(context['prNumber'])
        sha(context['baseSha'])
    elif context['mode'] != 'bootstrap' or context['prNumber'] is not None or context['baseSha'] is not None:
        raise DeploymentError('Review mode does not match its PR/base identity')
    positive_id(context['runId'])
    positive_id(context['runAttempt'])
    parse_sources(canonical_json_bytes(context['sources']))
    if digest(context['sources']) != context['sourceMappingSha256']:
        raise DeploymentError('Review source mapping is invalid')


def _still_current(context: dict, api) -> None:
    if context['prNumber'] and _pull(api, context['prNumber']) != (context['headSha'], context['baseSha']):
        raise DeploymentError('PR head or base changed; start a fresh trusted review')


def _fetch(repo_root: Path, reference: str) -> None:
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', "credential.helper=!gh auth git-credential",
               'fetch', '--no-tags', f'https://github.com/{REPOSITORY}.git', reference]
    result = subprocess.run(command, cwd=repo_root, env=_git_env(), capture_output=True, timeout=1200, check=False)
    if result.returncode:
        raise DeploymentError('Trusted Git fetch failed; check access and retry')


def prepare_review(*, repo_root: Path, work_root: Path, context: dict, api) -> dict:
    _context(context)
    _still_current(context, api)
    # The workflow checks out this exact trusted revision in every job.
    if _git(repo_root, 'rev-parse', 'HEAD').decode().strip() != context['toolSha']:
        raise DeploymentError('Checked-out tools differ from the frozen trusted revision')
    if context['prNumber']:
        _fetch(repo_root, f'refs/pull/{context["prNumber"]}/head')
        if _git(repo_root, 'rev-parse', 'FETCH_HEAD').decode().strip() != context['headSha']:
            raise DeploymentError('Fetched PR head changed; restart the review')
        _fetch(repo_root, 'refs/heads/main')
    else:
        # Bootstrap only a known baseline in trusted main history, never a branch's code.
        if _git(repo_root, 'merge-base', context['headSha'], context['toolSha']).decode().strip() != context['headSha']:
            raise DeploymentError('Bootstrap baseline must be an ancestor of trusted main')
    work = _real_directory(work_root)
    records = {}
    package_records = {}
    seen_sources = set()
    for label, revision in [('head', context['headSha']), ('base', context['baseSha'])]:
        if revision is None:
            records[label] = None
            continue
        check_revision(repo_root=repo_root, revision=revision)
        public = work / label / 'public'
        export_revision(repo_root=repo_root, revision=revision, output_public_root=public)
        plan_path = public / 'config/dataset-upload-plan.json'
        expected_plan = _read(plan_path)
        # Budget data plus an archive before hydration. Archives are discarded as
        # soon as their part verifies; only the two extracted snapshots coexist.
        tile_sets = read_tile_sets(public_root=public)
        needed = sum(t.byte_count for s in tile_sets for t in s.tiles)
        if shutil.disk_usage(work).free < needed + min(needed + 10_000_000, 2_147_483_648):
            raise DeploymentError('Insufficient runner space for snapshot and one archive')
        keys = {s.key for s in tile_sets}
        sources = [s for s in context['sources'] if _entry_key(s) in keys]
        seen_sources.update(_entry_key(s) for s in sources)
        lock_path = public / 'config/dataset-releases.lock.json'
        restored = restore_snapshot(public_root=public, lock_path=lock_path,
                                     sources=sources, api=api, cache_root=work / 'archive-cache')
        for package in restored['packages']:
            key = (*_entry_key(package['entry']), package['entry']['releaseTag'])
            existing = package_records.get(key)
            if existing is not None and existing != package:
                raise DeploymentError('Same tile inventory resolved to conflicting source packages')
            package_records[key] = package
        plan = build_dataset_plan(public_root=public)
        if plan != expected_plan:
            raise DeploymentError('Restored snapshot differs from its own committed upload plan')
        lock_path = public / 'config/dataset-releases.lock.json'
        records[label] = {'public': public, 'graph': plan['graphSha256'],
                          'lock': hashlib.sha256(lock_path.read_bytes()).hexdigest()}
    if seen_sources != {_entry_key(s) for s in context['sources']}:
        raise DeploymentError('Source mapping includes a map outside the reviewed snapshots')
    _still_current(context, api)
    base = records['base']
    review_datasets(candidate_public_root=records['head']['public'], output_dir=work / 'report',
                    candidate_sha=context['headSha'], base_public_root=base['public'] if base else None,
                    base_sha=context['baseSha'])
    receipt = {**context, 'headLockSha256': records['head']['lock'], 'baseLockSha256': base['lock'] if base else None,
               'headGraphSha256': records['head']['graph'], 'baseGraphSha256': base['graph'] if base else None,
               'packages': [package_records[k] for k in sorted(package_records)]}
    _write(work / 'report/receipt.json', receipt)
    return receipt


def promote_review(*, receipt_path: Path, receipt_sha: str, work_root: Path, api,
                   tool_sha: str, run_id: int, run_attempt: int) -> dict:
    receipt = _read(receipt_path)
    require_sha256(receipt_sha, 'receipt SHA-256')
    if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != receipt_sha or digest(receipt) != receipt_sha:
        raise DeploymentError('Review artifact differs from the trusted receipt digest')
    context_keys = {'schemaVersion', 'repository', 'prNumber', 'headSha', 'baseSha', 'toolSha',
                    'runId', 'runAttempt', 'sources', 'sourceMappingSha256', 'mode'}
    if set(receipt) != context_keys | {'headLockSha256', 'baseLockSha256', 'headGraphSha256', 'baseGraphSha256', 'packages'}:
        raise DeploymentError('Review receipt fields are invalid')
    _context({key: receipt[key] for key in context_keys})
    if (receipt['toolSha'], receipt['runId'], receipt['runAttempt']) != (sha(tool_sha), run_id, run_attempt):
        raise DeploymentError('Receipt belongs to a different trusted workflow attempt')
    for name in ('headGraphSha256', 'baseGraphSha256', 'headLockSha256', 'baseLockSha256'):
        if receipt[name] is not None:
            require_sha256(receipt[name], name)
    _still_current(receipt, api)
    publications = publish_packages(receipt['packages'], api=api, work_root=work_root / 'packages', tool_sha=tool_sha)
    _still_current(receipt, api)
    binding_keys = context_keys - {'sources', 'mode'}
    binding = {key: receipt[key] for key in binding_keys}
    binding.update({key: receipt[key] for key in ('headLockSha256', 'baseLockSha256', 'headGraphSha256', 'baseGraphSha256')})
    binding.update(receiptSha256=receipt_sha, publicationSha256=digest(publications))
    _write(work_root / 'result/binding.json', binding)
    _write(work_root / 'result/publication.json', publications)
    _write(work_root / 'result/receipt.json', receipt)
    return binding


def finish_review(*, api, pr_number: int, head_sha: str, run_id: int, run_attempt: int,
                  tool_sha: str, success: bool, binding_path: Path | None = None, receipt_sha: str = '') -> bool:
    sha(head_sha)
    positive_id(run_id)
    positive_id(run_attempt)
    if not pr_number:
        return success  # Bootstrap has no PR status to attach.
    positive_id(pr_number)
    binding = None
    if success:
        try:
            binding = _read(binding_path, 16384)
            if (binding['prNumber'], binding['headSha'], binding['runId'], binding['runAttempt'], binding['toolSha'], binding['receiptSha256']) != (pr_number, head_sha, run_id, run_attempt, tool_sha, receipt_sha):
                raise DeploymentError('Publication result binding differs from this review')
            if _pull(api, pr_number) != (head_sha, binding['baseSha']):
                raise DeploymentError('PR head or base changed after publication')
            from tools.deployment.require_dataset_review import _binding
            _binding({'output': {'text': json.dumps(binding)}})
        except (DeploymentError, ValueError, KeyError, OSError, TypeError):
            success = False
    url = f'https://github.com/{REPOSITORY}/actions/runs/{run_id}'
    payload = {'name': 'Dataset review (trusted)', 'head_sha': head_sha, 'status': 'completed',
               'conclusion': 'success' if success else 'failure', 'details_url': url,
               'external_id': f'dataset-review:{run_id}:{run_attempt}:{receipt_sha}' if success else f'dataset-review:{run_id}',
               'output': {'title': 'Dataset data review', 'summary': 'Trusted validation and publication: ' + url}}
    if success:
        payload['output']['text'] = canonical_json_bytes(binding).decode()
    api.create_check(payload)
    return success


def _outputs(**values) -> None:
    if path := os.environ.get('GITHUB_OUTPUT'):
        with open(path, 'a') as output:
            for key, value in values.items():
                output.write(f'{key}={value}\n')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze', 'review', 'publish', 'finish'))
    parser.add_argument('--repo-root', type=Path, default=Path.cwd())
    parser.add_argument('--work-root', type=Path, required=True)
    args = parser.parse_args(argv)
    env = os.environ
    api = ReleaseAPI(writable=args.command in ('publish', 'finish'))
    try:
        tool_sha, run_id, attempt = sha(env['GITHUB_SHA']), int(env['GITHUB_RUN_ID']), int(env['GITHUB_RUN_ATTEMPT'])
        if env.get('GITHUB_REPOSITORY') != REPOSITORY or env.get('GITHUB_REF') != 'refs/heads/main':
            raise DeploymentError('Dataset workflow must run from trusted canonical main')
        if _git(args.repo_root, 'rev-parse', 'HEAD').decode().strip() != tool_sha:
            raise DeploymentError('Workflow must execute the pinned trusted tools')
        if args.command == 'freeze':
            context = freeze(api=api, pr_number=int(env.get('PR_NUMBER') or 0), bootstrap_sha=env.get('BOOTSTRAP_SHA', ''),
                             tool_sha=tool_sha, run_id=run_id, run_attempt=attempt,
                             expected_head=env.get('EXPECTED_HEAD', ''), expected_base=env.get('EXPECTED_BASE', ''),
                             sources=env.get('SOURCE_MAPPING', '[]').encode())
            _write(args.work_root / 'context.json', context)
            _outputs(candidate_sha=context['headSha'], pr_number=context['prNumber'] or 0)
        elif args.command == 'review':
            receipt = prepare_review(repo_root=args.repo_root, work_root=args.work_root,
                                     context=_read(args.work_root / 'context.json'), api=api)
            _outputs(receipt_sha=digest(receipt))
        elif args.command == 'publish':
            promote_review(receipt_path=args.work_root / 'input/receipt.json', receipt_sha=env['RECEIPT_SHA'],
                           work_root=args.work_root, api=api, tool_sha=tool_sha, run_id=run_id, run_attempt=attempt)
        else:
            success = finish_review(api=api, pr_number=int(env['PR_NUMBER']), head_sha=env['CANDIDATE_SHA'],
                                    run_id=run_id, run_attempt=attempt, tool_sha=tool_sha,
                                    success=env.get('PUBLICATION_SUCCESS') == 'true', receipt_sha=env.get('RECEIPT_SHA', ''),
                                    binding_path=args.work_root / 'binding.json')
            return 0 if success else 1
    except (DeploymentError, GitDatasetError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, (DeploymentError, GitDatasetError)) else 'Invalid workflow context or failed local operation'
        print('Trusted dataset review: ' + message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
