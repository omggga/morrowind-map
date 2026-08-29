import type { TileCoverage, TilePyramid } from '@morrowind-map/contracts';
import { describe, expect, it } from 'vitest';
import {
  SparseTileCoverageIndex,
  createSparseTileUrlFunction,
  createTes3Resolutions,
  createTes3TileGrid,
} from './sparseTiles';

const HASH = '0'.repeat(64);

function poisonSongPyramid(
  urlTemplate = '/tiles/{z}/{x}/{y}.webp',
): TilePyramid {
  return {
    id: 'poison-song-26.08.basemap',
    regionIds: ['vvardenfell', 'solstheim', 'tr-mainland'],
    kind: 'xyz-pyramid',
    urlTemplate,
    mediaType: 'image/webp',
    tileSize: 512,
    extent: [-229_376, -475_136, 409_600, 278_528],
    origin: [-229_376, 278_528],
    resolutions: [2_048, 1_024, 512, 256, 128, 64, 32, 16],
    minZoom: 0,
    maxZoom: 7,
    sparse: true,
    coverage: {
      url: '/tile-coverage.json',
      mediaType: 'application/json',
      sha256: HASH,
      bytes: 1,
    },
    qualityReport: {
      url: '/basemap-audit.json',
      mediaType: 'application/json',
      sha256: HASH,
      bytes: 1,
    },
    derivation: {
      kind: 'cross-shard-seam-stabilization',
      version: 'test-v1',
      sourceInventorySha256: HASH,
      implementationSha256: HASH,
      receipt: {
        url: '/seam-stabilization.json',
        mediaType: 'application/json',
        sha256: HASH,
        bytes: 1,
      },
    },
    integrity: {
      tileCount: 1,
      totalBytes: 1,
      inventorySha256: HASH,
      inventoryFileSha256: HASH,
      provenanceFingerprint: HASH,
      planFingerprint: HASH,
      profileFingerprint: HASH,
      rendererFingerprint: HASH,
      productionSourceFingerprint: HASH,
      assetTreeFingerprint: HASH,
      inputFingerprint: HASH,
    },
  };
}

function poisonSongCoverage(): TileCoverage {
  return {
    schemaVersion: 1,
    datasetId: 'poison-song-26.08',
    snapshotId: 'test-snapshot',
    tilePyramidId: 'poison-song-26.08.basemap',
    encoding: 'x-y-ranges-v1',
    tileCount: 8,
    levels: [
      {
        z: 7,
        columns: [
          { x: 0, yRanges: [[10, 15]] },
          { x: 1, yRanges: [[6, 6], [8, 8]] },
        ],
      },
    ],
  };
}

describe('TES3 sparse tiles', () => {
  it('uses the direct top-left XYZ orientation for the production z7 grid', () => {
    const grid = createTes3TileGrid(poisonSongPyramid());

    expect(grid.getMinZoom()).toBe(0);
    expect(grid.getMaxZoom()).toBe(7);
    expect(grid.getOrigin(7)).toEqual([-229_376, 278_528]);
    expect(grid.getResolution(7)).toBe(16);
    expect(grid.getTileCoordExtent([7, 0, 10])).toEqual([
      -229_376,
      188_416,
      -221_184,
      196_608,
    ]);
  });

  it('normalizes resolutions to absolute OpenLayers zoom indices when minZoom is non-zero', () => {
    const pyramid = {
      ...poisonSongPyramid(),
      resolutions: [1024, 512],
      minZoom: 1,
      maxZoom: 2,
    } satisfies TilePyramid;
    const resolutions = createTes3Resolutions(pyramid);
    const grid = createTes3TileGrid(pyramid);

    expect(resolutions).toEqual([2048, 1024, 512]);
    expect(grid.getMinZoom()).toBe(1);
    expect(grid.getMaxZoom()).toBe(2);
    expect(grid.getResolution(1)).toBe(1024);
    expect(grid.getResolution(2)).toBe(512);
  });

  it('indexes covered ranges and rejects holes or invalid coordinates', () => {
    const index = new SparseTileCoverageIndex(poisonSongCoverage());

    expect(index.has([7, 0, 10])).toBe(true);
    expect(index.has([7, 0, 15])).toBe(true);
    expect(index.has([7, 0, 9])).toBe(false);
    expect(index.has([7, 1, 7])).toBe(false);
    expect(index.has([-1, 0, 10])).toBe(false);
    expect(index.has([8, 0, 10])).toBe(false);
    expect(index.has([7, -1, 10])).toBe(false);
    expect(index.has([7, 0, -1])).toBe(false);
    expect(index.has([7, 0, 10.5])).toBe(false);
  });

  it('returns an exact URL for covered tiles and no URL for sparse holes', () => {
    const urlForTile = createSparseTileUrlFunction(
      poisonSongPyramid(),
      poisonSongCoverage(),
    );

    expect(urlForTile([7, 0, 10], 1, null!)).toBe('/tiles/7/0/10.webp');
    expect(urlForTile([7, 0, 9], 1, null!)).toBeUndefined();
    expect(urlForTile([8, 0, 10], 1, null!)).toBeUndefined();
  });

  it('substitutes every occurrence of each XYZ placeholder', () => {
    const urlForTile = createSparseTileUrlFunction(
      poisonSongPyramid('/{z}/{x}/{y}/{z}-{x}-{y}.webp'),
      poisonSongCoverage(),
    );

    expect(urlForTile([7, 0, 10], 1, null!)).toBe('/7/0/10/7-0-10.webp');
  });
});
