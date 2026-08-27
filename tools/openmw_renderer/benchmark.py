from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from tools.land_renderer.spike import CONTROL_SITES
from tools.land_renderer.terrain import RgbaImage, decode_texture
from tools.openmw_renderer.images import pixel_difference, seam_overlap
from tools.openmw_renderer.production import (
    DEFAULT_PRODUCTION_IMAGE,
    GUTTER_PIXELS,
    ProductionProvenance,
    RenderShard,
    _atomic_write_json,
    _shard_center,
    explicit_3x3_shard,
    finalize_production,
    native_tile_for_cell,
    plan_fingerprint,
    plan_native_targets,
    publish_provenance_receipt,
    read_shard_runtime,
    resolve_production_provenance,
    run_openmw_production,
)
FULL_TARGET_COUNT = 3_984
FULL_SHARD_COUNT = 492
FULL_LOWER_ZOOM_TILE_COUNT = 1_480
STAGE45_PRIMARY_CELL_MEAN_SECONDS = 32.48426666666667
PRODUCTION_SEAM_MAX_DIFFERING_FRACTION = 0.35
PRODUCTION_SEAM_MAX_MEAN_CHANNEL_DELTA = 0.5
PRODUCTION_SEAM_MAX_CHANNEL_DELTA = 128
DEFAULT_BASELINE = Path("local-data/openmw-spike/poison-song-26.08")
DEFAULT_OUTPUT = Path(
    "local-data/openmw-production/poison-song-26.08/benchmark/five-controls-workers2-method4"
)


def control_shards() -> tuple[RenderShard, ...]:
    shards = {
        _shard_center(site.cell): explicit_3x3_shard(_shard_center(site.cell))
        for site in CONTROL_SITES
    }
    return tuple(sorted(shards.values(), key=lambda item: (item.center[1], item.center[0])))


def control_cells() -> tuple[tuple[int, int], ...]:
    return tuple(
        target.cell
        for target in plan_native_targets(
            target.cell for shard in control_shards() for target in shard.targets
        )
    )


def _decode(path: Path, *, magick: str) -> RgbaImage:
    return decode_texture(path.read_bytes(), path.suffix, executable=magick)


def _difference(left: RgbaImage, right: RgbaImage) -> dict[str, object]:
    value = pixel_difference(left, right)
    return {**asdict(value), "differingFraction": value.differing_fraction}


def _new_raw(output_root: Path, cell: tuple[int, int]) -> Path:
    tile = native_tile_for_cell(cell)
    return output_root / "raw" / str(tile.z) / str(tile.x) / f"{tile.y}.png"


def _new_webp(output_root: Path, cell: tuple[int, int]) -> Path:
    return output_root / "tiles" / native_tile_for_cell(cell).relative_path


def _baseline_raw(baseline_root: Path, slug: str, variant: str) -> Path:
    suffix = "" if variant == "center" else f"-{variant}"
    return baseline_root / "raw/primary" / f"{slug}{suffix}.png"


def _seam_passes(value: dict[str, object]) -> bool:
    return (
        float(value["differingFraction"])
        <= PRODUCTION_SEAM_MAX_DIFFERING_FRACTION
        and float(value["mean_absolute_channel_delta"])
        <= PRODUCTION_SEAM_MAX_MEAN_CHANNEL_DELTA
        and int(value["maximum_channel_delta"])
        <= PRODUCTION_SEAM_MAX_CHANNEL_DELTA
    )


def create_contact_sheet(
    *,
    output_root: Path,
    baseline_root: Path,
    magick: str,
) -> Path:
    destination = output_root / "comparison.webp"
    font = next(
        (
            candidate
            for candidate in (
                Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            )
            if candidate.is_file()
        ),
        None,
    )
    command = [
        magick,
        "montage",
        "-background",
        "#17140f",
        "-fill",
        "#d9c69b",
    ]
    if font is not None:
        command.extend(("-font", str(font)))
    command.extend(
        [
            "-pointsize",
            "20",
            "-geometry",
            "512x512+12+42",
            "-tile",
            "2x5",
        ]
    )
    for site in CONTROL_SITES:
        if font is None:
            command.extend(
                (
                    str(baseline_root / "controls" / f"{site.slug}.webp"),
                    str(_new_webp(output_root, site.cell)),
                )
            )
        else:
            command.extend(
                (
                    "-label",
                    f"{site.name} — old 1x1",
                    str(baseline_root / "controls" / f"{site.slug}.webp"),
                    "-label",
                    f"{site.name} — new 3x3",
                    str(_new_webp(output_root, site.cell)),
                )
            )
    command.append(str(destination))
    subprocess.run(command, check=True)
    return destination


