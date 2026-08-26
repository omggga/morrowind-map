import { describe, expect, it, vi } from 'vitest';
import type { DatasetManifest } from '@morrowind-map/contracts';
import { loadOriginalDataset } from './loadOriginalDataset';

const snapshotId = 'original:goty:fixture';
const placeId = 'original-goty.vvardenfell.mim-0000';

const manifest = {
  datasetId: 'original-goty',
  snapshotId,
  artifacts: {
    locations: { url: '/locations.json' },
    locales: [
      { locale: 'en', artifact: { url: '/en.json' } },
      { locale: 'ru', artifact: { url: '/ru.json' } },
    ],
    tiles: { manifestUrl: '/map-assets.json' },
  },
} as DatasetManifest;

const place = {
  id: placeId,
  regionId: 'vvardenfell',
  type: 'settlement',
  mapPosition: [-20_000, -12_000],
  exteriorCell: [-3, -2],
  mimCategory: 19,
  minZoom: 0,
  entrances: [],
  sources: [{ kind: 'mim', plugin: 'mwmain.gdb', recordId: null, mimIndex: 0 }],
};

function response(value: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(value),
  });
}

describe('loadOriginalDataset', () => {
  it('loads and cross-checks all four Original artifacts', async () => {
    const values: Record<string, unknown> = {
      '/locations.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId,
        places: [place],
      },
      '/en.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId,
        locale: 'en',
        places: [{ placeId, name: 'Balmora', aliases: [] }],
      },
      '/ru.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId,
        locale: 'ru',
        places: [{ placeId, name: 'Балмора', aliases: [] }],
      },
      '/map-assets.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId,
        projection: 'TES3:WORLD',
        rasters: [
          {
            id: 'original-goty.vvardenfell',
            regionId: 'vvardenfell',
            kind: 'static-image',
            imageUrl: '/datasets/generated/original-goty/rasters/vvardenfell.jpg',
            mediaType: 'image/jpeg',
            pixelSize: [3300, 3800],
            extent: [-125_000, -130_000, 175_000, 220_000],
            sha256: 'a'.repeat(64),
          },
        ],
      },
    };
    vi.stubGlobal('fetch', vi.fn((url: string) => response(values[url])));

    const bundle = await loadOriginalDataset(manifest, new AbortController().signal);

    expect(bundle.locations.places).toHaveLength(1);
    expect(bundle.locales.ru.places[0]?.name).toBe('Балмора');
    expect(bundle.mapAssets.rasters[0]?.regionId).toBe('vvardenfell');
  });

  it('rejects a locale that does not cover the structural catalog', async () => {
    const values: Record<string, unknown> = {
      '/locations.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId,
        places: [place],
      },
      '/en.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId,
        locale: 'en',
        places: [],
      },
      '/ru.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId,
        locale: 'ru',
        places: [{ placeId, name: 'Балмора', aliases: [] }],
      },
      '/map-assets.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId,
        projection: 'TES3:WORLD',
        rasters: [
          {
            id: 'original-goty.vvardenfell',
            regionId: 'vvardenfell',
            kind: 'static-image',
            imageUrl: '/datasets/generated/original-goty/rasters/vvardenfell.jpg',
            mediaType: 'image/jpeg',
            pixelSize: [3300, 3800],
            extent: [-125_000, -130_000, 175_000, 220_000],
            sha256: 'a'.repeat(64),
          },
        ],
      },
    };
    vi.stubGlobal('fetch', vi.fn((url: string) => response(values[url])));

    await expect(
      loadOriginalDataset(manifest, new AbortController().signal),
    ).rejects.toThrow('Locale en не покрывает весь location catalog');
  });
});
