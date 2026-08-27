from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

from tools.land_renderer.land import (
    DEFAULT_HEIGHT,
    LandCell,
    TerrainDataset,
    audit_effective_textures,
    load_terrain,
)
from tools.land_renderer.terrain import (
    RgbaImage,
    TerrainCell,
    TerrainWorld,
    decode_texture,
    encode_webp,
    image_sha256,
    render_cell,
    write_webp,
)
from tools.land_renderer.tiles import (
    CELL_REFERENCE_ZOOM,
    POISON_SONG_TILE_GRID,
    cell_extent,
    cell_raster_grid,
)
from tools.land_renderer.vfs import ResolvedResource, VirtualFileSystem


RENDERER_VERSION = "land-spike-v1"
PROFILE_ID = "poison-song-26.08"
DEFAULT_OUTPUT = Path("local-data/renderer-spike") / PROFILE_ID
RENDERER_CODE_PATHS = (
    "tools/tes3/records.py",
    "tools/tes3/bsa.py",
    "tools/land_renderer/land.py",
    "tools/land_renderer/vfs.py",
    "tools/land_renderer/tiles.py",
    "tools/land_renderer/terrain.py",
    "tools/land_renderer/spike.py",
)


@dataclass(frozen=True, slots=True)
class ControlSite:
    slug: str
    name: str
    cell: tuple[int, int]

    @property
    def center(self) -> tuple[float, float]:
        extent = cell_extent(*self.cell)
        return (extent.min_x + extent.width / 2, extent.min_y + extent.height / 2)


CONTROL_SITES = (
    ControlSite("balmora", "Balmora", (-3, -2)),
    ControlSite("old-ebonheart", "Old Ebonheart", (7, -19)),
    ControlSite("othrenis", "Othrenis", (16, -29)),
    ControlSite("gorne", "Gorne", (19, -14)),
    ControlSite("nan-iban", "Nan Iban", (41, -30)),
)


# Paths are relative to the user-owned source root. Game data never enters Git.
PLUGIN_PATHS = (
    "bsa/Morrowind.esm",
    "bsa/Tribunal.esm",
    "bsa/Bloodmoon.esm",
    "Tamriel Data (SD) 44537 26.08 2026-08-23T18-34Z 9AnoA0Zl/00 Data Files/Tamriel_Data.esm",
    "tamriel/00 Core/Data Files/TR_Mainland.esm",
    "tamriel/01 Faction Integration/Data Files/TR_Factions.esp",
    "tamriel/02 Firemoth Remover/Data Files/TR_Firemoth_Vanilla_patch.esp",
)

BSA_PATHS = (
    "bsa/Morrowind.bsa",
    "bsa/Tribunal.bsa",
    "bsa/Bloodmoon.bsa",
)

LOOSE_PATHS = (
    "Tamriel Data (SD) 44537 26.08 2026-08-23T18-34Z 9AnoA0Zl/00 Data Files",
    "tamriel/00 Core/Data Files",
    "tamriel/01 Faction Integration/Data Files",
    "tamriel/02 Firemoth Remover/Data Files",
)

EXPECTED_SHA256 = {
    "bsa/Morrowind.esm": "5c3c8c2cbd20e25901b59b3ece33d36b7ef0e3d60ad8d11828bcc61a5ead1647",
    "bsa/Tribunal.esm": "2ace511f23cc2a9ddd5f3aa59c7919789b9378cf4b17c8ae3375dd6b782f3f2b",
    "bsa/Bloodmoon.esm": "bd27090d0e6ad4c1bf1abc83f1a2dac56fcc82cae7bfe8263c413fb301801357",
    "bsa/Morrowind.bsa": "3dcd5e6bfa08245521a53374bf733ee5c920df49103898a15aa31144ad64cf48",
    "bsa/Tribunal.bsa": "3901e7a146f7a64a4ae9534c80d5974f7ab15adf5c48c4561d9313c0f7831d69",
    "bsa/Bloodmoon.bsa": "7c20956791400d958cb407f0b7c1c19ceaf46719df7eb724d0b450299360bd7c",
    PLUGIN_PATHS[3]: "e94ca3a5c62e0228ac3782e813cae58c4e10da2e9e8b7611e0a8f5ff9a98d06f",
    PLUGIN_PATHS[4]: "661c96c6aa5e517d897f8b9de93c814d2aca16fd17b6e4ce7869486e3737064b",
    PLUGIN_PATHS[5]: "5a645aae80d02b9634f5da482f97df87fb1cc77aaf20bf0fdb26c272996b671e",
    PLUGIN_PATHS[6]: "c8aa89d6446b1cfb1cacbaf84fe78d62b2fa8b0f804f69f755a8c80f5067bab3",
}

