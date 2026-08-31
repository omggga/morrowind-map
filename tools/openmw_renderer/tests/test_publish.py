from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.openmw_renderer import publish as publish_module
from tools.openmw_renderer.production import (
    DATASET_ID,
    OPENMW_COMMIT,
    POISON_WORLD_EXTENT,
    SNAPSHOT_ID,
    TileKey,
    _shard_center,
    cell_for_native_tile,
    execution_provenance_fingerprint,
    plan_report,
    production_presentation_contract,
)
from tools.openmw_renderer.publish import (
    EXPECTED_AUDIT_VERSION,
    LEGACY_AUDIT_IMPLEMENTATION_SHA256,
    LEGACY_AUDIT_VERSION,
    MANDATORY_QUALITY_GATES,
    PUBLISHED_QUALITY_REPORT_NAME,
    TILE_PYRAMID_ID,
    _publish_staged_directory_no_replace,
    _require_ignored_worktree_target,
    build_publish_metadata,
    build_tile_coverage,
    prepare_dataset,
    validate_quality_report,
    validate_source,
    write_publish_metadata,
)


FINGERPRINTS = {
    "profile": "3" * 64,
    "renderer": "4" * 64,
    "production": "5" * 64,
}
FIXTURE_STABILIZER_IMPLEMENTATION = "8" * 64

FIXTURE_COORDINATES = tuple(
    [(zoom, 0, 0) for zoom in range(6)]
    + [(6, 0, 0), (6, 0, 1)]
    + [(7, 0, 0), (7, 0, 1), (7, 0, 2), (7, 0, 3), (7, 1, 0)]
)
FIXTURE_TILE_COUNTS = {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 2, 7: 5}
FIXTURE_NATIVE = {TileKey(z, x, y) for z, x, y in FIXTURE_COORDINATES if z == 7}
FIXTURE_CELLS = tuple(sorted(cell_for_native_tile(tile) for tile in FIXTURE_NATIVE))
FIXTURE_PLAN = plan_report(FIXTURE_CELLS)
FIXTURE_NATIVE_ADJACENCIES = tuple(
    (tile, neighbor)
    for tile in FIXTURE_NATIVE
    for neighbor in (
        TileKey(7, tile.x + 1, tile.y),
        TileKey(7, tile.x, tile.y - 1),
    )
    if neighbor in FIXTURE_NATIVE
)
FIXTURE_QUALITY_SCOPE = {
    "tiles": len(FIXTURE_COORDINATES),
    "nativeTiles": len(FIXTURE_NATIVE),
    "lowerZoomTiles": len(FIXTURE_COORDINATES) - len(FIXTURE_NATIVE),
    "shards": len(FIXTURE_PLAN["shards"]),
    "allFinalAdjacencies": len(FIXTURE_NATIVE_ADJACENCIES) + 1,
    "nativeAdjacencies": len(FIXTURE_NATIVE_ADJACENCIES),
    "nativeCrossShardAdjacencies": sum(
        _shard_center(cell_for_native_tile(first))
        != _shard_center(cell_for_native_tile(second))
        for first, second in FIXTURE_NATIVE_ADJACENCIES
    ),
    "rawCrossShardProbes": 2,
}


def _fixture_scope_patches() -> mock._patch:
    return mock.patch.multiple(
        publish_module,
        EXPECTED_TILE_COUNTS=FIXTURE_TILE_COUNTS,
        EXPECTED_QUALITY_SCOPE=FIXTURE_QUALITY_SCOPE,
        EXPECTED_PLAN_FINGERPRINT=FIXTURE_PLAN["planFingerprint"],
    )


