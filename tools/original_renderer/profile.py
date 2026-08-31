from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


PROFILE_ID = "original-goty-hd"
OPENMW_RELEASE = "openmw-0.51.0"
OPENMW_COMMIT = "f4bec41444214a7903bebd178389ca22ca13f646"
OPENMW_SOURCE_URL = "https://gitlab.com/OpenMW/openmw.git"
DOCKER_PLATFORM = "linux/amd64"
UBUNTU_SNAPSHOT = "20260826T000000Z"
DOCKER_BASE_IMAGE = (
    "ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517"
)
DEFAULT_DOCKER_IMAGE = "morrowind-map-openmw:0.51.0-original-hd-v1"


@dataclass(frozen=True, slots=True)
class SourceInput:
    logical_id: str
    relative_path: str
    sha256: str


# The exact English GOTY input allowlist.  No Tamriel Data, Tamriel Rebuilt,
# Fullrest, loose asset, or optional plugin path is accepted by this profile.
SOURCE_INPUTS = (
    SourceInput(
        "morrowind-esm",
        "bsa/Morrowind.esm",
        "5c3c8c2cbd20e25901b59b3ece33d36b7ef0e3d60ad8d11828bcc61a5ead1647",
    ),
    SourceInput(
        "tribunal-esm",
        "bsa/Tribunal.esm",
        "2ace511f23cc2a9ddd5f3aa59c7919789b9378cf4b17c8ae3375dd6b782f3f2b",
    ),
    SourceInput(
        "bloodmoon-esm",
        "bsa/Bloodmoon.esm",
        "bd27090d0e6ad4c1bf1abc83f1a2dac56fcc82cae7bfe8263c413fb301801357",
    ),
    SourceInput(
        "morrowind-bsa",
        "bsa/Morrowind.bsa",
        "3dcd5e6bfa08245521a53374bf733ee5c920df49103898a15aa31144ad64cf48",
    ),
    SourceInput(
        "tribunal-bsa",
        "bsa/Tribunal.bsa",
        "3901e7a146f7a64a4ae9534c80d5974f7ab15adf5c48c4561d9313c0f7831d69",
    ),
    SourceInput(
        "bloodmoon-bsa",
        "bsa/Bloodmoon.bsa",
        "7c20956791400d958cb407f0b7c1c19ceaf46719df7eb724d0b450299360bd7c",
    ),
)

DATA_DIRECTORIES = ("bsa",)
FALLBACK_ARCHIVES = ("Morrowind.bsa", "Tribunal.bsa", "Bloodmoon.bsa")
CONTENT_FILES = ("Morrowind.esm", "Tribunal.esm", "Bloodmoon.esm")
EXCLUDED_DYNAMIC_CONTENT_FILES: tuple[str, ...] = ()

EXPECTED_ASSET_TREE = {
    "files": 6,
    "bytes": 587_905_891,
    "sha256": "42574edf6a23720a2a455d2a3f1b899aa541da330450856e546c5c735fad8083",
}


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source_inputs(
    source_root: Path,
    inputs: Iterable[SourceInput] = SOURCE_INPUTS,
) -> dict[str, dict[str, object]]:
    expected = tuple(inputs)
    if expected != SOURCE_INPUTS:
        raise ValueError("Original GOTY source input allowlist cannot be overridden")
    audit: dict[str, dict[str, object]] = {}
    for source in expected:
        path = source_root / source.relative_path
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"Required Original GOTY input is missing or unsafe: {path}")
        actual = sha256_file(path)
        if actual != source.sha256:
            raise ValueError(
                f"Original GOTY input hash mismatch for {source.relative_path}: "
                f"expected {source.sha256}, got {actual}"
            )
        audit[source.logical_id] = {
            "relativePath": source.relative_path,
            "bytes": path.stat().st_size,
            "sha256": actual,
        }
    return audit


