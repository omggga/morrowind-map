from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from tools.land_renderer.spike import CONTROL_SITES, ControlSite, coordinate_report
from tools.land_renderer.terrain import RgbaImage, decode_texture, image_sha256, write_webp
from tools.openmw_renderer.images import (
    DEFAULT_GRADE,
    GRADE_VERSION,
    PixelDifference,
    apply_grade,
    pixel_difference,
    seam_overlap,
)
from tools.openmw_renderer.profile import (
    CONTENT_FILES,
    DATA_DIRECTORIES,
    DEFAULT_DOCKER_IMAGE,
    DOCKER_BASE_IMAGE,
    DOCKER_PLATFORM,
    EXCLUDED_DYNAMIC_CONTENT_FILES,
    FALLBACK_ARCHIVES,
    OPENMW_COMMIT,
    OPENMW_RELEASE,
    OPENMW_SOURCE_URL,
    PROFILE_ID,
    UBUNTU_SNAPSHOT,
    fingerprint_data_directories,
    profile_fingerprint,
    render_console_script,
    render_openmw_cfg,
    render_settings_cfg,
    sha256_file,
    validate_source_inputs,
)


RENDERER_VERSION = "openmw-export-spike-v1"
NATIVE_PIXELS = 512
GUTTER_PIXELS = 16
RAW_PIXELS = NATIVE_PIXELS + 2 * GUTTER_PIXELS
TES3_CELL_SIZE = 8192
WORLD_UNITS_PER_PIXEL = TES3_CELL_SIZE / NATIVE_PIXELS
DEFAULT_TIMEOUT_SECONDS = 15 * 60
DEFAULT_OUTPUT = Path("local-data/openmw-spike") / PROFILE_ID
REPRO_MAX_DIFFERING_FRACTION = 0.0001
REPRO_MAX_MEAN_CHANNEL_DELTA = 0.0001
REPRO_MAX_CHANNEL_DELTA = 4
SEAM_MAX_DIFFERING_FRACTION = 0.35
SEAM_MAX_MEAN_CHANNEL_DELTA = 0.3
SEAM_MAX_CHANNEL_DELTA = 32
VISUAL_FEATURES = frozenset(
    ("roofs", "buildings", "bridges", "trees", "walls", "water", "alphaGeometry")
)
RENDERER_CODE_PATHS = (
    ".dockerignore",
    "tools/__init__.py",
    "tools/tes3/__init__.py",
    "tools/tes3/bsa.py",
    "tools/tes3/records.py",
    "tools/land_renderer/__init__.py",
    "tools/land_renderer/land.py",
    "tools/land_renderer/spike.py",
    "tools/land_renderer/terrain.py",
    "tools/land_renderer/tiles.py",
    "tools/land_renderer/vfs.py",
    "tools/openmw_renderer/__init__.py",
    "tools/openmw_renderer/Dockerfile",
    "tools/openmw_renderer/entrypoint.sh",
    "tools/openmw_renderer/images.py",
    "tools/openmw_renderer/profile.py",
    "tools/openmw_renderer/spike.py",
    "tools/openmw_renderer/patches/openmw-0.51.0-map-export.patch",
    "tools/openmw_renderer/patches/openmw-0.51.0-map-export-once.patch",
)

