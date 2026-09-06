import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import {
  ANALYTICS_CONSENT_STORAGE_KEY,
  ANALYTICS_NOTICE_VERSION,
} from '../../apps/web/src/analytics/googleAnalytics';

import {
  loadTrCandidateFromEnvironment,
  loadTrCandidatePreparedAssets,
} from './tr-candidate';

const DATASET_ID = 'poison-song-26.08';
const SNAPSHOT_ID = 'tr:poison-song-26.08:6964517551e0fcb0';
const V4_INVENTORY =
  '93758a5e645013821d99a7989d69f3e4aa39373e2c5cb4b97873da421c5052b2';
const PLACE_ID = 'poison-song-26.08.place-014cd9c0ca05af58dc14';
const PLACE_NAME = 'Pneuma Grove';
const POISON_CAVE_ID = 'poison-song-26.08.place-ashfall-cavern';
const POISON_CAVE_NAME = 'Ashfall Cavern';
const POISON_GUILD_ID = 'poison-song-26.08.place-andothren-guildhall';
const POISON_GUILD_NAME = 'Andothren Guildhall';
const POISON_SHOP_ID = 'poison-song-26.08.place-vvardenfell-tradehouse';
const POISON_SHOP_NAME = 'Vvardenfell Tradehouse';
const POISON_CARD_NAME = 'Open map: Tamriel Rebuilt — Poison Song';
const OLD_EBONHEART_ID = 'poison-song-26.08.place-old-ebonheart-fixture';
const OLD_EBONHEART_NAME = 'Old Ebonheart';
const ORIGINAL_CARD_NAME = 'Open map: Morrowind Game of the Year';
const ORIGINAL_DATASET_ID = 'original-goty-hd';
const ORIGINAL_INVENTORY =
  'aade4b98c2fb905fd2617871345292a638e3a4a25c6d036db7a3cc18bb2dd014';
const ORIGINAL_CATALOG_INVENTORY =
  '6ea0c0a0272f6c8456a947c9dc36bac5116a9cd524cc4b351fdad867cf3e0df1';
const ORIGINAL_SNAPSHOT_ID = 'original:goty:8b2690c0ce1c954e';
const ORIGINAL_PLACE_ID = 'original-goty-hd.place-18680400d24ed6f70770';
const ORIGINAL_PLACE_NAME = 'Balmora, Guild of Mages';
const ORIGINAL_SETTLEMENT_ID = 'original-goty-hd.place-seyda-neen-fixture';
const ORIGINAL_SETTLEMENT_NAME = 'Seyda Neen';
const ORIGINAL_TEMPLE_ID = 'original-goty-hd.place-balmora-temple-fixture';
const ORIGINAL_TEMPLE_NAME = 'Balmora Temple';
const ORIGINAL_CAVE_ID = 'original-goty-hd.place-solstheim-ice-cave';
const ORIGINAL_CAVE_NAME = 'Solstheim Ice Cave';
const BAL_FELL_ID = 'original-goty-hd.place-bal-fell-fixture';
const BAL_FELL_NAME = 'Bal Fell';
const SYNTHETIC_TILE = Buffer.from(
  'UklGRh4AAABXRUJQVlA4TBEAAAAvB8ABAAfQvK5Vqv+BiOh/AAA=',
  'base64',
);
const trCandidate = loadTrCandidateFromEnvironment();
const trCandidatePreparedAssets = trCandidate
  ? loadTrCandidatePreparedAssets(trCandidate)
  : null;

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
      minZoom: 0,
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
    {
      id: POISON_CAVE_ID,
      regionId: 'tr-mainland',
      type: 'cave',
      mapPosition: [12_500, -217_000],
      exteriorCell: [1, -27],
      mimCategory: null,
      minZoom: 0,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'TR_Mainland.esm',
          recordId: POISON_CAVE_NAME,
          mimIndex: null,
        },
      ],
    },
    {
      id: POISON_GUILD_ID,
      regionId: 'tr-mainland',
      type: 'guild',
      mapPosition: [13_000, -216_500],
      exteriorCell: [1, -27],
      mimCategory: null,
      minZoom: 4,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'TR_Mainland.esm',
          recordId: POISON_GUILD_NAME,
          mimIndex: null,
        },
      ],
    },
    {
      id: POISON_SHOP_ID,
      regionId: 'vvardenfell',
      type: 'shop',
      mapPosition: [-22_000, -14_000],
      exteriorCell: [-3, -2],
      mimCategory: null,
      minZoom: 2,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'Morrowind.esm',
          recordId: POISON_SHOP_NAME,
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
  places: [
    { placeId: PLACE_ID, name: PLACE_NAME, aliases: [] },
    { placeId: POISON_CAVE_ID, name: POISON_CAVE_NAME, aliases: ['Ashfall'] },
    { placeId: POISON_GUILD_ID, name: POISON_GUILD_NAME, aliases: [] },
    { placeId: POISON_SHOP_ID, name: POISON_SHOP_NAME, aliases: [] },
  ],
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
      minZoom: 0,
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
    {
      id: ORIGINAL_SETTLEMENT_ID,
      regionId: 'vvardenfell',
      type: 'settlement',
      mapPosition: [-23_000, -16_000],
      exteriorCell: [-3, -2],
      mimCategory: null,
      minZoom: 0,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'Morrowind.esm',
          recordId: ORIGINAL_SETTLEMENT_NAME,
          mimIndex: null,
        },
      ],
    },
    {
      id: ORIGINAL_TEMPLE_ID,
      regionId: 'vvardenfell',
      type: 'temple',
      mapPosition: [-21_000, -14_500],
      exteriorCell: [-3, -2],
      mimCategory: null,
      minZoom: 2,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'Morrowind.esm',
          recordId: ORIGINAL_TEMPLE_NAME,
          mimIndex: null,
        },
      ],
    },
    {
      id: ORIGINAL_CAVE_ID,
      regionId: 'solstheim',
      type: 'cave',
      mapPosition: [-165_000, 140_000],
      exteriorCell: [-21, 17],
      mimCategory: null,
      minZoom: 3,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'Bloodmoon.esm',
          recordId: ORIGINAL_CAVE_NAME,
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
  places: [
    { placeId: ORIGINAL_PLACE_ID, name: ORIGINAL_PLACE_NAME, aliases: [] },
    { placeId: ORIGINAL_SETTLEMENT_ID, name: ORIGINAL_SETTLEMENT_NAME, aliases: [] },
    { placeId: ORIGINAL_TEMPLE_ID, name: ORIGINAL_TEMPLE_NAME, aliases: [] },
    { placeId: ORIGINAL_CAVE_ID, name: ORIGINAL_CAVE_NAME, aliases: [] },
  ],
};

