"""Require a verified trusted dataset review before deploying a merged dataset PR."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any


CHECK_NAME = "Dataset review (trusted)"
WORKFLOW_PATH = ".github/workflows/dataset-review.yml"
_SHA = re.compile(r"[a-f0-9]{40}")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
_EXTERNAL_ID = re.compile(r"dataset-review:([1-9][0-9]*)")


class DatasetReviewError(ValueError):
    """The required immutable-head review cannot be verified."""


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
    return {
        "repository": repo, "commit": commit, "pullRequest": number, "headSha": head,
        "checkRunId": check["id"], "reviewRunId": run_id,
    }


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