_MISSING_RESOURCE = re.compile(
    r"(?:failed to (?:load|open)|could not (?:load|open|find)|can't find|"
    r"resource[^\n]*not found|(?:mesh|texture|file)[^\n]*not found)",
    re.IGNORECASE,
)
_EXPORT_EVIDENCE = re.compile(
    r"MWMAP export target\s+(-?\d+),(-?\d+):\s+(\d+)px over "
    r"(-?[0-9]+(?:\.[0-9]+)?) world units; center=\("
    r"(-?[0-9]+(?:\.[0-9]+)?),(-?[0-9]+(?:\.[0-9]+)?)\); bounds=\["
    r"(-?[0-9]+(?:\.[0-9]+)?),(-?[0-9]+(?:\.[0-9]+)?)\]x\["
    r"(-?[0-9]+(?:\.[0-9]+)?),(-?[0-9]+(?:\.[0-9]+)?)\]; "
    r"raster=top-left,\+x,-y,flipVertical=false"
)
_GL_RENDERER = re.compile(r"^OpenGL renderer string:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class RenderTarget:
    key: str
    site_slug: str
    pass_name: str
    cell: tuple[int, int]


@dataclass(frozen=True, slots=True)
class DockerImageInfo:
    image: str
    image_id: str
    repo_digests: tuple[str, ...]
    os: str
    architecture: str
    labels: dict[str, str]
    contract_errors: tuple[str, ...]

    @property
    def contract_passes(self) -> bool:
        return not self.contract_errors


def renderer_fingerprint(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for relative in RENDERER_CODE_PATHS:
        path = repo_root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def primary_targets(sites: Sequence[ControlSite] = CONTROL_SITES) -> tuple[RenderTarget, ...]:
    targets: list[RenderTarget] = []
    for site in sites:
        targets.extend(
            (
                RenderTarget(site.slug, site.slug, "primary", site.cell),
                RenderTarget(
                    f"{site.slug}-east",
                    site.slug,
                    "primary",
                    (site.cell[0] + 1, site.cell[1]),
                ),
                RenderTarget(
                    f"{site.slug}-north",
                    site.slug,
                    "primary",
                    (site.cell[0], site.cell[1] + 1),
                ),
            )
        )
    return tuple(targets)


def repeat_targets(sites: Sequence[ControlSite] = CONTROL_SITES) -> tuple[RenderTarget, ...]:
    return tuple(
        RenderTarget(site.slug, site.slug, "repeat", site.cell) for site in sites
    )


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def prepare_run_profile(output_root: Path, target: RenderTarget) -> Path:
    profile_root = output_root / "runs" / target.pass_name / target.key / "profile"
    if profile_root.exists():
        shutil.rmtree(profile_root)
    config_root = profile_root / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    (profile_root / "user-data").mkdir(parents=True, exist_ok=True)
    _atomic_write_text(config_root / "openmw.cfg", render_openmw_cfg())
    _atomic_write_text(config_root / "settings.cfg", render_settings_cfg())
    _atomic_write_text(profile_root / "commands.txt", render_console_script(target.cell))
    return profile_root


def docker_run_command(
    *,
    image: str,
    source_root: Path,
    profile_root: Path,
    output_root: Path,
    target: RenderTarget,
) -> list[str]:
    container_output = f"/out/raw/{target.pass_name}/{target.key}.png"
    container_name = _container_name(target)
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--platform",
        DOCKER_PLATFORM,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        "512",
        "--memory",
        "4g",
        "--tmpfs",
        "/tmp:rw,nosuid,size=1g",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--security-opt",
        "no-new-privileges",
    ]
    for relative in DATA_DIRECTORIES:
        command.extend(
            (
                "--mount",
                f"type=bind,src={source_root / relative},dst=/game/{relative},readonly",
            )
        )
    command.extend(
        [
        "--mount",
        f"type=bind,src={profile_root},dst=/profile",
        "--mount",
        f"type=bind,src={output_root},dst=/out",
        "--env",
        f"MWMAP_EXPORT_CELL={target.cell[0]},{target.cell[1]}",
        "--env",
        f"MWMAP_EXPORT_PATH={container_output}",
        "--env",
        f"MWMAP_EXPORT_GUTTER_PIXELS={GUTTER_PIXELS}",
        "--env",
        "LIBGL_ALWAYS_SOFTWARE=1",
        "--env",
        "GALLIUM_DRIVER=llvmpipe",
        "--env",
        "OPENMW_DONT_PRECOMPILE=1",
        "--env",
        "OSG_THREADING=SingleThreaded",
        image,
        ]
    )
    return command


def _container_name(target: RenderTarget) -> str:
    suffix = re.sub(r"[^a-zA-Z0-9_.-]", "-", f"{target.pass_name}-{target.key}")
    return f"mwm45-{os.getpid()}-{suffix}"[:128]


def _run_logged(
    command: Sequence[str],
    log_path: Path,
    *,
    timeout_seconds: int,
    timeout_cleanup: Sequence[str] | None = None,
) -> float:
    def cleanup() -> None:
        if timeout_cleanup:
            subprocess.run(
                list(timeout_cleanup),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )

    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        _atomic_write_text(log_path, output)
        cleanup()
        raise RuntimeError(f"Command timed out after {timeout_seconds}s; see {log_path}") from error
    except KeyboardInterrupt:
        cleanup()
        raise
    elapsed = time.monotonic() - started
    _atomic_write_text(log_path, completed.stdout)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}; see {log_path}"
        )
    return elapsed


def build_image(
    repo_root: Path,
    image: str,
    *,
    renderer_hash: str,
    timeout_seconds: int,
) -> float:
    log_path = repo_root / "local-data/openmw-spike/docker-build.log"
    command = (
        "docker",
        "build",
        "--platform",
        DOCKER_PLATFORM,
        "--file",
        str(repo_root / "tools/openmw_renderer/Dockerfile"),
        "--build-arg",
        f"RENDERER_FINGERPRINT={renderer_hash}",
        "--tag",
        image,
        str(repo_root),
    )
    return _run_logged(command, log_path, timeout_seconds=timeout_seconds)


