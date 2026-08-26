from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from tools.data_pipeline.build_original import (
    assert_mim_layout,
    build_mim_import_region,
    canonical_position,
    canonical_solstheim_extent,
    mim_source_fingerprint,
)
from tools.data_pipeline.esm import extract_world_data
from tools.data_pipeline.mim import (
    classify_place,
    match_mim_progress,
    parse_mim_locations,
    parse_mim_markers,
    parse_mim_progress,
)


def subrecord(name: bytes, value: bytes) -> bytes:
    return name + struct.pack("<I", len(value)) + value


class MimParserTests(unittest.TestCase):
    def test_reads_cp1251_location_blocks_without_losing_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mwmain.gdb"
            path.write_text(
                "loc\r\n nm = Балмора\r\n pc = 19\r\n dl = 0\r\n pd = -20000,-12000\r\nend\r\n",
                encoding="cp1251",
            )

            locations = parse_mim_locations(path)

        self.assertEqual(len(locations), 1)
        self.assertEqual(locations[0].name, "Балмора")
        self.assertEqual(locations[0].position, (-20_000, -12_000))
        self.assertEqual(classify_place(locations[0].category, locations[0].name), "settlement")
        self.assertEqual(classify_place(None, "Balmora, Guild of Fighters"), "guild")

    def test_reads_cp1251_progress_and_markers_without_a_final_newline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user_path = root / "user.gdb"
            marker_path = root / "markers.gdb"
            user_path.write_bytes(
                (
                    "loc\r\n"
                    "   nm = Лагерь Ашаману, Юрта Кауши\r\n"
                    "   status = 3\r\n"
                    "   note = ф\r\n"
                    "end\r\n"
                    "loc\r\n"
                    "   nm = Башня\r\n"
                    "   status = 2\r\n"
                    "   note = \r\n"
                    "end"
                ).encode("cp1251")
            )
            marker_path.write_bytes(
                (
                    "marker\r\n"
                    "   text = Дом с силовым полем\r\n"
                    "   pos = 59590,184171\r\n"
                    "end"
                ).encode("cp1251")
            )

            progress = parse_mim_progress(user_path)
            markers = parse_mim_markers(marker_path)

        self.assertEqual(
            [(record.name, record.status, record.note) for record in progress],
            [
                ("Лагерь Ашаману, Юрта Кауши", "visited", "ф"),
                ("Башня", "active", ""),
            ],
        )
        self.assertEqual(markers[0].text, "Дом с силовым полем")
        self.assertEqual(markers[0].position, (59_590, 184_171))

    def test_rejects_progress_count_and_ordinal_name_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mwmain_path = root / "mwmain.gdb"
            user_path = root / "user.gdb"
            mwmain_path.write_text(
                "loc\r\n nm = Башня\r\n pc = 20\r\n dl = 4\r\n pd = 1,2\r\nend\r\n"
                "loc\r\n nm = Храм\r\n pc = 11\r\n dl = 2\r\n pd = 3,4\r\nend\r\n",
                encoding="cp1251",
            )
            locations = parse_mim_locations(mwmain_path)

            fixtures = (
                (
                    "count",
                    "loc\r\n nm = Башня\r\n status = 1\r\n note = \r\nend\r\n",
                    "count mismatch",
                ),
                (
                    "name",
                    "loc\r\n nm = Башня\r\n status = 1\r\n note = \r\nend\r\n"
                    "loc\r\n nm = Другое имя\r\n status = 3\r\n note = \r\nend\r\n",
                    "ordinal 1",
                ),
            )
            for label, user_text, message in fixtures:
                with self.subTest(label=label):
                    user_path.write_text(user_text, encoding="cp1251")
                    progress = parse_mim_progress(user_path)
                    with self.assertRaisesRegex(ValueError, message):
                        match_mim_progress("vvardenfell", locations, progress)

    def test_duplicate_names_are_joined_by_ordinal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mwmain_path = root / "mwmain.gdb"
            user_path = root / "user.gdb"
            marker_path = root / "markers.gdb"
            mwmain_path.write_text(
                "loc\r\n nm = Башня\r\n pc = 20\r\n dl = 4\r\n pd = 1,2\r\nend\r\n"
                "loc\r\n nm = Башня\r\n pc = 20\r\n dl = 4\r\n pd = 3,4\r\nend\r\n",
                encoding="cp1251",
            )
            user_path.write_text(
                "loc\r\n nm = Башня\r\n status = 1\r\n note = \r\nend\r\n"
                "loc\r\n nm = Башня\r\n status = 3\r\n note = готово\r\nend\r\n",
                encoding="cp1251",
            )
            marker_path.write_bytes(b"")

            progress, markers, audit = build_mim_import_region(
                "vvardenfell",
                parse_mim_locations(mwmain_path),
                user_path,
                marker_path,
            )

        self.assertEqual(
            progress,
            [
                {
                    "placeId": "original-goty.vvardenfell.mim-0000",
                    "status": "unvisited",
                    "note": "",
                },
                {
                    "placeId": "original-goty.vvardenfell.mim-0001",
                    "status": "visited",
                    "note": "готово",
                },
            ],
        )
        self.assertEqual(markers, [])
        self.assertEqual(audit["statuses"], {"unvisited": 1, "active": 0, "visited": 1})

    def test_marker_ids_are_deterministic_and_use_the_region_georeference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user_path = root / "user.gdb"
            marker_path = root / "markers.gdb"
            user_path.write_bytes(b"")
            marker_path.write_bytes(
                (
                    "marker\r\n text = Marker\r\n pos = -125000,-130000\r\nend\r\n"
                    "marker\r\n text = Marker\r\n pos = -125000,-130000\r\nend"
                ).encode("cp1251")
            )

            first = build_mim_import_region(
                "solstheim", [], user_path, marker_path
            )[1]
            second = build_mim_import_region(
                "solstheim", [], user_path, marker_path
            )[1]
            marker_path.write_bytes(
                (
                    "marker\r\n text = New marker\r\n pos = 1,2\r\nend\r\n"
                    "marker\r\n text = Marker\r\n pos = -125000,-130000\r\nend\r\n"
                    "marker\r\n text = Marker\r\n pos = -125000,-130000\r\nend"
                ).encode("cp1251")
            )
            with_unrelated_prefix = build_mim_import_region(
                "solstheim", [], user_path, marker_path
            )[1]

        expected_digest = hashlib.sha256(
            "\0".join(
                ("mim-progress-v2", "solstheim", "Marker", "-125000,-130000", "0")
            ).encode()
        ).hexdigest()[:16]
        self.assertEqual(first, second)
        self.assertEqual(
            [marker["id"] for marker in first],
            [marker["id"] for marker in with_unrelated_prefix[1:]],
        )
        self.assertEqual(first[0]["id"], f"original-goty.custom.mim-solstheim-{expected_digest}")
        self.assertNotEqual(first[0]["id"], first[1]["id"])
        self.assertEqual(first[0]["position"], [-229_547.327, 115_992.354])

    def test_rejects_a_changed_ordinal_layout_even_when_user_order_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mwmain.gdb"
            first_layout = (
                "loc\r\n nm = Башня\r\n pc = 20\r\n dl = 4\r\n pd = 1,2\r\nend\r\n"
                "loc\r\n nm = Храм\r\n pc = 11\r\n dl = 2\r\n pd = 3,4\r\nend\r\n"
            ).encode("cp1251")
            path.write_bytes(first_layout)
            expected = hashlib.sha256(first_layout).hexdigest()

            assert_mim_layout("vvardenfell", path, {"vvardenfell": expected})
            path.write_bytes(
                (
                    "loc\r\n nm = Храм\r\n pc = 11\r\n dl = 2\r\n pd = 3,4\r\nend\r\n"
                    "loc\r\n nm = Башня\r\n pc = 20\r\n dl = 4\r\n pd = 1,2\r\nend\r\n"
                ).encode("cp1251")
            )

            with self.assertRaisesRegex(ValueError, "layout SHA-256"):
                assert_mim_layout("vvardenfell", path, {"vvardenfell": expected})

    def test_rejects_unknown_status_and_malformed_marker_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user_path = root / "user.gdb"
            marker_path = root / "markers.gdb"
            user_path.write_text(
                "loc\r\n nm = Башня\r\n status = 4\r\n note = \r\nend\r\n",
                encoding="cp1251",
            )
            marker_path.write_text(
                "marker\r\n text = Marker\r\n pos = 1.5,2\r\nend\r\n",
                encoding="cp1251",
            )

            with self.assertRaisesRegex(ValueError, "Invalid status"):
                parse_mim_progress(user_path)
            with self.assertRaisesRegex(ValueError, "Invalid pos"):
                parse_mim_markers(marker_path)

    def test_source_fingerprint_includes_mapping_version_and_ignores_input_order(self) -> None:
        source_files = [
            {"path": "mim_morrowind/user.gdb", "sha256": "a" * 64},
            {"path": "mim_morrowind/mwmain.gdb", "sha256": "b" * 64},
        ]

        current = mim_source_fingerprint(source_files, "mim-progress-v1")

        self.assertEqual(
            current,
            mim_source_fingerprint(list(reversed(source_files)), "mim-progress-v1"),
        )
        self.assertNotEqual(
            current,
            mim_source_fingerprint(source_files, "mim-progress-v2"),
        )


