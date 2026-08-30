from __future__ import annotations

from dataclasses import dataclass

from tools.land_renderer.terrain import RgbaImage


GRADE_VERSION = "mim-muted-v1"
PRODUCTION_GRADE_VERSION = "mim-opaque-v4"
PRODUCTION_ALPHA_MODE = "binary-nonzero"


@dataclass(frozen=True, slots=True)
class GradeStyle:
    brightness_percent: int = 104
    contrast_percent: int = 108
    saturation_percent: int = 92

    def __post_init__(self) -> None:
        for value in (
            self.brightness_percent,
            self.contrast_percent,
            self.saturation_percent,
        ):
            if not 0 <= value <= 300:
                raise ValueError("Grade percentages must be between 0 and 300")


DEFAULT_GRADE = GradeStyle()
PRODUCTION_GRADE = GradeStyle(
    brightness_percent=114,
    contrast_percent=102,
    saturation_percent=92,
)


def _clamp_byte(value: int) -> int:
    return max(0, min(255, value))


def apply_grade(image: RgbaImage, style: GradeStyle = DEFAULT_GRADE) -> RgbaImage:
    """Apply an integer-only muted MIM-like grade without changing alpha."""

    output = bytearray(len(image.pixels))
    for offset in range(0, len(image.pixels), 4):
        red, green, blue, alpha = image.pixels[offset : offset + 4]
        luminance = (54 * red + 183 * green + 19 * blue + 128) // 256
        channels = (red, green, blue)
        for index, channel in enumerate(channels):
            saturated = (
                luminance * (100 - style.saturation_percent)
                + channel * style.saturation_percent
                + 50
            ) // 100
            contrasted = 128 + ((saturated - 128) * style.contrast_percent + 50) // 100
            brightened = (contrasted * style.brightness_percent + 50) // 100
            output[offset + index] = _clamp_byte(brightened)
        output[offset + 3] = alpha
    return RgbaImage(image.width, image.height, bytes(output))


def normalize_binary_alpha(image: RgbaImage) -> RgbaImage:
    """Return a binary-alpha image while preserving every RGB channel.

    Fully transparent sparse coverage stays transparent. Any rendered pixel,
    including OpenMW's translucent water, becomes fully opaque.
    """

    output = bytearray(image.pixels)
    for alpha_offset in range(3, len(output), 4):
        if output[alpha_offset] != 0:
            output[alpha_offset] = 255
    return RgbaImage(image.width, image.height, bytes(output))


@dataclass(frozen=True, slots=True)
class PixelDifference:
    pixels: int
    differing_pixels: int
    mean_absolute_channel_delta: float
    maximum_channel_delta: int

    @property
    def differing_fraction(self) -> float:
        return self.differing_pixels / self.pixels if self.pixels else 0.0


def pixel_difference(left: RgbaImage, right: RgbaImage) -> PixelDifference:
    if (left.width, left.height) != (right.width, right.height):
        raise ValueError("Images must have the same dimensions")
    pixel_count = left.width * left.height
    differing_pixels = 0
    total_delta = 0
    maximum_delta = 0
    for offset in range(0, len(left.pixels), 4):
        pixel_changed = False
        for channel in range(4):
            delta = abs(left.pixels[offset + channel] - right.pixels[offset + channel])
            total_delta += delta
            maximum_delta = max(maximum_delta, delta)
            pixel_changed = pixel_changed or delta != 0
        if pixel_changed:
            differing_pixels += 1
    return PixelDifference(
        pixels=pixel_count,
        differing_pixels=differing_pixels,
        mean_absolute_channel_delta=total_delta / (pixel_count * 4),
        maximum_channel_delta=maximum_delta,
    )


def seam_overlap(
    center: RgbaImage,
    neighbor: RgbaImage,
    *,
    direction: str,
    gutter_pixels: int,
) -> PixelDifference:
    if gutter_pixels <= 0:
        raise ValueError("A positive gutter is required for overlap comparison")
    if (center.width, center.height) != (neighbor.width, neighbor.height):
        raise ValueError("Seam images must have the same dimensions")
    overlap = gutter_pixels * 2
    native_size = center.width - overlap
    if native_size <= 0 or center.height != center.width:
        raise ValueError("Seam images must be square native tiles with symmetric gutters")

    if direction == "east":
        left_strip = center.crop(native_size, 0, overlap, center.height)
        right_strip = neighbor.crop(0, 0, overlap, neighbor.height)
    elif direction == "north":
        left_strip = center.crop(0, 0, center.width, overlap)
        right_strip = neighbor.crop(0, native_size, neighbor.width, overlap)
    else:
        raise ValueError("Direction must be east or north")
    return pixel_difference(left_strip, right_strip)
