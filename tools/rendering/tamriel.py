"""Run a versioned province release in an isolated local workspace."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from tools.rendering.common import REPO_ROOT, copy_public_tree, run_module, write_json
from tools.tr_release.model import load_profile


NORMALIZED_DIRECTORIES = {
    "base-game": "bsa",
    "tamriel-data": "tamriel-data",
    "tamriel-rebuilt-core": "tamriel-rebuilt/00 Core/Data Files",
    "project-cyrodiil-core": "project-cyrodiil/00 Core",
    "home-of-nords-core": "home-of-nords/00 Core",
    "oaab-data": "oaab-data/00 Core",
    "azurian-isles-core": "azurian-isles/00 Core",
}
RUN_STAGES = (
    "plan", "renderer-smoke", "renderer-render", "renderer-finalize",
    "renderer-stabilize", "renderer-audit", "dataset-validate", "dataset-prepare",
    "catalog-build", "catalog-validate", "catalog-prepare", "manifest-build",
    "release-verify", "activate-local",
)


def prepare_profile(profile_path: Path, work_root: Path, dataset_id: str | None) -> Path:
    """Retain release contracts while adapting input paths and candidate identity."""
    value = load_profile(profile_path).to_dict()
    active = json.loads((REPO_ROOT / "apps/web/public/datasets/index.json").read_bytes())
    active_ids = {entry["datasetId"] for entry in active["datasets"]}
    if dataset_id is not None:
        value["datasetId"] = dataset_id
    elif value["datasetId"] in active_ids:
        value["datasetId"] += "-local"
    if value["datasetId"] in active_ids:
        raise ValueError("A local rerender requires a new dataset ID, not an active ID")
    value.pop("adoptedSnapshotId", None)
    for directory in value["dataDirectories"]:
        if directory["id"] == "tamriel-rebuilt-core":
            old_package = Path(directory["path"]).parents[1].as_posix()
            for optional in value["excludedOptionalModules"]:
                if optional["relativePath"].startswith(old_package + "/"):
                    optional["relativePath"] = "tamriel-rebuilt/" + optional["relativePath"][len(old_package) + 1:]
        directory["path"] = NORMALIZED_DIRECTORIES[directory["id"]]
    target = work_root / "profile.json"
    write_json(target, value)
    load_profile(target)
    return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "build", "smoke", "run"))
    parser.add_argument("--source-root", type=Path, default=REPO_ROOT / "local-data/inputs")
    parser.add_argument("--work-root", type=Path, default=REPO_ROOT / "local-data/render/tamriel-rebuilt")
    parser.add_argument("--profile", type=Path, default=REPO_ROOT / "config/tr-release.json")
    parser.add_argument("--dataset-id")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--render-workers", type=int, default=2)
    parser.add_argument("--control", help="Run a single named control for the smoke command")
    parser.add_argument("--baseline-public-root", type=Path, default=REPO_ROOT / "apps/web/public")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    source = args.source_root.resolve()
    work = args.work_root.resolve()
    baseline = args.baseline_public_root.resolve()
    published = (REPO_ROOT / "apps/web/public").resolve()
    local = (REPO_ROOT / "local-data").resolve()
    if work == local or local not in work.parents:
        raise ValueError("TR work root must be a dedicated directory inside repository local-data")
    if args.workers < 1 or args.render_workers < 1:
        raise ValueError("Worker counts must be positive")
    if args.control and args.command != "smoke":
        raise ValueError("--control is supported only by smoke; full runs check every control")
    for protected in (source, baseline, published):
        if work == protected or protected in work.parents or work in protected.parents:
            raise ValueError("Work root must be separate from input and baseline/public trees")
    profile = prepare_profile(args.profile.resolve(), work, args.dataset_id)
    candidate = work / "candidate/apps/web/public"
    immutable_baseline = work / "baseline/apps/web/public"
    lock = work / "release.lock.json"
    common = [
        "--profile", str(profile), "--lock", str(lock), "--source-root", str(source),
        "--work-root", str(work), "--public-root", str(candidate),
        "--baseline-public-root", str(immutable_baseline),
    ]

    def stage(name: str, extra: Sequence[str] = ()) -> None:
        run_module("tools.tr_release.cli", [name, *common, *extra])

    stage("check")
    result: dict[str, object] = {
        "datasetId": load_profile(profile).dataset_id,
        "mapKey": load_profile(profile).map_key,
        "profile": str(profile), "workRoot": str(work), "valid": True,
    }
    if args.command == "check":
        return result
    stage("lock")
    result["snapshotId"] = json.loads(lock.read_bytes())["snapshotId"]
    if args.command == "build":
        stage("renderer-build")
    elif args.command == "smoke":
        stage("renderer-smoke", ["--control", args.control] if args.control else [])
    else:
        copy_public_tree(baseline, immutable_baseline)
        copy_public_tree(immutable_baseline, candidate)
        for name in RUN_STAGES:
            extra: list[str] = []
            if name in {"renderer-render", "renderer-stabilize", "renderer-audit"}:
                extra.extend(["--workers", str(args.workers)])
            if name == "renderer-audit":
                extra.extend(["--render-workers", str(args.render_workers)])
            stage(name, extra)
        result["publicRoot"] = str(candidate)
        write_json(work / "receipt.json", result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run(_parser().parse_args(argv))
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"TR rendering failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
