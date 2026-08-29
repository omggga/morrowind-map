import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DatasetManifest } from '@morrowind-map/contracts';
import { DatasetAssetsMissingError, loadDataset } from './loadDataset';

const originalSnapshotId = 'original:goty:fixture';
const originalPlaceId = 'original-goty.vvardenfell.mim-0000';
const poisonSnapshotId = 'tr:poison-song-26.08:fixture';
const poisonPlaceId = 'poison-song-26.08.place-0001';

const originalPlace = {
  id: originalPlaceId,
  regionId: 'vvardenfell',
  type: 'settlement',
  mapPosition: [-20_000, -12_000],
  exteriorCell: [-3, -2],
  mimCategory: 19,
  minZoom: 0,
  entrances: [],
  sources: [{ kind: 'mim', plugin: 'mwmain.gdb', recordId: null, mimIndex: 0 }],
};

const poisonPlace = {
  id: poisonPlaceId,
  regionId: 'vvardenfell',
  type: 'settlement',
  mapPosition: [100, 200],
  exteriorCell: [0, 0],
  mimCategory: null,
  minZoom: 0,
  entrances: [],
  sources: [{ kind: 'esm', plugin: 'Morrowind.esm', recordId: 'Balmora', mimIndex: null }],
};

function originalManifest(): DatasetManifest {
  return {
    datasetId: 'original-goty',
    snapshotId: originalSnapshotId,
    localization: {
      defaultLocale: 'ru',
      locales: [
        { locale: 'en', status: 'available', coverage: 1, fallbackLocale: null },
        { locale: 'ru', status: 'available', coverage: 1, fallbackLocale: null },
      ],
    },
    regions: [
      {
        id: 'vvardenfell',
        title: { en: 'Vvardenfell', ru: 'Вварденфелл' },
        kind: 'exterior',
        status: 'available',
      },
    ],
    map: {
      projection: {
        code: 'TES3:WORLD',
        units: 'world-units',
        cellSize: 8192,
        extent: [-32_768, -32_768, 32_768, 32_768],
        center: [0, 0],
      },
      tileGrid: {
        tileSize: 512,
        origin: [-32_768, 32_768],
        resolutions: [2048, 1024],
      },
    },
    artifacts: {
      locations: { url: '/locations.json' },
      locales: [
        { locale: 'en', artifact: { url: '/en.json' } },
        { locale: 'ru', artifact: { url: '/ru.json' } },
      ],
      tiles: { manifestUrl: '/map-assets.json' },
    },
  } as unknown as DatasetManifest;
}

function poisonManifest(): DatasetManifest {
  return {
    datasetId: 'poison-song-26.08',
    snapshotId: poisonSnapshotId,
    localization: {
      defaultLocale: 'en',
      locales: [{ locale: 'en', status: 'available', coverage: 1, fallbackLocale: null }],
    },
    regions: [
      {
        id: 'vvardenfell',
        title: { en: 'Vvardenfell' },
        kind: 'exterior',
        status: 'available',
      },
      {
        id: 'mournhold',
        title: { en: 'Mournhold' },
        kind: 'interior-inset',
        status: 'planned',
      },
    ],
    map: {
      projection: {
        code: 'TES3:WORLD',
        units: 'world-units',
        cellSize: 8192,
        extent: [0, 0, 16_384, 16_384],
        center: [8192, 8192],
      },
      tileGrid: {
        tileSize: 512,
        origin: [0, 16_384],
        resolutions: [2048, 1024],
      },
    },
    artifacts: {
      locations: { url: '/poison-locations.json' },
      locales: [{ locale: 'en', artifact: { url: '/poison-en.json' } }],
      tiles: { manifestUrl: '/poison-map-assets.json' },
    },
  } as unknown as DatasetManifest;
}

function originalMapAssets() {
  return {
    schemaVersion: 1,
    datasetId: 'original-goty',
    snapshotId: originalSnapshotId,
    projection: 'TES3:WORLD',
    rasters: [
      {
        id: 'original-goty.vvardenfell',
        regionId: 'vvardenfell',
        kind: 'static-image',
        imageUrl: '/datasets/generated/original-goty/rasters/vvardenfell.jpg',
        mediaType: 'image/jpeg',
        pixelSize: [3300, 3800],
        extent: [-32_768, -32_768, 32_768, 32_768],
        sha256: 'a'.repeat(64),
      },
    ],
  };
}

