from __future__ import annotations

import hashlib
import io
import json
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from tools.deployment.common import DeploymentError, canonical_json_bytes
from tools.deployment import upload_datasets
from tools.deployment.dataset_remote import (
    RemoteInstallError,
    abort_stage,
    install_stage,
    prepare_stage,
    probe_installed,
)
from tools.deployment.tests.fixtures import TILE_HASH, write_dist
from tools.deployment.upload_datasets import build_dataset_plan, upload_dataset_plan


class DatasetPlanTests(unittest.TestCase):
    def test_collects_only_active_graph_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            public = root / "public"
            paths = write_dist(public)
            stale = public / "datasets/generated/test-dataset" / ("e" * 64) / "tiles/0/0/0.webp"
            stale.parent.mkdir(parents=True)
            stale.write_bytes(b"stale")

            first = build_dataset_plan(public_root=public)
            second = build_dataset_plan(public_root=public)

            self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
            self.assertEqual(first["fileCount"], 3)
            self.assertEqual(
                {record["path"] for record in first["files"]},
                {
                    paths["locations"].removeprefix("/datasets/generated/"),
                    paths["locale"].removeprefix("/datasets/generated/"),
                    paths["tile"].removeprefix("/datasets/generated/"),
                },
            )
            self.assertNotIn("e" * 64, canonical_json_bytes(first).decode())
            core = dict(first)
            graph_sha = core.pop("graphSha256")
            self.assertEqual(graph_sha, hashlib.sha256(canonical_json_bytes(core)).hexdigest())

    def test_rejects_tampered_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            public = Path(temporary) / "public"
            paths = write_dist(public)
            (public / paths["locations"].lstrip("/")).write_bytes(b"{}\n")
            with self.assertRaisesRegex(DeploymentError, "location catalog.*(bytes|SHA-256)"):
                build_dataset_plan(public_root=public)

    def test_rejects_tiles_ndjson_that_differs_from_quality_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            public = Path(temporary) / "public"
            paths = write_dist(public)
            (public / paths["tilesInventory"].lstrip("/")).write_bytes(b"{}\n")
            with self.assertRaisesRegex(DeploymentError, "tiles.ndjson.*(bytes|SHA-256)"):
                build_dataset_plan(public_root=public)

    def test_rejects_unlisted_file_inside_active_tile_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            public = Path(temporary) / "public"
            write_dist(public)
            extra = public / f"datasets/generated/test-dataset/{TILE_HASH}/tiles/0/0/1.webp"
            extra.write_bytes(b"extra")
            with self.assertRaisesRegex(DeploymentError, "tile tree differs"):
                build_dataset_plan(public_root=public)


