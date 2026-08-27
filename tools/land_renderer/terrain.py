from __future__ import annotations

import hashlib
import math
import os
import subprocess
import tempfile
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from tools.land_renderer.tiles import (
    CELL_PIXEL_SIZE,
    LAND_TEXTURES_PER_SIDE,
    LAND_TEXTURE_WORLD_SIZE,
    LAND_VERTEX_SPACING,
    LAND_VERTICES_PER_SIDE,
    RasterGrid,
    TES3_CELL_SIZE,
    cell_raster_grid,
    world_to_cell,
)


Rgb: TypeAlias = tuple[int, int, int]
Rgba: TypeAlias = tuple[int, int, int, int]
TextureKey: TypeAlias = Hashable


def _validate_channel(value: int) -> None:
    if not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError("RGBA channels must be integers from 0 through 255")


@dataclass(frozen=True, slots=True)
class RgbaImage:
    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Image dimensions must be positive")
        if len(self.pixels) != self.width * self.height * 4:
            raise ValueError("RGBA payload size does not match image dimensions")
        object.__setattr__(self, "pixels", bytes(self.pixels))

    @classmethod
    def solid(cls, width: int, height: int, color: Rgba) -> RgbaImage:
        for channel in color:
            _validate_channel(channel)
        return cls(width, height, bytes(color) * (width * height))

    def pixel(self, x: int, y: int) -> Rgba:
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise IndexError("Pixel is outside the image")
        offset = (y * self.width + x) * 4
        return tuple(self.pixels[offset : offset + 4])  # type: ignore[return-value]

    def crop(self, left: int, top: int, width: int, height: int) -> RgbaImage:
        if (
            left < 0
            or top < 0
            or width <= 0
            or height <= 0
            or left + width > self.width
            or top + height > self.height
        ):
            raise ValueError("Crop rectangle is outside the image")
        stride = self.width * 4
        row_bytes = width * 4
        cropped = bytearray(row_bytes * height)
        for target_y in range(height):
            source_offset = (top + target_y) * stride + left * 4
            target_offset = target_y * row_bytes
            cropped[target_offset : target_offset + row_bytes] = self.pixels[
                source_offset : source_offset + row_bytes
            ]
        return RgbaImage(width, height, bytes(cropped))

    def sample_repeat(self, u: float, v: float) -> Rgba:
        """Bilinearly sample repeating normalized texture coordinates."""

        if not math.isfinite(u) or not math.isfinite(v):
            raise ValueError("Texture coordinates must be finite")
        source_x = (u % 1.0) * self.width - 0.5
        source_y = (v % 1.0) * self.height - 0.5
        x0 = math.floor(source_x)
        y0 = math.floor(source_y)
        fx = source_x - x0
        fy = source_y - y0
        x1 = x0 + 1
        y1 = y0 + 1
        corners = (
            (x0 % self.width, y0 % self.height, (1.0 - fx) * (1.0 - fy)),
            (x1 % self.width, y0 % self.height, fx * (1.0 - fy)),
            (x0 % self.width, y1 % self.height, (1.0 - fx) * fy),
            (x1 % self.width, y1 % self.height, fx * fy),
        )
        channels = [0.0, 0.0, 0.0, 0.0]
        for x, y, weight in corners:
            color = self.pixel(x, y)
            for index in range(4):
                channels[index] += color[index] * weight
        return tuple(_byte(channel) for channel in channels)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class TerrainCell:
    """Renderer-facing, already-decoded effective LAND cell.

    Heights and optional vertex colours are row-major from south to north,
    matching LAND's 65x65 vertex grid. Texture keys are row-major from south
    to north on the post-transpose 16x16 VTEX grid. Keys remain opaque so a
    caller can preserve plugin-scoped LTEX identity.
    """

    cell_x: int
    cell_y: int
    heights: Sequence[float]
    texture_keys: Sequence[TextureKey | None]
    vertex_colors: Sequence[Rgb] | None = None
    water_height: float | None = None

    def __post_init__(self) -> None:
        if len(self.heights) != LAND_VERTICES_PER_SIDE**2:
            raise ValueError("LAND height grid must contain 65x65 vertices")
        if len(self.texture_keys) != LAND_TEXTURES_PER_SIDE**2:
            raise ValueError("LAND texture grid must contain 16x16 keys")
        if not all(math.isfinite(value) for value in self.heights):
            raise ValueError("LAND heights must be finite")
        object.__setattr__(self, "heights", tuple(float(value) for value in self.heights))
        frozen_texture_keys = tuple(self.texture_keys)
        for key in frozen_texture_keys:
            if key is not None:
                try:
                    hash(key)
                except TypeError as error:
                    raise ValueError("LAND texture keys must be hashable") from error
        object.__setattr__(self, "texture_keys", frozen_texture_keys)
        if self.vertex_colors is not None:
            if len(self.vertex_colors) != LAND_VERTICES_PER_SIDE**2:
                raise ValueError("LAND vertex-colour grid must contain 65x65 colours")
            for color in self.vertex_colors:
                if len(color) != 3:
                    raise ValueError("Vertex colours must be RGB triples")
                for channel in color:
                    _validate_channel(channel)
            object.__setattr__(self, "vertex_colors", tuple(self.vertex_colors))
        if self.water_height is not None and not math.isfinite(self.water_height):
            raise ValueError("Water height must be finite")

    @property
    def grid(self) -> tuple[int, int]:
        return self.cell_x, self.cell_y

    def height_vertex(self, x: int, y: int) -> float:
        if not 0 <= x < LAND_VERTICES_PER_SIDE or not 0 <= y < LAND_VERTICES_PER_SIDE:
            raise IndexError("Height vertex is outside the LAND cell")
        return float(self.heights[y * LAND_VERTICES_PER_SIDE + x])

    def color_vertex(self, x: int, y: int) -> Rgb:
        if self.vertex_colors is None:
            return 255, 255, 255
        if not 0 <= x < LAND_VERTICES_PER_SIDE or not 0 <= y < LAND_VERTICES_PER_SIDE:
            raise IndexError("Colour vertex is outside the LAND cell")
        return self.vertex_colors[y * LAND_VERTICES_PER_SIDE + x]

    def texture_key(self, x: int, y: int) -> TextureKey | None:
        if not 0 <= x < LAND_TEXTURES_PER_SIDE or not 0 <= y < LAND_TEXTURES_PER_SIDE:
            raise IndexError("Texture slot is outside the LAND cell")
        return self.texture_keys[y * LAND_TEXTURES_PER_SIDE + x]


