"""Validate a CI application archive against installed data and atomically activate it."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from tools.deployment.common import (
    DeploymentError,
    artifact_descriptor,
    canonical_json_bytes,
    safe_file,
    sha256_bytes,
    strict_json_object,
    verify_artifact,
)
from tools.deployment.package_release import ReleaseBuilder


MAX_UNPACKED_BYTES = 100 * 1024 * 1024


def _unpack(archive_path: Path, stage: Path) -> None:
    total = 0
    names: set[str] = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (
                not member.isfile()
                or path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != member.name
                or member.name in names
                or member.size < 0
            ):
                raise DeploymentError(f"Unsafe archive member: {member.name}")
            names.add(member.name)
            total += member.size
            if total > MAX_UNPACKED_BYTES:
                raise DeploymentError("Application archive exceeds the unpacked size limit")
            source = archive.extractfile(member)
            if source is None:
                raise DeploymentError(f"Cannot read archive member: {member.name}")
            target = stage.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            target.chmod(0o644)
    for directory in stage.rglob("*"):
        if directory.is_dir():
            directory.chmod(0o755)
    stage.chmod(0o755)


def _validate(stage: Path, generated: Path, commit_sha: str) -> bytes:
    manifest_path = safe_file(stage, Path("release-manifest.json"), "release manifest")
    manifest = strict_json_object(manifest_path.read_bytes(), "release manifest")
    builder = ReleaseBuilder(stage, MAX_UNPACKED_BYTES)
    builder.collect()
    expected = {
        "commitSha": commit_sha,
        "datasets": sorted(builder.datasets, key=lambda item: str(item["datasetId"])),
        "files": [
            {"bytes": len(payload), "path": path, "sha256": sha256_bytes(payload)}
            for path, payload in sorted(builder.files.items())
        ],
        "generatedArtifacts": [builder.generated[url] for url in sorted(builder.generated)],
        "schemaVersion": 1,
    }
    if manifest != expected:
        raise DeploymentError("Release manifest differs from the verified commit or package files")
    files = {p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()}
    if files != set(builder.files) | {"release-manifest.json"}:
        raise DeploymentError("Application archive contains unlisted files")
    for value in builder.generated.values():
        descriptor = artifact_descriptor(value, "installed dataset", require_bytes=False)
        relative = Path(descriptor.url.removeprefix("/datasets/generated/"))
        payload = safe_file(generated, relative, "installed dataset").read_bytes()
        verify_artifact(payload, descriptor, "installed dataset")
    # Dataset upload already verifies tile hashes. Check every expected tile's
    # presence and the total size here without rereading gigabytes on each UI deploy.
    for dataset in builder.datasets:
        for pyramid in dataset["tilePyramids"]:
            coverage_url = pyramid["coverage"]["url"]
            coverage = strict_json_object(
                builder.files[coverage_url.lstrip("/")], "tile coverage"
            )
            count = byte_count = 0
            for level in coverage["levels"]:
                for column in level["columns"]:
                    for start, end in column["yRanges"]:
                        for y in range(start, end + 1):
                            count += 1
                            if count > pyramid["tileCount"]:
                                raise DeploymentError("Coverage exceeds the declared tile count")
                            url = pyramid["urlTemplate"].format(z=level["z"], x=column["x"], y=y)
                            relative = Path(url.removeprefix("/datasets/generated/"))
                            byte_count += safe_file(generated, relative, "installed tile").stat().st_size
            if count != pyramid["tileCount"] or byte_count != pyramid["totalBytes"]:
                raise DeploymentError("Installed tiles differ from the release inventory totals")
    return canonical_json_bytes(manifest)


def install_release(
    archive: Path, archive_sha256: str, commit_sha: str, root: Path, *, check_only: bool = False,
    health_urls: tuple[str, ...] = ("http://127.0.0.1:9003/",),
    dataset_graph: str | None = None,
) -> Path:
    if not check_only and not health_urls:
        raise DeploymentError("Publishing requires at least one health check URL")
    if re.fullmatch(r"[a-f0-9]{40}", commit_sha) is None:
        raise DeploymentError("Expected a full commit SHA")
    if dataset_graph is not None and re.fullmatch(r"[a-f0-9]{64}", dataset_graph) is None:
        raise DeploymentError("Expected a dataset graph SHA-256")
    if re.fullmatch(r"[a-f0-9]{64}", archive_sha256) is None:
        raise DeploymentError("Expected an archive SHA-256")
    if archive.stat().st_size > MAX_UNPACKED_BYTES:
        raise DeploymentError("Application archive exceeds the compressed size limit")
    if sha256_bytes(archive.read_bytes()) != archive_sha256:
        raise DeploymentError("Application archive SHA-256 mismatch")
    root = root.resolve(strict=True)
    releases = root / "releases"
    if releases.is_symlink() or not releases.is_dir():
        raise DeploymentError("Application releases must be an existing real directory")
    current = root / "current"
    # Serialize app deployments, and prevent the dataset uploader from swapping
    # or pruning the data tree while this release is being validated/activated.
    with (root / ".app-deploy.lock").open("a") as app_lock, (
        root / "data/.dataset-upload.lock"
    ).open("a") as data_lock:
        fcntl.flock(app_lock, fcntl.LOCK_EX)
        fcntl.flock(data_lock, fcntl.LOCK_SH)
        if current.exists() and not current.is_symlink():
            raise DeploymentError("Refusing to replace a non-symlink current path")
        generated = (root / "data/releases" / dataset_graph if dataset_graph else root / "data/generated").resolve(strict=True)
        if root / "data" not in generated.parents:
            raise DeploymentError("Generated dataset path escaped the data directory")
        with tempfile.TemporaryDirectory(prefix=".ci-", dir=releases) as temporary:
            stage = Path(temporary)
            _unpack(archive, stage)
            manifest = _validate(stage, generated, commit_sha)
            destination = releases / commit_sha
            if check_only:
                return destination
            previous = current.readlink() if current.is_symlink() else None
            if previous is not None:
                previous_release = current.resolve(strict=True)
                if previous_release.parent != releases:
                    raise DeploymentError("Previous release is outside the releases directory")
                previous_manifest = strict_json_object(
                    (previous_release / "release-manifest.json").read_bytes(), "previous release"
                )
                previous_link = previous_release / "datasets/generated"
                previous_generated = (
                    previous_link if previous_link.is_symlink() else root / "data/generated"
                ).resolve(strict=True)
                if root / "data" not in previous_generated.parents:
                    raise DeploymentError("Previous dataset path escaped the data directory")
                _validate(previous_release, previous_generated, previous_manifest["commitSha"])
                # One-time migration of releases created before datasets were pinned per app.
                if not previous_link.is_symlink():
                    previous_link.symlink_to(os.path.relpath(previous_generated, previous_link.parent))
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink() or _validate(destination, generated, commit_sha) != manifest:
                    raise DeploymentError("Existing immutable release differs from the CI package")
            else:
                os.rename(stage, destination)
            dataset_link = destination / "datasets/generated"
            if dataset_link.is_symlink():
                if dataset_link.resolve(strict=True) != generated:
                    raise DeploymentError("Existing immutable release is pinned to a different dataset graph")
            else:
                dataset_link.symlink_to(os.path.relpath(generated, dataset_link.parent))
            link = root / f".current-{stage.name}"
            try:
                link.symlink_to(Path("releases") / commit_sha)
                os.replace(link, current)
                try:
                    print(f"Activated {commit_sha}; previous current: {previous}", flush=True)
                    for base_url in health_urls:
                        # This is the existing deploy:health entry point; no Node.js is needed on VPS.
                        subprocess.run(
                            [sys.executable, "-m", "tools.deployment.health_check", "--base-url", base_url],
                            check=True, timeout=120,
                        )
                except BaseException:
                    if previous is None:
                        current.unlink()
                        print("Health check failed; removed first deployment's current link.", file=sys.stderr)
                    else:
                        link.symlink_to(previous)
                        os.replace(link, current)
                        print(f"Health check failed; restored current to {previous}.", file=sys.stderr)
                    raise
            finally:
                link.unlink(missing_ok=True)
            return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--root", type=Path, default=Path("/srv/morrowind-map"))
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--dataset-graph", help="Previously staged immutable dataset graph SHA-256")
    parser.add_argument(
        "--health-url", action="append",
        help="Run deploy:health after activation for each URL; defaults to the local nginx origin",
    )
    args = parser.parse_args()
    path = install_release(
        args.archive, args.archive_sha256, args.commit_sha, args.root, check_only=args.check_only,
        health_urls=tuple(args.health_url or ["http://127.0.0.1:9003/"]),
        dataset_graph=args.dataset_graph,
    )
    print(json.dumps({"release": str(path), "status": "validated" if args.check_only else "published"}))


if __name__ == "__main__":
    main()
