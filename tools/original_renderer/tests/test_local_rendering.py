from __future__ import annotations

import argparse
import configparser
import tempfile
import unittest
from pathlib import Path

from tools.original_renderer.profile import render_settings_cfg
from tools.rendering.original import REPO_ROOT, _work, settings_text, snapshot_identity


class LocalOriginalProfileTests(unittest.TestCase):
    def test_default_settings_preserve_the_existing_render_profile(self) -> None:
        self.assertEqual(settings_text(None), render_settings_cfg())

    def test_local_settings_override_retains_unspecified_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.cfg"
            settings.write_text("[Video]\nantialiasing = 4\n")
            effective = configparser.ConfigParser(interpolation=None)
            effective.read_string(settings_text(settings))
        self.assertEqual(effective.get("Video", "antialiasing"), "4")
        self.assertEqual(effective.get("Map", "local map resolution"), "512")
        self.assertEqual(effective.get("Cells", "preload enabled"), "false")

    def test_override_cannot_change_the_published_tile_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.cfg"
            settings.write_text("[Map]\nlocal map resolution = 1024\n")
            with self.assertRaisesRegex(ValueError, "must remain 512"):
                settings_text(settings)

    def test_settings_reject_symlinks_and_malformed_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.cfg"
            settings.write_text("[Video]\nantialiasing = 4\nantialiasing = 8\n")
            with self.assertRaises(configparser.DuplicateOptionError):
                settings_text(settings)
            link = Path(directory) / "linked.cfg"
            link.symlink_to(settings)
            with self.assertRaisesRegex(ValueError, "regular UTF-8 file"):
                settings_text(link)

    def test_snapshot_changes_with_either_settings_profile_or_producer(self) -> None:
        original = snapshot_identity("a" * 64, "b" * 64)
        self.assertEqual(original, snapshot_identity("a" * 64, "b" * 64))
        self.assertNotEqual(original, snapshot_identity("c" * 64, "b" * 64))
        self.assertNotEqual(original, snapshot_identity("a" * 64, "d" * 64))
        self.assertRegex(original, r"^original:goty:[0-9a-f]{16}$")

    def test_work_output_cannot_write_to_tracked_application(self) -> None:
        args = argparse.Namespace(work_root=REPO_ROOT / "apps/web/public")
        with self.assertRaisesRegex(ValueError, "under repository local-data"):
            _work(args, "original:goty:" + "a" * 16)
        args.work_root = REPO_ROOT / "local-data/rendering/original"
        self.assertEqual(_work(args, "original:goty:" + "a" * 16), args.work_root / ("a" * 16))


if __name__ == "__main__":
    unittest.main()
