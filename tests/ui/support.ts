import { expect, type Page } from '@playwright/test';

export const POISON_DATASET_ID = 'poison-song-26.08';
export const POISON_SNAPSHOT_ID = 'tr:poison-song-26.08:6964517551e0fcb0';
export const POISON_PLACE_ID = 'poison-song-26.08.place-014cd9c0ca05af58dc14';
export const POISON_PLACE_NAME = 'Pneuma Grove';
export const POISON_CARD_NAME = 'Open map: Tamriel Rebuilt 26.08 — Poison Song';
export const POISON_HEADING = 'Tamriel Rebuilt 26.08 — Poison Song';

export const ORIGINAL_DATASET_ID = 'original-goty-hd';
export const ORIGINAL_SNAPSHOT_ID = 'original:goty:8b2690c0ce1c954e';
export const ORIGINAL_PLACE_ID = 'original-goty-hd.place-18680400d24ed6f70770';
export const ORIGINAL_PLACE_NAME = 'Balmora, Guild of Mages';
export const ORIGINAL_CARD_NAME = 'Open map: Morrowind Game of the Year — HD';
export const ORIGINAL_HEADING = 'Morrowind Game of the Year — HD';

const SYNTHETIC_TILE = Buffer.from(
  'UklGRh4AAABXRUJQVlA4TBEAAAAvB8ABAAfQvK5Vqv+BiOh/AAA=',
  'base64',
);

const poisonLocations = {
  schemaVersion: 1,
  datasetId: POISON_DATASET_ID,
  snapshotId: POISON_SNAPSHOT_ID,
  places: [
    {
      id: POISON_PLACE_ID,
      regionId: 'tr-mainland',
      type: 'landmark',
      mapPosition: [12_288, -217_088],
      exteriorCell: [1, -27],
      mimCategory: null,
      minZoom: 0,
      entrances: [],
      sources: [{ kind: 'esm', plugin: 'TR_Mainland.esm', recordId: 'CELL exterior 1,-27', mimIndex: null }],
    },
    {
      id: 'poison-song-26.08.place-ashfall-cavern',
      regionId: 'tr-mainland',
      type: 'cave',
      mapPosition: [12_500, -217_000],
      exteriorCell: [1, -27],
      mimCategory: null,
      minZoom: 0,
      entrances: [],
      sources: [{ kind: 'esm', plugin: 'TR_Mainland.esm', recordId: 'Ashfall Cavern', mimIndex: null }],
    },
    {
      id: 'poison-song-26.08.place-andothren-guildhall',
      regionId: 'tr-mainland',
      type: 'guild',
      mapPosition: [13_000, -216_500],
      exteriorCell: [1, -27],
      mimCategory: null,
      minZoom: 4,
      entrances: [],
      sources: [{ kind: 'esm', plugin: 'TR_Mainland.esm', recordId: 'Andothren Guildhall', mimIndex: null }],
    },
    {
      id: 'poison-song-26.08.place-vvardenfell-tradehouse',
      regionId: 'vvardenfell',
      type: 'shop',
      mapPosition: [-22_000, -14_000],
      exteriorCell: [-3, -2],
      mimCategory: null,
      minZoom: 2,
      entrances: [],
      sources: [{ kind: 'esm', plugin: 'Morrowind.esm', recordId: 'Vvardenfell Tradehouse', mimIndex: null }],
    },
  ],
};

const poisonLocale = {
  schemaVersion: 1,
  datasetId: POISON_DATASET_ID,
  snapshotId: POISON_SNAPSHOT_ID,
  locale: 'en',
  places: [
    { placeId: POISON_PLACE_ID, name: POISON_PLACE_NAME, aliases: [] },
    { placeId: 'poison-song-26.08.place-ashfall-cavern', name: 'Ashfall Cavern', aliases: ['Ashfall'] },
    { placeId: 'poison-song-26.08.place-andothren-guildhall', name: 'Andothren Guildhall', aliases: [] },
    { placeId: 'poison-song-26.08.place-vvardenfell-tradehouse', name: 'Vvardenfell Tradehouse', aliases: [] },
  ],
};

