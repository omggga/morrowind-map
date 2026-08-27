from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from tools.tes3.bsa import BsaArchive, BsaEntry, normalize_resource_path


@dataclass(frozen=True)
class ResolvedResource:
    logical_path: str
    source_kind: Literal["bsa", "loose"]
    source_path: Path
    archive_entry: BsaEntry | None = None
    _archive: BsaArchive | None = field(default=None, repr=False, compare=False)

    def read(self) -> bytes:
        if self.source_kind == "loose":
            return self.source_path.read_bytes()
        if self._archive is None or self.archive_entry is None:
            raise RuntimeError("Incomplete BSA resource descriptor")
        return self._archive.read_entry(self.archive_entry)


class VirtualFileSystem:
    """Case-insensitive TES3 resource overlay with loose-file priority.

    Later mounts win within the archive or loose-file class. Loose resources always
    override archive resources, matching the safe mod-development expectation.
    """

    def __init__(self) -> None:
        self._bsa_entries: dict[str, ResolvedResource] = {}
        self._loose_entries: dict[str, ResolvedResource] = {}
        self._archives: list[BsaArchive] = []

    def mount_bsa(self, path: Path) -> VirtualFileSystem:
        archive = BsaArchive(Path(path))
        self._archives.append(archive)
        for logical_path, entry in archive.entries.items():
            self._bsa_entries[logical_path] = ResolvedResource(
                logical_path=logical_path,
                source_kind="bsa",
                source_path=archive.path,
                archive_entry=entry,
                _archive=archive,
            )
        return self

    def mount_loose(self, root: Path) -> VirtualFileSystem:
        root = Path(root)
        if not root.is_dir():
            raise NotADirectoryError(root)
        resolved_root = root.resolve()
        mounted: dict[str, ResolvedResource] = {}
        candidates = sorted(root.rglob("*"), key=lambda path: path.as_posix().casefold())
        for candidate in candidates:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved_candidate = candidate.resolve()
            if not resolved_candidate.is_relative_to(resolved_root):
                raise ValueError(f"Loose resource escapes mount root: {candidate}")
            relative = candidate.relative_to(root).as_posix()
            logical_path = normalize_resource_path(relative)
            if logical_path in mounted:
                raise ValueError(
                    f"Duplicate case-insensitive loose resource {logical_path!r} in {root}"
                )
            mounted[logical_path] = ResolvedResource(
                logical_path=logical_path,
                source_kind="loose",
                source_path=resolved_candidate,
            )
        self._loose_entries.update(mounted)
        return self

    def resolve(self, logical_path: str) -> ResolvedResource | None:
        key = normalize_resource_path(logical_path)
        return self._loose_entries.get(key) or self._bsa_entries.get(key)

    def read(self, logical_path: str) -> bytes:
        resource = self.resolve(logical_path)
        if resource is None:
            raise FileNotFoundError(f"TES3 resource not found: {logical_path}")
        return resource.read()

    def resolve_texture(self, texture_path: str) -> ResolvedResource | None:
        """Resolve Bethesda/OpenMW texture fallbacks, preferring a DDS asset."""

        separated = texture_path.replace("\\", "/")
        raw_parts = separated.split("/")
        resource_segment = next(
            (
                index
                for index, part in enumerate(raw_parts)
                if part.lower() in ("textures", "bookart")
            ),
            None,
        )
        if resource_segment is not None:
            separated = "/".join(raw_parts[resource_segment:])
        else:
            separated = f"textures/{separated}"
        original = normalize_resource_path(separated)
        parsed = PurePosixPath(original)
        # OpenMW replaces an extension; it does not invent one for extensionless IDs.
        dds = parsed.with_suffix(".dds").as_posix() if parsed.suffix else original
        basename_dds = f"textures/{PurePosixPath(dds).name}"
        basename_original = f"textures/{parsed.name}"
        candidates = tuple(
            dict.fromkeys((dds, original, basename_dds, basename_original))
        )
        for candidate in candidates:
            resource = self.resolve(candidate)
            if resource is not None:
                return resource
        return None


VFS = VirtualFileSystem
