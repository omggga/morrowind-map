from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from tools.deployment.common import DeploymentError
from tools.deployment.dataset_packages import REPOSITORY
from tools.deployment import dataset_review_retry as retry


class FakeAPI:
    def __init__(self):
        self.head, self.base, self.tool = 'a' * 40, 'b' * 40, 'c' * 40
        self.pull = {'number': 17, 'state': 'open', 'merged': False,
                     'head': {'sha': self.head},
                     'base': {'sha': self.base, 'ref': 'main', 'repo': {'full_name': REPOSITORY}}}
        self.binding = {'schemaVersion': 2, 'repository': REPOSITORY, 'prNumber': 17,
                        'headSha': self.head, 'baseSha': self.base, 'toolSha': self.tool,
                        'runId': 200, 'runAttempt': 2, 'headLockSha256': '1' * 64,
                        'baseLockSha256': None, 'headGraphSha256': '2' * 64,
                        'baseGraphSha256': '3' * 64, 'sourceMappingSha256': '4' * 64,
                        'receiptSha256': '5' * 64, 'publicationSha256': '6' * 64}
        self.check = {'id': 300, 'name': retry.CHECK_NAME, 'app': {'slug': 'github-actions'},
                      'head_sha': self.head, 'status': 'completed', 'conclusion': 'success',
                      'external_id': 'dataset-review:200:2:' + '5' * 64,
                      'output': {'text': json.dumps(self.binding)}}
        self.checks = [self.check]
        self.runs = {
            100: {'id': 100, 'repository': {'full_name': REPOSITORY}, 'run_attempt': 1,
                  'head_sha': self.head, 'path': retry.CI_WORKFLOW_PATH, 'event': 'pull_request',
                  'status': 'completed', 'conclusion': 'failure', 'pull_requests': [{'number': 17}]},
            200: {'id': 200, 'repository': {'full_name': REPOSITORY}, 'run_attempt': 2,
                  'head_sha': self.tool, 'path': retry.WORKFLOW_PATH, 'event': 'workflow_dispatch',
                  'head_branch': 'main', 'status': 'completed', 'conclusion': 'success',
                  'display_title': retry.review_run_title(17, self.head, self.base)},
        }
        self.calls = []
        self.writes = []
        self.on_call = lambda operation, argument: None

    def call(self, operation, argument):
        self.calls.append((operation, argument))
        self.on_call(operation, argument)

    def get_pull(self, number):
        self.call('pull', number)
        return copy.deepcopy(self.pull)

    def get_run(self, number):
        self.call('run', number)
        return copy.deepcopy(self.runs[number])

    def list_checks(self, head):
        self.call('checks', head)
        return copy.deepcopy(self.checks)

    def rerun_failed_jobs(self, number):
        self.call('rerun', number)
        self.writes.append(number)


class DatasetReviewRetryTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()

    def run_retry(self):
        return retry.retry_failed_jobs(api=self.api, pr_number=17, run_id=100)

    def reject(self):
        with self.assertRaises(DeploymentError):
            self.run_retry()
        self.assertEqual(self.api.writes, [])

    def test_retries_only_failed_jobs_after_two_fresh_identity_checks(self):
        result = self.run_retry()
        self.assertEqual(self.api.writes, [100])
        self.assertEqual(result['status'], 'rerun-requested')
        self.assertEqual(result['reviewRunAttempt'], 2)
        self.assertEqual(result['receiptSha256'], '5' * 64)
        self.assertEqual(self.api.calls, [
            ('pull', 17), ('run', 100), ('checks', self.api.head), ('run', 200),
            ('pull', 17), ('run', 100), ('checks', self.api.head), ('run', 200), ('rerun', 100),
        ])

    def test_cancelled_and_timed_out_runs_can_be_retried(self):
        for conclusion in ('cancelled', 'timed_out'):
            with self.subTest(conclusion=conclusion):
                self.api = FakeAPI()
                self.api.runs[100]['conclusion'] = conclusion
                self.run_retry()
                self.assertEqual(self.api.writes, [100])

    def test_invalid_ids_never_call_api(self):
        for number, run_id in ((0, 100), (True, 100), (17, -1), (17, 2**63)):
            with self.subTest(number=number, run=run_id), self.assertRaises(DeploymentError):
                retry.retry_failed_jobs(api=self.api, pr_number=number, run_id=run_id)
        self.assertEqual(self.api.calls, [])

    def test_requires_current_open_canonical_main_pr(self):
        changes = [('number', 18), ('state', 'closed'), ('merged', True),
                   ('head', {'sha': 'HEAD'}),
                   ('base', {'sha': self.api.base, 'ref': 'dev', 'repo': {'full_name': REPOSITORY}}),
                   ('base', {'sha': self.api.base, 'ref': 'main', 'repo': {'full_name': 'fork/repo'}})]
        for key, value in changes:
            with self.subTest(key=key):
                self.api = FakeAPI()
                self.api.pull[key] = value
                self.reject()

    def test_requires_failed_ci_run_for_same_head_pr_and_repository(self):
        changes = [('id', 101), ('repository', {'full_name': 'fork/repo'}), ('head_sha', 'd' * 40),
                   ('path', '.github/workflows/deploy.yml'), ('event', 'pull_request_target'),
                   ('status', 'in_progress'), ('conclusion', 'success'), ('run_attempt', True),
                   ('pull_requests', []), ('pull_requests', [{'number': 18}]), ('pull_requests', None)]
        for key, value in changes:
            with self.subTest(key=key):
                self.api = FakeAPI()
                self.api.runs[100][key] = value
                self.reject()

    def test_requires_successful_latest_github_actions_v2_check(self):
        changes = [('app', {'slug': 'someone-else'}), ('head_sha', 'd' * 40),
                   ('status', 'in_progress'), ('conclusion', 'failure'),
                   ('external_id', 'dataset-review:200'), ('external_id', 'dataset-review:200:2:bad'),
                   ('output', {'text': '{}'}), ('output', None)]
        for key, value in changes:
            with self.subTest(key=key):
                self.api = FakeAPI()
                self.api.check[key] = value
                self.reject()
        self.api = FakeAPI()
        self.api.checks.append({**self.api.check, 'id': 301, 'conclusion': 'failure'})
        self.reject()
        self.api.checks.reverse()
        self.reject()

    def test_ignores_newer_unrelated_checks(self):
        self.api.checks.append({**self.api.check, 'id': 301, 'name': 'Other check', 'conclusion': 'failure'})
        self.run_retry()
        self.assertEqual(self.api.writes, [100])

    def test_rejects_binding_head_base_receipt_and_run_mismatches(self):
        changes = [('repository', 'fork/repo'), ('prNumber', 18), ('headSha', 'd' * 40),
                   ('baseSha', 'd' * 40), ('runId', 201), ('runAttempt', 3),
                   ('receiptSha256', '7' * 64), ('publicationSha256', None)]
        for key, value in changes:
            with self.subTest(key=key):
                self.api = FakeAPI()
                self.api.binding[key] = value
                self.api.check['output']['text'] = json.dumps(self.api.binding)
                self.reject()

    def test_requires_successful_same_repository_main_review_attempt_and_tools(self):
        changes = [('id', 201), ('repository', {'full_name': 'fork/repo'}), ('head_sha', 'd' * 40),
                   ('run_attempt', 3), ('run_attempt', 2.0), ('head_branch', 'candidate'),
                   ('path', retry.CI_WORKFLOW_PATH), ('event', 'push'),
                   ('status', 'in_progress'), ('conclusion', 'failure')]
        for key, value in changes:
            with self.subTest(key=key):
                self.api = FakeAPI()
                self.api.runs[200][key] = value
                self.reject()

    def test_detects_pr_changes_during_preflight(self):
        for revision in ('head', 'base'):
            with self.subTest(revision=revision):
                self.api = FakeAPI()

                def change(operation, argument):
                    if operation == 'pull' and self.api.calls.count(('pull', 17)) == 2:
                        self.api.pull[revision]['sha'] = 'd' * 40

                self.api.on_call = change
                self.reject()

    def test_rejects_forged_check_binding_to_unrelated_successful_run(self):
        for title in (None, 'Dataset review', retry.review_run_title(18, self.api.head, self.api.base),
                      retry.review_run_title(17, 'd' * 40, self.api.base),
                      retry.review_run_title(17, self.api.head, 'd' * 40)):
            with self.subTest(title=title):
                self.api = FakeAPI()
                self.api.runs[200]['display_title'] = title
                self.reject()

    def test_detects_ci_attempt_or_state_changes_during_preflight(self):
        for field, value in (('run_attempt', 2), ('status', 'queued'), ('head_sha', 'd' * 40)):
            with self.subTest(field=field):
                self.api = FakeAPI()

                def change(operation, argument):
                    if operation == 'run' and argument == 100 and self.api.calls.count(('run', 100)) == 2:
                        self.api.runs[100][field] = value

                self.api.on_call = change
                self.reject()

    def test_detects_new_review_or_changed_review_attempt_during_preflight(self):
        for change_run in (False, True):
            with self.subTest(change_run=change_run):
                self.api = FakeAPI()

                def change(operation, argument):
                    if operation == 'checks' and self.api.calls.count(('checks', self.api.head)) == 2:
                        if change_run:
                            self.api.runs[200]['run_attempt'] = 3
                        else:
                            self.api.checks.append({**self.api.check, 'id': 301})

                self.api.on_call = change
                self.reject()

    def test_cli_requests_write_api_only_for_explicit_invocation(self):
        with patch.object(retry, 'ReleaseAPI', return_value=self.api) as api, \
                patch.object(retry.sys, 'argv', ['retry', '--pr-number', '17', '--run-id', '100']), \
                patch('builtins.print'):
            self.assertEqual(retry.main(), 0)
        api.assert_called_once_with(writable=True)
        self.assertEqual(self.api.writes, [100])


if __name__ == '__main__':
    unittest.main()
