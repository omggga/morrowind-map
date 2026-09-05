"""Run the existing Original renderer with an isolated, reproducible local profile.

The shipped Original entry points retain their frozen identity. This adapter
binds settings and producer changes to a new snapshot while retaining the exact
English GOTY inputs and the established tile geometry and quality gates.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from tools.rendering.common import copy_public_tree, run_module, write_json as _write_json


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IMAGE = "morrowind-map-openmw:0.51.0-original-local-v1"
STAGES = ("plan", "render", "finalize", "stabilize", "audit", "prepare", "catalog", "candidate")


def settings_text(path: Path | None) -> str:
    """Merge local INI overrides without changing the renderer's tile contract."""
    from tools.original_renderer.profile import render_settings_cfg

    default = render_settings_cfg()
    if path is None:
        return default
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Settings must be a regular UTF-8 file no larger than 64 KiB")
    override = path.read_text(encoding="utf-8")
    if "\0" in override:
        raise ValueError("Settings cannot contain NUL characters")
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.read_string(default)
    parser.read_string(override)
    for name, expected in (
        ("local map resolution", "512"),
        ("local map widget size", "512"),
        ("max local viewing distance", "1"),
    ):
        if parser.get("Map", name) != expected:
            raise ValueError(f"[Map] {name} must remain {expected} for the published tile grid")
    output = io.StringIO()
    parser.write(output)
    return output.getvalue()


