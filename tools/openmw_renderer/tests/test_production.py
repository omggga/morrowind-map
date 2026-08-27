from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.land_renderer.terrain import RgbaImage
from tools.openmw_renderer.production import (
    CHECKPOINT_SCHEMA_VERSION,
    DATASET_ID,
    DEFAULT_PRODUCTION_IMAGE,
    DEFAULT_STAGE45_IMAGE,
    NATIVE_ZOOM,
    SNAPSHOT_ID,
    TileKey,
    build_inventory,
    build_lower_zoom_level,
    cell_for_native_tile,
    compose_parent,
    derive_effective_exterior_cells,
    derive_effective_land_cells,
    docker_batch_command,
    docker_build_command,
    explicit_3x3_shard,
    finalize_production,
    group_targets_3x3,
    native_tile_for_cell,
    plan_fingerprint,
    plan_native_targets,
    production_source_fingerprint,
    read_shard_runtime,
    render_shard_manifest,
    run_native_batch,
    run_openmw_production,
    select_shards,
)


FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64


def _subrecord(name: bytes, payload: bytes) -> bytes:
    return struct.pack("<4sI", name, len(payload)) + payload


def _record(name: bytes, payload: bytes) -> bytes:
    return struct.pack("<4sIII", name, len(payload), 0, 0) + payload


def _cell(
    grid: tuple[int, int],
    *,
    interior: bool = False,
    deleted: bool = False,
    deleted_reference: bool = False,
) -> bytes:
    flags = 1 if interior else 0
    payload = _subrecord(b"NAME", b"fixture\0")
    payload += _subrecord(b"DATA", struct.pack("<Iii", flags, *grid))
    if deleted:
        payload += _subrecord(b"DELE", b"\0\0\0")
    if deleted_reference:
        payload += _subrecord(b"FRMR", struct.pack("<I", 1))
        payload += _subrecord(b"DELE", b"\0\0\0")
    return _record(b"CELL", payload)


def _land(grid: tuple[int, int], *, deleted: bool = False) -> bytes:
    payload = _subrecord(b"INTV", struct.pack("<ii", *grid))
    payload += _subrecord(b"DATA", struct.pack("<I", 0))
    if deleted:
        payload += _subrecord(b"DELE", b"\0\0\0")
    return _record(b"LAND", payload)


def _fake_webp(image: RgbaImage) -> bytes:
    body = hashlib.sha256(
        f"{image.width}x{image.height}".encode() + image.pixels
    ).digest()
    return b"RIFF" + (4 + len(body)).to_bytes(4, "little") + b"WEBP" + body


class CoverageTests(unittest.TestCase):
    def test_effective_cell_coverage_obeys_load_order_and_cell_level_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.esm"
            override = root / "override.esm"
            base.write_bytes(
                _cell((-5, -7))
                + _cell((0, 0), deleted_reference=True)
                + _cell((99, 99), interior=True)
            )
            override.write_bytes(
                _cell((-5, -7), deleted=True)
                + _cell((0, 0))
                + _cell((4, -2))
            )

            cells = derive_effective_exterior_cells((base, override))

        self.assertEqual(cells, ((4, -2), (0, 0)))

    def test_effective_land_coverage_obeys_overrides_and_deletions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.esm"
            override = root / "override.esm"
            base.write_bytes(_land((-8, -9)) + _land((2, 3)))
            override.write_bytes(_land((-8, -9), deleted=True) + _land((-1, 4)))

            cells = derive_effective_land_cells((base, override))

        self.assertEqual(cells, ((2, 3), (-1, 4)))


