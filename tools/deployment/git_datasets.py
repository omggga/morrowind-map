"""Inspect and export dataset objects without checking out or running candidate code.

Invoke a trusted copy by absolute path; all imports resolve from that trusted tree.
Legacy Git LFS objects must already be fetched using a trusted endpoint. Release
snapshots export metadata only, for a separate trusted downloader. At cutover,
trusted callers must pin --release-boundary or use --require-releases: shallow
history alone cannot prove that a missing lock belongs to a historical snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
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
MAX_POINTER_BYTES = 200
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
    lfs_oid: str | None = None
    lfs_size: int | None = None

    @property
    def output_size(self) -> int:
        return self.lfs_size if self.lfs_size is not None else self.size


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
        raise GitDatasetError(f"Candidate .lfsconfig is forbidden; use trusted LFS configuration: {path}")
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


def _snapshot_mode(repo_root: Path, revision: str, *, has_lock: bool,
                   mode: str, release_boundary: str | None) -> str:
    if mode not in {"auto", "legacy", "releases"}:
        raise GitDatasetError("Snapshot mode must be auto, legacy or releases")
    required = mode == "releases"
    if release_boundary is not None:
        if not re.fullmatch(r"[a-f0-9]{40}", release_boundary):
            raise GitDatasetError("release boundary must be a full lowercase 40-character commit SHA")
        if _git(repo_root, "cat-file", "-t", release_boundary).strip() != b"commit":
            raise GitDatasetError("release boundary must identify a locally available commit")
        def ancestor(left: str, right: str) -> bool:
            result = subprocess.run(_git_args(repo_root, "merge-base", "--is-ancestor", left, right),
                                    env=_git_env(), capture_output=True, check=False)
            if result.returncode not in (0, 1):
                raise GitDatasetError("Cannot establish trusted release boundary ancestry")
            return result.returncode == 0
        if ancestor(release_boundary, revision):
            required = True
        elif not ancestor(revision, release_boundary):
            raise GitDatasetError("Cannot prove snapshot precedes trusted release boundary; fetch trusted history")
    # Full history also catches deletion, rename, and merge-side lock introductions.
    history = _git(repo_root, "log", "--full-history", "--format=%H", "-1", revision, "--", LOCK_PATH)
    required = required or bool(history.strip()) or has_lock
    if required and mode == "legacy":
        raise GitDatasetError("Release snapshot cannot downgrade to legacy LFS mode")
    if required and not has_lock:
        raise GitDatasetError("Release snapshot requires its committed transport lock; legacy downgrade is forbidden")
    return "releases" if required else "legacy"


def _validate_release_snapshot(repo_root: Path, entries: list[Entry]) -> None:
    by_path = {entry.path: entry for entry in entries}
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
    mode: str = "auto", release_boundary: str | None = None,
) -> tuple[list[Entry], str]:
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
            if generated and suffix == ".webp" and size > MAX_POINTER_BYTES:
                raise GitDatasetError(f"Generated WebP must be a canonical Git LFS pointer: {path}")
            payload = _read_blob(blobs, entry)
            pointer = _POINTER.fullmatch(payload) if suffix == ".webp" else None
            if pointer:
                entry = Entry(path, oid, size, pointer[1].decode("ascii"), int(pointer[2]))
            elif generated and suffix == ".webp":
                raise GitDatasetError(f"Generated WebP must be a canonical Git LFS pointer: {path}")
            elif suffix == ".webp":
                if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
                    raise GitDatasetError(f"Dataset WebP header is invalid: {path}")
            else:
                _json(payload, path)
            if entry.output_size > max_file_bytes:
                raise GitDatasetError(f"Dataset per-file byte limit exceeded: {path}")
            total += entry.output_size
            if total > max_total_bytes:
                raise GitDatasetError("Dataset total byte limit exceeded")
            entries.append(entry)
    try:
        snapshot_mode = _snapshot_mode(repo_root, revision, has_lock=any(e.path == LOCK_PATH for e in entries),
                                       mode=mode, release_boundary=release_boundary)
        if snapshot_mode == "releases":
            if any(e.path.startswith(GENERATED_PREFIX) and e.path.endswith(".webp") for e in entries):
                raise GitDatasetError("Release snapshots forbid tracked generated WebP tiles")
            if any(entry.lfs_oid is not None for entry in entries):
                raise GitDatasetError("Release snapshots forbid LFS pointers, including metadata WebP")
            _validate_release_snapshot(repo_root, entries)
    except DeploymentError as error:
        raise GitDatasetError(str(error)) from error
    return entries, snapshot_mode


def _report(entries: list[Entry], revision: str, snapshot_mode: str) -> dict[str, object]:
    entries = [entry for entry in entries if entry.path.startswith(DATASET_PREFIX)]
    return {
        "revision": revision,
        "snapshotMode": snapshot_mode,
        "fileCount": len(entries),
        "generatedFileCount": sum(entry.path.startswith(GENERATED_PREFIX) for entry in entries),
        "lfsFileCount": sum(entry.lfs_oid is not None for entry in entries),
        "totalBytes": sum(entry.output_size for entry in entries),
    }


def check_revision(
    *, repo_root: Path, revision: str, max_file_bytes: int = MAX_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES, max_files: int = MAX_FILES,
    mode: str = "auto", release_boundary: str | None = None,
) -> dict[str, object]:
    entries, snapshot_mode = _inspect(repo_root, revision, max_file_bytes, max_total_bytes, max_files,
                                      mode, release_boundary)
    return _report(entries, revision, snapshot_mode)


def _no_symlinks(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise GitDatasetError(f"Output/object symlink is forbidden: {component}")


def _copy_lfs(git_dir: Path, entry: Entry, target: Path) -> None:
    assert entry.lfs_oid is not None and entry.lfs_size is not None
    oid = entry.lfs_oid
    source = git_dir / "lfs/objects" / oid[:2] / oid[2:4] / oid
    _no_symlinks(source)
    try:
        with source.open("rb") as stream, target.open("xb") as output:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or os.fstat(stream.fileno()).st_size != entry.lfs_size:
                raise GitDatasetError(f"LFS object size/type mismatch: {entry.path}")
            digest = hashlib.sha256()
            count = 0
            prefix = b""
            while chunk := stream.read(min(1024 * 1024, entry.lfs_size - count + 1)):
                count += len(chunk)
                if count > entry.lfs_size:
                    raise GitDatasetError(f"LFS object exceeds declared size: {entry.path}")
                if len(prefix) < 12:
                    prefix += chunk[:12 - len(prefix)]
                digest.update(chunk)
                output.write(chunk)
            if count != entry.lfs_size or digest.hexdigest() != oid:
                raise GitDatasetError(f"LFS object SHA-256/size mismatch: {entry.path}")
            if len(prefix) < 12 or prefix[:4] != b"RIFF" or prefix[8:12] != b"WEBP":
                raise GitDatasetError(f"LFS object is not a WebP render: {entry.path}")
    except OSError as error:
        raise GitDatasetError(f"LFS object missing or unreadable for {entry.path}: {error}") from error


def export_revision(
    *, repo_root: Path, revision: str, output_public_root: Path,
    max_file_bytes: int = MAX_FILE_BYTES, max_total_bytes: int = MAX_TOTAL_BYTES,
    max_files: int = MAX_FILES, mode: str = "auto", release_boundary: str | None = None,
    output_config_root: Path | None = None,
) -> dict[str, object]:
    """Export only committed data; config defaults to output_public_root/config.

    Release output intentionally has no generated tiles. Pass the exported lock
    explicitly to the trusted downloader before validating the complete graph.
    """
    entries, snapshot_mode = _inspect(repo_root, revision, max_file_bytes, max_total_bytes, max_files,
                                      mode, release_boundary)
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
    git_dir = Path(os.fsdecode(_git(repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()))
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
                if entry.lfs_oid:
                    _copy_lfs(git_dir, entry, target)
                else:
                    target.write_bytes(_read_blob(blobs, entry))
        output_public_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging, destination)
        if config_staging.exists():
            shutil.copytree(config_staging, config_destination)
    return _report(entries, revision, snapshot_mode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "export"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-public-root", type=Path)
    parser.add_argument("--output-config-root", type=Path)
    parser.add_argument("--mode", choices=("auto", "legacy", "releases"), default="auto")
    parser.add_argument("--require-releases", action="store_true")
    parser.add_argument("--release-boundary", help="Trusted first release-backed commit SHA")
    parser.add_argument("--max-file-bytes", type=int, default=MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=MAX_TOTAL_BYTES)
    parser.add_argument("--max-files", type=int, default=MAX_FILES)
    args = parser.parse_args()
    kwargs = dict(repo_root=args.repo_root, revision=args.revision, max_file_bytes=args.max_file_bytes, max_total_bytes=args.max_total_bytes, max_files=args.max_files, mode="releases" if args.require_releases else args.mode, release_boundary=args.release_boundary)
    if args.require_releases and args.mode == "legacy":
        parser.error("--require-releases conflicts with --mode legacy")
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