def docker_image_info(image: str, *, expected_renderer_hash: str) -> DockerImageInfo:
    completed = subprocess.run(
        ("docker", "image", "inspect", image),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError(f"Unexpected docker image inspect response for {image}")
    item = payload[0]
    labels = {
        str(key): str(value)
        for key, value in ((item.get("Config") or {}).get("Labels") or {}).items()
    }
    actual_os = str(item.get("Os", ""))
    actual_architecture = str(item.get("Architecture", ""))
    errors: list[str] = []
    if actual_os != "linux":
        errors.append(f"expected image OS linux, got {actual_os or 'missing'}")
    if actual_architecture != "amd64":
        errors.append(
            f"expected image architecture amd64, got {actual_architecture or 'missing'}"
        )
    if labels.get("org.opencontainers.image.revision") != OPENMW_COMMIT:
        errors.append("OpenMW commit label does not match the pinned commit")
    if labels.get("io.morrowind-map.stage") != "4.5":
        errors.append("Stage label is not 4.5")
    if labels.get("io.morrowind-map.renderer-fingerprint") != expected_renderer_hash:
        errors.append("Renderer fingerprint label does not match the current source")
    if labels.get("io.morrowind-map.base-image") != DOCKER_BASE_IMAGE:
        errors.append("Base image label does not match the pinned digest")
    if labels.get("io.morrowind-map.ubuntu-snapshot") != UBUNTU_SNAPSHOT:
        errors.append("Ubuntu package snapshot label does not match the pinned snapshot")
    return DockerImageInfo(
        image=image,
        image_id=str(item["Id"]),
        repo_digests=tuple(str(value) for value in item.get("RepoDigests") or ()),
        os=actual_os,
        architecture=actual_architecture,
        labels=labels,
        contract_errors=tuple(errors),
    )


def run_target(
    *,
    image: str,
    source_root: Path,
    output_root: Path,
    target: RenderTarget,
    timeout_seconds: int,
) -> dict[str, object]:
    profile_root = prepare_run_profile(output_root, target)
    output_path = output_root / "raw" / target.pass_name / f"{target.key}.png"
    output_path.unlink(missing_ok=True)
    log_path = output_root / "logs" / target.pass_name / f"{target.key}.log"
    command = docker_run_command(
        image=image,
        source_root=source_root,
        profile_root=profile_root,
        output_root=output_root,
        target=target,
    )
    elapsed = _run_logged(
        command,
        log_path,
        timeout_seconds=timeout_seconds,
        timeout_cleanup=("docker", "rm", "-f", _container_name(target)),
    )
    if not output_path.is_file():
        raise RuntimeError(f"OpenMW returned success without producing {output_path}")
    engine_log_path = profile_root / "config" / "openmw.log"
    if not engine_log_path.is_file():
        raise RuntimeError(f"OpenMW returned success without producing {engine_log_path}")
    return {
        "key": target.key,
        "site": target.site_slug,
        "pass": target.pass_name,
        "cell": list(target.cell),
        "elapsedSeconds": round(elapsed, 3),
        "rawPath": str(output_path.relative_to(output_root)),
        "rawBytes": output_path.stat().st_size,
        "rawSha256": sha256_file(output_path),
        "logPath": str(log_path.relative_to(output_root)),
        "engineLogPath": str(engine_log_path.relative_to(output_root)),
    }


def _decode_raw(path: Path, *, magick: str) -> RgbaImage:
    image = decode_texture(path.read_bytes(), ".png", executable=magick)
    if (image.width, image.height) != (RAW_PIXELS, RAW_PIXELS):
        raise RuntimeError(
            f"Expected {RAW_PIXELS}x{RAW_PIXELS} OpenMW render, got "
            f"{image.width}x{image.height}: {path}"
        )
    return image


def _difference_report(difference: PixelDifference) -> dict[str, object]:
    return {
        **asdict(difference),
        "differingFraction": difference.differing_fraction,
    }


def _reproducibility_difference_passes(difference: PixelDifference) -> bool:
    return (
        difference.differing_fraction <= REPRO_MAX_DIFFERING_FRACTION
        and difference.mean_absolute_channel_delta <= REPRO_MAX_MEAN_CHANNEL_DELTA
        and difference.maximum_channel_delta <= REPRO_MAX_CHANNEL_DELTA
    )


def _seam_difference_passes(difference: PixelDifference) -> bool:
    return (
        difference.differing_fraction <= SEAM_MAX_DIFFERING_FRACTION
        and difference.mean_absolute_channel_delta <= SEAM_MAX_MEAN_CHANNEL_DELTA
        and difference.maximum_channel_delta <= SEAM_MAX_CHANNEL_DELTA
    )


def process_center(
    raw_path: Path,
    output_path: Path,
    *,
    magick: str,
    report_root: Path | None = None,
) -> dict[str, object]:
    raw = _decode_raw(raw_path, magick=magick)
    native = raw.crop(GUTTER_PIXELS, GUTTER_PIXELS, NATIVE_PIXELS, NATIVE_PIXELS)
    graded = apply_grade(native)
    unique_colors = {
        native.pixels[offset : offset + 4]
        for offset in range(0, len(native.pixels), 4)
    }
    non_black_pixels = sum(
        1
        for offset in range(0, len(native.pixels), 4)
        if max(native.pixels[offset : offset + 3]) > 8
    )
    channels = [
        channel
        for offset in range(0, len(native.pixels), 4)
        for channel in native.pixels[offset : offset + 3]
    ]
    dynamic_range = max(channels) - min(channels)
    content_quality = {
        "uniqueRgbaColors": len(unique_colors),
        "nonBlackFraction": non_black_pixels / (native.width * native.height),
        "rgbDynamicRange": dynamic_range,
        "passes": (
            len(unique_colors) >= 128
            and non_black_pixels >= native.width * native.height * 0.15
            and dynamic_range >= 32
        ),
    }
    written = write_webp(
        graded,
        output_path,
        executable=magick,
        lossless=True,
        quality=100,
        method=6,
    )
    return {
        "path": str(
            output_path.relative_to(report_root) if report_root is not None else output_path
        ),
        "width": graded.width,
        "height": graded.height,
        "bytes": written.byte_length,
        "sha256": written.sha256,
        "rgbaSha256": image_sha256(graded),
        "nativeRgbaSha256": image_sha256(native),
        "contentQuality": content_quality,
    }


def coordinate_alignment(site: ControlSite) -> dict[str, object]:
    base = coordinate_report(site)
    cell_x, cell_y = site.cell
    samples = (
        (cell_x * TES3_CELL_SIZE, (cell_y + 1) * TES3_CELL_SIZE),
        site.center,
        ((cell_x + 1) * TES3_CELL_SIZE, cell_y * TES3_CELL_SIZE),
    )
    max_pixel_error = 0.0
    mapped: list[dict[str, list[float]]] = []
    for world_x, world_y in samples:
        pixel_x = (world_x - cell_x * TES3_CELL_SIZE) / WORLD_UNITS_PER_PIXEL
        pixel_y = ((cell_y + 1) * TES3_CELL_SIZE - world_y) / WORLD_UNITS_PER_PIXEL
        roundtrip_x = cell_x * TES3_CELL_SIZE + pixel_x * WORLD_UNITS_PER_PIXEL
        roundtrip_y = (cell_y + 1) * TES3_CELL_SIZE - pixel_y * WORLD_UNITS_PER_PIXEL
        error = max(
            abs(roundtrip_x - world_x),
            abs(roundtrip_y - world_y),
        ) / WORLD_UNITS_PER_PIXEL
        max_pixel_error = max(max_pixel_error, error)
        mapped.append(
            {
                "world": [world_x, world_y],
                "pixelEdge": [pixel_x, pixel_y],
            }
        )
    base.update(
        {
            "transform": {
                "pixelX": "(worldX - cellX*8192) / 16",
                "pixelY": "((cellY+1)*8192 - worldY) / 16",
                "pixelConvention": "pixel edges; centers are +0.5,+0.5",
            },
            "samples": mapped,
            "maxRoundtripPixelError": max_pixel_error,
            "passesOnePixelGate": max_pixel_error <= 1.0,
        }
    )
    return base


def _runtime_text(output_root: Path, name: str) -> str:
    path = output_root / "runtime" / name
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _magick_version(executable: str) -> str:
    completed = subprocess.run(
        (executable, "-version"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    )
    return completed.stdout.strip() if completed.stdout else "unknown"


def resource_resolution_report(
    output_root: Path,
    *,
    expected_logs: Sequence[str] | None = None,
) -> dict[str, object]:
    if expected_logs is None:
        log_paths = sorted((output_root / "logs").glob("*/*.log"))
        missing_logs: list[str] = []
    else:
        log_paths = []
        missing_logs = []
        for relative in expected_logs:
            path = output_root / relative
            if path.is_file():
                log_paths.append(path)
            else:
                missing_logs.append(relative)
    matches: list[dict[str, str]] = []
    for path in log_paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if _MISSING_RESOURCE.search(line):
                matches.append(
                    {
                        "log": str(path.relative_to(output_root)),
                        "line": line.strip(),
                    }
                )
    return {
        "logsInspected": len(log_paths),
        "missingExpectedLogs": missing_logs,
        "missingResourceMessages": matches,
        "passes": bool(log_paths) and not missing_logs and not matches,
    }


def runtime_capture_evidence(
    output_root: Path,
    run_results: Sequence[dict[str, object]],
) -> dict[str, object]:
    captures: list[dict[str, object]] = []
    for run in run_results:
        relative_log = str(run["logPath"])
        log_path = output_root / relative_log
        matches = _EXPORT_EVIDENCE.findall(
            log_path.read_text(encoding="utf-8", errors="replace")
        )
        expected_cell = tuple(int(value) for value in run["cell"])  # type: ignore[arg-type]
        expected_bounds = (
            expected_cell[0] * TES3_CELL_SIZE - GUTTER_PIXELS * WORLD_UNITS_PER_PIXEL,
            (expected_cell[0] + 1) * TES3_CELL_SIZE
            + GUTTER_PIXELS * WORLD_UNITS_PER_PIXEL,
            expected_cell[1] * TES3_CELL_SIZE - GUTTER_PIXELS * WORLD_UNITS_PER_PIXEL,
            (expected_cell[1] + 1) * TES3_CELL_SIZE
            + GUTTER_PIXELS * WORLD_UNITS_PER_PIXEL,
        )
        evaluated: list[dict[str, object]] = []
        for match in matches:
            actual_cell = (int(match[0]), int(match[1]))
            actual_pixels = int(match[2])
            actual_world_extent = float(match[3])
            actual_center = (float(match[4]), float(match[5]))
            actual_bounds = tuple(float(value) for value in match[6:10])
            bound_error_pixels = max(
                abs(actual - expected) / WORLD_UNITS_PER_PIXEL
                for actual, expected in zip(actual_bounds, expected_bounds, strict=True)
            )
            expected_center = (
                (expected_cell[0] + 0.5) * TES3_CELL_SIZE,
                (expected_cell[1] + 0.5) * TES3_CELL_SIZE,
            )
            center_error_pixels = max(
                abs(actual - expected) / WORLD_UNITS_PER_PIXEL
                for actual, expected in zip(actual_center, expected_center, strict=True)
            )
            max_error_pixels = max(bound_error_pixels, center_error_pixels)
            evaluated.append(
                {
                    "actualCell": list(actual_cell),
                    "actualPixels": actual_pixels,
                    "actualWorldExtent": actual_world_extent,
                    "actualCenter": list(actual_center),
                    "actualBounds": list(actual_bounds),
                    "expectedBounds": list(expected_bounds),
                    "maxPixelError": max_error_pixels,
                    "passes": (
                        actual_cell == expected_cell
                        and actual_pixels == RAW_PIXELS
                        and actual_world_extent == RAW_PIXELS * WORLD_UNITS_PER_PIXEL
                        and max_error_pixels <= 1.0
                    ),
                }
            )
        passing = [item for item in evaluated if bool(item["passes"])]
        captures.append(
            {
                "run": f"{run['pass']}/{run['key']}",
                "cell": list(expected_cell),
                "cameraLogMatches": evaluated,
                "maxPixelError": min(
                    (float(item["maxPixelError"]) for item in evaluated),
                    default=None,
                ),
                "passes": len(passing) == 1 and len(evaluated) == 1,
            }
        )
    return {
        "captures": captures,
        "passes": bool(captures) and all(bool(item["passes"]) for item in captures),
    }


def analyse_outputs(
    *,
    output_root: Path,
    magick: str,
    sites: Sequence[ControlSite],
) -> dict[str, object]:
    controls: dict[str, object] = {}
    seams: dict[str, object] = {}
    reproducibility: dict[str, object] = {}
    coordinates: dict[str, object] = {}

    for site in sites:
        primary_raw = output_root / "raw/primary" / f"{site.slug}.png"
        repeat_raw = output_root / "raw/repeat" / f"{site.slug}.png"
        primary_webp = output_root / "controls" / f"{site.slug}.webp"
        repeat_webp = output_root / "repeat-controls" / f"{site.slug}.webp"
        primary = process_center(primary_raw, primary_webp, magick=magick)
        repeated = process_center(
            repeat_raw, repeat_webp, magick=magick, report_root=output_root
        )
        primary["path"] = str(primary_webp.relative_to(output_root))
        controls[site.slug] = primary
        primary_native = _decode_raw(primary_raw, magick=magick).crop(
            GUTTER_PIXELS, GUTTER_PIXELS, NATIVE_PIXELS, NATIVE_PIXELS
        )
        repeat_native = _decode_raw(repeat_raw, magick=magick).crop(
            GUTTER_PIXELS, GUTTER_PIXELS, NATIVE_PIXELS, NATIVE_PIXELS
        )
        native_difference = pixel_difference(primary_native, repeat_native)
        graded_difference = pixel_difference(
            apply_grade(primary_native), apply_grade(repeat_native)
        )
        within_pixel_tolerance = (
            _reproducibility_difference_passes(native_difference)
            and _reproducibility_difference_passes(graded_difference)
        )
        reproducibility[site.slug] = {
            "primarySha256": primary["sha256"],
            "repeatSha256": repeated["sha256"],
            "primaryRgbaSha256": primary["rgbaSha256"],
            "repeatRgbaSha256": repeated["rgbaSha256"],
            "primaryNativeRgbaSha256": primary["nativeRgbaSha256"],
            "repeatNativeRgbaSha256": repeated["nativeRgbaSha256"],
            "identicalEncodedWebp": primary["sha256"] == repeated["sha256"],
            "identicalGradedRgba": primary["rgbaSha256"] == repeated["rgbaSha256"],
            "identicalNativeRgba": (
                primary["nativeRgbaSha256"] == repeated["nativeRgbaSha256"]
            ),
            "identical": (
                primary["nativeRgbaSha256"] == repeated["nativeRgbaSha256"]
                and primary["rgbaSha256"] == repeated["rgbaSha256"]
                and primary["sha256"] == repeated["sha256"]
            ),
            "nativeDifference": _difference_report(native_difference),
            "gradedDifference": _difference_report(graded_difference),
            "withinPixelTolerance": within_pixel_tolerance,
            "passes": within_pixel_tolerance,
        }

        center = _decode_raw(primary_raw, magick=magick)
        east_path = output_root / "raw/primary" / f"{site.slug}-east.png"
        north_path = output_root / "raw/primary" / f"{site.slug}-north.png"
        east = _decode_raw(east_path, magick=magick)
        north = _decode_raw(north_path, magick=magick)
        site_seams: dict[str, object] = {}
        for direction, neighbor, neighbor_path in (
            ("east", east, east_path),
            ("north", north, north_path),
        ):
            difference = seam_overlap(
                center,
                neighbor,
                direction=direction,
                gutter_pixels=GUTTER_PIXELS,
            )
            site_seams[direction] = {
                **_difference_report(difference),
                "centerRawSha256": sha256_file(primary_raw),
                "neighborRawSha256": sha256_file(neighbor_path),
                "passes": _seam_difference_passes(difference),
            }
        seams[site.slug] = site_seams
        coordinates[site.slug] = coordinate_alignment(site)

    all_reproducible = all(
        bool(item["passes"]) for item in reproducibility.values()  # type: ignore[union-attr]
    )
    all_seamless = all(
        bool(direction["passes"])
        for site_result in seams.values()
        for direction in site_result.values()  # type: ignore[union-attr]
    )
    coordinates_pass = all(
        bool(item["passesOnePixelGate"]) for item in coordinates.values()  # type: ignore[union-attr]
    )
    return {
        "controls": controls,
        "reproducibility": {
            "controls": reproducibility,
            "comparison": "native and graded RGBA; exact hashes retained alongside bounded raster tolerance",
            "tolerance": {
                "maximumDifferingFraction": REPRO_MAX_DIFFERING_FRACTION,
                "maximumMeanAbsoluteChannelDelta": REPRO_MAX_MEAN_CHANNEL_DELTA,
                "maximumChannelDelta": REPRO_MAX_CHANNEL_DELTA,
            },
            "passes": all_reproducible,
        },
        "seams": {
            "controls": seams,
            "comparison": "32px raw overlap from independent 544px renders; visual seam receipt is also required",
            "tolerance": {
                "maximumDifferingFraction": SEAM_MAX_DIFFERING_FRACTION,
                "maximumMeanAbsoluteChannelDelta": SEAM_MAX_MEAN_CHANNEL_DELTA,
                "maximumChannelDelta": SEAM_MAX_CHANNEL_DELTA,
            },
            "passes": all_seamless,
        },
        "coordinates": {
            "controls": coordinates,
            "passes": coordinates_pass,
        },
        "contentQuality": {
            "controls": {
                slug: control["contentQuality"]
                for slug, control in controls.items()  # type: ignore[union-attr]
            },
            "passes": all(
                bool(control["contentQuality"]["passes"])
                for control in controls.values()  # type: ignore[index,union-attr]
            ),
        },
    }


def seam_evidence_fingerprint(seams: dict[str, object]) -> str:
    encoded = json.dumps(
        seams, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def visual_receipt_report(
    output_root: Path,
    controls: dict[str, object],
    seams: dict[str, object],
    *,
    profile_hash: str,
    execution_hash: str,
) -> dict[str, object]:
    receipt_path = output_root / "visual-receipt.json"
    if not receipt_path.is_file():
        return {
            "path": "visual-receipt.json",
            "present": False,
            "controls": {},
            "featureCoverage": [],
            "referenceCoverage": [],
            "seamsApproved": False,
            "passes": False,
        }
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Visual receipt must be a JSON object")
    receipt_controls = payload.get("controls")
    if not isinstance(receipt_controls, dict):
        raise ValueError("Visual receipt controls must be a JSON object")

    evaluated: dict[str, object] = {}
    all_features: set[str] = set()
    all_references: set[str] = set()
    for site in CONTROL_SITES:
        actual = controls.get(site.slug)
        receipt = receipt_controls.get(site.slug)
        if not isinstance(actual, dict) or not isinstance(receipt, dict):
            evaluated[site.slug] = {"passes": False, "reason": "missing control"}
            continue
        features = {
            str(value) for value in receipt.get("observedFeatures", ())
        }
        references = {
            str(value).casefold() for value in receipt.get("referencesCompared", ())
        }
        all_features.update(features)
        all_references.update(references)
        expected_references = {"land", "uesp"}
        if site.slug == "balmora":
            expected_references.add("mim")
        checks = {
            "approved": receipt.get("approved") is True,
            "webpHash": receipt.get("webpSha256") == actual.get("sha256"),
            "nativeRgbaHash": (
                receipt.get("nativeRgbaSha256") == actual.get("nativeRgbaSha256")
            ),
            "knownFeatures": features <= VISUAL_FEATURES,
            "hasFeatureEvidence": bool(features),
            "references": expected_references <= references,
            "notes": bool(str(receipt.get("notes", "")).strip()),
        }
        evaluated[site.slug] = {
            "observedFeatures": sorted(features),
            "referencesCompared": sorted(references),
            "checks": checks,
            "passes": all(checks.values()),
        }

    top_level_checks = {
        "schemaVersion": payload.get("schemaVersion") == 1,
        "profileId": payload.get("profileId") == PROFILE_ID,
        "profileFingerprint": payload.get("profileFingerprint") == profile_hash,
        "executionFingerprint": payload.get("executionFingerprint") == execution_hash,
        "exactControlSet": set(receipt_controls) == {site.slug for site in CONTROL_SITES},
        "allControlsApproved": all(
            isinstance(item, dict) and bool(item.get("passes"))
            for item in evaluated.values()
        ),
        "allRequiredFeaturesObserved": VISUAL_FEATURES <= all_features,
        "allReferenceKindsUsed": {"land", "mim", "uesp"} <= all_references,
        "seamEvidenceFingerprint": (
            payload.get("seamEvidenceFingerprint") == seam_evidence_fingerprint(seams)
        ),
        "seamsApproved": payload.get("seamsApproved") is True,
        "seamNotes": bool(str(payload.get("seamNotes", "")).strip()),
    }
    return {
        "path": "visual-receipt.json",
        "present": True,
        "reviewer": payload.get("reviewer"),
        "reviewedAt": payload.get("reviewedAt"),
        "controls": evaluated,
        "featureCoverage": sorted(all_features),
        "referenceCoverage": sorted(all_references),
        "seamsApproved": payload.get("seamsApproved") is True,
        "checks": top_level_checks,
        "passes": all(top_level_checks.values()),
    }


def write_visual_receipt_template(
    output_root: Path,
    controls: dict[str, object],
    seams: dict[str, object],
    *,
    profile_hash: str,
    execution_hash: str,
) -> None:
    path = output_root / "visual-receipt.template.json"
    template = {
        "schemaVersion": 1,
        "profileId": PROFILE_ID,
        "profileFingerprint": profile_hash,
        "executionFingerprint": execution_hash,
        "reviewer": "",
        "reviewedAt": "",
        "seamEvidenceFingerprint": seam_evidence_fingerprint(seams),
        "seamsApproved": False,
        "seamNotes": "",
        "controls": {
            site.slug: {
                "webpSha256": controls[site.slug]["sha256"],  # type: ignore[index]
                "nativeRgbaSha256": controls[site.slug]["nativeRgbaSha256"],  # type: ignore[index]
                "observedFeatures": [],
                "referencesCompared": [],
                "approved": False,
                "notes": "",
            }
            for site in CONTROL_SITES
        },
    }
    _write_report(path, template)


def evaluate_gate(
    *,
    analysis: dict[str, object],
    resources: dict[str, object],
    capture_evidence: dict[str, object],
    visual_receipt: dict[str, object],
    runtime: dict[str, object],
    image_info: DockerImageInfo,
) -> dict[str, bool]:
    gate = {
        "fiveControlsRendered": len(analysis["controls"]) == len(CONTROL_SITES),  # type: ignore[arg-type]
        "coordinatesWithinOnePixel": bool(capture_evidence["passes"]),
        "deterministic": bool(analysis["reproducibility"]["passes"]),  # type: ignore[index]
        "seamless": bool(analysis["seams"]["passes"]),  # type: ignore[index]
        "resourcesResolved": bool(resources["passes"]),
        "contentNonEmpty": bool(analysis["contentQuality"]["passes"]),  # type: ignore[index]
        "runtimeCameraTransformConfirmed": bool(capture_evidence["passes"]),
        "visualFeatureReceipt": bool(visual_receipt["passes"]),
        "dockerImageIdentity": image_info.contract_passes,
        "headlessLinuxDocker": bool(runtime["passes"]),
    }
    gate["passesAutomatedChecks"] = all(gate.values())
    return gate


def _write_report(path: Path, report: dict[str, object]) -> None:
    _atomic_write_text(
        path,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _reset_run_artifacts(output_root: Path) -> None:
    if output_root == Path(output_root.anchor):
        raise ValueError("OpenMW output root cannot be a filesystem root")
    for relative in (
        "runs",
        "raw",
        "logs",
        "runtime",
        "controls",
        "repeat-controls",
        "smoke",
    ):
        path = output_root / relative
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    for name in ("report.json", "smoke-report.json"):
        (output_root / name).unlink(missing_ok=True)


def runtime_environment_report(
    image_info: DockerImageInfo,
    *,
    build_manifest: str,
    glxinfo: str,
) -> dict[str, object]:
    renderer_matches = _GL_RENDERER.findall(glxinfo)
    renderer = renderer_matches[0].strip() if len(renderer_matches) == 1 else None
    manifest_commit = None
    for line in build_manifest.splitlines():
        if line.startswith("openmw_commit="):
            manifest_commit = line.partition("=")[2].strip()
            break
    checks = {
        "dockerImageIdentity": image_info.contract_passes,
        "linuxAmd64": image_info.os == "linux" and image_info.architecture == "amd64",
        "softwareRenderer": renderer is not None and "llvmpipe" in renderer.casefold(),
        "buildManifestCommit": manifest_commit == OPENMW_COMMIT,
    }
    return {
        "buildManifest": build_manifest,
        "glxinfo": glxinfo,
        "openGlRenderer": renderer,
        "checks": checks,
        "passes": all(checks.values()),
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Build and execute the Stage 4.5 OpenMW offscreen renderer gate."
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=repo_root.parent / "morr-dev",
        help="External proprietary game/mod input root (default: ../morr-dev).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / DEFAULT_OUTPUT,
        help="Ignored local output root.",
    )
    parser.add_argument("--image", default=DEFAULT_DOCKER_IMAGE)
    parser.add_argument("--magick", default="magick")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument(
        "--evaluate-only",
        action="store_true",
        help="Re-evaluate existing full outputs and visual receipt without rendering.",
    )
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="Render only Balmora once; does not evaluate the quality gate.",
    )
    parser.add_argument(
        "--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS
    )
    return parser.parse_args(argv)


def reevaluate_existing(
    *,
    repo_root: Path,
    output_root: Path,
    image: str,
    magick: str,
) -> int:
    report_path = output_root / "report.json"
    if not report_path.is_file():
        raise FileNotFoundError(f"Existing Stage 4.5 report is missing: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("status") != "evaluated":
        raise ValueError("Existing Stage 4.5 report is not a full evaluated report")

    renderer_hash = renderer_fingerprint(repo_root)
    image_info = docker_image_info(image, expected_renderer_hash=renderer_hash)
    if not image_info.contract_passes:
        raise RuntimeError(
            "Docker image identity check failed: " + "; ".join(image_info.contract_errors)
        )
    profile = report.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("Existing Stage 4.5 report has no profile object")
    profile_hash = str(profile.get("fingerprint", ""))
    magick_provenance = _magick_version(magick)
    execution_hash = hashlib.sha256(
        (
            renderer_hash
            + "\0"
            + image_info.image_id
            + "\0"
            + profile_hash
            + "\0"
            + magick_provenance
        ).encode("utf-8")
    ).hexdigest()
    if report.get("rendererFingerprint") != renderer_hash:
        raise ValueError("Existing outputs were produced by a different renderer source")
    if report.get("executionFingerprint") != execution_hash:
        raise ValueError("Existing outputs were produced by a different execution toolchain")

    runs = report.get("runs")
    runtime = report.get("runtime")
    if not isinstance(runs, list) or not isinstance(runtime, dict):
        raise ValueError("Existing Stage 4.5 report has no runs/runtime evidence")
    analysis = analyse_outputs(
        output_root=output_root,
        magick=magick,
        sites=CONTROL_SITES,
    )
    expected_logs = [
        str(run[key])
        for run in runs
        for key in ("logPath", "engineLogPath")
    ]
    resources = resource_resolution_report(output_root, expected_logs=expected_logs)
    capture_evidence = runtime_capture_evidence(output_root, runs)
    visual_receipt = visual_receipt_report(
        output_root,
        analysis["controls"],  # type: ignore[arg-type]
        analysis["seams"],  # type: ignore[arg-type]
        profile_hash=profile_hash,
        execution_hash=execution_hash,
    )
    report.update(analysis)
    report["resourceResolution"] = resources
    report["runtimeCaptureEvidence"] = capture_evidence
    report["visualReceipt"] = visual_receipt
    gate = evaluate_gate(
        analysis=analysis,
        resources=resources,
        capture_evidence=capture_evidence,
        visual_receipt=visual_receipt,
        runtime=runtime,
        image_info=image_info,
    )
    report["gate"] = gate
    _write_report(report_path, report)
    print(json.dumps(gate, ensure_ascii=False, sort_keys=True))
    return 0 if gate["passesAutomatedChecks"] else 2


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")

    repo_root = Path(__file__).resolve().parents[2]
    source_root = args.source_root.resolve()
    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if args.evaluate_only:
        if args.smoke_only or not args.skip_build:
            raise ValueError("--evaluate-only requires --skip-build and cannot use --smoke-only")
        return reevaluate_existing(
            repo_root=repo_root,
            output_root=output_root,
            image=args.image,
            magick=args.magick,
        )
    _reset_run_artifacts(output_root)

    input_audit = validate_source_inputs(source_root)
    asset_audit = fingerprint_data_directories(source_root)
    openmw_cfg = render_openmw_cfg()
    settings_cfg = render_settings_cfg()
    profile_hash = profile_fingerprint(
        input_audit,
        asset_audit=asset_audit,
        openmw_cfg=openmw_cfg,
        settings_cfg=settings_cfg,
    )
    renderer_hash = renderer_fingerprint(repo_root)
    build_seconds = None
    if not args.skip_build:
        build_seconds = build_image(
            repo_root,
            args.image,
            renderer_hash=renderer_hash,
            timeout_seconds=max(args.timeout_seconds, 60 * 60),
        )
    image_info = docker_image_info(
        args.image, expected_renderer_hash=renderer_hash
    )
    if not image_info.contract_passes:
        raise RuntimeError(
            "Docker image identity check failed: " + "; ".join(image_info.contract_errors)
        )
    runtime_image = image_info.image_id
    magick_provenance = _magick_version(args.magick)
    execution_hash = hashlib.sha256(
        (
            renderer_hash
            + "\0"
            + runtime_image
            + "\0"
            + profile_hash
            + "\0"
            + magick_provenance
        ).encode("utf-8")
    ).hexdigest()

    targets: tuple[RenderTarget, ...]
    if args.smoke_only:
        site = CONTROL_SITES[0]
        targets = (RenderTarget(site.slug, site.slug, "smoke", site.cell),)
    else:
        targets = primary_targets() + repeat_targets()

    run_results: list[dict[str, object]] = []
    for index, target in enumerate(targets, start=1):
        print(
            f"[{index}/{len(targets)}] OpenMW {target.pass_name}/{target.key} "
            f"cell={target.cell[0]},{target.cell[1]}",
            flush=True,
        )
        run_results.append(
            run_target(
                image=runtime_image,
                source_root=source_root,
                output_root=output_root,
                target=target,
                timeout_seconds=args.timeout_seconds,
            )
        )

    base_report: dict[str, object] = {
        "schemaVersion": 1,
        "rendererVersion": RENDERER_VERSION,
        "profileId": PROFILE_ID,
        "status": "smoke" if args.smoke_only else "evaluated",
        "pins": {
            "openmwRelease": OPENMW_RELEASE,
            "openmwCommit": OPENMW_COMMIT,
            "openmwSource": OPENMW_SOURCE_URL,
            "dockerPlatform": DOCKER_PLATFORM,
            "dockerBaseImage": DOCKER_BASE_IMAGE,
            "ubuntuSnapshot": UBUNTU_SNAPSHOT,
            "dockerImage": asdict(image_info),
        },
        "profile": {
            "fingerprint": profile_hash,
            "dataDirectories": list(DATA_DIRECTORIES),
            "fallbackArchives": list(FALLBACK_ARCHIVES),
            "contentFiles": list(CONTENT_FILES),
            "excludedDynamicContentFiles": list(EXCLUDED_DYNAMIC_CONTENT_FILES),
            "dynamicContentPolicy": (
                "Pinned .omwscripts manifests are fingerprinted but excluded: their distributions contain "
                "no referenced Lua resources, and UI/actors/dynamic gameplay are outside this renderer."
            ),
            "inputs": input_audit,
            "assetTrees": asset_audit,
            "knownWarnings": [
                "TR_Mainland.esm records Tamriel_Data.esm master size 776 bytes above the pinned file; runtime acceptance is audited in logs."
            ],
        },
        "render": {
            "nativePixels": NATIVE_PIXELS,
            "gutterPixels": GUTTER_PIXELS,
            "rawPixels": RAW_PIXELS,
            "worldUnitsPerPixel": WORLD_UNITS_PER_PIXEL,
            "rawWorldExtent": RAW_PIXELS * WORLD_UNITS_PER_PIXEL,
            "lighting": "OpenMW LocalMap fixed ambient=0.3, diffuse=0.7, direction=(-0.3,-0.3,0.7)",
            "cullMask": ["Scene", "SimpleWater", "Terrain", "Static"],
            "excluded": [
                "UI",
                "actors",
                "player",
                "dynamic objects (Mask_Object)",
                "sky",
                "fog",
                "weather",
                "shadows",
            ],
            "gradeVersion": GRADE_VERSION,
            "grade": asdict(DEFAULT_GRADE),
            "magick": magick_provenance,
        },
        "rendererFingerprint": renderer_hash,
        "executionFingerprint": execution_hash,
        "buildSeconds": round(build_seconds, 3) if build_seconds is not None else None,
        "runs": run_results,
        "runtime": runtime_environment_report(
            image_info,
            build_manifest=_runtime_text(output_root, "openmw-build-manifest.txt"),
            glxinfo=_runtime_text(output_root, "glxinfo.txt"),
        ),
    }

    if args.smoke_only:
        raw_path = output_root / "raw/smoke/balmora.png"
        smoke_output = output_root / "smoke/balmora.webp"
        base_report["smokeOutput"] = process_center(
            raw_path, smoke_output, magick=args.magick, report_root=output_root
        )
        expected_logs = [
            str(run_results[0][key]) for key in ("logPath", "engineLogPath")
        ]
        base_report["resourceResolution"] = resource_resolution_report(
            output_root, expected_logs=expected_logs
        )
        base_report["runtimeCaptureEvidence"] = runtime_capture_evidence(
            output_root, run_results
        )
        _write_report(output_root / "smoke-report.json", base_report)
        print(f"Smoke render written to {smoke_output}")
        return 0

    analysis = analyse_outputs(
        output_root=output_root,
        magick=args.magick,
        sites=CONTROL_SITES,
    )
    expected_logs = [
        str(run[key])
        for run in run_results
        for key in ("logPath", "engineLogPath")
    ]
    resources = resource_resolution_report(output_root, expected_logs=expected_logs)
    capture_evidence = runtime_capture_evidence(output_root, run_results)
    base_report.update(analysis)
    base_report["resourceResolution"] = resources
    base_report["runtimeCaptureEvidence"] = capture_evidence
    write_visual_receipt_template(
        output_root,
        analysis["controls"],  # type: ignore[arg-type]
        analysis["seams"],  # type: ignore[arg-type]
        profile_hash=profile_hash,
        execution_hash=execution_hash,
    )
    visual_receipt = visual_receipt_report(
        output_root,
        analysis["controls"],  # type: ignore[arg-type]
        analysis["seams"],  # type: ignore[arg-type]
        profile_hash=profile_hash,
        execution_hash=execution_hash,
    )
    base_report["visualReceipt"] = visual_receipt
    gate = evaluate_gate(
        analysis=analysis,
        resources=resources,
        capture_evidence=capture_evidence,
        visual_receipt=visual_receipt,
        runtime=base_report["runtime"],  # type: ignore[arg-type]
        image_info=image_info,
    )
    base_report["gate"] = gate
    _write_report(output_root / "report.json", base_report)
    print(json.dumps(gate, ensure_ascii=False, sort_keys=True))
    return 0 if gate["passesAutomatedChecks"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"OpenMW renderer spike failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
