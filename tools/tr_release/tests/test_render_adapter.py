from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tools.rendering import tamriel
from tools.tr_release import cli


class LocalRenderAdapterTests(unittest.TestCase):
    def test_active_release_profile_becomes_local_without_relaxing_source_contracts(self) -> None:
        original = tamriel.REPO_ROOT / "config/tr-release.json"
        before = original.read_bytes()
        current = json.loads(before)
        with tempfile.TemporaryDirectory() as raw:
            profile = tamriel.prepare_profile(original, Path(raw), None)
            candidate = json.loads(profile.read_bytes())
            self.assertEqual(candidate["datasetId"], current["datasetId"] + "-local")
            self.assertNotIn("adoptedSnapshotId", candidate)
            self.assertEqual(candidate["requiredInputs"], current["requiredInputs"])
            self.assertEqual(candidate["masterSizeExceptions"], current["masterSizeExceptions"])
            self.assertEqual(
                {item["id"]: item["path"] for item in candidate["dataDirectories"]},
                tamriel.NORMALIZED_DIRECTORIES,
            )
            self.assertTrue(all(item["relativePath"].startswith("tamriel-rebuilt/") for item in candidate["excludedOptionalModules"]))
        self.assertEqual(original.read_bytes(), before)

    def test_future_profile_keeps_its_identity_and_explicitly_unpinned_mod(self) -> None:
        value = json.loads((tamriel.REPO_ROOT / "config/tr-release.json").read_bytes())
        value["datasetId"] = "tamriel-rebuilt-27.01"
        value.pop("adoptedSnapshotId")
        next(item for item in value["requiredInputs"] if item["id"] == "tr-mainland-esm").pop("sha256")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "future.json"
            source.write_text(json.dumps(value))
            profile = tamriel.prepare_profile(source, root / "work", None)
            candidate = json.loads(profile.read_bytes())
            self.assertEqual(candidate["datasetId"], value["datasetId"])
            self.assertNotIn("sha256", next(item for item in candidate["requiredInputs"] if item["id"] == "tr-mainland-esm"))

    def test_explicit_active_identity_is_rejected(self) -> None:
        original = tamriel.REPO_ROOT / "config/tr-release.json"
        active = json.loads(original.read_bytes())["datasetId"]
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(ValueError, "new dataset ID"):
                tamriel.prepare_profile(original, Path(raw), active)

    def test_context_redirects_every_output_without_changing_repository_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw).resolve()
            profile = tamriel.prepare_profile(tamriel.REPO_ROOT / "config/tr-release.json", work, None)
            args = cli._parser().parse_args([
                "check", "--profile", str(profile), "--work-root", str(work),
                "--public-root", str(work / "candidate/apps/web/public"),
                "--baseline-public-root", str(work / "baseline/apps/web/public"),
            ])
            context = cli._context(args, require_lock=False)
            context = replace(context, lock={"datasetId": "local-release"})
            self.assertEqual(context.repo_root, tamriel.REPO_ROOT)
            for path in (context.production_root, context.release_root, context.catalog_root, context.candidate_root, context.public):
                self.assertIn(work, path.parents)
            arguments = cli._candidate_arguments(context)
            self.assertEqual(arguments["active_datasets_root"], context.baseline_public / "datasets")
            legacy = replace(context, work_root=None, public_root=None, baseline_public_root=None)
            self.assertEqual(legacy.candidate_root, tamriel.REPO_ROOT / "local-data/tr-release/candidate/datasets")
            with patch.object(cli, "_context", return_value=legacy):
                with self.assertRaisesRegex(ValueError, "requires --work-root"):
                    cli._command_activate_local(argparse.Namespace())
            published = replace(context, public_root=tamriel.REPO_ROOT / "apps/web/public")
            with patch.object(cli, "_context", return_value=published):
                with self.assertRaisesRegex(ValueError, "published public tree"):
                    cli._command_activate_local(argparse.Namespace())

    def test_full_run_passes_isolated_roots_to_every_stage_and_stops_on_failure(self) -> None:
        (tamriel.REPO_ROOT / "local-data").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tamriel.REPO_ROOT / "local-data") as raw:
            work = Path(raw).resolve() / "work"
            args = tamriel._parser().parse_args(["run", "--work-root", str(work)])
            calls: list[str] = []

            def execute(module: str, argv: list[str]) -> None:
                self.assertEqual(module, "tools.tr_release.cli")
                self.assertEqual(argv[argv.index("--public-root") + 1], str(work / "candidate/apps/web/public"))
                calls.append(argv[0])
                if argv[0] == "lock":
                    (work / "release.lock.json").write_text('{"snapshotId":"tr:local:1234"}')
                if argv[0] == "renderer-finalize":
                    raise RuntimeError("render gate failed")

            with patch.object(tamriel, "run_module", side_effect=execute), patch.object(tamriel, "copy_public_tree"):
                with self.assertRaisesRegex(RuntimeError, "render gate failed"):
                    tamriel.run(args)
            self.assertEqual(calls, ["check", "lock", "plan", "renderer-smoke", "renderer-render", "renderer-finalize"])
            self.assertFalse((work / "receipt.json").exists())

    def test_full_run_verifies_before_local_activation_and_records_receipt(self) -> None:
        (tamriel.REPO_ROOT / "local-data").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tamriel.REPO_ROOT / "local-data") as raw:
            work = Path(raw).resolve() / "work"
            args = tamriel._parser().parse_args(["run", "--work-root", str(work)])
            calls: list[str] = []

            def execute(module: str, argv: list[str]) -> None:
                calls.append(argv[0])
                if argv[0] == "lock":
                    (work / "release.lock.json").write_text('{"snapshotId":"tr:local:1234"}')

            with patch.object(tamriel, "run_module", side_effect=execute), patch.object(tamriel, "copy_public_tree"):
                receipt = tamriel.run(args)
            self.assertEqual(calls, ["check", "lock", *tamriel.RUN_STAGES])
            self.assertEqual(calls[-2:], ["release-verify", "activate-local"])
            self.assertEqual(receipt["snapshotId"], "tr:local:1234")
            self.assertEqual(receipt, json.loads((work / "receipt.json").read_bytes()))


if __name__ == "__main__":
    unittest.main()