const originalLocations = {
  schemaVersion: 1,
  datasetId: ORIGINAL_DATASET_ID,
  snapshotId: ORIGINAL_SNAPSHOT_ID,
  places: [
    {
      id: ORIGINAL_PLACE_ID,
      regionId: 'vvardenfell',
      type: 'guild',
      mapPosition: [-21_879.766, -14_022.853],
      exteriorCell: [-3, -2],
      mimCategory: null,
      minZoom: 0,
      entrances: [],
      sources: [{ kind: 'esm', plugin: 'Morrowind.esm', recordId: ORIGINAL_PLACE_NAME, mimIndex: null }],
    },
    {
      id: 'original-goty-hd.place-seyda-neen-fixture',
      regionId: 'vvardenfell',
      type: 'settlement',
      mapPosition: [-23_000, -16_000],
      exteriorCell: [-3, -2],
      mimCategory: null,
      minZoom: 0,
      entrances: [],
      sources: [{ kind: 'esm', plugin: 'Morrowind.esm', recordId: 'Seyda Neen', mimIndex: null }],
    },
    {
      id: 'original-goty-hd.place-balmora-temple-fixture',
      regionId: 'vvardenfell',
      type: 'temple',
      mapPosition: [-21_000, -14_500],
      exteriorCell: [-3, -2],
      mimCategory: null,
      minZoom: 2,
      entrances: [],
      sources: [{ kind: 'esm', plugin: 'Morrowind.esm', recordId: 'Balmora Temple', mimIndex: null }],
    },
    {
      id: 'original-goty-hd.place-solstheim-ice-cave',
      regionId: 'solstheim',
      type: 'cave',
      mapPosition: [-165_000, 140_000],
      exteriorCell: [-21, 17],
      mimCategory: null,
      minZoom: 3,
      entrances: [],
      sources: [{ kind: 'esm', plugin: 'Bloodmoon.esm', recordId: 'Solstheim Ice Cave', mimIndex: null }],
    },
  ],
};

const originalLocale = {
  schemaVersion: 1,
  datasetId: ORIGINAL_DATASET_ID,
  snapshotId: ORIGINAL_SNAPSHOT_ID,
  locale: 'en',
  places: [
    { placeId: ORIGINAL_PLACE_ID, name: ORIGINAL_PLACE_NAME, aliases: [] },
    { placeId: 'original-goty-hd.place-seyda-neen-fixture', name: 'Seyda Neen', aliases: [] },
    { placeId: 'original-goty-hd.place-balmora-temple-fixture', name: 'Balmora Temple', aliases: [] },
    { placeId: 'original-goty-hd.place-solstheim-ice-cave', name: 'Solstheim Ice Cave', aliases: [] },
  ],
};

export type TileFailureMode = 'none' | 'partial' | 'full';

export interface OfflineRouteOptions {
  readonly failManifestDatasetId?: string;
  readonly failDatasetAssets?: boolean;
  readonly holdDatasetAssets?: boolean;
  readonly failTiles?: boolean;
  readonly tileFailureMode?: TileFailureMode;
  readonly holdTiles?: boolean;
  readonly holdTileRetries?: boolean;
  readonly blockOriginalManifest?: boolean;
  readonly emptyCatalogDatasetId?: string;
}

export interface OfflineProbe {
  readonly externalRequests: string[];
  readonly localFailures: string[];
  readonly manifestRequests: string[];
  readonly datasetAssetRequests: string[];
  readonly tileRequests: string[];
  readonly failedTileRequests: string[];
  readonly manifestRequestCount: (datasetId: string) => number;
  readonly datasetAssetRequestCount: () => number;
  readonly tileRequestCount: (pathname?: string) => number;
  readonly restoreManifest: () => void;
  readonly restoreDatasetAssets: () => void;
  readonly restoreTiles: () => void;
  readonly failTilesFully: () => void;
  readonly showEmptyCatalog: (datasetId: string) => void;
  readonly releaseDatasetAssets: () => void;
  readonly releaseTiles: () => void;
  readonly releaseTileRetries: () => void;
}

function syntheticCatalog(pathname: string) {
  if (pathname.includes(`/datasets/generated/${POISON_DATASET_ID}/catalogs/`)) {
    return { locations: poisonLocations, locale: poisonLocale };
  }
  if (pathname.includes(`/datasets/generated/${ORIGINAL_DATASET_ID}/catalogs/`)) {
    return { locations: originalLocations, locale: originalLocale };
  }
  return null;
}