const trMainlandLocationsFixture = {
  ...locationsFixture,
  places: [
    ...locationsFixture.places,
    {
      id: OLD_EBONHEART_ID,
      regionId: 'tr-mainland',
      type: 'settlement',
      mapPosition: [53_248, -151_552],
      exteriorCell: [6, -19],
      mimCategory: null,
      minZoom: 0,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'TR_Mainland.esm',
          recordId: OLD_EBONHEART_NAME,
          mimIndex: null,
        },
      ],
    },
  ],
};

const trMainlandLocaleFixture = {
  ...localeFixture,
  places: [
    ...localeFixture.places,
    { placeId: OLD_EBONHEART_ID, name: OLD_EBONHEART_NAME, aliases: [] },
  ],
};

const ORIGINAL_PAGINATION_PREFIX_COUNT = 240;
const originalPaginationLocations = Array.from(
  { length: ORIGINAL_PAGINATION_PREFIX_COUNT },
  (_, index) => {
    const ordinal = String(index + 1).padStart(3, '0');
    return {
      id: `original-goty-hd.place-pagination-${ordinal}`,
      regionId: 'vvardenfell',
      type: 'landmark',
      mapPosition: [-22_000 + (index % 9) * 32, -15_000 + Math.floor(index / 9) * 32],
      exteriorCell: [-3, -2],
      mimCategory: null,
      minZoom: 0,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'Morrowind.esm',
          recordId: `Ald Fixture ${ordinal}`,
          mimIndex: null,
        },
      ],
    };
  },
);

const originalPaginationLocale = Array.from(
  { length: ORIGINAL_PAGINATION_PREFIX_COUNT },
  (_, index) => {
    const ordinal = String(index + 1).padStart(3, '0');
    return {
      placeId: `original-goty-hd.place-pagination-${ordinal}`,
      name: `Ald Fixture ${ordinal}`,
      aliases: [],
    };
  },
);

const originalPaginationLocationsFixture = {
  ...originalLocationsFixture,
  places: [
    ...originalPaginationLocations,
    {
      id: BAL_FELL_ID,
      regionId: 'vvardenfell',
      type: 'landmark',
      mapPosition: [-21_700, -14_700],
      exteriorCell: [-3, -2],
      mimCategory: null,
      minZoom: 0,
      entrances: [],
      sources: [
        {
          kind: 'esm',
          plugin: 'Morrowind.esm',
          recordId: BAL_FELL_NAME,
          mimIndex: null,
        },
      ],
    },
  ],
};

const originalPaginationLocaleFixture = {
  ...originalLocaleFixture,
  places: [
    ...originalPaginationLocale,
    { placeId: BAL_FELL_ID, name: BAL_FELL_NAME, aliases: [] },
  ],
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
    heading: 'Tamriel Rebuilt — Poison Song',
    regionName: 'TR Mainland',
    placeName: PLACE_NAME,
    view: [16_384, -204_800, 4.5],
  },
  {
    label: 'Original GOTY HD',
    url:
      `/?dataset=${ORIGINAL_DATASET_ID}&region=vvardenfell&x=-20000&y=-15000&z=5.25&place=${ORIGINAL_PLACE_ID}`,
    heading: 'Morrowind Game of the Year',
    regionName: 'Vvardenfell',
    placeName: ORIGINAL_PLACE_NAME,
    view: [-20_000, -15_000, 5.25],
  },
];

interface LandingDefaultViewFixture {
  readonly label: string;
  readonly cardName: string;
  readonly heading: string;
  readonly view: readonly [x: number, y: number, zoom: number];
}

const landingDefaultViewFixtures: readonly LandingDefaultViewFixture[] = [
  {
    label: 'Poison Song',
    cardName: POISON_CARD_NAME,
    heading: 'Tamriel Rebuilt — Poison Song',
    view: [90_112, -98_304, 2],
  },
  {
    label: 'Original GOTY HD',
    cardName: ORIGINAL_CARD_NAME,
    heading: 'Morrowind Game of the Year',
    view: [-16_384, 40_960, 2],
  },
];

test.beforeEach(async ({ page }) => {
  await page.addInitScript(({ storageKey, noticeVersion }) => {
    window.localStorage.setItem(storageKey, JSON.stringify({
      choice: 'denied',
      decidedAt: '2026-09-02T00:00:00.000Z',
      noticeVersion,
    }));
  }, {
    storageKey: ANALYTICS_CONSENT_STORAGE_KEY,
    noticeVersion: ANALYTICS_NOTICE_VERSION,
  });
});

const TR_MAINLAND_DEFAULT_VIEW = [53_248, -151_552, 4] as const;

const preparedDirectUrlFixtures: readonly DirectUrlFixture[] = trCandidatePreparedAssets
  ? [
      {
        label: trCandidate!.manifest.title.en,
        url:
          `/?dataset=${trCandidate!.manifest.datasetId}` +
          `&region=${trCandidatePreparedAssets.selectedRegionId}` +
          `&x=${trCandidatePreparedAssets.selectedPlace.mapPosition[0]}` +
          `&y=${trCandidatePreparedAssets.selectedPlace.mapPosition[1]}` +
          `&z=${trCandidatePreparedAssets.zoom}` +
          `&place=${trCandidatePreparedAssets.selectedPlace.id}`,
        heading: trCandidate!.manifest.title.en,
        regionName: trCandidatePreparedAssets.selectedRegionName,
        placeName: trCandidatePreparedAssets.selectedPlaceName,
        view: [
          trCandidatePreparedAssets.selectedPlace.mapPosition[0],
          trCandidatePreparedAssets.selectedPlace.mapPosition[1],
          trCandidatePreparedAssets.zoom,
        ],
      },
      directUrlFixtures[1]!,
    ]
  : directUrlFixtures;