class CoordinateAndShardTests(unittest.TestCase):
    def test_negative_tes3_cells_round_trip_through_native_xyz(self) -> None:
        fixtures = {
            (-28, 33): TileKey(7, 0, 0),
            (-3, -2): TileKey(7, 25, 35),
            (0, 0): TileKey(7, 28, 33),
            (49, -58): TileKey(7, 77, 91),
        }
        for cell, tile in fixtures.items():
            with self.subTest(cell=cell):
                self.assertEqual(native_tile_for_cell(cell), tile)
                self.assertEqual(cell_for_native_tile(tile), cell)

    def test_offset_two_partition_is_deterministic_for_negative_cells(self) -> None:
        cells = [
            (-4, -4),
            (-3, -4),
            (-2, -4),
            (-4, -3),
            (-3, -3),
            (-2, -3),
            (-4, -2),
            (-3, -2),
            (-2, -2),
            (0, 0),
        ]
        shuffled = list(reversed(cells)) + [(-3, -3)]

        targets = plan_native_targets(shuffled)
        shards = group_targets_3x3(targets)

        self.assertEqual([shard.center for shard in shards], [(-3, -3), (0, 0)])
        self.assertEqual([len(shard.targets) for shard in shards], [9, 1])
        self.assertEqual(
            plan_fingerprint(targets),
            plan_fingerprint(tuple(reversed(targets))),
        )

    def test_explicit_smoke_shard_has_exactly_nine_targets(self) -> None:
        shard = explicit_3x3_shard((-3, -3))

        self.assertEqual(shard.center, (-3, -3))
        self.assertEqual(len(shard.targets), 9)
        self.assertEqual(
            {target.cell for target in shard.targets},
            {(x, y) for x in range(-4, -1) for y in range(-4, -1)},
        )

    def test_modulo_partition_is_stable_before_and_after_resume_filtering(self) -> None:
        targets = plan_native_targets(
            (x, y) for y in range(-7, 3) for x in range(-7, 3)
        )
        shards = group_targets_3x3(targets)

        partitions = [select_shards(shards, shard_index=index, shard_count=3) for index in range(3)]

        self.assertEqual(
            {shard.key for partition in partitions for shard in partition},
            {shard.key for shard in shards},
        )
        self.assertEqual(
            sum((list(partition) for partition in partitions), []),
            [
                shard
                for index in range(3)
                for ordinal, shard in enumerate(shards)
                if ordinal % 3 == index
            ],
        )
        with self.assertRaisesRegex(ValueError, "0 <= index < shard_count"):
            select_shards(shards, shard_index=3, shard_count=3)


class BatchProcessContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shard = explicit_3x3_shard((-3, -3))

    def test_manifest_is_top_left_ordered_and_uses_absolute_atomic_raw_paths(self) -> None:
        manifest = render_shard_manifest(self.shard)
        lines = manifest.splitlines()

        self.assertEqual(len(lines), 9)
        self.assertEqual(lines[0], "-4,-2\t/out/raw/7/24/35.png")
        self.assertEqual(lines[-1], "-2,-4\t/out/raw/7/26/37.png")
        self.assertEqual(len(set(lines)), 9)

    def test_docker_command_runs_one_isolated_process_for_the_whole_shard(self) -> None:
        with (
            patch("tools.openmw_renderer.production.os.getuid", return_value=501),
            patch("tools.openmw_renderer.production.os.getgid", return_value=20),
            patch(
                "tools.openmw_renderer.production._container_name",
                return_value="mwm5-fixture",
            ),
        ):
            command = docker_batch_command(
                image="morrowind-map-openmw:fixture",
                source_root=Path("/host/source"),
                profile_root=Path("/host/profile"),
                output_root=Path("/host/output"),
                shard=self.shard,
            )

        self.assertEqual(command[:6], ["docker", "run", "--rm", "--name", "mwm5-fixture", "--platform"])
        self.assertIn("MWMAP_EXPORT_BATCH_FILE=/profile/export-targets.tsv", command)
        self.assertIn("MWMAP_EXPORT_BATCH_CENTER=-3,-3", command)
        self.assertIn("MWMAP_EXPORT_BATCH_ID=cx-n3_cy-n3", command)
        self.assertNotIn("MWMAP_EXPORT_CELL", "\n".join(command))
        self.assertNotIn("MWMAP_EXPORT_PATH", "\n".join(command))
        self.assertEqual(command.count("morrowind-map-openmw:fixture"), 1)
        self.assertIn("none", command)
        self.assertIn("--read-only", command)
        self.assertNotIn("--privileged", command)

    def test_batch_patch_preserves_context_and_renders_only_requested_rtts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (
            root / "patches/openmw-0.51.0-map-export-batch.patch"
        ).read_text(encoding="utf-8")

        self.assertIn('std::getenv("MWMAP_EXPORT_BATCH_FILE") != nullptr ? 2', source)
        self.assertIn("Export batch target is outside the declared 3x3 center", source)
        self.assertIn("result.mTargets.empty() || result.mTargets.size() > 9", source)
        self.assertIn("Duplicate export batch cell", source)
        self.assertIn("Duplicate export batch output path", source)
        self.assertIn("if (exportConfig && exportTarget == nullptr)", source)
        self.assertIn("MWMAP export batch scheduled: center=", source)
        self.assertIn("MWMAP export batch missing 5x5 context CELL", source)
        self.assertIn("for (const auto& target : exportConfig->mTargets)", source)
        self.assertIn("setupRenderToTexture(target.mCellX, target.mCellY", source)
        self.assertIn("return std::all_of(config->mTargets.begin()", source)
        self.assertIn("finishLocalMapExportTarget(node->mExportPath, written)", source)
        self.assertNotIn("constexpr int CellGridRadius = 2", source)

    def test_production_image_is_incremental_and_entrypoint_records_cgroup_peak(self) -> None:
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "Dockerfile.production").read_text(encoding="utf-8")
        entrypoint = (root / "entrypoint-production.sh").read_text(encoding="utf-8")

        self.assertIn("ARG STAGE45_IMAGE", dockerfile)
        self.assertIn("FROM ${STAGE45_IMAGE}", dockerfile)
        self.assertIn("openmw-0.51.0-map-export-batch.patch", dockerfile)
        self.assertIn("git -C /src/openmw apply --check", dockerfile)
        self.assertIn('io.morrowind-map.scene-grid="5x5"', dockerfile)
        self.assertIn('io.morrowind-map.rtt-grid="3x3"', dockerfile)
        self.assertIn('io.morrowind-map.stage45-image-id="${STAGE45_IMAGE_ID}"', dockerfile)
        self.assertIn("MWMAP_EXPORT_BATCH_FILE is required", entrypoint)
        self.assertIn("/sys/fs/cgroup/memory.peak", entrypoint)
        self.assertIn('runtime_root="/out/runtime/${MWMAP_EXPORT_BATCH_ID}"', entrypoint)
        self.assertNotIn("exec xvfb-run", entrypoint)

    def test_build_command_pins_the_base_tag_and_current_source_fingerprint(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        command = docker_build_command(repo_root=repo_root)
        source_hash = production_source_fingerprint(repo_root)

        self.assertEqual(command[0:2], ["docker", "build"])
        self.assertIn(DEFAULT_PRODUCTION_IMAGE, command)
        self.assertIn(f"STAGE45_IMAGE={DEFAULT_STAGE45_IMAGE}", command)
        self.assertIn("STAGE45_IMAGE_ID=unverified", command)
        self.assertIn(f"PRODUCTION_FINGERPRINT={source_hash}", command)

    def test_runtime_evidence_requires_numeric_cgroup_peak_and_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            runtime_root = output_root / "runtime/cx-n3_cy-n3"
            runtime_root.mkdir(parents=True)
            (runtime_root / "memory.peak").write_text("2147483648\n", encoding="ascii")
            (runtime_root / "process.json").write_text(
                '{"elapsedSeconds":31,"exitCode":0}\n',
                encoding="utf-8",
            )

            evidence = read_shard_runtime(output_root, "cx-n3_cy-n3")
            self.assertEqual(evidence.elapsed_seconds, 31)
            self.assertEqual(evidence.memory_peak_bytes, 2_147_483_648)

            (runtime_root / "memory.peak").write_text("unavailable\n", encoding="ascii")
            with self.assertRaisesRegex(RuntimeError, "no usable cgroup memory peak"):
                read_shard_runtime(output_root, "cx-n3_cy-n3")

    def test_parallel_pipeline_keeps_docker_image_identity_across_shards(self) -> None:
        cells = ((-3, -3), (0, 0))
        images_seen: list[str] = []

        def fake_shard_process(**kwargs) -> None:
            images_seen.append(kwargs["image"])

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "tools.openmw_renderer.production._run_shard_process",
                    side_effect=fake_shard_process,
                ),
                patch(
                    "tools.openmw_renderer.production.process_raw_master",
                    return_value=RgbaImage.solid(512, 512, (1, 2, 3, 255)),
                ),
                patch(
                    "tools.openmw_renderer.production._webp_encoder",
                    return_value=_fake_webp,
                ),
            ):
                result = run_openmw_production(
                    source_root=Path(directory),
                    output_root=Path(directory) / "output",
                    cells=cells,
                    provenance_fingerprint=FINGERPRINT_A,
                    image="morrowind-map-openmw:fixture",
                    workers=2,
                    retain_raw=True,
                )

        self.assertEqual(images_seen, [
            "morrowind-map-openmw:fixture",
            "morrowind-map-openmw:fixture",
        ])
        self.assertEqual((result.rendered, result.selected_shards), (2, 2))


