"""Verify the deployed application shell and its active dataset graph over HTTP."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tools.deployment.common import (
    ArtifactDescriptor,
    DeploymentError,
    artifact_descriptor,
    content_addressed_path,
    public_path,
    require_dataset_id,
    require_integer,
    require_mapping,
    require_sequence,
    require_sha256,
    require_string,
    strict_json_object,
    verify_artifact,
)


_MAX_HTML_BYTES = 2 * 1024 * 1024
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_ASSET_BYTES = 16 * 1024 * 1024
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class _HtmlAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_root = False
        self.assets: dict[str, str] = {}
        self.module_scripts = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "div" and values.get("id") == "root":
            self.has_root = True
        if tag == "script" and values.get("type") == "module":
            self.module_scripts += 1
        if tag == "script" and values.get("src"):
            self.assets[values["src"]] = "script"
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.assets[values["href"]] = "style"


@dataclass(frozen=True)
class Response:
    path: str
    status: int
    headers: dict[str, str]
    body: bytes


class HealthClient:
    def __init__(self, base_url: str, timeout: float, cache_policy: str) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise DeploymentError("base URL must be an HTTP(S) origin without credentials or a path")
        self.base_url = f"{parsed.scheme}://{parsed.netloc}/"
        self.timeout = timeout
        self.cache_policy = cache_policy
        self.opener = build_opener(_NoRedirect())
        self.checked: list[str] = []
        self.warnings: list[str] = []

    def fetch(
        self,
        path: str,
        *,
        max_bytes: int,
        media_types: set[str],
        cache_kind: str,
    ) -> Response:
        normalized = "/" if path == "/" else public_path(path, "health-check URL")
        request = Request(
            urljoin(self.base_url, normalized.lstrip("/")),
            headers={"Accept-Encoding": "identity", "User-Agent": "morrowind-map-health/1"},
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as source:
                body = source.read(max_bytes + 1)
                status = source.status
                headers = {key.lower(): value for key, value in source.headers.items()}
        except HTTPError as error:
            raise DeploymentError(f"GET {normalized} returned HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise DeploymentError(f"GET {normalized} failed: {error}") from error
        if status != 200:
            raise DeploymentError(f"GET {normalized} returned HTTP {status}")
        if len(body) > max_bytes:
            raise DeploymentError(f"GET {normalized} exceeded {max_bytes} bytes")
        media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type not in media_types:
            raise DeploymentError(
                f"GET {normalized} returned Content-Type {media_type!r}, expected {sorted(media_types)}"
            )
        self._check_cache(normalized, headers, cache_kind)
        if "set-cookie" in headers:
            self.warnings.append(f"GET {normalized} unexpectedly returned Set-Cookie")
        self.checked.append(normalized)
        return Response(normalized, status, headers, body)

    def expect_dataset_404(self, path: str) -> None:
        normalized = public_path(path, "missing dataset probe")
        request = Request(
            urljoin(self.base_url, normalized.lstrip("/")),
            headers={"Accept-Encoding": "identity", "User-Agent": "morrowind-map-health/1"},
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raise DeploymentError(
                    f"GET {normalized} returned HTTP {response.status}; missing dataset paths must be 404"
                )
        except HTTPError as error:
            try:
                if error.code != 404:
                    raise DeploymentError(
                        f"GET {normalized} returned HTTP {error.code}, expected 404"
                    ) from error
                cache_control = error.headers.get("Cache-Control", "")
                if "no-store" not in cache_control.lower():
                    self._cache_failure(
                        normalized, "missing dataset response must use Cache-Control: no-store"
                    )
            finally:
                error.close()
        except (URLError, TimeoutError, OSError) as error:
            raise DeploymentError(f"GET {normalized} failed: {error}") from error
        self.checked.append(normalized)

    def _check_cache(self, path: str, headers: dict[str, str], kind: str) -> None:
        if self.cache_policy == "off":
            return
        directives: dict[str, str | None] = {}
        for raw in headers.get("cache-control", "").lower().split(","):
            item = raw.strip()
            if not item:
                continue
            name, separator, value = item.partition("=")
            directives[name.strip()] = value.strip().strip('"') if separator else None
        if kind == "mutable":
            max_age = directives.get("max-age")
            valid = (
                "no-cache" in directives
                or "no-store" in directives
                or (max_age == "0" and "must-revalidate" in directives)
            ) and "immutable" not in directives
            if not valid:
                self._cache_failure(path, "mutable response must force revalidation")
        elif kind == "immutable":
            try:
                max_age_value = int(directives.get("max-age") or "-1")
            except ValueError:
                max_age_value = -1
            if not (
                "public" in directives
                and "immutable" in directives
                and max_age_value >= 31_536_000
            ):
                self._cache_failure(path, "immutable response needs public, max-age>=31536000, immutable")

    def _cache_failure(self, path: str, message: str) -> None:
        detail = f"GET {path}: {message}"
        if self.cache_policy == "strict":
            raise DeploymentError(detail)
        self.warnings.append(detail)


def _json_response(
    client: HealthClient,
    path: str,
    *,
    cache_kind: str,
    descriptor: ArtifactDescriptor | None = None,
    label: str,
) -> dict[str, Any]:
    response = client.fetch(
        path,
        max_bytes=_MAX_JSON_BYTES,
        media_types={"application/json"},
        cache_kind=cache_kind,
    )
    if descriptor is not None:
        verify_artifact(response.body, descriptor, label)
    return strict_json_object(response.body, label)


def _identity(value: dict[str, Any], dataset_id: str, snapshot_id: str, label: str) -> None:
    if value.get("datasetId") != dataset_id or value.get("snapshotId") != snapshot_id:
        raise DeploymentError(f"{label} identity does not match {dataset_id}")


def _probe_from_coverage(
    coverage: dict[str, Any],
    *,
    dataset_id: str,
    snapshot_id: str,
    pyramid_id: str,
    template: str,
    expected_tile_count: int,
) -> str:
    _identity(coverage, dataset_id, snapshot_id, f"{pyramid_id} coverage")
    if coverage.get("schemaVersion") != 1 or coverage.get("encoding") != "x-y-ranges-v1":
        raise DeploymentError(f"{pyramid_id} coverage has an unsupported schema or encoding")
    if coverage.get("tilePyramidId") != pyramid_id:
        raise DeploymentError(f"{pyramid_id} coverage names a different pyramid")
    levels = require_sequence(coverage.get("levels"), f"{pyramid_id}.coverage.levels")
    counted = 0
    probe: tuple[int, int, int] | None = None
    previous_z = -1
    for level_position, raw_level in enumerate(levels):
        level = require_mapping(raw_level, f"{pyramid_id}.levels[{level_position}]")
        z = require_integer(level.get("z"), f"{pyramid_id}.levels[{level_position}].z")
        if z <= previous_z:
            raise DeploymentError(f"{pyramid_id} coverage levels are not strictly ordered")
        previous_z = z
        previous_x = -1
        for column_position, raw_column in enumerate(
            require_sequence(level.get("columns"), f"{pyramid_id}.level[{z}].columns")
        ):
            column = require_mapping(raw_column, f"{pyramid_id}.level[{z}].column[{column_position}]")
            x = require_integer(column.get("x"), f"{pyramid_id}.level[{z}].column.x")
            if x <= previous_x:
                raise DeploymentError(f"{pyramid_id} coverage columns are not strictly ordered")
            previous_x = x
            previous_max_y = -1
            for raw_range in require_sequence(
                column.get("yRanges"), f"{pyramid_id}.level[{z}].column[{x}].yRanges"
            ):
                values = require_sequence(raw_range, f"{pyramid_id}.level[{z}].column[{x}].range")
                if len(values) != 2:
                    raise DeploymentError(f"{pyramid_id} coverage range must have two values")
                min_y = require_integer(values[0], f"{pyramid_id}.range.min")
                max_y = require_integer(values[1], f"{pyramid_id}.range.max")
                if min_y > max_y or min_y <= previous_max_y:
                    raise DeploymentError(f"{pyramid_id} coverage contains overlapping or invalid ranges")
                previous_max_y = max_y
                counted += max_y - min_y + 1
                probe = (z, x, min_y)
    declared_tile_count = require_integer(
        coverage.get("tileCount"), f"{pyramid_id}.coverage.tileCount", minimum=1
    )
    if counted != declared_tile_count:
        raise DeploymentError(f"{pyramid_id} coverage tileCount does not match its ranges")
    if declared_tile_count != expected_tile_count:
        raise DeploymentError(f"{pyramid_id} coverage tileCount does not match map-assets integrity")
    if probe is None:
        raise DeploymentError(f"{pyramid_id} coverage contains no tiles")
    z, x, y = probe
    return template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))


def _check_descriptor_json(
    client: HealthClient,
    descriptor: ArtifactDescriptor,
    *,
    dataset_id: str,
    snapshot_id: str,
    label: str,
) -> dict[str, Any]:
    value = _json_response(
        client,
        descriptor.url,
        cache_kind="immutable",
        descriptor=descriptor,
        label=label,
    )
    _identity(value, dataset_id, snapshot_id, label)
    return value


def check_deployment(base_url: str, *, timeout: float, cache_policy: str) -> dict[str, object]:
    client = HealthClient(base_url, timeout, cache_policy)
    root = client.fetch(
        "/", max_bytes=_MAX_HTML_BYTES, media_types={"text/html"}, cache_kind="mutable"
    )
    try:
        html = root.body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DeploymentError("application HTML is not UTF-8") from error
    parser = _HtmlAssets()
    parser.feed(html)
    if not parser.has_root or parser.module_scripts < 1:
        raise DeploymentError("application HTML does not contain the expected root and module script")
    for raw_url, kind in sorted(parser.assets.items()):
        url = public_path(raw_url, "application asset URL")
        if not url.startswith("/assets/"):
            raise DeploymentError(f"Application shell references an unexpected URL: {url}")
        media_types = (
            {"text/css"}
            if kind == "style"
            else {"text/javascript", "application/javascript", "application/x-javascript"}
        )
        client.fetch(url, max_bytes=_MAX_ASSET_BYTES, media_types=media_types, cache_kind="immutable")

    index = _json_response(
        client, "/datasets/index.json", cache_kind="mutable", label="dataset index"
    )
    if index.get("schemaVersion") != 1:
        raise DeploymentError("dataset index schemaVersion must be 1")
    entries = require_sequence(index.get("datasets"), "dataset index.datasets")
    if not entries:
        raise DeploymentError("dataset index contains no datasets")
    seen: set[str] = set()
    for position, raw_entry in enumerate(entries):
        entry = require_mapping(raw_entry, f"dataset index.datasets[{position}]")
        dataset_id = require_dataset_id(entry.get("datasetId"), f"dataset[{position}].datasetId")
        if dataset_id in seen:
            raise DeploymentError(f"Duplicate datasetId: {dataset_id}")
        seen.add(dataset_id)
        manifest_url = public_path(entry.get("manifestUrl"), f"{dataset_id}.manifestUrl")
        manifest = _json_response(
            client, manifest_url, cache_kind="mutable", label=f"{dataset_id} manifest"
        )
        if manifest.get("schemaVersion") != 1 or manifest.get("datasetId") != dataset_id:
            raise DeploymentError(f"Manifest identity does not match {dataset_id}")
        snapshot_id = require_string(manifest.get("snapshotId"), f"{dataset_id}.snapshotId")
        artifacts = require_mapping(manifest.get("artifacts"), f"{dataset_id}.artifacts")
        locations = artifact_descriptor(artifacts.get("locations"), f"{dataset_id}.locations")
        content_addressed_path(
            locations.url, f"{dataset_id}.locations.url", dataset_id=dataset_id
        )
        _check_descriptor_json(
            client,
            locations,
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            label=f"{dataset_id} locations",
        )
        for locale_position, raw_locale in enumerate(
            require_sequence(artifacts.get("locales"), f"{dataset_id}.locales")
        ):
            locale = require_mapping(raw_locale, f"{dataset_id}.locales[{locale_position}]")
            if locale.get("artifact") is None:
                continue
            descriptor = artifact_descriptor(
                locale.get("artifact"), f"{dataset_id}.locales[{locale_position}].artifact"
            )
            content_addressed_path(
                descriptor.url,
                f"{dataset_id}.locales[{locale_position}].artifact.url",
                dataset_id=dataset_id,
            )
            _check_descriptor_json(
                client,
                descriptor,
                dataset_id=dataset_id,
                snapshot_id=snapshot_id,
                label=f"{dataset_id} locale {locale_position}",
            )
        tile_ref = require_mapping(artifacts.get("tiles"), f"{dataset_id}.tiles")
        map_assets_url = content_addressed_path(
            tile_ref.get("manifestUrl"),
            f"{dataset_id}.tiles.manifestUrl",
            dataset_id=dataset_id,
        )
        map_assets_descriptor = ArtifactDescriptor(
            map_assets_url,
            "application/json",
            require_sha256(tile_ref.get("sha256"), f"{dataset_id}.tiles.sha256"),
            None,
        )
        map_assets = _check_descriptor_json(
            client,
            map_assets_descriptor,
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            label=f"{dataset_id} map assets",
        )
        if map_assets.get("projection") != "TES3:WORLD":
            raise DeploymentError(f"{dataset_id} map assets use an unexpected projection")
        for raster_position, raw_raster in enumerate(
            require_sequence(map_assets.get("rasters"), f"{dataset_id}.rasters")
        ):
            raster = require_mapping(raw_raster, f"{dataset_id}.rasters[{raster_position}]")
            raster_url = content_addressed_path(
                raster.get("imageUrl"),
                f"{dataset_id}.raster.imageUrl",
                dataset_id=dataset_id,
            )
            response = client.fetch(
                raster_url,
                max_bytes=_MAX_IMAGE_BYTES,
                media_types={require_string(raster.get("mediaType"), f"{dataset_id}.raster.mediaType")},
                cache_kind="immutable",
            )
            descriptor = ArtifactDescriptor(
                raster_url,
                require_string(raster.get("mediaType"), f"{dataset_id}.raster.mediaType"),
                require_sha256(raster.get("sha256"), f"{dataset_id}.raster.sha256"),
                None,
            )
            verify_artifact(response.body, descriptor, f"{dataset_id} raster")
        for pyramid_position, raw_pyramid in enumerate(
            require_sequence(map_assets.get("tilePyramids", []), f"{dataset_id}.tilePyramids")
        ):
            pyramid = require_mapping(raw_pyramid, f"{dataset_id}.pyramid[{pyramid_position}]")
            pyramid_id = require_dataset_id(pyramid.get("id"), f"{dataset_id}.pyramid.id")
            template = content_addressed_path(
                pyramid.get("urlTemplate"),
                f"{pyramid_id}.urlTemplate",
                dataset_id=dataset_id,
                template=True,
            )
            if not template.startswith("/datasets/generated/"):
                raise DeploymentError(f"{pyramid_id} tile template is outside generated storage")
            if pyramid.get("mediaType") != "image/webp":
                raise DeploymentError(f"{pyramid_id}.mediaType must be image/webp")
            integrity = require_mapping(pyramid.get("integrity"), f"{pyramid_id}.integrity")
            expected_tile_count = require_integer(
                integrity.get("tileCount"), f"{pyramid_id}.integrity.tileCount", minimum=1
            )
            coverage_descriptor = artifact_descriptor(pyramid.get("coverage"), f"{pyramid_id}.coverage")
            content_addressed_path(
                coverage_descriptor.url,
                f"{pyramid_id}.coverage.url",
                dataset_id=dataset_id,
            )
            coverage = _check_descriptor_json(
                client,
                coverage_descriptor,
                dataset_id=dataset_id,
                snapshot_id=snapshot_id,
                label=f"{pyramid_id} coverage",
            )
            tile_url = _probe_from_coverage(
                coverage,
                dataset_id=dataset_id,
                snapshot_id=snapshot_id,
                pyramid_id=pyramid_id,
                template=template,
                expected_tile_count=expected_tile_count,
            )
            tile = client.fetch(
                tile_url,
                max_bytes=_MAX_IMAGE_BYTES,
                media_types={"image/webp"},
                cache_kind="immutable",
            )
            if len(tile.body) < 12 or tile.body[:4] != b"RIFF" or tile.body[8:12] != b"WEBP":
                raise DeploymentError(f"{tile_url} is not a WebP file")
            riff_size = int.from_bytes(tile.body[4:8], "little") + 8
            if riff_size != len(tile.body):
                raise DeploymentError(f"{tile_url} has an invalid RIFF length")
    default_id = require_dataset_id(index.get("defaultDatasetId"), "defaultDatasetId")
    if default_id not in seen:
        raise DeploymentError("defaultDatasetId is absent from dataset index")
    client.expect_dataset_404(
        f"/datasets/generated/__healthcheck_missing__/{secrets.token_hex(16)}.webp"
    )
    return {
        "baseUrl": client.base_url,
        "checked": len(client.checked),
        "datasets": len(seen),
        "status": "healthy",
        "warnings": sorted(client.warnings),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check a deployed Morrowind map release.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--cache-policy", choices=("strict", "warn", "off"), default="strict")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = check_deployment(
            args.base_url,
            timeout=args.timeout,
            cache_policy=args.cache_policy,
        )
    except DeploymentError as error:
        print(f"deployment health check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