function isLocalUrl(url: URL): boolean {
  return url.hostname === '127.0.0.1' || url.hostname === 'localhost';
}

export async function installOfflineRoutes(
  page: Page,
  {
    failManifestDatasetId,
    failDatasetAssets = false,
    holdDatasetAssets = false,
    failTiles = false,
    tileFailureMode = failTiles ? 'full' : 'none',
    holdTiles = false,
    holdTileRetries = false,
    blockOriginalManifest = false,
    emptyCatalogDatasetId,
  }: OfflineRouteOptions = {},
): Promise<OfflineProbe> {
  let manifestUnavailable = failManifestDatasetId !== undefined;
  let datasetAssetsUnavailable = failDatasetAssets;
  let activeTileFailureMode = tileFailureMode;
  let activeEmptyCatalogDatasetId = emptyCatalogDatasetId;
  let tileRecoveryStarted = false;
  const manifestRequests: string[] = [];
  const datasetAssetRequests: string[] = [];
  const tileRequests: string[] = [];
  const failedTileRequests: string[] = [];
  const partialFailedTilePaths = new Set<string>();
  let releasePendingDatasetAssets: (() => void) | null = null;
  const pendingDatasetAssets = new Promise<void>((resolve) => {
    releasePendingDatasetAssets = resolve;
  });
  let releasePendingTiles: (() => void) | null = null;
  const pendingTiles = new Promise<void>((resolve) => {
    releasePendingTiles = resolve;
  });
  let releasePendingTileRetries: (() => void) | null = null;
  const pendingTileRetries = new Promise<void>((resolve) => {
    releasePendingTileRetries = resolve;
  });
  const probe: OfflineProbe = {
    externalRequests: [],
    localFailures: [],
    manifestRequests,
    datasetAssetRequests,
    tileRequests,
    failedTileRequests,
    manifestRequestCount: (datasetId) => manifestRequests.filter(
      (pathname) => pathname === `/datasets/manifests/${datasetId}.json`,
    ).length,
    datasetAssetRequestCount: () => datasetAssetRequests.length,
    tileRequestCount: (pathname) => pathname === undefined
      ? tileRequests.length
      : tileRequests.filter((candidate) => candidate === pathname).length,
    restoreManifest: () => { manifestUnavailable = false; },
    restoreDatasetAssets: () => { datasetAssetsUnavailable = false; },
    restoreTiles: () => {
      activeTileFailureMode = 'none';
      tileRecoveryStarted = true;
    },
    failTilesFully: () => { activeTileFailureMode = 'full'; },
    showEmptyCatalog: (datasetId) => { activeEmptyCatalogDatasetId = datasetId; },
    releaseDatasetAssets: () => { releasePendingDatasetAssets?.(); },
    releaseTiles: () => { releasePendingTiles?.(); },
    releaseTileRetries: () => { releasePendingTileRetries?.(); },
  };

  page.on('response', (response) => {
    const url = new URL(response.url());
    if (isLocalUrl(url) && response.status() >= 400) {
      probe.localFailures.push(`${response.status()} ${url.pathname}`);
    }
  });
  page.on('websocket', (socket) => {
    const url = new URL(socket.url());
    if (!isLocalUrl(url)) {
      probe.externalRequests.push(`WS ${socket.url()}`);
    }
  });

  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.protocol === 'data:' || url.protocol === 'blob:') {
      await route.continue();
      return;
    }
    if (!isLocalUrl(url)) {
      probe.externalRequests.push(`${request.method()} ${request.url()}`);
      await route.abort('blockedbyclient');
      return;
    }

    const { pathname } = url;
    const manifestPrefix = '/datasets/manifests/';
    const isManifest = pathname.startsWith(manifestPrefix) && pathname.endsWith('.json');
    const manifestDatasetId = isManifest
      ? pathname.slice(manifestPrefix.length, -'.json'.length)
      : null;
    if (manifestDatasetId !== null) {
      manifestRequests.push(pathname);
    }
    if (
      manifestUnavailable &&
      failManifestDatasetId !== undefined &&
      manifestDatasetId === failManifestDatasetId
    ) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
      return;
    }
    if (blockOriginalManifest && pathname === `/datasets/manifests/${ORIGINAL_DATASET_ID}.json`) {
      const response = await route.fetch();
      const manifest = await response.json() as {
        readiness: { status: string; blockers: string[] };
        localization: { locales: Array<{ status: string; coverage: number }> };
        regions: Array<{ status: string }>;
        artifacts: { locations: unknown; locales: Array<{ artifact: unknown }>; tiles: unknown; catalogAudit: unknown };
        provenance: { kind: string };
      };
      manifest.readiness.status = 'blocked';
      manifest.readiness.blockers = ['Synthetic unpublished-dataset UI fixture.'];
      manifest.localization.locales[0]!.status = 'planned';
      manifest.localization.locales[0]!.coverage = 0;
      for (const region of manifest.regions) {
        if (region.status === 'available') region.status = 'blocked';
      }
      manifest.artifacts.locations = null;
      manifest.artifacts.locales[0]!.artifact = null;
      manifest.artifacts.tiles = null;
      manifest.artifacts.catalogAudit = null;
      manifest.provenance.kind = 'placeholder';
      await route.fulfill({ response, json: manifest });
      return;
    }

    const catalog = syntheticCatalog(pathname);
    const isLocations = catalog !== null && pathname.endsWith('/locations.json');
    const isLocale = catalog !== null && pathname.endsWith('/locales/en.json');
    const isDatasetAssets = pathname.startsWith('/datasets/metadata/') && pathname.endsWith('/map-assets.json');
    const isTile = pathname.startsWith('/datasets/generated/') && pathname.includes('/tiles/') && pathname.endsWith('.webp');

    if (isDatasetAssets) {
      datasetAssetRequests.push(pathname);
      if (datasetAssetsUnavailable) {
        await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
        return;
      }
      if (holdDatasetAssets) {
        await pendingDatasetAssets;
      }
    }
    if (isTile) {
      tileRequests.push(pathname);
      if (holdTiles) await pendingTiles;
      if (tileRecoveryStarted && holdTileRetries) await pendingTileRetries;
      if (activeTileFailureMode === 'partial' && partialFailedTilePaths.size === 0) {
        partialFailedTilePaths.add(pathname);
      }
      const shouldFail = activeTileFailureMode === 'full' ||
        (activeTileFailureMode === 'partial' && partialFailedTilePaths.has(pathname));
      if (shouldFail) {
        failedTileRequests.push(pathname);
        await route.fulfill({ status: 503, contentType: 'text/plain', body: 'unavailable' });
        return;
      }
      await route.fulfill({ status: 200, contentType: 'image/webp', body: SYNTHETIC_TILE });
      return;
    }
    if (isLocations) {
      await route.fulfill({
        json: activeEmptyCatalogDatasetId === catalog.locations.datasetId
          ? { ...catalog.locations, places: [] }
          : catalog.locations,
      });
      return;
    }
    if (isLocale) {
      await route.fulfill({
        json: activeEmptyCatalogDatasetId === catalog.locale.datasetId
          ? { ...catalog.locale, places: [] }
          : catalog.locale,
      });
      return;
    }
    await route.continue();
  });

  return probe;
}

export async function openDataset(
  page: Page,
  cardName: string,
  heading: string,
): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: cardName }).click();
  await expect(page.getByRole('heading', { name: heading })).toBeVisible();
  await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeVisible();
}

export async function waitForLandingReady(page: Page): Promise<void> {
  await expect(page.locator('.landing-map-backdrop')).toHaveAttribute('data-ready', 'true');
}

export async function waitForVisualReady(page: Page): Promise<void> {
  await page.evaluate(async () => document.fonts.ready);
  await expect(page.locator('.archive-screen, .map-screen')).toBeVisible();
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  await expect(map).toHaveAttribute('data-basemap-loaded', /^[1-9]\d*$/);
  await expect(map).toHaveAttribute('data-basemap-pending', '0');
  await expect(page.locator('.basemap-state')).toHaveCount(0);
  await page.locator('.archive-screen, .map-screen').evaluate((element) => {
    element.setAttribute('data-visual-ready', 'true');
  });
}

export async function expectNoViewportOverflow(page: Page): Promise<void> {
  await expect.poll(() => page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )).toBe(0);
}
