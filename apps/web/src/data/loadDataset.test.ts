import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ContractValidationError,
  type DatasetManifest,
} from '@morrowind-map/contracts';
import {
  DatasetAssetsInvalidError,
  DatasetAssetsMissingError,
  loadDataset,
} from './loadDataset';

const originalSnapshotId = 'original:goty-hd:fixture';
const originalPlaceId = 'original-goty-hd.place-balmora';
const poisonSnapshotId = 'tr:poison-song-26.08:fixture';
const poisonPlaceId = 'poison-song-26.08.place-0001';

const originalPlace = {
  id: originalPlaceId,
  regionId: 'vvardenfell',
  type: 'settlement',
  mapPosition: [-20_000, -12_000],
  exteriorCell: [-3, -2],
  mimCategory: null,
  minZoom: 0,
  entrances: [],
  sources: [{ kind: 'esm', plugin: 'Morrowind.esm', recordId: 'Balmora', mimIndex: null }],
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
    datasetId: 'original-goty-hd',
    snapshotId: originalSnapshotId,
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
      locales: [{ locale: 'en', artifact: { url: '/en.json' } }],
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
    datasetId: 'original-goty-hd',
    snapshotId: originalSnapshotId,
    projection: 'TES3:WORLD',
    rasters: [
      {
        id: 'original-goty-hd.vvardenfell-preview',
        regionId: 'vvardenfell',
        kind: 'static-image',
        imageUrl: '/datasets/fixtures/original-goty-hd-vvardenfell.jpg',
        mediaType: 'image/jpeg',
        pixelSize: [1024, 1024],
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

function poisonResponses(): Record<string, unknown> {
  return {
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
  it('loads the EN-only Original catalog from ESM-derived place data', async () => {
    stubJson({
      '/locations.json': {
        schemaVersion: 1,
        datasetId: 'original-goty-hd',
        snapshotId: originalSnapshotId,
        places: [originalPlace],
      },
      '/en.json': {
        schemaVersion: 1,
        datasetId: 'original-goty-hd',
        snapshotId: originalSnapshotId,
        locale: 'en',
        places: [{ placeId: originalPlaceId, name: 'Balmora', aliases: [] }],
      },
      '/map-assets.json': originalMapAssets(),
    });

    const bundle = await loadDataset(originalManifest(), new AbortController().signal);

    expect(bundle.locations.places).toHaveLength(1);
    expect([...bundle.locales.keys()]).toEqual(['en']);
    expect(bundle.locales.get('en')?.places[0]?.name).toBe('Balmora');
    expect(bundle.mapAssets.rasters[0]?.id).toBe('original-goty-hd.vvardenfell-preview');
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

    const controller = new AbortController();
    const bundle = await loadDataset(poisonManifest(), controller.signal);

    expect([...bundle.locales.keys()]).toEqual(['en']);
    expect(bundle.mapAssets.tilePyramids?.[0]?.mediaType).toBe('image/webp');
    expect(bundle.tileCoverages.get('poison-song-26.08.basemap')?.tileCount).toBe(2);
    expect(vi.mocked(fetch).mock.calls).toHaveLength(4);
    expect(
      vi.mocked(fetch).mock.calls.every(([, options]) => options?.signal === controller.signal),
    ).toBe(true);
  });

  it('propagates abort to in-flight fetches and does not continue to dependent resources', async () => {
    const controller = new AbortController();
    const abortError = new DOMException('Fixture request cancelled', 'AbortError');
    const fetchMock = vi.fn((_url: string, options?: RequestInit) =>
      new Promise<never>((_resolve, reject) => {
        const signal = options?.signal;
        expect(signal).toBe(controller.signal);
        if (signal?.aborted) {
          reject(abortError);
          return;
        }
        signal?.addEventListener('abort', () => reject(abortError), { once: true });
      }));
    vi.stubGlobal('fetch', fetchMock);

    const loading = loadDataset(poisonManifest(), controller.signal);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    controller.abort(abortError);

    await expect(loading).rejects.toBe(abortError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    ['location catalog', '/poison-locations.json'],
    ['locale catalog', '/poison-en.json'],
    ['map-assets manifest', '/poison-map-assets.json'],
  ])('propagates malformed %s JSON without reclassifying it', async (label, failingUrl) => {
    const responses = poisonResponses();
    const syntaxError = new SyntaxError(`Malformed ${label}`);
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url === failingUrl
          ? Promise.resolve({
              ok: true,
              status: 200,
              json: () => Promise.reject(syntaxError),
            })
          : jsonResponse(responses[url])),
    );

    await expect(
      loadDataset(poisonManifest(), new AbortController().signal),
    ).rejects.toBe(syntaxError);
  });

  it.each([
    ['locations', '/poison-locations.json', 'location catalog'],
    ['locale', '/poison-en.json', 'place locale catalog'],
    ['map assets', '/poison-map-assets.json', 'map assets manifest'],
  ] as const)(
    'rejects malformed %s schema through the contract parser',
    async (_label, failingUrl, contract) => {
      const responses = poisonResponses();
      responses[failingUrl] = { schemaVersion: 1 };
      stubJson(responses);

      const error = await loadDataset(
        poisonManifest(),
        new AbortController().signal,
      ).catch((reason: unknown) => reason);

      expect(error).toBeInstanceOf(ContractValidationError);
      expect(error).toMatchObject({ contract });
    },
  );

  it.each([
    {
      label: 'location catalog dataset',
      url: '/poison-locations.json',
      replacement: () => ({
        schemaVersion: 1,
        datasetId: 'other-dataset',
        snapshotId: poisonSnapshotId,
        places: [{ ...poisonPlace, id: 'other-dataset.place-0001' }],
      }),
      message: 'Location catalog belongs to a different dataset snapshot',
    },
    {
      label: 'locale catalog snapshot',
      url: '/poison-en.json',
      replacement: () => ({
        schemaVersion: 1,
        datasetId: 'poison-song-26.08',
        snapshotId: 'tr:poison-song-26.08:other',
        locale: 'en',
        places: [{ placeId: poisonPlaceId, name: 'Balmora', aliases: [] }],
      }),
      message: 'EN locale catalog belongs to a different dataset snapshot',
    },
    {
      label: 'map-assets snapshot',
      url: '/poison-map-assets.json',
      replacement: () => ({
        ...poisonMapAssets(),
        snapshotId: 'tr:poison-song-26.08:other',
      }),
      message: 'Map assets belongs to a different dataset snapshot',
    },
  ])('rejects a valid $label mismatch against the manifest', async ({
    url,
    replacement,
    message,
  }) => {
    const responses = poisonResponses();
    responses[url] = replacement();
    stubJson(responses);

    const error = await loadDataset(
      poisonManifest(),
      new AbortController().signal,
    ).catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(DatasetAssetsInvalidError);
    expect(error).toMatchObject({ message });
  });

  it('rejects coverage inventory count that differs from map-assets integrity', async () => {
    const responses = poisonResponses();
    const mapAssets = poisonMapAssets();
    mapAssets.tilePyramids[0]!.integrity.tileCount = 3;
    responses['/poison-map-assets.json'] = mapAssets;
    stubJson(responses);

    await expect(
      loadDataset(poisonManifest(), new AbortController().signal),
    ).rejects.toThrow('must match tile pyramid integrity.tileCount');
  });

  it.each([
    ['map-assets manifest', '/poison-map-assets.json'],
    ['tile coverage', '/datasets/poison-coverage.json'],
  ])('keeps an HTTP 503 for the declared %s as a recoverable runtime error', async (
    _label,
    failingUrl,
  ) => {
    const responses = poisonResponses();
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url === failingUrl
          ? Promise.resolve({
              ok: false,
              status: 503,
              json: () => Promise.resolve({}),
            })
          : jsonResponse(responses[url])),
    );

    const error = await loadDataset(poisonManifest(), new AbortController().signal).catch(
      (reason: unknown) => reason,
    );

    expect(error).toBeInstanceOf(Error);
    expect(error).not.toBeInstanceOf(DatasetAssetsMissingError);
    expect(error).toMatchObject({
      message: `Could not load ${failingUrl} (HTTP 503)`,
    });
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
    ).rejects.toThrow('Locale en does not cover the complete location catalog');
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
      message: 'Dataset poison-song-26.08 does not contain an EN locale catalog',
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
    ).rejects.toThrow('resolutions do not match the dataset manifest');
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
    ).rejects.toThrow('contains unknown regionIds: unknown');
  });
});
