"""Shared fail-closed helpers for deployment tooling."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit


_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_DATASET_ID = re.compile(r"^[a-z0-9]+(?:[.:-][a-z0-9]+)*$")


class DeploymentError(ValueError):
    """Raised when a release or deployed runtime violates its contract."""


@dataclass(frozen=True)
class ArtifactDescriptor:
    url: str
    media_type: str
    sha256: str
    byte_count: int | None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "mediaType": self.media_type,
            "sha256": self.sha256,
            "url": self.url,
        }
        if self.byte_count is not None:
            result["bytes"] = self.byte_count
        return result


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
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


def _reject_json_constant(value: str) -> None:
    raise DeploymentError(f"Non-finite JSON number is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DeploymentError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def strict_json_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, DeploymentError) as error:
        raise DeploymentError(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise DeploymentError(f"{label} must be a JSON object")
    return value


def require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DeploymentError(f"{label} must be an object")
    return value


def require_sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise DeploymentError(f"{label} must be an array")
    return value


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeploymentError(f"{label} must be a non-empty string")
    return value


def require_dataset_id(value: object, label: str) -> str:
    result = require_string(value, label)
    if _DATASET_ID.fullmatch(result) is None:
        raise DeploymentError(f"{label} is not a safe identifier: {result!r}")
    return result


def require_integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DeploymentError(f"{label} must be an integer >= {minimum}")
    return value


def require_sha256(value: object, label: str) -> str:
    result = require_string(value, label)
    if _SHA256.fullmatch(result) is None:
        raise DeploymentError(f"{label} is not a lowercase SHA-256")
    return result


def public_path(value: object, label: str, *, template: bool = False) -> str:
    url = require_string(value, label)
    parsed = urlsplit(url)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not url.startswith("/")
        or url.startswith("//")
        or "\\" in url
        or "\x00" in url
        or "%" in url
        or any(character.isspace() for character in url)
    ):
        raise DeploymentError(f"{label} must be a canonical same-origin absolute path: {url!r}")
    relative = url[1:]
    if template:
        for token in ("{z}", "{x}", "{y}"):
            if relative.count(token) != 1:
                raise DeploymentError(f"{label} must contain exactly one {token}")
        relative = relative.replace("{z}", "0").replace("{x}", "0").replace("{y}", "0")
    pure = PurePosixPath(relative)
    if (
        not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise DeploymentError(f"{label} contains an unsafe path: {url!r}")
    if not url.startswith("/datasets/") and not url.startswith("/assets/"):
        raise DeploymentError(f"{label} is outside the public runtime roots: {url!r}")
    return url


def relative_public_path(url: str) -> Path:
    return Path(*PurePosixPath(url[1:]).parts)


def content_addressed_path(
    value: object,
    label: str,
    *,
    dataset_id: str,
    template: bool = False,
) -> str:
    url = public_path(value, label, template=template)
    parts = PurePosixPath(url).parts
    if (
        len(parts) < 6
        or parts[1] != "datasets"
        or parts[2] not in {"generated", "metadata"}
        or parts[3] != dataset_id
    ):
        raise DeploymentError(f"{label} is outside the content-addressed dataset root: {url}")
    hash_position = 5 if parts[4] == "catalogs" else 4
    if len(parts) <= hash_position + 1 or _SHA256.fullmatch(parts[hash_position]) is None:
        raise DeploymentError(f"{label} does not contain an immutable SHA-256 path segment: {url}")
    return url


def artifact_descriptor(
    value: object,
    label: str,
    *,
    url_key: str = "url",
    require_bytes: bool = True,
) -> ArtifactDescriptor:
    descriptor = require_mapping(value, label)
    url = public_path(descriptor.get(url_key), f"{label}.{url_key}")
    media_type = require_string(descriptor.get("mediaType"), f"{label}.mediaType")
    digest = require_sha256(descriptor.get("sha256"), f"{label}.sha256")
    byte_count = (
        require_integer(descriptor.get("bytes"), f"{label}.bytes", minimum=1)
        if require_bytes
        else None
    )
    return ArtifactDescriptor(url, media_type, digest, byte_count)


def verify_artifact(payload: bytes, descriptor: ArtifactDescriptor, label: str) -> None:
    if descriptor.byte_count is not None and len(payload) != descriptor.byte_count:
        raise DeploymentError(
            f"{label} has {len(payload)} bytes, expected {descriptor.byte_count}"
        )
    actual = sha256_bytes(payload)
    if actual != descriptor.sha256:
        raise DeploymentError(f"{label} SHA-256 is {actual}, expected {descriptor.sha256}")


def absolute_directory(path: Path, label: str) -> Path:
    result = Path(os.path.abspath(os.fspath(path)))
    if result.is_symlink() or not result.is_dir():
        raise DeploymentError(f"{label} must be a real directory: {result}")
    return result


def safe_file(root: Path, relative: Path, label: str) -> Path:
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise DeploymentError(f"{label} is unsafe: {relative}")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise DeploymentError(f"{label} contains a symlink: {current}")
    try:
        current.relative_to(root)
    except ValueError as error:
        raise DeploymentError(f"{label} escapes its root: {current}") from error
    if not current.is_file():
        raise DeploymentError(f"{label} is missing: {current}")
    return current