def _fixture_validated_stabilization(
    source_root: Path,
    _inventory: object,
) -> tuple[dict[str, object], str]:
    return (
        json.loads((source_root / "seam-stabilization.json").read_text(encoding="utf-8")),
        FIXTURE_STABILIZER_IMPLEMENTATION,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> bytes:
    payload = _canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _legacy_provenance_fingerprint(provenance: dict[str, object]) -> str:
    image = provenance["image"]
    assert isinstance(image, dict)
    return _sha256(
        _canonical(
            {
                "datasetId": DATASET_ID,
                "snapshotId": SNAPSHOT_ID,
                "rendererVersion": "openmw-export-production-v1",
                "profileFingerprint": provenance["profileFingerprint"],
                "productionSourceFingerprint": provenance[
                    "productionSourceFingerprint"
                ],
                "openmwCommit": OPENMW_COMMIT,
                "imageId": image["id"],
                "imageRepoDigests": sorted(set(image["repoDigests"])),
                "gradeVersion": "mim-muted-v1",
                "magickVersion": provenance["magickVersion"],
            }
        )
    )


def _released_repeat_evidence(*, v4: bool) -> list[dict[str, object]]:
    if not v4:
        return [
            {"passes": True, "opaqueDifferingPixels": 0},
            {"passes": True, "opaqueDifferingPixels": 0},
        ]
    return [
        {
            "passes": True,
            "opaqueDifferingPixels": 5_096,
            "differingFraction": 0.019515857,
            "alphaDifferingFraction": 0.0,
            "meanAbsoluteChannelDelta": 0.049099843,
            "p99PixelDelta": 3.0,
            "hardPixelDelta": 8,
            "hardPixelFraction": 0.001976095,
            "maximumOpaqueChannelDelta": 34,
            "largestHardComponentPixels": 9,
        },
        {
            "passes": True,
            "opaqueDifferingPixels": 5_740,
            "differingFraction": 0.021982146,
            "alphaDifferingFraction": 0.0,
            "meanAbsoluteChannelDelta": 0.089869256,
            "p99PixelDelta": 4.0,
            "hardPixelDelta": 8,
            "hardPixelFraction": 0.005438092,
            "maximumOpaqueChannelDelta": 37,
            "largestHardComponentPixels": 11,
        },
    ]


def _fixture(
    root: Path,
    *,
    with_quality: bool = True,
    v4: bool = True,
) -> dict[str, object]:
    tiles = []
    for z, x, y in FIXTURE_COORDINATES:
        payload = f"fixture-webp-{z}-{x}-{y}".encode("ascii")
        relative = f"tiles/{z}/{x}/{y}.webp"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        tiles.append(
            {
                "z": z,
                "x": x,
                "y": y,
                "path": relative,
                "bytes": len(payload),
                "sha256": _sha256(payload),
            }
        )
    asset_audit = {"fixture-assets": {"bytes": 10, "files": 2, "sha256": "a" * 64}}
    input_audit = {"fixture": {"sha256": "b" * 64}}
    provenance = {
        "schemaVersion": 2 if v4 else 1,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "rendererVersion": (
            "openmw-export-production-v2"
            if v4
            else "openmw-export-production-v1"
        ),
        "openmwCommit": OPENMW_COMMIT,
        "profileFingerprint": FINGERPRINTS["profile"],
        "productionSourceFingerprint": FINGERPRINTS["production"],
        "magickVersion": "fixture-magick-v1",
        "image": {
            "id": "sha256:" + "6" * 64,
            "repoDigests": ["fixture@example@sha256:" + "7" * 64],
            "labels": {
                "io.morrowind-map.renderer-fingerprint": FINGERPRINTS["renderer"]
            },
        },
        "assetAudit": asset_audit,
        "inputAudit": input_audit,
    }
    if v4:
        provenance["presentation"] = production_presentation_contract()
        provenance["provenanceFingerprint"] = execution_provenance_fingerprint(
            profile_fingerprint=FINGERPRINTS["profile"],
            production_source_fingerprint_value=FINGERPRINTS["production"],
            image_id=str(provenance["image"]["id"]),  # type: ignore[index]
            image_repo_digests=list(provenance["image"]["repoDigests"]),  # type: ignore[index]
            magick_version=str(provenance["magickVersion"]),
        )
    else:
        provenance["provenanceFingerprint"] = _legacy_provenance_fingerprint(
            provenance
        )
    provenance_bytes = _write_json(root / "provenance.json", provenance)
    plan_bytes = _write_json(root / "plan.json", FIXTURE_PLAN)

    inventory_core = {
        "schemaVersion": 1,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "rendererVersion": "fixture-renderer-v1",
        "provenanceFingerprint": provenance["provenanceFingerprint"],
        "planFingerprint": FIXTURE_PLAN["planFingerprint"],
        "tileFormat": "image/webp",
        "tilePixels": 512,
        "minZoom": 0,
        "maxZoom": 7,
        "origin": [-229376.0, 278528.0],
        "extent": list(POISON_WORLD_EXTENT),
        "tileCount": len(tiles),
        "totalBytes": sum(int(tile["bytes"]) for tile in tiles),
        "tiles": tiles,
    }
    inventory = dict(inventory_core)
    inventory["inventorySha256"] = _sha256(_canonical(inventory_core))
    inventory_bytes = _write_json(root / "inventory.json", inventory)

    source_inventory_bytes = _write_json(
        root / "seam-stabilization" / "source-inventory.json", inventory
    )
    transform_bytes = b"{}\n"
    transform_path = root / "seam-stabilization" / "tile-transforms.ndjson"
    transform_path.write_bytes(transform_bytes)
    stabilization_identity = {
        "algorithm": {
            "boundaryWidthPixels": 1,
            "kernel": "linear-2:1",
            "alphaMode": "premultiplied",
            **({"outputAlphaMode": "binary-nonzero"} if v4 else {}),
            "passes": ["east-west", "north-south"],
            "nativeZoom": 7,
            "tilePixels": 512,
        },
        "implementationSha256": FIXTURE_STABILIZER_IMPLEMENTATION,
        "postprocessToolchain": {
            "productionSourceFingerprint": FINGERPRINTS["production"],
            "imageMagick": {
                "version": "fixture-magick-v1",
                "webpCoder": "WEBP* WEBP rw+ WebP Image Format (libwebp fixture)",
                "executableSha256": "7" * 64,
            },
            "python": {"implementation": "CPython", "version": "fixture"},
        },
        "sourceInventory": {
            "path": "seam-stabilization/source-inventory.json",
            "sha256": _sha256(source_inventory_bytes),
            "bytes": len(source_inventory_bytes),
            "logicalSha256": inventory["inventorySha256"],
        },
        "tileTransforms": {
            "path": "seam-stabilization/tile-transforms.ndjson",
            "sha256": _sha256(transform_bytes),
            "bytes": len(transform_bytes),
            "records": 1,
        },
        "renderCheckpointFileSha256": "9" * 64,
        "provenanceFileSha256": _sha256(provenance_bytes),
        "provenanceFingerprint": provenance["provenanceFingerprint"],
        "planFileSha256": _sha256(plan_bytes),
        "planFingerprint": FIXTURE_PLAN["planFingerprint"],
        "scope": {
            "nativeTiles": len(FIXTURE_NATIVE),
            "crossShardAdjacencies": FIXTURE_QUALITY_SCOPE[
                "nativeCrossShardAdjacencies"
            ],
            "touchedTiles": 1,
            "changedTiles": 1,
        },
    }
    stabilization_fingerprint = _sha256(_canonical(stabilization_identity))
    alpha_evidence = {
        "mode": "binary-nonzero",
        "tilesChecked": len(tiles),
        "transparentPixels": 0,
        "opaquePixels": len(tiles) * 512 * 512,
        "intermediatePixels": 0,
    }
    receipt_core = {
        "schemaVersion": 3 if v4 else 2,
        "datasetId": DATASET_ID,
        "snapshotId": SNAPSHOT_ID,
        "stabilizerVersion": (
            "cross-shard-linear-feather-binary-alpha-v2"
            if v4
            else "cross-shard-linear-feather-v1"
        ),
        "stabilizationFingerprint": stabilization_fingerprint,
        "identity": stabilization_identity,
        "output": {
            "inventorySha256": inventory["inventorySha256"],
            "inventoryFileSha256": _sha256(inventory_bytes),
            "nativeAggregateSha256": "0" * 64,
            "tileCount": len(tiles),
            "totalBytes": inventory["totalBytes"],
            **({"alphaEvidence": alpha_evidence} if v4 else {}),
        },
    }
    receipt = dict(receipt_core)
    receipt["receiptSha256"] = _sha256(_canonical(receipt_core))
    receipt_bytes = _write_json(root / "seam-stabilization.json", receipt)

    if with_quality:
        detail_payloads = {
            "tiles": ("tiles.ndjson", b"{}\n"),
            "seams": ("seams.ndjson", b"{}\n"),
            "resourceRuntime": ("resource-runtime.json", b"{}\n"),
            "worstSeams": ("worst-seams.webp", b"fixture-webp"),
            "seamStabilization": ("seam-stabilization.json", receipt_bytes),
            "rawRendererProvenance": (
                "raw-probes-fixture/provenance.json",
                _canonical(provenance) + b"\n",
            ),
        }
        detail_artifacts = {}
        for name, (relative, payload) in detail_payloads.items():
            path = root / "quality-audit" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            detail_artifacts[name] = {
                "path": relative,
                "sha256": _sha256(payload),
                "bytes": len(payload),
            }
        report_core = {
            "schemaVersion": 2 if v4 else 1,
            "datasetId": DATASET_ID,
            "snapshotId": SNAPSHOT_ID,
            "auditVersion": (
                EXPECTED_AUDIT_VERSION if v4 else LEGACY_AUDIT_VERSION
            ),
            "identity": {
                "inventorySha256": inventory["inventorySha256"],
                "inventoryFileSha256": _sha256(inventory_bytes),
                "provenanceFileSha256": _sha256(provenance_bytes),
                "planFileSha256": _sha256(plan_bytes),
                "provenanceFingerprint": provenance["provenanceFingerprint"],
                "planFingerprint": FIXTURE_PLAN["planFingerprint"],
                "profileFingerprint": FINGERPRINTS["profile"],
                "rendererFingerprint": FINGERPRINTS["renderer"],
                "productionSourceFingerprint": FINGERPRINTS["production"],
                "assetTreeFingerprint": _sha256(_canonical(asset_audit)),
                "inputFingerprint": _sha256(_canonical(input_audit)),
                "stabilizationFingerprint": stabilization_fingerprint,
                "stabilizationReceiptSha256": receipt["receiptSha256"],
                "stabilizationReceiptFileSha256": _sha256(receipt_bytes),
                "stabilizerImplementationSha256": FIXTURE_STABILIZER_IMPLEMENTATION,
                "sourceInventorySha256": inventory["inventorySha256"],
                "auditImplementationSha256": (
                    _sha256(
                        Path(publish_module.__file__)
                        .with_name("audit.py")
                        .read_bytes()
                    )
                    if v4
                    else LEGACY_AUDIT_IMPLEMENTATION_SHA256
                ),
            },
            "scope": dict(FIXTURE_QUALITY_SCOPE),
            "gates": {
                "inventory": {
                    "passes": True,
                    "tileCount": len(tiles),
                    "totalBytes": inventory["totalBytes"],
                    "decoded512Rgba": len(tiles),
                    "nonemptyTiles": len(tiles),
                    **(
                        {
                            "alphaMode": "binary-nonzero",
                            "binaryAlphaTiles": len(tiles),
                            "alphaTransparentPixels": 0,
                            "alphaOpaquePixels": len(tiles) * 512 * 512,
                            "alphaIntermediatePixels": 0,
                        }
                        if v4
                        else {}
                    ),
                    "inventorySha256": inventory["inventorySha256"],
                    "inventoryFileSha256": _sha256(inventory_bytes),
                },
                "seamStabilization": {
                    "passes": True,
                    "stabilizerVersion": receipt["stabilizerVersion"],
                    "stabilizationFingerprint": stabilization_fingerprint,
                    "receiptSha256": receipt["receiptSha256"],
                    "receiptFileSha256": _sha256(receipt_bytes),
                    "implementationSha256": FIXTURE_STABILIZER_IMPLEMENTATION,
                    "postprocessToolchain": stabilization_identity[
                        "postprocessToolchain"
                    ],
                    "sourceInventorySha256": inventory["inventorySha256"],
                    "tileTransformsSha256": _sha256(transform_bytes),
                    "scope": stabilization_identity["scope"],
                    "expectedTouchedTiles": 1,
                    "transformRecords": 1,
                    "verifiedAfterRgbaTiles": 1,
                    "afterRgbaMismatches": 0,
                    "mismatchExamples": [],
                    "beforeRgbaValidation": "format-and-receipt-bound",
                    **(
                        {
                            "alphaEvidence": alpha_evidence,
                            "alphaEvidenceMatchesTiles": True,
                        }
                        if v4
                        else {}
                    ),
                },
                "stateAndMigrations": {
                    "passes": True,
                    "planFingerprint": FIXTURE_PLAN["planFingerprint"],
                    "targetCount": len(FIXTURE_NATIVE),
                    "shardCount": len(FIXTURE_PLAN["shards"]),
                    "checkpointSha256": "c" * 64,
                    "checkpointArtifacts": len(FIXTURE_NATIVE),
                    "checkpointArtifactBytes": 1,
                    "postprocessedNativeTiles": 1,
                    "migrationChain": [],
                    "renderProvenanceBreakdown": [
                        {
                            "provenanceFingerprint": provenance[
                                "provenanceFingerprint"
                            ],
                            "tiles": len(FIXTURE_NATIVE),
                        }
                    ],
                },
                "pyramidDerivation": {
                    "passes": True,
                    "parentsChecked": FIXTURE_QUALITY_SCOPE["lowerZoomTiles"],
                    "expectedParents": FIXTURE_QUALITY_SCOPE["lowerZoomTiles"],
                    "mismatches": [],
                    "tileCountsByZoom": {
                        str(zoom): count
                        for zoom, count in FIXTURE_TILE_COUNTS.items()
                    },
                },
                "finalSeams": {
                    "passes": True,
                    "adjacencies": FIXTURE_QUALITY_SCOPE["allFinalAdjacencies"],
                    "nativeAdjacencies": FIXTURE_QUALITY_SCOPE[
                        "nativeAdjacencies"
                    ],
                    "nativeSameShard": FIXTURE_QUALITY_SCOPE["nativeAdjacencies"]
                    - FIXTURE_QUALITY_SCOPE["nativeCrossShardAdjacencies"],
                    "nativeCrossShard": FIXTURE_QUALITY_SCOPE[
                        "nativeCrossShardAdjacencies"
                    ],
                    "flaggedPairs": 0,
                    "flaggedPairsAreDiagnostic": True,
                    "crossShardStructuralFailures": 0,
                    "crossShardStructuralFailureIds": [],
                    "thresholds": publish_module.EXPECTED_FINAL_SEAM_THRESHOLDS,
                    "sameShardPopulation": {
                        "count": FIXTURE_QUALITY_SCOPE["nativeAdjacencies"]
                        - FIXTURE_QUALITY_SCOPE["nativeCrossShardAdjacencies"]
                    },
                    "crossShardPopulation": {
                        "count": FIXTURE_QUALITY_SCOPE[
                            "nativeCrossShardAdjacencies"
                        ]
                    },
                    "relativePopulationPasses": True,
                    "absolutePopulationPasses": True,
                    "populationPasses": True,
                },
                "runtimeResourcesCoordinates": {
                    "passes": True,
                    "shards": len(FIXTURE_PLAN["shards"]),
                    "targetMarkers": len(FIXTURE_NATIVE),
                    "maximumCoordinateErrorPixels": 0.0,
                    "resourceReports": len(FIXTURE_PLAN["shards"]),
                    "actionableMissingResources": 0,
                    "ignoredCompatibilityWarningEvents": 0,
                    "normalizedBuildManifestSha256": "d" * 64,
                    "buildManifestProductionSources": {
                        FINGERPRINTS["production"]: len(FIXTURE_PLAN["shards"])
                    },
                    "openmwCommit": OPENMW_COMMIT,
                    "runtime": {
                        "sumContainerSeconds": 1,
                        "maximumContainerSeconds": 1,
                        "maximumMemoryPeakBytes": 1,
                        "os": "linux",
                        "architecture": "amd64",
                        "renderer": "llvmpipe",
                    },
                },
                "rawProbes": {
                    "passes": True,
                    "status": "passed",
                    "selectedCrossShardSeams": 2,
                    "selectionSha256": "e" * 64,
                    "uniqueCells": 4,
                    "targetCells": 4,
                    "completedCells": 4,
                    "rendererProvenance": {
                        "passes": True,
                        "mode": "exact",
                        "releasedProvenanceFingerprint": provenance[
                            "provenanceFingerprint"
                        ],
                        "candidateProvenanceFingerprint": provenance[
                            "provenanceFingerprint"
                        ],
                        "releasedImageId": provenance["image"]["id"],
                        "candidateImageId": provenance["image"]["id"],
                        "candidatePayloadSha256": _sha256(_canonical(provenance)),
                        "rendererContractEqual": True,
                        "nonImageProvenanceEqual": True,
                    },
                    "thresholds": (
                        publish_module.EXPECTED_RAW_THRESHOLDS
                        if v4
                        else publish_module.LEGACY_RAW_THRESHOLDS
                    ),
                    "selectionStrategy": "pinned-plus-directional-risk-strata-v2",
                    "pinnedProbeIds": list(publish_module.PINNED_RAW_PROBE_IDS),
                    "probes": [
                        {
                            "id": identifier,
                            "passes": True,
                            "sourceOverlapPasses": True,
                            "releaseSeamPasses": True,
                            "repairRequired": False,
                            "repairCoveredByReceipt": False,
                            "releasedRepeat": _released_repeat_evidence(v4=v4),
                        }
                        for identifier in publish_module.PINNED_RAW_PROBE_IDS
                    ],
                },
            },
            "artifacts": detail_artifacts,
            "contactSheet": {
                "samples": 1,
                "crossShardSamples": 1,
                "width": 128,
                "height": 128,
                "sha256": detail_artifacts["worstSeams"]["sha256"],
                "bytes": detail_artifacts["worstSeams"]["bytes"],
            },
            "limitations": ["fixture"],
            "passes": True,
        }
        report = dict(report_core)
        report["auditSha256"] = _sha256(_canonical(report_core))
        _write_json(root / "quality-audit" / "report.json", report)
    return inventory


@_fixture_scope_patches()
@mock.patch.object(
    publish_module,
    "_validated_stabilization",
    new=_fixture_validated_stabilization,
)
class CoverageTests(unittest.TestCase):
    def test_coverage_is_compact_sorted_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            inventory = validate_source(root)

            first = build_tile_coverage(inventory)
            second = build_tile_coverage(inventory)

        self.assertEqual(first, second)
        self.assertEqual(first["tilePyramidId"], TILE_PYRAMID_ID)
        self.assertEqual(first["tileCount"], len(FIXTURE_COORDINATES))
        self.assertEqual([level["z"] for level in first["levels"]], list(range(8)))
        self.assertEqual(
            first["levels"][-1],
            {
                "z": 7,
                "columns": [
                    {"x": 0, "yRanges": [[0, 3]]},
                    {"x": 1, "yRanges": [[0, 0]]},
                ],
            },
        )


@_fixture_scope_patches()
@mock.patch.object(
    publish_module,
    "_validated_stabilization",
    new=_fixture_validated_stabilization,
)
class ValidationTests(unittest.TestCase):
    def test_v4_quality_accepts_bounded_opaque_repeat_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)

            quality = validate_quality_report(root, validate_source(root))
            report = json.loads(quality.path.read_text(encoding="utf-8"))

        repeats = report["gates"]["rawProbes"]["probes"][0]["releasedRepeat"]
        self.assertEqual(
            [repeat["opaqueDifferingPixels"] for repeat in repeats],
            [5_096, 5_740],
        )

    def test_v4_quality_accepts_repeat_metric_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            inventory = validate_source(root)
            report_path = root / "quality-audit" / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            repeat = report["gates"]["rawProbes"]["probes"][0][
                "releasedRepeat"
            ][0]
            repeat["maximumOpaqueChannelDelta"] = 48
            repeat["largestHardComponentPixels"] = 16
            report["auditSha256"] = _sha256(
                _canonical(
                    {
                        key: value
                        for key, value in report.items()
                        if key != "auditSha256"
                    }
                )
            )
            _write_json(report_path, report)

            validate_quality_report(root, inventory)

    def test_v4_quality_rechecks_every_repeat_limit(self) -> None:
        excesses = (
            ("differingFraction", 0.030001),
            ("alphaDifferingFraction", 0.020001),
            ("meanAbsoluteChannelDelta", 0.100001),
            ("meanAbsoluteChannelDelta", 10**1_000),
            ("p99PixelDelta", 8.001),
            ("hardPixelDelta", 9),
            ("hardPixelFraction", 0.010001),
            ("maximumOpaqueChannelDelta", 49),
            ("largestHardComponentPixels", 17),
        )
        for field, value in excesses:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    _fixture(root)
                    inventory = validate_source(root)
                    report_path = root / "quality-audit" / "report.json"
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    report["gates"]["rawProbes"]["probes"][0][
                        "releasedRepeat"
                    ][0][field] = value
                    report["auditSha256"] = _sha256(
                        _canonical(
                            {
                                key: item
                                for key, item in report.items()
                                if key != "auditSha256"
                            }
                        )
                    )
                    _write_json(report_path, report)

                    with self.assertRaisesRegex(
                        ValueError,
                        "raw probe evidence is incomplete",
                    ):
                        validate_quality_report(root, inventory)

    def test_legacy_quality_keeps_the_immutable_repeat_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root, v4=False)

            inventory = validate_source(root)
            quality = validate_quality_report(root, inventory)
            report = json.loads(quality.path.read_text(encoding="utf-8"))

        self.assertEqual(
            report["gates"]["rawProbes"]["thresholds"],
            publish_module.LEGACY_RAW_THRESHOLDS,
        )

    def test_legacy_quality_rejects_nonzero_opaque_repeat_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root, v4=False)
            inventory = validate_source(root)
            report_path = root / "quality-audit" / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["gates"]["rawProbes"]["probes"][0]["releasedRepeat"][0][
                "opaqueDifferingPixels"
            ] = 1
            report["auditSha256"] = _sha256(
                _canonical(
                    {
                        key: value
                        for key, value in report.items()
                        if key != "auditSha256"
                    }
                )
            )
            _write_json(report_path, report)

            with self.assertRaisesRegex(
                ValueError,
                "raw probe evidence is incomplete",
            ):
                validate_quality_report(root, inventory)

    def test_v4_publication_declares_baked_presentation_and_legacy_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v4_root = root / "v4"
            legacy_root = root / "legacy"
            _fixture(v4_root)
            _fixture(legacy_root, v4=False)

            v4 = build_publish_metadata(v4_root, validate_source(v4_root))
            legacy = build_publish_metadata(
                legacy_root,
                validate_source(legacy_root),
            )

        self.assertEqual(
            v4.map_assets["tilePyramids"][0]["presentation"],
            {
                "gradeVersion": "mim-opaque-v4",
                "alphaMode": "binary-nonzero",
                "colorGrade": "baked",
            },
        )
        self.assertNotIn("presentation", legacy.map_assets["tilePyramids"][0])

    def test_v4_quality_rejects_intermediate_alpha_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            inventory = validate_source(root)
            report_path = root / "quality-audit" / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["gates"]["inventory"]["alphaIntermediatePixels"] = 1
            report["auditSha256"] = _sha256(
                _canonical(
                    {
                        key: value
                        for key, value in report.items()
                        if key != "auditSha256"
                    }
                )
            )
            _write_json(report_path, report)

            with self.assertRaisesRegex(
                ValueError,
                "inventory.alphaIntermediatePixels",
            ):
                validate_quality_report(root, inventory)

    def test_v4_quality_rejects_stale_repeat_threshold_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            inventory = validate_source(root)
            report_path = root / "quality-audit" / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            thresholds = report["gates"]["rawProbes"]["thresholds"]
            thresholds.pop("repeatMaximumOpaqueDeltaMax")
            thresholds.pop("repeatLargestHardComponentPixelsMax")
            thresholds["repeatOpaqueDifferingPixelsMax"] = 0
            report["auditSha256"] = _sha256(
                _canonical(
                    {
                        key: value
                        for key, value in report.items()
                        if key != "auditSha256"
                    }
                )
            )
            _write_json(report_path, report)

            with self.assertRaisesRegex(ValueError, "rawProbes.thresholds"):
                validate_quality_report(root, inventory)

    def test_validate_source_does_not_require_quality_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = _fixture(root, with_quality=False)

            actual = validate_source(root)

            self.assertEqual(actual.inventory_sha256, expected["inventorySha256"])
            with self.assertRaisesRegex(FileNotFoundError, "Quality audit report"):
                validate_quality_report(root, actual)
            with self.assertRaisesRegex(FileNotFoundError, "Quality audit report"):
                build_publish_metadata(root, actual)

    def test_source_rejects_uninventoried_files_and_hash_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            (root / "tiles" / "unexpected.webp").write_bytes(b"extra")
            with self.assertRaisesRegex(ValueError, "does not match inventory"):
                validate_source(root)
            (root / "tiles" / "unexpected.webp").unlink()
            corrupt = root / "tiles" / "7" / "0" / "0.webp"
            original = corrupt.read_bytes()
            corrupt.write_bytes(bytes([original[0] ^ 0xFF]) + original[1:])
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                validate_source(root)

    def test_quality_report_must_pass_and_match_logical_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            inventory = validate_source(root)
            report_path = root / "quality-audit" / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["passes"] = False
            _write_json(report_path, report)

            with self.assertRaisesRegex(ValueError, "not passing"):
                validate_quality_report(root, inventory)

            report["passes"] = True
            report["scope"] = {**FIXTURE_QUALITY_SCOPE, "tiles": 999}
            _write_json(report_path, report)
            with self.assertRaisesRegex(ValueError, "pinned full scope"):
                validate_quality_report(root, inventory)

            report["auditSha256"] = _sha256(
                _canonical(
                    {key: value for key, value in report.items() if key != "auditSha256"}
                )
            )
            report["scope"] = dict(FIXTURE_QUALITY_SCOPE)
            report["identity"]["rendererFingerprint"] = "9" * 64
            report["auditSha256"] = _sha256(
                _canonical(
                    {key: value for key, value in report.items() if key != "auditSha256"}
                )
            )
            _write_json(report_path, report)
            with self.assertRaisesRegex(ValueError, "rendererFingerprint"):
                validate_quality_report(root, inventory)

    def test_quality_report_rejects_a_rehashed_incomplete_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            inventory = validate_source(root)
            report_path = root / "quality-audit" / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["gates"]["inventory"] = {"passes": True}
            report["auditSha256"] = _sha256(
                _canonical(
                    {key: value for key, value in report.items() if key != "auditSha256"}
                )
            )
            _write_json(report_path, report)

            with self.assertRaisesRegex(ValueError, "inventory.tileCount"):
                validate_quality_report(root, inventory)

    def test_quality_report_binds_exact_raw_renderer_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            inventory = validate_source(root)
            report_path = root / "quality-audit" / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["gates"]["rawProbes"]["rendererProvenance"][
                "candidatePayloadSha256"
            ] = "f" * 64
            report["auditSha256"] = _sha256(
                _canonical(
                    {key: value for key, value in report.items() if key != "auditSha256"}
                )
            )
            _write_json(report_path, report)

            with self.assertRaisesRegex(ValueError, "exact raw renderer provenance"):
                validate_quality_report(root, inventory)

    def test_quality_report_recomputes_rematerialized_renderer_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            inventory = validate_source(root)
            report_path = root / "quality-audit" / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            artifact = report["artifacts"]["rawRendererProvenance"]
            provenance_path = root / "quality-audit" / artifact["path"]
            candidate = json.loads(provenance_path.read_text(encoding="utf-8"))
            candidate["image"]["id"] = "sha256:" + "e" * 64
            candidate["image"]["repoDigests"] = ["fixture@sha256:" + "e" * 64]
            candidate["provenanceFingerprint"] = "f" * 64
            candidate_bytes = _canonical(candidate) + b"\n"
            provenance_path.write_bytes(candidate_bytes)
            artifact["sha256"] = _sha256(candidate_bytes)
            artifact["bytes"] = len(candidate_bytes)
            renderer = report["gates"]["rawProbes"]["rendererProvenance"]
            renderer["mode"] = "manifest-rematerialization"
            renderer["candidateProvenanceFingerprint"] = candidate[
                "provenanceFingerprint"
            ]
            renderer["candidateImageId"] = candidate["image"]["id"]
            renderer["candidatePayloadSha256"] = _sha256(_canonical(candidate))
            report["auditSha256"] = _sha256(
                _canonical(
                    {key: value for key, value in report.items() if key != "auditSha256"}
                )
            )
            _write_json(report_path, report)

            with self.assertRaisesRegex(ValueError, "fingerprint does not recompute"):
                validate_quality_report(root, inventory)

    def test_source_rejects_noncanonical_plan_and_stale_provenance_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            plan_path = root / "plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["targetCount"] = 999
            _write_json(plan_path, plan)
            with self.assertRaisesRegex(ValueError, "does not recompute exactly"):
                validate_source(root)

            _fixture(root)
            provenance_path = root / "provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["auditTamper"] = True
            _write_json(provenance_path, provenance)
            inventory = validate_source(root)
            with self.assertRaisesRegex(
                ValueError,
                "provenanceFileSha256|exact raw renderer provenance",
            ):
                validate_quality_report(root, inventory)

    def test_source_rejects_incomplete_zoom_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            inventory_path = root / "inventory.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            removed = inventory["tiles"].pop(6)
            (root / removed["path"]).unlink()
            inventory["tileCount"] = len(inventory["tiles"])
            inventory["totalBytes"] = sum(tile["bytes"] for tile in inventory["tiles"])
            core = {
                key: value for key, value in inventory.items() if key != "inventorySha256"
            }
            inventory["inventorySha256"] = _sha256(_canonical(core))
            _write_json(inventory_path, inventory)

            with self.assertRaisesRegex(ValueError, "zoom topology count mismatch"):
                validate_source(root)

    def test_source_rejects_an_alternative_self_consistent_plan_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture(root)
            alternative = plan_report((FIXTURE_CELLS[0],))
            _write_json(root / "plan.json", alternative)
            inventory_path = root / "inventory.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["planFingerprint"] = alternative["planFingerprint"]
            core = {
                key: value for key, value in inventory.items() if key != "inventorySha256"
            }
            inventory["inventorySha256"] = _sha256(_canonical(core))
            _write_json(inventory_path, inventory)

            with mock.patch.object(
                publish_module,
                "EXPECTED_PLAN_FINGERPRINT",
                FIXTURE_PLAN["planFingerprint"],
            ):
                with self.assertRaisesRegex(ValueError, "pinned Poison plan"):
                    validate_source(root)


