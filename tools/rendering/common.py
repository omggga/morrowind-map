from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_PROFILES = {
    "tamriel-rebuilt": "tr-release.json",
    "project-cyrodiil": "pc-release.json",
    "home-of-nords": "shotn-release.json",
}


def run_module(module: str, args: Sequence[str]) -> None:
    """Pipeline identities are process-local; never activate two in one process."""
    subprocess.run([sys.executable, "-m", module, *map(str, args)], cwd=REPO_ROOT, check=True)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def safe_path(path: Path, boundary: Path) -> Path:
    """Reject traversal and symlinks before reading or writing a workspace path."""
    boundary = boundary.resolve()
    path = Path(os.path.abspath(path))
    if path != boundary and boundary not in path.parents:
        raise ValueError(f"Path escapes workspace: {path}")
    current = path
    while current != boundary:
        if current.is_symlink():
            raise ValueError(f"Symlink in workspace path: {current}")
        current = current.parent
    return path


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            with source.open("rb") as reader:
                shutil.copyfileobj(reader, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def copy_public_tree(source_public: Path, target_public: Path) -> None:
    """Copy a browser dataset baseline without linking mutable candidate files."""
    from tools.deployment.upload_datasets import build_dataset_plan

    source = Path(os.path.abspath(source_public))
    target = Path(os.path.abspath(target_public))
    for path in (source, target):
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError(f"Public trees must not contain symlink ancestors: {path}")
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Candidate public tree must be separate from its baseline")
    plan = build_dataset_plan(public_root=source)
    receipt = target / ".render-baseline.json"
    # Resume must preserve a candidate already assembled by the same pipeline,
    # but never combine it with a different baseline during render:all.
    if (target / "datasets/index.json").is_file():
        if not receipt.is_file() or receipt.is_symlink():
            raise ValueError("Existing candidate has no baseline receipt; choose a new work root")
        if json.loads(receipt.read_text()).get("graphSha256") != plan["graphSha256"]:
            raise ValueError("Candidate baseline changed; choose a new work root")
        return
    target.mkdir(parents=True, exist_ok=True)
    for current, directories, filenames in os.walk(source, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(source)
        for name in directories:
            if (current_path / name).is_symlink():
                raise ValueError(f"Symlink in baseline: {current_path / name}")
        if relative == Path("datasets"):
            directories[:] = [name for name in directories if name != "generated"]
        for name in filenames:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Unsafe baseline file: {path}")
            # Write the index last; an interrupted copy is safe to retry.
            if relative / name == Path("datasets/index.json"):
                continue
            destination = safe_path(target / relative / name, target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_copy(path, destination)
    for entry in plan["files"]:
        relative = Path("datasets/generated") / entry["path"]
        destination = safe_path(target / relative, target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_copy(source / relative, destination)
    (target / "datasets").mkdir(exist_ok=True)
    write_json(receipt, {"graphSha256": plan["graphSha256"]})
    for name in RELEASE_PROFILES.values():
        profile = source.parent / name
        if profile.is_file():
            safe_path(profile, source.parent)
            atomic_copy(profile, target.parent / name)
    atomic_copy(source / "datasets/index.json", safe_path(target / "datasets/index.json", target))
