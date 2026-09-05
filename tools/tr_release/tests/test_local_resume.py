from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools.tr_release import cli
from tools.tr_release.tests.test_candidate import CandidateFixture


class LocalCandidateResumeTests(unittest.TestCase):
    def test_repeated_build_and_activation_preserve_the_immutable_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = CandidateFixture(root / "fixture")
            work = root / "work"
            baseline = work / "baseline/apps/web/public"
            public = work / "candidate/apps/web/public"
            shutil.copytree(fixture.active_root, baseline / "datasets")
            shutil.copytree(fixture.active_root, public / "datasets")
            shutil.copytree(fixture.generated_root, public / "datasets/generated", dirs_exist_ok=True)
            shutil.copytree(fixture.metadata_root, public / "datasets/metadata")
            before = {path.relative_to(baseline): path.read_bytes()
                      for path in baseline.rglob("*") if path.is_file()}
            context = cli.Context(
                repo_root=root, profile_path=work / "profile.json", lock_path=work / "release.lock.json",
                source_root=root / "inputs",
                profile=SimpleNamespace(to_dict=lambda: fixture.profile),
                lock=fixture.lock, work_root=work, public_root=public,
                baseline_public_root=baseline,
            )
            with mock.patch.object(cli, "_context", return_value=context), contextlib.redirect_stdout(io.StringIO()):
                for _ in range(2):
                    self.assertEqual(cli._command_manifest_build(argparse.Namespace()), 0)
                    self.assertEqual(cli._command_activate_local(argparse.Namespace()), 0)
            after = {path.relative_to(baseline): path.read_bytes()
                     for path in baseline.rglob("*") if path.is_file()}
            self.assertEqual(after, before)
            index = json.loads((public / "datasets/index.json").read_bytes())
            self.assertEqual([entry["datasetId"] for entry in index["datasets"]],
                             [fixture.original_id, fixture.dataset_id])
            self.assertEqual((public / "datasets/manifests" / f"{fixture.original_id}.json").read_bytes(),
                             (baseline / "datasets/manifests" / f"{fixture.original_id}.json").read_bytes())

    def test_local_activation_requires_an_independent_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            public = root / "work/public"
            context = cli.Context(root, root / "profile", root / "lock", root / "inputs",
                                  None, {}, root / "work", public, public)
            with mock.patch.object(cli, "_context", return_value=context):
                with self.assertRaisesRegex(ValueError, "separate immutable baseline"):
                    cli._command_activate_local(argparse.Namespace())


if __name__ == "__main__":
    unittest.main()