MISSING_TEXTURE = RgbaImage(
    2,
    2,
    bytes(
        (
            255,
            0,
            255,
            255,
            24,
            24,
            24,
            255,
            24,
            24,
            24,
            255,
            255,
            0,
            255,
            255,
        )
    ),
)


@dataclass(frozen=True, slots=True)
class Lighting:
    sun_direction: tuple[float, float, float] = (-0.45, -0.35, 0.82)
    ambient: float = 0.48
    diffuse: float = 0.52
    height_step: float = LAND_VERTEX_SPACING

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in self.sun_direction):
            raise ValueError("Sun direction must be finite")
        if math.isclose(sum(value * value for value in self.sun_direction), 0.0):
            raise ValueError("Sun direction must be non-zero")
        if self.ambient < 0 or self.diffuse < 0:
            raise ValueError("Lighting factors must be non-negative")
        if self.height_step <= 0 or not math.isfinite(self.height_step):
            raise ValueError("Normal sampling step must be finite and positive")

    @property
    def normalized_sun(self) -> tuple[float, float, float]:
        length = math.sqrt(sum(value * value for value in self.sun_direction))
        return tuple(value / length for value in self.sun_direction)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class RenderStyle:
    lighting: Lighting = Lighting()
    water_color: Rgb = (38, 73, 87)
    water_opacity: float = 0.58
    use_vertex_colors: bool = True

    def __post_init__(self) -> None:
        for channel in self.water_color:
            _validate_channel(channel)
        if not 0.0 <= self.water_opacity <= 1.0:
            raise ValueError("Water opacity must be from zero through one")


