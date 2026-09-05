"""Remote, standard-library-only installer for verified dataset payloads.

This module is sent to ``python3 -`` over SSH by ``upload_datasets``.  Keep it
free of project imports so the destination host needs only Python 3.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator


DATA_ROOT = Path("/srv/morrowind-map/data")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_UPLOAD_ID = re.compile(r"^[a-f0-9]{32}$")


class RemoteInstallError(ValueError):
    """Raised when a staged payload is unsafe or differs from its plan."""


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RemoteInstallError(f"{label} must be a non-empty POSIX path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or pure.as_posix() != value or any(
        part in {"", ".", ".."} for part in pure.parts
    ):
        raise RemoteInstallError(f"{label} is unsafe: {value!r}")
    return Path(*pure.parts)


def _load_plan(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RemoteInstallError(f"Upload plan is missing: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RemoteInstallError("Upload plan is not UTF-8 JSON") from error
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise RemoteInstallError("Upload plan schemaVersion must be 1")
    graph_sha = value.get("graphSha256")
    if not isinstance(graph_sha, str) or _SHA256.fullmatch(graph_sha) is None:
        raise RemoteInstallError("Upload plan graphSha256 is invalid")
    core = dict(value)
    del core["graphSha256"]
    actual = hashlib.sha256(_canonical_json_bytes(core)).hexdigest()
    if actual != graph_sha:
        raise RemoteInstallError(
            f"Upload plan graph SHA-256 is {actual}, expected {graph_sha}"
        )
    return value


def _expected_files(plan: dict[str, object]) -> dict[str, tuple[int, str]]:
    raw_files = plan.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise RemoteInstallError("Upload plan files must be a non-empty array")
    expected: dict[str, tuple[int, str]] = {}
    folded: set[str] = set()
    total = 0
    for index, raw in enumerate(raw_files):
        if not isinstance(raw, dict):
            raise RemoteInstallError(f"Upload plan file {index} must be an object")
        relative = _safe_relative(raw.get("path"), f"Upload plan file {index} path")
        text = relative.as_posix()
        lowered = text.casefold()
        if text in expected or lowered in folded:
            raise RemoteInstallError(f"Duplicate upload path: {text}")
        byte_count = raw.get("bytes")
        digest = raw.get("sha256")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 1:
            raise RemoteInstallError(f"Upload plan file {text} bytes are invalid")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise RemoteInstallError(f"Upload plan file {text} SHA-256 is invalid")
        expected[text] = (byte_count, digest)
        folded.add(lowered)
        total += byte_count
    if plan.get("fileCount") != len(expected) or plan.get("totalBytes") != total:
        raise RemoteInstallError("Upload plan totals differ from its file records")
    return expected


def verify_tree(root: Path, plan: dict[str, object]) -> None:
    """Verify that ``root`` contains exactly the plan and no stale payload."""

    if root.is_symlink() or not root.is_dir():
        raise RemoteInstallError(f"Dataset payload must be a real directory: {root}")
    expected = _expected_files(plan)
    seen: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as stream:
            entries = sorted(stream, key=lambda entry: entry.name)
        for entry in entries:
            path = Path(entry.path)
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                raise RemoteInstallError(f"Dataset payload contains a symlink: {path}")
            if stat.S_ISDIR(mode):
                pending.append(path)
                continue
            if not stat.S_ISREG(mode):
                raise RemoteInstallError(f"Dataset payload contains a non-file: {path}")
            relative = path.relative_to(root).as_posix()
            binding = expected.get(relative)
            if binding is None:
                raise RemoteInstallError(f"Unexpected dataset payload file: {relative}")
            byte_count, digest = binding
            if path.stat().st_size != byte_count or _sha256_file(path) != digest:
                raise RemoteInstallError(f"Dataset payload file failed integrity: {relative}")
            seen.add(relative)
    missing = sorted(set(expected) - seen)
    if missing:
        raise RemoteInstallError("Dataset payload files are missing: " + ", ".join(missing[:10]))


def _normalize_public_permissions(root: Path) -> None:
    """Make a verified release traversable and readable by the web server."""

    root.chmod(0o755)
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as stream:
            entries = list(stream)
        for entry in entries:
            path = Path(entry.path)
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                raise RemoteInstallError(
                    f"Dataset payload changed after verification: {path}"
                )
            if stat.S_ISDIR(mode):
                path.chmod(0o755)
                pending.append(path)
            elif stat.S_ISREG(mode):
                path.chmod(0o644)
            else:
                raise RemoteInstallError(
                    f"Dataset payload changed after verification: {path}"
                )


def _require_layout(data_root: Path) -> tuple[Path, Path]:
    if not data_root.is_absolute() or data_root == Path("/"):
        raise RemoteInstallError("Dataset data root must be a narrow absolute path")
    if data_root.is_symlink() or not data_root.is_dir():
        raise RemoteInstallError(f"Dataset data root must be a real directory: {data_root}")
    releases = data_root / "releases"
    incoming = data_root / "incoming"
    for directory in (releases, incoming):
        directory.mkdir(mode=0o750, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise RemoteInstallError(f"Dataset deployment directory is unsafe: {directory}")
    return releases, incoming


def _stage_path(data_root: Path, upload_id: str) -> Path:
    if _UPLOAD_ID.fullmatch(upload_id) is None:
        raise RemoteInstallError("Upload id must be 32 lowercase hexadecimal characters")
    return data_root / "incoming" / upload_id


@contextmanager
def _deployment_lock(data_root: Path) -> Iterator[None]:
    lock_path = data_root / ".dataset-upload.lock"
    if lock_path.is_symlink():
        raise RemoteInstallError(f"Dataset upload lock cannot be a symlink: {lock_path}")
    with lock_path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield


def prepare_stage(data_root: Path, upload_id: str) -> Path:
    _, incoming = _require_layout(data_root)
    stage = _stage_path(data_root, upload_id)
    with _deployment_lock(data_root):
        if stage.exists() or stage.is_symlink():
            raise RemoteInstallError(f"Upload stage already exists: {stage}")
        (stage / "payload").mkdir(parents=True, mode=0o750)
    if stage.parent != incoming:
        raise RemoteInstallError("Upload stage escaped the incoming directory")
    return stage


def abort_stage(data_root: Path, upload_id: str) -> None:
    """Remove only the named incomplete upload, leaving active data untouched."""

    _, incoming = _require_layout(data_root)
    stage = _stage_path(data_root, upload_id)
    with _deployment_lock(data_root):
        if stage.exists() or stage.is_symlink():
            _remove_child(incoming, stage)


def _remove_child(parent: Path, child: Path) -> None:
    if child.parent != parent:
        raise RemoteInstallError(f"Refusing to remove a path outside {parent}: {child}")
    mode = child.lstat().st_mode
    if stat.S_ISDIR(mode):
        shutil.rmtree(child)
    else:
        child.unlink()


def _cleanup_completed_stage(
    incoming: Path,
    *,
    completed_stage: Path,
) -> None:
    """Remove this upload's staging files; app releases may reference any graph."""

    if completed_stage.parent != incoming:
        raise RemoteInstallError("Completed stage escaped the fixed incoming namespace")
    if completed_stage.exists() or completed_stage.is_symlink():
        _remove_child(incoming, completed_stage)


