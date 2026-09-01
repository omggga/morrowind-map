import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const DATASET_ID = 'poison-song-26.08';
const SNAPSHOT_ID = 'tr:poison-song-26.08:6964517551e0fcb0';
const V4_INVENTORY =
  '93758a5e645013821d99a7989d69f3e4aa39373e2c5cb4b97873da421c5052b2';
const PLACE_ID = 'poison-song-26.08.place-014cd9c0ca05af58dc14';
const PLACE_NAME = 'Pneuma Grove';
const POISON_CARD_NAME = 'Open map: Tamriel Rebuilt 26.08 — Poison Song';
const ORIGINAL_CARD_NAME = 'Open map: Morrowind Game of the Year — HD';
const ORIGINAL_DATASET_ID = 'original-goty-hd';
const ORIGINAL_INVENTORY =
  'aade4b98c2fb905fd2617871345292a638e3a4a25c6d036db7a3cc18bb2dd014';
const ORIGINAL_CATALOG_INVENTORY =
  '6ea0c0a0272f6c8456a947c9dc36bac5116a9cd524cc4b351fdad867cf3e0df1';
const ORIGINAL_SNAPSHOT_ID = 'original:goty:8b2690c0ce1c954e';
const ORIGINAL_PLACE_ID = 'original-goty-hd.place-18680400d24ed6f70770';
const ORIGINAL_PLACE_NAME = 'Balmora, Guild of Mages';
const SYNTHETIC_TILE = Buffer.from(
  'UklGRh4AAABXRUJQVlA4TBEAAAAvB8ABAAfQvK5Vqv+BiOh/AAA=',
  'base64',
);

const locationsFixture = {
  schemaVersion: 1,
  datasetId: DATASET_ID,
  snapshotId: SNAPSHOT_ID,
  places: [
    {
      id: PLACE_ID,
      regionId: 'tr-mainland',
      type: 'landmark',
      mapPosition: [12_288, -217_088],
      exteriorCell: [1, -27],
      mimCategory: null,
      minZoom: 2,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'TR_Mainland.esm',
          recordId: 'CELL exterior 1,-27',
          mimIndex: null,
        },
      ],
    },
  ],
};

const localeFixture = {
  schemaVersion: 1,
  datasetId: DATASET_ID,
  snapshotId: SNAPSHOT_ID,
  locale: 'en',
  places: [{ placeId: PLACE_ID, name: PLACE_NAME, aliases: [] }],
};

const originalLocationsFixture = {
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
      minZoom: 4,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'Morrowind.esm',
          recordId: ORIGINAL_PLACE_NAME,
          mimIndex: null,
        },
      ],
    },
  ],
};

const originalLocaleFixture = {
  schemaVersion: 1,
  datasetId: ORIGINAL_DATASET_ID,
  snapshotId: ORIGINAL_SNAPSHOT_ID,
  locale: 'en',
  places: [{ placeId: ORIGINAL_PLACE_ID, name: ORIGINAL_PLACE_NAME, aliases: [] }],
};

interface DirectUrlFixture {
  readonly label: string;
  readonly url: string;
  readonly heading: string;
  readonly regionName: string;
  readonly placeName: string;
  readonly view: readonly [x: number, y: number, zoom: number];
}

const directUrlFixtures: readonly DirectUrlFixture[] = [
  {
    label: 'Poison Song',
    url:
      `/?dataset=${DATASET_ID}&region=tr-mainland&x=16384&y=-204800&z=4.5&place=${PLACE_ID}`,
    heading: 'Tamriel Rebuilt 26.08 — Poison Song',
    regionName: 'TR Mainland',
    placeName: PLACE_NAME,
    view: [16_384, -204_800, 4.5],
  },
  {
    label: 'Original GOTY HD',
    url:
      `/?dataset=${ORIGINAL_DATASET_ID}&region=vvardenfell&x=-20000&y=-15000&z=5.25&place=${ORIGINAL_PLACE_ID}`,
    heading: 'Morrowind Game of the Year — HD',
    regionName: 'Vvardenfell',
    placeName: ORIGINAL_PLACE_NAME,
    view: [-20_000, -15_000, 5.25],
  },
];