class EsmParserTests(unittest.TestCase):
    def test_extracts_only_exterior_teleport_references(self) -> None:
        payload = b"".join(
            (
                subrecord(b"NAME", b"Balmora\0"),
                subrecord(b"DATA", struct.pack("<Iii", 2, -3, -2)),
                subrecord(b"FRMR", struct.pack("<I", 42)),
                subrecord(b"NAME", b"door_fixture\0"),
                subrecord(b"DNAM", b"Balmora, Fixture House\0"),
                subrecord(b"DATA", struct.pack("<6f", -20_000, -12_000, 0, 0, 0, 0)),
            )
        )
        record = b"CELL" + struct.pack("<III", len(payload), 0, 0) + payload
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Fixture.esm"
            path.write_bytes(record)

            world = extract_world_data(path)

        self.assertEqual(len(world.teleports), 1)
        self.assertEqual(world.teleports[0].destination, "Balmora, Fixture House")
        self.assertEqual(world.teleports[0].exterior_cell, (-3, -2))
        self.assertEqual(world.named_exterior_cells[0].name, "Balmora")


class GeoreferenceTests(unittest.TestCase):
    def test_keeps_vvardenfell_and_maps_bloodmoon_logical_space_to_tes3(self) -> None:
        self.assertEqual(canonical_position("vvardenfell", (-20_000, -12_000)), (-20_000, -12_000))
        x, y = canonical_position("solstheim", (-125_000, -130_000))
        self.assertAlmostEqual(x, -229_547.3274585)
        self.assertAlmostEqual(y, 115_992.353777)

    def test_uses_the_exact_bloodmoon_cell_grid_extent_for_the_raster(self) -> None:
        self.assertEqual(
            canonical_solstheim_extent(),
            (-229_376.0, 114_688.0, -131_072.0, 237_568.0),
        )


if __name__ == "__main__":
    unittest.main()
