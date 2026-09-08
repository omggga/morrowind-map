"""Stage only generated files in the validated active runtime graph, never local inputs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.deployment.common import DeploymentError
from tools.deployment.dataset_packages import _read_lock, _tile_sets, _write_json, validate_lock
from tools.deployment.upload_datasets import build_dataset_plan


def stage_datasets(*, repo_root: Path) -> None:
    root = repo_root.resolve()
    public = root / "apps/web/public"
    plan = build_dataset_plan(public_root=public)
    validate_lock(_read_lock(root / "config/dataset-releases.lock.json"), _tile_sets(plan))
    paths = []
    for file in plan["files"]:
        suffix = Path(file["path"]).suffix
        if suffix == ".webp":
            continue
        if suffix not in {".json", ".ndjson"}:
            raise DeploymentError(f"Unsupported generated Git file: {file['path']}")
        paths.append("apps/web/public/datasets/generated/" + file["path"])
    _write_json(root / "config/dataset-upload-plan.json", plan)
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "apps/web/public/datasets/generated"], cwd=root,
    ).decode().split("\0")
    obsolete = sorted(set(tracked) - set(paths) - {""})
    for offset in range(0, len(obsolete), 200):
        subprocess.run(["git", "rm", "--quiet", "--cached", "--", *obsolete[offset:offset + 200]], cwd=root, check=True)
    for offset in range(0, len(paths), 200):
        subprocess.run(["git", "add", "-f", "--", *paths[offset:offset + 200]], cwd=root, check=True)
    subprocess.run(["git", "add", "--", "config/dataset-upload-plan.json",
                    "config/dataset-releases.lock.json"], cwd=root, check=True)
    print(f"Staged {len(paths)} active generated JSON files, release lock and upload plan; "
          f"untracked {len(obsolete)} generated files without deleting local data; graph {plan['graphSha256']}.")


def main() -> None:
    stage_datasets(repo_root=Path(__file__).resolve().parents[2])


if __name__ == "__main__":
    main()
