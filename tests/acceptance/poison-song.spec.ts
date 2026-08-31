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
    const isCatalog = pathname.includes(`/datasets/generated/${DATASET_ID}/catalogs/`);
    const isLocations = isCatalog && pathname.endsWith('/locations.json');
    const isLocale = isCatalog && pathname.endsWith('/locales/en.json');
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
      await route.fulfill({ json: locationsFixture });
      return;
    }
    if (syntheticPayloads && isLocale) {
      await route.fulfill({ json: localeFixture });
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
  await page.getByRole('button', { name: POISON_CARD_NAME }).click();
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
  const probe = await installOfflineRoutes(page, { failMapAssets: true });
  await page.goto('/');
  await page.getByRole('button', { name: POISON_CARD_NAME }).click();

  const alert = page.getByRole('alert');
  await expect(alert).toBeVisible();
  await expect(alert).toContainText('could not be opened');
  probe.restoreMapAssets();
  await alert.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeVisible();
  await expect.poll(() => probe.mapAssetRequests.length).toBeGreaterThan(1);
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
  await page.getByRole('button', { name: ORIGINAL_CARD_NAME }).click();
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
