from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.tr_release.cli import _assert_future_dataset_id


class CliIdentityTests(unittest.TestCase):
    def test_future_identity_is_rejected_before_expensive_release_work(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            index = Path(raw) / "index.json"
            index.write_text(
                json.dumps(
                    {
                        "datasets": [
                            {"datasetId": "original-goty-hd"},
                            {"datasetId": "poison-song-26.08"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            _assert_future_dataset_id("tamriel-rebuilt-27.01", index)
            with self.assertRaisesRegex(ValueError, "already active.*new versioned id"):
                _assert_future_dataset_id("poison-song-26.08", index)

    def test_malformed_active_index_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            index = Path(raw) / "index.json"
            index.write_text('{"datasets":[]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Original.*exactly one TR"):
                _assert_future_dataset_id("tamriel-rebuilt-27.01", index)


if __name__ == "__main__":
    unittest.main()