class CheckpointTests(unittest.TestCase):
    def test_interrupted_batch_resumes_without_reencoding_completed_tile(self) -> None:
        cells = ((-3, -3), (-2, -3))
        calls: list[tuple[int, int]] = []

        def interrupted(target):
            calls.append(target.cell)
            if target.cell == (-2, -3):
                raise RuntimeError("fixture interruption")
            return RgbaImage.solid(512, 512, (10, 20, 30, 255))

        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "fixture interruption"):
                run_native_batch(
                    output_root=output_root,
                    cells=cells,
                    provenance_fingerprint=FINGERPRINT_A,
                    render_target=interrupted,
                    encoder=_fake_webp,
                )

            checkpoint = json.loads(
                (output_root / "checkpoint.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["schemaVersion"], CHECKPOINT_SCHEMA_VERSION)
            self.assertEqual(len(checkpoint["completed"]), 1)

            resumed_calls: list[tuple[int, int]] = []
            result = run_native_batch(
                output_root=output_root,
                cells=reversed(cells),
                provenance_fingerprint=FINGERPRINT_A,
                render_target=lambda target: (
                    resumed_calls.append(target.cell)
                    or RgbaImage.solid(512, 512, (40, 50, 60, 255))
                ),
                encoder=_fake_webp,
            )

        self.assertEqual(calls, [(-3, -3), (-2, -3)])
        self.assertEqual(resumed_calls, [(-2, -3)])
        self.assertEqual((result.rendered, result.skipped), (1, 1))

    def test_stale_provenance_is_rejected_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            run_native_batch(
                output_root=output_root,
                cells=((1, 2),),
                provenance_fingerprint=FINGERPRINT_A,
                render_target=lambda _target: RgbaImage.solid(512, 512, (1, 2, 3, 255)),
                encoder=_fake_webp,
            )
            with self.assertRaisesRegex(ValueError, "provenanceFingerprint mismatch"):
                run_native_batch(
                    output_root=output_root,
                    cells=((1, 2),),
                    provenance_fingerprint=FINGERPRINT_B,
                    render_target=lambda _target: self.fail("renderer must not run"),
                    encoder=_fake_webp,
                )

    def test_encoder_failure_preserves_existing_output_and_incomplete_checkpoint(self) -> None:
        cell = (-3, -2)
        target = plan_native_targets((cell,))[0]
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            output_path = output_root / "tiles" / target.tile.relative_path
            output_path.parent.mkdir(parents=True)
            output_path.write_bytes(b"preexisting-untrusted-output")

            def fail_encoder(_image: RgbaImage) -> bytes:
                raise RuntimeError("encoder failed")

            with self.assertRaisesRegex(RuntimeError, "encoder failed"):
                run_native_batch(
                    output_root=output_root,
                    cells=(cell,),
                    provenance_fingerprint=FINGERPRINT_A,
                    render_target=lambda _target: RgbaImage.solid(
                        512, 512, (1, 2, 3, 255)
                    ),
                    encoder=fail_encoder,
                )

            checkpoint = json.loads(
                (output_root / "checkpoint.json").read_text(encoding="utf-8")
            )
            leftovers = list(output_path.parent.glob(f".{output_path.name}.*.tmp"))
            preserved = output_path.read_bytes()

        self.assertEqual(preserved, b"preexisting-untrusted-output")
        self.assertEqual(checkpoint["completed"], [])
        self.assertEqual(leftovers, [])


class PyramidAndInventoryTests(unittest.TestCase):
    def test_parent_composition_uses_xyz_top_left_orientation_and_sparse_alpha(self) -> None:
        colors = {
            (0, 0): (255, 0, 0, 255),
            (1, 0): (0, 255, 0, 255),
            (0, 1): (0, 0, 255, 255),
            (1, 1): (255, 255, 0, 255),
        }
        parent = compose_parent(
            {quadrant: RgbaImage.solid(512, 512, color) for quadrant, color in colors.items()}
        )

        self.assertEqual(parent.pixel(10, 10), colors[(0, 0)])
        self.assertEqual(parent.pixel(300, 10), colors[(1, 0)])
        self.assertEqual(parent.pixel(10, 300), colors[(0, 1)])
        self.assertEqual(parent.pixel(300, 300), colors[(1, 1)])

        sparse = compose_parent({(0, 0): RgbaImage.solid(512, 512, (12, 34, 56, 255))})
        self.assertEqual(sparse.pixel(100, 100), (12, 34, 56, 255))
        self.assertEqual(sparse.pixel(400, 400), (0, 0, 0, 0))

    def test_lower_zoom_floor_groups_negative_xyz_children(self) -> None:
        child_colors = {
            TileKey(7, -2, -2): (1, 2, 3, 255),
            TileKey(7, -1, -2): (4, 5, 6, 255),
            TileKey(7, -2, -1): (7, 8, 9, 255),
            TileKey(7, -1, -1): (10, 11, 12, 255),
        }
        images = {
            tile.relative_path.as_posix(): RgbaImage.solid(512, 512, color)
            for tile, color in child_colors.items()
        }
        encoded_images: list[RgbaImage] = []

        def reader(path: Path) -> RgbaImage:
            return images[Path(*path.parts[-3:]).as_posix()]

        def encoder(image: RgbaImage) -> bytes:
            encoded_images.append(image)
            return _fake_webp(image)

        with tempfile.TemporaryDirectory() as directory:
            parents = build_lower_zoom_level(
                tile_root=Path(directory),
                child_tiles=child_colors,
                reader=reader,
                encoder=encoder,
            )

        self.assertEqual(parents, (TileKey(6, -1, -1),))
        parent = encoded_images[0]
        self.assertEqual(parent.pixel(10, 10), child_colors[TileKey(7, -2, -2)])
        self.assertEqual(parent.pixel(300, 10), child_colors[TileKey(7, -1, -2)])
        self.assertEqual(parent.pixel(10, 300), child_colors[TileKey(7, -2, -1)])
        self.assertEqual(parent.pixel(300, 300), child_colors[TileKey(7, -1, -1)])

    def test_inventory_is_portable_and_deterministic_across_creation_order(self) -> None:
        tiles = (TileKey(7, 25, 35), TileKey(6, 12, 17), TileKey(7, 26, 35))
        payloads = {
            tiles[0]: b"first",
            tiles[1]: b"parent",
            tiles[2]: b"second",
        }
        plan_hash = hashlib.sha256(b"plan").hexdigest()
        inventories = []
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for root_value, order in (
                (first, tiles),
                (second, tuple(reversed(tiles))),
            ):
                root = Path(root_value)
                for tile in order:
                    path = root / "tiles" / tile.relative_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payloads[tile])
                inventories.append(
                    build_inventory(
                        output_root=root,
                        tiles=reversed(order),
                        provenance_fingerprint=FINGERPRINT_A,
                        plan_fingerprint_value=plan_hash,
                    ).payload
                )

        self.assertEqual(inventories[0], inventories[1])
        inventory = inventories[0]
        self.assertEqual(inventory["datasetId"], DATASET_ID)
        self.assertEqual(inventory["snapshotId"], SNAPSHOT_ID)
        self.assertEqual(inventory["tileCount"], 3)
        self.assertTrue(all(not Path(item["path"]).is_absolute() for item in inventory["tiles"]))
        core = {key: value for key, value in inventory.items() if key != "inventorySha256"}
        expected_hash = hashlib.sha256(
            json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(inventory["inventorySha256"], expected_hash)
        self.assertEqual(NATIVE_ZOOM, 7)

    def test_finalize_publishes_inventory_last_without_temporary_files(self) -> None:
        cell = (-3, -2)
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            run_native_batch(
                output_root=output_root,
                cells=(cell,),
                provenance_fingerprint=FINGERPRINT_A,
                render_target=lambda _target: RgbaImage.solid(
                    512, 512, (10, 20, 30, 255)
                ),
                encoder=_fake_webp,
            )
            inventory = finalize_production(
                output_root=output_root,
                cells=(cell,),
                provenance_fingerprint=FINGERPRINT_A,
                min_zoom=7,
            )
            published = json.loads(
                (output_root / "inventory.json").read_text(encoding="utf-8")
            )
            temporary = list(output_root.glob(".inventory.json.*.tmp"))

        self.assertEqual(published, inventory.payload)
        self.assertEqual(temporary, [])


if __name__ == "__main__":
    unittest.main()