interface RouteOptions {
  readonly syntheticPayloads?: boolean;
  readonly failMapAssets?: boolean;
  readonly failTiles?: boolean;
  readonly blockOriginalManifest?: boolean;
}

interface NetworkProbe {
  readonly externalRequests: string[];
  readonly localFailures: string[];
  readonly mapAssetRequests: string[];
  readonly tileRequests: string[];
  readonly restoreMapAssets: () => void;
  readonly restoreTiles: () => void;
}

function isAppUrl(url: URL): boolean {
  return url.hostname === '127.0.0.1' && url.port === '4173';
}

function syntheticCatalog(pathname: string): {
  readonly locations: typeof locationsFixture | typeof originalLocationsFixture;
  readonly locale: typeof localeFixture | typeof originalLocaleFixture;
} | null {
  if (pathname.includes(`/datasets/generated/${DATASET_ID}/catalogs/`)) {
    return { locations: locationsFixture, locale: localeFixture };
  }
  if (pathname.includes(`/datasets/generated/${ORIGINAL_DATASET_ID}/catalogs/`)) {
    return { locations: originalLocationsFixture, locale: originalLocaleFixture };
  }
  return null;
}

async function installOfflineRoutes(
  page: Page,
  {
    syntheticPayloads = true,
    failMapAssets = false,
    failTiles = false,
    blockOriginalManifest = false,
  }: RouteOptions = {},
): Promise<NetworkProbe> {
  let mapAssetsUnavailable = failMapAssets;
  let tilesUnavailable = failTiles;
  const probe: NetworkProbe = {
    externalRequests: [],
    localFailures: [],
    mapAssetRequests: [],
    tileRequests: [],
    restoreMapAssets: () => {
      mapAssetsUnavailable = false;
    },
    restoreTiles: () => {
      tilesUnavailable = false;
    },
  };

  page.on('response', (response) => {
    const url = new URL(response.url());
    if (isAppUrl(url) && response.status() >= 400) {
      probe.localFailures.push(`${response.status()} ${url.pathname}`);
    }
  });
  page.on('websocket', (socket) => {
    const url = new URL(socket.url());
    if (!isAppUrl(url)) {
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
    if (!isAppUrl(url)) {
      probe.externalRequests.push(`${request.method()} ${request.url()}`);
      await route.abort('blockedbyclient');
      return;
    }

    const { pathname } = url;
    if (
      blockOriginalManifest &&
      pathname === `/datasets/manifests/${ORIGINAL_DATASET_ID}.json`
    ) {
      const response = await route.fetch();
      const manifest = (await response.json()) as {
        readiness: {
          status: string;
          blockers: string[];
        };
        localization: {
          locales: Array<{ status: string; coverage: number }>;
        };
        regions: Array<{ status: string }>;
        artifacts: {
          locations: unknown;
          locales: Array<{ artifact: unknown }>;
          tiles: unknown;
          catalogAudit: unknown;
        };
        provenance: { kind: string };
      };
      manifest.readiness.status = 'blocked';
      manifest.readiness.blockers = ['Synthetic unpublished-dataset acceptance fixture.'];
      manifest.localization.locales[0]!.status = 'planned';
      manifest.localization.locales[0]!.coverage = 0;
      for (const region of manifest.regions) {
        if (region.status === 'available') {
          region.status = 'blocked';
        }
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
    const isMapAssets =
      pathname.startsWith('/datasets/metadata/') && pathname.endsWith('/map-assets.json');
    const isTile =
      pathname.startsWith('/datasets/generated/') &&
      pathname.includes('/tiles/') &&
      pathname.endsWith('.webp');

    if (isMapAssets) {
      probe.mapAssetRequests.push(pathname);
      if (mapAssetsUnavailable) {
        await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
        return;
      }
    }
    if (isTile) {
      probe.tileRequests.push(pathname);
      if (tilesUnavailable) {
        await route.fulfill({ status: 503, contentType: 'text/plain', body: 'unavailable' });
        return;
      }
      if (syntheticPayloads) {
        await route.fulfill({ status: 200, contentType: 'image/webp', body: SYNTHETIC_TILE });
        return;
      }
    }
    if (syntheticPayloads && isLocations) {
      await route.fulfill({ json: catalog.locations });
      return;
    }
    if (syntheticPayloads && isLocale) {
      await route.fulfill({ json: catalog.locale });
      return;
    }

    await route.continue();
  });

  return probe;
}

async function openPoisonSong(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: POISON_CARD_NAME }).click();
  await expect(
    page.getByRole('heading', { name: 'Tamriel Rebuilt 26.08 — Poison Song' }),
  ).toBeVisible();
  await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeVisible();
}

async function openOriginal(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: ORIGINAL_CARD_NAME }).click();
  await expect(page.getByRole('heading', { name: 'Morrowind Game of the Year — HD' })).toBeVisible();
  await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeVisible();
}