class TerrainWorld:
    """Global sampler over effective cells and decoded LTEX images."""

    def __init__(
        self,
        cells: Mapping[tuple[int, int], TerrainCell],
        textures: Mapping[TextureKey, RgbaImage],
        *,
        default_texture: RgbaImage = MISSING_TEXTURE,
        default_height: float = -2_048.0,
        default_water_height: float | None = 0.0,
    ) -> None:
        if not math.isfinite(default_height):
            raise ValueError("Default height must be finite")
        if default_water_height is not None and not math.isfinite(default_water_height):
            raise ValueError("Default water height must be finite")
        bad_keys = [key for key, cell in cells.items() if key != cell.grid]
        if bad_keys:
            raise ValueError(f"Cell mapping key does not match cell grid: {bad_keys[0]}")
        self.cells = dict(cells)
        self.textures = dict(textures)
        self.default_texture = default_texture
        self.default_height = default_height
        self.default_water_height = default_water_height

    def cell_at(self, world_x: float, world_y: float) -> TerrainCell | None:
        return self.cells.get(world_to_cell(world_x, world_y))

    def sample_height(self, world_x: float, world_y: float) -> float:
        cell_x, cell_y = world_to_cell(world_x, world_y)
        cell = self.cells.get((cell_x, cell_y))
        if cell is None:
            return self.default_height
        local_x = world_x - cell_x * TES3_CELL_SIZE
        local_y = world_y - cell_y * TES3_CELL_SIZE
        vertex_x = min(max(local_x / LAND_VERTEX_SPACING, 0.0), 64.0)
        vertex_y = min(max(local_y / LAND_VERTEX_SPACING, 0.0), 64.0)
        return _sample_vertex_scalar(cell.height_vertex, vertex_x, vertex_y)

    def sample_vertex_color(self, world_x: float, world_y: float) -> Rgb:
        cell_x, cell_y = world_to_cell(world_x, world_y)
        cell = self.cells.get((cell_x, cell_y))
        if cell is None or cell.vertex_colors is None:
            return 255, 255, 255
        local_x = world_x - cell_x * TES3_CELL_SIZE
        local_y = world_y - cell_y * TES3_CELL_SIZE
        vertex_x = min(max(local_x / LAND_VERTEX_SPACING, 0.0), 64.0)
        vertex_y = min(max(local_y / LAND_VERTEX_SPACING, 0.0), 64.0)
        return _sample_vertex_rgb(cell.color_vertex, vertex_x, vertex_y)

    def texture_key_at_global_slot(self, slot_x: int, slot_y: int) -> TextureKey | None:
        cell_x = slot_x // LAND_TEXTURES_PER_SIDE
        cell_y = slot_y // LAND_TEXTURES_PER_SIDE
        local_x = slot_x - cell_x * LAND_TEXTURES_PER_SIDE
        local_y = slot_y - cell_y * LAND_TEXTURES_PER_SIDE
        cell = self.cells.get((cell_x, cell_y))
        if cell is None:
            return None
        return cell.texture_key(local_x, local_y)

    def texture_weights(self, world_x: float, world_y: float) -> dict[TextureKey | None, float]:
        """Blend the four nearest 512-unit VTEX slot centres across cells."""

        slot_position_x = world_x / LAND_TEXTURE_WORLD_SIZE - 0.5
        slot_position_y = world_y / LAND_TEXTURE_WORLD_SIZE - 0.5
        slot_x0 = math.floor(slot_position_x)
        slot_y0 = math.floor(slot_position_y)
        fraction_x = slot_position_x - slot_x0
        fraction_y = slot_position_y - slot_y0
        slots = (
            (slot_x0, slot_y0, (1.0 - fraction_x) * (1.0 - fraction_y)),
            (slot_x0 + 1, slot_y0, fraction_x * (1.0 - fraction_y)),
            (slot_x0, slot_y0 + 1, (1.0 - fraction_x) * fraction_y),
            (slot_x0 + 1, slot_y0 + 1, fraction_x * fraction_y),
        )
        weights: dict[TextureKey | None, float] = {}
        for slot_x, slot_y, weight in slots:
            if weight <= 0.0:
                continue
            key = self.texture_key_at_global_slot(slot_x, slot_y)
            weights[key] = weights.get(key, 0.0) + weight
        return weights

    def sample_texture(self, world_x: float, world_y: float) -> Rgba:
        # LAND tiles repeat every 512 world units. Raster V is inverted so a
        # decoded image's top row corresponds to the north side of a tile.
        u = (world_x / LAND_TEXTURE_WORLD_SIZE) % 1.0
        v = (-world_y / LAND_TEXTURE_WORLD_SIZE) % 1.0
        channels = [0.0, 0.0, 0.0, 0.0]
        for key, weight in self.texture_weights(world_x, world_y).items():
            texture = self.textures.get(key, self.default_texture)
            color = texture.sample_repeat(u, v)
            alpha = color[3] / 255.0
            for index in range(3):
                channels[index] += color[index] * alpha * weight
            channels[3] += color[3] * weight
        return tuple(_byte(channel) for channel in channels)  # type: ignore[return-value]

    def sample_water_height(self, world_x: float, world_y: float) -> float | None:
        cell = self.cell_at(world_x, world_y)
        if cell is not None and cell.water_height is not None:
            return cell.water_height
        return self.default_water_height

    def surface_normal(
        self, world_x: float, world_y: float, *, step: float = LAND_VERTEX_SPACING
    ) -> tuple[float, float, float]:
        if step <= 0 or not math.isfinite(step):
            raise ValueError("Normal sampling step must be finite and positive")
        dx = (
            self.sample_height(world_x + step, world_y)
            - self.sample_height(world_x - step, world_y)
        ) / (2.0 * step)
        dy = (
            self.sample_height(world_x, world_y + step)
            - self.sample_height(world_x, world_y - step)
        ) / (2.0 * step)
        normal = (-dx, -dy, 1.0)
        length = math.sqrt(sum(value * value for value in normal))
        return tuple(value / length for value in normal)  # type: ignore[return-value]


