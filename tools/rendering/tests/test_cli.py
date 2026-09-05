from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.rendering import cli, common


class RenderingWorkflowTests(unittest.TestCase):
    def test_all_preflights_both_maps_before_any_build_or_render(self) -> None:
        calls = []

        def adapter(target, arguments, logs):
            calls.append((target, arguments[0]))
            if target == "tamriel-rebuilt":
                raise ValueError("Required TR input is missing")
            return {"valid": True}

        with mock.patch.object(cli, "run_adapter", side_effect=adapter), mock.patch.object(cli, "require_tools") as tools:
            with self.assertRaisesRegex(ValueError, "Required TR input"):
                cli.main(["run", "all"])
        self.assertEqual(calls, [("original", "check"), ("tamriel-rebuilt", "check")])
        tools.assert_not_called()

    def test_all_composes_validated_original_into_tr_candidate(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw).resolve()
            root = repo / "local-data/render"
            profile = repo / "profile.json"
            profile.write_text('{}')

            def adapter(target, arguments, logs):
                calls.append((target, arguments))
                return {"publicRoot": str(root / target / "public"), "profile": str(profile)}

            with mock.patch.object(cli, "REPO_ROOT", repo), mock.patch.object(cli, "run_adapter", side_effect=adapter), \
                 mock.patch.object(cli, "require_tools"), mock.patch.object(cli, "ensure_base_image"), \
                 mock.patch.object(cli, "validate_candidate", return_value={"graphSha256": "a" * 64}) as validate:
                self.assertEqual(cli.main(["run", "all", "--work-root", str(root)]), 0)
            tr_run = next(args for target, args in calls if target == "tamriel-rebuilt" and args[0] == "run")
            self.assertEqual(tr_run[-2:], ["--baseline-public-root", str(root / "original/public")])
            self.assertEqual(validate.call_count, 2)
            self.assertEqual(json.loads((root / "result.json").read_text())["publicRoot"], str(root / "tamriel-rebuilt/public"))

    def test_work_root_cannot_pollute_inputs_or_tracked_files(self) -> None:
        for path in (cli.REPO_ROOT / "apps/web/public", cli.REPO_ROOT / "local-data/inputs/output"):
            with self.subTest(path=path), mock.patch.object(cli, "run_adapter") as adapter:
                with self.assertRaises(ValueError):
                    cli.main(["check", "--work-root", str(path)])
                adapter.assert_not_called()

    def test_workspace_destination_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            (root / "outside").mkdir()
            (root / "link").symlink_to(root / "outside", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Symlink"):
                common.safe_path(root / "link/file.json", root)

    def test_copy_does_not_link_candidate_bytes_to_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            source, target = root / "source", root / "target"
            generated = source / "datasets/generated/map/tile.webp"
            generated.parent.mkdir(parents=True)
            generated.write_bytes(b"original")
            (source / "datasets/index.json").write_text('{}')
            plan = {"graphSha256": "a" * 64, "files": [{"path": "map/tile.webp"}]}
            with mock.patch("tools.deployment.upload_datasets.build_dataset_plan", return_value=plan):
                common.copy_public_tree(source, target)
                (target / "datasets/generated/map/tile.webp").write_bytes(b"changed")
                self.assertEqual(generated.read_bytes(), b"original")
                common.copy_public_tree(source, target)
            changed = {**plan, "graphSha256": "b" * 64}
            with mock.patch("tools.deployment.upload_datasets.build_dataset_plan", return_value=changed):
                with self.assertRaisesRegex(ValueError, "baseline changed"):
                    common.copy_public_tree(source, target)

    def test_use_refuses_files_outside_ignored_local_workspace(self) -> None:
        with mock.patch.object(cli, "validate_candidate") as validate:
            with self.assertRaisesRegex(ValueError, "ignored local-data"):
                cli.use_candidate(Path("/private/tmp/unrelated-public"))
        validate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