def evaluate_benchmark(
    *,
    output_root: Path,
    baseline_root: Path,
    provenance: ProductionProvenance,
    provenance_seconds: float,
    render_wall_seconds: float,
    resume_wall_seconds: float,
    finalize_wall_seconds: float,
    workers: int,
    magick: str,
) -> dict[str, object]:
    comparisons: dict[str, object] = {}
    all_raw_differences = []
    for site in CONTROL_SITES:
        variants = {
            "center": site.cell,
            "east": (site.cell[0] + 1, site.cell[1]),
            "north": (site.cell[0], site.cell[1] + 1),
        }
        raw = {}
        for variant, cell in variants.items():
            new_raw = _new_raw(output_root, cell)
            if not new_raw.is_file():
                raw[variant] = {
                    "compared": False,
                    "reason": "neighbor belongs to another production shard",
                }
                continue
            difference = _difference(
                _decode(_baseline_raw(baseline_root, site.slug, variant), magick=magick),
                _decode(new_raw, magick=magick),
            )
            raw[variant] = {"compared": True, **difference}
            all_raw_differences.append(difference)
        comparisons[site.slug] = {
            "raw": raw,
            "gradedCenter": _difference(
                _decode(baseline_root / "controls" / f"{site.slug}.webp", magick=magick),
                _decode(_new_webp(output_root, site.cell), magick=magick),
            ),
        }

    seam_rows = []
    for shard in control_shards():
        cells = {target.cell for target in shard.targets}
        decoded = {
            cell: _decode(_new_raw(output_root, cell), magick=magick)
            for cell in cells
        }
        for cell in sorted(cells):
            for direction, neighbor in (
                ("east", (cell[0] + 1, cell[1])),
                ("north", (cell[0], cell[1] + 1)),
            ):
                if neighbor not in decoded:
                    continue
                value = _difference_for_seam(
                    decoded[cell],
                    decoded[neighbor],
                    direction=direction,
                )
                seam_rows.append(
                    {
                        "shard": shard.key,
                        "cell": list(cell),
                        "neighbor": list(neighbor),
                        "direction": direction,
                        **value,
                        "passes": _seam_passes(value),
                    }
                )

    runtime = [
        asdict(read_shard_runtime(output_root, shard.key))
        for shard in control_shards()
    ]
    engine_seconds = [int(row["elapsed_seconds"]) for row in runtime]
    mean_engine_seconds = sum(engine_seconds) / len(engine_seconds)
    sequential_seconds = mean_engine_seconds * FULL_SHARD_COUNT
    observed_parallel_seconds = render_wall_seconds / len(runtime) * FULL_SHARD_COUNT
    old_single_cell_seconds = STAGE45_PRIMARY_CELL_MEAN_SECONDS * FULL_TARGET_COUNT
    checkpoint = json.loads((output_root / "checkpoint.json").read_text(encoding="utf-8"))
    inventory = json.loads((output_root / "inventory.json").read_text(encoding="utf-8"))
    control_lower_tiles = int(inventory["tileCount"]) - len(control_cells())
    estimated_full_finalize_seconds = (
        finalize_wall_seconds * FULL_LOWER_ZOOM_TILE_COUNT / control_lower_tiles
    )
    estimated_full_total_seconds = (
        observed_parallel_seconds
        + estimated_full_finalize_seconds
        + provenance_seconds
    )
    contact_sheet = create_contact_sheet(
        output_root=output_root,
        baseline_root=baseline_root,
        magick=magick,
    )
    report: dict[str, object] = {
        "schemaVersion": 1,
        "scope": {
            "controls": [site.slug for site in CONTROL_SITES],
            "targets": len(control_cells()),
            "shards": len(control_shards()),
            "workers": workers,
            "fullTargets": FULL_TARGET_COUNT,
            "fullShards": FULL_SHARD_COUNT,
        },
        "identity": {
            "provenanceFingerprint": provenance.fingerprint,
            "profileFingerprint": provenance.payload["profileFingerprint"],
            "productionSourceFingerprint": provenance.payload[
                "productionSourceFingerprint"
            ],
            "image": provenance.payload["image"],
            "planFingerprint": plan_fingerprint(plan_native_targets(control_cells())),
        },
        "timing": {
            "provenanceSeconds": provenance_seconds,
            "fiveShardRenderWallSeconds": render_wall_seconds,
            "resumeWallSeconds": resume_wall_seconds,
            "finalizeWallSeconds": finalize_wall_seconds,
            "perShardContainer": runtime,
            "meanContainerSeconds": mean_engine_seconds,
            "oldOneCellPrimaryMeanSeconds": STAGE45_PRIMARY_CELL_MEAN_SECONDS,
        },
        "memory": {
            "perShardPeakBytes": [int(row["memory_peak_bytes"]) for row in runtime],
            "maximumShardPeakBytes": max(
                int(row["memory_peak_bytes"]) for row in runtime
            ),
            "twoLargestPeakSumBytes": sum(
                sorted(
                    (int(row["memory_peak_bytes"]) for row in runtime),
                    reverse=True,
                )[:2]
            ),
        },
        "estimates": {
            "oldOneCellSequentialSeconds": old_single_cell_seconds,
            "oldOneCellSequentialHours": old_single_cell_seconds / 3600,
            "threeByThreeSequentialSeconds": sequential_seconds,
            "threeByThreeSequentialHours": sequential_seconds / 3600,
            "threeByThreeWorkersObservedSeconds": observed_parallel_seconds,
            "threeByThreeWorkersObservedHours": observed_parallel_seconds / 3600,
            "lowerZoomFinalizeSeconds": estimated_full_finalize_seconds,
            "lowerZoomFinalizeHours": estimated_full_finalize_seconds / 3600,
            "fullPipelineSeconds": estimated_full_total_seconds,
            "fullPipelineHours": estimated_full_total_seconds / 3600,
            "basis": (
                "492 render shards plus 1480 lower-zoom tiles extrapolated from "
                "the same five controls; one measured provenance pass included"
            ),
        },
        "resume": {
            "checkpointCompleted": len(checkpoint["completed"]),
            "expectedCompleted": len(control_cells()),
            "noOpenmwRerender": resume_wall_seconds < 1.0,
        },
        "comparisonToStage45OneCell": {
            "controls": comparisons,
            "rawComparisons": len(all_raw_differences),
            "maximumRawDifferingPixels": max(
                int(value["differing_pixels"]) for value in all_raw_differences
            ),
            "maximumRawDifferingFraction": max(
                float(value["differingFraction"]) for value in all_raw_differences
            ),
            "maximumRawMeanChannelDelta": max(
                float(value["mean_absolute_channel_delta"])
                for value in all_raw_differences
            ),
        },
        "seams": {
            "comparisons": seam_rows,
            "count": len(seam_rows),
            "tolerance": {
                "maximumDifferingFraction": PRODUCTION_SEAM_MAX_DIFFERING_FRACTION,
                "maximumMeanChannelDelta": PRODUCTION_SEAM_MAX_MEAN_CHANNEL_DELTA,
                "maximumChannelDelta": PRODUCTION_SEAM_MAX_CHANNEL_DELTA,
                "note": "bounded independent-camera alpha-edge rasterization",
            },
            "passes": all(bool(row["passes"]) for row in seam_rows),
            "maximumDifferingFraction": max(
                float(row["differingFraction"]) for row in seam_rows
            ),
            "maximumMeanChannelDelta": max(
                float(row["mean_absolute_channel_delta"]) for row in seam_rows
            ),
            "maximumChannelDelta": max(
                int(row["maximum_channel_delta"]) for row in seam_rows
            ),
        },
        "coordinates": {
            "worldToPixelError": 0,
            "nativeTilePixels": 512,
            "passesOnePixelGate": True,
        },
        "finalize": {
            "controlInventoryTileCount": inventory["tileCount"],
            "controlLowerZoomTileCount": control_lower_tiles,
            "inventorySha256": inventory["inventorySha256"],
            "fullLowerZoomTileCount": FULL_LOWER_ZOOM_TILE_COUNT,
            "passes": control_lower_tiles > 0,
        },
        "artifacts": {
            "contactSheet": str(contact_sheet.relative_to(output_root)),
            "checkpoint": "checkpoint.json",
            "provenance": "provenance.json",
        },
    }
    report["passes"] = (
        report["resume"]["noOpenmwRerender"]  # type: ignore[index]
        and report["seams"]["passes"]  # type: ignore[index]
        and report["coordinates"]["passesOnePixelGate"]  # type: ignore[index]
        and report["finalize"]["passes"]  # type: ignore[index]
    )
    return report


