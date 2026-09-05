from __future__ import annotations

import fcntl
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.deployment.common import DeploymentError
from tools.deployment.install_release import install_release
from tools.deployment.package_release import package_release
from tools.deployment.tests.fixtures import write_dist
from tools.deployment.tests.test_health_check import serve


class InstallReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name).resolve()
        self.dist = self.workspace / "dist"
        self.paths = write_dist(self.dist)
        self.root = self.workspace / "site"
        (self.root / "releases").mkdir(parents=True)
        shutil.copytree(self.dist / "datasets/generated", self.root / "data/generated")
        self.old_sha = "a" * 40
        self.new_sha = "b" * 40
        self.old = self.package(self.old_sha)
        self.new = self.package(self.new_sha)

    def package(self, sha: str) -> dict[str, object]:
        return package_release(
            repo_root=self.workspace, dist_root=self.dist,
            output_dir=self.workspace / sha, commit_sha=sha,
        )

    def install(self, package: dict[str, object], sha: str, **kwargs: object) -> Path:
        return install_release(
            Path(str(package["archive"])), str(package["archiveSha256"]), sha, self.root, **kwargs
        )

    def seed_previous(self, url: str) -> None:
        self.install(self.old, self.old_sha, health_urls=(url,))

    def test_success_and_check_only_with_real_health_command(self) -> None:
        self.install(self.new, self.new_sha, check_only=True)
        self.assertFalse((self.root / "current").is_symlink())
        with serve() as url:
            self.seed_previous(url)
            self.install(self.new, self.new_sha, health_urls=(url,))
        self.assertEqual((self.root / "current").resolve(), self.root / "releases" / self.new_sha)

    def test_public_health_failure_restores_previous_after_origin_passes(self) -> None:
        with serve() as origin, serve(bad_cache_path="/datasets/index.json") as public:
            self.seed_previous(origin)
            before = (self.root / "current").readlink()
            with self.assertRaises(subprocess.CalledProcessError):
                self.install(self.new, self.new_sha, health_urls=(origin, public))
        self.assertEqual((self.root / "current").readlink(), before)

    def test_first_deploy_failure_leaves_no_current(self) -> None:
        with serve(missing_as_spa=True) as url:
            with self.assertRaises(subprocess.CalledProcessError):
                self.install(self.new, self.new_sha, health_urls=(url,))
        self.assertFalse((self.root / "current").is_symlink())

    def test_missing_generated_artifacts_never_switch_current(self) -> None:
        with serve() as url:
            self.seed_previous(url)
        before = (self.root / "current").readlink()
        for name in ("locations", "tile"):
            with self.subTest(artifact=name):
                path = self.root / "data/generated" / self.paths[name].removeprefix("/datasets/generated/")
                payload = path.read_bytes()
                path.unlink()
                try:
                    with self.assertRaises(DeploymentError), patch("tools.deployment.install_release.subprocess.run") as health:
                        self.install(self.new, self.new_sha)
                    health.assert_not_called()
                    self.assertEqual((self.root / "current").readlink(), before)
                finally:
                    path.write_bytes(payload)

    def test_health_timeout_rolls_back_while_both_locks_are_held(self) -> None:
        with serve() as url:
            self.seed_previous(url)
        before = (self.root / "current").readlink()

        def timeout(*args: object, **kwargs: object) -> None:
            self.assertEqual((self.root / "current").resolve(), self.root / "releases" / self.new_sha)
            for name in (".app-deploy.lock", "data/.dataset-upload.lock"):
                with (self.root / name).open("a") as lock:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            raise subprocess.TimeoutExpired("deploy:health", 120)

        with patch("tools.deployment.install_release.subprocess.run", side_effect=timeout):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.install(self.new, self.new_sha)
        self.assertEqual((self.root / "current").readlink(), before)

    def test_rollback_restores_previous_dataset_graph_with_the_application(self) -> None:
        old_graph, new_graph = "c" * 64, "d" * 64
        for graph in (old_graph, new_graph):
            shutil.copytree(self.root / "data/generated", self.root / "data/releases" / graph)
        with serve() as healthy, serve(missing_as_spa=True) as unhealthy:
            self.install(self.old, self.old_sha, dataset_graph=old_graph, health_urls=(healthy,))
            shutil.rmtree(self.root / "data/generated")
            with self.assertRaises(subprocess.CalledProcessError):
                self.install(self.new, self.new_sha, dataset_graph=new_graph, health_urls=(unhealthy,))
            self.assertEqual(
                (self.root / "current/datasets/generated").resolve(),
                self.root / "data/releases" / old_graph,
            )
            self.install(self.new, self.new_sha, dataset_graph=new_graph, health_urls=(healthy,))
            self.assertEqual(
                (self.root / "current/datasets/generated").resolve(),
                self.root / "data/releases" / new_graph,
            )


if __name__ == "__main__":
    unittest.main()