@_fixture_scope_patches()
@mock.patch.object(
    publish_module,
    "_validated_stabilization",
    new=_fixture_validated_stabilization,
)
class PrepareTests(unittest.TestCase):
    def test_immutable_directory_publication_is_atomic_and_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging"
            destination = root / "destination"
            staging.mkdir()
            (staging / "nested").mkdir()
            (staging / "payload").write_bytes(b"complete")
            (staging / "nested" / "evidence").write_bytes(b"complete")

            _publish_staged_directory_no_replace(staging, destination)

            self.assertFalse(staging.exists())
            self.assertEqual((destination / "payload").read_bytes(), b"complete")
            self.assertEqual(
                (destination / "nested" / "evidence").read_bytes(), b"complete"
            )

    def test_immutable_directory_publication_never_replaces_existing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging"
            destination = root / "destination"
            staging.mkdir()
            destination.mkdir()
            (staging / "payload").write_bytes(b"preserved")

            with self.assertRaisesRegex(FileExistsError, "appeared during publication"):
                _publish_staged_directory_no_replace(staging, destination)

            self.assertEqual(list(destination.iterdir()), [])
            self.assertEqual((staging / "payload").read_bytes(), b"preserved")

            destination.rmdir()
            destination.write_bytes(b"existing")
            with self.assertRaisesRegex(FileExistsError, "appeared during publication"):
                _publish_staged_directory_no_replace(staging, destination)
            self.assertEqual(destination.read_bytes(), b"existing")
            self.assertEqual((staging / "payload").read_bytes(), b"preserved")

            destination.unlink()
            outside = root / "outside"
            outside.mkdir()
            destination.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(FileExistsError, "appeared during publication"):
                _publish_staged_directory_no_replace(staging, destination)
            self.assertTrue(destination.is_symlink())
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual((staging / "payload").read_bytes(), b"preserved")

    def test_immutable_directory_publication_fails_closed_when_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging"
            destination = root / "destination"
            staging.mkdir()
            (staging / "payload").write_bytes(b"preserved")

            with mock.patch.object(publish_module.sys, "platform", "unsupported"):
                with self.assertRaisesRegex(RuntimeError, "unsupported"):
                    _publish_staged_directory_no_replace(staging, destination)

            self.assertFalse(destination.exists())
            self.assertEqual((staging / "payload").read_bytes(), b"preserved")

    def test_metadata_writer_publishes_complete_versioned_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            _fixture(source)
            inventory = validate_source(source)
            metadata = build_publish_metadata(source, inventory)
            metadata_root = root / "metadata"

            write_publish_metadata(metadata_root, metadata)

            self.assertFalse((metadata_root / "map-assets.json").exists())
            version_root = metadata_root / inventory.inventory_sha256
            self.assertEqual(
                (version_root / "map-assets.json").read_bytes(),
                publish_module._json_file_bytes(metadata.map_assets),
            )
            self.assertTrue((version_root / "tile-coverage.json").is_file())

    def test_worktree_tile_target_must_be_git_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(("git", "init", "--quiet", str(root)), check=True)
            (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")

            _require_ignored_worktree_target(root / "ignored" / "tiles", repo_root=root)
            with self.assertRaisesRegex(ValueError, "must be Git-ignored"):
                _require_ignored_worktree_target(root / "tracked" / "tiles", repo_root=root)

    def test_prepare_copies_validates_and_publishes_metadata_last(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            inventory = _fixture(source)
            public_root = root / "public" / "datasets" / "generated"
            metadata_root = root / "public" / "datasets" / "metadata" / DATASET_ID

            first = prepare_dataset(
                source_root=source,
                public_root=public_root,
                metadata_root=metadata_root,
                copy_mode="copy",
            )
            second = prepare_dataset(
                source_root=source,
                public_root=public_root,
                metadata_root=metadata_root,
                copy_mode="copy",
            )

            expected_target = public_root / DATASET_ID / str(inventory["inventorySha256"])
            self.assertEqual(first.target_root, expected_target.resolve())
            self.assertTrue(first.created)
            self.assertEqual(first.copy_method, "copy")
            self.assertFalse(second.created)
            self.assertEqual(second.copy_method, "existing")
            for tile in inventory["tiles"]:  # type: ignore[index]
                relative = Path(str(tile["path"]))  # type: ignore[index]
                self.assertEqual(
                    (expected_target / relative).read_bytes(),
                    (source / relative).read_bytes(),
                )
            version_root = metadata_root / str(inventory["inventorySha256"])
            map_assets_bytes = (version_root / "map-assets.json").read_bytes()
            map_assets = json.loads(map_assets_bytes)
            self.assertFalse((metadata_root / "map-assets.json").exists())
            coverage_bytes = (version_root / "tile-coverage.json").read_bytes()
            quality_bytes = (version_root / PUBLISHED_QUALITY_REPORT_NAME).read_bytes()
            pyramid = map_assets["tilePyramids"][0]
            self.assertEqual(map_assets["rasters"], [])
            self.assertIn(str(inventory["inventorySha256"]), pyramid["urlTemplate"])
            self.assertEqual(pyramid["coverage"]["sha256"], _sha256(coverage_bytes))
            self.assertEqual(pyramid["coverage"]["bytes"], len(coverage_bytes))
            self.assertEqual(pyramid["qualityReport"]["sha256"], _sha256(quality_bytes))
            self.assertEqual(pyramid["qualityReport"]["bytes"], len(quality_bytes))
            receipt_bytes = (source / "seam-stabilization.json").read_bytes()
            self.assertEqual(pyramid["derivation"]["receipt"]["sha256"], _sha256(receipt_bytes))
            self.assertEqual(
                (version_root / "seam-stabilization.json").read_bytes(),
                receipt_bytes,
            )
            self.assertTrue(
                (version_root / "seam-stabilization" / "source-inventory.json").is_file()
            )
            self.assertTrue(
                (version_root / "seam-stabilization" / "tile-transforms.ndjson").is_file()
            )
            self.assertEqual(
                quality_bytes,
                (source / "quality-audit" / "report.json").read_bytes(),
            )
            published_quality = json.loads(quality_bytes)
            for artifact in published_quality["artifacts"].values():
                relative = Path(artifact["path"])
                self.assertEqual(
                    (version_root / relative).read_bytes(),
                    (source / "quality-audit" / relative).read_bytes(),
                )

    def test_prepare_revalidates_tiles_immediately_before_metadata_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            inventory = _fixture(source)
            inventory_sha256 = str(inventory["inventorySha256"])
            public_root = root / "generated"
            metadata_root = root / "metadata"
            target_tile = (
                public_root
                / DATASET_ID
                / inventory_sha256
                / "tiles"
                / "7"
                / "0"
                / "0.webp"
            )
            version_root = metadata_root / inventory_sha256
            validate_metadata_tree = publish_module._validate_immutable_metadata_tree

            def validate_metadata_then_corrupt_tile(
                staged_root: Path,
                artifacts: dict[Path, bytes],
            ) -> None:
                validate_metadata_tree(staged_root, artifacts)
                target_tile.write_bytes(b"corrupt-after-metadata-staging")

            with mock.patch.object(
                publish_module,
                "_validate_immutable_metadata_tree",
                side_effect=validate_metadata_then_corrupt_tile,
            ):
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    prepare_dataset(
                        source_root=source,
                        public_root=public_root,
                        metadata_root=metadata_root,
                        copy_mode="copy",
                    )

            self.assertFalse(version_root.exists())
            self.assertFalse((version_root / "map-assets.json").exists())

    def test_prepare_rejects_legacy_incomplete_metadata_tree_without_upgrading_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            inventory = _fixture(source)
            public_root = root / "generated"
            metadata_root = root / "metadata"
            validated = validate_source(source)
            metadata = build_publish_metadata(source, validated)
            write_publish_metadata(metadata_root, metadata)
            version_root = metadata_root / str(inventory["inventorySha256"])
            (version_root / "map-assets.json").unlink()

            with self.assertRaisesRegex(ValueError, "incomplete or divergent"):
                prepare_dataset(
                    source_root=source,
                    public_root=public_root,
                    metadata_root=metadata_root,
                    copy_mode="copy",
                )

            self.assertFalse((metadata_root / "map-assets.json").exists())
            self.assertFalse((version_root / "map-assets.json").exists())
            self.assertTrue((version_root / "tile-coverage.json").is_file())

    def test_prepare_never_overwrites_divergent_immutable_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            inventory = _fixture(source)
            public_root = root / "generated"
            metadata_root = root / "metadata"
            prepare_dataset(
                source_root=source,
                public_root=public_root,
                metadata_root=metadata_root,
                copy_mode="copy",
            )
            target = (
                public_root
                / DATASET_ID
                / str(inventory["inventorySha256"])
                / "tiles"
                / "7"
                / "0"
                / "0.webp"
            )
            target.write_bytes(b"divergent")

            with self.assertRaisesRegex(ValueError, "mismatch"):
                prepare_dataset(
                    source_root=source,
                    public_root=public_root,
                    metadata_root=metadata_root,
                    copy_mode="copy",
                )
            self.assertEqual(target.read_bytes(), b"divergent")

    def test_prepare_rejects_symlinked_metadata_version_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            inventory = _fixture(source)
            metadata_root = root / "metadata"
            metadata_root.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (metadata_root / str(inventory["inventorySha256"])).symlink_to(
                outside,
                target_is_directory=True,
            )

            with self.assertRaisesRegex(ValueError, "version root cannot be a symlink"):
                prepare_dataset(
                    source_root=source,
                    public_root=root / "generated",
                    metadata_root=metadata_root,
                    copy_mode="copy",
                )
            self.assertEqual(list(outside.iterdir()), [])

    def test_prepare_rejects_nested_symlink_in_existing_metadata_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            inventory = _fixture(source)
            metadata_root = root / "metadata"
            version_root = metadata_root / str(inventory["inventorySha256"])
            version_root.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            (version_root / "seam-stabilization").symlink_to(
                outside,
                target_is_directory=True,
            )

            with self.assertRaisesRegex(ValueError, "contains a symlink"):
                prepare_dataset(
                    source_root=source,
                    public_root=root / "generated",
                    metadata_root=metadata_root,
                    copy_mode="copy",
                )
            self.assertEqual(list(outside.iterdir()), [])

    def test_prepare_rejects_metadata_overlap_and_dataset_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            inventory = _fixture(source)
            public_root = root / "generated"

            with self.assertRaisesRegex(ValueError, "Metadata root cannot overlap"):
                prepare_dataset(
                    source_root=source,
                    public_root=public_root,
                    metadata_root=source,
                    copy_mode="copy",
                )

            target = public_root / DATASET_ID / str(inventory["inventorySha256"])
            with self.assertRaisesRegex(ValueError, "Metadata root cannot overlap"):
                prepare_dataset(
                    source_root=source,
                    public_root=public_root,
                    metadata_root=target / "tiles",
                    copy_mode="copy",
                )

            public_root.mkdir(parents=True, exist_ok=True)
            (public_root / DATASET_ID).symlink_to(source, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "overlap|symlink"):
                prepare_dataset(
                    source_root=source,
                    public_root=public_root,
                    metadata_root=root / "metadata",
                    copy_mode="copy",
                )


class PublishedPackageTests(unittest.TestCase):
    def test_committed_manifest_pins_versioned_map_assets_payload(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        manifest_path = (
            repo_root
            / "apps/web/public/datasets/manifests"
            / f"{DATASET_ID}.json"
        )
        manifest = json.loads(manifest_path.read_bytes())
        tile_reference = manifest["artifacts"]["tiles"]
        match = re.fullmatch(
            rf"/datasets/metadata/{re.escape(DATASET_ID)}/([a-f0-9]{{64}})/map-assets\.json",
            tile_reference["manifestUrl"],
        )
        self.assertIsNotNone(match)
        assert match is not None
        inventory_sha256 = match.group(1)

        map_assets_path = (
            repo_root
            / "apps/web/public"
            / tile_reference["manifestUrl"].removeprefix("/")
        )
        payload = map_assets_path.read_bytes()
        self.assertEqual(tile_reference["sha256"], _sha256(payload))
        map_assets = json.loads(payload)
        self.assertEqual(map_assets["datasetId"], DATASET_ID)
        self.assertEqual(
            map_assets["tilePyramids"][0]["integrity"]["inventorySha256"],
            inventory_sha256,
        )


if __name__ == "__main__":
    unittest.main()
