import { useEffect, useState, type CSSProperties } from 'react';
import {
  parseMapAssetsManifest,
  parseTileCoverage,
  type DatasetManifest,
  type MapAssetsManifest,
  type TileCoverage,
  type TileCoverageLevel,
  type TilePyramid,
} from '@morrowind-map/contracts';

const MAX_PREVIEW_ZOOM = 5;
const PREVIEW_TILE_RADIUS = 1;
const ORIGINAL_PREVIEW_FOCUS = [-21_879.766, -14_022.853] as const;

interface PreviewTile {
  readonly key: string;
  readonly url: string;
  readonly column: number;
  readonly row: number;
}

interface PreviewMosaic {
  readonly key: string;
  readonly columns: number;
  readonly rows: number;
  readonly tiles: readonly PreviewTile[];
}

type BackdropState =
  | {
      readonly phase: 'loading';
      readonly mosaic: PreviewMosaic | null;
      readonly loadedTiles: ReadonlySet<string>;
    }
  | { readonly phase: 'ready'; readonly mosaic: PreviewMosaic }
  | { readonly phase: 'fallback'; readonly mosaic: null };

interface LandingMapBackdropProps {
  readonly dataset: DatasetManifest | null;
}

async function fetchJson(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal,
  });
  if (!response.ok) {
    throw new Error(`Could not load ${url} (HTTP ${response.status})`);
  }
  return response.json() as Promise<unknown>;
}

function assertMapAssetsIdentity(
  dataset: DatasetManifest,
  mapAssets: MapAssetsManifest,
): void {
  if (
    mapAssets.datasetId !== dataset.datasetId ||
    mapAssets.snapshotId !== dataset.snapshotId ||
    mapAssets.projection !== dataset.map.projection.code
  ) {
    throw new Error('Landing map assets belong to a different dataset snapshot');
  }
}

