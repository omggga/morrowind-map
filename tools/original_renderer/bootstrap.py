from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

from tools.original_renderer import profile
from tools.original_renderer.publish_contract import install as install_publish_contract
from tools.land_renderer.tiles import TileGrid


DATASET_ID = "original-goty-hd"
SNAPSHOT_ID = "original:goty:8b2690c0ce1c954e"
PINNED_PROFILE_FINGERPRINT = (
    "8b2690c0ce1c954e603d317728b19339f4b985ce3c362b0bc0eee93b3841b2a7"
)
WORLD_EXTENT = (-229_376, -155_648, 196_608, 237_568)
ORIGINAL_TILE_ORIGIN = (-229_376, 237_568)
EXPECTED_TILE_COUNTS = {0: 1, 1: 1, 2: 4, 3: 10, 4: 33, 5: 115, 6: 410, 7: 1540}
EXPECTED_ADJACENCIES = {
    (0, "east"): 0,
    (0, "north"): 0,
    (1, "east"): 0,
    (1, "north"): 0,
    (2, "east"): 2,
    (2, "north"): 2,
    (3, "east"): 7,
    (3, "north"): 6,
    (4, "east"): 27,
    (4, "north"): 26,
    (5, "east"): 101,
    (5, "north"): 102,
    (6, "east"): 380,
    (6, "north"): 383,
    (7, "east"): 1478,
    (7, "north"): 1486,
}
EXPECTED_TOTAL_TILES = 2_114
EXPECTED_NATIVE_TILES = 1_540
EXPECTED_SHARDS = 198
EXPECTED_TOTAL_ADJACENCIES = 4_000
EXPECTED_NATIVE_ADJACENCIES = 2_964
EXPECTED_NATIVE_CROSS_SHARD = 999
EXPECTED_PLAN_FINGERPRINT = "9ad7c36652b18615234819aba986df32a89125b1365d47eddef0f847af90886c"
PINNED_RAW_PROBE_IDS = (
    "7/25/30:north:7/25/29",
    "7/2/0:east:7/3/0",
)
AUDIT_VERSION = "original-goty-basemap-quality-binary-alpha-v1"
DEFAULT_IMAGE = "morrowind-map-openmw:0.51.0-original-hd-v1"

ORIGINAL_SOURCE_PATHS = (
    ".dockerignore",
    "tools/tes3/records.py",
    "tools/land_renderer/land.py",
    "tools/land_renderer/terrain.py",
    "tools/land_renderer/tiles.py",
    "tools/openmw_renderer/images.py",
    "tools/openmw_renderer/spike.py",
    "tools/openmw_renderer/production.py",
    "tools/openmw_renderer/publish.py",
    "tools/openmw_renderer/stabilize.py",
    "tools/openmw_renderer/audit.py",
    "tools/openmw_renderer/entrypoint-production.sh",
    "tools/openmw_renderer/patches/openmw-0.51.0-map-export-batch.patch",
    "tools/original_renderer/__init__.py",
    "tools/original_renderer/profile.py",
    "tools/original_renderer/bootstrap.py",
    "tools/original_renderer/publish_contract.py",
    "tools/original_renderer/production.py",
    "tools/original_renderer/stabilize.py",
    "tools/original_renderer/audit.py",
    "tools/original_renderer/publish.py",
    "tools/original_renderer/Dockerfile.production",
)

_FROZEN_MODULES = (
    "tools.openmw_renderer.production",
    "tools.openmw_renderer.publish",
    "tools.openmw_renderer.stabilize",
    "tools.openmw_renderer.audit",
)
_activated: tuple[ModuleType, ModuleType, ModuleType, ModuleType] | None = None


def _docker_build_command(
    *,
    repo_root: Path,
    image: str = DEFAULT_IMAGE,
    stage45_image: str = "morrowind-map-openmw:0.51.0-stage45",
    stage45_image_id: str = "unverified",
) -> list[str]:
    production = sys.modules["tools.openmw_renderer.production"]
    source_hash = production.production_source_fingerprint(repo_root)
    return [
        "docker",
        "build",
        "--platform",
        profile.DOCKER_PLATFORM,
        "--file",
        str(repo_root / "tools/original_renderer/Dockerfile.production"),
        "--tag",
        image,
        "--build-arg",
        f"STAGE45_IMAGE={stage45_image}",
        "--build-arg",
        f"STAGE45_IMAGE_ID={stage45_image_id}",
        "--build-arg",
        f"PRODUCTION_FINGERPRINT={source_hash}",
        str(repo_root),
    ]


