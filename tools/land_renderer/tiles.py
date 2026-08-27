from __future__ import annotations

import math
from dataclasses import dataclass


TES3_CELL_SIZE = 8_192.0
LAND_QUADS_PER_CELL = 64
LAND_VERTICES_PER_SIDE = LAND_QUADS_PER_CELL + 1
LAND_VERTEX_SPACING = TES3_CELL_SIZE / LAND_QUADS_PER_CELL
LAND_TEXTURES_PER_SIDE = 16
LAND_TEXTURE_WORLD_SIZE = TES3_CELL_SIZE / LAND_TEXTURES_PER_SIDE

CELL_TILE_PIXELS = 512
CELL_PIXEL_SIZE = TES3_CELL_SIZE / CELL_TILE_PIXELS
CELL_REFERENCE_ZOOM = 7


@dataclass(frozen=True, slots=True)
class WorldExtent:
    """A half-open TES3 world extent: [min_x, max_x) x [min_y, max_y)."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self) -> None:
        values = (self.min_x, self.min_y, self.max_x, self.max_y)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("World extent values must be finite")
        if self.max_x <= self.min_x or self.max_y <= self.min_y:
            raise ValueError("World extent must have positive width and height")

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    def expanded(self, amount: float) -> WorldExtent:
        if amount < 0 or not math.isfinite(amount):
            raise ValueError("Expansion amount must be finite and non-negative")
        return WorldExtent(
            self.min_x - amount,
            self.min_y - amount,
            self.max_x + amount,
            self.max_y + amount,
        )


def world_to_cell(world_x: float, world_y: float) -> tuple[int, int]:
    """Return the exterior cell containing a TES3 point.

    Cell extents are half-open on their north/east edges, matching integer floor
    division for both positive and negative coordinates.
    """

    if not math.isfinite(world_x) or not math.isfinite(world_y):
        raise ValueError("World coordinates must be finite")
    return math.floor(world_x / TES3_CELL_SIZE), math.floor(world_y / TES3_CELL_SIZE)


def cell_extent(cell_x: int, cell_y: int) -> WorldExtent:
    min_x = cell_x * TES3_CELL_SIZE
    min_y = cell_y * TES3_CELL_SIZE
    return WorldExtent(min_x, min_y, min_x + TES3_CELL_SIZE, min_y + TES3_CELL_SIZE)


@dataclass(frozen=True, slots=True)
class RasterGrid:
    """Top-left-origin raster georeferenced to a TES3 world extent."""

    extent: WorldExtent
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Raster dimensions must be positive")

    @property
    def units_per_pixel_x(self) -> float:
        return self.extent.width / self.width

    @property
    def units_per_pixel_y(self) -> float:
        return self.extent.height / self.height

    def world_to_pixel(self, world_x: float, world_y: float) -> tuple[float, float]:
        """Map a world position to a pixel-boundary position.

        The north-west extent corner maps to (0, 0), so the TES3 Y axis is
        inverted exactly once. The south-east corner maps to (width, height).
        """

        if not math.isfinite(world_x) or not math.isfinite(world_y):
            raise ValueError("World coordinates must be finite")
        column = (world_x - self.extent.min_x) / self.units_per_pixel_x
        row = (self.extent.max_y - world_y) / self.units_per_pixel_y
        return column, row

    def pixel_to_world(self, column: float, row: float) -> tuple[float, float]:
        """Map a pixel-boundary position to TES3 world coordinates."""

        if not math.isfinite(column) or not math.isfinite(row):
            raise ValueError("Pixel coordinates must be finite")
        world_x = self.extent.min_x + column * self.units_per_pixel_x
        world_y = self.extent.max_y - row * self.units_per_pixel_y
        return world_x, world_y

    def pixel_center_to_world(self, column: int, row: int) -> tuple[float, float]:
        if not 0 <= column < self.width or not 0 <= row < self.height:
            raise IndexError("Pixel is outside the raster")
        return self.pixel_to_world(column + 0.5, row + 0.5)

    def contains_world(self, world_x: float, world_y: float) -> bool:
        return (
            self.extent.min_x <= world_x < self.extent.max_x
            and self.extent.min_y <= world_y < self.extent.max_y
        )


def cell_raster_grid(cell_x: int, cell_y: int, *, gutter_pixels: int = 0) -> RasterGrid:
    """Build the canonical 512 px/cell grid, optionally with a world gutter."""

    if gutter_pixels < 0:
        raise ValueError("Gutter must be non-negative")
    gutter_world = gutter_pixels * CELL_PIXEL_SIZE
    return RasterGrid(
        cell_extent(cell_x, cell_y).expanded(gutter_world),
        CELL_TILE_PIXELS + 2 * gutter_pixels,
        CELL_TILE_PIXELS + 2 * gutter_pixels,
    )


def cell_pixel_to_world(
    cell_x: int,
    cell_y: int,
    column: float,
    row: float,
    *,
    center: bool = False,
) -> tuple[float, float]:
    """Convert canonical cell pixels to world coordinates.

    Fractional/boundary pixel coordinates are accepted. ``center=True`` adds
    half a native pixel and is intended for integer raster indices.
    """

    offset = 0.5 if center else 0.0
    return RasterGrid(cell_extent(cell_x, cell_y), CELL_TILE_PIXELS, CELL_TILE_PIXELS).pixel_to_world(
        column + offset,
        row + offset,
    )


def world_to_cell_pixel(world_x: float, world_y: float) -> tuple[int, int, float, float]:
    """Return containing cell and its top-left-origin pixel-boundary position."""

    cell_x, cell_y = world_to_cell(world_x, world_y)
    column, row = RasterGrid(
        cell_extent(cell_x, cell_y), CELL_TILE_PIXELS, CELL_TILE_PIXELS
    ).world_to_pixel(world_x, world_y)
    return cell_x, cell_y, column, row


@dataclass(frozen=True, slots=True)
class TileGrid:
    """XYZ-like top-left tile grid anchored in TES3 world coordinates.

    At ``reference_zoom`` one 512 px tile covers exactly one 8192-unit TES3
    exterior cell. Lower zooms double the world span per tile.
    """

    origin_x: float
    origin_y: float
    reference_zoom: int = CELL_REFERENCE_ZOOM
    tile_pixels: int = CELL_TILE_PIXELS
    reference_units_per_pixel: float = CELL_PIXEL_SIZE

    def __post_init__(self) -> None:
        if not math.isfinite(self.origin_x) or not math.isfinite(self.origin_y):
            raise ValueError("Tile origin must be finite")
        if self.reference_zoom < 0:
            raise ValueError("Reference zoom must be non-negative")
        if self.tile_pixels <= 0:
            raise ValueError("Tile dimensions must be positive")
        if self.reference_units_per_pixel <= 0 or not math.isfinite(
            self.reference_units_per_pixel
        ):
            raise ValueError("Reference resolution must be finite and positive")

    def units_per_pixel(self, zoom: int) -> float:
        if zoom < 0:
            raise ValueError("Zoom must be non-negative")
        return self.reference_units_per_pixel * 2.0 ** (self.reference_zoom - zoom)

    def tile_world_size(self, zoom: int) -> float:
        return self.tile_pixels * self.units_per_pixel(zoom)

    def world_to_tile(self, world_x: float, world_y: float, zoom: int) -> tuple[int, int]:
        if not math.isfinite(world_x) or not math.isfinite(world_y):
            raise ValueError("World coordinates must be finite")
        span = self.tile_world_size(zoom)
        tile_x = math.floor((world_x - self.origin_x) / span)
        tile_y = math.floor((self.origin_y - world_y) / span)
        return tile_x, tile_y

    def tile_extent(self, tile_x: int, tile_y: int, zoom: int) -> WorldExtent:
        span = self.tile_world_size(zoom)
        min_x = self.origin_x + tile_x * span
        max_y = self.origin_y - tile_y * span
        return WorldExtent(min_x, max_y - span, min_x + span, max_y)

    def tile_raster_grid(self, tile_x: int, tile_y: int, zoom: int) -> RasterGrid:
        return RasterGrid(self.tile_extent(tile_x, tile_y, zoom), self.tile_pixels, self.tile_pixels)

    def world_to_tile_pixel(
        self, world_x: float, world_y: float, zoom: int
    ) -> tuple[int, int, float, float]:
        tile_x, tile_y = self.world_to_tile(world_x, world_y, zoom)
        column, row = self.tile_raster_grid(tile_x, tile_y, zoom).world_to_pixel(
            world_x, world_y
        )
        return tile_x, tile_y, column, row

    def cell_to_tile(self, cell_x: int, cell_y: int) -> tuple[int, int]:
        """Return the reference-zoom tile aligned with an exterior cell.

        Raises if this grid's origin/resolution does not align cell boundaries
        to integer reference tiles.
        """

        extent = cell_extent(cell_x, cell_y)
        span = self.tile_world_size(self.reference_zoom)
        raw_x = (extent.min_x - self.origin_x) / span
        raw_y = (self.origin_y - extent.max_y) / span
        tile_x = round(raw_x)
        tile_y = round(raw_y)
        if not math.isclose(raw_x, tile_x, abs_tol=1e-9) or not math.isclose(
            raw_y, tile_y, abs_tol=1e-9
        ):
            raise ValueError("Tile grid is not aligned to TES3 cell boundaries")
        return tile_x, tile_y


POISON_SONG_TILE_GRID = TileGrid(origin_x=-229_376.0, origin_y=278_528.0)
