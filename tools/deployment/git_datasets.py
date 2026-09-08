"""Inspect and export dataset objects without checking out or running candidate code.

Invoke a trusted copy by absolute path; all imports resolve from that trusted tree.
Snapshots must contain their own complete Release lock and upload plan. Export
contains metadata only, for a separate trusted downloader. Tracked generated
tiles and LFS pointers are rejected; historical transport restoration is not
supported by this tool.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator


# The candidate repository is never an import source, even for an absolute-file CLI.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.deployment.common import DeploymentError, canonical_json_bytes, strict_json_object
from tools.deployment.dataset_packages import MAX_LOCK_BYTES, parse_lock, read_tile_sets, validate_lock
from tools.deployment.upload_datasets import build_metadata_plan


LOCK_PATH = "config/dataset-releases.lock.json"
PLAN_PATH = "config/dataset-upload-plan.json"
CONFIG_PATHS = {LOCK_PATH, PLAN_PATH}
DATASET_PREFIX = "apps/web/public/datasets/"
GENERATED_PREFIX = DATASET_PREFIX + "generated/"
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024 * 1024
MAX_FILES = 500_000
MAX_TREE_BYTES = 128 * 1024 * 1024
_SOURCE_EXTENSIONS = {
    ".bsa", ".ba2", ".esm", ".esp", ".omwaddon", ".omwgame", ".omwscripts",
    ".fnt", ".dds", ".tga", ".nif", ".kf", ".pex",
}
_SOURCE_DIRECTORIES = {
    "local-data", "data-sources", "input", "inputs", "renders", "raw", "raw-output", "renderer-output",
}
_ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".zst"}
_POINTER = re.compile(
    rb"version https://git-lfs.github.com/spec/v1\noid sha256:([a-f0-9]{64})\nsize (0|[1-9][0-9]*)\n"
)


class GitDatasetError(ValueError):
    """A candidate revision or local object violates the dataset boundary."""


@dataclass(frozen=True)
class Entry:
    path: str
    oid: str
    size: int


def _git_args(repo_root: Path, *args: str) -> list[str]:
    return [
        "git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null",
        "-c", "core.fsmonitor=false", "-c", "protocol.allow=never",
        "-C", str(repo_root), *args,
    ]


def _git_env() -> dict[str, str]:
    # Inherited Git overrides must not redirect object reads or introduce config.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1")
    return env


def _git(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(_git_args(repo_root, *args), env=_git_env(), capture_output=True, check=False)
    if result.returncode:
        raise GitDatasetError("Git object read failed: " + result.stderr.decode("utf-8", errors="replace")[:1000].strip())
    return result.stdout


def _tree(repo_root: Path, revision: str, max_files: int) -> Iterator[tuple[str, str, str, int, str]]:
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            _git_args(repo_root, "ls-tree", "-r", "-z", "--long", revision),
            env=_git_env(), stdout=subprocess.PIPE, stderr=errors,
        )
        assert process.stdout is not None
        total = count = 0
        pending = b""
        try:
            while chunk := process.stdout.read(65536):
                total += len(chunk)
                if total > MAX_TREE_BYTES:
                    raise GitDatasetError("Git tree byte limit exceeded")
                records = (pending + chunk).split(b"\0")
                pending = records.pop()
                if len(pending) > 8192:
                    raise GitDatasetError("Git path length limit exceeded")
                for raw in records:
                    count += 1
                    if count > max_files:
                        raise GitDatasetError("Git tree file count limit exceeded")
                    try:
                        header, path = raw.split(b"\t", 1)
                        mode, kind, oid, size = header.split()
                        yield mode.decode("ascii"), kind.decode("ascii"), oid.decode("ascii"), int(size) if size != b"-" else 0, path.decode("utf-8")
                    except (ValueError, UnicodeDecodeError) as error:
                        raise GitDatasetError("Invalid Git tree record") from error
            if pending or process.wait() != 0:
                errors.seek(0)
                raise GitDatasetError("Git tree read failed: " + errors.read(1000).decode("utf-8", errors="replace"))
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()


@contextmanager
def _blobs(repo_root: Path) -> Iterator[subprocess.Popen[bytes]]:
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            _git_args(repo_root, "cat-file", "--batch"), env=_git_env(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
        )
        try:
            yield process
        finally:
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()


def _read_blob(process: subprocess.Popen[bytes], entry: Entry) -> bytes:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write((entry.oid + "\n").encode("ascii"))
    process.stdin.flush()
    if process.stdout.readline(256) != f"{entry.oid} blob {entry.size}\n".encode("ascii"):
        raise GitDatasetError(f"Unexpected Git blob header: {entry.path}")
    payload = process.stdout.read(entry.size)
    if len(payload) != entry.size or process.stdout.read(1) != b"\n":
        raise GitDatasetError(f"Truncated Git blob: {entry.path}")
    return payload


def _validate_path(path: str) -> None:
    parts = path.split("/")
    if len(path.encode("utf-8")) > 4096 or any(part in {"", ".", ".."} for part in parts):
        raise GitDatasetError(f"Unsafe Git path: {path!r}")
    if "\\" in path or any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise GitDatasetError(f"Unsafe Git path: {path!r}")
    lowered = [part.lower() for part in parts]
    if ".lfsconfig" in lowered:
        raise GitDatasetError(f"Candidate .lfsconfig is forbidden: {path}")
    if any(part in _SOURCE_DIRECTORIES for part in lowered[:-1]):
        raise GitDatasetError(f"Tracked source-input directory is forbidden: {path}")
    suffix = PurePosixPath(lowered[-1]).suffix
    if suffix in _SOURCE_EXTENSIONS:
        raise GitDatasetError(f"Tracked game/mod source asset is forbidden: {path}")
    if suffix in _ARCHIVE_EXTENSIONS:
        raise GitDatasetError(f"Tracked dataset/source archive is forbidden: {path}")


def _json(payload: bytes, path: str) -> None:
    try:
        text = payload.decode("utf-8")
        if path.endswith(".ndjson"):
            for line in text.splitlines():
                if line.strip():
                    json.loads(line)
        else:
            json.loads(text)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise GitDatasetError(f"Dataset JSON is invalid: {path}") from error


def _validate_release_snapshot(repo_root: Path, entries: list[Entry]) -> None:
    by_path = {entry.path: entry for entry in entries}
    if LOCK_PATH not in by_path:
        raise GitDatasetError("Release snapshot requires its committed transport lock")
    if PLAN_PATH not in by_path:
        raise GitDatasetError("Release snapshot requires its committed dataset upload plan")
    with tempfile.TemporaryDirectory(prefix="git-dataset-metadata-") as temporary:
        public = Path(temporary).resolve() / "public"
        public.mkdir()
        with _blobs(repo_root) as blobs:
            lock = parse_lock(_read_blob(blobs, by_path[LOCK_PATH]))
            plan = strict_json_object(_read_blob(blobs, by_path[PLAN_PATH]), "committed dataset upload plan")
            for entry in entries:
                if entry.path.startswith(DATASET_PREFIX):
                    target = public / entry.path.removeprefix("apps/web/public/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(_read_blob(blobs, entry))
        validate_lock(lock, read_tile_sets(public_root=public))
        if canonical_json_bytes(plan) != canonical_json_bytes(build_metadata_plan(public_root=public)):
            raise GitDatasetError("Committed dataset upload plan differs from the verified snapshot metadata")


def _inspect(
    repo_root: Path, revision: str, max_file_bytes: int, max_total_bytes: int, max_files: int,
) -> list[Entry]:
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise GitDatasetError("revision must be a full lowercase 40-character commit SHA")
    if any(value <= 0 for value in (max_file_bytes, max_total_bytes, max_files)):
        raise GitDatasetError("All limits must be positive")
    if _git(repo_root, "cat-file", "-t", revision).strip() != b"commit":
        raise GitDatasetError("revision must identify a commit")
    entries: list[Entry] = []
    total = 0
    seen: set[str] = set()
    with _blobs(repo_root) as blobs:
        for file_mode, kind, oid, size, path in _tree(repo_root, revision, max_files):
            _validate_path(path)
            if path in {"apps", "apps/web", "apps/web/public", DATASET_PREFIX.rstrip("/")} and kind != "tree":
                raise GitDatasetError(f"Dataset parent must be a directory, not a symlink/file: {path}")
            if not path.startswith(DATASET_PREFIX) and path not in CONFIG_PATHS:
                continue
            if file_mode != "100644" or kind != "blob":
                raise GitDatasetError(f"Dataset entry must be a non-executable regular file: {path}")
            if path.casefold() in seen:
                raise GitDatasetError(f"Case-colliding dataset path: {path}")
            seen.add(path.casefold())
            if size > (min(max_file_bytes, MAX_LOCK_BYTES) if path == LOCK_PATH else max_file_bytes):
                raise GitDatasetError(f"Dataset per-file byte limit exceeded: {path}")
            entry = Entry(path, oid, size)
            generated = path.startswith(GENERATED_PREFIX)
            suffix = PurePosixPath(path).suffix
            if suffix not in {".json", ".ndjson", ".webp"}:
                raise GitDatasetError(f"Only JSON metadata and WebP renders are permitted in datasets: {path}")
            if generated and suffix == ".webp":
                raise GitDatasetError("Release snapshots forbid tracked generated WebP tiles")
            payload = _read_blob(blobs, entry)
            if _POINTER.fullmatch(payload):
                raise GitDatasetError("Release snapshots forbid LFS pointers, including metadata WebP")
            if suffix == ".webp":
                if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
                    raise GitDatasetError(f"Dataset WebP header is invalid: {path}")
            else:
                _json(payload, path)
            total += entry.size
            if total > max_total_bytes:
                raise GitDatasetError("Dataset total byte limit exceeded")
            entries.append(entry)
    try:
        _validate_release_snapshot(repo_root, entries)
    except DeploymentError as error:
        raise GitDatasetError(str(error)) from error
    return entries


def _report(entries: list[Entry], revision: str) -> dict[str, object]:
    entries = [entry for entry in entries if entry.path.startswith(DATASET_PREFIX)]
    return {
        "revision": revision,
        "snapshotMode": "releases",
        "fileCount": len(entries),
        "generatedFileCount": sum(entry.path.startswith(GENERATED_PREFIX) for entry in entries),
        "totalBytes": sum(entry.size for entry in entries),
    }


def check_revision(
    *, repo_root: Path, revision: str, max_file_bytes: int = MAX_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES, max_files: int = MAX_FILES,
) -> dict[str, object]:
    entries = _inspect(repo_root, revision, max_file_bytes, max_total_bytes, max_files)
    return _report(entries, revision)


def _no_symlinks(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise GitDatasetError(f"Output/object symlink is forbidden: {component}")


def export_revision(
    *, repo_root: Path, revision: str, output_public_root: Path,
    max_file_bytes: int = MAX_FILE_BYTES, max_total_bytes: int = MAX_TOTAL_BYTES,
    max_files: int = MAX_FILES, output_config_root: Path | None = None,
) -> dict[str, object]:
    """Export only committed data; config defaults to output_public_root/config.

    Release output intentionally has no generated tiles. Pass the exported lock
    explicitly to the trusted downloader before validating the complete graph.
    """
    entries = _inspect(repo_root, revision, max_file_bytes, max_total_bytes, max_files)
    output_public_root = output_public_root.absolute()
    _no_symlinks(output_public_root)
    output_public_root = Path(os.path.abspath(output_public_root))
    destination = output_public_root / "datasets"
    if destination.exists() or destination.is_symlink():
        raise GitDatasetError(f"Output dataset tree already exists: {destination}")
    config_destination = (output_config_root or output_public_root / "config").absolute()
    _no_symlinks(config_destination)
    config_destination = Path(os.path.abspath(config_destination))
    if config_destination == destination or destination in config_destination.parents or config_destination in destination.parents:
        raise GitDatasetError("Config output must not overlap the dataset tree")
    if any(entry.path in CONFIG_PATHS for entry in entries) and config_destination.exists():
        raise GitDatasetError(f"Output config tree already exists: {config_destination}")
    # Validate in a private staging tree, so corrupt/missing objects publish nothing.
    with tempfile.TemporaryDirectory(prefix="git-datasets-") as temporary:
        staging = Path(temporary) / "datasets"
        staging.mkdir()
        config_staging = Path(temporary) / "config"
        with _blobs(repo_root) as blobs:
            for entry in entries:
                target = (config_staging / Path(entry.path).name if entry.path in CONFIG_PATHS
                          else staging / entry.path.removeprefix(DATASET_PREFIX))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_read_blob(blobs, entry))
        output_public_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging, destination)
        if config_staging.exists():
            shutil.copytree(config_staging, config_destination)
    return _report(entries, revision)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "export"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-public-root", type=Path)
    parser.add_argument("--output-config-root", type=Path)
    parser.add_argument("--max-file-bytes", type=int, default=MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=MAX_TOTAL_BYTES)
    parser.add_argument("--max-files", type=int, default=MAX_FILES)
    args = parser.parse_args()
    kwargs = dict(repo_root=args.repo_root, revision=args.revision, max_file_bytes=args.max_file_bytes, max_total_bytes=args.max_total_bytes, max_files=args.max_files)
    try:
        if args.command == "export":
            if args.output_public_root is None:
                parser.error("export requires --output-public-root")
            report = export_revision(**kwargs, output_public_root=args.output_public_root, output_config_root=args.output_config_root)
        else:
            report = check_revision(**kwargs)
    except (GitDatasetError, OSError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