MIM_REFERENCE = {
    "path": "Maps/mim_morrowind/bigmap_hi.jpg",
    "sha256": "64134d40b4d2ba7ff30e6ff449149d73d36b901433c6937d22880dbb531ab76b",
    "balmoraCrop": [1105, 2478, 90, 89],
}


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def renderer_code_hashes() -> dict[str, str]:
    repository_root = Path(__file__).resolve().parents[2]
    return {
        relative: sha256_file(repository_root / relative)
        for relative in RENDERER_CODE_PATHS
    }


def validate_inputs(source_root: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for relative, expected in EXPECTED_SHA256.items():
        path = source_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"Required Stage 4 input is missing: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(
                f"Stage 4 input hash mismatch for {relative}: expected {expected}, got {actual}"
            )
        result[relative] = {"bytes": path.stat().st_size, "sha256": actual}
    return result


def wanted_control_cells(radius: int = 1) -> frozenset[tuple[int, int]]:
    if radius < 0:
        raise ValueError("Control radius must be non-negative")
    return frozenset(
        (site.cell[0] + dx, site.cell[1] + dy)
        for site in CONTROL_SITES
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
    )


def build_vfs(source_root: Path) -> VirtualFileSystem:
    vfs = VirtualFileSystem()
    for relative in BSA_PATHS:
        vfs.mount_bsa(source_root / relative)
    for relative in LOOSE_PATHS:
        vfs.mount_loose(source_root / relative)
    return vfs


def _renderer_texture_key(cell: LandCell, vtex_index: int) -> tuple[int, int] | None:
    return None if vtex_index == 0 else (cell.source_plugin, vtex_index)


def adapt_cell(cell: LandCell) -> TerrainCell:
    heights = cell.heights or (DEFAULT_HEIGHT,) * (65 * 65)
    textures = cell.textures or (0,) * (16 * 16)
    vertex_colors = None
    if cell.colors is not None:
        vertex_colors = tuple(
            (cell.colors[offset], cell.colors[offset + 1], cell.colors[offset + 2])
            for offset in range(0, len(cell.colors), 3)
        )
    return TerrainCell(
        cell.grid[0],
        cell.grid[1],
        heights,
        tuple(_renderer_texture_key(cell, value) for value in textures),
        vertex_colors,
    )


def _decode_resource(
    resource: ResolvedResource, *, texture_size: int, executable: str
) -> RgbaImage:
    suffix = PurePosixPath(resource.logical_path).suffix
    if not suffix:
        raise ValueError(f"Resolved texture has no file extension: {resource.logical_path}")
    return decode_texture(
        resource.read(), suffix, resize=texture_size, executable=executable
    )