def shade_point(
    world: TerrainWorld,
    world_x: float,
    world_y: float,
    style: RenderStyle = RenderStyle(),
) -> Rgba:
    color = world.sample_texture(world_x, world_y)
    normal = world.surface_normal(
        world_x, world_y, step=style.lighting.height_step
    )
    sun = style.lighting.normalized_sun
    lambert = max(0.0, sum(normal[index] * sun[index] for index in range(3)))
    light = style.lighting.ambient + style.lighting.diffuse * lambert
    vertex_color = (
        world.sample_vertex_color(world_x, world_y)
        if style.use_vertex_colors
        else (255, 255, 255)
    )
    shaded = [
        _byte(color[index] * (vertex_color[index] / 255.0) * light)
        for index in range(3)
    ]

    height = world.sample_height(world_x, world_y)
    water_height = world.sample_water_height(world_x, world_y)
    if water_height is not None and height < water_height:
        # Slightly increase opacity with depth while keeping the style's value
        # as the deterministic lower bound.
        depth_factor = min(1.0, (water_height - height) / 512.0)
        opacity = style.water_opacity + (1.0 - style.water_opacity) * depth_factor * 0.35
        shaded = [
            _byte(shaded[index] * (1.0 - opacity) + style.water_color[index] * opacity)
            for index in range(3)
        ]
    return shaded[0], shaded[1], shaded[2], color[3]


def render_grid(
    world: TerrainWorld,
    grid: RasterGrid,
    *,
    style: RenderStyle = RenderStyle(),
) -> RgbaImage:
    """Render pixel centres of an arbitrary georeferenced TES3 raster grid."""

    pixels = bytearray(grid.width * grid.height * 4)
    offset = 0
    for row in range(grid.height):
        world_y = grid.extent.max_y - (row + 0.5) * grid.units_per_pixel_y
        for column in range(grid.width):
            world_x = grid.extent.min_x + (column + 0.5) * grid.units_per_pixel_x
            pixels[offset : offset + 4] = bytes(shade_point(world, world_x, world_y, style))
            offset += 4
    return RgbaImage(grid.width, grid.height, bytes(pixels))


def render_cell(
    world: TerrainWorld,
    cell_x: int,
    cell_y: int,
    *,
    style: RenderStyle = RenderStyle(),
    gutter_pixels: int = 0,
    crop_gutter: bool = True,
) -> RgbaImage:
    """Render a cell at the canonical 512 px/16 units-per-pixel scale.

    A positive gutter samples the global neighbouring-cell surface before an
    optional exact 512x512 centre crop, avoiding edge-clamp seams.
    """

    grid = cell_raster_grid(cell_x, cell_y, gutter_pixels=gutter_pixels)
    rendered = render_grid(world, grid, style=style)
    if gutter_pixels and crop_gutter:
        return rendered.crop(
            gutter_pixels,
            gutter_pixels,
            grid.width - 2 * gutter_pixels,
            grid.height - 2 * gutter_pixels,
        )
    return rendered


def decode_texture(
    payload: bytes,
    suffix: str,
    *,
    resize: int | None = None,
    executable: str = "magick",
) -> RgbaImage:
    """Decode BSA/loose texture bytes to canonical RGBA via ImageMagick."""

    if not payload:
        raise ValueError("Texture payload is empty")
    normalized_suffix = suffix.lower().lstrip(".")
    if not normalized_suffix.isalnum():
        raise ValueError("Texture suffix must be alphanumeric")
    command = [
        executable,
        f"{normalized_suffix}:-",
        "-alpha",
        "on",
        "-colorspace",
        "sRGB",
    ]
    if resize is not None:
        if resize <= 0:
            raise ValueError("Resize dimension must be positive")
        command.extend(("-filter", "Lanczos", "-resize", f"{resize}x{resize}!"))
    command.extend(("-depth", "8", "rgba:-"))
    completed = _run_encoder(command, payload)
    dimensions = _identify_rgba_dimensions(
        payload,
        normalized_suffix,
        resize=resize,
        executable=executable,
    )
    expected = dimensions[0] * dimensions[1] * 4
    if len(completed.stdout) != expected:
        raise RuntimeError(
            f"ImageMagick returned {len(completed.stdout)} RGBA bytes, expected {expected}"
        )
    return RgbaImage(dimensions[0], dimensions[1], completed.stdout)