function poisonMapAssets() {
  return {
    schemaVersion: 1,
    datasetId: 'poison-song-26.08',
    snapshotId: poisonSnapshotId,
    projection: 'TES3:WORLD',
    rasters: [],
    tilePyramids: [
      {
        id: 'poison-song-26.08.basemap',
        regionIds: ['vvardenfell'],
        kind: 'xyz-pyramid',
        urlTemplate: '/datasets/poison/{z}/{x}/{y}.webp',
        mediaType: 'image/webp',
        tileSize: 512,
        extent: [0, 0, 16_384, 16_384],
        origin: [0, 16_384],
        resolutions: [2048, 1024],
        minZoom: 0,
        maxZoom: 1,
        sparse: true,
        coverage: {
          url: '/datasets/poison-coverage.json',
          mediaType: 'application/json',
          sha256: 'b'.repeat(64),
          bytes: 200,
        },
        qualityReport: {
          url: '/datasets/poison-quality.json',
          mediaType: 'application/json',
          sha256: 'c'.repeat(64),
          bytes: 200,
        },
        derivation: {
          kind: 'cross-shard-seam-stabilization',
          version: 'fixture-v1',
          sourceInventorySha256: 'd'.repeat(64),
          implementationSha256: 'e'.repeat(64),
          receipt: {
            url: '/datasets/poison-derivation.json',
            mediaType: 'application/json',
            sha256: 'f'.repeat(64),
            bytes: 200,
          },
        },
        integrity: {
          tileCount: 2,
          totalBytes: 1000,
          inventorySha256: '0'.repeat(64),
          inventoryFileSha256: '1'.repeat(64),
          provenanceFingerprint: '2'.repeat(64),
          planFingerprint: '3'.repeat(64),
          profileFingerprint: '4'.repeat(64),
          rendererFingerprint: '5'.repeat(64),
          productionSourceFingerprint: '6'.repeat(64),
          assetTreeFingerprint: '7'.repeat(64),
          inputFingerprint: '8'.repeat(64),
        },
      },
    ],
  };
}

function poisonCoverage() {
  return {
    schemaVersion: 1,
    datasetId: 'poison-song-26.08',
    snapshotId: poisonSnapshotId,
    tilePyramidId: 'poison-song-26.08.basemap',
    encoding: 'x-y-ranges-v1',
    tileCount: 2,
    levels: [
      { z: 0, columns: [{ x: 0, yRanges: [[0, 0]] }] },
      { z: 1, columns: [{ x: 0, yRanges: [[0, 0]] }] },
    ],
  };
}

function jsonResponse(value: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(value),
  });
}

