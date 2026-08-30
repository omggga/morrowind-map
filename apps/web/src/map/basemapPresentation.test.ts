import type { TilePyramid } from '@morrowind-map/contracts';
import { describe, expect, it } from 'vitest';
import {
  BASEMAP_BRIGHTNESS_FACTOR,
  BASEMAP_CONTRAST_FACTOR,
  BASEMAP_MAX_OVERSCALE,
  createOverscaledViewResolutions,
  makeRenderedPixelsOpaque,
} from './basemapPresentation';
import { createTes3TileGrid } from './sparseTiles';

const HASH = '0'.repeat(64);

function pyramid(): TilePyramid {
  return {
    id: 'poison-song-26.08.basemap',
    regionIds: ['vvardenfell'],
    kind: 'xyz-pyramid',
    urlTemplate: '/tiles/{z}/{x}/{y}.webp',
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

describe('basemap presentation preview', () => {
  it('adds one 10% view-only overscale without extending the source tile grid', () => {
    const sourcePyramid = pyramid();
    const viewResolutions = createOverscaledViewResolutions(sourcePyramid);
    const sourceGrid = createTes3TileGrid(sourcePyramid);

    expect(BASEMAP_MAX_OVERSCALE).toBe(1.1);
    expect(viewResolutions).toHaveLength(9);
    expect(viewResolutions.at(-1)).toBeCloseTo(16 / 1.1);
    expect(sourceGrid.getMaxZoom()).toBe(7);
    expect(sourceGrid.getZForResolution(16 / 1.1)).toBe(7);
  });

  it('uses the conservative visual grade selected for the preview', () => {
    expect(BASEMAP_CONTRAST_FACTOR).toBeCloseTo(102 / 108);
    expect(BASEMAP_BRIGHTNESS_FACTOR).toBe(1.05);
  });

  it('makes rendered pixels opaque while retaining transparent sparse holes', () => {
    const pixels = new Uint8ClampedArray([
      10, 20, 30, 0,
      40, 50, 60, 1,
      70, 80, 90, 109,
      100, 110, 120, 255,
    ]);

    makeRenderedPixelsOpaque(pixels);

    expect([...pixels]).toEqual([
      10, 20, 30, 0,
      40, 50, 60, 255,
      70, 80, 90, 255,
      100, 110, 120, 255,
    ]);
  });
});