async function searchAndOpenPlace(page: Page): Promise<void> {
  await page.getByRole('searchbox', { name: 'Find a place' }).fill(PLACE_NAME);
  await page.getByRole('button', { name: new RegExp(`^${PLACE_NAME}`) }).click();
  await expect(page.getByRole('heading', { name: PLACE_NAME })).toBeVisible();
}

async function hasPaintedBasemap(page: Page): Promise<boolean> {
  const canvases = page.locator('.dataset-basemap-layer canvas');
  const count = await canvases.count();
  for (let index = 0; index < count; index += 1) {
    const painted = await canvases.nth(index).evaluate((element) => {
      const canvas = element as HTMLCanvasElement;
      const context = canvas.getContext('2d');
      if (!context || canvas.width === 0 || canvas.height === 0) {
        return false;
      }
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      for (let offset = 3; offset < pixels.length; offset += 64) {
        if ((pixels[offset] ?? 0) > 0) {
          return true;
        }
      }
      return false;
    });
    if (painted) {
      return true;
    }
  }
  return false;
}

async function cursorCoordinatesAtMapCenter(page: Page): Promise<string> {
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  const box = await map.boundingBox();
  if (!box) {
    throw new Error('Map canvas has no visible bounding box');
  }
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x + 1, y);
  await page.mouse.move(x, y);
  const values = await page.getByLabel('Map status').locator('strong').allTextContents();
  return values.slice(0, 2).join(',');
}

function relativePageUrl(page: Page): string {
  const url = new URL(page.url());
  return `${url.pathname}${url.search}${url.hash}`;
}

async function historyLength(page: Page): Promise<number> {
  return page.evaluate(() => window.history.length);
}

async function expectRelativeUrl(page: Page, expected: string): Promise<void> {
  await expect.poll(() => relativePageUrl(page)).toBe(expected);
}

async function expectMapView(
  page: Page,
  [expectedX, expectedY, expectedZoom]: DirectUrlFixture['view'],
): Promise<void> {
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  await expect(map).toBeVisible();
  await expect.poll(async () => {
    const view = await map.evaluate((element) => {
      const target = element as HTMLElement;
      return {
        x: Number(target.dataset.viewX),
        y: Number(target.dataset.viewY),
        zoom: Number(target.dataset.viewZ),
      };
    });
    return [
      Number.isFinite(view.x) && Math.abs(view.x - expectedX) <= 1,
      Number.isFinite(view.y) && Math.abs(view.y - expectedY) <= 1,
      Number.isFinite(view.zoom) && Math.abs(view.zoom - expectedZoom) <= 0.01,
    ];
  }).toEqual([true, true, true]);
}