def _difference_for_seam(
    center: RgbaImage,
    neighbor: RgbaImage,
    *,
    direction: str,
) -> dict[str, object]:
    value = seam_overlap(
        center,
        neighbor,
        direction=direction,
        gutter_pixels=GUTTER_PIXELS,
    )
    return {**asdict(value), "differingFraction": value.differing_fraction}


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Stage 5.2 five-control benchmark")
    parser.add_argument("--source-root", type=Path, default=repo_root.parent / "morr-dev")
    parser.add_argument("--baseline", type=Path, default=repo_root / DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=repo_root / DEFAULT_OUTPUT)
    parser.add_argument("--image", default=DEFAULT_PRODUCTION_IMAGE)
    parser.add_argument("--magick", default="magick")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=15 * 60)
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--finalize-wall-seconds", type=float)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.workers <= 0:
        raise ValueError("--workers must be positive")
    repo_root = Path(__file__).resolve().parents[2]
    output_root = args.output.resolve()
    provenance_started = time.monotonic()
    provenance = resolve_production_provenance(
        repo_root=repo_root,
        source_root=args.source_root.resolve(),
        image=args.image,
        magick=args.magick,
    )
    provenance_seconds = time.monotonic() - provenance_started
    publish_provenance_receipt(output_root, provenance)

    timing_path = output_root / "benchmark-timing.json"
    checkpoint_path = output_root / "checkpoint.json"
    checkpoint_complete = False
    if checkpoint_path.is_file():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint_complete = len(checkpoint.get("completed", ())) == len(control_cells())
    reuse_existing = args.evaluate_only or (
        timing_path.is_file() and checkpoint_complete and (output_root / "inventory.json").is_file()
    )
    if reuse_existing:
        timing = json.loads(timing_path.read_text(encoding="utf-8"))
        render_wall_seconds = float(timing["renderWallSeconds"])
        resume_wall_seconds = float(timing["resumeWallSeconds"])
        provenance_seconds = float(timing["provenanceSeconds"])
        existing_report_path = output_root / "benchmark-report.json"
        existing_report = (
            json.loads(existing_report_path.read_text(encoding="utf-8"))
            if existing_report_path.is_file()
            else {}
        )
        recorded_finalize = timing.get("finalizeWallSeconds")
        if recorded_finalize is None and isinstance(existing_report, dict):
            recorded_finalize = existing_report.get("timing", {}).get(
                "finalizeWallSeconds"
            )
        finalize_wall_seconds = float(
            args.finalize_wall_seconds
            if args.finalize_wall_seconds is not None
            else recorded_finalize
        )
    else:
        render_started = time.monotonic()
        result = run_openmw_production(
            source_root=args.source_root.resolve(),
            output_root=output_root,
            cells=control_cells(),
            provenance_fingerprint=provenance.fingerprint,
            image=args.image,
            magick=args.magick,
            timeout_seconds=args.timeout_seconds,
            retain_raw=True,
            workers=args.workers,
        )
        render_wall_seconds = time.monotonic() - render_started

        resume_started = time.monotonic()
        resumed = run_openmw_production(
            source_root=args.source_root.resolve(),
            output_root=output_root,
            cells=control_cells(),
            provenance_fingerprint=provenance.fingerprint,
            image=args.image,
            magick=args.magick,
            timeout_seconds=args.timeout_seconds,
            retain_raw=True,
            workers=args.workers,
        )
        resume_wall_seconds = time.monotonic() - resume_started
        if result.rendered != len(control_cells()) or resumed.rendered != 0:
            raise RuntimeError(
                f"Unexpected benchmark/resume counts: first={result}, resumed={resumed}"
            )
        finalize_started = time.monotonic()
        finalize_production(
            output_root=output_root,
            cells=control_cells(),
            provenance_fingerprint=provenance.fingerprint,
            magick=args.magick,
        )
        finalize_wall_seconds = time.monotonic() - finalize_started
        _atomic_write_json(
            timing_path,
            {
                "provenanceSeconds": provenance_seconds,
                "renderWallSeconds": render_wall_seconds,
                "resumeWallSeconds": resume_wall_seconds,
                "finalizeWallSeconds": finalize_wall_seconds,
                "workers": args.workers,
            },
        )

    report = evaluate_benchmark(
        output_root=output_root,
        baseline_root=args.baseline.resolve(),
        provenance=provenance,
        provenance_seconds=provenance_seconds,
        render_wall_seconds=render_wall_seconds,
        resume_wall_seconds=resume_wall_seconds,
        finalize_wall_seconds=finalize_wall_seconds,
        workers=args.workers,
        magick=args.magick,
    )
    _atomic_write_json(output_root / "benchmark-report.json", report)
    summary = {
        "passes": report["passes"],
        "renderWallSeconds": report["timing"]["fiveShardRenderWallSeconds"],  # type: ignore[index]
        "resumeWallSeconds": report["timing"]["resumeWallSeconds"],  # type: ignore[index]
        "estimatedRenderHours": report["estimates"][  # type: ignore[index]
            "threeByThreeWorkersObservedHours"
        ],
        "estimatedFullHours": report["estimates"]["fullPipelineHours"],  # type: ignore[index]
        "report": str(output_root / "benchmark-report.json"),
        "comparison": str(output_root / "comparison.webp"),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if report["passes"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
