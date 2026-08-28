from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools.openmw_renderer import audit as audit_module
from tools.openmw_renderer.audit import (
    AUDIT_VERSION,
    _decode_rgba,
    _canonical_raw_completion,
    _expected_target,
    _load_reusable_report,
    _read_ndjson,
    _raw_probe_cache_name,
    _raw_probe_provenance_compatibility,
    _require_final_raw_probe_provenance,
    _repeat_result,
    _select_raw_probe_records,
    _stabilization_rgba_gate,
    _validate_checkpoint_identity,
    _visual_difference,
    build_adjacencies,
    main as audit_main,
    report_with_hash,
    run_full_audit,
    seam_metrics,
)
from tools.land_renderer.terrain import RgbaImage, encode_webp
from tools.openmw_renderer.production import (
    ProductionProvenance,
    TileKey,
    native_tile_for_cell,
)


def _line(color: tuple[int, int, int, int], pixels: int = 8) -> bytes:
    return bytes(color) * pixels


class FinalSeamMetricTests(unittest.TestCase):
    def test_continuous_boundary_has_no_excess(self) -> None:
        line = _line((40, 80, 120, 255))

        result = seam_metrics(line, line, line, line)

        self.assertEqual(result["meanExcessChannelDelta"], 0)
        self.assertEqual(result["hardPixelFraction"], 0)
        self.assertFalse(result["flagged"])

    def test_discontinuous_boundary_is_flagged_after_local_baseline(self) -> None:
        dark = _line((0, 0, 0, 255))
        bright = _line((255, 255, 255, 255))

        result = seam_metrics(dark, dark, bright, bright)

        self.assertGreater(result["meanExcessChannelDelta"], 8)
        self.assertEqual(result["hardPixelFraction"], 1)
        self.assertTrue(result["flagged"])

    def test_transparent_rgb_is_premultiplied_before_metric(self) -> None:
        transparent_red = _line((255, 0, 0, 0))
        transparent_blue = _line((0, 0, 255, 0))

        result = seam_metrics(
            transparent_red,
            transparent_red,
            transparent_blue,
            transparent_blue,
        )

        self.assertFalse(result["flagged"])

    def test_one_sided_alpha_discontinuity_is_not_skipped(self) -> None:
        transparent = _line((255, 0, 0, 0))
        opaque = _line((255, 255, 255, 255))

        result = seam_metrics(transparent, transparent, opaque, opaque)

        self.assertEqual(result["comparablePixels"], 8)
        self.assertEqual(result["unmatchedAlphaPixels"], 8)
        self.assertTrue(result["flagged"])