def fingerprint_data_directories(source_root: Path) -> dict[str, dict[str, object]]:
    root = source_root / "bsa"
    if not root.is_dir() or root.is_symlink():
        raise FileNotFoundError(f"Required Original GOTY data directory is missing: {root}")
    entries: list[tuple[str, int, str]] = []
    normalized_paths: set[str] = set()
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix().casefold()):
        if path.is_symlink():
            raise ValueError(f"Original GOTY data directory cannot contain symlinks: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        normalized = relative.casefold()
        if normalized in normalized_paths:
            raise ValueError(f"Case-insensitive Original GOTY resource collision: {relative}")
        normalized_paths.add(normalized)
        entries.append((relative, path.stat().st_size, sha256_file(path)))

    allowed = {Path(item.relative_path).name for item in SOURCE_INPUTS}
    actual = {relative for relative, _, _ in entries}
    if actual != allowed:
        missing = sorted(allowed - actual)
        extra = sorted(actual - allowed)
        raise ValueError(
            "Original GOTY bsa mount must contain exactly the six pinned files: "
            f"missing={missing!r}, extra={extra!r}"
        )

    digest = hashlib.sha256()
    for relative, byte_length, file_hash in entries:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(byte_length).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    value = {
        "files": len(entries),
        "bytes": sum(entry[1] for entry in entries),
        "sha256": digest.hexdigest(),
    }
    if value != EXPECTED_ASSET_TREE:
        raise ValueError(f"Original GOTY asset tree does not match the pinned release: {value}")
    return {"bsa": value}


def _quoted_path(root: PurePosixPath, relative: str) -> str:
    value = str(root / PurePosixPath(relative))
    if '"' in value or "\n" in value or "\r" in value:
        raise ValueError("OpenMW data paths cannot contain quotes or newlines")
    return f'"{value}"'


def render_openmw_cfg(*, game_root: PurePosixPath = PurePosixPath("/game")) -> str:
    lines = [
        "# Generated by morrowind-map Stage 4.5. Do not edit.",
        "replace=config",
        "encoding=win1252",
    ]
    lines.extend(f"fallback-archive={archive}" for archive in FALLBACK_ARCHIVES)
    lines.extend(f"data={_quoted_path(game_root, relative)}" for relative in DATA_DIRECTORIES)
    lines.extend(f"content={content}" for content in CONTENT_FILES)
    # OpenMW's generic weather defaults request tx_sky_snow.dds and
    # tx_sky_blizzard.dds, which do not exist in the pinned Bloodmoon BSA.
    # These are the canonical aliases used by the proven Poison renderer and
    # map the generic settings to Bethesda's shipped Bloodmoon texture names.
    lines.extend(
        (
            "fallback=Weather_Snow_Cloud_Texture,Tx_BM_Sky_Snow.dds",
            "fallback=Weather_Blizzard_Cloud_Texture,Tx_BM_Sky_Blizzard.dds",
        )
    )
    return "\n".join(lines) + "\n"


def render_settings_cfg() -> str:
    return """# Generated by morrowind-map Stage 4.5. Do not edit.
[Cells]
preload enabled = false
preload num threads = 1

[GUI]
scaling factor = 1.0

[Map]
local map resolution = 512
local map widget size = 512
max local viewing distance = 1

[Terrain]
distant terrain = false
object paging = false
object paging active grid = false
water culling = false

[Video]
resolution x = 640
resolution y = 480
window mode = 2
antialiasing = 0
vsync mode = 0
framerate limit = 60

[Water]
shader = false
refraction = false
reflection detail = 0
wobbly shores = false

[Shadows]
enable shadows = false
actor shadows = false
player shadows = false
terrain shadows = false
object shadows = false
"""


def render_console_script(cell: tuple[int, int]) -> str:
    return f"coe {cell[0]} {cell[1]}\n"


def profile_fingerprint(
    input_audit: dict[str, dict[str, object]],
    *,
    asset_audit: dict[str, dict[str, object]] | None = None,
    openmw_cfg: str | None = None,
    settings_cfg: str | None = None,
) -> str:
    payload = {
        "profileId": PROFILE_ID,
        "openmwCommit": OPENMW_COMMIT,
        "dockerPlatform": DOCKER_PLATFORM,
        "dockerBaseImage": DOCKER_BASE_IMAGE,
        "ubuntuSnapshot": UBUNTU_SNAPSHOT,
        "dataDirectories": DATA_DIRECTORIES,
        "fallbackArchives": FALLBACK_ARCHIVES,
        "contentFiles": CONTENT_FILES,
        "excludedDynamicContentFiles": EXCLUDED_DYNAMIC_CONTENT_FILES,
        "assetTrees": asset_audit or {},
        "openmwCfg": openmw_cfg if openmw_cfg is not None else render_openmw_cfg(),
        "settingsCfg": settings_cfg if settings_cfg is not None else render_settings_cfg(),
        "inputs": input_audit,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