def activate() -> tuple[ModuleType, ModuleType, ModuleType, ModuleType]:
    """Activate Original identity before importing any frozen pipeline module."""

    global _activated
    if _activated is not None:
        return _activated
    already_loaded = [name for name in _FROZEN_MODULES if name in sys.modules]
    if already_loaded:
        raise RuntimeError(
            "Original renderer must start in a fresh subprocess before the frozen "
            f"Poison modules are imported: {already_loaded}"
        )

    sys.modules["tools.openmw_renderer.profile"] = profile
    production = importlib.import_module("tools.openmw_renderer.production")
    production.DATASET_ID = DATASET_ID
    production.SNAPSHOT_ID = SNAPSHOT_ID
    production.PINNED_PROFILE_FINGERPRINT = PINNED_PROFILE_FINGERPRINT
    production.DEFAULT_OUTPUT = Path("local-data/openmw-production") / DATASET_ID
    production.DEFAULT_PRODUCTION_IMAGE = DEFAULT_IMAGE
    production.POISON_WORLD_EXTENT = WORLD_EXTENT
    production.POISON_SONG_TILE_GRID = TileGrid(
        origin_x=float(ORIGINAL_TILE_ORIGIN[0]),
        origin_y=float(ORIGINAL_TILE_ORIGIN[1]),
    )
    production.PRODUCTION_SOURCE_PATHS = ORIGINAL_SOURCE_PATHS
    production.docker_build_command = _docker_build_command
    # The pinned Original profile fingerprint was derived from this exact
    # config.  Do not inherit Poison-specific fallback mutations here.
    production.render_production_openmw_cfg = profile.render_openmw_cfg

    publish = importlib.import_module("tools.openmw_renderer.publish")
    publish.TILE_PYRAMID_ID = f"{DATASET_ID}.basemap"
    publish.TILE_REGIONS = ("vvardenfell", "solstheim")
    publish.EXPECTED_TILE_COUNTS = EXPECTED_TILE_COUNTS
    publish.PINNED_RAW_PROBE_IDS = PINNED_RAW_PROBE_IDS
    publish.EXPECTED_PLAN_FINGERPRINT = EXPECTED_PLAN_FINGERPRINT
    publish.DEFAULT_RELEASE_OUTPUT = Path("local-data/openmw-release") / DATASET_ID
    publish.DEFAULT_METADATA_ROOT = Path("apps/web/public/datasets/metadata") / DATASET_ID
    publish.EXPECTED_AUDIT_VERSION = AUDIT_VERSION
    publish.POISON_WORLD_EXTENT = WORLD_EXTENT
    publish.EXPECTED_QUALITY_SCOPE = {
        "tiles": EXPECTED_TOTAL_TILES,
        "nativeTiles": EXPECTED_NATIVE_TILES,
        "lowerZoomTiles": EXPECTED_TOTAL_TILES - EXPECTED_NATIVE_TILES,
        "shards": EXPECTED_SHARDS,
        "allFinalAdjacencies": EXPECTED_TOTAL_ADJACENCIES,
        "nativeAdjacencies": EXPECTED_NATIVE_ADJACENCIES,
        "nativeCrossShardAdjacencies": EXPECTED_NATIVE_CROSS_SHARD,
        "rawCrossShardProbes": 16,
    }
    install_publish_contract(
        publish,
        production,
        origin=ORIGINAL_TILE_ORIGIN,
    )

    stabilize = importlib.import_module("tools.openmw_renderer.stabilize")
    stabilize.DEFAULT_STABILIZED_OUTPUT = Path("local-data/openmw-release") / DATASET_ID
    stabilize.EXPECTED_CROSS_SHARD_EDGES = EXPECTED_NATIVE_CROSS_SHARD

    audit = importlib.import_module("tools.openmw_renderer.audit")
    audit.AUDIT_VERSION = AUDIT_VERSION
    audit.EXPECTED_TILE_COUNTS = EXPECTED_TILE_COUNTS
    audit.EXPECTED_ADJACENCIES = {
        key: value for key, value in EXPECTED_ADJACENCIES.items() if value
    }
    audit.EXPECTED_TOTAL_TILES = EXPECTED_TOTAL_TILES
    audit.EXPECTED_NATIVE_TILES = EXPECTED_NATIVE_TILES
    audit.EXPECTED_SHARDS = EXPECTED_SHARDS
    audit.EXPECTED_TOTAL_ADJACENCIES = EXPECTED_TOTAL_ADJACENCIES
    audit.EXPECTED_NATIVE_ADJACENCIES = EXPECTED_NATIVE_ADJACENCIES
    audit.EXPECTED_NATIVE_CROSS_SHARD = EXPECTED_NATIVE_CROSS_SHARD
    audit.PINNED_RAW_PROBE_IDS = PINNED_RAW_PROBE_IDS
    audit.EXPECTED_SCOPE = dict(publish.EXPECTED_QUALITY_SCOPE)

    frozen_audit_snapshot = audit._run_full_audit_from_snapshot

    def original_audit_snapshot(*args: object, **kwargs: object) -> dict[str, object]:
        report = frozen_audit_snapshot(*args, **kwargs)
        core = {key: value for key, value in report.items() if key != "auditSha256"}
        core["limitations"] = [
            "The 32px raw gutters are retained only for the deterministic raw-probe sample, not all 198 Original GOTY production shards.",
            "Every final adjacency is audited; raw duplicate-gutter equality is re-rendered for 16 deterministic Original GOTY cross-shard controls.",
            "Tribunal contributes records and assets but no exterior LAND; Mournhold therefore requires a separate interior inset and is outside this exterior basemap.",
        ]
        return audit.report_with_hash(core)

    audit._run_full_audit_from_snapshot = original_audit_snapshot

    _activated = production, publish, stabilize, audit
    return _activated