function arraysEqual<T>(left: readonly T[], right: readonly T[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function assertPyramidMatchesManifest(
  dataset: DatasetManifest,
  pyramid: TilePyramid,
): void {
  const grid = dataset.map.tileGrid;
  const [worldMinX, worldMinY, worldMaxX, worldMaxY] = dataset.map.projection.extent;
  const [minX, minY, maxX, maxY] = pyramid.extent;
  if (
    minX < worldMinX ||
    minY < worldMinY ||
    maxX > worldMaxX ||
    maxY > worldMaxY ||
    !arraysEqual(pyramid.origin, grid.origin) ||
    !arraysEqual(pyramid.resolutions, grid.resolutions) ||
    pyramid.tileSize !== grid.tileSize
  ) {
    throw new Error('Landing tile pyramid does not match the dataset manifest');
  }
}

function highestPreviewLevel(coverage: TileCoverage): TileCoverageLevel {
  const level = coverage.levels.reduce<TileCoverageLevel | null>(
    (highest, candidate) =>
      candidate.z <= MAX_PREVIEW_ZOOM && (highest === null || candidate.z > highest.z)
        ? candidate
        : highest,
    null,
  );
  if (level === null) {
    throw new Error(`Landing map has no tile coverage at z${MAX_PREVIEW_ZOOM} or below`);
  }
  return level;
}

function tileUrl(template: string, z: number, x: number, y: number): string {
  const resolved = template
    .replaceAll('{z}', String(z))
    .replaceAll('{x}', String(x))
    .replaceAll('{y}', String(y));
  if (resolved.includes('{z}') || resolved.includes('{x}') || resolved.includes('{y}')) {
    throw new Error('Landing map tile URL template could not be resolved');
  }
  return resolved;
}

function buildMosaic(
  dataset: DatasetManifest,
  pyramid: TilePyramid,
  coverage: TileCoverage,
): PreviewMosaic {
  if (coverage.tilePyramidId !== pyramid.id) {
    throw new Error('Landing tile coverage references a different pyramid');
  }
  const level = highestPreviewLevel(coverage);
  const resolution = pyramid.resolutions[level.z - pyramid.minZoom];
  if (resolution === undefined) {
    throw new Error(`Landing map pyramid does not define z${level.z}`);
  }
  const [minX, minY, maxX, maxY] = pyramid.extent;
  const tileWorldSize = pyramid.tileSize * resolution;
  const pyramidColumns = Math.ceil((maxX - minX) / tileWorldSize);
  const pyramidRows = Math.ceil((maxY - minY) / tileWorldSize);
  const coveredTiles = level.columns.flatMap(({ x, yRanges }) =>
    yRanges.flatMap(([startY, endY]) =>
      Array.from({ length: endY - startY + 1 }, (_, offset) => {
        const y = startY + offset;
        return { x, y };
      }),
    ),
  );
  if (pyramidColumns < 1 || pyramidRows < 1 || coveredTiles.length === 0) {
    throw new Error('Landing map preview does not contain renderable tiles');
  }

  const [focusX, focusY] = dataset.mapKey === 'original'
    ? ORIGINAL_PREVIEW_FOCUS
    : dataset.map.projection.center;
  const requestedColumn = Math.floor((focusX - pyramid.origin[0]) / tileWorldSize);
  const requestedRow = Math.floor((pyramid.origin[1] - focusY) / tileWorldSize);
  const focusTile = coveredTiles.reduce((nearest, tile) => {
    const distance = Math.hypot(tile.x - requestedColumn, tile.y - requestedRow);
    const nearestDistance = Math.hypot(
      nearest.x - requestedColumn,
      nearest.y - requestedRow,
    );
    return distance < nearestDistance ? tile : nearest;
  });
  const windowSize = PREVIEW_TILE_RADIUS * 2 + 1;
  const columns = Math.min(windowSize, pyramidColumns);
  const rows = Math.min(windowSize, pyramidRows);
  const startColumn = Math.min(
    Math.max(focusTile.x - PREVIEW_TILE_RADIUS, 0),
    pyramidColumns - columns,
  );
  const startRow = Math.min(
    Math.max(focusTile.y - PREVIEW_TILE_RADIUS, 0),
    pyramidRows - rows,
  );
  const tiles = coveredTiles
    .filter(({ x, y }) =>
      x >= startColumn &&
      x < startColumn + columns &&
      y >= startRow &&
      y < startRow + rows
    )
    .map(({ x, y }) => ({
      key: `${level.z}/${x}/${y}`,
      url: tileUrl(pyramid.urlTemplate, level.z, x, y),
      column: x - startColumn + 1,
      row: y - startRow + 1,
    } satisfies PreviewTile));
  if (tiles.length === 0) {
    throw new Error('Landing map preview focus does not contain renderable tiles');
  }
  return {
    key: `${dataset.datasetId}\0${dataset.snapshotId}\0${pyramid.id}\0${level.z}\0${startColumn}\0${startRow}`,
    columns,
    rows,
    tiles,
  };
}

async function loadMosaic(
  dataset: DatasetManifest,
  signal: AbortSignal,
): Promise<PreviewMosaic> {
  const mapAssetsUrl = dataset.artifacts.tiles?.manifestUrl;
  if (!mapAssetsUrl) {
    throw new Error('Landing dataset does not publish map assets');
  }
  const mapAssets = parseMapAssetsManifest(await fetchJson(mapAssetsUrl, signal));
  assertMapAssetsIdentity(dataset, mapAssets);
  const pyramid = mapAssets.tilePyramids?.[0];
  if (pyramid === undefined) {
    throw new Error('Landing dataset does not publish a tile pyramid');
  }
  assertPyramidMatchesManifest(dataset, pyramid);
  const coverage = parseTileCoverage(
    await fetchJson(pyramid.coverage.url, signal),
    mapAssets,
  );
  return buildMosaic(dataset, pyramid, coverage);
}

function LandingMapBackdropInstance({ dataset }: LandingMapBackdropProps) {
  const [state, setState] = useState<BackdropState>(() =>
    dataset === null
      ? { phase: 'fallback', mosaic: null }
      : { phase: 'loading', mosaic: null, loadedTiles: new Set<string>() },
  );

  useEffect(() => {
    if (dataset === null) {
      return undefined;
    }
    const controller = new AbortController();
    let active = true;
    void loadMosaic(dataset, controller.signal)
      .then((mosaic) => {
        if (active) {
          setState({ phase: 'loading', mosaic, loadedTiles: new Set<string>() });
        }
      })
      .catch(() => {
        if (active) {
          setState({ phase: 'fallback', mosaic: null });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [dataset]);

  const mosaic = state.mosaic;
  const gridStyle = mosaic === null
    ? undefined
    : {
        '--preview-columns': String(mosaic.columns),
        '--preview-rows': String(mosaic.rows),
        aspectRatio: `${mosaic.columns} / ${mosaic.rows}`,
      } as CSSProperties;

  const markTileLoaded = (mosaicKey: string, tileKey: string) => {
    setState((current) => {
      if (
        current.phase !== 'loading' ||
        current.mosaic === null ||
        current.mosaic.key !== mosaicKey ||
        current.loadedTiles.has(tileKey)
      ) {
        return current;
      }
      const loadedTiles = new Set(current.loadedTiles);
      loadedTiles.add(tileKey);
      return loadedTiles.size === current.mosaic.tiles.length
        ? { phase: 'ready', mosaic: current.mosaic }
        : { ...current, loadedTiles };
    });
  };

  const markTileFailed = (mosaicKey: string) => {
    setState((current) =>
      current.mosaic?.key === mosaicKey
        ? { phase: 'fallback', mosaic: null }
        : current,
    );
  };

  return (
    <div
      className="landing-map-backdrop"
      aria-hidden="true"
      data-ready={state.phase === 'loading' ? 'false' : 'true'}
      data-state={state.phase}
      style={{ pointerEvents: 'none' }}
    >
      {mosaic === null ? null : (
        <div className="landing-map-backdrop__grid" style={gridStyle}>
          {mosaic.tiles.map((tile) => (
            <img
              key={tile.key}
              className="landing-map-backdrop__tile"
              src={tile.url}
              alt=""
              decoding="async"
              draggable={false}
              style={{ gridColumn: tile.column, gridRow: tile.row }}
              onLoad={() => markTileLoaded(mosaic.key, tile.key)}
              onError={() => markTileFailed(mosaic.key)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function LandingMapBackdrop({ dataset }: LandingMapBackdropProps) {
  const backdropKey = dataset === null
    ? 'fallback'
    : `${dataset.datasetId}:${dataset.snapshotId}`;
  return <LandingMapBackdropInstance key={backdropKey} dataset={dataset} />;
}