interface FilterAcceptanceFixture {
  readonly label: string;
  readonly url: string;
  readonly heading: string;
  readonly primaryPlaceId: string;
  readonly primaryPlaceName: string;
  readonly queryPlaceId: string;
  readonly queryPlaceName: string;
  readonly availableTypes: readonly string[];
  readonly clickedTypes: readonly [first: string, second: string];
  readonly canonicalTypes: readonly string[];
  readonly unavailableType: string;
  readonly facetRegionName: string;
}

const filterAcceptanceFixtures: readonly FilterAcceptanceFixture[] = [
  {
    label: 'Poison Song',
    url: `/?dataset=${DATASET_ID}&region=all&x=12288&y=-217088&z=6`,
    heading: 'Tamriel Rebuilt — Poison Song',
    primaryPlaceId: PLACE_ID,
    primaryPlaceName: PLACE_NAME,
    queryPlaceId: POISON_CAVE_ID,
    queryPlaceName: POISON_CAVE_NAME,
    availableTypes: ['Landmark', 'Cave', 'Guild', 'Shop'],
    clickedTypes: ['Shop', 'Landmark'],
    canonicalTypes: ['landmark', 'shop'],
    unavailableType: 'Mine',
    facetRegionName: 'TR Mainland',
  },
  {
    label: 'Original GOTY HD',
    url: `/?dataset=${ORIGINAL_DATASET_ID}&region=all&x=-22000&y=-15000&z=6`,
    heading: 'Morrowind Game of the Year',
    primaryPlaceId: ORIGINAL_PLACE_ID,
    primaryPlaceName: ORIGINAL_PLACE_NAME,
    queryPlaceId: ORIGINAL_PLACE_ID,
    queryPlaceName: ORIGINAL_PLACE_NAME,
    availableTypes: ['Settlement', 'Temple', 'Cave', 'Guild'],
    clickedTypes: ['Guild', 'Settlement'],
    canonicalTypes: ['settlement', 'guild'],
    unavailableType: 'Shop',
    facetRegionName: 'Vvardenfell',
  },
];

interface RouteOptions {
  readonly syntheticPayloads?: boolean;
  readonly syntheticCatalogScenario?: 'default' | 'original-pagination' | 'tr-mainland';
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

function syntheticCatalog(
  pathname: string,
  scenario: NonNullable<RouteOptions['syntheticCatalogScenario']>,
) {
  if (pathname.includes(`/datasets/generated/${DATASET_ID}/catalogs/`)) {
    if (scenario === 'tr-mainland') {
      return { locations: trMainlandLocationsFixture, locale: trMainlandLocaleFixture };
    }
    return { locations: locationsFixture, locale: localeFixture };
  }
  if (pathname.includes(`/datasets/generated/${ORIGINAL_DATASET_ID}/catalogs/`)) {
    if (scenario === 'original-pagination') {
      return {
        locations: originalPaginationLocationsFixture,
        locale: originalPaginationLocaleFixture,
      };
    }
    return { locations: originalLocationsFixture, locale: originalLocaleFixture };
  }
  return null;
}

async function installOfflineRoutes(
  page: Page,
  {
    syntheticPayloads = true,
    syntheticCatalogScenario = 'default',
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
    if (trCandidate && pathname === '/datasets/index.json') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: trCandidate.indexJson,
      });
      return;
    }
    if (trCandidate && pathname === trCandidate.manifestUrl) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: trCandidate.manifestJson,
      });
      return;
    }
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
    const catalog = syntheticCatalog(pathname, syntheticCatalogScenario);
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
    page.getByRole('heading', { name: 'Tamriel Rebuilt — Poison Song' }),
  ).toBeVisible();
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

async function currentMapView(page: Page): Promise<{
  readonly x: number;
  readonly y: number;
  readonly zoom: number;
}> {
  return mapCanvas(page).evaluate((element) => {
    const target = element as HTMLElement;
    return {
      x: Number(target.dataset.viewX),
      y: Number(target.dataset.viewY),
      zoom: Number(target.dataset.viewZ),
    };
  });
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
    const view = await currentMapView(page);
    return [
      Number.isFinite(view.x) && Math.abs(view.x - expectedX) <= 1,
      Number.isFinite(view.y) && Math.abs(view.y - expectedY) <= 1,
      Number.isFinite(view.zoom) && Math.abs(view.zoom - expectedZoom) <= 0.01,
    ];
  }).toEqual([true, true, true]);
}