def encode_webp(
    image: RgbaImage,
    *,
    executable: str = "magick",
    lossless: bool = True,
    quality: int = 92,
    method: int = 6,
) -> bytes:
    """Encode metadata-free WebP bytes with fully pinned encoder options."""

    if not 0 <= quality <= 100:
        raise ValueError("WebP quality must be from zero through 100")
    if not 0 <= method <= 6:
        raise ValueError("WebP method must be from zero through 6")
    command = [
        executable,
        "-size",
        f"{image.width}x{image.height}",
        "-depth",
        "8",
        "rgba:-",
        "-alpha",
        "on",
        "-colorspace",
        "sRGB",
        "-strip",
        "-define",
        "webp:exact=true",
        "-define",
        f"webp:method={method}",
        "-define",
        f"webp:lossless={'true' if lossless else 'false'}",
        "-quality",
        str(quality),
        "webp:-",
    ]
    completed = _run_encoder(command, image.pixels)
    encoded = completed.stdout
    if len(encoded) < 12 or encoded[:4] != b"RIFF" or encoded[8:12] != b"WEBP":
        raise RuntimeError("ImageMagick did not return a WebP payload")
    return encoded


@dataclass(frozen=True, slots=True)
class WebpWriteResult:
    path: Path
    byte_length: int
    sha256: str


def write_webp(
    image: RgbaImage,
    output_path: Path,
    *,
    executable: str = "magick",
    lossless: bool = True,
    quality: int = 92,
    method: int = 6,
) -> WebpWriteResult:
    """Atomically write a deterministic WebP and return its audit metadata."""

    encoded = encode_webp(
        image,
        executable=executable,
        lossless=lossless,
        quality=quality,
        method=method,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
            temporary_path = Path(stream.name)
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return WebpWriteResult(
        output_path,
        len(encoded),
        hashlib.sha256(encoded).hexdigest(),
    )


def image_sha256(image: RgbaImage) -> str:
    header = f"RGBA:{image.width}x{image.height}\0".encode("ascii")
    return hashlib.sha256(header + image.pixels).hexdigest()


def _sample_vertex_scalar(getter: Callable[[int, int], float], x: float, y: float) -> float:
    x0 = min(math.floor(x), 63)
    y0 = min(math.floor(y), 63)
    x1 = x0 + 1
    y1 = y0 + 1
    fx = x - x0
    fy = y - y0
    get = getter  # keep the hot loop's calls compact
    south = get(x0, y0) * (1.0 - fx) + get(x1, y0) * fx
    north = get(x0, y1) * (1.0 - fx) + get(x1, y1) * fx
    return float(south * (1.0 - fy) + north * fy)


def _sample_vertex_rgb(getter: Callable[[int, int], Rgb], x: float, y: float) -> Rgb:
    x0 = min(math.floor(x), 63)
    y0 = min(math.floor(y), 63)
    x1 = x0 + 1
    y1 = y0 + 1
    fx = x - x0
    fy = y - y0
    colors = (
        (getter(x0, y0), (1.0 - fx) * (1.0 - fy)),
        (getter(x1, y0), fx * (1.0 - fy)),
        (getter(x0, y1), (1.0 - fx) * fy),
        (getter(x1, y1), fx * fy),
    )
    return tuple(
        _byte(sum(color[channel] * weight for color, weight in colors))
        for channel in range(3)
    )  # type: ignore[return-value]


def _byte(value: float) -> int:
    return min(255, max(0, int(value + 0.5)))


def _run_encoder(command: list[str], payload: bytes) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            env={**os.environ, "SOURCE_DATE_EPOCH": "0"},
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"ImageMagick executable not found: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ImageMagick failed: {detail or error.returncode}") from error


def _identify_rgba_dimensions(
    payload: bytes,
    suffix: str,
    *,
    resize: int | None,
    executable: str,
) -> tuple[int, int]:
    if resize is not None:
        return resize, resize
    completed = _run_encoder(
        [executable, f"{suffix}:-", "-format", "%w %h", "info:"], payload
    )
    try:
        width_text, height_text = completed.stdout.decode("ascii").split()
        width, height = int(width_text), int(height_text)
    except (UnicodeDecodeError, ValueError) as error:
        raise RuntimeError("ImageMagick returned invalid texture dimensions") from error
    if width <= 0 or height <= 0:
        raise RuntimeError("ImageMagick returned invalid texture dimensions")
    return width, height
