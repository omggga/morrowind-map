"""Verify and upload only the generated files reachable from the active index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

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


_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.:@-]*[A-Za-z0-9])?$")
_REMOTE_DATA_ROOT = "/srv/morrowind-map/data"
_RSYNC_PUBLIC_MODES = "Du=rwx,Dgo=rx,Fu=rw,Fgo=r"


@dataclass(frozen=True)
class PlannedFile:
    path: str
    byte_count: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"bytes": self.byte_count, "path": self.path, "sha256": self.sha256}


@dataclass
class DatasetPlanner:
    public_root: Path
    files: dict[str, PlannedFile] = field(default_factory=dict)
    datasets: list[dict[str, object]] = field(default_factory=list)

    @property
    def generated_root(self) -> Path:
        return self.public_root / "datasets/generated"

    def _read_url(self, url: str, label: str) -> bytes:
        return safe_file(self.public_root, relative_public_path(url), label).read_bytes()

    def _add_generated(
        self, descriptor: ArtifactDescriptor, label: str, *, json_identity: tuple[str, str] | None = None
    ) -> bytes:
        if not descriptor.url.startswith("/datasets/generated/"):
            raise DeploymentError(f"{label} must use generated storage: {descriptor.url}")
        payload = self._read_url(descriptor.url, label)
        verify_artifact(payload, descriptor, label)
        relative = Path(*PurePosixPath(descriptor.url).parts[3:])
        key = PurePosixPath(*relative.parts).as_posix()
        record = PlannedFile(key, len(payload), descriptor.sha256)
        existing = self.files.get(key)
        if existing is not None and existing != record:
            raise DeploymentError(f"Conflicting generated descriptors for {descriptor.url}")
        self.files[key] = record
        if json_identity is not None:
            dataset_id, snapshot_id = json_identity
            value = strict_json_object(payload, label)
            if (
                value.get("schemaVersion") != 1
                or value.get("datasetId") != dataset_id
                or value.get("snapshotId") != snapshot_id
            ):
                raise DeploymentError(f"{label} identity does not match its manifest")
        return payload

    def collect(self) -> dict[str, object]:
        index = strict_json_object(safe_file(self.public_root, Path("datasets/index.json"), "dataset index").read_bytes(), "dataset index")
        if index.get("schemaVersion") != 1:
            raise DeploymentError("dataset index schemaVersion must be 1")
        entries = require_sequence(index.get("datasets"), "dataset index.datasets")
        if not entries:
            raise DeploymentError("dataset index.datasets cannot be empty")
        seen: set[str] = set()
        for position, raw_entry in enumerate(entries):
            entry = require_mapping(raw_entry, f"dataset index.datasets[{position}]")
            dataset_id = require_dataset_id(entry.get("datasetId"), f"dataset[{position}].datasetId")
            if dataset_id in seen:
                raise DeploymentError(f"Duplicate datasetId: {dataset_id}")
            seen.add(dataset_id)
            manifest_url = public_path(entry.get("manifestUrl"), f"dataset[{position}].manifestUrl")
            if not manifest_url.startswith("/datasets/manifests/"):
                raise DeploymentError(f"Manifest URL is outside /datasets/manifests/: {manifest_url}")
            self._collect_manifest(dataset_id, manifest_url)
        default_id = require_dataset_id(index.get("defaultDatasetId"), "defaultDatasetId")
        if default_id not in seen:
            raise DeploymentError("defaultDatasetId is not present in dataset index")
        core: dict[str, object] = {
            "datasets": sorted(self.datasets, key=lambda item: str(item["datasetId"])),
            "fileCount": len(self.files),
            "files": [self.files[path].to_dict() for path in sorted(self.files)],
            "schemaVersion": 1,
            "totalBytes": sum(item.byte_count for item in self.files.values()),
        }
        graph_sha = sha256_bytes(canonical_json_bytes(core))
        return {**core, "graphSha256": graph_sha}

    def _collect_manifest(self, dataset_id: str, manifest_url: str) -> None:
        manifest_payload = self._read_url(manifest_url, f"manifest for {dataset_id}")
        manifest = strict_json_object(manifest_payload, f"manifest for {dataset_id}")
        if manifest.get("schemaVersion") != 1 or manifest.get("datasetId") != dataset_id:
            raise DeploymentError(f"Manifest identity does not match {dataset_id}")
        readiness = require_mapping(manifest.get("readiness", {"status": "ready"}), f"{dataset_id}.readiness")
        if readiness.get("status") != "ready":
            raise DeploymentError(f"Active dataset is not ready: {dataset_id}")
        snapshot_id = require_string(manifest.get("snapshotId"), f"{dataset_id}.snapshotId")
        artifacts = require_mapping(manifest.get("artifacts"), f"{dataset_id}.artifacts")
        generated_urls: list[str] = []

        locations = artifact_descriptor(artifacts.get("locations"), f"{dataset_id}.artifacts.locations")
        content_addressed_path(locations.url, f"{dataset_id}.locations.url", dataset_id=dataset_id)
        if not locations.url.endswith("/locations.json") or "/catalogs/" not in locations.url:
            raise DeploymentError(f"{dataset_id} locations URL is not canonical")
        self._add_generated(locations, f"{dataset_id} location catalog", json_identity=(dataset_id, snapshot_id))
        generated_urls.append(locations.url)

        locale_urls: list[str] = []
        for position, raw_locale in enumerate(require_sequence(artifacts.get("locales"), f"{dataset_id}.artifacts.locales")):
            locale = require_mapping(raw_locale, f"{dataset_id}.locales[{position}]")
            artifact = locale.get("artifact")
            if artifact is None:
                continue
            locale_id = require_string(locale.get("locale"), f"{dataset_id}.locales[{position}].locale")
            descriptor = artifact_descriptor(artifact, f"{dataset_id}.locales[{position}].artifact")
            content_addressed_path(descriptor.url, f"{dataset_id}.locale.url", dataset_id=dataset_id)
            if not descriptor.url.endswith(f"/locales/{locale_id}.json"):
                raise DeploymentError(f"{dataset_id} locale URL is not canonical: {locale_id}")
            payload = self._add_generated(descriptor, f"{dataset_id} locale {locale_id}", json_identity=(dataset_id, snapshot_id))
            value = strict_json_object(payload, f"{dataset_id} locale {locale_id}")
            if value.get("locale") != locale_id:
                raise DeploymentError(f"{dataset_id} locale payload identity differs: {locale_id}")
            locale_urls.append(descriptor.url)
            generated_urls.append(descriptor.url)

        self._verify_catalog_tree(dataset_id, locations.url, generated_urls)
        catalog_audit = self._verify_catalog_audit(
            dataset_id,
            snapshot_id,
            artifacts.get("catalogAudit"),
            locations.url,
            generated_urls,
        )
        tile_ref = require_mapping(artifacts.get("tiles"), f"{dataset_id}.artifacts.tiles")
        map_assets_url = content_addressed_path(tile_ref.get("manifestUrl"), f"{dataset_id}.tiles.manifestUrl", dataset_id=dataset_id)
        if not map_assets_url.startswith("/datasets/metadata/"):
            raise DeploymentError(f"Map-assets URL must use metadata storage: {map_assets_url}")
        map_assets_payload = self._read_url(map_assets_url, f"{dataset_id} map assets")
        expected_map_sha = require_sha256(tile_ref.get("sha256"), f"{dataset_id}.tiles.sha256")
        if sha256_bytes(map_assets_payload) != expected_map_sha:
            raise DeploymentError(f"{dataset_id} map-assets SHA-256 differs from the manifest")
        pyramids, rasters = self._collect_map_assets(dataset_id, snapshot_id, map_assets_url, map_assets_payload)
        self.datasets.append(
            {
                "datasetId": dataset_id,
                "catalogAudit": catalog_audit,
                "generatedArtifacts": sorted(generated_urls),
                "localeArtifacts": sorted(locale_urls),
                "manifest": {"bytes": len(manifest_payload), "sha256": sha256_bytes(manifest_payload), "url": manifest_url},
                "mapAssets": {"bytes": len(map_assets_payload), "sha256": expected_map_sha, "url": map_assets_url},
                "snapshotId": snapshot_id,
                "staticRasters": rasters,
                "tilePyramids": pyramids,
            }
        )

    def _verify_catalog_audit(
        self,
        dataset_id: str,
        snapshot_id: str,
        raw_descriptor: object,
        locations_url: str,
        generated_urls: list[str],
    ) -> dict[str, object]:
        descriptor = artifact_descriptor(raw_descriptor, f"{dataset_id}.artifacts.catalogAudit")
        content_addressed_path(
            descriptor.url,
            f"{dataset_id}.catalogAudit.url",
            dataset_id=dataset_id,
        )
        location_parts = PurePosixPath(locations_url).parts
        catalog_sha = location_parts[-2]
        canonical_audit_url = (
            f"/datasets/metadata/{dataset_id}/catalogs/{catalog_sha}/catalog-audit.json"
        )
        if descriptor.url != canonical_audit_url:
            raise DeploymentError(f"{dataset_id} catalog audit URL is not canonical")
        payload = self._read_url(descriptor.url, f"{dataset_id} catalog audit")
        verify_artifact(payload, descriptor, f"{dataset_id} catalog audit")
        value = strict_json_object(payload, f"{dataset_id} catalog audit")
        if (
            value.get("schemaVersion") != 1
            or value.get("datasetId") != dataset_id
            or value.get("snapshotId") != snapshot_id
            or value.get("catalogInventorySha256") != catalog_sha
            or value.get("passes") is not True
        ):
            raise DeploymentError(f"{dataset_id} catalog audit is not passing for this manifest")
        integrity = require_mapping(value.get("integrity"), f"{dataset_id}.catalogAudit.integrity")
        bindings = require_mapping(
            integrity.get("artifacts"), f"{dataset_id}.catalogAudit.integrity.artifacts"
        )
        catalog_root = relative_public_path(locations_url).parent
        expected: dict[str, tuple[int, str]] = {}
        for url in generated_urls:
            record = self.files[url.removeprefix("/datasets/generated/")]
            relative = relative_public_path(url).relative_to(catalog_root).as_posix()
            expected[relative] = (record.byte_count, record.sha256)
        actual: dict[str, tuple[int, str]] = {}
        for name, raw in bindings.items():
            binding = require_mapping(raw, f"{dataset_id}.catalogAudit.artifacts.{name}")
            relative = require_string(
                binding.get("path"), f"{dataset_id}.catalogAudit.artifacts.{name}.path"
            )
            pure = PurePosixPath(relative)
            if (
                pure.is_absolute()
                or pure.as_posix() != relative
                or any(part in {"", ".", ".."} for part in pure.parts)
            ):
                raise DeploymentError(f"{dataset_id} catalog audit contains an unsafe path")
            if relative in actual:
                raise DeploymentError(f"{dataset_id} catalog audit repeats {relative}")
            actual[relative] = (
                require_integer(
                    binding.get("bytes"),
                    f"{dataset_id}.catalogAudit.artifacts.{name}.bytes",
                    minimum=1,
                ),
                require_sha256(
                    binding.get("sha256"),
                    f"{dataset_id}.catalogAudit.artifacts.{name}.sha256",
                ),
            )
        if actual != expected:
            raise DeploymentError(f"{dataset_id} catalog audit bindings differ from the manifest")
        return descriptor.to_dict()

    def _verify_catalog_tree(self, dataset_id: str, locations_url: str, expected_urls: list[str]) -> None:
        location_path = relative_public_path(locations_url)
        catalog_root = self.public_root / location_path.parent
        expected = {str(relative_public_path(url).relative_to(location_path.parent).as_posix()) for url in expected_urls}
        actual = self._regular_tree_files(catalog_root, f"{dataset_id} active catalog")
        if actual != expected:
            unexpected = sorted(actual - expected)
            missing = sorted(expected - actual)
            detail = unexpected[:5] or missing[:5]
            raise DeploymentError(f"{dataset_id} active catalog tree differs from its manifest: {detail}")

    def _collect_map_assets(self, dataset_id: str, snapshot_id: str, map_assets_url: str, payload: bytes) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        value = strict_json_object(payload, f"{dataset_id} map assets")
        if value.get("schemaVersion") != 1 or value.get("datasetId") != dataset_id or value.get("snapshotId") != snapshot_id or value.get("projection") != "TES3:WORLD":
            raise DeploymentError(f"Map-assets identity does not match {dataset_id}")
        rasters: list[dict[str, object]] = []
        for position, raw in enumerate(require_sequence(value.get("rasters"), f"{dataset_id}.rasters")):
            raster = require_mapping(raw, f"{dataset_id}.rasters[{position}]")
            image_url = content_addressed_path(raster.get("imageUrl"), f"{dataset_id}.raster.imageUrl", dataset_id=dataset_id)
            descriptor = ArtifactDescriptor(image_url, require_string(raster.get("mediaType"), f"{dataset_id}.raster.mediaType"), require_sha256(raster.get("sha256"), f"{dataset_id}.raster.sha256"), None)
            payload_bytes = self._read_url(image_url, f"{dataset_id} raster")
            if sha256_bytes(payload_bytes) != descriptor.sha256:
                raise DeploymentError(f"{dataset_id} raster SHA-256 differs")
            self._add_record(image_url, len(payload_bytes), descriptor.sha256)
            rasters.append({"bytes": len(payload_bytes), **descriptor.to_dict()})

        pyramids: list[dict[str, object]] = []
        for position, raw in enumerate(require_sequence(value.get("tilePyramids"), f"{dataset_id}.tilePyramids")):
            pyramid = require_mapping(raw, f"{dataset_id}.tilePyramids[{position}]")
            pyramid_id = require_dataset_id(pyramid.get("id"), f"{dataset_id}.pyramid.id")
            template = content_addressed_path(pyramid.get("urlTemplate"), f"{pyramid_id}.urlTemplate", dataset_id=dataset_id, template=True)
            integrity = require_mapping(pyramid.get("integrity"), f"{pyramid_id}.integrity")
            inventory_sha = require_sha256(integrity.get("inventorySha256"), f"{pyramid_id}.inventorySha256")
            canonical_template = f"/datasets/generated/{dataset_id}/{inventory_sha}/tiles/{{z}}/{{x}}/{{y}}.webp"
            if template != canonical_template or pyramid.get("mediaType") != "image/webp":
                raise DeploymentError(f"{pyramid_id} tile template is not canonical XYZ WebP")
            tile_count = require_integer(integrity.get("tileCount"), f"{pyramid_id}.tileCount", minimum=1)
            total_bytes = require_integer(integrity.get("totalBytes"), f"{pyramid_id}.totalBytes", minimum=1)
            quality = artifact_descriptor(pyramid.get("qualityReport"), f"{pyramid_id}.qualityReport")
            content_addressed_path(quality.url, f"{pyramid_id}.qualityReport.url", dataset_id=dataset_id)
            quality_payload = self._read_url(quality.url, f"{pyramid_id} quality report")
            verify_artifact(quality_payload, quality, f"{pyramid_id} quality report")
            quality_value = strict_json_object(quality_payload, f"{pyramid_id} quality report")
            if quality_value.get("datasetId") != dataset_id or quality_value.get("snapshotId") != snapshot_id or quality_value.get("passes") is not True:
                raise DeploymentError(f"{pyramid_id} quality report is not passing for this dataset")
            gate = require_mapping(require_mapping(quality_value.get("gates"), f"{pyramid_id}.quality.gates").get("inventory"), f"{pyramid_id}.inventory gate")
            expected_inventory_file_sha = require_sha256(integrity.get("inventoryFileSha256"), f"{pyramid_id}.inventoryFileSha256")
            if gate.get("passes") is not True or gate.get("inventorySha256") != inventory_sha or gate.get("inventoryFileSha256") != expected_inventory_file_sha or gate.get("tileCount") != tile_count or gate.get("totalBytes") != total_bytes:
                raise DeploymentError(f"{pyramid_id} quality inventory gate differs from map-assets")
            artifacts = require_mapping(quality_value.get("artifacts"), f"{pyramid_id}.quality.artifacts")
            inventory_record = require_mapping(artifacts.get("tiles"), f"{pyramid_id}.quality.artifacts.tiles")
            if inventory_record.get("path") != "tiles.ndjson":
                raise DeploymentError(f"{pyramid_id} quality report must bind tiles.ndjson")
            inventory_descriptor = ArtifactDescriptor("/datasets/metadata/placeholder", "application/x-ndjson", require_sha256(inventory_record.get("sha256"), f"{pyramid_id}.tiles.ndjson.sha256"), require_integer(inventory_record.get("bytes"), f"{pyramid_id}.tiles.ndjson.bytes", minimum=1))
            inventory_path = self.public_root / relative_public_path(quality.url).parent / "tiles.ndjson"
            inventory_payload = safe_file(self.public_root, inventory_path.relative_to(self.public_root), f"{pyramid_id} tiles.ndjson").read_bytes()
            verify_artifact(inventory_payload, inventory_descriptor, f"{pyramid_id} tiles.ndjson")
            self._collect_tiles(dataset_id, pyramid_id, inventory_sha, inventory_payload, tile_count, total_bytes)
            pyramids.append({"id": pyramid_id, "inventoryFileSha256": expected_inventory_file_sha, "inventorySha256": inventory_sha, "qualityReport": quality.to_dict(), "tileCount": tile_count, "tilesNdjson": {"bytes": len(inventory_payload), "sha256": inventory_descriptor.sha256}, "totalBytes": total_bytes, "urlTemplate": template})
        if not rasters and not pyramids:
            raise DeploymentError(f"{dataset_id} map assets contain no rasters or tile pyramids")
        return pyramids, rasters

    def _collect_tiles(self, dataset_id: str, pyramid_id: str, inventory_sha: str, payload: bytes, expected_count: int, expected_total: int) -> None:
        if not payload or not payload.endswith(b"\n"):
            raise DeploymentError(f"{pyramid_id} tiles.ndjson must be non-empty and LF-terminated")
        version_root = self.generated_root / dataset_id / inventory_sha
        expected_paths: set[str] = set()
        folded: set[str] = set()
        total = 0
        for position, line in enumerate(payload[:-1].split(b"\n")):
            if not line:
                raise DeploymentError(f"{pyramid_id} tiles.ndjson line {position + 1} is empty")
            record = strict_json_object(line, f"{pyramid_id} tiles.ndjson line {position + 1}")
            if canonical_json_bytes(record)[:-1] != line:
                raise DeploymentError(f"{pyramid_id} tiles.ndjson line {position + 1} is not canonical JSON")
            z = require_integer(record.get("z"), f"{pyramid_id} tile z")
            x = require_integer(record.get("x"), f"{pyramid_id} tile x")
            y = require_integer(record.get("y"), f"{pyramid_id} tile y")
            relative_text = require_string(record.get("path"), f"{pyramid_id} tile path")
            canonical = f"tiles/{z}/{x}/{y}.webp"
            if relative_text != canonical or relative_text.casefold() in folded:
                raise DeploymentError(f"{pyramid_id} tile path is duplicate or non-canonical: {relative_text}")
            byte_count = require_integer(record.get("bytes"), f"{pyramid_id} tile bytes", minimum=1)
            digest = require_sha256(record.get("sha256"), f"{pyramid_id} tile SHA-256")
            tile_path = safe_file(self.generated_root, Path(dataset_id) / inventory_sha / Path(relative_text), f"{pyramid_id} tile {relative_text}")
            if tile_path.stat().st_size != byte_count or self._sha256_file(tile_path) != digest:
                raise DeploymentError(f"{pyramid_id} tile failed integrity: {relative_text}")
            public_url = f"/datasets/generated/{dataset_id}/{inventory_sha}/{relative_text}"
            self._add_record(public_url, byte_count, digest)
            expected_paths.add(relative_text)
            folded.add(relative_text.casefold())
            total += byte_count
        if len(expected_paths) != expected_count or total != expected_total:
            raise DeploymentError(f"{pyramid_id} tiles.ndjson count/bytes differ from map-assets")
        actual = self._regular_tree_files(version_root, f"{pyramid_id} active tile tree")
        if actual != expected_paths:
            extra = sorted(actual - expected_paths)
            missing = sorted(expected_paths - actual)
            raise DeploymentError(f"{pyramid_id} tile tree differs from tiles.ndjson: {(extra or missing)[:5]}")

    def _add_record(self, public_url: str, byte_count: int, digest: str) -> None:
        relative = PurePosixPath(*PurePosixPath(public_url).parts[3:]).as_posix()
        record = PlannedFile(relative, byte_count, digest)
        previous = self.files.get(relative)
        if previous is not None and previous != record:
            raise DeploymentError(f"Conflicting generated file record: {relative}")
        self.files[relative] = record

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _regular_tree_files(root: Path, label: str) -> set[str]:
        if root.is_symlink() or not root.is_dir():
            raise DeploymentError(f"{label} must be a real directory: {root}")
        result: set[str] = set()
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise DeploymentError(f"{label} contains a symlink: {path}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise DeploymentError(f"{label} contains a non-file: {path}")
            result.add(path.relative_to(root).as_posix())
        return result


def build_dataset_plan(*, public_root: Path) -> dict[str, object]:
    public = absolute_directory(public_root, "web public root")
    generated = public / "datasets/generated"
    if generated.is_symlink() or not generated.is_dir():
        raise DeploymentError(f"generated dataset root must be a real directory: {generated}")
    return DatasetPlanner(public).collect()


def _validate_host(host: str) -> str:
    if _HOST.fullmatch(host) is None or host.startswith("-"):
        raise DeploymentError(f"SSH host is unsafe: {host!r}")
    return host


def _remote_program() -> str:
    path = Path(__file__).with_name("dataset_remote.py")
    return path.read_text(encoding="utf-8")


def _run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True, input=input_text)


def probe_dataset_plan(*, host: str, plan: dict[str, object]) -> dict[str, object]:
    """Verify a stored graph on the host without reading local generated payload."""

    host = _validate_host(host)
    graph_sha = require_sha256(plan.get("graphSha256"), "graphSha256")
    plan_bytes = canonical_json_bytes(plan)
    upload_id = secrets.token_hex(16)
    stage = f"{_REMOTE_DATA_ROOT}/incoming/{upload_id}"
    remote_program = _remote_program()
    _run(["ssh", host, "python3", "-", "prepare", upload_id], input_text=remote_program)
    try:
        with tempfile.TemporaryDirectory(prefix="morrowind-dataset-probe-") as temporary:
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_bytes(plan_bytes)
            _run([
                "rsync", "--archive", "--no-owner", "--no-group",
                f"--chmod={_RSYNC_PUBLIC_MODES}", str(plan_path), f"{host}:{stage}/plan.json",
            ])
            probe = _run(
                ["ssh", host, "python3", "-", "probe-stage", upload_id],
                input_text=remote_program,
            )
            response = probe.stdout.strip()
            if response not in {"installed", "upload"}:
                raise DeploymentError(f"Unexpected remote dataset probe response: {probe.stdout!r}")
            return {
                "graphSha256": graph_sha,
                "releasePath": f"{_REMOTE_DATA_ROOT}/releases/{graph_sha}",
                "status": "already-staged" if response == "installed" else "missing",
            }
    finally:
        # A successful missing probe leaves its plan staged. Existing-graph
        # probes already clean it, so abort is intentionally idempotent.
        failed = sys.exc_info()[0] is not None
        try:
            _run(["ssh", host, "python3", "-", "abort", upload_id], input_text=remote_program)
        except (OSError, subprocess.SubprocessError) as error:
            if not failed:
                raise
            print(f"dataset probe cleanup failed: {error}", file=sys.stderr)


def upload_dataset_plan(
    *, public_root: Path, host: str, plan: dict[str, object], stage_only: bool = False
) -> dict[str, object]:
    host = _validate_host(host)
    graph_sha = require_sha256(plan.get("graphSha256"), "graphSha256")
    result = {
        "files": int(plan["fileCount"]),
        "graphSha256": graph_sha,
        "releasePath": f"{_REMOTE_DATA_ROOT}/releases/{graph_sha}",
        "status": "staged" if stage_only else "installed",
        "totalBytes": int(plan["totalBytes"]),
    }
    upload_id = secrets.token_hex(16)
    stage = f"{_REMOTE_DATA_ROOT}/incoming/{upload_id}"
    remote_program = _remote_program()
    _run(["ssh", host, "python3", "-", "prepare", upload_id], input_text=remote_program)
    try:
        with tempfile.TemporaryDirectory(prefix="morrowind-datasets-") as temporary:
            temporary_root = Path(temporary)
            plan_path = temporary_root / "plan.json"
            plan_path.write_bytes(canonical_json_bytes(plan))
            files_path = temporary_root / "files-from.txt"
            raw_files = require_sequence(plan.get("files"), "plan.files")
            paths = [require_string(require_mapping(item, "plan file").get("path"), "plan file path") for item in raw_files]
            files_path.write_text("".join(f"{path}\n" for path in paths), encoding="utf-8")
            _run(
                [
                    "rsync",
                    "--archive",
                    "--no-owner",
                    "--no-group",
                    f"--chmod={_RSYNC_PUBLIC_MODES}",
                    str(plan_path),
                    f"{host}:{stage}/plan.json",
                ]
            )
            probe_action = "probe-stage" if stage_only else "probe"
            probe = _run(["ssh", host, "python3", "-", probe_action, upload_id], input_text=remote_program)
            if probe.stdout.strip() == "installed":
                return {**result, "status": "already-staged" if stage_only else "already-installed"}
            if probe.stdout.strip() != "upload":
                raise DeploymentError(f"Unexpected remote dataset probe response: {probe.stdout!r}")
            source = str(public_root / "datasets/generated") + os.sep
            _run(
                [
                    "rsync",
                    "--archive",
                    "--partial",
                    "--no-owner",
                    "--no-group",
                    f"--chmod={_RSYNC_PUBLIC_MODES}",
                    f"--files-from={files_path}",
                    source,
                    f"{host}:{stage}/payload/",
                ]
            )
            install_action = "install-stage" if stage_only else "install"
            installed = _run(["ssh", host, "python3", "-", install_action, upload_id], input_text=remote_program)
            if installed.stdout.strip() != "installed":
                raise DeploymentError(f"Unexpected remote dataset install response: {installed.stdout!r}")
    except BaseException:
        try:
            _run(
                ["ssh", host, "python3", "-", "abort", upload_id],
                input_text=remote_program,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        raise
    return result


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify and upload the active generated dataset graph.")
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    parser.add_argument("--host", help="SSH host or alias; omit to build and verify the plan only")
    parser.add_argument("--plan-output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--stage-only",
        action="store_true",
        help="Stage an immutable graph without switching data/generated; app publication handles retention",
    )
    mode.add_argument(
        "--probe-plan", type=Path,
        help="Probe a stored plan on --host without reading or transferring local generated files",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.probe_plan is not None and (not args.host or args.plan_output is not None):
        parser.error("--probe-plan requires --host and cannot be combined with --plan-output")
    try:
        repo_root = absolute_directory(args.repo_root, "repository root")
        if args.probe_plan is not None:
            plan_path = args.probe_plan if args.probe_plan.is_absolute() else repo_root / args.probe_plan
            plan = strict_json_object(plan_path.read_bytes(), "stored dataset plan")
            result = probe_dataset_plan(host=args.host, plan=plan)
        else:
            public_root = repo_root / "apps/web/public"
            plan = build_dataset_plan(public_root=public_root)
            if args.plan_output is not None:
                output = args.plan_output if args.plan_output.is_absolute() else repo_root / args.plan_output
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(canonical_json_bytes(plan))
            result = upload_dataset_plan(public_root=public_root, host=args.host, plan=plan, stage_only=args.stage_only) if args.host else {"files": plan["fileCount"], "graphSha256": plan["graphSha256"], "status": "verified", "totalBytes": plan["totalBytes"]}
    except (DeploymentError, OSError, subprocess.CalledProcessError) as error:
        print(f"dataset upload failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
