"""Build a deterministic application archive from the active runtime graph only."""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from tools.deployment.common import (
    ArtifactDescriptor,
    DeploymentError,
    absolute_directory,
    artifact_descriptor,
    canonical_json_bytes,
    content_addressed_path,
    public_path,
    relative_public_path,
    require_dataset_id,
    require_integer,
    require_mapping,
    require_sequence,
    require_sha256,
    require_string,
    safe_file,
    sha256_bytes,
    strict_json_object,
    verify_artifact,
)


_COMMIT_SHA = re.compile(r"^[a-f0-9]{40}$")
_DEFAULT_MAX_BYTES = 100 * 1024 * 1024


class _ShellReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: set[str] = set()
        self.module_scripts = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("type") == "module":
            self.module_scripts += 1
        key = "src" if tag in {"script", "img", "source"} else "href"
        value = values.get(key)
        if value and value.startswith("/"):
            self.urls.add(value)


@dataclass
class ReleaseBuilder:
    dist_root: Path
    max_unpacked_bytes: int
    files: dict[str, bytes] = field(default_factory=dict)
    generated: dict[str, dict[str, object]] = field(default_factory=dict)
    datasets: list[dict[str, object]] = field(default_factory=list)

    def add_file(
        self,
        relative: Path,
        label: str,
        descriptor: ArtifactDescriptor | None = None,
    ) -> bytes:
        key = PurePosixPath(*relative.parts).as_posix()
        if key in self.files:
            payload = self.files[key]
        else:
            payload = safe_file(self.dist_root, relative, label).read_bytes()
            self.files[key] = payload
            total = sum(len(item) for item in self.files.values())
            if total > self.max_unpacked_bytes:
                raise DeploymentError(
                    f"Release payload exceeds {self.max_unpacked_bytes} unpacked bytes"
                )
        if descriptor is not None:
            verify_artifact(payload, descriptor, label)
        return payload

    def add_public_artifact(self, descriptor: ArtifactDescriptor, label: str) -> bytes | None:
        if descriptor.url.startswith("/datasets/generated/"):
            existing = self.generated.get(descriptor.url)
            value = descriptor.to_dict()
            if existing is not None and existing != value:
                raise DeploymentError(f"Conflicting descriptors for {descriptor.url}")
            self.generated[descriptor.url] = value
            return None
        if not descriptor.url.startswith("/datasets/metadata/"):
            raise DeploymentError(
                f"{label} must be content-addressed metadata or generated data: {descriptor.url}"
            )
        return self.add_file(relative_public_path(descriptor.url), label, descriptor)

    def collect(self) -> None:
        index_payload = self.add_file(Path("index.html"), "application index")
        self._collect_shell(index_payload)
        index = strict_json_object(
            self.add_file(Path("datasets/index.json"), "dataset index"),
            "dataset index",
        )
        if index.get("schemaVersion") != 1:
            raise DeploymentError("dataset index schemaVersion must be 1")
        entries = require_sequence(index.get("datasets"), "dataset index.datasets")
        if not entries:
            raise DeploymentError("dataset index.datasets cannot be empty")
        seen_ids: set[str] = set()
        for position, raw_entry in enumerate(entries):
            entry = require_mapping(raw_entry, f"dataset index.datasets[{position}]")
            dataset_id = require_dataset_id(entry.get("datasetId"), f"dataset[{position}].datasetId")
            if dataset_id in seen_ids:
                raise DeploymentError(f"Duplicate datasetId: {dataset_id}")
            seen_ids.add(dataset_id)
            manifest_url = public_path(entry.get("manifestUrl"), f"dataset[{position}].manifestUrl")
            if not manifest_url.startswith("/datasets/manifests/"):
                raise DeploymentError(f"Manifest URL is outside /datasets/manifests/: {manifest_url}")
            self._collect_manifest(dataset_id, manifest_url)
        default_id = require_dataset_id(index.get("defaultDatasetId"), "defaultDatasetId")
        if default_id not in seen_ids:
            raise DeploymentError("defaultDatasetId is not present in dataset index")

    def _collect_shell(self, payload: bytes) -> None:
        try:
            source = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DeploymentError("application index is not UTF-8") from error
        parser = _ShellReferences()
        parser.feed(source)
        if parser.module_scripts < 1 or '<div id="root"></div>' not in source:
            raise DeploymentError("application index does not contain the Vite application shell")
        for url in sorted(parser.urls):
            normalized = public_path(url, "application shell URL")
            if not normalized.startswith("/assets/"):
                raise DeploymentError(f"Unexpected root-relative shell asset: {normalized}")
        assets_root = self.dist_root / "assets"
        if assets_root.is_symlink() or not assets_root.is_dir():
            raise DeploymentError(f"Vite assets directory is missing: {assets_root}")
        asset_count = 0
        for path in sorted(assets_root.rglob("*")):
            if path.is_symlink():
                raise DeploymentError(f"Vite assets contain a symlink: {path}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise DeploymentError(f"Vite assets contain a non-file: {path}")
            relative = path.relative_to(self.dist_root)
            self.add_file(relative, f"Vite asset {relative}")
            asset_count += 1
        if asset_count == 0:
            raise DeploymentError("Vite assets directory is empty")
        missing = [url for url in parser.urls if url[1:] not in self.files]
        if missing:
            raise DeploymentError(f"Application shell references missing assets: {', '.join(missing)}")

    def _collect_manifest(self, dataset_id: str, manifest_url: str) -> None:
        manifest_payload = self.add_file(
            relative_public_path(manifest_url), f"manifest for {dataset_id}"
        )
        manifest = strict_json_object(manifest_payload, f"manifest for {dataset_id}")
        if manifest.get("schemaVersion") != 1 or manifest.get("datasetId") != dataset_id:
            raise DeploymentError(f"Manifest identity does not match {dataset_id}")
        snapshot_id = require_string(manifest.get("snapshotId"), f"{dataset_id}.snapshotId")
        artifacts = require_mapping(manifest.get("artifacts"), f"{dataset_id}.artifacts")
        generated_urls: list[str] = []

        locations = artifact_descriptor(
            artifacts.get("locations"), f"{dataset_id}.artifacts.locations"
        )
        content_addressed_path(
            locations.url, f"{dataset_id}.artifacts.locations.url", dataset_id=dataset_id
        )
        self.add_public_artifact(locations, f"{dataset_id} location catalog")
        generated_urls.append(locations.url)

        locale_entries = require_sequence(
            artifacts.get("locales"), f"{dataset_id}.artifacts.locales"
        )
        for position, raw_locale in enumerate(locale_entries):
            locale = require_mapping(raw_locale, f"{dataset_id}.locales[{position}]")
            artifact = locale.get("artifact")
            if artifact is None:
                continue
            descriptor = artifact_descriptor(
                artifact, f"{dataset_id}.locales[{position}].artifact"
            )
            content_addressed_path(
                descriptor.url,
                f"{dataset_id}.locales[{position}].artifact.url",
                dataset_id=dataset_id,
            )
            self.add_public_artifact(descriptor, f"{dataset_id} locale artifact")
            generated_urls.append(descriptor.url)

        tile_ref = require_mapping(artifacts.get("tiles"), f"{dataset_id}.artifacts.tiles")
        map_assets_url = content_addressed_path(
            tile_ref.get("manifestUrl"),
            f"{dataset_id}.artifacts.tiles.manifestUrl",
            dataset_id=dataset_id,
        )
        if not map_assets_url.startswith("/datasets/metadata/"):
            raise DeploymentError(f"Map-assets URL must be metadata: {map_assets_url}")
        map_assets_descriptor = ArtifactDescriptor(
            url=map_assets_url,
            media_type="application/json",
            sha256=require_sha256(
                tile_ref.get("sha256"), f"{dataset_id}.artifacts.tiles.sha256"
            ),
            byte_count=None,
        )
        map_assets_payload = self.add_public_artifact(
            map_assets_descriptor, f"{dataset_id} map assets"
        )
        assert map_assets_payload is not None
        pyramids, rasters = self._collect_map_assets(
            dataset_id, snapshot_id, map_assets_payload
        )
        self.datasets.append(
            {
                "datasetId": dataset_id,
                "generatedArtifacts": sorted(generated_urls),
                "manifestUrl": manifest_url,
                "mapAssetsUrl": map_assets_url,
                "rasters": rasters,
                "snapshotId": snapshot_id,
                "tilePyramids": pyramids,
            }
        )

    def _collect_map_assets(
        self, dataset_id: str, snapshot_id: str, payload: bytes
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        value = strict_json_object(payload, f"{dataset_id} map assets")
        if (
            value.get("schemaVersion") != 1
            or value.get("datasetId") != dataset_id
            or value.get("snapshotId") != snapshot_id
            or value.get("projection") != "TES3:WORLD"
        ):
            raise DeploymentError(f"Map-assets identity does not match {dataset_id}")
        rasters: list[dict[str, object]] = []
        for position, raw_raster in enumerate(
            require_sequence(value.get("rasters"), f"{dataset_id}.mapAssets.rasters")
        ):
            raster = require_mapping(raw_raster, f"{dataset_id}.rasters[{position}]")
            image_url = content_addressed_path(
                raster.get("imageUrl"),
                f"{dataset_id}.raster.imageUrl",
                dataset_id=dataset_id,
            )
            descriptor = ArtifactDescriptor(
                image_url,
                require_string(raster.get("mediaType"), f"{dataset_id}.raster.mediaType"),
                require_sha256(raster.get("sha256"), f"{dataset_id}.raster.sha256"),
                None,
            )
            packaged = self.add_public_artifact(descriptor, f"{dataset_id} static raster")
            if packaged is None:
                self.generated[image_url] = descriptor.to_dict()
            rasters.append(descriptor.to_dict())

        pyramids: list[dict[str, object]] = []
        for position, raw_pyramid in enumerate(
            require_sequence(value.get("tilePyramids", []), f"{dataset_id}.tilePyramids")
        ):
            pyramid = require_mapping(raw_pyramid, f"{dataset_id}.tilePyramids[{position}]")
            pyramid_id = require_dataset_id(pyramid.get("id"), f"{dataset_id}.pyramid.id")
            template = content_addressed_path(
                pyramid.get("urlTemplate"),
                f"{pyramid_id}.urlTemplate",
                dataset_id=dataset_id,
                template=True,
            )
            if not template.startswith("/datasets/generated/"):
                raise DeploymentError(f"Tile template must use generated storage: {template}")
            if pyramid.get("mediaType") != "image/webp":
                raise DeploymentError(f"{pyramid_id}.mediaType must be image/webp")
            coverage = artifact_descriptor(pyramid.get("coverage"), f"{pyramid_id}.coverage")
            content_addressed_path(
                coverage.url, f"{pyramid_id}.coverage.url", dataset_id=dataset_id
            )
            self.add_public_artifact(coverage, f"{pyramid_id} coverage")
            integrity = require_mapping(pyramid.get("integrity"), f"{pyramid_id}.integrity")
            pyramids.append(
                {
                    "coverage": coverage.to_dict(),
                    "inventoryFileSha256": require_sha256(
                        integrity.get("inventoryFileSha256"),
                        f"{pyramid_id}.integrity.inventoryFileSha256",
                    ),
                    "inventorySha256": require_sha256(
                        integrity.get("inventorySha256"),
                        f"{pyramid_id}.integrity.inventorySha256",
                    ),
                    "mediaType": require_string(
                        pyramid.get("mediaType"), f"{pyramid_id}.mediaType"
                    ),
                    "tileCount": require_integer(
                        integrity.get("tileCount"), f"{pyramid_id}.integrity.tileCount", minimum=1
                    ),
                    "tilePyramidId": pyramid_id,
                    "totalBytes": require_integer(
                        integrity.get("totalBytes"), f"{pyramid_id}.integrity.totalBytes", minimum=1
                    ),
                    "urlTemplate": template,
                }
            )
        if not rasters and not pyramids:
            raise DeploymentError(f"{dataset_id} map assets contain no rasters or tile pyramids")
        return pyramids, rasters


def _git_commit(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _tar_info(name: str, payload: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o644
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def package_release(
    *,
    repo_root: Path,
    dist_root: Path,
    output_dir: Path,
    commit_sha: str,
    max_unpacked_bytes: int = _DEFAULT_MAX_BYTES,
) -> dict[str, object]:
    if _COMMIT_SHA.fullmatch(commit_sha) is None:
        raise DeploymentError("commit SHA must be exactly 40 lowercase hexadecimal characters")
    dist = absolute_directory(dist_root, "Vite dist root")
    builder = ReleaseBuilder(dist, max_unpacked_bytes)
    builder.collect()
    file_records = [
        {"bytes": len(payload), "path": path, "sha256": sha256_bytes(payload)}
        for path, payload in sorted(builder.files.items())
    ]
    release_manifest = {
        "commitSha": commit_sha,
        "datasets": sorted(builder.datasets, key=lambda item: str(item["datasetId"])),
        "files": file_records,
        "generatedArtifacts": [builder.generated[url] for url in sorted(builder.generated)],
        "schemaVersion": 1,
    }
    release_manifest_bytes = canonical_json_bytes(release_manifest)
    output = Path(os.path.abspath(os.fspath(output_dir)))
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise DeploymentError(f"Output directory cannot be a symlink: {output}")
    archive_name = f"morrowind-map-{commit_sha[:12]}.tar.gz"
    archive_path = output / archive_name
    fd, temporary_name = tempfile.mkstemp(prefix=f".{archive_name}.", dir=output)
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        with temporary_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for path, payload in sorted(builder.files.items()):
                        archive.addfile(_tar_info(path, payload), io.BytesIO(payload))
                    archive.addfile(
                        _tar_info("release-manifest.json", release_manifest_bytes),
                        io.BytesIO(release_manifest_bytes),
                    )
        os.replace(temporary_path, archive_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    digest = sha256_bytes(archive_path.read_bytes())
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {archive_name}\n", encoding="ascii")
    return {
        "archive": str(archive_path),
        "archiveBytes": archive_path.stat().st_size,
        "archiveSha256": digest,
        "datasets": len(builder.datasets),
        "files": len(builder.files) + 1,
        "generatedArtifacts": len(builder.generated),
        "unpackedBytes": sum(len(item) for item in builder.files.values())
        + len(release_manifest_bytes),
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic production archive from active runtime files."
    )
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    parser.add_argument("--dist-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--commit-sha")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--max-unpacked-bytes", type=int, default=_DEFAULT_MAX_BYTES)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        repo_root = absolute_directory(args.repo_root, "repository root")
        dist_root = args.dist_root or Path("apps/web/dist")
        if not dist_root.is_absolute():
            dist_root = repo_root / dist_root
        output_dir = args.output_dir or Path("artifacts/deployment")
        if not output_dir.is_absolute():
            output_dir = repo_root / output_dir
        if args.max_unpacked_bytes < 1:
            raise DeploymentError("max unpacked bytes must be positive")
        if not args.skip_build:
            subprocess.run(["pnpm", "build"], cwd=repo_root, check=True)
        result = package_release(
            repo_root=repo_root,
            dist_root=dist_root,
            output_dir=output_dir,
            commit_sha=args.commit_sha or _git_commit(repo_root),
            max_unpacked_bytes=args.max_unpacked_bytes,
        )
    except (DeploymentError, OSError, subprocess.CalledProcessError) as error:
        print(f"deployment package failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
