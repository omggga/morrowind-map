"""One local interface for checking, rendering, and reviewing prepared maps."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from tools.rendering.common import REPO_ROOT, atomic_copy, safe_path, write_json


TARGETS = ("original", "tamriel-rebuilt", "project-cyrodiil")
MODULES = {"original": "tools.rendering.original", "tamriel-rebuilt": "tools.rendering.tamriel", "project-cyrodiil": "tools.rendering.tamriel"}
BASE_IMAGE = "morrowind-map-openmw:0.51.0-stage45"


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Worker count must be positive")
    return number


def adapter_arguments(args: argparse.Namespace, target: str, command: str) -> list[str]:
    result = [command, "--source-root", str(args.source_root.resolve()),
              "--work-root", str((args.work_root / target).resolve()),
              "--workers", str(args.workers), "--render-workers", str(args.render_workers)]
    if target == "original" and args.settings:
        result += ["--settings", str(args.settings.resolve())]
    if target in {"tamriel-rebuilt", "project-cyrodiil"}:
        profile = args.profile or REPO_ROOT / "config" / ("pc-release.json" if target == "project-cyrodiil" else "tr-release.json")
        result += ["--profile", str(profile.resolve())]
        if args.dataset_id:
            result += ["--dataset-id", args.dataset_id]
        if args.control and command == "smoke":
            result += ["--control", args.control]
    return result


def run_adapter(target: str, arguments: Sequence[str], log_root: Path) -> dict[str, object]:
    log_root.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, object] | None = None
    json_buffer = ""
    argv = [sys.executable, "-m", MODULES[target], *arguments]
    with (log_root / f"{target}-{arguments[0]}.log").open("w", encoding="utf-8") as log:
        with subprocess.Popen(argv, cwd=REPO_ROOT, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True) as process:
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
                if line.startswith("{"):
                    json_buffer = line
                elif json_buffer:
                    json_buffer += line
                try:
                    value = json.loads(json_buffer)
                    if isinstance(value, dict):
                        receipt = value
                        json_buffer = ""
                except ValueError:
                    pass
            status = process.wait()
    if status:
        raise subprocess.CalledProcessError(status, argv)
    if receipt is None:
        raise ValueError(f"{target} did not return a render receipt; inspect {log_root}")
    return receipt


def require_tools() -> None:
    missing = [name for name in ("docker", "magick", "pnpm") if shutil.which(name) is None]
    if missing:
        raise ValueError("Install required tools before rendering: " + ", ".join(missing))
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True,
                   stdout=subprocess.DEVNULL, timeout=30)


def ensure_base_image() -> None:
    from tools.openmw_renderer.spike import build_image, renderer_fingerprint

    fingerprint = renderer_fingerprint(REPO_ROOT)
    inspected = subprocess.run(["docker", "image", "inspect", BASE_IMAGE],
                               capture_output=True, text=True, check=False, timeout=30)
    if inspected.returncode == 0:
        image = json.loads(inspected.stdout)[0]
        labels = image.get("Config", {}).get("Labels", {}) or {}
        if labels.get("io.morrowind-map.renderer-fingerprint") == fingerprint:
            return
    print("Building the pinned OpenMW base image; see local-data/openmw-spike/docker-build.log", flush=True)
    build_image(REPO_ROOT, BASE_IMAGE, renderer_hash=fingerprint, timeout_seconds=7200)


def validate_candidate(public_root: Path, *, browser: bool = True) -> dict[str, object]:
    from tools.deployment.upload_datasets import build_dataset_plan

    plan = build_dataset_plan(public_root=public_root)
    if browser:
        environment = dict(os.environ, MORROWIND_RENDER_PUBLIC_ROOT=str(public_root.resolve()))
        subprocess.run(["pnpm", "test:acceptance:rendered"], cwd=REPO_ROOT,
                       env=environment, check=True)
    from tools.deployment.common import canonical_json_bytes
    (public_root.parent / "dataset-upload-plan.json").write_bytes(canonical_json_bytes(plan))
    return plan


def use_candidate(public_root: Path) -> None:
    """Install validated local outputs; content-addressed bytes always precede the index."""
    source = Path(os.path.abspath(public_root))
    local = (REPO_ROOT / "local-data").resolve()
    if local not in source.parents:
        raise ValueError("Use a candidate inside this repository's ignored local-data directory")
    safe_path(source, REPO_ROOT)
    plan = validate_candidate(source)
    destination = REPO_ROOT / "apps/web/public"
    index = json.loads((source / "datasets/index.json").read_text())
    release_profiles = []
    for name in ("tr-release.json", "pc-release.json"):
        release_profile = safe_path(source.parent / name, REPO_ROOT)
        if release_profile.is_file():
            from tools.tr_release.model import load_profile
            profile = load_profile(release_profile)
            expected_key = "project-cyrodiil" if name == "pc-release.json" else "tamriel-rebuilt"
            if profile.map_key != expected_key:
                raise ValueError("Candidate release profile has the wrong map identity")
            if profile.dataset_id not in {entry["datasetId"] for entry in index["datasets"]}:
                raise ValueError("Candidate release profile does not match its dataset index")
            release_profiles.append(release_profile)
    immutable = {Path("datasets/generated") / entry["path"]: entry["sha256"] for entry in plan["files"]}
    # Copy only active metadata packages, never the entire local output tree.
    packages = set()
    for dataset in plan["datasets"]:
        packages.add(Path(dataset["mapAssets"]["url"].lstrip("/")).parent)
        packages.add(Path(dataset["catalogAudit"]["url"].lstrip("/")).parent)
        for pyramid in dataset["tilePyramids"]:
            packages.add(Path(pyramid["qualityReport"]["url"].lstrip("/")).parent)
    for package in packages:
        safe_path(source / package, source / "datasets/metadata")
        for path in (source / package).rglob("*"):
            safe_path(path, source)
            if path.is_file():
                if path.suffix not in {".json", ".ndjson", ".webp"}:
                    raise ValueError(f"Unexpected candidate metadata file: {path}")
                immutable[path.relative_to(source)] = hashlib.sha256(path.read_bytes()).hexdigest()
    mutable = [*(Path(e["manifestUrl"].lstrip("/")) for e in index["datasets"]), Path("datasets/index.json")]
    # Preflight every destination before changing tracked metadata.
    for relative, expected in immutable.items():
        safe_path(source / relative, source)
        target = safe_path(destination / relative, REPO_ROOT)
        if target.exists():
            digest = hashlib.sha256()
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ValueError(f"Existing immutable output differs: {relative}")
    for relative in mutable:
        safe_path(source / relative, source)
        safe_path(destination / relative, REPO_ROOT)
    for name in ("dataset-upload-plan.json", "tr-release.json", "pc-release.json"):
        safe_path(REPO_ROOT / "config" / name, REPO_ROOT)
    for relative in immutable:
        target = destination / relative
        if not target.exists():
            atomic_copy(source / relative, target)
    for relative in mutable:
        atomic_copy(source / relative, destination / relative)
    atomic_copy(source.parent / "dataset-upload-plan.json", REPO_ROOT / "config/dataset-upload-plan.json")
    for release_profile in release_profiles:
        atomic_copy(release_profile, REPO_ROOT / "config" / release_profile.name)
    print("Candidate is active locally. Review the diff, run pnpm verify, then pnpm datasets:stage and open a PR.")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("check", "build", "smoke", "run"):
        command = commands.add_parser(name)
        command.add_argument("target", nargs="?", choices=(*TARGETS, "all"), default="all")
        command.add_argument("--source-root", type=Path, default=REPO_ROOT / "local-data/inputs")
        command.add_argument("--work-root", type=Path, default=REPO_ROOT / "local-data/render")
        command.add_argument("--profile", type=Path, default=None)
        command.add_argument("--dataset-id")
        command.add_argument("--settings", type=Path)
        command.add_argument("--control", help="One named release smoke control; default runs every configured control")
        command.add_argument("--workers", type=positive, default=2)
        command.add_argument("--render-workers", type=positive, default=2)
    for name in ("preview", "use"):
        command = commands.add_parser(name)
        command.add_argument("--public-root", type=Path, required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "preview":
        validate_candidate(args.public_root, browser=False)
        environment = dict(os.environ, MORROWIND_RENDER_PUBLIC_ROOT=str(args.public_root.resolve()))
        return subprocess.call(["pnpm", "--filter", "@morrowind-map/web", "exec", "vite", "--host", "127.0.0.1"],
                               cwd=REPO_ROOT, env=environment)
    if args.command == "use":
        use_candidate(args.public_root)
        return 0
    if args.target == "all" and (args.profile or args.dataset_id):
        raise ValueError("--profile and --dataset-id require a single release target")
    targets = TARGETS if args.target == "all" else (args.target,)
    work = safe_path(args.work_root, REPO_ROOT)
    local = (REPO_ROOT / "local-data").resolve()
    if local not in work.parents:
        raise ValueError("Work root must be a dedicated directory inside repository local-data")
    source = args.source_root.resolve()
    if work == source or source in work.parents or work in source.parents:
        raise ValueError("Work root must be separate from input files")
    logs = safe_path(work / "logs", REPO_ROOT)
    # Check every requested input set before starting either expensive renderer.
    receipts = {target: run_adapter(target, adapter_arguments(args, target, "check"), logs) for target in targets}
    for target, receipt in receipts.items():
        if target != "original" and receipt.get("mapKey") != target:
            raise ValueError(f"The selected profile does not describe {target}")
    if args.command == "check":
        print(json.dumps({"status": "valid", "maps": receipts}, sort_keys=True))
        return 0
    require_tools()
    ensure_base_image()
    baseline: Path | None = None
    for target in targets:
        run_adapter(target, adapter_arguments(args, target, "build"), logs)
        if args.command == "build":
            continue
        options = adapter_arguments(args, target, args.command)
        if baseline is not None and target != "original":
            options += ["--baseline-public-root", str(baseline)]
        receipt = run_adapter(target, options, logs)
        if args.command == "run":
            baseline = Path(str(receipt["publicRoot"]))
            plan = validate_candidate(baseline)
            receipt["graphSha256"] = plan["graphSha256"]
            if target != "original":
                profile_name = "pc-release.json" if target == "project-cyrodiil" else "tr-release.json"
                write_json(baseline.parent / profile_name, json.loads(Path(str(receipt["profile"])).read_text()))
        receipts[target] = receipt
    result = {"status": "complete", "command": args.command, "maps": receipts}
    if baseline is not None:
        result["publicRoot"] = str(baseline)
    write_json(args.work_root.resolve() / "result.json", result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Local rendering failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
