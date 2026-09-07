from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from typing import Iterable

from tools.catalog_pipeline.catalog import build_catalog, entrance_id, place_id
from tools.catalog_pipeline.tes3 import (
    CELL_SIZE,
    CellKey,
    PluginInput,
    ReferenceKey,
    canonical_ref_id,
    merge_plugins,
)


_ABSENT = object()


def subrecord(tag: bytes, payload: bytes) -> bytes:
    return struct.pack("<4sI", tag, len(payload)) + payload


def record(tag: bytes, payload: bytes) -> bytes:
    return struct.pack("<4sIII", tag, len(payload), 0, 0) + payload


def ignored_record(value: bytes) -> bytes:
    result = bytearray(value)
    struct.pack_into("<I", result, 12, 0x1000)
    return bytes(result)


def zstring(value: str) -> bytes:
    return value.encode("cp1252") + b"\0"


def tes3_header(masters: Iterable[tuple[str, int]] = ()) -> bytes:
    payload = b""
    for name, advertised_size in masters:
        payload += subrecord(b"MAST", zstring(name))
        payload += subrecord(b"DATA", struct.pack("<Q", advertised_size))
    return record(b"TES3", payload)


def door(record_id: str, name: str = "", *, deleted: bool = False) -> bytes:
    payload = subrecord(b"NAME", zstring(record_id))
    if name:
        payload += subrecord(b"FNAM", zstring(name))
    if deleted:
        payload += subrecord(b"DELE", b"\0\0\0")
    return record(b"DOOR", payload)


def land(grid: tuple[int, int], *, deleted: bool = False) -> bytes:
    payload = subrecord(b"INTV", struct.pack("<ii", *grid))
    if deleted:
        payload += subrecord(b"DELE", b"\0\0\0")
    return record(b"LAND", payload)


def frmr(
    raw_index: int,
    *,
    base_id: str | object = _ABSENT,
    position: tuple[float, float, float] | None = None,
    door_destination: tuple[float, float, float] | None = None,
    destination_cell: str | object = _ABSENT,
    deleted: bool = False,
) -> bytes:
    payload = subrecord(b"FRMR", struct.pack("<I", raw_index))
    if base_id is not _ABSENT:
        payload += subrecord(b"NAME", zstring(str(base_id)))
    if position is not None:
        payload += subrecord(b"DATA", struct.pack("<6f", *position, 0.0, 0.0, 0.0))
    if door_destination is not None:
        payload += subrecord(
            b"DODT",
            struct.pack("<6f", *door_destination, 0.0, 0.0, 0.0),
        )
    if destination_cell is not _ABSENT:
        payload += subrecord(b"DNAM", zstring(str(destination_cell)))
    if deleted:
        payload += subrecord(b"DELE", b"\0\0\0")
    return payload


def moved_frmr(
    moved_raw_index: int,
    target_grid: tuple[int, int],
    *,
    frmr_raw_index: int | None = None,
    base_id: str | object = _ABSENT,
    position: tuple[float, float, float] | None = None,
    door_destination: tuple[float, float, float] | None = None,
    destination_cell: str | object = _ABSENT,
    deleted: bool = False,
) -> bytes:
    return (
        subrecord(b"MVRF", struct.pack("<I", moved_raw_index))
        + subrecord(b"CNDT", struct.pack("<ii", *target_grid))
        + frmr(
            moved_raw_index if frmr_raw_index is None else frmr_raw_index,
            base_id=base_id,
            position=position,
            door_destination=door_destination,
            destination_cell=destination_cell,
            deleted=deleted,
        )
    )


def cell(
    name: str,
    *,
    grid: tuple[int, int] = (0, 0),
    interior: bool = False,
    region: str | object = _ABSENT,
    references: Iterable[bytes] = (),
    deleted: bool = False,
) -> bytes:
    flags = 0x01 if interior else 0
    payload = subrecord(b"NAME", zstring(name))
    payload += subrecord(b"DATA", struct.pack("<Iii", flags, *grid))
    if region is not _ABSENT:
        payload += subrecord(b"RGNN", zstring(str(region)))
    if deleted:
        payload += subrecord(b"DELE", b"\0\0\0")
    payload += b"".join(references)
    return record(b"CELL", payload)


