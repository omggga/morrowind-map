from __future__ import annotations

import json
import unittest
import tempfile
from pathlib import Path
from unittest import mock

from tools.land_renderer.terrain import RgbaImage
from tools.openmw_renderer.production import TILE_PIXELS, TileKey, native_tile_for_cell
from tools.openmw_renderer.publish import ValidatedInventory
from tools.openmw_renderer import stabilize as stabilization
from tools.openmw_renderer.stabilize import (
    CrossShardEdge,
    _blend_pixel,
    _build_stabilized_pyramid,
    _extract_edges,
    _publish_staged_directory_no_replace,
    _require_stabilization_inputs_unchanged,
    _resolve_stabilization_toolchain,
    _webp_coder_identity,
    border_neighbors,
    cross_shard_edges,
    stabilize_native_image,
    validate_stabilization_receipt,
)


def _pixel(image: RgbaImage, x: int, y: int) -> tuple[int, int, int, int]:
    offset = (y * image.width + x) * 4
    return tuple(image.pixels[offset : offset + 4])  # type: ignore[return-value]


class SeamKernelTests(unittest.TestCase):
    def test_immutable_release_publication_never_replaces_existing_empty_root(self) -> None:
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

    def test_stabilization_rejects_inputs_changed_during_execution(self) -> None:
        with mock.patch(
            "tools.openmw_renderer.stabilize.stabilizer_implementation_sha256",
            return_value="b" * 64,
        ):
            with self.assertRaisesRegex(RuntimeError, "implementation changed"):
                _require_stabilization_inputs_unchanged(
                    implementation_sha256="a" * 64,
                    resolved_magick="/pinned/magick",
                    toolchain={"identity": "captured"},
                    repo_root=Path("."),
                    expected_production_source_fingerprint="c" * 64,
                    expected_magick_version="fixture",
                )

        with (
            mock.patch(
                "tools.openmw_renderer.stabilize.stabilizer_implementation_sha256",
                return_value="a" * 64,
            ),
            mock.patch(
                "tools.openmw_renderer.stabilize._resolve_stabilization_toolchain",
                return_value=("/pinned/magick", {"identity": "changed"}),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "toolchain changed"):
                _require_stabilization_inputs_unchanged(
                    implementation_sha256="a" * 64,
                    resolved_magick="/pinned/magick",
                    toolchain={"identity": "captured"},
                    repo_root=Path("."),
                    expected_production_source_fingerprint="c" * 64,
                    expected_magick_version="fixture",
                )

    def test_postprocess_toolchain_must_match_render_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "magick"
            executable.write_bytes(b"fixture executable")
            with (
                mock.patch(
                    "tools.openmw_renderer.stabilize.shutil.which",
                    return_value=str(executable),
                ),
                mock.patch(
                    "tools.openmw_renderer.stabilize.production_source_fingerprint",
                    return_value="a" * 64,
                ),
                mock.patch(
                    "tools.openmw_renderer.stabilize._magick_version",
                    return_value="ImageMagick exact version",
                ),
                mock.patch(
                    "tools.openmw_renderer.stabilize._webp_coder_identity",
                    return_value="WEBP* WEBP rw+ libwebp exact",
                ),
            ):
                resolved, identity = _resolve_stabilization_toolchain(
                    repo_root=Path("."),
                    magick="magick",
                    expected_production_source_fingerprint="a" * 64,
                    expected_magick_version="ImageMagick exact version",
                )
                with self.assertRaisesRegex(ValueError, "production source differs"):
                    _resolve_stabilization_toolchain(
                        repo_root=Path("."),
                        magick="magick",
                        expected_production_source_fingerprint="b" * 64,
                        expected_magick_version="ImageMagick exact version",
                    )

        self.assertEqual(resolved, str(executable.resolve()))
        self.assertEqual(identity["productionSourceFingerprint"], "a" * 64)
        self.assertEqual(identity["imageMagick"]["version"], "ImageMagick exact version")
        self.assertEqual(identity["imageMagick"]["webpCoder"], "WEBP* WEBP rw+ libwebp exact")

    def test_webp_coder_identity_requires_exactly_one_entry(self) -> None:
        with mock.patch(
            "tools.openmw_renderer.stabilize.subprocess.run",
            return_value=mock.Mock(stdout="PNG PNG rw- fixture\n"),
        ):
            with self.assertRaisesRegex(RuntimeError, "found 0"):
                _webp_coder_identity("magick")

        with mock.patch(
            "tools.openmw_renderer.stabilize.subprocess.run",
            return_value=mock.Mock(
                stdout="WEBP* WEBP rw+ one\nWEBP WEBP rw+ two\n"
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "found 2"):
                _webp_coder_identity("magick")

    def test_custom_magick_is_forwarded_to_every_pyramid_level(self) -> None:
        levels = [(TileKey(zoom, 0, 0),) for zoom in range(6, -1, -1)]
        with mock.patch(
            "tools.openmw_renderer.stabilize.build_lower_zoom_level",
            side_effect=levels,
        ) as build:
            result = _build_stabilized_pyramid(
                Path("/fixture"),
                [TileKey(7, 0, 0)],
                magick="/pinned/magick",
            )

        self.assertEqual(len(result), 8)
        self.assertEqual(build.call_count, 7)
        self.assertTrue(
            all(call.kwargs["magick"] == "/pinned/magick" for call in build.call_args_list)
        )

    def test_opaque_linear_thirds_are_exact(self) -> None:
        self.assertEqual(
            _blend_pixel(bytes((0, 0, 0, 255)), bytes((255, 255, 255, 255)), first_weight=2),
            bytes((85, 85, 85, 255)),
        )
        self.assertEqual(
            _blend_pixel(bytes((0, 0, 0, 255)), bytes((255, 255, 255, 255)), first_weight=1),
            bytes((170, 170, 170, 255)),
        )

    def test_transparent_color_does_not_bleed_into_opaque_pixel(self) -> None:
        result = _blend_pixel(
            bytes((255, 0, 0, 0)),
            bytes((0, 0, 255, 255)),
            first_weight=2,
        )

        self.assertEqual(result[:3], bytes((0, 0, 255)))
        self.assertEqual(result[3], 85)


class StabilizationReceiptTests(unittest.TestCase):
    def test_valid_receipt_with_transform_record_returns_receipt_dict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            tile = TileKey(stabilization.NATIVE_ZOOM, 0, 0)
            tile_path = (Path("tiles") / tile.relative_path).as_posix()
            tile_bytes = b"synthetic stabilized tile"
            tile_sha256 = stabilization._sha256_bytes(tile_bytes)
            tile_entry = {
                "z": tile.z,
                "x": tile.x,
                "y": tile.y,
                "path": tile_path,
                "bytes": len(tile_bytes),
                "sha256": tile_sha256,
            }
            provenance_fingerprint = "1" * 64
            plan_fingerprint = "2" * 64
            production_source_fingerprint = "3" * 64

            source_core = {
                "schemaVersion": 1,
                "datasetId": stabilization.DATASET_ID,
                "snapshotId": stabilization.SNAPSHOT_ID,
                "provenanceFingerprint": provenance_fingerprint,
                "planFingerprint": plan_fingerprint,
                "tiles": [tile_entry],
            }
            source_payload = dict(source_core)
            source_payload["inventorySha256"] = stabilization._sha256_bytes(
                stabilization._canonical_json_bytes(source_core)
            )
            source_path = output_root / stabilization.SOURCE_INVENTORY_PATH
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(stabilization._canonical_json_bytes(source_payload))

            checkpoint = {
                "completed": [
                    {
                        "path": tile_path,
                        "bytes": len(tile_bytes),
                        "sha256": tile_sha256,
                    }
                ]
            }
            (output_root / "checkpoint.json").write_bytes(
                stabilization._canonical_json_bytes(checkpoint)
            )
            (output_root / "provenance.json").write_bytes(
                stabilization._canonical_json_bytes({"fixture": "provenance"})
            )
            (output_root / "plan.json").write_bytes(
                stabilization._canonical_json_bytes({"fixture": "plan"})
            )

            transform_record = {
                "z": tile.z,
                "x": tile.x,
                "y": tile.y,
                "path": tile_path,
                "sides": ["east", "west"],
                "beforeBytes": len(tile_bytes),
                "beforeSha256": tile_sha256,
                "beforeRgbaSha256": "4" * 64,
                "afterBytes": len(tile_bytes),
                "afterSha256": tile_sha256,
                "afterRgbaSha256": "5" * 64,
            }
            transform_path = output_root / stabilization.TILE_TRANSFORMS_PATH
            transform_path.write_bytes(
                stabilization._canonical_json_bytes(transform_record) + b"\n"
            )

            postprocess_toolchain = {
                "productionSourceFingerprint": production_source_fingerprint,
                "imageMagick": {
                    "version": "fixture-magick-v1",
                    "webpCoder": "WEBP* WEBP rw+ fixture-libwebp",
                    "executableSha256": "6" * 64,
                },
                "python": {
                    "implementation": "CPython",
                    "version": "fixture-python-v1",
                },
            }
            source_artifact = stabilization._artifact(source_path, output_root)
            source_artifact["logicalSha256"] = source_payload["inventorySha256"]
            transform_artifact = stabilization._artifact(transform_path, output_root)
            transform_artifact["records"] = 1
            identity = {
                "algorithm": {
                    "boundaryWidthPixels": 1,
                    "kernel": "linear-2:1",
                    "alphaMode": "premultiplied",
                    "passes": ["east-west", "north-south"],
                    "nativeZoom": stabilization.NATIVE_ZOOM,
                    "tilePixels": TILE_PIXELS,
                },
                "implementationSha256": "7" * 64,
                "postprocessToolchain": postprocess_toolchain,
                "sourceInventory": source_artifact,
                "tileTransforms": transform_artifact,
                "renderCheckpointFileSha256": stabilization._sha256_file(
                    output_root / "checkpoint.json"
                ),
                "provenanceFileSha256": stabilization._sha256_file(
                    output_root / "provenance.json"
                ),
                "provenanceFingerprint": provenance_fingerprint,
                "planFileSha256": stabilization._sha256_file(output_root / "plan.json"),
                "planFingerprint": plan_fingerprint,
                "scope": {
                    "nativeTiles": 1,
                    "crossShardAdjacencies": 1,
                    "touchedTiles": 1,
                    "changedTiles": 0,
                },
            }
            stabilization_fingerprint = stabilization._sha256_bytes(
                stabilization._canonical_json_bytes(identity)
            )
            inventory = ValidatedInventory(
                payload={
                    "postprocess": {
                        "type": "crossShardSeamStabilization",
                        "version": stabilization.STABILIZER_VERSION,
                        "fingerprint": stabilization_fingerprint,
                    }
                },
                inventory_sha256="8" * 64,
                inventory_file_sha256="9" * 64,
                provenance_file_sha256="a" * 64,
                plan_file_sha256="b" * 64,
                tile_count=1,
                total_bytes=len(tile_bytes),
                tile_entries=(tile_entry,),
                provenance={"magickVersion": "fixture-magick-v1"},
                provenance_fingerprint=provenance_fingerprint,
                plan_fingerprint=plan_fingerprint,
                profile_fingerprint="c" * 64,
                renderer_fingerprint="d" * 64,
                production_source_fingerprint=production_source_fingerprint,
                asset_tree_fingerprint="e" * 64,
                input_fingerprint="f" * 64,
                source_scope={},
            )
            receipt_core = {
                "schemaVersion": stabilization.STABILIZER_SCHEMA_VERSION,
                "datasetId": stabilization.DATASET_ID,
                "snapshotId": stabilization.SNAPSHOT_ID,
                "stabilizerVersion": stabilization.STABILIZER_VERSION,
                "stabilizationFingerprint": stabilization_fingerprint,
                "identity": identity,
                "output": {
                    "inventorySha256": inventory.inventory_sha256,
                    "inventoryFileSha256": inventory.inventory_file_sha256,
                    "nativeAggregateSha256": stabilization._native_aggregate(
                        inventory.tile_entries
                    ),
                    "tileCount": inventory.tile_count,
                    "totalBytes": inventory.total_bytes,
                },
            }
            expected_receipt = stabilization._receipt_with_hash(receipt_core)
            (output_root / stabilization.STABILIZATION_RECEIPT).write_text(
                json.dumps(expected_receipt), encoding="utf-8"
            )
            synthetic_edge = CrossShardEdge(tile, tile, "east")

            with (
                mock.patch.object(
                    stabilization, "EXPECTED_CROSS_SHARD_EDGES", 1
                ),
                mock.patch.object(
                    stabilization,
                    "cross_shard_edges",
                    return_value=(synthetic_edge,),
                ),
            ):
                result = validate_stabilization_receipt(
                    output_root,
                    inventory,
                    require_current_implementation=False,
                )

        self.assertIsInstance(result, dict)
        self.assertEqual(result, expected_receipt)


class NativeTileStabilizationTests(unittest.TestCase):
    def test_only_documented_boundary_columns_change(self) -> None:
        left_tile = native_tile_for_cell((1, 0))
        right_tile = native_tile_for_cell((2, 0))
        self.assertEqual(right_tile.x, left_tile.x + 1)
        left = RgbaImage.solid(TILE_PIXELS, TILE_PIXELS, (0, 0, 0, 255))
        right = RgbaImage.solid(TILE_PIXELS, TILE_PIXELS, (255, 255, 255, 255))
        edge = CrossShardEdge(left_tile, right_tile, "east")
        neighbors = border_neighbors((edge,))
        edges = {
            left_tile: _extract_edges(left),
            right_tile: _extract_edges(right),
        }

        corrected_left = stabilize_native_image(
            left_tile, left, edges=edges, neighbors=neighbors
        )
        corrected_right = stabilize_native_image(
            right_tile, right, edges=edges, neighbors=neighbors
        )

        self.assertEqual(_pixel(corrected_left, TILE_PIXELS - 1, 200), (85, 85, 85, 255))
        self.assertEqual(_pixel(corrected_right, 0, 200), (170, 170, 170, 255))
        self.assertEqual(_pixel(corrected_left, TILE_PIXELS - 2, 200), (0, 0, 0, 255))
        self.assertEqual(_pixel(corrected_right, 1, 200), (255, 255, 255, 255))
        self.assertEqual(_pixel(corrected_left, 10, 10), (0, 0, 0, 255))

    def test_cross_shard_selection_uses_the_pinned_partition(self) -> None:
        same_a = native_tile_for_cell((0, 0))
        same_b = native_tile_for_cell((1, 0))
        cross = native_tile_for_cell((2, 0))

        result = cross_shard_edges((same_a, same_b, cross))

        self.assertEqual(result, (CrossShardEdge(same_b, cross, "east"),))


if __name__ == "__main__":
    unittest.main()
