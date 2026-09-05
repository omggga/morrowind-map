from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools.deployment import require_dataset_review as review


class DatasetReviewGateTests(unittest.TestCase):
    repo = "owner/morrowind-map"
    commit = "a" * 40
    head = "b" * 40

    def setUp(self) -> None:
        self.pr = {
            "number": 17, "state": "closed", "merged_at": "2026-09-05T10:00:00Z",
            "merge_commit_sha": self.commit,
            "base": {"ref": "main", "repo": {"full_name": self.repo}},
            "head": {"sha": self.head},
        }
        self.check = {
            "id": 30, "name": "Dataset review (trusted)", "head_sha": self.head,
            "app": {"slug": "github-actions"}, "status": "completed",
            "conclusion": "success", "external_id": "dataset-review:1234",
        }
        self.run = {
            "id": 1234, "repository": {"full_name": self.repo},
            "path": ".github/workflows/dataset-review.yml", "event": "workflow_dispatch",
            "head_branch": "main", "status": "completed", "conclusion": "success",
        }
        self.pulls = [[self.pr]]
        self.check_pages = [{"check_runs": [self.check]}]
        self.calls: list[str] = []

    def fake_api(self, endpoint: str, *, paginate: bool = False) -> object:
        self.calls.append(endpoint)
        if endpoint.endswith("/pulls?per_page=100"):
            self.assertTrue(paginate)
            return self.pulls
        if "/check-runs?" in endpoint:
            self.assertTrue(paginate)
            self.assertIn(self.head, endpoint)
            self.assertIn("filter=all", endpoint)
            return self.check_pages
        self.assertFalse(paginate)
        self.assertEqual(endpoint, f"repos/{self.repo}/actions/runs/1234")
        return self.run

    def require(self) -> dict[str, object]:
        with patch.object(review, "_gh_api", side_effect=self.fake_api):
            return review.require_dataset_review(repo=self.repo, commit=self.commit)

    def test_accepts_exact_merged_head_and_verified_trusted_run(self) -> None:
        result = self.require()
        self.assertEqual(result, {"repository": self.repo, "commit": self.commit, "pullRequest": 17, "headSha": self.head, "checkRunId": 30, "reviewRunId": 1234})
        self.assertEqual(len(self.calls), 3)
        self.run["path"] += "@refs/heads/main"
        self.require()

    def test_requires_merged_pr_for_exact_commit_into_same_repository_main(self) -> None:
        for key, value in (("merge_commit_sha", "c" * 40), ("merged_at", None), ("state", "open"), ("base", {"ref": "dev", "repo": {"full_name": self.repo}}), ("base", {"ref": "main", "repo": {"full_name": "other/repo"}})):
            with self.subTest(key=key, value=value):
                original = self.pr[key]
                self.pr[key] = value
                with self.assertRaisesRegex(review.DatasetReviewError, "merged PR"):
                    self.require()
                self.pr[key] = original
        self.pulls = [[]]
        with self.assertRaisesRegex(review.DatasetReviewError, "merged PR"):
            self.require()

    def test_rejects_spoofed_app_wrong_head_missing_external_id_and_unsuccessful_check(self) -> None:
        for key, value in (("app", {"slug": "untrusted-app"}), ("head_sha", "c" * 40), ("external_id", "1234"), ("external_id", "dataset-review:1234/../9"), ("conclusion", "failure"), ("status", "in_progress")):
            with self.subTest(key=key, value=value):
                original = self.check[key]
                self.check[key] = value
                with self.assertRaises(review.DatasetReviewError):
                    self.require()
                self.check[key] = original

    def test_newest_failure_blocks_older_success_across_pages(self) -> None:
        newer = {**self.check, "id": 31, "conclusion": "failure"}
        self.check_pages = [{"check_runs": [self.check]}, {"check_runs": [newer]}]
        with self.assertRaisesRegex(review.DatasetReviewError, "newest.*successful"):
            self.require()
        self.check_pages.reverse()
        with self.assertRaises(review.DatasetReviewError):
            self.require()

    def test_old_success_remains_usable_without_newer_matching_review(self) -> None:
        unrelated = {**self.check, "id": 31, "name": "Other check", "conclusion": "failure"}
        self.check_pages[0]["check_runs"].append(unrelated)
        self.assertEqual(self.require()["checkRunId"], 30)

    def test_rejects_run_from_wrong_repository_workflow_event_branch_or_conclusion(self) -> None:
        for key, value in (("id", 9), ("repository", {"full_name": "other/repo"}), ("path", ".github/workflows/ci.yml"), ("event", "pull_request_target"), ("head_branch", "candidate"), ("status", "in_progress"), ("conclusion", "failure")):
            with self.subTest(key=key, value=value):
                original = self.run[key]
                self.run[key] = value
                with self.assertRaisesRegex(review.DatasetReviewError, "trusted workflow run"):
                    self.require()
                self.run[key] = original

    def test_rejects_invalid_inputs_before_calling_github(self) -> None:
        for repo, commit in (("owner/repo/../secret", self.commit), ("-owner/repo", self.commit), (self.repo, "HEAD"), (self.repo, "a" * 39)):
            with self.subTest(repo=repo, commit=commit), patch.object(review, "_gh_api") as api:
                with self.assertRaises(review.DatasetReviewError):
                    review.require_dataset_review(repo=repo, commit=commit)
                api.assert_not_called()

    def test_gh_adapter_uses_get_with_pagination_and_fails_closed(self) -> None:
        response = SimpleNamespace(returncode=0, stdout=json.dumps(self.pulls), stderr="")
        with patch.object(review.subprocess, "run", return_value=response) as run:
            self.assertEqual(review._gh_api("repos/owner/repo/commits/sha/pulls", paginate=True), self.pulls)
            argv = run.call_args.args[0]
            self.assertEqual(argv[:4], ["gh", "api", "--hostname", "github.com"])
            self.assertIn("--paginate", argv)
            self.assertIn("--slurp", argv)
            self.assertNotIn("POST", argv)
        response.returncode = 1
        response.stderr = "not authorized"
        with patch.object(review.subprocess, "run", return_value=response), self.assertRaisesRegex(review.DatasetReviewError, "GitHub API"):
            review._gh_api("repos/owner/repo")


if __name__ == "__main__":
    unittest.main()