function stubJson(values: Readonly<Record<string, unknown>>): void {
  vi.stubGlobal('fetch', vi.fn((url: string) => jsonResponse(values[url])));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('loadDataset', () => {
  it('preserves the Original EN/RU catalog and static raster behavior', async () => {
    stubJson({
      '/locations.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId: originalSnapshotId,
        places: [originalPlace],
      },
      '/en.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId: originalSnapshotId,
        locale: 'en',
        places: [{ placeId: originalPlaceId, name: 'Balmora', aliases: [] }],
      },
      '/ru.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId: originalSnapshotId,
        locale: 'ru',
        places: [{ placeId: originalPlaceId, name: 'Балмора', aliases: [] }],
      },
      '/map-assets.json': originalMapAssets(),
    });

    const bundle = await loadDataset(originalManifest(), new AbortController().signal);

    expect(bundle.locations.places).toHaveLength(1);
    expect(bundle.locales.get('ru')?.places[0]?.name).toBe('Балмора');
    expect(bundle.mapAssets.rasters[0]?.regionId).toBe('vvardenfell');
    expect(bundle.tileCoverages.size).toBe(0);
  });

  it('loads an EN-only Poison Song catalog, pyramid and sparse coverage', async () => {
    stubJson({
      '/poison-locations.json': {
        schemaVersion: 1,
        datasetId: 'poison-song-26.08',
        snapshotId: poisonSnapshotId,
        places: [poisonPlace],
      },
      '/poison-en.json': {
        schemaVersion: 1,
        datasetId: 'poison-song-26.08',
        snapshotId: poisonSnapshotId,
        locale: 'en',
        places: [{ placeId: poisonPlaceId, name: 'Balmora', aliases: [] }],
      },
      '/poison-map-assets.json': poisonMapAssets(),
      '/datasets/poison-coverage.json': poisonCoverage(),
    });

    const bundle = await loadDataset(poisonManifest(), new AbortController().signal);

    expect([...bundle.locales.keys()]).toEqual(['en']);
    expect(bundle.mapAssets.tilePyramids?.[0]?.mediaType).toBe('image/webp');
    expect(bundle.tileCoverages.get('poison-song-26.08.basemap')?.tileCount).toBe(2);
  });

  it('fills a partial locale through its declared fallback chain', async () => {
    const manifest = originalManifest();
    manifest.localization.locales[1] = {
      locale: 'ru',
      status: 'partial',
      coverage: 0.5,
      fallbackLocale: 'en',
    };
    const secondPlace = {
      ...originalPlace,
      id: 'original-goty.vvardenfell.mim-0001',
      mapPosition: [4_096, 8_192],
      exteriorCell: [0, 1],
    };
    stubJson({
      '/locations.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId: originalSnapshotId,
        places: [originalPlace, secondPlace],
      },
      '/en.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId: originalSnapshotId,
        locale: 'en',
        places: [
          { placeId: originalPlaceId, name: 'Balmora', aliases: [] },
          { placeId: secondPlace.id, name: 'Caldera', aliases: [] },
        ],
      },
      '/ru.json': {
        schemaVersion: 1,
        datasetId: 'original-goty',
        snapshotId: originalSnapshotId,
        locale: 'ru',
        places: [{ placeId: originalPlaceId, name: 'Балмора', aliases: [] }],
      },
      '/map-assets.json': originalMapAssets(),
    });

    const bundle = await loadDataset(manifest, new AbortController().signal);

    expect(bundle.locales.get('ru')?.places).toEqual([
      { placeId: originalPlaceId, name: 'Балмора', aliases: [] },
      { placeId: secondPlace.id, name: 'Caldera', aliases: [] },
    ]);
  });

  it('rejects an available locale that does not cover the structural catalog', async () => {
    stubJson({
      '/poison-locations.json': {
        schemaVersion: 1,
        datasetId: 'poison-song-26.08',
        snapshotId: poisonSnapshotId,
        places: [poisonPlace],
      },
      '/poison-en.json': {
        schemaVersion: 1,
        datasetId: 'poison-song-26.08',
        snapshotId: poisonSnapshotId,
        locale: 'en',
        places: [],
      },
      '/poison-map-assets.json': poisonMapAssets(),
      '/datasets/poison-coverage.json': poisonCoverage(),
    });

    await expect(
      loadDataset(poisonManifest(), new AbortController().signal),
    ).rejects.toThrow('Locale en не покрывает весь location catalog');
  });

  it('uses a typed error for missing required dataset references', async () => {
    const manifest = poisonManifest();
    manifest.artifacts.locations = null;

    await expect(loadDataset(manifest, new AbortController().signal)).rejects.toBeInstanceOf(
      DatasetAssetsMissingError,
    );
  });

  it('uses a typed error when an available locale has no artifact', async () => {
    const manifest = poisonManifest();
    manifest.artifacts.locales[0]!.artifact = null;
    stubJson({
      '/poison-locations.json': {
        schemaVersion: 1,
        datasetId: 'poison-song-26.08',
        snapshotId: poisonSnapshotId,
        places: [poisonPlace],
      },
      '/poison-map-assets.json': poisonMapAssets(),
    });

    const error = await loadDataset(manifest, new AbortController().signal).catch(
      (reason: unknown) => reason,
    );
    expect(error).toBeInstanceOf(DatasetAssetsMissingError);
    expect(error).toMatchObject({
      message: 'Dataset poison-song-26.08 не содержит EN locale catalog',
    });
  });

  it('keeps an HTTP 404 for a declared artifact as a normal load error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url === '/poison-locations.json'
          ? Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
          : jsonResponse({}),
      ),
    );

    const error = await loadDataset(poisonManifest(), new AbortController().signal).catch(
      (reason: unknown) => reason,
    );
    expect(error).toBeInstanceOf(Error);
    expect(error).not.toBeInstanceOf(DatasetAssetsMissingError);
    if (!(error instanceof Error)) {
      throw new Error('Expected a normal Error');
    }
    expect(error.message).toContain('HTTP 404');
  });

  it('rejects a valid pyramid whose grid differs from the dataset manifest', async () => {
    const mapAssets = poisonMapAssets();
    mapAssets.tilePyramids[0]!.resolutions = [1024, 512];
    stubJson({
      '/poison-locations.json': {
        schemaVersion: 1,
        datasetId: 'poison-song-26.08',
        snapshotId: poisonSnapshotId,
        places: [poisonPlace],
      },
      '/poison-en.json': {
        schemaVersion: 1,
        datasetId: 'poison-song-26.08',
        snapshotId: poisonSnapshotId,
        locale: 'en',
        places: [{ placeId: poisonPlaceId, name: 'Balmora', aliases: [] }],
      },
      '/poison-map-assets.json': mapAssets,
    });

    await expect(
      loadDataset(poisonManifest(), new AbortController().signal),
    ).rejects.toThrow('resolutions не совпадают с dataset manifest');
  });

  it('rejects pyramid regions that differ from available exterior regions', async () => {
    const mapAssets = poisonMapAssets();
    mapAssets.tilePyramids[0]!.regionIds = ['unknown'];
    stubJson({
      '/poison-locations.json': {
        schemaVersion: 1,
        datasetId: 'poison-song-26.08',
        snapshotId: poisonSnapshotId,
        places: [poisonPlace],
      },
      '/poison-en.json': {
        schemaVersion: 1,
        datasetId: 'poison-song-26.08',
        snapshotId: poisonSnapshotId,
        locale: 'en',
        places: [{ placeId: poisonPlaceId, name: 'Balmora', aliases: [] }],
      },
      '/poison-map-assets.json': mapAssets,
    });

    await expect(
      loadDataset(poisonManifest(), new AbortController().signal),
    ).rejects.toThrow('содержит неизвестные regionIds: unknown');
  });
});