def _activate(data_root: Path, release: Path, upload_id: str) -> None:
    generated = data_root / "generated"
    if generated.exists() and not generated.is_symlink():
        raise RemoteInstallError(
            f"Refusing to replace non-symlink generated path: {generated}"
        )
    temporary_link = data_root / f".generated-{upload_id}.tmp"
    if temporary_link.exists() or temporary_link.is_symlink():
        temporary_link.unlink()
    os.symlink(Path("releases") / release.name, temporary_link)
    os.replace(temporary_link, generated)


def probe_installed(data_root: Path, upload_id: str, *, stage_only: bool = False) -> bool:
    releases, incoming = _require_layout(data_root)
    stage = _stage_path(data_root, upload_id)
    plan = _load_plan(stage / "plan.json")
    graph_sha = str(plan["graphSha256"])
    release = releases / graph_sha
    with _deployment_lock(data_root):
        if not release.exists():
            return False
        verify_tree(release, plan)
        _normalize_public_permissions(release)
        if not stage_only:
            _activate(data_root, release, upload_id)
        _cleanup_completed_stage(
            incoming,
            completed_stage=stage,
        )
    return True


def install_stage(data_root: Path, upload_id: str, *, stage_only: bool = False) -> Path:
    releases, incoming = _require_layout(data_root)
    stage = _stage_path(data_root, upload_id)
    plan = _load_plan(stage / "plan.json")
    payload = stage / "payload"
    graph_sha = str(plan["graphSha256"])
    release = releases / graph_sha
    with _deployment_lock(data_root):
        verify_tree(payload, plan)
        if release.exists():
            verify_tree(release, plan)
            shutil.rmtree(payload)
        else:
            os.replace(payload, release)
        _normalize_public_permissions(release)
        if not stage_only:
            _activate(data_root, release, upload_id)
        _cleanup_completed_stage(
            incoming,
            completed_stage=stage,
        )
    return release


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2 or arguments[0] not in {
        "abort",
        "prepare",
        "probe",
        "probe-stage",
        "install",
        "install-stage",
    }:
        print(
            "usage: dataset_remote.py {abort|prepare|probe|probe-stage|install|install-stage} UPLOAD_ID",
            file=sys.stderr,
        )
        return 2
    action, upload_id = arguments
    try:
        if action == "abort":
            abort_stage(DATA_ROOT, upload_id)
            result = "aborted"
        elif action == "prepare":
            prepare_stage(DATA_ROOT, upload_id)
            result = "prepared"
        elif action in {"probe", "probe-stage"}:
            result = "installed" if probe_installed(DATA_ROOT, upload_id, stage_only=action == "probe-stage") else "upload"
        else:
            install_stage(DATA_ROOT, upload_id, stage_only=action == "install-stage")
            result = "installed"
    except (OSError, RemoteInstallError) as error:
        print(f"dataset remote install failed: {error}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
