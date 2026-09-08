"""Require a verified trusted dataset review before deploying a merged dataset PR."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import subprocess
import sys
from typing import Any


CHECK_NAME = "Dataset review (trusted)"
WORKFLOW_PATH = ".github/workflows/dataset-review.yml"
_SHA = re.compile(r"[a-f0-9]{40}")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
_EXTERNAL_ID = re.compile(r"dataset-review:([1-9][0-9]*)(?::([1-9][0-9]*):([a-f0-9]{64}))?")
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
MAX_BINDING_BYTES = 16 * 1024
_BINDING_FIELDS = {
    "schemaVersion", "repository", "prNumber", "headSha", "baseSha", "toolSha",
    "runId", "runAttempt", "headLockSha256", "baseLockSha256", "headGraphSha256",
    "baseGraphSha256", "sourceMappingSha256", "receiptSha256", "publicationSha256",
}


class DatasetReviewError(ValueError):
    """The required immutable-head review cannot be verified."""


def review_run_title(pr_number: int, head: str, base: str) -> str:
    """Server-recorded dispatch identity, independent of caller-writable checks."""
    return f"dataset-review-v2:pr:{pr_number}:head:{head}:base:{base}"


def _gh_api(endpoint: str, *, paginate: bool = False) -> Any:
    argv = ["gh", "api", "--hostname", "github.com", "--method", "GET", endpoint]
    if paginate:
        argv.extend(["--paginate", "--slurp"])
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DatasetReviewError(f"GitHub API request failed: {error}") from error
    if result.returncode:
        raise DatasetReviewError(f"GitHub API request failed: {result.stderr.strip()[:1000]}")
    try:
        return json.loads(result.stdout)
    except (ValueError, RecursionError) as error:
        raise DatasetReviewError("GitHub API returned invalid JSON") from error


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DatasetReviewError("GitHub API returned an invalid object")
    return value


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise DatasetReviewError("GitHub API returned an invalid list")
    return value


def _positive_id(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DatasetReviewError(f"GitHub API returned an invalid {label}")
    return value


def _strict_object(payload: str, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DatasetReviewError(f"{label} contains duplicate fields")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise DatasetReviewError(f"{label} contains a non-finite number: {value}")

    try:
        return _object(json.loads(payload, object_pairs_hook=unique, parse_constant=reject_constant))
    except (ValueError, RecursionError) as error:
        raise DatasetReviewError(f"Invalid {label}: {error}") from error


def _binding(check: dict[str, Any]) -> dict[str, Any]:
    text = _object(check.get("output")).get("text")
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BINDING_BYTES:
        raise DatasetReviewError("Review check is missing its bounded durable binding")
    binding = _strict_object(text, "durable review binding")
    if set(binding) != _BINDING_FIELDS or type(binding["schemaVersion"]) is not int or binding["schemaVersion"] != 2:
        raise DatasetReviewError("Review binding has an invalid schema or fields")
    if not isinstance(binding["repository"], str) or not _REPO.fullmatch(binding["repository"]):
        raise DatasetReviewError("Review binding has an invalid repository")
    for name in ("prNumber", "runId", "runAttempt"):
        _positive_id(binding[name], f"binding {name}")
    for name in ("headSha", "baseSha", "toolSha"):
        if not isinstance(binding[name], str) or not _SHA.fullmatch(binding[name]):
            raise DatasetReviewError(f"Review binding has an invalid {name}")
    for name in ("headLockSha256", "baseLockSha256", "headGraphSha256", "baseGraphSha256", "sourceMappingSha256", "receiptSha256", "publicationSha256"):
        if binding[name] is None and name in ("headLockSha256", "baseLockSha256", "baseGraphSha256"):
            continue
        if not isinstance(binding[name], str) or not _SHA256.fullmatch(binding[name]):
            raise DatasetReviewError(f"Review binding has an invalid {name}")
    return binding


def _tree(repo: str, sha: str) -> dict[str, dict[str, Any]]:
    tree = _object(_gh_api(f"repos/{repo}/git/trees/{sha}"))
    if tree.get("sha") != sha or tree.get("truncated") is not False:
        raise DatasetReviewError("Snapshot tree is incomplete or has a different identity")
    entries: dict[str, dict[str, Any]] = {}
    for raw in _list(tree.get("tree")):
        item = _object(raw)
        path = item.get("path")
        if not isinstance(path, str) or path in entries or "/" in path:
            raise DatasetReviewError("Snapshot tree contains an invalid or duplicate path")
        entries[path] = item
    return entries


def _entry_sha(entry: dict[str, Any], kind: str) -> str:
    sha = entry.get("sha")
    if (
        entry.get("type") != kind or not isinstance(sha, str) or not _SHA.fullmatch(sha)
        or (kind == "blob" and entry.get("mode") not in ("100644", "100755"))
        or (kind == "tree" and entry.get("mode") != "040000")
    ):
        raise DatasetReviewError("Snapshot metadata must be regular Git files and trees")
    return sha


def _blob(repo: str, entry: dict[str, Any]) -> bytes:
    sha = _entry_sha(entry, "blob")
    size = _positive_id(entry.get("size"), "snapshot file size")
    if size > MAX_SNAPSHOT_BYTES:
        raise DatasetReviewError("Snapshot metadata exceeds the size limit")
    blob = _object(_gh_api(f"repos/{repo}/git/blobs/{sha}"))
    content = blob.get("content")
    if (
        blob.get("sha") != sha or type(blob.get("size")) is not int or blob["size"] != size
        or blob.get("encoding") != "base64" or not isinstance(content, str)
        or len(content) > (MAX_SNAPSHOT_BYTES * 4 // 3 + MAX_SNAPSHOT_BYTES // 30 + 8)
    ):
        raise DatasetReviewError("Snapshot blob has invalid encoding, size or identity")
    try:
        payload = base64.b64decode(content.replace("\n", ""), validate=True)
    except (ValueError, binascii.Error) as error:
        raise DatasetReviewError("Snapshot blob is not valid base64") from error
    if len(payload) != size or hashlib.sha1(f"blob {size}\0".encode() + payload).hexdigest() != sha:
        raise DatasetReviewError("Snapshot blob bytes do not match its Git identity")
    return payload


def _snapshot_binding(repo: str, commit: str, *, graph: bool) -> dict[str, Any]:
    # Inspect only metadata as data. Tree lookup distinguishes an absent lock
    # from permissions/API errors, and blob sizes are bounded before fetching.
    metadata = _object(_gh_api(f"repos/{repo}/git/commits/{commit}"))
    if metadata.get("sha") != commit:
        raise DatasetReviewError("Snapshot commit has a different identity")
    tree_sha = _object(metadata.get("tree")).get("sha")
    if not isinstance(tree_sha, str) or not _SHA.fullmatch(tree_sha):
        raise DatasetReviewError("Snapshot commit has an invalid tree")
    root = _tree(repo, tree_sha)
    config = _tree(repo, _entry_sha(root["config"], "tree")) if "config" in root else {}
    lock_entry = config.get("dataset-releases.lock.json")
    lock_digest = None
    if lock_entry is not None:
        # Even legacy checks must reject malformed/non-regular lock entries.
        _entry_sha(lock_entry, "blob")
        lock_digest = hashlib.sha256(_blob(repo, lock_entry)).hexdigest() if graph else "present"
    graph_digest = None
    if graph:
        plan_entry = config.get("dataset-upload-plan.json")
        if plan_entry is None:
            raise DatasetReviewError("Snapshot is missing the committed upload plan")
        try:
            plan = _strict_object(_blob(repo, plan_entry).decode("utf-8"), "committed upload plan")
        except UnicodeDecodeError as error:
            raise DatasetReviewError("Committed upload plan is not UTF-8") from error
        graph_digest = plan.get("graphSha256")
        if not isinstance(graph_digest, str) or not _SHA256.fullmatch(graph_digest):
            raise DatasetReviewError("Committed upload plan has an invalid graph digest")
    return {"lockSha256": lock_digest, "graphSha256": graph_digest, "parents": metadata.get("parents")}


def require_dataset_review(*, repo: str, commit: str) -> dict[str, object]:
    if not _REPO.fullmatch(repo):
        raise DatasetReviewError("repo must be a safe GitHub owner/name")
    if not _SHA.fullmatch(commit):
        raise DatasetReviewError("commit must be a full lowercase 40-character SHA")

    pages = _list(_gh_api(f"repos/{repo}/commits/{commit}/pulls?per_page=100", paginate=True))
    matches: list[dict[str, Any]] = []
    for page in pages:
        for raw in _list(page):
            pr = _object(raw)
            base = _object(pr.get("base"))
            base_repo = _object(base.get("repo"))
            if (
                pr.get("merge_commit_sha") == commit
                and pr.get("state") == "closed"
                and isinstance(pr.get("merged_at"), str) and pr["merged_at"]
                and base.get("ref") == "main"
                and str(base_repo.get("full_name", "")).casefold() == repo.casefold()
            ):
                matches.append(pr)
    if len(matches) != 1:
        raise DatasetReviewError("Expected exactly one merged PR into main for this exact commit")
    pr = matches[0]
    number = _positive_id(pr.get("number"), "PR number")
    head = _object(pr.get("head")).get("sha")
    if not isinstance(head, str) or not _SHA.fullmatch(head):
        raise DatasetReviewError("Merged PR has an invalid immutable head SHA")

    pages = _list(_gh_api(
        f"repos/{repo}/commits/{head}/check-runs?check_name=Dataset%20review%20%28trusted%29&filter=all&per_page=100",
        paginate=True,
    ))
    checks: list[dict[str, Any]] = []
    for page in pages:
        for raw in _list(_object(page).get("check_runs")):
            check = _object(raw)
            if check.get("name") == CHECK_NAME and _object(check.get("app")).get("slug") == "github-actions":
                _positive_id(check.get("id"), "check run ID")
                checks.append(check)
    if not checks:
        raise DatasetReviewError(f"No GitHub Actions {CHECK_NAME!r} check exists for PR #{number} head {head}")
    # Check IDs are monotonically allocated. Never fall back to an older green
    # review after the newest matching review fails, is cancelled, or is running.
    check = max(checks, key=lambda item: item["id"])
    if check.get("head_sha") != head or check.get("status") != "completed" or check.get("conclusion") != "success":
        raise DatasetReviewError("The newest trusted dataset review check is not successful for this exact PR head")
    external = check.get("external_id")
    matched = _EXTERNAL_ID.fullmatch(external) if isinstance(external, str) else None
    if not matched:
        raise DatasetReviewError("Trusted dataset review check has no valid workflow run binding")
    run_id = int(matched[1])
    run = _object(_gh_api(f"repos/{repo}/actions/runs/{run_id}"))
    run_repo = _object(run.get("repository"))
    path = run.get("path")
    if (
        run.get("id") != run_id
        or str(run_repo.get("full_name", "")).casefold() != repo.casefold()
        or not isinstance(path, str) or path.split("@", 1)[0] != WORKFLOW_PATH
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        raise DatasetReviewError("Review check does not reference a successful trusted workflow run on main in this repository")
    result: dict[str, object] = {
        "repository": repo, "commit": commit, "pullRequest": number, "headSha": head,
        "checkRunId": check["id"], "reviewRunId": run_id,
    }
    if matched[2] is None:
        # Old successful reviews remain deployable without their expired report
        # artifacts, but they can never authorize the new release transport.
        snapshots = [_snapshot_binding(repo, sha, graph=False) for sha in (head, commit)]
        if any(snapshot["lockSha256"] is not None for snapshot in snapshots):
            raise DatasetReviewError("Legacy review cannot authorize a snapshot with a transport lock")
        parents = _list(snapshots[1]["parents"])
        parent = _object(parents[0]).get("sha") if parents else None
        if not isinstance(parent, str) or not _SHA.fullmatch(parent):
            raise DatasetReviewError("Legacy reviewed merge must identify its immutable first parent")
        if _snapshot_binding(repo, parent, graph=False)["lockSha256"] is not None:
            raise DatasetReviewError("Legacy review cannot authorize a release transport downgrade")
        return result

    binding = _binding(check)
    if binding["baseLockSha256"] is not None and binding["headLockSha256"] is None:
        raise DatasetReviewError("Review cannot authorize a release transport downgrade")
    if (
        binding["repository"] != repo or binding["prNumber"] != number
        or binding["headSha"] != head or binding["runId"] != run_id
        or binding["runAttempt"] != int(matched[2]) or binding["receiptSha256"] != matched[3]
        or run.get("head_sha") != binding["toolSha"]
        or type(run.get("run_attempt")) is not int or run["run_attempt"] != binding["runAttempt"]
        or run.get("display_title") != review_run_title(number, head, binding["baseSha"])
    ):
        raise DatasetReviewError("Review binding does not match the PR head or trusted workflow attempt/tool revision")
    head_snapshot = _snapshot_binding(repo, head, graph=True)
    merged_snapshot = _snapshot_binding(repo, commit, graph=True)
    # GitHub's current PR base.sha can move after review/merge. The deployed
    # commit's first parent is immutable. A later merge base requires a fresh
    # review instead of silently accepting a different before/after comparison.
    parents = _list(merged_snapshot["parents"])
    if not parents or _object(parents[0]).get("sha") != binding["baseSha"]:
        raise DatasetReviewError("Merged commit base differs from the reviewed base SHA; a fresh review is required")
    for snapshot in (head_snapshot, merged_snapshot):
        if snapshot["lockSha256"] != binding["headLockSha256"] or snapshot["graphSha256"] != binding["headGraphSha256"]:
            raise DatasetReviewError("Reviewed head/merged snapshot lock or graph differs from the durable review binding")
    base_snapshot = _snapshot_binding(repo, binding["baseSha"], graph=True)
    if base_snapshot["lockSha256"] != binding["baseLockSha256"] or base_snapshot["graphSha256"] != binding["baseGraphSha256"]:
        raise DatasetReviewError("Reviewed base snapshot lock or graph differs from the durable review binding")
    result.update({"reviewRunAttempt": binding["runAttempt"], "receiptSha256": binding["receiptSha256"], "publicationSha256": binding["publicationSha256"]})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    try:
        result = require_dataset_review(repo=args.repo, commit=args.commit)
    except DatasetReviewError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