async function expectDirectUrlState(page: Page, fixture: DirectUrlFixture): Promise<void> {
  await expect(page.getByRole('heading', { name: fixture.heading })).toBeVisible();
  await expect(
    page.getByRole('button', { name: fixture.regionName, exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('heading', { name: fixture.placeName, exact: true })).toBeVisible();
  await expectMapView(page, fixture.view);
  await expectRelativeUrl(page, fixture.url);
}

for (const fixture of directUrlFixtures) {
  test(`opens and reloads a canonical direct URL for ${fixture.label}`, async ({ page }) => {
    const probe = await installOfflineRoutes(page);

    await page.goto(fixture.url);
    await expectDirectUrlState(page, fixture);

    await page.reload();
    await expectDirectUrlState(page, fixture);

    expect(probe.externalRequests).toEqual([]);
    expect(probe.localFailures).toEqual([]);
  });
}

test('canonicalizes an unknown dataset to landing while preserving unrelated URL state', async ({ page }) => {
  const probe = await installOfflineRoutes(page);

  await page.goto(
    '/?theme=sepia&dataset=retired-map&region=vvardenfell&x=1&y=2&z=3&place=stale#ledger',
  );

  await expect(page.getByRole('heading', { name: 'Choose a world' })).toBeVisible();
  await expectRelativeUrl(page, '/?theme=sepia#ledger');
  expect(probe.externalRequests).toEqual([]);
});

test('canonicalizes invalid region, view and cross-dataset place without crashing', async ({ page }) => {
  const probe = await installOfflineRoutes(page);

  await page.goto(
    `/?theme=sepia&dataset=${ORIGINAL_DATASET_ID}&region=unknown&x=123&y=NaN&place=${PLACE_ID}`,
  );

  await expect(page.getByRole('heading', { name: 'Morrowind Game of the Year — HD' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'All', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeVisible();
  await expect(page.getByRole('heading', { name: PLACE_NAME, exact: true })).toHaveCount(0);
  const canonicalUrl = new URL(page.url());
  expect(canonicalUrl.searchParams.get('theme')).toBe('sepia');
  expect(canonicalUrl.searchParams.get('dataset')).toBe(ORIGINAL_DATASET_ID);
  expect(canonicalUrl.searchParams.get('region')).toBe('all');
  expect(canonicalUrl.searchParams.has('place')).toBe(false);
  expect(canonicalUrl.searchParams.get('x')).not.toBe('123');
  expect(Number.isFinite(Number(canonicalUrl.searchParams.get('x')))).toBe(true);
  expect(Number.isFinite(Number(canonicalUrl.searchParams.get('y')))).toBe(true);
  expect(Number.isFinite(Number(canonicalUrl.searchParams.get('z')))).toBe(true);
  const canonicalPath = relativePageUrl(page);
  await page.reload();
  await expectRelativeUrl(page, canonicalPath);
  expect(probe.externalRequests).toEqual([]);
});

test('drops a cross-dataset place while retaining a valid region and camera', async ({ page }) => {
  const probe = await installOfflineRoutes(page);
  const url =
    `/?dataset=${ORIGINAL_DATASET_ID}&region=vvardenfell&x=-20000&y=-15000&z=5.25&place=${PLACE_ID}`;
  const canonicalUrl =
    `/?dataset=${ORIGINAL_DATASET_ID}&region=vvardenfell&x=-20000&y=-15000&z=5.25`;

  await page.goto(url);

  await expect(page.getByRole('heading', { name: 'Morrowind Game of the Year — HD' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Vvardenfell', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByRole('heading', { name: PLACE_NAME, exact: true })).toHaveCount(0);
  await expectMapView(page, [-20_000, -15_000, 5.25]);
  await expectRelativeUrl(page, canonicalUrl);
  expect(probe.externalRequests).toEqual([]);
});

test('uses push history for semantic states and replace history for camera movement', async ({ page }) => {
  const probe = await installOfflineRoutes(page);
  await page.goto('/');
  const landingHistoryLength = await historyLength(page);

  const poisonCard = page.getByRole('button', { name: POISON_CARD_NAME });
  await poisonCard.click();
  await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeVisible();
  await expect.poll(() => historyLength(page)).toBe(landingHistoryLength + 1);

  const mainland = page.getByRole('button', { name: 'TR Mainland', exact: true });
  await mainland.click();
  await expect(mainland).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => historyLength(page)).toBe(landingHistoryLength + 2);

  await searchAndOpenPlace(page);
  await expect.poll(() => historyLength(page)).toBe(landingHistoryLength + 3);
  const cameraHistoryLength = await historyLength(page);
  const cameraUrlBefore = relativePageUrl(page);
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  const xBeforePan = Number(await map.getAttribute('data-view-x'));

  await page.getByRole('button', { name: 'Zoom in' }).click();
  await page.getByRole('button', { name: 'Zoom in' }).click();
  await map.focus();
  await map.press('ArrowRight');
  await expect.poll(async () => Number(await map.getAttribute('data-view-x'))).not.toBe(xBeforePan);
  await expect.poll(() => relativePageUrl(page)).not.toBe(cameraUrlBefore);
  expect(await historyLength(page)).toBe(cameraHistoryLength);
  const finalPlaceUrl = relativePageUrl(page);

  await page.goBack();
  await expect(mainland).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('heading', { name: PLACE_NAME, exact: true })).toHaveCount(0);
  expect(new URL(page.url()).searchParams.has('place')).toBe(false);

  await page.goBack();
  await expect(page.getByRole('button', { name: 'All', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );

  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Choose a world' })).toBeVisible();
  await expect(poisonCard).toBeFocused();

  await page.goForward();
  await expect(page.getByRole('button', { name: 'All', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.goForward();
  await expect(page.getByRole('button', { name: 'TR Mainland', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.goForward();
  await expect(page.getByRole('heading', { name: PLACE_NAME, exact: true })).toBeVisible();
  await expectRelativeUrl(page, finalPlaceUrl);
  expect(await historyLength(page)).toBe(cameraHistoryLength);
  expect(probe.externalRequests).toEqual([]);
});

test('offline V4 workflow persists progress, notes and personal markers', async ({ page }) => {
  const probe = await installOfflineRoutes(page);
  await openPoisonSong(page);

  await expect.poll(() => probe.mapAssetRequests.length).toBeGreaterThan(0);
  await expect.poll(() => probe.tileRequests.length).toBeGreaterThan(0);
  await expect.poll(() => hasPaintedBasemap(page)).toBe(true);
  expect(probe.mapAssetRequests).toContain(
    `/datasets/metadata/${DATASET_ID}/${V4_INVENTORY}/map-assets.json`,
  );
  expect(probe.tileRequests.every((path) => path.includes(V4_INVENTORY))).toBe(true);

  await searchAndOpenPlace(page);
  const progress = page.getByLabel('Place progress');
  const activeStatus = progress.getByRole('button', { name: 'Active' });
  await activeStatus.click();
  await expect(activeStatus).toHaveAttribute('aria-pressed', 'true');
  await progress.getByRole('textbox', { name: 'Personal note' }).fill('Return after sunset.');
  await progress.getByRole('button', { name: 'Save note' }).click();
  await expect(progress.getByRole('status')).toHaveText('Saved.');

  const zoomValue = page.getByLabel('Map status').locator('.statusbar-zoom strong');
  const zoomBefore = Number(await zoomValue.innerText());
  await page.getByRole('button', { name: 'Zoom in' }).click();
  await expect.poll(async () => Number(await zoomValue.innerText())).toBeGreaterThan(zoomBefore);
  await page.getByRole('button', { name: 'Close place card' }).click();

  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  const coordinatesBeforePan = await cursorCoordinatesAtMapCenter(page);
  await map.focus();
  await map.press('ArrowRight');
  await expect.poll(() => cursorCoordinatesAtMapCenter(page)).not.toBe(coordinatesBeforePan);

  await page.getByRole('button', { name: 'Add personal marker' }).click();
  await map.focus();
  await map.press('Enter');
  const markerEditor = page.getByLabel('Custom marker');
  await markerEditor.getByRole('textbox', { name: 'Marker name' }).fill('Field note pin');
  await markerEditor.getByRole('textbox', { name: 'Personal note' }).fill('Hidden cache.');
  await markerEditor.getByRole('button', { name: 'Save marker' }).click();
  await expect(markerEditor.getByRole('status')).toHaveText('Saved.');
  await expect(
    page.getByRole('region', { name: 'Personal markers' }).getByRole('button', {
      name: /^Field note pin/,
    }),
  ).toBeVisible();

  await page.reload();
  await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeVisible();
  await searchAndOpenPlace(page);
  const reloadedProgress = page.getByLabel('Place progress');
  await expect(reloadedProgress.getByRole('button', { name: 'Active' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(reloadedProgress.getByRole('textbox', { name: 'Personal note' })).toHaveValue(
    'Return after sunset.',
  );
  await page.getByRole('button', { name: 'Close place card' }).click();
  await expect.poll(() => new URL(page.url()).searchParams.has('place')).toBe(false);
  const persistedMarker = page
    .getByRole('region', { name: 'Personal markers' })
    .getByRole('button', { name: /^Field note pin/ });
  await expect(persistedMarker).toBeVisible();
  await persistedMarker.click();
  const reloadedMarkerEditor = page.getByLabel('Custom marker');
  await expect(reloadedMarkerEditor.getByRole('textbox', { name: 'Marker name' })).toHaveValue(
    'Field note pin',
  );
  await expect(reloadedMarkerEditor.getByRole('textbox', { name: 'Personal note' })).toHaveValue(
    'Hidden cache.',
  );

  expect(probe.externalRequests).toEqual([]);
  expect(probe.localFailures).toEqual([]);
});

test('recovers from a dataset asset error through Retry', async ({ page }) => {
  const fixture = directUrlFixtures[0]!;
  const probe = await installOfflineRoutes(page, { failMapAssets: true });
  await page.goto(fixture.url);
  const historyLengthBeforeRetry = await historyLength(page);

  const alert = page.getByRole('alert');
  await expect(alert).toBeVisible();
  await expect(alert).toContainText('could not be opened');
  await expectRelativeUrl(page, fixture.url);
  probe.restoreMapAssets();
  await alert.getByRole('button', { name: 'Retry' }).click();
  await expectDirectUrlState(page, fixture);
  await expect.poll(() => probe.mapAssetRequests.length).toBeGreaterThan(1);
  expect(await historyLength(page)).toBe(historyLengthBeforeRetry);
  expect(probe.externalRequests).toEqual([]);
});

test('reports a tile failure and refreshes the source through Retry', async ({ page }) => {
  const probe = await installOfflineRoutes(page, { failTiles: true });
  await openPoisonSong(page);

  const tileAlert = page.getByRole('alert').filter({ hasText: 'Map tiles failed to load' });
  await expect(tileAlert).toBeVisible();
  const failedRequestCount = probe.tileRequests.length;
  probe.restoreTiles();
  await tileAlert.getByRole('button', { name: 'Retry' }).click();
  await expect(tileAlert).toBeHidden();
  await expect.poll(() => probe.tileRequests.length).toBeGreaterThan(failedRequestCount);
  await expect.poll(() => hasPaintedBasemap(page)).toBe(true);
  expect(probe.externalRequests).toEqual([]);
});

test('shows a non-retryable missing state for an unpublished dataset', async ({ page }) => {
  const probe = await installOfflineRoutes(page, {
    syntheticPayloads: false,
    blockOriginalManifest: true,
  });
  await page.goto('/');
  await page.getByRole('button', { name: ORIGINAL_CARD_NAME }).click();

  const status = page.getByRole('status');
  await expect(status).toContainText('not been published locally');
  await expect(status.getByRole('button', { name: 'Retry' })).toHaveCount(0);
  expect(probe.externalRequests).toEqual([]);
});

test('@prepared renders the complete local V4 catalog and tile pyramid', async ({ page }) => {
  test.skip(
    process.env.MORROWIND_ACCEPTANCE_PREPARED !== '1',
    'Run pnpm test:acceptance:prepared when the ignored V4 payload is available.',
  );
  const preparedRoot = join(
    process.cwd(),
    'apps/web/public/datasets/generated',
    DATASET_ID,
    V4_INVENTORY,
  );
  expect(existsSync(join(preparedRoot, 'tiles'))).toBe(true);

  const probe = await installOfflineRoutes(page, { syntheticPayloads: false });
  await openPoisonSong(page);
  await expect(page.getByText('4085 places')).toBeVisible();
  await page.getByRole('searchbox', { name: 'Find a place' }).fill(PLACE_NAME);
  await expect(page.getByRole('button', { name: new RegExp(`^${PLACE_NAME}`) })).toBeVisible();
  await expect.poll(() => probe.tileRequests.length).toBeGreaterThan(0);
  await expect.poll(() => hasPaintedBasemap(page)).toBe(true);
  expect(probe.tileRequests.every((path) => path.includes(V4_INVENTORY))).toBe(true);
  expect(probe.externalRequests).toEqual([]);
  expect(probe.localFailures).toEqual([]);
});

test('@prepared renders and searches the complete local Original HD dataset', async ({ page }) => {
  test.skip(
    process.env.MORROWIND_ACCEPTANCE_PREPARED !== '1',
    'Run pnpm test:acceptance:prepared when the ignored Original HD payload is available.',
  );
  const generatedRoot = join(
    process.cwd(),
    'apps/web/public/datasets/generated',
    ORIGINAL_DATASET_ID,
  );
  expect(existsSync(join(generatedRoot, ORIGINAL_INVENTORY, 'tiles'))).toBe(true);
  expect(
    existsSync(
      join(
        generatedRoot,
        'catalogs',
        ORIGINAL_CATALOG_INVENTORY,
        'locations.json',
      ),
    ),
  ).toBe(true);

  const probe = await installOfflineRoutes(page, { syntheticPayloads: false });
  await openOriginal(page);
  await expect(page.getByText('1036 places')).toBeVisible();
  await page.getByRole('searchbox', { name: 'Find a place' }).fill(ORIGINAL_PLACE_NAME);
  await page.getByRole('button', { name: new RegExp(`^${ORIGINAL_PLACE_NAME}`) }).click();
  await expect(page.getByRole('heading', { name: ORIGINAL_PLACE_NAME })).toBeVisible();
  await expect.poll(() => probe.tileRequests.length).toBeGreaterThan(0);
  await expect.poll(() => hasPaintedBasemap(page)).toBe(true);

  const progress = page.getByLabel('Place progress');
  const visitedStatus = progress.getByRole('button', { name: 'Visited', exact: true });
  await visitedStatus.click();
  await expect(visitedStatus).toHaveAttribute('aria-pressed', 'true');
  await progress.getByRole('textbox', { name: 'Personal note' }).fill('Original route cleared.');
  await progress.getByRole('button', { name: 'Save note' }).click();
  await expect(progress.getByRole('status')).toHaveText('Saved.');

  const zoomValue = page.getByLabel('Map status').locator('.statusbar-zoom strong');
  const zoomBefore = Number(await zoomValue.innerText());
  await page.getByRole('button', { name: 'Zoom in' }).click();
  await expect.poll(async () => Number(await zoomValue.innerText())).toBeGreaterThan(zoomBefore);
  await page.getByRole('button', { name: 'Close place card' }).click();

  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  const coordinatesBeforePan = await cursorCoordinatesAtMapCenter(page);
  await map.focus();
  await map.press('ArrowRight');
  await expect.poll(() => cursorCoordinatesAtMapCenter(page)).not.toBe(coordinatesBeforePan);

  await page.getByRole('button', { name: 'Add personal marker' }).click();
  await map.focus();
  await map.press('Enter');
  const markerEditor = page.getByLabel('Custom marker');
  await markerEditor.getByRole('textbox', { name: 'Marker name' }).fill('Original field pin');
  await markerEditor.getByRole('textbox', { name: 'Personal note' }).fill('Base-game only.');
  await markerEditor.getByRole('button', { name: 'Save marker' }).click();
  await expect(markerEditor.getByRole('status')).toHaveText('Saved.');

  await page.reload();
  await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeVisible();
  await page.getByRole('searchbox', { name: 'Find a place' }).fill(ORIGINAL_PLACE_NAME);
  await page.getByRole('button', { name: new RegExp(`^${ORIGINAL_PLACE_NAME}`) }).click();
  const reloadedProgress = page.getByLabel('Place progress');
  await expect(
    reloadedProgress.getByRole('button', { name: 'Visited', exact: true }),
  ).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(reloadedProgress.getByRole('textbox', { name: 'Personal note' })).toHaveValue(
    'Original route cleared.',
  );
  await expect(
    page
      .getByRole('region', { name: 'Personal markers' })
      .getByRole('button', { name: /^Original field pin/ }),
  ).toBeVisible();

  expect(probe.tileRequests.every((path) => path.includes(ORIGINAL_INVENTORY))).toBe(true);
  expect(probe.externalRequests).toEqual([]);
  expect(probe.localFailures).toEqual([]);
});
