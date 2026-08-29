import type {
  TileCoverage,
  TilePyramid,
  TileYRange,
} from '@morrowind-map/contracts';
import type { UrlFunction } from 'ol/Tile.js';
import type { TileCoord } from 'ol/tilecoord.js';
import TileGrid from 'ol/tilegrid/TileGrid.js';

type CoverageColumns = Map<number, readonly TileYRange[]>;

export class SparseTileCoverageIndex {
  private readonly levels = new Map<number, CoverageColumns>();

  constructor(coverage: TileCoverage) {
    for (const level of coverage.levels) {
      const columns: CoverageColumns = new Map();

      for (const column of level.columns) {
        columns.set(column.x, column.yRanges);
      }

      this.levels.set(level.z, columns);
    }
  }

  has(tileCoord: TileCoord): boolean {
    const z = tileCoord[0];
    const x = tileCoord[1];
    const y = tileCoord[2];

    if (
      z === undefined ||
      x === undefined ||
      y === undefined ||
      !Number.isSafeInteger(z) ||
      !Number.isSafeInteger(x) ||
      !Number.isSafeInteger(y) ||
      z < 0 ||
      x < 0 ||
      y < 0
    ) {
      return false;
    }

    const ranges = this.levels.get(z)?.get(x);
    if (ranges === undefined) {
      return false;
    }

    let lower = 0;
    let upper = ranges.length - 1;

    while (lower <= upper) {
      const middle = Math.floor((lower + upper) / 2);
      const range = ranges[middle];

      if (range === undefined) {
        return false;
      }

      if (y < range[0]) {
        upper = middle - 1;
      } else if (y > range[1]) {
        lower = middle + 1;
      } else {
        return true;
      }
    }

    return false;
  }
}

export function createTes3Resolutions(pyramid: TilePyramid): number[] {
  const firstResolution = pyramid.resolutions[0];

  if (pyramid.minZoom === 0 || firstResolution === undefined) {
    return [...pyramid.resolutions];
  }

  const prefix = Array.from(
    { length: pyramid.minZoom },
    (_, zoom) => firstResolution * 2 ** (pyramid.minZoom - zoom),
  );

  return [...prefix, ...pyramid.resolutions];
}

export function createTes3TileGrid(pyramid: TilePyramid): TileGrid {
  return new TileGrid({
    extent: [...pyramid.extent],
    minZoom: pyramid.minZoom,
    origin: [...pyramid.origin],
    resolutions: createTes3Resolutions(pyramid),
    tileSize: pyramid.tileSize,
  });
}

export function createSparseTileUrlFunction(
  pyramid: TilePyramid,
  coverage: TileCoverage,
): UrlFunction {
  const coverageIndex = new SparseTileCoverageIndex(coverage);

  return (tileCoord) => {
    if (!coverageIndex.has(tileCoord)) {
      return undefined;
    }

    const z = tileCoord[0];
    const x = tileCoord[1];
    const y = tileCoord[2];

    if (z === undefined || x === undefined || y === undefined) {
      return undefined;
    }

    return pyramid.urlTemplate
      .replaceAll('{z}', String(z))
      .replaceAll('{x}', String(x))
      .replaceAll('{y}', String(y));
  };
}