def write_plugin(
    root: Path,
    name: str,
    records: Iterable[bytes] = (),
    *,
    masters: Iterable[tuple[str, int]] = (),
) -> PluginInput:
    path = root / name
    content = tes3_header(masters) + b"".join(records)
    path.write_bytes(content)
    return PluginInput(name=name, path=path, sha256=hashlib.sha256(content).hexdigest())


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class Tes3MergeContractTests(unittest.TestCase):
    def test_master_ordinal_resolves_origin_identity_not_load_order_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = write_plugin(
                root,
                "Base.esm",
                [cell("", references=[frmr(0x42, base_id="base_door")])],
            )
            unrelated = write_plugin(root, "Unrelated.esm")
            patch = write_plugin(
                root,
                "Patch.esp",
                [cell("", references=[frmr(0x02000042, base_id="patched_door")])],
                masters=(("Unrelated.esm", 111), ("Base.esm", 222)),
            )

            world = merge_plugins((base, unrelated, patch))

        key = ReferenceKey(0, 0x42)
        self.assertEqual(set(world.references), {key})
        self.assertEqual(world.references[key].origin_plugin, "Base.esm")
        self.assertEqual(world.references[key].winning_plugin, "Patch.esp")
        self.assertEqual(world.references[key].base_id, "patched_door")
        self.assertEqual(
            [master.resolved_plugin_index for master in world.masters[2]],
            [1, 0],
        )
        self.assertEqual(
            [master.advertised_size for master in world.masters[2]],
            [111, 222],
        )

    def test_record_identity_folds_ascii_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = write_plugin(
                root,
                "World.esm",
                [
                    door("ÄDoor", "capital umlaut"),
                    door("äDoor", "lower umlaut"),
                    door("Plain", "old"),
                    door("pLAIN", "new"),
                ],
            )
            world = merge_plugins((plugin,))

        self.assertEqual(canonical_ref_id("ASCII-Id"), "ascii-id")
        self.assertEqual(canonical_ref_id("ÄDoor"), "Ädoor")
        self.assertEqual(canonical_ref_id("äDoor"), "ädoor")
        self.assertNotEqual(canonical_ref_id("ÄDoor"), canonical_ref_id("äDoor"))
        self.assertEqual(set(world.doors), {"Ädoor", "ädoor", "plain"})
        self.assertEqual(world.doors["plain"].name, "new")

    def test_ignored_records_do_not_participate_in_effective_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = write_plugin(
                root,
                "World.esm",
                [
                    door("Gate", "live"),
                    ignored_record(door("gate", "ignored override")),
                    land((0, 0)),
                    ignored_record(land((0, 0), deleted=True)),
                    cell("Live", grid=(0, 0)),
                    ignored_record(cell("Ignored", grid=(0, 0))),
                ],
            )
            world = merge_plugins((plugin,))

        self.assertEqual(world.doors["gate"].name, "live")
        self.assertEqual(world.land_sources[(0, 0)], "World.esm")
        self.assertEqual(world.cells[CellKey.exterior(0, 0)].name, "Live")
        self.assertEqual(world.counts["ignoredRecords"], 3)

    def test_door_override_delete_and_resurrection_follow_exact_load_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = write_plugin(root, "Base.esm", [door("Gate", "base")])
            override = write_plugin(
                root,
                "Override.esp",
                [door("gATE", "override")],
                masters=(("Base.esm", 1),),
            )
            deletion = write_plugin(
                root,
                "Delete.esp",
                [door("GATE", deleted=True)],
                masters=(("Base.esm", 1),),
            )
            resurrection = write_plugin(
                root,
                "Resurrect.esp",
                [door("gate", "resurrected")],
                masters=(("Base.esm", 1),),
            )

            after_override = merge_plugins((base, override))
            after_delete = merge_plugins((base, override, deletion))
            after_resurrection = merge_plugins((base, override, deletion, resurrection))

        self.assertEqual(after_override.doors["gate"].name, "override")
        self.assertEqual(after_override.doors["gate"].plugin, "Override.esp")
        self.assertNotIn("gate", after_delete.doors)
        self.assertEqual(after_resurrection.doors["gate"].name, "resurrected")
        self.assertEqual(after_resurrection.doors["gate"].plugin, "Resurrect.esp")

    def test_cell_metadata_override_preserves_optional_region_and_accumulates_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = write_plugin(
                root,
                "Base.esm",
                [
                    cell(
                        "Old Port",
                        region="Base Region",
                        references=[frmr(1, base_id="door_a", position=(100.0, 200.0, 0.0))],
                    )
                ],
            )
            patch = write_plugin(
                root,
                "Patch.esp",
                [
                    cell(
                        "New Port",
                        references=[frmr(2, base_id="door_b", position=(300.0, 400.0, 0.0))],
                    )
                ],
                masters=(("Base.esm", 1),),
            )
            world = merge_plugins((base, patch))

        exterior = world.cells[CellKey.exterior(0, 0)]
        self.assertEqual(exterior.name, "New Port")
        self.assertEqual(exterior.region, "Base Region")
        self.assertEqual(exterior.first_plugin, "Base.esm")
        self.assertEqual(exterior.plugin, "Patch.esp")
        self.assertEqual(exterior.historical_names, {"Old Port", "New Port"})
        self.assertEqual(
            set(world.references),
            {ReferenceKey(0, 1), ReferenceKey(1, 2)},
        )

    def test_cell_tombstone_drops_old_contexts_and_later_record_resurrects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = write_plugin(
                root,
                "Base.esm",
                [cell("Base", references=[frmr(1, base_id="old")])],
            )
            deletion = write_plugin(
                root,
                "Delete.esp",
                [cell("Deleted", deleted=True)],
                masters=(("Base.esm", 1),),
            )
            resurrection = write_plugin(
                root,
                "Resurrect.esp",
                [cell("Restored", references=[frmr(2, base_id="new")])],
                masters=(("Base.esm", 1),),
            )

            deleted_world = merge_plugins((base, deletion))
            restored_world = merge_plugins((base, deletion, resurrection))

        self.assertNotIn(CellKey.exterior(0, 0), deleted_world.cells)
        self.assertEqual(deleted_world.references, {})
        restored = restored_world.cells[CellKey.exterior(0, 0)]
        self.assertEqual(restored.name, "Restored")
        self.assertEqual(restored.first_plugin, "Resurrect.esp")
        self.assertEqual(set(restored_world.references), {ReferenceKey(2, 2)})

    def test_frmr_is_full_replacement_with_delete_and_resurrection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = write_plugin(
                root,
                "Base.esm",
                [
                    cell(
                        "",
                        references=[
                            frmr(
                                0x11,
                                base_id="door_a",
                                position=(10.0, 20.0, 0.0),
                                door_destination=(1.0, 2.0, 3.0),
                                destination_cell="Target A",
                            )
                        ],
                    )
                ],
            )
            replacement = write_plugin(
                root,
                "Replace.esp",
                [cell("", references=[frmr(0x01000011, base_id="door_b")])],
                masters=(("Base.esm", 1),),
            )
            deletion = write_plugin(
                root,
                "Delete.esp",
                [cell("", references=[frmr(0x01000011, deleted=True)])],
                masters=(("Base.esm", 1),),
            )
            resurrection = write_plugin(
                root,
                "Resurrect.esp",
                [
                    cell(
                        "",
                        references=[
                            frmr(
                                0x01000011,
                                base_id="door_c",
                                position=(30.0, 40.0, 0.0),
                                door_destination=(4.0, 5.0, 6.0),
                                destination_cell="Target C",
                            )
                        ],
                    )
                ],
                masters=(("Base.esm", 1),),
            )
            replaced_world = merge_plugins((base, replacement))
            deleted_world = merge_plugins((base, replacement, deletion))
            restored_world = merge_plugins((base, replacement, deletion, resurrection))

        key = ReferenceKey(0, 0x11)
        replaced = replaced_world.references[key]
        self.assertEqual(replaced.base_id, "door_b")
        self.assertIsNone(replaced.position)
        self.assertIsNone(replaced.door_destination)
        self.assertEqual(replaced.destination_cell, "")
        deleted = deleted_world.references[key]
        self.assertTrue(deleted.deleted)
        self.assertEqual(deleted.base_id, "")
        restored = restored_world.references[key]
        self.assertFalse(restored.deleted)
        self.assertEqual(restored.origin_plugin, "Base.esm")
        self.assertEqual(restored.winning_plugin, "Resurrect.esp")
        self.assertEqual(restored.base_id, "door_c")
        self.assertEqual(restored.position, (30.0, 40.0, 0.0))

    def test_mvrf_cndt_moves_same_identity_and_rejects_mismatched_frmr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = write_plugin(
                root,
                "Base.esm",
                [cell("", references=[frmr(0x22, base_id="door")])],
            )
            move = write_plugin(
                root,
                "Move.esp",
                [
                    cell(
                        "",
                        references=[
                            moved_frmr(
                                0x01000022,
                                (2, -1),
                                base_id="door",
                                position=(2 * CELL_SIZE + 100.0, -CELL_SIZE + 200.0, 0.0),
                            )
                        ],
                    )
                ],
                masters=(("Base.esm", 1),),
            )
            mismatch = write_plugin(
                root,
                "Mismatch.esp",
                [
                    cell(
                        "",
                        references=[
                            moved_frmr(
                                0x01000022,
                                (2, -1),
                                frmr_raw_index=0x01000023,
                            )
                        ],
                    )
                ],
                masters=(("Base.esm", 1),),
            )

            world = merge_plugins((base, move))
            with self.assertRaisesRegex(ValueError, "MVRF/FRMR identity mismatch"):
                merge_plugins((base, mismatch))

        moved = world.references[ReferenceKey(0, 0x22)]
        self.assertTrue(moved.moved)
        self.assertEqual(moved.origin_plugin, "Base.esm")
        self.assertEqual(moved.source_cell, CellKey.exterior(0, 0))
        self.assertEqual(moved.effective_cell, CellKey.exterior(2, -1))
        self.assertEqual(moved.exterior_cell, (2, -1))