def build_render_world(
    dataset: TerrainDataset,
    vfs: VirtualFileSystem,
    *,
    texture_size: int,
    executable: str,
) -> tuple[TerrainWorld, list[dict[str, object]]]:
    renderer_cells = {grid: adapt_cell(cell) for grid, cell in dataset.cells.items()}
    required_keys = sorted(
        {
            key
            for cell in renderer_cells.values()
            for key in cell.texture_keys
            if key is not None
        }
    )
    textures: dict[tuple[int, int], RgbaImage] = {}
    assets: list[dict[str, object]] = []
    for source_plugin, vtex_index in required_keys:
        texture = dataset.resolve_texture_for_plugin(source_plugin, vtex_index)
        if texture is None:
            raise RuntimeError(
                f"Unresolved LTEX for plugin {source_plugin}, VTEX {vtex_index}"
            )
        resource = vfs.resolve_texture(texture.path)
        if resource is None:
            raise RuntimeError(f"Unresolved texture asset: {texture.path}")
        payload = resource.read()
        suffix = PurePosixPath(resource.logical_path).suffix
        textures[(source_plugin, vtex_index)] = decode_texture(
            payload, suffix, resize=texture_size, executable=executable
        )
        assets.append(
            {
                "key": [source_plugin, vtex_index],
                "ltexId": texture.record_id,
                "logicalPath": resource.logical_path,
                "sourceKind": resource.source_kind,
                "sourcePath": resource.source_path.name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    default_resource = vfs.resolve_texture("_land_default.dds")
    if default_resource is None:
        raise RuntimeError("Default terrain texture textures/_land_default.dds is missing")
    default_texture = _decode_resource(
        default_resource, texture_size=texture_size, executable=executable
    )
    return (
        TerrainWorld(
            renderer_cells,
            textures,
            default_texture=default_texture,
            default_water_height=0.0,
        ),
        assets,
    )


def effective_asset_fingerprint(
    dataset: TerrainDataset, vfs: VirtualFileSystem
) -> tuple[str, int, int]:
    """Hash every effective VTEX mapping and payload, including loose overrides."""

    entries: list[dict[str, object]] = []
    unique_payloads: set[tuple[str, str]] = set()
    references = sorted(
        {
            (usage.source_plugin, vtex_index)
            for usage in dataset.texture_usage.values()
            for vtex_index in usage.texture_indices
        }
    )
    for source_plugin, vtex_index in references:
        texture = dataset.resolve_texture_for_plugin(source_plugin, vtex_index)
        if texture is None:
            raise RuntimeError(
                f"Cannot fingerprint missing LTEX for plugin {source_plugin}, VTEX {vtex_index}"
            )
        resource = vfs.resolve_texture(texture.path)
        if resource is None:
            raise RuntimeError(f"Cannot fingerprint missing texture asset: {texture.path}")
        digest = hashlib.sha256(resource.read()).hexdigest()
        unique_payloads.add((resource.logical_path, digest))
        entries.append(
            {
                "plugin": source_plugin,
                "vtex": vtex_index,
                "ltexId": texture.record_id,
                "logicalPath": resource.logical_path,
                "sourceKind": resource.source_kind,
                "sourcePath": resource.source_path.name,
                "sha256": digest,
            }
        )
    default_resource = vfs.resolve_texture("_land_default.dds")
    if default_resource is None:
        raise RuntimeError("Cannot fingerprint missing default LAND texture")
    default_digest = hashlib.sha256(default_resource.read()).hexdigest()
    unique_payloads.add((default_resource.logical_path, default_digest))
    entries.append(
        {
            "default": True,
            "logicalPath": default_resource.logical_path,
            "sourceKind": default_resource.source_kind,
            "sourcePath": default_resource.source_path.name,
            "sha256": default_digest,
        }
    )
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest(), len(entries), len(unique_payloads)


def coordinate_report(site: ControlSite) -> dict[str, object]:
    extent = cell_extent(*site.cell)
    grid = cell_raster_grid(*site.cell)
    samples = (
        (extent.min_x, extent.max_y),
        site.center,
        (extent.max_x, extent.min_y),
    )
    max_error = 0.0
    for world_x, world_y in samples:
        column, row = grid.world_to_pixel(world_x, world_y)
        roundtrip_x, roundtrip_y = grid.pixel_to_world(column, row)
        max_error = max(
            max_error,
            abs(roundtrip_x - world_x),
            abs(roundtrip_y - world_y),
        )
    tile = POISON_SONG_TILE_GRID.cell_to_tile(*site.cell)
    return {
        "cell": list(site.cell),
        "center": list(site.center),
        "extent": [extent.min_x, extent.min_y, extent.max_x, extent.max_y],
        "nativeTile": {"z": CELL_REFERENCE_ZOOM, "x": tile[0], "y": tile[1]},
        "unitsPerPixel": grid.units_per_pixel_x,
        "maxRoundtripWorldError": max_error,
        "uespUrl": (
            "https://gamemap.uesp.net/ptr/?world=tamrielrebuilt"
            f"&x={site.center[0]:g}&y={site.center[1]:g}&zoom=7"
        ),
    }


def seam_report(dataset: TerrainDataset) -> dict[str, object]:
    compared = 0
    max_height_delta = 0.0
    worst: dict[str, object] | None = None
    for (cell_x, cell_y), cell in sorted(dataset.cells.items()):
        if cell.heights is None:
            continue
        for direction, neighbor_grid in (
            ("east", (cell_x + 1, cell_y)),
            ("north", (cell_x, cell_y + 1)),
        ):
            neighbor = dataset.cells.get(neighbor_grid)
            if neighbor is None or neighbor.heights is None:
                continue
            if direction == "east":
                pairs = (
                    (cell.heights[row * 65 + 64], neighbor.heights[row * 65])
                    for row in range(65)
                )
            else:
                pairs = (
                    (cell.heights[64 * 65 + column], neighbor.heights[column])
                    for column in range(65)
                )
            delta = max(abs(left - right) for left, right in pairs)
            compared += 1
            if delta > max_height_delta:
                max_height_delta = delta
                worst = {
                    "cell": [cell_x, cell_y],
                    "neighbor": list(neighbor_grid),
                    "direction": direction,
                    "maxHeightDelta": delta,
                }
    return {
        "sharedEdgesCompared": compared,
        "maxHeightDelta": max_height_delta,
        "heightQuantum": 8.0,
        "withinOneHeightQuantum": max_height_delta <= 8.0,
        "worstEdge": worst,
    }


def _magick_version(executable: str) -> str:
    try:
        completed = subprocess.run(
            [executable, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"ImageMagick executable is unavailable: {executable}") from error
    return completed.stdout.strip()


def _write_json_atomic(path: Path, value: object) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", dir=path.parent, delete=False
        ) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_spike(
    source_root: Path,
    output_root: Path,
    *,
    executable: str = "magick",
    texture_size: int = 64,
    gutter_pixels: int = 16,
) -> dict[str, object]:
    source_root = source_root.resolve()
    if texture_size <= 0:
        raise ValueError("Texture size must be positive")
    if gutter_pixels < 0:
        raise ValueError("Gutter must be non-negative")

    inputs = validate_inputs(source_root)
    plugins = tuple(source_root / relative for relative in PLUGIN_PATHS)
    dataset = load_terrain(plugins, wanted_control_cells())
    missing_controls = [site.name for site in CONTROL_SITES if site.cell not in dataset.cells]
    if missing_controls:
        raise RuntimeError(f"Missing control LAND cells: {', '.join(missing_controls)}")

    vfs = build_vfs(source_root)
    texture_audit = audit_effective_textures(dataset, vfs)
    if not texture_audit.ok:
        first = texture_audit.unresolved[0]
        raise RuntimeError(
            f"Effective LAND texture audit failed: {len(texture_audit.unresolved)} unresolved; "
            f"first is plugin {first.source_plugin}, VTEX {first.vtex_index} ({first.reason})"
        )

    asset_fingerprint, fingerprinted_mappings, unique_asset_payloads = (
        effective_asset_fingerprint(dataset, vfs)
    )
    code_hashes = renderer_code_hashes()
    magick_version = _magick_version(executable)

    world, used_assets = build_render_world(
        dataset, vfs, texture_size=texture_size, executable=executable
    )
    controls: list[dict[str, object]] = []
    controls_root = output_root / "controls"
    for site in CONTROL_SITES:
        image = render_cell(
            world,
            *site.cell,
            gutter_pixels=gutter_pixels,
            crop_gutter=True,
        )
        first_encoding = encode_webp(image, executable=executable)
        second_encoding = encode_webp(image, executable=executable)
        if first_encoding != second_encoding:
            raise RuntimeError(f"Non-deterministic WebP encoding for {site.name}")
        result = write_webp(image, controls_root / f"{site.slug}.webp", executable=executable)
        if (image.width, image.height) != (512, 512):
            raise RuntimeError(f"Control render {site.name} is not 512x512")
        controls.append(
            {
                "id": site.slug,
                "name": site.name,
                **coordinate_report(site),
                "image": {
                    "path": result.path.relative_to(output_root).as_posix(),
                    "width": image.width,
                    "height": image.height,
                    "bytes": result.byte_length,
                    "pixelSha256": image_sha256(image),
                    "webpSha256": result.sha256,
                    "encoderRepeatMatched": True,
                },
            }
        )

    fingerprint_value = {
        "rendererVersion": RENDERER_VERSION,
        "profile": PROFILE_ID,
        "rendererCode": code_hashes,
        "runtime": {
            "python": platform.python_version(),
            "imageMagick": magick_version,
        },
        "inputs": {key: value["sha256"] for key, value in sorted(inputs.items())},
        "effectiveAssetFingerprint": asset_fingerprint,
        "settings": {
            "textureSize": texture_size,
            "gutterPixels": gutter_pixels,
            "tilePixels": 512,
            "unitsPerPixel": 16,
            "webp": {"lossless": True, "quality": 92, "method": 6},
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report: dict[str, object] = {
        "schemaVersion": 1,
        "rendererVersion": RENDERER_VERSION,
        "rendererFingerprint": fingerprint,
        "rendererCode": code_hashes,
        "profile": PROFILE_ID,
        "inputFiles": inputs,
        "loadOrder": list(PLUGIN_PATHS),
        "vfs": {"archives": list(BSA_PATHS), "loose": list(LOOSE_PATHS)},
        "terrain": {
            "effectiveLandCells": texture_audit.cell_count,
            "uniqueEffectiveTextureReferences": texture_audit.reference_count,
            "effectiveTextureOccurrences": texture_audit.occurrence_count,
            "resolvedTextureReferences": texture_audit.resolved_count,
            "unresolvedTextureReferences": len(texture_audit.unresolved),
            "effectiveAssetFingerprint": asset_fingerprint,
            "fingerprintedTextureMappings": fingerprinted_mappings,
            "uniqueResolvedAssetPayloads": unique_asset_payloads,
        },
        "render": {
            "python": platform.python_version(),
            "imageMagick": magick_version,
            "textureDecodeSize": texture_size,
            "gutterPixels": gutter_pixels,
            "controls": controls,
            "usedAssets": used_assets,
        },
        "coordinates": {
            "cellSize": 8192,
            "landVertices": [65, 65],
            "landTextureSlots": [16, 16],
            "tileSize": 512,
            "nativeUnitsPerPixel": 16,
            "nativeZoom": CELL_REFERENCE_ZOOM,
            "tileOrigin": [
                POISON_SONG_TILE_GRID.origin_x,
                POISON_SONG_TILE_GRID.origin_y,
            ],
            "seams": seam_report(dataset),
        },
        "references": {
            "mim": MIM_REFERENCE,
            "uesp": {site.slug: coordinate_report(site)["uespUrl"] for site in CONTROL_SITES},
            "note": "Reference imagery is comparison-only and is not copied into Git.",
        },
    }
    _write_json_atomic(output_root / "report.json", report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render and audit the Poison Song LAND-only quality-gate controls."
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "morr-dev",
        help="Directory containing bsa/, tamriel/ and Tamriel Data 26.08.",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--magick", default="magick", help="ImageMagick executable")
    parser.add_argument("--texture-size", type=int, default=64)
    parser.add_argument("--gutter-pixels", type=int, default=16)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_spike(
        args.source_root,
        args.output_root,
        executable=args.magick,
        texture_size=args.texture_size,
        gutter_pixels=args.gutter_pixels,
    )
    summary = {
        "profile": report["profile"],
        "rendererFingerprint": report["rendererFingerprint"],
        "controls": len(report["render"]["controls"]),  # type: ignore[index]
        "terrain": report["terrain"],
        "report": str(args.output_root / "report.json"),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