class RawVisualMetricTests(unittest.TestCase):
    def test_raw_completion_evidence_is_identical_for_clean_and_resumed_runs(self) -> None:
        clean = _canonical_raw_completion(target_cells=7, rendered=7, skipped=0)
        resumed = _canonical_raw_completion(target_cells=7, rendered=0, skipped=7)

        self.assertEqual(clean, resumed)

    def test_audit_root_cannot_overlap_protected_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            game = root / "game"
            release.mkdir()
            game.mkdir()

            for unsafe in (release / "tiles", game / "audit", root):
                with self.subTest(unsafe=unsafe):
                    with self.assertRaisesRegex(ValueError, "overlap"):
                        run_full_audit(
                            repo_root=root,
                            source_root=release,
                            game_source_root=game,
                            audit_root=unsafe,
                            workers=1,
                            render_workers=1,
                            probe_count=2,
                            skip_raw_probes=True,
                            image="fixture",
                            magick="magick",
                            timeout_seconds=1,
                        )

            symlink = root / "audit-link"
            symlink.symlink_to(release / "quality-audit", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "cannot be a symlink"):
                audit_main(
                    [
                        "full",
                        "--output",
                        str(release),
                        "--source-root",
                        str(game),
                        "--audit-root",
                        str(symlink),
                        "--skip-raw-probes",
                    ]
                )

            with mock.patch(
                "tools.openmw_renderer.audit.validate_source",
                side_effect=RuntimeError("safe root reached validation"),
            ):
                with self.assertRaisesRegex(RuntimeError, "safe root reached"):
                    run_full_audit(
                        repo_root=root,
                        source_root=release,
                        game_source_root=game,
                        audit_root=release / "quality-audit",
                        workers=1,
                        render_workers=1,
                        probe_count=2,
                        skip_raw_probes=True,
                        image="fixture",
                        magick="magick",
                        timeout_seconds=1,
                    )

    def test_stabilization_after_rgba_hashes_are_verified_against_decoded_tiles(self) -> None:
        transforms = [
            {"path": "tiles/7/1/2.webp", "afterRgbaSha256": "a" * 64},
            {"path": "tiles/7/1/3.webp", "afterRgbaSha256": "b" * 64},
        ]
        decoded = [
            {"path": "tiles/7/1/2.webp", "rgbaSha256": "a" * 64},
            {"path": "tiles/7/1/3.webp", "rgbaSha256": "c" * 64},
        ]

        result = _stabilization_rgba_gate(
            transforms,
            decoded,
            expected_touched_tiles=2,
        )

        self.assertFalse(result["passes"])
        self.assertEqual(result["verifiedAfterRgbaTiles"], 1)
        self.assertEqual(result["afterRgbaMismatches"], 1)

    def test_raw_probe_cache_isolated_by_candidate_provenance(self) -> None:
        selection = "a" * 64

        first = _raw_probe_cache_name(selection, "b" * 64)
        second = _raw_probe_cache_name(selection, "c" * 64)

        self.assertNotEqual(first, second)
        self.assertEqual(first, f"raw-probes-{'a' * 16}-{'b' * 16}")

    def test_manifest_rematerialization_requires_the_exact_renderer_contract(self) -> None:
        released = {
            "provenanceFingerprint": "a" * 64,
            "profileFingerprint": "b" * 64,
            "assetAudit": {"tree": "c" * 64},
            "image": {
                "requested": "renderer:production",
                "id": "sha256:" + "d" * 64,
                "repoDigests": ["renderer@sha256:" + "d" * 64],
                "os": "linux",
                "architecture": "amd64",
                "labels": {"source": "e" * 64},
            },
        }
        candidate = json.loads(json.dumps(released))
        candidate["provenanceFingerprint"] = "f" * 64
        candidate["image"]["id"] = "sha256:" + "0" * 64
        candidate["image"]["repoDigests"] = ["renderer@sha256:" + "0" * 64]
        candidate_payload_sha256 = hashlib.sha256(
            json.dumps(
                candidate,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        compatible = _raw_probe_provenance_compatibility(released, candidate)
        candidate["image"]["labels"]["source"] = "1" * 64
        incompatible = _raw_probe_provenance_compatibility(released, candidate)

        self.assertTrue(compatible["passes"])
        self.assertEqual(compatible["mode"], "manifest-rematerialization")
        self.assertEqual(compatible["candidatePayloadSha256"], candidate_payload_sha256)
        self.assertFalse(incompatible["passes"])

    def test_final_raw_provenance_rejects_game_asset_drift(self) -> None:
        candidate = ProductionProvenance(
            fingerprint="a" * 64,
            payload={"image": {"id": "sha256:" + "b" * 64}, "assetAudit": {}},
        )
        payload_sha256 = hashlib.sha256(
            json.dumps(
                candidate.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        report = {
            "gates": {
                "rawProbes": {
                    "rendererProvenance": {
                        "candidateProvenanceFingerprint": candidate.fingerprint,
                        "candidateImageId": candidate.payload["image"]["id"],
                        "candidatePayloadSha256": payload_sha256,
                    }
                }
            }
        }

        _require_final_raw_probe_provenance(report, candidate)
        candidate.payload["assetAudit"] = {"changed": True}
        with self.assertRaisesRegex(RuntimeError, "changed during audit"):
            _require_final_raw_probe_provenance(report, candidate)

    def test_hidden_transparent_rgb_is_ignored(self) -> None:
        red = RgbaImage.solid(2, 2, (255, 0, 0, 0))
        blue = RgbaImage.solid(2, 2, (0, 0, 255, 0))

        result = _visual_difference(red, blue, hard_pixel_delta=8)

        self.assertEqual(result["differingPixels"], 0)
        self.assertEqual(result["meanAbsoluteChannelDelta"], 0)

    def test_repeat_rejects_any_opaque_static_change(self) -> None:
        left = RgbaImage.solid(2, 2, (10, 20, 30, 255))
        right = RgbaImage.solid(2, 2, (11, 20, 30, 255))

        result = _repeat_result(left, right)

        self.assertEqual(result["opaqueDifferingPixels"], 4)
        self.assertFalse(result["passes"])

    def test_repeat_masks_only_the_receipt_covered_outer_pixel(self) -> None:
        base = bytearray(RgbaImage.solid(4, 4, (10, 20, 30, 255)).pixels)
        border = bytearray(base)
        border[0:4] = bytes((99, 20, 30, 255))
        inner = bytearray(base)
        inner[4:8] = bytes((99, 20, 30, 255))

        covered = _repeat_result(
            RgbaImage(4, 4, bytes(base)),
            RgbaImage(4, 4, bytes(border)),
            ignored_border_sides=("west",),
        )
        uncovered = _repeat_result(
            RgbaImage(4, 4, bytes(base)),
            RgbaImage(4, 4, bytes(inner)),
            ignored_border_sides=("west",),
        )

        self.assertTrue(covered["passes"])
        self.assertEqual(covered["ignoredPixels"], 4)
        self.assertFalse(uncovered["passes"])

    def test_hard_component_distinguishes_cluster_from_isolated_spikes(self) -> None:
        base = RgbaImage.solid(20, 20, (0, 0, 0, 0))
        clustered = bytearray(base.pixels)
        scattered = bytearray(base.pixels)
        for index in range(17):
            clustered[index * 4 + 3] = 64
            x = (index % 5) * 4
            y = (index // 5) * 4
            scattered[(y * 20 + x) * 4 + 3] = 64

        clustered_result = _visual_difference(
            base, RgbaImage(20, 20, bytes(clustered)), hard_pixel_delta=8
        )
        scattered_result = _visual_difference(
            base, RgbaImage(20, 20, bytes(scattered)), hard_pixel_delta=8
        )

        self.assertEqual(clustered_result["largestHardComponentPixels"], 17)
        self.assertEqual(scattered_result["largestHardComponentPixels"], 1)
        self.assertEqual(scattered_result["maximumOpaqueChannelDelta"], 0)

    def test_decode_rejects_same_byte_count_with_wrong_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wide.webp"
            try:
                path.write_bytes(
                    encode_webp(
                        RgbaImage.solid(1024, 256, (1, 2, 3, 255)),
                        executable="magick",
                    )
                )
            except RuntimeError as error:
                if "executable not found" in str(error):
                    self.skipTest(str(error))
                raise

            with self.assertRaisesRegex(ValueError, "dimensions mismatch"):
                _decode_rgba(path, pixels=512, magick="magick")

    def test_selection_keeps_pinned_alpha_control_and_both_directions(self) -> None:
        records = []
        for index in range(20):
            records.append(
                {
                    "id": (
                        "7/5/14:east:7/6/14"
                        if index == 0
                        else "7/34/80:north:7/34/79"
                        if index == 1
                        else f"7/{index}/{index}:{'east' if index % 2 == 0 else 'north'}:"
                        f"7/{index + 1}/{index}"
                    ),
                    "direction": "east" if index % 2 == 0 else "north",
                    "meanExcessChannelDelta": float(index),
                    "hardPixelFraction": float(20 - index),
                    "maximumPixelExcess": index * 2,
                    "unmatchedAlphaPixels": index * 3,
                }
            )

        selected = _select_raw_probe_records(records, 8)

        self.assertIn("7/5/14:east:7/6/14", {record["id"] for record in selected})
        self.assertIn("7/34/80:north:7/34/79", {record["id"] for record in selected})
        self.assertEqual(
            [record["direction"] for record in selected].count("east"),
            4,
        )
        self.assertEqual(
            [record["direction"] for record in selected].count("north"),
            4,
        )


class AuditTopologyTests(unittest.TestCase):
    def test_builds_each_east_and_north_pair_once(self) -> None:
        tiles = {
            TileKey(7, 0, 0),
            TileKey(7, 1, 0),
            TileKey(7, 0, 1),
            TileKey(7, 1, 1),
        }

        adjacencies = build_adjacencies(tiles)

        self.assertEqual(len(adjacencies), 4)
        self.assertEqual(
            {(item.direction, item.first.x, item.first.y) for item in adjacencies},
            {("east", 0, 0), ("east", 0, 1), ("north", 0, 1), ("north", 1, 1)},
        )

    def test_expected_runtime_marker_round_trips_to_native_tile(self) -> None:
        cell = (-2, -41)

        marker = _expected_target(cell)

        self.assertEqual(marker["center_x"], -12_288)
        self.assertEqual(marker["center_y"], -331_776)
        self.assertEqual(marker["pixels"], 544)
        tile = native_tile_for_cell(cell)
        self.assertEqual((marker["z"], marker["x"], marker["y"]), (tile.z, tile.x, tile.y))

    def test_migration_checkpoint_identity_is_exact(self) -> None:
        checkpoint = {
            "schemaVersion": 1,
            "datasetId": "poison-song-26.08",
            "snapshotId": "tr:poison-song-26.08:6964517551e0fcb0",
            "provenanceFingerprint": "a" * 64,
            "planFingerprint": "b" * 64,
            "targetCount": 3984,
        }

        _validate_checkpoint_identity(
            checkpoint,
            provenance_fingerprint="a" * 64,
            plan_fingerprint="b" * 64,
            target_count=3984,
            label="Migration checkpoint backup",
        )
        checkpoint["provenanceFingerprint"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "provenanceFingerprint mismatch"):
            _validate_checkpoint_identity(
                checkpoint,
                provenance_fingerprint="a" * 64,
                plan_fingerprint="b" * 64,
                target_count=3984,
                label="Migration checkpoint backup",
            )


class AuditReportTests(unittest.TestCase):
    def test_ndjson_reader_requires_objects_and_rejects_empty_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.ndjson"
            path.write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")
            self.assertEqual(_read_ndjson(path), [{"id": 1}, {"id": 2}])

            path.write_text('{"id":1}\n\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 2 is empty"):
                _read_ndjson(path)

    def test_full_audit_reads_snapshot_and_publishes_only_after_revalidation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            game = root / "game"
            release.mkdir()
            game.mkdir()
            receipt_bytes = b'{"fixture":true}\n'
            (release / "seam-stabilization.json").write_bytes(receipt_bytes)
            inventory = SimpleNamespace(
                inventory_sha256="1" * 64,
                inventory_file_sha256="2" * 64,
                provenance_file_sha256="3" * 64,
                plan_file_sha256="4" * 64,
                provenance_fingerprint="5" * 64,
                plan_fingerprint="6" * 64,
                tile_count=5464,
                total_bytes=123,
                production_source_fingerprint="7" * 64,
                provenance={"magickVersion": "fixture-magick"},
            )
            toolchain = {"fixture": "pinned"}
            receipt = {"receiptSha256": "8" * 64}
            implementation = "9" * 64
            report = {
                "identity": {"auditImplementationSha256": implementation},
                "auditSha256": "a" * 64,
                "passes": True,
            }
            snapshot_paths: list[Path] = []

            def create_snapshot(_source: Path, snapshot: Path) -> None:
                snapshot_paths.append(snapshot)
                snapshot.mkdir()
                (snapshot / "seam-stabilization.json").write_bytes(receipt_bytes)

            with (
                mock.patch.object(
                    audit_module,
                    "validate_source",
                    return_value=inventory,
                ) as validate,
                mock.patch.object(
                    audit_module,
                    "_resolve_stabilization_toolchain",
                    return_value=("/pinned/magick", toolchain),
                ),
                mock.patch.object(
                    audit_module,
                    "validate_stabilization_receipt",
                    return_value=receipt,
                ),
                mock.patch.object(
                    audit_module,
                    "_audit_implementation_sha256",
                    return_value=implementation,
                ),
                mock.patch.object(
                    audit_module,
                    "_create_audit_snapshot",
                    side_effect=create_snapshot,
                ),
                mock.patch.object(
                    audit_module,
                    "_run_full_audit_from_snapshot",
                    return_value=report,
                ) as run_snapshot,
            ):
                actual = run_full_audit(
                    repo_root=root,
                    source_root=release,
                    game_source_root=game,
                    audit_root=release / "quality-audit",
                    workers=1,
                    render_workers=1,
                    probe_count=2,
                    skip_raw_probes=True,
                    image="fixture",
                    magick="magick",
                    timeout_seconds=1,
                )

            self.assertEqual(actual, report)
            self.assertEqual(validate.call_count, 4)
            self.assertEqual(len(snapshot_paths), 1)
            self.assertNotEqual(snapshot_paths[0], release)
            self.assertFalse(snapshot_paths[0].exists())
            self.assertEqual(
                run_snapshot.call_args.kwargs["source_root"], snapshot_paths[0]
            )
            self.assertEqual(
                json.loads((release / "quality-audit" / "report.json").read_bytes()),
                report,
            )

    def test_logical_hash_is_canonical_and_deterministic(self) -> None:
        core = {
            "schemaVersion": 1,
            "datasetId": "poison-song-26.08",
            "snapshotId": "tr:poison-song-26.08:fixture",
            "auditVersion": AUDIT_VERSION,
            "identity": {"inventorySha256": "a" * 64},
            "scope": {"tiles": 2},
            "gates": {"inventory": {"passes": True}},
            "passes": True,
        }

        first = report_with_hash(core)
        second = report_with_hash(dict(reversed(list(core.items()))))
        expected = hashlib.sha256(
            json.dumps(
                core,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(first, second)
        self.assertEqual(first["auditSha256"], expected)

    def test_reuse_rejects_self_hashed_incomplete_report(self) -> None:
        identity = {"inventorySha256": "a" * 64}
        core = {
            "auditVersion": AUDIT_VERSION,
            "identity": identity,
            "scope": {"tiles": 1},
            "gates": {
                "pyramidDerivation": {"passes": True, "parentsChecked": 0},
                "runtimeResourcesCoordinates": {"passes": True, "targetMarkers": 0},
            },
            "artifacts": {},
            "passes": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report_with_hash(core)), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "exact contract"):
                _load_reusable_report(
                    path,
                    expected_identity=identity,
                    expected_scope={"tiles": 1},
                )


if __name__ == "__main__":
    unittest.main()
