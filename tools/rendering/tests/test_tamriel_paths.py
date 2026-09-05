from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.rendering import tamriel


class TamrielWorkspaceTests(unittest.TestCase):
    def test_tracked_work_directory_is_rejected_before_profile_write(self) -> None:
        args = tamriel._parser().parse_args(["check", "--work-root", str(tamriel.REPO_ROOT / "tools")])
        with mock.patch.object(tamriel, "prepare_profile") as prepare:
            with self.assertRaisesRegex(ValueError, "inside repository local-data"):
                tamriel.run(args)
        prepare.assert_not_called()

    def test_ignored_work_directory_cannot_overlap_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            inputs = root / "local-data/inputs"
            args = tamriel._parser().parse_args([
                "check", "--source-root", str(inputs), "--work-root", str(inputs / "output"),
            ])
            with mock.patch.object(tamriel, "REPO_ROOT", root), mock.patch.object(tamriel, "prepare_profile") as prepare:
                with self.assertRaisesRegex(ValueError, "separate from input"):
                    tamriel.run(args)
            prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