class CatalogContractTests(unittest.TestCase):
    DATASET = "synthetic"
    SNAPSHOT = "synthetic:snapshot"
    REGIONS = {"World.esm": "vvardenfell", "Patch.esp": "vvardenfell"}

    def _grouping_stack(self, root: Path) -> tuple[PluginInput, PluginInput]:
        target = "Ald-ruhn, Manor District"
        world = write_plugin(
            root,
            "World.esm",
            [
                door("door_a", "Wooden Door"),
                door("door_b", "Stone Door"),
                land((0, 0)),
                land((1, 0)),
                cell(target, interior=True),
                cell(
                    "",
                    grid=(0, 0),
                    references=[
                        frmr(
                            1,
                            base_id="door_a",
                            position=(100.0, 200.0, 0.0),
                            door_destination=(10.0, 20.0, 0.0),
                            destination_cell=target,
                        )
                    ],
                ),
                cell(
                    "",
                    grid=(1, 0),
                    references=[
                        frmr(
                            2,
                            base_id="door_b",
                            position=(CELL_SIZE + 300.0, 400.0, 0.0),
                            door_destination=(30.0, 40.0, 0.0),
                            destination_cell=target,
                        )
                    ],
                ),
            ],
        )
        patch = write_plugin(
            root,
            "Patch.esp",
            [
                cell(
                    "",
                    grid=(0, 0),
                    references=[
                        frmr(
                            0x01000001,
                            base_id="door_a",
                            position=(500.0, 600.0, 0.0),
                            door_destination=(50.0, 60.0, 0.0),
                            destination_cell=target,
                        )
                    ],
                )
            ],
            masters=(("World.esm", 1),),
        )
        return world, patch

    def test_groups_multiple_entrances_and_ids_survive_reference_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            world_plugin, patch = self._grouping_stack(root)
            before = build_catalog(
                merge_plugins((world_plugin,)),
                dataset_id=self.DATASET,
                snapshot_id=self.SNAPSHOT,
                plugin_regions=self.REGIONS,
            )
            after = build_catalog(
                merge_plugins((world_plugin, patch)),
                dataset_id=self.DATASET,
                snapshot_id=self.SNAPSHOT,
                plugin_regions=self.REGIONS,
            )

        self.assertEqual(before.counts["interiorPlaces"], 1)
        self.assertEqual(before.counts["entrances"], 2)
        self.assertEqual(before.counts["multiEntrancePlaces"], 1)
        self.assertEqual(len(before.locations["places"]), 1)
        before_place = before.locations["places"][0]
        after_place = after.locations["places"][0]
        self.assertEqual(before_place["id"], after_place["id"])
        self.assertEqual(
            before_place["id"],
            place_id(self.DATASET, "interior", canonical_ref_id("Ald-ruhn, Manor District")),
        )
        before_ids = {entry["id"] for entry in before_place["entrances"]}
        after_ids = {entry["id"] for entry in after_place["entrances"]}
        self.assertEqual(before_ids, after_ids)
        self.assertIn(entrance_id(self.DATASET, "World.esm", 1), before_ids)
        self.assertEqual(before.english["places"][0]["name"], "Ald-ruhn, Manor District")
        self.assertEqual(before_place["regionId"], "vvardenfell")

    def test_province_scope_keeps_dependency_doors_but_excludes_base_map_places(self) -> None:
        for plugin_name, region in (("Cyr_Main.esm", "cyrodiil"), ("Sky_Main.esm", "skyrim")):
            with self.subTest(region=region), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                base, patch = self._grouping_stack(root)
                province = write_plugin(root, plugin_name, [
                    land((3, 3)), cell("Anvil Shop", interior=True),
                    cell("Anvil", grid=(3, 3), references=[frmr(
                        1, base_id="door_a", position=(3 * CELL_SIZE + 100.0, 3 * CELL_SIZE + 100.0, 0.0),
                        door_destination=(0.0, 0.0, 0.0), destination_cell="Anvil Shop",
                    )]),
                ], masters=((base.name, base.path.stat().st_size),))
                ocean = write_plugin(root, "Ocean.esp", [cell("", grid=(-19, 15), references=[
                    frmr(1, base_id="door_a", position=(-19 * CELL_SIZE + 100.0, 15 * CELL_SIZE + 100.0, 0.0)),
                ])], masters=((base.name, base.path.stat().st_size),))
                world = merge_plugins((base, patch, province, ocean))
                regions = {**self.REGIONS, province.name: region, ocean.name: "vvardenfell"}
                full = build_catalog(world, dataset_id=self.DATASET, snapshot_id=self.SNAPSHOT, plugin_regions=regions)
                scoped = build_catalog(world, dataset_id=self.DATASET, snapshot_id=self.SNAPSHOT,
                                       plugin_regions=regions, allowed_regions=(region,))
                self.assertLess(scoped.counts["places"], full.counts["places"])
                self.assertEqual(scoped.counts["entrances"], 1)
                self.assertEqual(scoped.counts["namedExteriorPlaces"], 1)
                self.assertEqual({place["regionId"] for place in scoped.locations["places"]}, {region})
                self.assertNotEqual(scoped.policy_fingerprint, full.policy_fingerprint)

    def test_named_exterior_cells_use_eight_neighbor_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = write_plugin(
                root,
                "World.esm",
                [
                    land((0, 0)),
                    land((1, 1)),
                    land((3, 3)),
                    cell("Suran", grid=(0, 0)),
                    cell("Suran", grid=(1, 1)),
                    cell("Suran", grid=(3, 3)),
                ],
            )
            catalog = build_catalog(
                merge_plugins((plugin,)),
                dataset_id=self.DATASET,
                snapshot_id=self.SNAPSHOT,
                plugin_regions=self.REGIONS,
            )

        self.assertEqual(catalog.counts["namedExteriorCells"], 3)
        self.assertEqual(catalog.counts["namedExteriorPlaces"], 2)
        self.assertEqual(sorted(len(place["sources"]) for place in catalog.locations["places"]), [1, 2])
        expected_ids = {
            place_id(self.DATASET, "exterior", "suran\0" + "0,0"),
            place_id(self.DATASET, "exterior", "suran\0" + "3,3"),
        }
        self.assertEqual({place["id"] for place in catalog.locations["places"]}, expected_ids)

    def test_land_only_region_resolution_fails_closed_when_source_is_unmapped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = write_plugin(
                root,
                "World.esm",
                [land((4, -2)), cell("Remote Camp", grid=(4, -2))],
            )
            world = merge_plugins((plugin,))

        with self.assertRaisesRegex(ValueError, "has no region mapping"):
            build_catalog(
                world,
                dataset_id=self.DATASET,
                snapshot_id=self.SNAPSHOT,
                plugin_regions={},
            )

    def test_repeated_merge_and_build_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            world_plugin, patch = self._grouping_stack(root)
            first = build_catalog(
                merge_plugins((world_plugin, patch)),
                dataset_id=self.DATASET,
                snapshot_id=self.SNAPSHOT,
                plugin_regions=self.REGIONS,
            )
            second = build_catalog(
                merge_plugins((world_plugin, patch)),
                dataset_id=self.DATASET,
                snapshot_id=self.SNAPSHOT,
                plugin_regions=self.REGIONS,
            )

        self.assertEqual(canonical_json(first.locations), canonical_json(second.locations))
        self.assertEqual(canonical_json(first.english), canonical_json(second.english))
        self.assertEqual(first.counts, second.counts)
        self.assertEqual(first.dropped, second.dropped)
        self.assertEqual(first.gates, second.gates)
        self.assertEqual(first.policy_fingerprint, second.policy_fingerprint)


if __name__ == "__main__":
    unittest.main()