async function expectExactMapView(
  page: Page,
  [expectedX, expectedY, expectedZoom]: LandingDefaultViewFixture['view'],
): Promise<void> {
  const map = mapCanvas(page);
  await expect(map).toBeVisible();
  await expect.poll(async () => {
    const view = await currentMapView(page);
    return [view.x, view.y, view.zoom];
  }).toEqual([expectedX, expectedY, expectedZoom]);
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

function mapCanvas(page: Page) {
  return page.getByLabel('Interactive map in TES3 world coordinates');
}

async function openFilterDrawer(page: Page): Promise<void> {
  const drawer = page.locator('details.place-filter-drawer');
  if (!(await drawer.evaluate((element) => (element as HTMLDetailsElement).open))) {
    await drawer.locator('summary').click();
  }
}

function typeFilterButton(page: Page, label: string) {
  return page
    .locator('fieldset.place-filter-axis--types')
    .getByRole('button', { name: new RegExp(`^${label}(?:\\s|$)`) });
}

function statusFilterButton(page: Page, label: string) {
  return page
    .locator('fieldset.place-filter-axis--statuses')
    .getByRole('button', { name: new RegExp(`^${label}(?:\\s|$)`) });
}

function placeResultByExactName(page: Page, name: string) {
  return page.locator('button.place-result').filter({
    has: page.locator('strong').filter({ hasText: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`) }),
  });
}

async function expectUrlFilters(
  page: Page,
  types: readonly string[],
  statuses: readonly string[],
): Promise<void> {
  await expect.poll(() => {
    const url = new URL(page.url());
    return {
      types: url.searchParams.getAll('type'),
      statuses: url.searchParams.getAll('status'),
    };
  }).toEqual({ types: [...types], statuses: [...statuses] });
}

async function labelPriority(page: Page): Promise<string[]> {
  const value = await mapCanvas(page).getAttribute('data-label-priority');
  return value ? value.split(',').filter(Boolean) : [];
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

for (const fixture of landingDefaultViewFixtures) {
  test(`opens ${fixture.label} from its landing card at the manifest default view`, async ({ page }) => {
    const probe = await installOfflineRoutes(page);
    await page.goto('/');
    const landingUrl = new URL(page.url());
    expect(landingUrl.searchParams.has('x')).toBe(false);
    expect(landingUrl.searchParams.has('y')).toBe(false);
    expect(landingUrl.searchParams.has('z')).toBe(false);

    await page.getByRole('button', { name: fixture.cardName }).click();
    await expect(page.getByRole('heading', { name: fixture.heading })).toBeVisible();
    await expectExactMapView(page, fixture.view);
    await expect.poll(async () =>
      Number(await mapCanvas(page).getAttribute('data-visible-place-count')),
    ).toBeGreaterThan(0);
    expect(probe.externalRequests).toEqual([]);
    expect(probe.localFailures).toEqual([]);
  });
}

test('loads Original catalog results beyond the first batch when the ledger is scrolled', async ({ page }) => {
  const probe = await installOfflineRoutes(page, {
    syntheticCatalogScenario: 'original-pagination',
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(`/?dataset=${ORIGINAL_DATASET_ID}&region=all&x=-22000&y=-15000&z=4`);
  const map = mapCanvas(page);
  await expect(map).toHaveAttribute(
    'data-visible-place-count',
    String(originalPaginationLocationsFixture.places.length),
  );

  const resultList = page.locator('.place-results');
  const catalogResults = resultList.locator(':scope > button.place-result');
  const balFell = placeResultByExactName(page, BAL_FELL_NAME);
  await expect(catalogResults).toHaveCount(80);
  await expect(balFell).toHaveCount(0);

  for (let batch = 0; batch < 3; batch += 1) {
    const count = await catalogResults.count();
    await resultList.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    await expect.poll(() => catalogResults.count()).toBeGreaterThan(count);
  }
  await expect(balFell).toHaveCount(1);
  await balFell.scrollIntoViewIfNeeded();
  await expect(balFell).toBeVisible();
  const scrollBeforeSelection = await resultList.evaluate((element) => element.scrollTop);
  await balFell.click();
  await expect(page.getByRole('heading', { name: BAL_FELL_NAME, exact: true })).toBeVisible();
  await expect(balFell).toHaveAttribute('aria-current', 'location');
  await expect.poll(() => resultList.evaluate((element) => element.scrollTop))
    .toBe(scrollBeforeSelection);
  await page.getByLabel('Place progress').getByRole('button', { name: 'Visited', exact: true }).click();
  await expect(balFell.locator('[data-marker-kind="visited"]')).toBeVisible();
  await expect.poll(() => resultList.evaluate((element) => element.scrollTop))
    .toBe(scrollBeforeSelection);
  expect(probe.externalRequests).toEqual([]);
  expect(probe.localFailures).toEqual([]);
});

test('fits TR Mainland from landing and a no-view URL', async ({ page }) => {
  const probe = await installOfflineRoutes(page, {
    syntheticCatalogScenario: 'tr-mainland',
  });
  await page.goto('/');
  await page.getByRole('button', { name: POISON_CARD_NAME }).click();
  await expect(
    page.getByRole('heading', { name: 'Tamriel Rebuilt — Poison Song' }),
  ).toBeVisible();

  const mainland = page.getByRole('button', { name: 'TR Mainland', exact: true });
  await mainland.click();
  await expect(mainland).toHaveAttribute('aria-pressed', 'true');
  await expectExactMapView(page, TR_MAINLAND_DEFAULT_VIEW);
  const map = mapCanvas(page);
  await expect(map).toHaveAttribute('data-visible-place-count', '4');
  const resultList = page.locator('.place-results');
  await expect(resultList.locator(':scope > .empty-state')).toHaveCount(0);
  await expect(
    resultList.getByText('No catalog places match these filters.', { exact: false }),
  ).toHaveCount(0);

  await page.getByRole('searchbox', { name: 'Find a place' }).fill('Old Ebonheart');
  const oldEbonheart = placeResultByExactName(page, OLD_EBONHEART_NAME);
  await expect(oldEbonheart).toBeVisible();
  await oldEbonheart.click();
  await expect(
    page.getByRole('heading', { name: OLD_EBONHEART_NAME, exact: true }),
  ).toBeVisible();

  await page.goto(`/?dataset=${DATASET_ID}&region=tr-mainland`);
  await expect(
    page.getByRole('heading', { name: 'Tamriel Rebuilt — Poison Song' }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'TR Mainland', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expectExactMapView(page, TR_MAINLAND_DEFAULT_VIEW);
  await expect(mapCanvas(page)).toHaveAttribute('data-visible-place-count', '4');
  await expect(page.locator('.place-results > .empty-state')).toHaveCount(0);
  expect(probe.externalRequests).toEqual([]);
  expect(probe.localFailures).toEqual([]);
});

test('keeps the open filter drawer in mobile ledger flow', async ({ page }) => {
  const probe = await installOfflineRoutes(page);
  const fixture = filterAcceptanceFixtures[0];
  if (!fixture) {
    throw new Error('Missing filter acceptance fixture');
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(fixture.url);
  await expect(page.getByRole('heading', { name: fixture.heading })).toBeVisible();
  await openFilterDrawer(page);

  const geometry = await page.evaluate(() => {
    const body = document.querySelector<HTMLElement>('.place-filter-drawer__body');
    const followingRow = document.querySelector<HTMLElement>('.place-results');
    if (!body || !followingRow) {
      return null;
    }
    const bodyRect = body.getBoundingClientRect();
    const followingRect = followingRow.getBoundingClientRect();
    return { bodyBottom: bodyRect.bottom, followingTop: followingRect.top };
  });
  expect(geometry).not.toBeNull();
  expect(geometry?.bodyBottom ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(
    (geometry?.followingTop ?? Number.NEGATIVE_INFINITY) + 1,
  );
  expect(probe.externalRequests).toEqual([]);
  expect(probe.localFailures).toEqual([]);
});

test('keeps catalog filters above the growing result list after zoom', async ({ page }) => {
  const probe = await installOfflineRoutes(page);
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(`/?dataset=${ORIGINAL_DATASET_ID}&region=all&x=-22000&y=-15000&z=1`);
  await expect(page.getByRole('heading', { name: 'Morrowind Game of the Year' })).toBeVisible();
  await openFilterDrawer(page);

  const catalogResults = page.locator('.place-results > button.place-result');
  const initialResultCount = await catalogResults.count();
  const zoomIn = page.getByRole('button', { name: 'Zoom in' });
  await zoomIn.click();
  await expect.poll(async () => (await currentMapView(page)).zoom).toBeGreaterThanOrEqual(2);
  await expect.poll(() => catalogResults.count()).toBeGreaterThan(initialResultCount);

  const settlementFilter = typeFilterButton(page, 'Settlement');
  const geometry = await page.evaluate(() => {
    const body = document.querySelector<HTMLElement>('.place-filter-drawer__body');
    const followingRow = document.querySelector<HTMLElement>('.place-results');
    const button = [...document.querySelectorAll<HTMLButtonElement>('.place-filter-option')]
      .find((candidate) => candidate.textContent?.trim().startsWith('Settlement'));
    if (!body || !followingRow || !button) {
      return null;
    }
    const bodyRect = body.getBoundingClientRect();
    const followingRect = followingRow.getBoundingClientRect();
    const buttonRect = button.getBoundingClientRect();
    const hitTarget = document.elementFromPoint(
      buttonRect.left + buttonRect.width / 2,
      buttonRect.top + buttonRect.height / 2,
    );
    return {
      bodyBottom: bodyRect.bottom,
      followingTop: followingRect.top,
      filterReceivesPointer: hitTarget !== null && button.contains(hitTarget),
    };
  });
  expect(geometry).not.toBeNull();
  expect(geometry?.bodyBottom ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(
    (geometry?.followingTop ?? Number.NEGATIVE_INFINITY) + 1,
  );
  expect(geometry?.filterReceivesPointer).toBe(true);
  await settlementFilter.click();
  await expect(settlementFilter).toHaveAttribute('aria-pressed', 'true');
  expect(probe.externalRequests).toEqual([]);
  expect(probe.localFailures).toEqual([]);
});

test('loads fonts and accessible icons entirely from local assets', async ({ page }) => {
  const probe = await installOfflineRoutes(page);
  const fixture = filterAcceptanceFixtures[0];
  if (!fixture) {
    throw new Error('Missing visual-system acceptance fixture');
  }
  await page.goto(fixture.url);
  await expect(page.getByRole('heading', { name: fixture.heading })).toBeVisible();
  await expect(mapCanvas(page)).toBeVisible();
  await page.evaluate(async () => {
    await document.fonts.ready;
  });

  const visualSystem = await page.evaluate(() => ({
    fonts: {
      ui: document.fonts.check('400 13px "Atkinson Hyperlegible Next Variable"'),
      display: document.fonts.check('600 20px "Alegreya Variable"'),
      data: document.fonts.check('400 11px "IBM Plex Mono"'),
    },
    fontResources: performance
      .getEntriesByType('resource')
      .map(({ name }) => new URL(name))
      .filter(({ pathname }) => pathname.endsWith('.woff2'))
      .map(({ origin, pathname }) => ({ origin, pathname })),
    icons: [...document.querySelectorAll<SVGElement>('[data-pixel-icon]')].map((icon) => ({
      name: icon.dataset.pixelIcon,
      hidden: icon.getAttribute('aria-hidden'),
      focusable: icon.getAttribute('focusable'),
      width: getComputedStyle(icon).width,
      height: getComputedStyle(icon).height,
    })),
  }));

  expect(visualSystem.fonts).toEqual({ ui: true, display: true, data: true });
  expect(visualSystem.fontResources.length).toBeGreaterThanOrEqual(3);
  expect(visualSystem.fontResources.every(({ origin }) => origin === new URL(page.url()).origin))
    .toBe(true);
  expect(visualSystem.icons.length).toBeGreaterThan(0);
  expect(visualSystem.icons.every(({ hidden, focusable }) =>
    hidden === 'true' && focusable === 'false'
  )).toBe(true);
  expect(visualSystem.icons.every(({ width, height }) => width === height)).toBe(true);
  expect(probe.externalRequests).toEqual([]);
  expect(probe.localFailures).toEqual([]);
});

for (const fixture of filterAcceptanceFixtures) {
  test(`${fixture.label} exposes data-driven filters and deterministic label priority`, async ({ page }) => {
    const probe = await installOfflineRoutes(page);
    await page.goto(fixture.url);

    await expect(page.getByRole('heading', { name: fixture.heading })).toBeVisible();
    await openFilterDrawer(page);
    for (const type of fixture.availableTypes) {
      await expect(typeFilterButton(page, type)).toHaveCount(1);
      await expect(typeFilterButton(page, type)).toContainText('1');
    }
    await expect(typeFilterButton(page, fixture.unavailableType)).toHaveCount(0);
    await expect(typeFilterButton(page, 'Any type')).toContainText('4');
    await expect(statusFilterButton(page, 'Unvisited')).toContainText('4');
    await expect(statusFilterButton(page, 'Active')).toContainText('0');
    await expect(statusFilterButton(page, 'Visited')).toContainText('0');

    const map = mapCanvas(page);
    await expect(map).toHaveAttribute('data-visible-place-count', '4');
    await expect(map).toHaveAttribute('data-label-candidate-count', '4');
    await expect.poll(async () => (await labelPriority(page))[0]).toBeTruthy();

    await page.getByRole('button', { name: fixture.facetRegionName, exact: true }).click();
    await expect(map).toHaveAttribute('data-visible-place-count', '3');
    await expect(typeFilterButton(page, 'Any type')).toContainText('3');
    await expect(statusFilterButton(page, 'Any status')).toContainText('3');

    const search = page.getByRole('searchbox', { name: 'Find a place' });
    await search.fill(fixture.queryPlaceName);
    const catalogResults = page.locator('.place-results > button.place-result');
    await expect(catalogResults).toHaveCount(1);
    await expect(catalogResults).toContainText(fixture.queryPlaceName);
    await expect(map).toHaveAttribute('data-visible-place-count', '3');
    await expect.poll(async () => (await labelPriority(page))[0]).toBe(
      fixture.queryPlaceId,
    );

    await catalogResults.click();
    await expect(
      page.getByRole('heading', { name: fixture.queryPlaceName, exact: true }),
    ).toBeVisible();
    await expect.poll(async () => (await labelPriority(page))[0]).toBe(
      fixture.queryPlaceId,
    );
    await search.fill('');
    const selectedPriority = await map.getAttribute('data-label-priority');
    expect(selectedPriority?.split(',')[0]).toBe(fixture.queryPlaceId);

    await page.reload();
    await expect(
      page.getByRole('heading', { name: fixture.queryPlaceName, exact: true }),
    ).toBeVisible();
    await expect(map).toHaveAttribute('data-label-priority', selectedPriority ?? '');
    expect(probe.externalRequests).toEqual([]);
    expect(probe.localFailures).toEqual([]);
  });

  test(`${fixture.label} filter URL survives reload and Back/Forward canonically`, async ({ page }) => {
    const probe = await installOfflineRoutes(page);
    await page.goto(fixture.url);
    await expect(page.getByRole('heading', { name: fixture.heading })).toBeVisible();
    await openFilterDrawer(page);

    await typeFilterButton(page, fixture.clickedTypes[0]).click();
    await typeFilterButton(page, fixture.clickedTypes[1]).click();
    await statusFilterButton(page, 'Visited').click();
    await statusFilterButton(page, 'Active').click();
    await expectUrlFilters(page, fixture.canonicalTypes, ['active', 'visited']);
    const finalUrl = relativePageUrl(page);

    await page.reload();
    await openFilterDrawer(page);
    for (const type of fixture.clickedTypes) {
      await expect(typeFilterButton(page, type)).toHaveAttribute('aria-pressed', 'true');
    }
    await expect(statusFilterButton(page, 'Active')).toHaveAttribute('aria-pressed', 'true');
    await expect(statusFilterButton(page, 'Visited')).toHaveAttribute('aria-pressed', 'true');
    await expectRelativeUrl(page, finalUrl);

    await page.goBack();
    await expectUrlFilters(page, fixture.canonicalTypes, ['visited']);
    await expect(statusFilterButton(page, 'Active')).toHaveAttribute('aria-pressed', 'false');
    await expect(statusFilterButton(page, 'Visited')).toHaveAttribute('aria-pressed', 'true');

    await page.goForward();
    await expectUrlFilters(page, fixture.canonicalTypes, ['active', 'visited']);
    await expect(statusFilterButton(page, 'Active')).toHaveAttribute('aria-pressed', 'true');
    await expectRelativeUrl(page, finalUrl);
    expect(probe.externalRequests).toEqual([]);
    expect(probe.localFailures).toEqual([]);
  });

  test(`${fixture.label} treats missing progress as unvisited and reacts to status changes`, async ({ page }) => {
    const probe = await installOfflineRoutes(page);
    await page.goto(fixture.url);
    await expect(page.getByRole('heading', { name: fixture.heading })).toBeVisible();
    const search = page.getByRole('searchbox', { name: 'Find a place' });
    await search.fill(fixture.primaryPlaceName);
    await page
      .getByRole('button', { name: new RegExp(`^${fixture.primaryPlaceName}`) })
      .click();

    const progress = page.getByLabel('Place progress');
    await expect(
      progress.getByRole('button', { name: 'Unvisited', exact: true }),
    ).toHaveAttribute('aria-pressed', 'true');
    await progress.getByRole('button', { name: 'Active', exact: true }).click();
    await expect(
      progress.getByRole('button', { name: 'Active', exact: true }),
    ).toHaveAttribute('aria-pressed', 'true');

    await openFilterDrawer(page);
    await statusFilterButton(page, 'Active').click();
    await expectUrlFilters(page, [], ['active']);
    expect(new URL(page.url()).searchParams.get('place')).toBe(fixture.primaryPlaceId);
    await expect(
      page.getByRole('heading', { name: fixture.primaryPlaceName, exact: true }),
    ).toBeVisible();

    await progress.getByRole('button', { name: 'Visited', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: fixture.primaryPlaceName, exact: true }),
    ).toHaveCount(0);
    await expect(mapCanvas(page)).toHaveAttribute('data-visible-place-count', '0');
    await expectUrlFilters(page, [], ['active']);
    expect(new URL(page.url()).searchParams.has('place')).toBe(false);
    expect(probe.externalRequests).toEqual([]);
    expect(probe.localFailures).toEqual([]);
  });
}

test('canonicalizes an unknown dataset to landing while preserving unrelated URL state', async ({ page }) => {
  const probe = await installOfflineRoutes(page);

  await page.goto(
    '/?theme=sepia&dataset=retired-map&region=vvardenfell&x=1&y=2&z=3&place=stale#ledger',
  );

  await expect(page.getByRole('heading', { name: 'Choose your world' })).toBeVisible();
  await expectRelativeUrl(page, '/?theme=sepia#ledger');
  expect(probe.externalRequests).toEqual([]);
});

test('canonicalizes invalid region, view and cross-dataset place without crashing', async ({ page }) => {
  const probe = await installOfflineRoutes(page);

  await page.goto(
    `/?theme=sepia&dataset=${ORIGINAL_DATASET_ID}&region=unknown&x=123&y=NaN&place=${PLACE_ID}`,
  );

  await expect(page.getByRole('heading', { name: 'Morrowind Game of the Year' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'All', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeVisible();
  await expect(page.getByRole('heading', { name: PLACE_NAME, exact: true })).toHaveCount(0);
  await expect.poll(() => {
    const currentUrl = new URL(page.url());
    return ['x', 'y', 'z'].every((parameter) => {
      const value = currentUrl.searchParams.get(parameter);
      return value !== null && value.length > 0 && Number.isFinite(Number(value));
    });
  }).toBe(true);
  const canonicalUrl = new URL(page.url());
  expect(canonicalUrl.searchParams.get('theme')).toBe('sepia');
  expect(canonicalUrl.searchParams.get('dataset')).toBe(ORIGINAL_DATASET_ID);
  expect(canonicalUrl.searchParams.get('region')).toBe('all');
  expect(canonicalUrl.searchParams.has('place')).toBe(false);
  expect(canonicalUrl.searchParams.get('x')).not.toBe('123');
  expect(canonicalUrl.searchParams.get('x')).not.toBeNull();
  expect(canonicalUrl.searchParams.get('y')).not.toBeNull();
  expect(canonicalUrl.searchParams.get('z')).not.toBeNull();
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

  await expect(page.getByRole('heading', { name: 'Morrowind Game of the Year' })).toBeVisible();
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
  await expect(page.getByRole('button', { name: 'Back to maps' })).toBeVisible();
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
  await expect(page.getByRole('heading', { name: 'Choose your world' })).toBeVisible();
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

  await page.getByRole('button', { name: 'Back to maps' }).click();
  await expect(page.getByRole('heading', { name: 'Choose your world' })).toBeVisible();
  await expect.poll(() => historyLength(page)).toBe(cameraHistoryLength + 1);
  expect(probe.externalRequests).toEqual([]);
});

test('offline V4 workflow persists progress, notes and personal markers', async ({ page }) => {
  const probe = await installOfflineRoutes(page);
  await openPoisonSong(page);

  await expect.poll(() => probe.mapAssetRequests.length).toBeGreaterThan(0);
  await expect.poll(() => probe.tileRequests.length).toBeGreaterThan(0);
  await expect.poll(() => probe.tileRequests.some((path) =>
    path.includes(`/${ORIGINAL_DATASET_ID}/${ORIGINAL_INVENTORY}/`)
  )).toBe(true);
  await expect.poll(() => probe.tileRequests.some((path) =>
    path.includes(`/${DATASET_ID}/${V4_INVENTORY}/`)
  )).toBe(true);
  await expect.poll(() => hasPaintedBasemap(page)).toBe(true);
  expect(probe.mapAssetRequests).toContain(
    `/datasets/metadata/${ORIGINAL_DATASET_ID}/${ORIGINAL_INVENTORY}/map-assets.json`,
  );
  expect(probe.mapAssetRequests).toContain(
    `/datasets/metadata/${DATASET_ID}/${V4_INVENTORY}/map-assets.json`,
  );
  expect(probe.tileRequests.every((path) =>
    path.includes(ORIGINAL_INVENTORY) || path.includes(V4_INVENTORY)
  )).toBe(true);

  await searchAndOpenPlace(page);
  const progress = page.getByLabel('Place progress');
  const activeStatus = progress.getByRole('button', { name: 'Active' });
  await activeStatus.click();
  await expect(activeStatus).toHaveAttribute('aria-pressed', 'true');
  const note = progress.getByRole('textbox', { name: 'Personal note' });
  await note.fill('Return after sunset.');
  await note.blur();
  await expect(progress.getByRole('status')).toHaveText('Saved.');

  const zoomBefore = (await currentMapView(page)).zoom;
  await page.getByRole('button', { name: 'Zoom in' }).click();
  await expect.poll(async () => (await currentMapView(page)).zoom).toBeGreaterThan(zoomBefore);
  await page.getByRole('button', { name: 'Close place card' }).click();

  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  const xBeforePan = (await currentMapView(page)).x;
  await map.focus();
  await map.press('ArrowRight');
  await expect.poll(async () => (await currentMapView(page)).x).not.toBe(xBeforePan);

  await page.locator('button.add-marker-tool').click();
  await map.focus();
  await map.press('Enter');
  const markerEditor = page.getByLabel('Custom marker');
  const markerName = markerEditor.getByRole('textbox', { name: 'Marker name' });
  const markerNote = markerEditor.getByRole('textbox', { name: 'Personal note' });
  await expect(markerName).toBeFocused();
  await markerName.fill('Field note pin');
  await markerNote.fill('Hidden cache.');
  await markerEditor.getByRole('button', { name: 'Save marker' }).click();
  await expect(markerEditor.getByRole('status')).toHaveText('Saved.');
  await expect(markerEditor.getByRole('textbox', { name: 'Marker name' })).toHaveValue(
    'Field note pin',
  );
  await expect(markerEditor.getByRole('textbox', { name: 'Personal note' })).toHaveValue(
    'Hidden cache.',
  );
  await expect(map).toHaveAttribute('data-custom-marker-count', '1');
  await page.getByRole('button', { name: 'Vvardenfell', exact: true }).click();
  await openFilterDrawer(page);
  await typeFilterButton(page, 'Cave').click();
  await statusFilterButton(page, 'Visited').click();
  await expect(map).toHaveAttribute('data-custom-marker-count', '1');
  await page.locator('button.place-filter-reset').click();

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
  const reloadedMap = mapCanvas(page);
  await expect(reloadedMap).toHaveAttribute('data-custom-marker-count', '1');
  await reloadedMap.focus();
  await reloadedMap.press('m');
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
  await tileAlert.getByRole('button', { name: 'Retry failed tiles' }).click();
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

for (const fixture of preparedDirectUrlFixtures) {
  test(`@prepared recovers the real ${fixture.label} bundle without losing its URL`, async ({ page }) => {
    test.skip(
      process.env.MORROWIND_ACCEPTANCE_PREPARED !== '1',
      'Run pnpm test:acceptance:prepared when both prepared payloads are available.',
    );
    const probe = await installOfflineRoutes(page, {
      syntheticPayloads: false,
      failMapAssets: true,
    });
    await page.goto(fixture.url);
    const alert = page.locator('.dataset-load-state[role="alert"]');
    await expect(alert).toContainText('could not be opened');
    await expectRelativeUrl(page, fixture.url);

    probe.restoreMapAssets();
    await alert.getByRole('button', { name: 'Retry' }).click();
    await expectDirectUrlState(page, fixture);
    await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeFocused();
    expect(probe.externalRequests).toEqual([]);
  });

  test(`@prepared retries only failed real ${fixture.label} tiles in place`, async ({ page }) => {
    test.skip(
      process.env.MORROWIND_ACCEPTANCE_PREPARED !== '1',
      'Run pnpm test:acceptance:prepared when both prepared payloads are available.',
    );
    const probe = await installOfflineRoutes(page, {
      syntheticPayloads: false,
      failTiles: true,
    });
    await page.goto(fixture.url);
    const tileAlert = page.locator('.basemap-state--error[role="alert"]');
    await expect(tileAlert).toBeVisible();
    const failedRequestCount = probe.tileRequests.length;
    const historyLengthBeforeRetry = await historyLength(page);

    probe.restoreTiles();
    await tileAlert.getByRole('button', { name: 'Retry failed tiles' }).click();
    await expect(tileAlert).toBeHidden();
    await expect.poll(() => probe.tileRequests.length).toBeGreaterThan(failedRequestCount);
    await expectRelativeUrl(page, fixture.url);
    expect(await historyLength(page)).toBe(historyLengthBeforeRetry);
    expect(probe.externalRequests).toEqual([]);
  });
}

test('@prepared renders the complete current TR catalog and tile pyramid', async ({ page }) => {
  test.skip(
    process.env.MORROWIND_ACCEPTANCE_PREPARED !== '1',
    'Run pnpm test:acceptance:prepared when the prepared TR payload is available.',
  );
  const preparedRoot = trCandidatePreparedAssets
    ? trCandidatePreparedAssets.tilesRoot
    : join(
        process.cwd(),
        'apps/web/public/datasets/generated',
        DATASET_ID,
        V4_INVENTORY,
        'tiles',
      );
  expect(existsSync(preparedRoot)).toBe(true);

  const probe = await installOfflineRoutes(page, { syntheticPayloads: false });
  const fixture = preparedDirectUrlFixtures[0]!;
  await page.goto(fixture.url);
  await expectDirectUrlState(page, fixture);
  await openFilterDrawer(page);
  // Facet counts remain contextual to the deep-linked region and current zoom.
  const anyTypeCount = trCandidatePreparedAssets?.anyTypeCount ?? 3_052;
  await expect(typeFilterButton(page, 'Any type')).toHaveText(
    `Any type ${anyTypeCount.toLocaleString('en-US')}`,
  );
  await expect.poll(async () =>
    Number(await mapCanvas(page).getAttribute('data-label-candidate-count')),
  ).toBeGreaterThan(0);
  const expectedPlaceName = trCandidatePreparedAssets?.selectedPlaceName ?? PLACE_NAME;
  await page.getByRole('searchbox', { name: 'Find a place' }).fill(expectedPlaceName);
  if (trCandidatePreparedAssets) {
    await expect(page.locator('button.place-result--selected')).toContainText(
      expectedPlaceName,
    );
  } else {
    await expect(
      page.getByRole('button', { name: new RegExp(`^${expectedPlaceName}`) }),
    ).toBeVisible();
  }
  await expect.poll(() => probe.tileRequests.length).toBeGreaterThan(0);
  await expect.poll(() => hasPaintedBasemap(page)).toBe(true);
  expect(
    probe.tileRequests.every((path) =>
      trCandidatePreparedAssets
        ? path.startsWith(trCandidatePreparedAssets.tileRequestPrefix) &&
          path.includes(`/${trCandidatePreparedAssets.tileInventorySha256}/`)
        : path.includes(V4_INVENTORY),
    ),
  ).toBe(true);
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
  const fixture = directUrlFixtures[1]!;
  await page.goto(fixture.url);
  await expectDirectUrlState(page, fixture);
  await openFilterDrawer(page);
  // Facet counts remain contextual to the deep-linked region and current zoom.
  await expect(typeFilterButton(page, 'Any type')).toContainText('944');
  await expect.poll(async () =>
    Number(await mapCanvas(page).getAttribute('data-label-candidate-count')),
  ).toBeGreaterThan(0);
  await page.getByRole('searchbox', { name: 'Find a place' }).fill(ORIGINAL_PLACE_NAME);
  await page.getByRole('button', { name: new RegExp(`^${ORIGINAL_PLACE_NAME}`) }).click();
  await expect(page.getByRole('heading', { name: ORIGINAL_PLACE_NAME })).toBeVisible();
  await expect.poll(() => probe.tileRequests.length).toBeGreaterThan(0);
  await expect.poll(() => hasPaintedBasemap(page)).toBe(true);

  const progress = page.getByLabel('Place progress');
  const visitedStatus = progress.getByRole('button', { name: 'Visited', exact: true });
  await visitedStatus.click();
  await expect(visitedStatus).toHaveAttribute('aria-pressed', 'true');
  const note = progress.getByRole('textbox', { name: 'Personal note' });
  await note.fill('Original route cleared.');
  await note.blur();
  await expect(progress.getByRole('status')).toHaveText('Saved.');

  const zoomBefore = (await currentMapView(page)).zoom;
  await page.getByRole('button', { name: 'Zoom in' }).click();
  await expect.poll(async () => (await currentMapView(page)).zoom).toBeGreaterThan(zoomBefore);
  await page.getByRole('button', { name: 'Close place card' }).click();

  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  const xBeforePan = (await currentMapView(page)).x;
  await map.focus();
  await map.press('ArrowRight');
  await expect.poll(async () => (await currentMapView(page)).x).not.toBe(xBeforePan);

  await page.locator('button.add-marker-tool').click();
  await map.focus();
  await map.press('Enter');
  const markerEditor = page.getByLabel('Custom marker');
  await markerEditor.getByRole('textbox', { name: 'Marker name' }).fill('Original field pin');
  await markerEditor.getByRole('textbox', { name: 'Personal note' }).fill('Base-game only.');
  await markerEditor.getByRole('button', { name: 'Save marker' }).click();
  await expect(markerEditor.getByRole('status')).toHaveText('Saved.');
  await expect(markerEditor.getByRole('textbox', { name: 'Marker name' })).toHaveValue(
    'Original field pin',
  );
  await expect(markerEditor.getByRole('textbox', { name: 'Personal note' })).toHaveValue(
    'Base-game only.',
  );
  await expect(map).toHaveAttribute('data-custom-marker-count', '1');

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
  await expect(mapCanvas(page)).toHaveAttribute('data-custom-marker-count', '1');

  expect(probe.tileRequests.every((path) => path.includes(ORIGINAL_INVENTORY))).toBe(true);
  expect(probe.externalRequests).toEqual([]);
  expect(probe.localFailures).toEqual([]);
});
