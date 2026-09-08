"""Manually rerun failed CI jobs after publication for the same reviewed PR head."""

from __future__ import annotations

import argparse
import json
import sys

from tools.deployment.common import DeploymentError
from tools.deployment.dataset_packages import REPOSITORY
from tools.deployment.dataset_review_api import ReleaseAPI, positive_id
from tools.deployment.require_dataset_review import (
    CHECK_NAME,
    WORKFLOW_PATH,
    DatasetReviewError,
    _EXTERNAL_ID,
    _SHA,
    _binding,
    review_run_title,
)


CI_WORKFLOW_PATH = '.github/workflows/ci.yml'


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise DeploymentError(f'{label} must be an object')
    return value


def _sha(value: object) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise DeploymentError('PR revisions must be full lowercase commit SHAs')
    return value


def _pull(api, number: int) -> tuple[str, str]:
    pr = _object(api.get_pull(number), 'PR')
    base = _object(pr.get('base'), 'PR base')
    if (type(pr.get('number')) is not int or pr['number'] != number or pr.get('state') != 'open'
            or pr.get('merged') is True or base.get('ref') != 'main'
            or _object(base.get('repo'), 'PR repository').get('full_name') != REPOSITORY):
        raise DeploymentError('Retry requires a current open PR into the canonical repository main')
    return _sha(_object(pr.get('head'), 'PR head').get('sha')), _sha(base.get('sha'))


def _ci_run(api, run_id: int, number: int, head: str) -> dict:
    run = _object(api.get_run(run_id), 'CI run')
    associated = run.get('pull_requests')
    if (positive_id(run.get('id')) != run_id
            or _object(run.get('repository'), 'CI repository').get('full_name') != REPOSITORY
            or not isinstance(run.get('path'), str) or run['path'].split('@', 1)[0] != CI_WORKFLOW_PATH
            or run.get('event') != 'pull_request' or run.get('head_sha') != head
            or run.get('status') != 'completed' or run.get('conclusion') not in ('failure', 'timed_out', 'cancelled')
            or not isinstance(associated, list)
            or not any(isinstance(pr, dict) and type(pr.get('number')) is int and pr['number'] == number for pr in associated)):
        raise DeploymentError('Retry target must be a failed completed CI run for this exact current PR head')
    positive_id(run.get('run_attempt'))
    return run


def _review(api, number: int, head: str, base: str) -> tuple[int, dict]:
    values = api.list_checks(head)
    if not isinstance(values, list) or len(values) > 10_000:
        raise DeploymentError('Review check listing is invalid or unbounded')
    checks = []
    for value in values:
        check = _object(value, 'Review check')
        if (check.get('name') == CHECK_NAME
                and _object(check.get('app'), 'Check app').get('slug') == 'github-actions'):
            positive_id(check.get('id'))
            checks.append(check)
    if not checks:
        raise DeploymentError('No trusted dataset review exists for this head; run a fresh review first')
    check = max(checks, key=lambda item: item['id'])
    external = check.get('external_id')
    matched = _EXTERNAL_ID.fullmatch(external) if isinstance(external, str) else None
    if (check.get('head_sha') != head or check.get('status') != 'completed'
            or check.get('conclusion') != 'success' or matched is None or matched[2] is None):
        raise DeploymentError('The newest trusted review must successfully bind v2 review and publication')
    try:
        binding = _binding(check)
    except DatasetReviewError as error:
        raise DeploymentError(str(error)) from error
    if (binding['repository'] != REPOSITORY or binding['prNumber'] != number
            or binding['headSha'] != head or binding['baseSha'] != base
            or binding['runId'] != int(matched[1]) or binding['runAttempt'] != int(matched[2])
            or binding['receiptSha256'] != matched[3]):
        raise DeploymentError('Review binding differs from the current PR head/base or review run; start a fresh review')
    run = _object(api.get_run(positive_id(binding['runId'])), 'Trusted review run')
    if (positive_id(run.get('id')) != binding['runId']
            or _object(run.get('repository'), 'Review repository').get('full_name') != REPOSITORY
            or not isinstance(run.get('path'), str) or run['path'].split('@', 1)[0] != WORKFLOW_PATH
            or run.get('event') != 'workflow_dispatch' or run.get('head_branch') != 'main'
            or run.get('status') != 'completed' or run.get('conclusion') != 'success'
            or type(run.get('run_attempt')) is not int or run['run_attempt'] != binding['runAttempt']
            or run.get('head_sha') != binding['toolSha']
            or run.get('display_title') != review_run_title(number, head, base)):
        raise DeploymentError('Review check must reference the same successful trusted main workflow attempt/tool revision')
    return check['id'], binding


def retry_failed_jobs(*, api, pr_number: int, run_id: int) -> dict:
    """Request one explicit retry; no credentials are added to review workflows."""
    positive_id(pr_number)
    positive_id(run_id)
    head, base = _pull(api, pr_number)
    run = _ci_run(api, run_id, pr_number, head)
    check_id, binding = _review(api, pr_number, head, base)
    # Do not reuse a decision after a force push, base update, competing retry,
    # or newer review attempt. GitHub has no atomic compare-and-rerun endpoint;
    # the immutable run itself remains pinned to its original head at write time.
    if _pull(api, pr_number) != (head, base):
        raise DeploymentError('PR head or base changed during retry preflight; start a fresh review')
    fresh_run = _ci_run(api, run_id, pr_number, head)
    if fresh_run['run_attempt'] != run['run_attempt']:
        raise DeploymentError('CI run attempt changed during retry preflight; inspect its current result')
    if _review(api, pr_number, head, base) != (check_id, binding):
        raise DeploymentError('Newest trusted review changed during retry preflight; inspect its current result')
    api.rerun_failed_jobs(run_id)
    return {'repository': REPOSITORY, 'prNumber': pr_number, 'headSha': head,
            'ciRunId': run_id, 'previousRunAttempt': run['run_attempt'], 'checkRunId': check_id,
            'reviewRunId': binding['runId'], 'reviewRunAttempt': binding['runAttempt'],
            'receiptSha256': binding['receiptSha256'], 'status': 'rerun-requested'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pr-number', required=True, type=int)
    parser.add_argument('--run-id', required=True, type=int)
    args = parser.parse_args()
    try:
        result = retry_failed_jobs(api=ReleaseAPI(writable=True), pr_number=args.pr_number, run_id=args.run_id)
    except DeploymentError as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
