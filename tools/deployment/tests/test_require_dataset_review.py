from __future__ import annotations

import base64
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools.deployment import require_dataset_review as review


class DatasetReviewGateTests(unittest.TestCase):
    repo = "owner/morrowind-map"
    commit = "a" * 40
    head = "b" * 40
    base = "c" * 40
    tool = "d" * 40
    graph = "e" * 64

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
        self.snapshots: dict[str, tuple[bytes | None, str]] = {
            sha: (None, self.graph) for sha in (self.head, self.commit, self.base)
        }
        self.merge_base = self.base

    def snapshot_api(self) -> dict[str, object]:
        responses: dict[str, object] = {}
        for sha, (lock, graph) in self.snapshots.items():
            files = {"dataset-upload-plan.json": json.dumps({"graphSha256": graph}).encode()}
            if lock is not None:
                files["dataset-releases.lock.json"] = lock
            entries = []
            for path, payload in files.items():
                blob_sha = hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha, "size": len(payload)})
                responses[f"repos/{self.repo}/git/blobs/{blob_sha}"] = {
                    "sha": blob_sha, "size": len(payload), "encoding": "base64",
                    "content": base64.b64encode(payload).decode(),
                }
            config_sha = hashlib.sha1((sha + "config").encode()).hexdigest()
            root_sha = hashlib.sha1((sha + "root").encode()).hexdigest()
            responses[f"repos/{self.repo}/git/trees/{config_sha}"] = {"sha": config_sha, "truncated": False, "tree": entries}
            responses[f"repos/{self.repo}/git/trees/{root_sha}"] = {
                "sha": root_sha, "truncated": False,
                "tree": [{"path": "config", "mode": "040000", "type": "tree", "sha": config_sha}],
            }
            responses[f"repos/{self.repo}/git/commits/{sha}"] = {
                "sha": sha, "tree": {"sha": root_sha}, "parents": [{"sha": self.merge_base}],
            }
        return responses

    def use_binding(self, **changes: object) -> dict[str, object]:
        binding = {
            "schemaVersion": 2, "repository": self.repo, "prNumber": 17,
            "headSha": self.head, "baseSha": self.base, "toolSha": self.tool,
            "runId": 1234, "runAttempt": 2, "headLockSha256": None, "baseLockSha256": None,
            "headGraphSha256": self.graph, "baseGraphSha256": self.graph,
            "sourceMappingSha256": "1" * 64, "receiptSha256": "2" * 64,
            "publicationSha256": "3" * 64,
        }
        binding.update(changes)
        self.check["external_id"] = "dataset-review:1234:2:" + "2" * 64
        self.check["output"] = {"text": json.dumps(binding)}
        self.run.update({"run_attempt": 2, "head_sha": self.tool,
                         "display_title": review.review_run_title(17, self.head, self.base)})
        return binding

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
        snapshots = self.snapshot_api()
        if endpoint in snapshots:
            return snapshots[endpoint]
        self.assertEqual(endpoint, f"repos/{self.repo}/actions/runs/1234")
        return self.run

    def require(self) -> dict[str, object]:
        with patch.object(review, "_gh_api", side_effect=self.fake_api):
            return review.require_dataset_review(repo=self.repo, commit=self.commit)

    def test_accepts_exact_merged_head_and_verified_trusted_run(self) -> None:
        result = self.require()
        self.assertEqual(result, {"repository": self.repo, "commit": self.commit, "pullRequest": 17, "headSha": self.head, "checkRunId": 30, "reviewRunId": 1234})
        self.assertIn(f"repos/{self.repo}/git/commits/{self.base}", self.calls)
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

    def test_v2_durable_binding_works_without_report_artifacts(self) -> None:
        self.use_binding()
        result = self.require()
        self.assertEqual(result["reviewRunAttempt"], 2)
        self.assertEqual(result["receiptSha256"], "2" * 64)
        self.assertFalse(any("artifacts" in call for call in self.calls))
        # A mutable PR base field does not replace the immutable merge parent.
        self.pr["base"]["sha"] = "f" * 40
        self.require()

    def test_legacy_review_cannot_authorize_lock_deletion_from_release_base(self) -> None:
        self.snapshots[self.base] = (b'{"schemaVersion":2}', self.graph)
        with self.assertRaisesRegex(review.DatasetReviewError, "transport downgrade"):
            self.require()

    def test_v2_review_cannot_authorize_bound_lock_deletion(self) -> None:
        lock = b'{"schemaVersion":2}'
        self.snapshots[self.base] = (lock, self.graph)
        self.use_binding(baseLockSha256=hashlib.sha256(lock).hexdigest())
        with self.assertRaisesRegex(review.DatasetReviewError, "transport downgrade"):
            self.require()

    def test_v2_binds_head_merged_and_base_lock_bytes(self) -> None:
        lock = b'{"schemaVersion":1}\n'
        digest = hashlib.sha256(lock).hexdigest()
        for sha in self.snapshots:
            self.snapshots[sha] = (lock, self.graph)
        self.use_binding(headLockSha256=digest, baseLockSha256=digest)
        self.require()
        for sha in self.snapshots:
            for bad in (None, lock + b" "):
                with self.subTest(sha=sha, bad=bad):
                    self.snapshots[sha] = (bad, self.graph)
                    with self.assertRaisesRegex(review.DatasetReviewError, "lock or graph"):
                        self.require()
                    self.snapshots[sha] = (lock, self.graph)

    def test_v2_binds_graph_in_every_snapshot(self) -> None:
        self.use_binding()
        for sha in self.snapshots:
            with self.subTest(sha=sha):
                self.snapshots[sha] = (None, "f" * 64)
                with self.assertRaisesRegex(review.DatasetReviewError, "lock or graph"):
                    self.require()
                self.snapshots[sha] = (None, self.graph)

    def test_legacy_review_rejects_transport_lock_at_head_or_merge(self) -> None:
        for sha in (self.head, self.commit):
            with self.subTest(sha=sha):
                self.snapshots[sha] = (b"{}", self.graph)
                with self.assertRaisesRegex(review.DatasetReviewError, "Legacy review"):
                    self.require()
                self.snapshots[sha] = (None, self.graph)

    def test_v2_requires_exact_binding_fields_and_types(self) -> None:
        valid = self.use_binding()
        invalid = []
        for name in valid:
            invalid.append({key: value for key, value in valid.items() if key != name})
        invalid.append({**valid, "unexpected": True})
        for name, value in (
            ("schemaVersion", True), ("schemaVersion", 2.0), ("schemaVersion", 3),
            ("repository", []), ("prNumber", True), ("runId", "1234"), ("runAttempt", 2.0),
            ("headSha", "HEAD"), ("baseSha", None), ("toolSha", "D" * 40),
            ("headLockSha256", "bad"), ("baseLockSha256", 0), ("headGraphSha256", None),
            ("baseGraphSha256", "bad"), ("sourceMappingSha256", []),
            ("receiptSha256", "bad"), ("publicationSha256", None),
        ):
            invalid.append({**valid, name: value})
        for binding in invalid:
            with self.subTest(binding=binding):
                self.check["output"] = {"text": json.dumps(binding)}
                with self.assertRaises(review.DatasetReviewError):
                    self.require()
        for text in ("{}", "{", "[]", json.dumps(valid)[:-1] + ',"runId":1234}', "x" * (review.MAX_BINDING_BYTES + 1)):
            self.check["output"] = {"text": text}
            with self.assertRaises(review.DatasetReviewError):
                self.require()
        del self.check["output"]
        with self.assertRaises(review.DatasetReviewError):
            self.require()

    def test_v2_rejects_different_pr_run_attempt_receipt_and_tool_revision(self) -> None:
        for key, value in (("repository", "other/repo"), ("prNumber", 18), ("headSha", "f" * 40), ("runId", 1235), ("runAttempt", 3), ("receiptSha256", "4" * 64), ("toolSha", "f" * 40)):
            with self.subTest(key=key):
                self.use_binding(**{key: value})
                with self.assertRaisesRegex(review.DatasetReviewError, "binding does not match"):
                    self.require()
        for key, value in (("run_attempt", 3), ("run_attempt", 2.0), ("head_sha", "f" * 40)):
            with self.subTest(run=key):
                self.use_binding()
                self.run[key] = value
                with self.assertRaisesRegex(review.DatasetReviewError, "binding does not match"):
                    self.require()
        self.use_binding()
        del self.run["run_attempt"]
        with self.assertRaises(review.DatasetReviewError):
            self.require()

    def test_v2_rejects_different_immutable_merge_parent(self) -> None:
        self.use_binding()
        self.merge_base = "f" * 40
        with self.assertRaisesRegex(review.DatasetReviewError, "reviewed base SHA"):
            self.require()

    def test_v2_rejects_forged_check_binding_to_unrelated_successful_run(self) -> None:
        self.use_binding()
        for title in (None, "Dataset review", review.review_run_title(18, self.head, self.base),
                      review.review_run_title(17, "f" * 40, self.base),
                      review.review_run_title(17, self.head, "f" * 40),
                      review.review_run_title(17, self.head, self.base) + " extra"):
            with self.subTest(title=title):
                self.run["display_title"] = title
                with self.assertRaisesRegex(review.DatasetReviewError, "binding does not match"):
                    self.require()
        self.use_binding(baseSha="f" * 40)
        with self.assertRaisesRegex(review.DatasetReviewError, "binding does not match"):
            self.require()

    def test_snapshot_metadata_reads_fail_closed_and_before_oversized_blob_fetch(self) -> None:
        self.use_binding()
        original_api = self.fake_api
        cases = ("truncated", "symlink", "oversize", "missing-plan", "wrong-blob", "bad-base64", "wrong-size", "wrong-commit")
        for case in cases:
            with self.subTest(case=case):
                self.calls.clear()

                def malformed(endpoint: str, *, paginate: bool = False) -> object:
                    response = original_api(endpoint, paginate=paginate)
                    if "/git/trees/" in endpoint:
                        if case == "truncated":
                            response["truncated"] = True
                        for entry in response["tree"]:
                            if entry["path"] == "dataset-upload-plan.json":
                                if case == "symlink":
                                    entry["mode"] = "120000"
                                elif case == "oversize":
                                    entry["size"] = review.MAX_SNAPSHOT_BYTES + 1
                        if case == "missing-plan":
                            response["tree"] = [item for item in response["tree"] if item["path"] != "dataset-upload-plan.json"]
                    if "/git/blobs/" in endpoint:
                        if case == "wrong-blob":
                            response["content"] = base64.b64encode(b"x" * response["size"]).decode()
                        elif case == "bad-base64":
                            response["content"] = "!!!"
                        elif case == "wrong-size":
                            response["size"] += 1
                    if "/git/commits/" in endpoint and case == "wrong-commit":
                        response["sha"] = "f" * 40
                    return response

                with patch.object(review, "_gh_api", side_effect=malformed), self.assertRaises(review.DatasetReviewError):
                    review.require_dataset_review(repo=self.repo, commit=self.commit)
                if case == "oversize":
                    self.assertFalse(any("/git/blobs/" in call for call in self.calls))

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