class RemoteDatasetInstallTests(unittest.TestCase):
    upload_one = "1" * 32
    upload_two = "2" * 32

    @staticmethod
    def _plan(content: bytes) -> dict[str, object]:
        core: dict[str, object] = {
            "datasets": [{"datasetId": "test-dataset"}],
            "fileCount": 1,
            "files": [
                {
                    "bytes": len(content),
                    "path": "test-dataset/" + ("d" * 64) + "/tiles/0/0/0.webp",
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ],
            "schemaVersion": 1,
            "totalBytes": len(content),
        }
        return {**core, "graphSha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest()}

    @staticmethod
    def _fill_stage(data_root: Path, upload_id: str, plan: dict[str, object], content: bytes) -> None:
        stage = prepare_stage(data_root, upload_id)
        (stage / "plan.json").write_bytes(canonical_json_bytes(plan))
        relative = Path(str(plan["files"][0]["path"]))
        target = stage / "payload" / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(content)

    def test_atomic_install_is_idempotent_and_retains_previous_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data"
            data_root.mkdir()
            first_content = b"first"
            first = self._plan(first_content)
            self._fill_stage(data_root, self.upload_one, first, first_content)
            staged_file = (
                data_root
                / "incoming"
                / self.upload_one
                / "payload"
                / str(first["files"][0]["path"])
            )
            staged_file.parent.chmod(0o700)
            staged_file.chmod(0o600)
            first_release = install_stage(data_root, self.upload_one)
            self.assertEqual((data_root / "generated").resolve(), first_release.resolve())
            installed_file = first_release / str(first["files"][0]["path"])
            self.assertEqual(stat.S_IMODE(first_release.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(installed_file.parent.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(installed_file.stat().st_mode), 0o644)

            # A retry of the same graph verifies the existing immutable release and
            # does not require another payload transfer.
            retry_id = "3" * 32
            retry = prepare_stage(data_root, retry_id)
            (retry / "plan.json").write_bytes(canonical_json_bytes(first))
            installed_file.chmod(0o600)
            self.assertTrue(probe_installed(data_root, retry_id))
            self.assertEqual(stat.S_IMODE(installed_file.stat().st_mode), 0o644)
            self.assertEqual([first["graphSha256"]], [path.name for path in (data_root / "releases").iterdir()])

            second_content = b"second"
            second = self._plan(second_content)
            self._fill_stage(data_root, self.upload_two, second, second_content)
            second_release = install_stage(data_root, self.upload_two)
            self.assertEqual((data_root / "generated").resolve(), second_release.resolve())
            self.assertTrue(first_release.exists())
            self.assertEqual({first["graphSha256"], second["graphSha256"]}, {path.name for path in (data_root / "releases").iterdir()})
            self.assertEqual([], list((data_root / "incoming").iterdir()))

    def test_stage_only_and_retry_preserve_active_and_other_releases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data"
            data_root.mkdir()
            active_plan = self._plan(b"active")
            self._fill_stage(data_root, self.upload_one, active_plan, b"active")
            active = install_stage(data_root, self.upload_one)
            generated = data_root / "generated"
            original_link = generated.lstat()

            plan = self._plan(b"staged")
            self._fill_stage(data_root, self.upload_two, plan, b"staged")
            staged = install_stage(data_root, self.upload_two, stage_only=True)
            self.assertEqual(staged, data_root / "releases" / str(plan["graphSha256"]))
            retry = prepare_stage(data_root, self.upload_two)
            (retry / "plan.json").write_bytes(canonical_json_bytes(plan))
            self.assertTrue(probe_installed(data_root, self.upload_two, stage_only=True))

            # Cleanup after a failed app deployment must not remove the graph.
            abort_stage(data_root, self.upload_two)
            self.assertTrue(staged.is_dir())
            self.assertEqual(generated.resolve(), active.resolve())
            self.assertEqual(generated.lstat().st_ino, original_link.st_ino)
            self.assertEqual(generated.lstat().st_mtime_ns, original_link.st_mtime_ns)
            self.assertEqual({active, staged}, set((data_root / "releases").iterdir()))
            self.assertEqual([], list((data_root / "incoming").iterdir()))

    def test_stage_only_without_active_link_and_rejects_corrupt_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data"
            data_root.mkdir()
            plan = self._plan(b"valid")
            self._fill_stage(data_root, self.upload_one, plan, b"bad")
            with self.assertRaisesRegex(RemoteInstallError, "integrity"):
                install_stage(data_root, self.upload_one, stage_only=True)
            abort_stage(data_root, self.upload_one)
            self._fill_stage(data_root, self.upload_two, plan, b"valid")
            release = install_stage(data_root, self.upload_two, stage_only=True)
            self.assertTrue(release.is_dir())
            self.assertFalse((data_root / "generated").exists())
            self.assertFalse((data_root / "generated").is_symlink())

    def test_refuses_to_replace_an_unmanaged_generated_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data"
            data_root.mkdir()
            (data_root / "generated").mkdir()
            content = b"payload"
            plan = self._plan(content)
            self._fill_stage(data_root, self.upload_one, plan, content)
            with self.assertRaisesRegex(RemoteInstallError, "non-symlink"):
                install_stage(data_root, self.upload_one)

    def test_install_does_not_remove_another_upload_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data"
            data_root.mkdir()
            first_content = b"first"
            second_content = b"second"
            first = self._plan(first_content)
            second = self._plan(second_content)
            self._fill_stage(data_root, self.upload_one, first, first_content)
            self._fill_stage(data_root, self.upload_two, second, second_content)

            install_stage(data_root, self.upload_one)
            second_stage = data_root / "incoming" / self.upload_two
            self.assertTrue(second_stage.is_dir())

            second_release = install_stage(data_root, self.upload_two)
            self.assertEqual((data_root / "generated").resolve(), second_release.resolve())
            self.assertEqual([], list((data_root / "incoming").iterdir()))

    def test_abort_removes_only_the_named_incomplete_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data"
            data_root.mkdir()
            first = prepare_stage(data_root, self.upload_one)
            second = prepare_stage(data_root, self.upload_two)

            abort_stage(data_root, self.upload_one)

            self.assertFalse(first.exists())
            self.assertTrue(second.is_dir())


class DatasetTransportTests(unittest.TestCase):
    def test_plan_probe_preserves_active_graph_and_transfers_only_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data"
            data_root.mkdir()
            active_plan = RemoteDatasetInstallTests._plan(b"active")
            RemoteDatasetInstallTests._fill_stage(data_root, "1" * 32, active_plan, b"active")
            active = install_stage(data_root, "1" * 32)
            generated_stat = (data_root / "generated").lstat()
            other_stage = prepare_stage(data_root, "2" * 32)

            for present in (False, True):
                with self.subTest(present=present):
                    plan = active_plan if present else RemoteDatasetInstallTests._plan(b"missing")
                    calls: list[list[str]] = []

                    def local_transport(arguments: list[str], **_: object):
                        calls.append(arguments)
                        if arguments[0] == "rsync":
                            self.assertTrue(arguments[-2].endswith("/plan.json"))
                            shutil.copyfile(arguments[-2], data_root / "incoming" / ("a" * 32) / "plan.json")
                            stdout = ""
                        else:
                            action, upload_id = arguments[-2:]
                            if action == "prepare":
                                prepare_stage(data_root, upload_id)
                                stdout = "prepared"
                            elif action == "probe-stage":
                                stdout = "installed" if probe_installed(data_root, upload_id, stage_only=True) else "upload"
                            elif action == "abort":
                                abort_stage(data_root, upload_id)
                                stdout = "aborted"
                            else:
                                self.fail(f"Unexpected remote action: {action}")
                        return subprocess.CompletedProcess(arguments, 0, stdout=stdout)

                    with patch("tools.deployment.upload_datasets._run", side_effect=local_transport), patch(
                        "tools.deployment.upload_datasets.secrets.token_hex", return_value="a" * 32
                    ):
                        result = upload_datasets.probe_dataset_plan(host="production", plan=plan)

                    self.assertEqual(result, {"graphSha256": plan["graphSha256"], "releasePath": f"/srv/morrowind-map/data/releases/{plan['graphSha256']}", "status": "already-staged" if present else "missing"})
                    self.assertEqual([call[-2] for call in calls if call[0] == "ssh"], ["prepare", "probe-stage", "abort"])
                    self.assertEqual(sum(call[0] == "rsync" for call in calls), 1)
                    self.assertEqual({active}, set((data_root / "releases").iterdir()))
                    self.assertEqual([other_stage], list((data_root / "incoming").iterdir()))
                    self.assertEqual((data_root / "generated").lstat(), generated_stat)

    def test_plan_probe_cleans_stage_on_transport_error(self) -> None:
        calls: list[list[str]] = []

        def fake_run(arguments: list[str], **_: object):
            calls.append(arguments)
            if arguments[0] == "rsync":
                raise subprocess.CalledProcessError(23, arguments)
            return subprocess.CompletedProcess(arguments, 0, stdout="prepared")

        with patch("tools.deployment.upload_datasets._run", side_effect=fake_run):
            with self.assertRaises(subprocess.CalledProcessError):
                upload_datasets.probe_dataset_plan(host="production", plan=RemoteDatasetInstallTests._plan(b"valid"))
        self.assertEqual(calls[-1][-2], "abort")

    def test_probe_cli_reads_plan_without_generated_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = RemoteDatasetInstallTests._plan(b"valid")
            (root / "plan.json").write_bytes(canonical_json_bytes(plan))
            with patch("tools.deployment.upload_datasets.probe_dataset_plan", return_value={"status": "missing"}) as probe, patch(
                "tools.deployment.upload_datasets.build_dataset_plan", side_effect=AssertionError("must not inspect generated data")
            ), redirect_stdout(io.StringIO()) as stdout:
                result = upload_datasets.main(["--repo-root", str(root), "--probe-plan", "plan.json", "--host", "production"])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.getvalue()), {"status": "missing"})
            probe.assert_called_once_with(host="production", plan=plan)

    def test_probe_cli_rejects_missing_host_and_conflicting_modes(self) -> None:
        for arguments in (["--probe-plan", "plan.json"], ["--probe-plan", "plan.json", "--host", "production", "--stage-only"], ["--probe-plan", "plan.json", "--host", "production", "--plan-output", "other.json"]):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    upload_datasets.main(arguments)
                self.assertEqual(error.exception.code, 2)

    def test_stage_only_transport_and_existing_graph_skip_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            public = Path(temporary) / "public"
            write_dist(public)
            plan = build_dataset_plan(public_root=public)
            for already_staged in (False, True):
                with self.subTest(already_staged=already_staged):
                    calls: list[list[str]] = []

                    def fake_run(arguments: list[str], **_: object):
                        calls.append(arguments)
                        stdout = "installed\n"
                        if "probe-stage" in arguments and not already_staged:
                            stdout = "upload\n"
                        return type("Result", (), {"stdout": stdout})()

                    with patch("tools.deployment.upload_datasets._run", side_effect=fake_run):
                        result = upload_dataset_plan(public_root=public, host="vpsdo", plan=plan, stage_only=True)

                    self.assertEqual(result["status"], "already-staged" if already_staged else "staged")
                    self.assertEqual(result["releasePath"], f"/srv/morrowind-map/data/releases/{plan['graphSha256']}")
                    actions = [call[-2] for call in calls if call[0] == "ssh"]
                    self.assertEqual(actions, ["prepare", "probe-stage"] + ([] if already_staged else ["install-stage"]))
                    payload_calls = [call for call in calls if any("--files-from=" in item for item in call)]
                    self.assertEqual(len(payload_calls), 0 if already_staged else 1)

    def test_transport_uses_exact_files_from_without_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            public = Path(temporary) / "public"
            write_dist(public)
            plan = build_dataset_plan(public_root=public)
            calls: list[list[str]] = []

            def fake_run(arguments: list[str], **_: object):
                calls.append(arguments)
                stdout = "upload\n" if "probe" in arguments else "installed\n" if "install" in arguments else "prepared\n"
                return type("Result", (), {"stdout": stdout})()

            with patch("tools.deployment.upload_datasets._run", side_effect=fake_run), patch(
                "tools.deployment.upload_datasets.secrets.token_hex", return_value="a" * 32
            ):
                result = upload_dataset_plan(public_root=public, host="vpsdo", plan=plan)

            self.assertEqual(result["status"], "installed")
            flattened = [argument for call in calls for argument in call]
            self.assertFalse(any("--delete" in argument for argument in flattened))
            self.assertTrue(
                all(
                    "--no-owner" in call and "--no-group" in call
                    for call in calls
                    if call and call[0] == "rsync"
                )
            )
            self.assertTrue(
                all(
                    "--chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r" in call
                    for call in calls
                    if call and call[0] == "rsync"
                )
            )
            payload_calls = [call for call in calls if call and call[0] == "rsync" and any("--files-from=" in item for item in call)]
            self.assertEqual(len(payload_calls), 1)
            self.assertIn("--partial", payload_calls[0])

    def test_transport_aborts_only_its_stage_after_rsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            public = Path(temporary) / "public"
            write_dist(public)
            plan = build_dataset_plan(public_root=public)
            calls: list[list[str]] = []

            def fake_run(arguments: list[str], **_: object):
                calls.append(arguments)
                if arguments[0] == "rsync" and any(
                    "--files-from=" in item for item in arguments
                ):
                    raise subprocess.CalledProcessError(23, arguments)
                stdout = "upload\n" if "probe" in arguments else "prepared\n"
                return type("Result", (), {"stdout": stdout})()

            with patch("tools.deployment.upload_datasets._run", side_effect=fake_run), patch(
                "tools.deployment.upload_datasets.secrets.token_hex", return_value="a" * 32
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    upload_dataset_plan(public_root=public, host="vpsdo", plan=plan)

            self.assertEqual(calls[-1][0:4], ["ssh", "vpsdo", "python3", "-"])
            self.assertEqual(calls[-1][-2:], ["abort", "a" * 32])


if __name__ == "__main__":
    unittest.main()
