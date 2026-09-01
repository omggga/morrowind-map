from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.tr_release.model import (
    ReleaseProfile,
    RELEASE_PRODUCTION_SOURCE_PATHS,
    canonical_json_bytes,
    canonical_json_sha256,
    check_source,
    derive_land_topology,
    generate_release_lock,
    load_profile,
)


DEFAULT_PROFILE = Path("config/tr-release.json")
DEFAULT_LOCK = Path("local-data/tr-release/release.lock.json")
PRODUCTION_IMAGE = "morrowind-map-openmw:0.51.0-tr"
ORIGINAL_DATASET_ID = "original-goty-hd"


@dataclass(frozen=True, slots=True)
class Context:
    repo_root: Path
    profile_path: Path
    lock_path: Path
    source_root: Path
    profile: ReleaseProfile
    lock: dict[str, Any]

    @property
    def dataset_id(self) -> str:
        return str(self.lock["datasetId"])

    @property
    def production_root(self) -> Path:
        return self.repo_root / "local-data/tr-release/production" / self.dataset_id

    @property
    def release_root(self) -> Path:
        return self.repo_root / "local-data/tr-release/release" / self.dataset_id

    @property
    def catalog_root(self) -> Path:
        return self.repo_root / "local-data/tr-release/catalog" / self.dataset_id

    @property
    def candidate_root(self) -> Path:
        return self.repo_root / "local-data/tr-release/candidate/datasets"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolved(repo_root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (repo_root / value).resolve()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json_output(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _assert_future_dataset_id(dataset_id: str, index_path: Path) -> None:
    if index_path.is_symlink() or not index_path.is_file():
        raise FileNotFoundError(f"Active dataset index is missing or unsafe: {index_path}")
    try:
        value = json.loads(index_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Active dataset index is not valid UTF-8 JSON: {index_path}") from error
    if not isinstance(value, dict) or not isinstance(value.get("datasets"), list):
        raise ValueError("Active dataset index must contain a datasets array")
    identifiers: list[str] = []
    for item in value["datasets"]:
        if not isinstance(item, dict) or not isinstance(item.get("datasetId"), str):
            raise ValueError("Active dataset index contains an invalid dataset entry")
        identifiers.append(item["datasetId"])
    if len(identifiers) != 2 or identifiers.count(ORIGINAL_DATASET_ID) != 1:
        raise ValueError("Active dataset index must contain Original and exactly one TR release")
    if dataset_id in identifiers:
        raise ValueError(
            f"TR release datasetId {dataset_id!r} is already active; choose a new versioned id "
            "before check/lock/render"
        )


def _candidate_payload(value: object) -> dict[str, str]:
    return {
        "datasetId": str(getattr(value, "dataset_id")),
        "snapshotId": str(getattr(value, "snapshot_id")),
        "manifest": str(getattr(value, "manifest_path")),
        "index": str(getattr(value, "index_path")),
    }


def _read_lock(path: Path, profile: ReleaseProfile) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"Generated TR release lock is missing or unsafe: {path}")
    payload = path.read_bytes()
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"TR release lock is not valid UTF-8 JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError("TR release lock must be a JSON object")
    if payload != canonical_json_bytes(value) + b"\n":
        raise ValueError("TR release lock must be canonical JSON with one trailing LF")
    lock_hash = value.get("lockSha256")
    core = {key: item for key, item in value.items() if key != "lockSha256"}
    if lock_hash != canonical_json_sha256(core):
        raise ValueError("TR release lock self-hash does not match its payload")
    if value.get("profile") != profile.to_dict():
        raise ValueError("config/tr-release.json differs from the generated release lock")
    if value.get("datasetId") != profile.dataset_id or value.get("mapKey") != profile.map_key:
        raise ValueError("TR release lock identity differs from config/tr-release.json")
    fingerprint_payload = {
        "schemaVersion": 1,
        "profile": profile.to_dict(include_adopted_snapshot=False),
        "source": value.get("source"),
    }
    fingerprint = canonical_json_sha256(fingerprint_payload)
    derived_snapshot = f"tr:{profile.dataset_id}:{fingerprint[:16]}"
    if value.get("profileFingerprint") != fingerprint:
        raise ValueError("TR release lock profile fingerprint is invalid")
    if value.get("derivedSnapshotId") != derived_snapshot:
        raise ValueError("TR release lock derived snapshot is invalid")
    if value.get("snapshotId") != (profile.adopted_snapshot_id or derived_snapshot):
        raise ValueError("TR release lock snapshot identity is invalid")
    if not isinstance(value.get("renderer"), dict) or not isinstance(value.get("catalog"), dict):
        raise ValueError("TR release lock is incomplete: renderer/catalog contracts are required")
    return value


def _context(args: argparse.Namespace, *, require_lock: bool = True) -> Context:
    repo_root = _repo_root()
    profile_path = _resolved(repo_root, args.profile)
    source_root = _resolved(repo_root, args.source_root)
    lock_path = _resolved(repo_root, args.lock)
    profile = load_profile(profile_path)
    _assert_future_dataset_id(
        profile.dataset_id,
        repo_root / "apps/web/public/datasets/index.json",
    )
    lock = _read_lock(lock_path, profile) if require_lock else {}
    return Context(repo_root, profile_path, lock_path, source_root, profile, lock)


def _plugin_paths(
    profile: ReleaseProfile, source_root: Path
) -> tuple[Path, ...]:
    by_filename = {item.filename.casefold(): item for item in profile.required_inputs}
    return tuple(
        source_root / profile.input_relative_path(by_filename[name.casefold()])
        for name in profile.content_files
    )


def _derive_renderer_contract(
    *,
    profile: ReleaseProfile,
    source_root: Path,
    lock_identity: Mapping[str, Any],
) -> dict[str, Any]:
    from tools.land_renderer.tiles import TileGrid
    from tools.openmw_renderer import production

    cells = production.derive_effective_land_cells(_plugin_paths(profile, source_root))
    topology = derive_land_topology(cells, probe_count=16)
    if topology.native_cross_shard_adjacencies < 16 or len(topology.probes) < 16:
        raise ValueError("TR LAND topology must provide at least 16 cross-shard audit probes")
    production.DATASET_ID = str(lock_identity["datasetId"])
    production.SNAPSHOT_ID = str(lock_identity["snapshotId"])
    production.POISON_WORLD_EXTENT = topology.extent
    production.POISON_SONG_TILE_GRID = TileGrid(
        origin_x=float(topology.origin[0]), origin_y=float(topology.origin[1])
    )
    production.PRODUCTION_SOURCE_PATHS = tuple(
        dict.fromkeys(
            (
                *production.PRODUCTION_SOURCE_PATHS,
                *RELEASE_PRODUCTION_SOURCE_PATHS,
            )
        )
    )
    plan = production.plan_report(cells)
    if plan["targetCount"] != topology.effective_cells or plan["shardCount"] != len(
        topology.shard_centers
    ):
        raise RuntimeError("Generic LAND topology and production plan disagree")
    tile_counts = {str(item.zoom): item.tile_count for item in topology.zooms}
    adjacencies = {
        str(item.zoom): {
            "east": item.east_adjacencies,
            "north": item.north_adjacencies,
        }
        for item in topology.zooms
    }
    native = topology.zooms[-1]
    scope = {
        "tiles": topology.total_tiles,
        "nativeTiles": topology.effective_cells,
        "lowerZoomTiles": topology.total_tiles - topology.effective_cells,
        "shards": len(topology.shard_centers),
        "allFinalAdjacencies": topology.total_adjacencies,
        "nativeAdjacencies": native.adjacencies,
        "nativeCrossShardAdjacencies": topology.native_cross_shard_adjacencies,
        "rawCrossShardProbes": 16,
    }
    return {
        "extent": list(topology.extent),
        "origin": list(topology.origin),
        "resolutions": [
            int(production.POISON_SONG_TILE_GRID.units_per_pixel(zoom))
            for zoom in range(topology.native_zoom + 1)
        ],
        "effectiveCells": topology.effective_cells,
        "cellsSha256": canonical_json_sha256([list(cell) for cell in cells]),
        "planFingerprint": plan["planFingerprint"],
        "tileCounts": tile_counts,
        "adjacencies": adjacencies,
        "scope": scope,
        "pinnedRawProbeIds": list(topology.probes[:2]),
        "producer": {
            "image": PRODUCTION_IMAGE,
            "openmwCommit": production.OPENMW_COMMIT,
            "rendererVersion": production.PRODUCTION_RENDERER_VERSION,
            "rendererFingerprint": production.renderer_fingerprint(_repo_root()),
            "productionSourceFingerprint": production.production_source_fingerprint(
                _repo_root()
            ),
            "presentation": production.production_presentation_contract(),
        },
    }


def _master_exceptions(
    profile: ReleaseProfile, source: Mapping[str, Any]
) -> tuple[dict[str, object], ...]:
    locked = {str(item["id"]): item for item in source["inputs"]}
    return tuple(
        {
            "dependentSha256": locked[item.dependent_input_id]["sha256"],
            "masterSha256": locked[item.master_input_id]["sha256"],
            "advertisedBytes": item.advertised_bytes,
            "actualBytes": item.actual_bytes,
            "reason": item.reason,
        }
        for item in profile.master_size_exceptions
    )


def _derive_catalog_contract(
    *,
    profile: ReleaseProfile,
    source_root: Path,
    release_lock: Mapping[str, Any],
    extent: Sequence[int],
) -> dict[str, Any]:
    from tools.catalog_pipeline import poison as catalog
    from tools.catalog_pipeline.tes3 import PluginInput

    source = release_lock["source"]
    locked_by_filename = {
        str(item["filename"]).casefold(): item for item in source["inputs"]
    }
    plugins = tuple(
        PluginInput(
            name,
            source_root / str(locked_by_filename[name.casefold()]["relativePath"]),
            str(locked_by_filename[name.casefold()]["sha256"]),
        )
        for name in profile.content_files
    )
    catalog.DATASET_ID = profile.dataset_id
    catalog.SNAPSHOT_ID = str(release_lock["snapshotId"])
    catalog.PLUGIN_REGIONS = profile.plugin_region_map
    catalog.MAP_EXTENT = tuple(int(value) for value in extent)
    catalog.MASTER_SIZE_EXCEPTIONS = _master_exceptions(profile, source)
    world = catalog.merge_plugins(plugins)
    catalog._input_audit(world, source_root)
    build = catalog.build_catalog(
        world,
        dataset_id=profile.dataset_id,
        snapshot_id=str(release_lock["snapshotId"]),
        plugin_regions=profile.plugin_region_map,
    )
    diagnostics = catalog._catalog_artifact_metrics(build.locations, build.english)
    if diagnostics.get("allCoordinatesWithinManifestExtent") is not True:
        raise ValueError("Generated catalog contains coordinates outside the derived LAND extent")
    catalog_counts: dict[str, Any] = {}
    for key, value in build.counts.items():
        if key == "byTypeRule" or key not in diagnostics:
            continue
        if diagnostics[key] != value:
            raise ValueError(f"Catalog model/artifact metric mismatch for {key}")
        catalog_counts[key] = value
    region_keys = (
        "entrancesByRegion",
        "interiorPlacesByRegion",
        "namedExteriorPlacesByRegion",
    )
    region_counts = {key: diagnostics[key] for key in region_keys}
    exclusions = {
        **build.dropped,
        "unreachableInteriorCells": world.counts["effectiveInteriorCells"]
        - build.counts["interiorPlaces"],
        "explicitDenylistEntries": 0,
        "automaticTestNameFiltering": False,
    }
    return {
        "worldCounts": world.counts,
        "catalogCounts": catalog_counts,
        "resolutionCounts": build.resolution,
        "regionCounts": region_counts,
        "dropped": build.dropped,
        "exclusions": exclusions,
        "policyFingerprint": build.policy_fingerprint,
        "implementationSha256": catalog._implementation_audit(_repo_root())["sha256"],
    }


def _command_check(args: argparse.Namespace) -> int:
    context = _context(args, require_lock=False)
    audit = check_source(context.profile, context.source_root)
    _json_output(
        {
            "datasetId": context.profile.dataset_id,
            "profile": str(context.profile_path),
            "source": audit.to_dict(),
            "valid": True,
        }
    )
    return 0


def _command_lock(args: argparse.Namespace) -> int:
    context = _context(args, require_lock=False)
    generated = generate_release_lock(context.profile, context.source_root)
    value = generated.to_dict()
    renderer = _derive_renderer_contract(
        profile=context.profile,
        source_root=context.source_root,
        lock_identity=value,
    )
    value["renderer"] = renderer
    value["catalog"] = _derive_catalog_contract(
        profile=context.profile,
        source_root=context.source_root,
        release_lock=value,
        extent=renderer["extent"],
    )
    value["lockSha256"] = canonical_json_sha256(value)
    _atomic_write(context.lock_path, canonical_json_bytes(value) + b"\n")
    _json_output(
        {
            "datasetId": context.profile.dataset_id,
            "lock": str(context.lock_path),
            "lockSha256": value["lockSha256"],
            "profileFingerprint": value["profileFingerprint"],
            "snapshotId": value["snapshotId"],
        }
    )
    return 0


def _activate_pipeline(context: Context):
    from tools.tr_release.bootstrap import activate

    return activate(context.profile.to_dict(), context.lock)


def _assert_plan(context: Context, plan_path: Path) -> None:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    expected = context.lock["renderer"]
    if (
        plan.get("datasetId") != context.dataset_id
        or plan.get("snapshotId") != context.lock["snapshotId"]
        or plan.get("planFingerprint") != expected["planFingerprint"]
        or plan.get("targetCount") != expected["effectiveCells"]
        or plan.get("shardCount") != expected["scope"]["shards"]
    ):
        raise ValueError("Generated renderer plan does not match release.lock.json")


def _command_plan(args: argparse.Namespace) -> int:
    context = _context(args)
    pipeline = _activate_pipeline(context)
    plan_path = context.production_root / "plan.json"
    result = pipeline.production.main(
        [
            "plan",
            "--source-root",
            str(context.source_root),
            "--output-plan",
            str(plan_path),
        ]
    )
    if result == 0:
        _assert_plan(context, plan_path)
    return int(result)


def _command_renderer_build(args: argparse.Namespace) -> int:
    context = _context(args)
    return int(_activate_pipeline(context).production.main(["build", "--image", PRODUCTION_IMAGE]))


def _command_renderer_smoke(args: argparse.Namespace) -> int:
    context = _context(args)
    production = _activate_pipeline(context).production
    results: dict[str, int] = {}
    for control in context.profile.smoke_centers:
        output = context.repo_root / "local-data/tr-release/smoke" / context.dataset_id / control.id
        result = int(
            production.main(
                [
                    "smoke",
                    "--source-root",
                    str(context.source_root),
                    "--output",
                    str(output),
                    "--center",
                    f"{control.cell[0]},{control.cell[1]}",
                    "--image",
                    PRODUCTION_IMAGE,
                    "--retain-raw",
                ]
            )
        )
        results[control.id] = result
        if result != 0:
            return result
    _json_output({"controls": results, "datasetId": context.dataset_id, "passes": True})
    return 0


def _command_renderer_render(args: argparse.Namespace) -> int:
    context = _context(args)
    argv = [
        "render",
        "--source-root",
        str(context.source_root),
        "--output",
        str(context.production_root),
        "--image",
        PRODUCTION_IMAGE,
        "--workers",
        str(args.workers),
    ]
    if args.retain_raw:
        argv.append("--retain-raw")
    return int(_activate_pipeline(context).production.main(argv))


def _command_renderer_finalize(args: argparse.Namespace) -> int:
    context = _context(args)
    return int(
        _activate_pipeline(context).production.main(
            [
                "finalize",
                "--source-root",
                str(context.source_root),
                "--output",
                str(context.production_root),
                "--image",
                PRODUCTION_IMAGE,
            ]
        )
    )


def _command_renderer_stabilize(args: argparse.Namespace) -> int:
    context = _context(args)
    return int(
        _activate_pipeline(context).stabilize.main(
            [
                "--source",
                str(context.production_root),
                "--output",
                str(context.release_root),
                "--workers",
                str(args.workers),
            ]
        )
    )


def _command_renderer_audit(args: argparse.Namespace) -> int:
    context = _context(args)
    return int(
        _activate_pipeline(context).audit.main(
            [
                "full",
                "--output",
                str(context.release_root),
                "--source-root",
                str(context.source_root),
                "--image",
                PRODUCTION_IMAGE,
                "--workers",
                str(args.workers),
                "--render-workers",
                str(args.render_workers),
            ]
        )
    )


def _command_dataset_validate(args: argparse.Namespace) -> int:
    context = _context(args)
    return int(
        _activate_pipeline(context).publish.main(
            ["--source-root", str(context.release_root), "validate", "--require-quality"]
        )
    )


def _command_dataset_prepare(args: argparse.Namespace) -> int:
    context = _context(args)
    return int(
        _activate_pipeline(context).publish.main(
            [
                "--source-root",
                str(context.release_root),
                "prepare",
                "--public-root",
                str(context.repo_root / "apps/web/public/datasets/generated"),
                "--metadata-root",
                str(context.repo_root / "apps/web/public/datasets/metadata" / context.dataset_id),
                "--copy-mode",
                args.copy_mode,
            ]
        )
    )


def _command_catalog_build(args: argparse.Namespace) -> int:
    context = _context(args)
    return int(
        _activate_pipeline(context).catalog.main(
            [
                "build",
                "--source-root",
                str(context.source_root),
                "--output",
                str(context.catalog_root),
            ]
        )
    )


def _command_catalog_validate(args: argparse.Namespace) -> int:
    context = _context(args)
    return int(
        _activate_pipeline(context).catalog.main(
            ["validate", "--source", str(context.catalog_root)]
        )
    )


def _command_catalog_prepare(args: argparse.Namespace) -> int:
    context = _context(args)
    return int(
        _activate_pipeline(context).catalog.main(
            [
                "prepare",
                "--source",
                str(context.catalog_root),
                "--public-root",
                str(context.repo_root / "apps/web/public/datasets/generated"),
                "--metadata-root",
                str(context.repo_root / "apps/web/public/datasets/metadata"),
            ]
        )
    )


def _candidate_arguments(context: Context) -> dict[str, object]:
    return {
        "profile": context.profile.to_dict(),
        "lock": context.lock,
        "generated_root": context.repo_root / "apps/web/public/datasets/generated",
        "metadata_root": context.repo_root / "apps/web/public/datasets/metadata",
        "active_datasets_root": context.repo_root / "apps/web/public/datasets",
        "candidate_root": context.candidate_root,
    }


def _command_manifest_build(args: argparse.Namespace) -> int:
    from tools.tr_release.candidate import build_candidate

    context = _context(args)
    result = build_candidate(**_candidate_arguments(context))
    _json_output(_candidate_payload(result))
    return 0


def _command_release_verify(args: argparse.Namespace) -> int:
    from tools.tr_release.candidate import verify_candidate

    context = _context(args)
    actual_source = check_source(context.profile, context.source_root).to_dict()
    if actual_source != context.lock["source"]:
        raise ValueError("Current TR source differs from release.lock.json")
    renderer = _derive_renderer_contract(
        profile=context.profile,
        source_root=context.source_root,
        lock_identity=context.lock,
    )
    if renderer != context.lock["renderer"]:
        raise ValueError("Current LAND plan/topology differs from release.lock.json")
    result = verify_candidate(**_candidate_arguments(context))
    _json_output(
        {
            "candidate": _candidate_payload(result),
            "datasetId": context.dataset_id,
            "lockSha256": context.lock["lockSha256"],
            "valid": True,
        }
    )
    return 0


def _command_activate(args: argparse.Namespace) -> int:
    from tools.tr_release.candidate import activate_candidate

    context = _context(args)
    result = activate_candidate(**_candidate_arguments(context))
    _json_output(_candidate_payload(result))
    return 0


def activate_after_gates() -> int:
    """Internal activation entry point used only by the full workflow orchestrator."""

    return _command_activate(
        argparse.Namespace(
            profile=DEFAULT_PROFILE,
            lock=DEFAULT_LOCK,
            source_root=_repo_root().parent / "morr-dev",
        )
    )


def _parser() -> argparse.ArgumentParser:
    repo_root = _repo_root()
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    common.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    common.add_argument("--source-root", type=Path, default=repo_root.parent / "morr-dev")
    parser = argparse.ArgumentParser(description="Tamriel Rebuilt release workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "check",
        "lock",
        "plan",
        "renderer-build",
        "renderer-smoke",
        "renderer-finalize",
        "dataset-validate",
        "catalog-build",
        "catalog-validate",
        "catalog-prepare",
        "manifest-build",
        "release-verify",
    ):
        subparsers.add_parser(name, parents=[common])
    for name in ("renderer-render", "renderer-stabilize"):
        command = subparsers.add_parser(name, parents=[common])
        command.add_argument("--workers", type=int, default=2 if name != "renderer-stabilize" else 4)
    render = subparsers.choices["renderer-render"]
    render.add_argument("--retain-raw", action="store_true")
    audit = subparsers.add_parser("renderer-audit", parents=[common])
    audit.add_argument("--workers", type=int, default=4)
    audit.add_argument("--render-workers", type=int, default=2)
    prepare = subparsers.add_parser("dataset-prepare", parents=[common])
    prepare.add_argument("--copy-mode", choices=("auto", "copy"), default="auto")
    return parser


_COMMANDS = {
    "check": _command_check,
    "lock": _command_lock,
    "plan": _command_plan,
    "renderer-build": _command_renderer_build,
    "renderer-smoke": _command_renderer_smoke,
    "renderer-render": _command_renderer_render,
    "renderer-finalize": _command_renderer_finalize,
    "renderer-stabilize": _command_renderer_stabilize,
    "renderer-audit": _command_renderer_audit,
    "dataset-validate": _command_dataset_validate,
    "dataset-prepare": _command_dataset_prepare,
    "catalog-build": _command_catalog_build,
    "catalog-validate": _command_catalog_validate,
    "catalog-prepare": _command_catalog_prepare,
    "manifest-build": _command_manifest_build,
    "release-verify": _command_release_verify,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return int(_COMMANDS[args.command](args))


if __name__ == "__main__":
    sys.exit(main())
