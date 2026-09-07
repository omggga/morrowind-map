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

    def test_smoke_separates_producers_and_preserves_existing_receipts(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.tr_release import cli
        from tools.openmw_renderer.production import ProductionProvenance, publish_provenance_receipt

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            legacy = root / "smoke/cyrodiil/anvil/provenance.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text('{"old":true}')
            context = SimpleNamespace(workspace=root, dataset_id="cyrodiil", repo_root=root,
                source_root=root / "inputs", profile=SimpleNamespace(smoke_centers=(SimpleNamespace(id="anvil", cell=(-120, -57)),)))
            outputs = []
            for fingerprint in ("a" * 64, "b" * 64, "a" * 64):
                provenance = ProductionProvenance(fingerprint, {"provenanceFingerprint": fingerprint})
                def smoke(argv):
                    output = Path(argv[argv.index("--output") + 1])
                    output.mkdir(parents=True, exist_ok=True)
                    publish_provenance_receipt(output, provenance)
                    outputs.append(output)
                    self.assertIn("--center=-120,-57", argv)
                    self.assertEqual(argv[argv.index("--provenance-fingerprint") + 1], fingerprint)
                    return 0
                production = SimpleNamespace(resolve_production_provenance=lambda **kwargs: provenance, main=smoke)
                with patch.object(cli, "_context", return_value=context), \
                     patch.object(cli, "_activate_pipeline", return_value=SimpleNamespace(production=production)):
                    self.assertEqual(cli._command_renderer_smoke(SimpleNamespace(control="anvil")), 0)
            self.assertNotEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[0], outputs[2])
            self.assertEqual(legacy.read_text(), '{"old":true}')

    def test_malformed_active_index_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            index = Path(raw) / "index.json"
            index.write_text('{"datasets":[]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "two to five maps including Original"):
                _assert_future_dataset_id("tamriel-rebuilt-27.01", index)


if __name__ == "__main__":
    unittest.main()
