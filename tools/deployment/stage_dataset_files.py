"""Stage only generated files in the validated active runtime graph, never local inputs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.deployment.common import canonical_json_bytes
from tools.deployment.upload_datasets import build_dataset_plan


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    public = root / "apps/web/public"
    plan = build_dataset_plan(public_root=public)
    subprocess.run(["git", "lfs", "version"], cwd=root, check=True)
    paths = ["apps/web/public/datasets/generated/" + file["path"] for file in plan["files"]]
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "apps/web/public/datasets/generated"], cwd=root,
    ).decode().split("\0")
    obsolete = sorted(set(tracked) - set(paths) - {""})
    for offset in range(0, len(obsolete), 200):
        subprocess.run(["git", "rm", "--cached", "--", *obsolete[offset:offset + 200]], cwd=root, check=True)
    for offset in range(0, len(paths), 200):
        subprocess.run(["git", "add", "-f", "--", *paths[offset:offset + 200]], cwd=root, check=True)
    (root / "config/dataset-upload-plan.json").write_bytes(canonical_json_bytes(plan))
    subprocess.run(["git", "add", "--", "config/dataset-upload-plan.json"], cwd=root, check=True)
    print(f"Staged {len(paths)} active generated files; graph {plan['graphSha256']}.")


if __name__ == "__main__":
    main()
