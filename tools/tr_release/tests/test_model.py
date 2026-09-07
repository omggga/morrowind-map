from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.tr_release import model as tr_model
from tools.tr_release.model import (
    BASE_INPUT_HASHES,
    CONTENT_FILES,
    DATA_DIRECTORY_IDS,
    FALLBACK_ARCHIVES,
    INVENTORY_ONLY_FILES,
    MAP_KEY,
    ProfileError,
    canonical_json_bytes,
    canonical_json_sha256,
    derive_land_topology,
    generate_release_lock,
    load_profile,
    parse_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = REPO_ROOT / "config/tr-release.json"


class ReleaseProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

    def test_cyrodiil_profile_uses_shared_engine_with_its_own_land_scope(self) -> None:
        profile = load_profile(REPO_ROOT / "config/pc-release.json")
        self.assertEqual(parse_profile(profile.to_dict()), profile)
        self.assertEqual(profile.land_content_files, ("Cyr_Main.esm",))
        self.assertEqual(profile.catalog_regions, ("cyrodiil",))
        self.assertEqual(profile.snapshot_prefix, "pc")
        self.assertNotIn("TR_Mainland.esm", profile.content_files)
        future = profile.to_dict()
        future["datasetId"] = "abecean-shores-next"
        future["requiredInputs"][-1].pop("sha256", None)
        self.assertEqual(parse_profile(future).dataset_id, "abecean-shores-next")
        future["contentFiles"][-1] = "unexpected.esp"
        with self.assertRaises(ProfileError):
            parse_profile(future)

    def test_seed_profile_is_current_strict_contract_and_round_trips(self) -> None:
        profile = load_profile(PROFILE_PATH)

        self.assertEqual(profile.schema_version, 1)
        self.assertEqual(profile.dataset_id, "poison-song-26.08")
        self.assertEqual(profile.map_key, MAP_KEY)
        self.assertEqual(tuple(item.id for item in profile.data_directories), DATA_DIRECTORY_IDS)
        self.assertEqual(profile.fallback_archives, FALLBACK_ARCHIVES)
        self.assertEqual(profile.content_files, CONTENT_FILES)
        self.assertEqual(profile.inventory_only_files, INVENTORY_ONLY_FILES)
        self.assertEqual(
            profile.adopted_snapshot_id,
            "tr:poison-song-26.08:6964517551e0fcb0",
        )
        self.assertEqual(len(profile.required_inputs), 10)
        self.assertEqual(len(profile.smoke_centers), 4)
        self.assertEqual(profile.to_dict(), self.payload)

    def test_home_of_nords_keeps_dependency_land_and_grass_out_of_render(self) -> None:
        profile = load_profile(REPO_ROOT / "config/shotn-release.json")
        self.assertEqual(parse_profile(profile.to_dict()), profile)
        self.assertEqual(profile.land_content_files, ("Sky_Main.esm",))
        self.assertEqual(profile.catalog_regions, ("skyrim",))
        self.assertEqual(profile.snapshot_prefix, "shotn")
        self.assertNotIn("Sky_Main_Grass.esp", profile.content_files)
        self.assertNotIn("Cyr_Main.esm", profile.content_files)
        self.assertNotIn("TR_Mainland.esm", profile.content_files)

    def test_profile_rejects_unknown_keys_at_every_fixed_object_layer(self) -> None:
        cases = []
        root = copy.deepcopy(self.payload)
        root["surprise"] = True
        cases.append(root)
        release = copy.deepcopy(self.payload)
        release["release"]["channel"] = "stable"
        cases.append(release)
        directory = copy.deepcopy(self.payload)
        directory["dataDirectories"][0]["order"] = 0
        cases.append(directory)
        region = copy.deepcopy(self.payload)
        region["regions"][0]["notes"] = []
        cases.append(region)
        exception = copy.deepcopy(self.payload)
        exception["masterSizeExceptions"][0]["temporary"] = True
        cases.append(exception)

        for payload in cases:
            with self.subTest(payload=payload), self.assertRaisesRegex(ProfileError, "unknown keys"):
                parse_profile(payload)

    def test_loader_rejects_duplicate_json_keys_and_non_finite_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            duplicate = Path(raw) / "duplicate.json"
            duplicate.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "Duplicate JSON key"):
                load_profile(duplicate)

            non_finite = Path(raw) / "nan.json"
            non_finite.write_text('{"schemaVersion":NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "Invalid JSON numeric constant"):
                load_profile(non_finite)

    def test_profile_rejects_absolute_parent_and_noncanonical_paths(self) -> None:
        for unsafe in ("/absolute/data", "../outside", "folder/../outside", "folder//data"):
            payload = copy.deepcopy(self.payload)
            payload["dataDirectories"][1]["path"] = unsafe
            with self.subTest(unsafe=unsafe), self.assertRaises(ProfileError):
                parse_profile(payload)

    def test_profile_rejects_duplicate_and_casefold_colliding_ids_and_paths(self) -> None:
        duplicate_id = copy.deepcopy(self.payload)
        duplicate_id["excludedOptionalModules"][1]["id"] = "tr-factions"
        with self.assertRaisesRegex(ProfileError, "collision"):
            parse_profile(duplicate_id)

        duplicate_cell = copy.deepcopy(self.payload)
        duplicate_cell["smokeCenters"][1]["cell"] = duplicate_cell["smokeCenters"][0]["cell"]
        with self.assertRaisesRegex(ProfileError, "cells must be unique"):
            parse_profile(duplicate_cell)

        casefold_path = copy.deepcopy(self.payload)
        casefold_path["dataDirectories"][0]["path"] = "GameData"
        casefold_path["dataDirectories"][1]["path"] = "gamedata"
        with self.assertRaisesRegex(ProfileError, "collision"):
            parse_profile(casefold_path)

    def test_profile_rejects_every_load_order_deviation_and_optional_content(self) -> None:
        fallback = copy.deepcopy(self.payload)
        fallback["fallbackArchives"].reverse()
        with self.assertRaisesRegex(ProfileError, "fallbackArchives"):
            parse_profile(fallback)

        content = copy.deepcopy(self.payload)
        content["contentFiles"][3:5] = reversed(content["contentFiles"][3:5])
        with self.assertRaisesRegex(ProfileError, "contentFiles"):
            parse_profile(content)

        inventory = copy.deepcopy(self.payload)
        inventory["inventoryOnlyFiles"].reverse()
        with self.assertRaisesRegex(ProfileError, "inventoryOnlyFiles"):
            parse_profile(inventory)

        optional = copy.deepcopy(self.payload)
        optional["contentFiles"][-1] = "TR_Factions.esp"
        with self.assertRaisesRegex(ProfileError, "Excluded optional modules"):
            parse_profile(optional)

    def test_profile_rejects_bad_input_layout_hashes_regions_and_exceptions(self) -> None:
        input_layout = copy.deepcopy(self.payload)
        input_layout["requiredInputs"][7]["filename"] = "renamed.omwscripts"
        with self.assertRaisesRegex(ProfileError, "canonical.*layout"):
            parse_profile(input_layout)

        base_hash = copy.deepcopy(self.payload)
        base_hash["requiredInputs"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ProfileError, "immutable base-game"):
            parse_profile(base_hash)

        duplicate_region = copy.deepcopy(self.payload)
        duplicate_region["regions"][1]["id"] = "VVARdenfell"
        with self.assertRaisesRegex(ProfileError, "lowercase slug"):
            parse_profile(duplicate_region)

        missing_region = copy.deepcopy(self.payload)
        missing_region["pluginRegions"]["TR_Mainland.esm"] = "unknown"
        with self.assertRaisesRegex(ProfileError, "unknown region"):
            parse_profile(missing_region)

        duplicate_exception = copy.deepcopy(self.payload)
        duplicate_exception["masterSizeExceptions"].append(
            copy.deepcopy(duplicate_exception["masterSizeExceptions"][0])
        )
        with self.assertRaisesRegex(ProfileError, "pairs.*collision"):
            parse_profile(duplicate_exception)

        unlocked_exception = copy.deepcopy(self.payload)
        unlocked_exception["requiredInputs"][6].pop("sha256")
        parse_profile(unlocked_exception)

        future_adoption = copy.deepcopy(self.payload)
        future_adoption["datasetId"] = "tamriel-rebuilt-27.01"
        future_adoption["adoptedSnapshotId"] = (
            "tr:tamriel-rebuilt-27.01:1111111111111111"
        )
        with self.assertRaisesRegex(ProfileError, "reserved.*26.08 seed"):
            parse_profile(future_adoption)

    def test_profile_requires_three_unique_shard_aligned_smoke_centers(self) -> None:
        too_few = copy.deepcopy(self.payload)
        too_few["smokeCenters"] = too_few["smokeCenters"][:2]
        with self.assertRaisesRegex(ProfileError, "at least three"):
            parse_profile(too_few)

        unaligned = copy.deepcopy(self.payload)
        unaligned["smokeCenters"][1]["cell"] = [7, -18]
        with self.assertRaisesRegex(ProfileError, "divisible by three"):
            parse_profile(unaligned)


class ReleaseSourceTests(unittest.TestCase):
    def _synthetic_payload(self) -> dict[str, object]:
        payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        payload["datasetId"] = "tamriel-rebuilt-27.01"
        payload["title"] = {"en": "Tamriel Rebuilt 27.01"}
        payload["summary"] = {"en": "Next release."}
        for region in payload["regions"]:
            region["title"] = {"en": region["title"]["en"]}
        payload["release"] = {"name": "Next", "version": "27.01", "build": "27.01.1"}
        payload["dataDirectories"] = [
            {"id": "base-game", "path": "game"},
            {"id": "tamriel-data", "path": "td-27.01"},
            {"id": "tamriel-rebuilt-core", "path": "tr-27.01/core"},
        ]
        for item in payload["requiredInputs"][6:]:
            item.pop("sha256")
        payload["masterSizeExceptions"] = []
        payload.pop("adoptedSnapshotId")
        return payload

    def _write_source(self, root: Path, profile) -> None:
        for item in profile.required_inputs:
            path = root / profile.input_relative_path(item)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"fixture:{item.id}".encode())
        td_root = root / profile.directory_by_id["tamriel-data"].path
        (td_root / "Textures").mkdir()
        (td_root / "Textures/release.dds").write_bytes(b"texture")

    @staticmethod
    def _fixture_hash(path: Path) -> str:
        immutable_by_filename = {
            "Morrowind.esm": BASE_INPUT_HASHES["morrowind-esm"],
            "Tribunal.esm": BASE_INPUT_HASHES["tribunal-esm"],
            "Bloodmoon.esm": BASE_INPUT_HASHES["bloodmoon-esm"],
            "Morrowind.bsa": BASE_INPUT_HASHES["morrowind-bsa"],
            "Tribunal.bsa": BASE_INPUT_HASHES["tribunal-bsa"],
            "Bloodmoon.bsa": BASE_INPUT_HASHES["bloodmoon-bsa"],
        }
        return immutable_by_filename.get(path.name, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_second_release_locks_unpinned_tr_inputs_without_code_changes(self) -> None:
        profile = parse_profile(self._synthetic_payload())
        with tempfile.TemporaryDirectory() as raw:
            source_root = Path(raw)
            self._write_source(source_root, profile)
            with mock.patch("tools.tr_release.model.sha256_file", side_effect=self._fixture_hash):
                first = generate_release_lock(profile, source_root)

                self.assertEqual(first.profile.dataset_id, "tamriel-rebuilt-27.01")
                self.assertEqual(first.snapshot_id, first.derived_snapshot_id)
                self.assertRegex(
                    first.snapshot_id,
                    r"^tr:tamriel-rebuilt-27\.01:[0-9a-f]{16}$",
                )
                self.assertEqual(len(first.source_audit.inputs), 10)
                self.assertEqual(len(first.source_audit.data_trees), 3)
                self.assertTrue(all(item.bytes > 0 for item in first.source_audit.inputs))

                tr_mainland = source_root / profile.input_relative_path(
                    profile.input_by_id["tr-mainland-esm"]
                )
                tr_mainland.write_bytes(b"fixture:next-content")
                changed = generate_release_lock(profile, source_root)
                self.assertNotEqual(changed.profile_fingerprint, first.profile_fingerprint)
                self.assertNotEqual(changed.snapshot_id, first.snapshot_id)

    def test_packaging_noise_is_ignored_deterministically(self) -> None:
        profile = parse_profile(self._synthetic_payload())
        with tempfile.TemporaryDirectory() as raw:
            source_root = Path(raw)
            self._write_source(source_root, profile)
            with mock.patch("tools.tr_release.model.sha256_file", side_effect=self._fixture_hash):
                before = generate_release_lock(profile, source_root)
                for directory in profile.data_directories:
                    tree = source_root / directory.path
                    (tree / ".DS_Store").write_bytes(b"noise")
                    (tree / "Thumbs.db").write_bytes(b"noise")
                    (tree / "desktop.ini").write_bytes(b"noise")
                    (tree / "__MACOSX").mkdir()
                    (tree / "__MACOSX/ignored.bin").write_bytes(os.urandom(13))
                after = generate_release_lock(profile, source_root)

            self.assertEqual(before.profile_fingerprint, after.profile_fingerprint)
            self.assertEqual(before.source_audit.data_trees, after.source_audit.data_trees)

    def test_locked_tr_hash_mismatch_is_rejected(self) -> None:
        payload = self._synthetic_payload()
        payload["requiredInputs"][8]["sha256"] = "0" * 64
        profile = parse_profile(payload)
        with tempfile.TemporaryDirectory() as raw:
            source_root = Path(raw)
            self._write_source(source_root, profile)
            with (
                mock.patch("tools.tr_release.model.sha256_file", side_effect=self._fixture_hash),
                self.assertRaisesRegex(ValueError, "Input hash mismatch for tr-mainland-esm"),
            ):
                generate_release_lock(profile, source_root)

    def test_unexpected_mounted_content_plugin_is_rejected(self) -> None:
        profile = parse_profile(self._synthetic_payload())
        with tempfile.TemporaryDirectory() as raw:
            source_root = Path(raw)
            self._write_source(source_root, profile)
            unexpected = (
                source_root
                / profile.directory_by_id["tamriel-rebuilt-core"].path
                / "OptionalPatch.esp"
            )
            unexpected.write_bytes(b"unexpected")
            with (
                mock.patch("tools.tr_release.model.sha256_file", side_effect=self._fixture_hash),
                self.assertRaisesRegex(ValueError, "Unexpected mounted release input"),
            ):
                generate_release_lock(profile, source_root)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_source_tree_rejects_symlinks_even_when_the_target_is_regular(self) -> None:
        profile = parse_profile(self._synthetic_payload())
        with tempfile.TemporaryDirectory() as raw:
            source_root = Path(raw)
            self._write_source(source_root, profile)
            tr_root = source_root / profile.directory_by_id["tamriel-rebuilt-core"].path
            (tr_root / "link.dds").symlink_to(tr_root / "TR_Mainland.esm")
            with (
                mock.patch("tools.tr_release.model.sha256_file", side_effect=self._fixture_hash),
                self.assertRaisesRegex(ValueError, "cannot contain symlinks"),
            ):
                generate_release_lock(profile, source_root)

    def test_source_tree_rejects_casefold_collisions_when_filesystem_supports_them(self) -> None:
        profile = parse_profile(self._synthetic_payload())
        with tempfile.TemporaryDirectory() as raw:
            source_root = Path(raw)
            self._write_source(source_root, profile)
            td_root = source_root / profile.directory_by_id["tamriel-data"].path
            candidates = (
                ("Foo.dds", "foo.dds"),
                ("Straße.dds", "STRASSE.dds"),
                ("Σ.dds", "ς.dds"),
            )
            for index, (first_name, second_name) in enumerate(candidates):
                collision_root = td_root / f"Collision-{index}"
                collision_root.mkdir()
                first = collision_root / first_name
                second = collision_root / second_name
                first.write_bytes(b"first")
                try:
                    second.write_bytes(b"second")
                except FileExistsError:
                    continue
                if first.samefile(second):
                    continue
                with (
                    mock.patch(
                        "tools.tr_release.model.sha256_file", side_effect=self._fixture_hash
                    ),
                    self.assertRaisesRegex(ValueError, "Case-insensitive data-tree collision"),
                ):
                    generate_release_lock(profile, source_root)
                return

            original_casefold = tr_model._casefold_key

            def forced_collision(value: str) -> str:
                if value in {"Tamriel_Data.esm", "Tamriel_Data.omwscripts"}:
                    return "forced-release-file-collision"
                return original_casefold(value)

            with (
                mock.patch("tools.tr_release.model._casefold_key", side_effect=forced_collision),
                mock.patch("tools.tr_release.model.sha256_file", side_effect=self._fixture_hash),
                self.assertRaisesRegex(ValueError, "Case-insensitive data-tree collision"),
            ):
                generate_release_lock(profile, source_root)


class CanonicalAndTopologyTests(unittest.TestCase):
    def test_canonical_json_hash_is_order_independent_and_rejects_nan(self) -> None:
        first = {"z": [3, 2, 1], "a": {"é": "Тест"}}
        second = {"a": {"é": "Тест"}, "z": [3, 2, 1]}
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(canonical_json_sha256(first), canonical_json_sha256(second))
        with self.assertRaisesRegex(ValueError, "canonical JSON"):
            canonical_json_bytes({"invalid": float("nan")})

    def test_land_topology_derives_extent_tiles_adjacencies_shards_and_probes(self) -> None:
        cells = ((0, 0), (1, 0), (2, 0), (3, 0), (0, 1))
        topology = derive_land_topology(cells, probe_count=16)

        self.assertEqual(topology.extent, (0, 0, 4 * 8192, 2 * 8192))
        self.assertEqual(topology.origin, (0, 2 * 8192))
        self.assertEqual(topology.effective_cells, 5)
        self.assertEqual(topology.zooms[0].tile_count, 1)
        self.assertEqual(topology.zooms[6].tile_count, 2)
        self.assertEqual(topology.zooms[7].tile_count, 5)
        self.assertEqual(topology.zooms[7].east_adjacencies, 3)
        self.assertEqual(topology.zooms[7].north_adjacencies, 1)
        self.assertEqual(topology.shard_centers, ((0, 0), (3, 0)))
        self.assertEqual(topology.native_cross_shard_adjacencies, 1)
        self.assertEqual(topology.probes, ("7/1/1:east:7/2/1",))
        self.assertEqual(topology.to_dict()["totalTiles"], topology.total_tiles)

    def test_land_topology_is_order_independent_and_strict_about_cells(self) -> None:
        cells = ((-2, 3), (0, 0), (4, -1), (1, 0))
        self.assertEqual(
            derive_land_topology(cells).to_dict(),
            derive_land_topology(reversed(cells)).to_dict(),
        )
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            derive_land_topology(((0, 0), (0, 0)))
        with self.assertRaisesRegex(ValueError, r"\(int, int\)"):
            derive_land_topology(((0, True),))
        with self.assertRaisesRegex(ValueError, "At least one"):
            derive_land_topology(())


if __name__ == "__main__":
    unittest.main()