def snapshot_identity(profile_fingerprint: str, producer_fingerprint: str) -> str:
    identity = hashlib.sha256(
        json.dumps(
            {"profile": profile_fingerprint, "producer": producer_fingerprint},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return f"original:goty:{identity[:16]}"


def _activate(args: argparse.Namespace, *, source: bool = True) -> tuple[Any, ...]:
    from tools.original_renderer import bootstrap, profile

    settings = settings_text(args.settings)
    production, publish, stabilize, audit = bootstrap.activate()
    production.PRODUCTION_SOURCE_PATHS = (
        *production.PRODUCTION_SOURCE_PATHS,
        "tools/rendering/original.py",
    )
    # Runtime settings belong to the profile, while the image is release-independent.
    production.render_settings_cfg = lambda: settings
    production.DEFAULT_PRODUCTION_IMAGE = args.image
    for module in (stabilize, audit):
        module.DEFAULT_PRODUCTION_IMAGE = args.image
    if not source:
        return production, publish, stabilize, audit
    inputs = profile.validate_source_inputs(args.source_root)
    assets = profile.fingerprint_data_directories(args.source_root)
    fingerprint = profile.profile_fingerprint(
        inputs, asset_audit=assets,
        openmw_cfg=profile.render_openmw_cfg(), settings_cfg=settings,
    )
    snapshot = snapshot_identity(
        fingerprint, production.production_source_fingerprint(REPO_ROOT),
    )
    for module in (production, publish, stabilize, audit):
        module.SNAPSHOT_ID = snapshot
    production.PINNED_PROFILE_FINGERPRINT = fingerprint
    cells = production.derive_effective_land_cells(
        tuple(args.source_root / item.relative_path for item in profile.SOURCE_INPUTS
              if item.relative_path.endswith(".esm"))
    )
    plan = production.plan_report(cells)
    if plan["targetCount"] != bootstrap.EXPECTED_NATIVE_TILES or plan["shardCount"] != bootstrap.EXPECTED_SHARDS:
        raise ValueError("Original coverage differs from the pinned English GOTY tile topology")
    publish.EXPECTED_PLAN_FINGERPRINT = plan["planFingerprint"]
    from tools.catalog_pipeline import original as catalog
    catalog.SNAPSHOT_ID = snapshot
    return production, publish, stabilize, audit, catalog, plan


def _work(args: argparse.Namespace, snapshot: str) -> Path:
    root = args.work_root.resolve()
    boundary = (REPO_ROOT / "local-data").resolve()
    if root == boundary or boundary not in root.parents:
        raise ValueError("Original work-root must be a dedicated directory under repository local-data")
    return root / snapshot.rsplit(":", 1)[-1]


def _candidate_tree(work: Path) -> Path:
    public = work / "candidate/apps/web/public"
    copy_public_tree(REPO_ROOT / "apps/web/public", public)
    return public


def _artifact(path: Path, public: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "url": "/" + path.relative_to(public).as_posix(),
        "mediaType": "application/json",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def _assemble_candidate(work: Path, snapshot: str) -> dict[str, object]:
    from tools.deployment.upload_datasets import build_dataset_plan

    public = _candidate_tree(work)
    datasets = public / "datasets"
    prepared = json.loads((work / "prepared.json").read_bytes())
    catalog = json.loads((work / "catalog-prepared.json").read_bytes())
    manifest_path = datasets / "manifests/original-goty-hd.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["snapshotId"] = snapshot
    tiles = datasets / "metadata/original-goty-hd" / prepared["inventorySha256"] / "map-assets.json"
    catalog_root = Path(catalog["generatedRoot"])
    audit = Path(catalog["metadataRoot"]) / "catalog-audit.json"
    manifest["artifacts"] = {
        "locations": _artifact(catalog_root / "locations.json", public),
        "locales": [{"locale": "en", "artifact": _artifact(catalog_root / "locales/en.json", public)}],
        "catalogAudit": _artifact(audit, public),
        "tiles": {"manifestUrl": "/" + tiles.relative_to(public).as_posix(),
                  "sha256": hashlib.sha256(tiles.read_bytes()).hexdigest()},
    }
    manifest["provenance"]["notes"] = [
        "Rendered from the exact six English GOTY source files with an isolated local settings profile.",
        "The snapshot binds the settings and producer source; execution provenance also binds the image and encoder.",
        "The complete tile quality audit and catalog validation passed before candidate assembly.",
    ]
    _write_json(manifest_path, manifest)
    plan = build_dataset_plan(public_root=public)
    _write_json(work / "dataset-upload-plan.json", plan)
    result = {"datasetId": manifest["datasetId"], "snapshotId": snapshot,
              "publicRoot": str(public), "manifest": str(manifest_path),
              "plan": str(work / "dataset-upload-plan.json"), "status": "prepared"}
    _write_json(work / "result.json", result)
    return result


def _run_stage(args: argparse.Namespace) -> int:
    pipeline = _activate(args, source=args.command != "build")
    production, publish, stabilize, audit = pipeline[:4]
    if args.command == "build":
        return int(production.main(["build", "--image", args.image]))
    catalog, plan = pipeline[4:]
    work = _work(args, production.SNAPSHOT_ID)
    source = str(args.source_root)
    raw = work / "production"
    release = work / "release"
    identity = {"datasetId": production.DATASET_ID, "snapshotId": production.SNAPSHOT_ID,
                "profileFingerprint": production.PINNED_PROFILE_FINGERPRINT,
                "planFingerprint": plan["planFingerprint"], "workRoot": str(work),
                "targetCount": plan["targetCount"], "shardCount": plan["shardCount"]}
    if args.command == "check":
        print(json.dumps({**identity, "valid": True}, sort_keys=True))
        return 0
    work.mkdir(parents=True, exist_ok=True)
    if args.command == "plan":
        _write_json(raw / "plan.json", plan)
        _write_json(work / "profile.json", identity)
        (work / "settings.cfg").write_text(settings_text(args.settings))
        return 0
    runtime = ["--source-root", source, "--image", args.image]
    if args.command == "smoke":
        return int(production.main(["smoke", *runtime, "--output", str(work / "smoke"),
                                   "--center=" + args.center, "--timeout-seconds", str(args.timeout_seconds),
                                   "--retain-raw"]))
    if args.command == "render":
        return int(production.main(["render", *runtime, "--output", str(raw),
                                   "--workers", str(args.render_workers),
                                   "--timeout-seconds", str(args.timeout_seconds)]))
    if args.command == "finalize":
        return int(production.main(["finalize", *runtime, "--output", str(raw)]))
    if args.command == "stabilize":
        return int(stabilize.main(["--source", str(raw), "--output", str(release),
                                   "--workers", str(args.workers)]))
    if args.command == "audit":
        return int(audit.main(["full", *runtime, "--output", str(release),
                              "--workers", str(args.workers), "--render-workers", str(args.render_workers)]))
    if args.command == "prepare":
        inventory = publish.validate_source(release)
        publish.validate_quality_report(release, inventory)
        public = _candidate_tree(work)
        result = publish.prepare_dataset(
            source_root=release, public_root=public / "datasets/generated",
            metadata_root=public / "datasets/metadata/original-goty-hd", copy_mode="auto",
        )
        _write_json(work / "prepared.json", {"inventorySha256": result.inventory_sha256})
        return 0
    if args.command == "catalog":
        output = work / "catalog"
        catalog.build_original_catalog(source_root=args.source_root, output_root=output, repo_root=REPO_ROOT)
        catalog.validate_catalog(output)
        public = _candidate_tree(work)
        result = catalog.prepare_catalog(source_root=output, public_root=public / "datasets/generated",
                                         metadata_root=public / "datasets/metadata")
        _write_json(work / "catalog-prepared.json", result)
        return 0
    if args.command == "candidate":
        print(json.dumps(_assemble_candidate(work, production.SNAPSHOT_ID), sort_keys=True))
        return 0
    raise ValueError(f"Unknown Original stage: {args.command}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "build", "smoke", "run", *STAGES))
    parser.add_argument("--source-root", type=Path, default=REPO_ROOT / "local-data/inputs")
    parser.add_argument("--work-root", type=Path, default=REPO_ROOT / "local-data/rendering/original")
    parser.add_argument("--settings", type=Path, help="Local OpenMW INI overrides; the 512px tile grid stays fixed")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--render-workers", type=int, default=2)
    parser.add_argument("--center", default="-3,-3")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(arguments)
    args.source_root = args.source_root.resolve()
    if args.workers <= 0 or args.render_workers <= 0 or args.timeout_seconds <= 0:
        raise ValueError("Workers and timeout must be positive")
    if args.command == "run":
        for stage in ("check", "smoke", *STAGES):
            run_module("tools.rendering.original", [stage, *arguments[1:]])
        return 0
    return _run_stage(args)


if __name__ == "__main__":
    raise SystemExit(main())
