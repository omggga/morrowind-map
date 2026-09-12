import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import {
  ORIGINAL_CARD_NAME,
  ORIGINAL_DATASET_ID,
  ORIGINAL_HEADING,
  POISON_CARD_NAME,
  POISON_DATASET_ID,
  POISON_HEADING,
  POISON_PLACE_NAME,
  expectNoViewportOverflow,
  installOfflineRoutes,
  openDataset,
  waitForLandingReady,
  waitForVisualReady,
} from './support';

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] as const;
const POISON_DEEP_LINK =
  `/?dataset=${POISON_DATASET_ID}&region=tr-mainland&x=12288&y=-217088&z=6`;
const ORIGINAL_DEEP_LINK =
  `/?dataset=${ORIGINAL_DATASET_ID}&region=vvardenfell&x=-21879.766&y=-14022.853&z=6`;

function isDesktop(testInfo: TestInfo): boolean {
  return testInfo.project.use.viewport?.width === 1280;
}

function isPrimaryResponsiveViewport(testInfo: TestInfo): boolean {
  const viewport = testInfo.project.use.viewport;
  return (viewport?.width === 390 && viewport.height === 844) ||
    (viewport?.width === 844 && viewport.height === 390);
}

async function currentRelativeUrl(page: Page): Promise<string> {
  return page.evaluate(() => `${window.location.pathname}${window.location.search}`);
}

async function expectAxeClean(page: Page, state: string): Promise<void> {
  const wcag = await new AxeBuilder({ page }).withTags([...WCAG_TAGS]).analyze();
  expect(
    wcag.violations,
    `${state}: WCAG violations\n${JSON.stringify(wcag.violations, null, 2)}`,
  ).toEqual([]);

  const bestPractice = await new AxeBuilder({ page }).withTags(['best-practice']).analyze();
  const severe = bestPractice.violations.filter(
    ({ impact }) => impact === 'serious' || impact === 'critical',
  );
  expect(
    severe,
    `${state}: serious/critical best-practice violations\n${JSON.stringify(severe, null, 2)}`,
  ).toEqual([]);
}

async function screenshot(page: Page, name: string): Promise<void> {
  if (process.env.MORROWIND_UI_SNAPSHOTS !== '1') return;
  await page.evaluate(async () => document.fonts.ready);
  await expect(page).toHaveScreenshot(name, {
    animations: 'disabled',
    caret: 'hide',
    scale: 'css',
  });
}

test('keeps a healthy landing card usable when one manifest fails', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'The detailed partial-catalog workflow runs once on desktop.');
  const probe = await installOfflineRoutes(page, { failManifestDatasetId: ORIGINAL_DATASET_ID });

  await page.goto('/');
  const partial = page.locator('.error-panel--partial[role="alert"]');
  await expect(partial).toContainText('PARTIAL CATALOG');
  await expect(partial).toContainText(
    'One map manifest is unavailable. The available map remains usable.',
  );
  await expect(partial).toContainText(ORIGINAL_DATASET_ID);
  await expect(page.getByRole('button', { name: POISON_CARD_NAME })).toBeEnabled();
  await expect(page.getByRole('button', { name: ORIGINAL_CARD_NAME })).toHaveCount(0);
  await expectAxeClean(page, 'partial landing error');

  await page.getByRole('button', { name: POISON_CARD_NAME }).click();
  await waitForVisualReady(page);
  await expect(page.getByRole('heading', { name: POISON_HEADING })).toBeVisible();
  expect(new URL(page.url()).searchParams.get('dataset')).toBe(POISON_DATASET_ID);
  expect(probe.externalRequests).toEqual([]);
});

test('preserves a failed deep link and coalesces repeated manifest retry clicks', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'The detailed partial-catalog workflow runs once on desktop.');
  const probe = await installOfflineRoutes(page, { failManifestDatasetId: ORIGINAL_DATASET_ID });

  await page.goto(ORIGINAL_DEEP_LINK);
  const partial = page.locator('.error-panel--partial[role="alert"]');
  await expect(partial).toBeVisible();
  const preservedUrl = await currentRelativeUrl(page);
  expect(probe.manifestRequestCount(ORIGINAL_DATASET_ID)).toBe(1);
  expect(probe.manifestRequestCount(POISON_DATASET_ID)).toBe(1);

  probe.restoreManifest();
  const retry = partial.getByRole('button', { name: 'Retry unavailable maps' });
  await retry.evaluate((button: HTMLButtonElement) => {
    button.click();
    button.click();
  });

  await expect(page.getByRole('heading', { name: ORIGINAL_HEADING })).toBeVisible();
  await waitForVisualReady(page);
  expect(await currentRelativeUrl(page)).toBe(preservedUrl);
  expect(probe.manifestRequestCount(ORIGINAL_DATASET_ID)).toBe(2);
  expect(probe.manifestRequestCount(POISON_DATASET_ID)).toBe(2);
});

test('shows a delayed dataset load without discarding its URL', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'Dataset loading states run once on desktop.');
  const probe = await installOfflineRoutes(page, { holdDatasetAssets: true });

  await page.goto(POISON_DEEP_LINK);
  const loading = page.locator('.dataset-load-state[role="status"]');
  await expect(loading).toHaveAttribute('aria-busy', 'true');
  await expect(loading).toContainText('Opening the map dataset…');
  await expect.poll(() => probe.datasetAssetRequestCount()).toBeGreaterThan(0);
  const delayedRequestCount = probe.datasetAssetRequestCount();
  const preservedUrl = await currentRelativeUrl(page);

  probe.releaseDatasetAssets();
  await waitForVisualReady(page);
  await expect(page.getByRole('heading', { name: POISON_HEADING })).toBeVisible();
  expect(await currentRelativeUrl(page)).toBe(preservedUrl);
  expect(probe.datasetAssetRequestCount()).toBe(delayedRequestCount);
});

test('exposes an idempotent dataset retry state and restores map focus', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'Dataset retry states run once on desktop.');
  const probe = await installOfflineRoutes(page, {
    failDatasetAssets: true,
    holdDatasetAssets: true,
  });

  await page.goto(POISON_DEEP_LINK);
  const alert = page.locator('.dataset-load-state[role="alert"]');
  await expect(alert).toContainText('The map dataset could not be opened');
  const preservedUrl = await currentRelativeUrl(page);
  const initialRequestCount = probe.datasetAssetRequestCount();
  expect(initialRequestCount).toBeGreaterThan(0);

  probe.restoreDatasetAssets();
  const retry = alert.getByRole('button', { name: 'Retry' });
  await retry.evaluate((button: HTMLButtonElement) => {
    button.click();
    button.click();
  });
  await expect(alert).toHaveAttribute('aria-busy', 'true');
  await expect(alert.getByRole('button', { name: 'Retrying…' })).toBeDisabled();
  await expect.poll(() => probe.datasetAssetRequestCount()).toBe(initialRequestCount + 1);
  await expectAxeClean(page, 'dataset retry');

  probe.releaseDatasetAssets();
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  await expect(map).toBeVisible();
  await waitForVisualReady(page);
  await expect(map).toBeFocused();
  expect(await currentRelativeUrl(page)).toBe(preservedUrl);
  expect(probe.datasetAssetRequestCount()).toBe(initialRequestCount + 1);
});

test('distinguishes partial tile failure, retries only failed tiles, and resets a later viewport', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'Tile recovery details run once on desktop.');
  const probe = await installOfflineRoutes(page, {
    tileFailureMode: 'partial',
    holdTileRetries: true,
  });

  await page.goto(POISON_DEEP_LINK);
  const alert = page.locator('.basemap-state--partial[role="alert"]');
  await expect(alert).toContainText(/Map tiles failed to load in some areas: \d+\./);
  await expect(alert).toContainText('Loaded areas remain available.');
  await page.waitForLoadState('networkidle');
  const preservedUrl = await currentRelativeUrl(page);
  const failedPaths = [...new Set(probe.failedTileRequests)];
  expect(failedPaths).toHaveLength(1);
  expect(new Set(probe.tileRequests).size).toBeGreaterThan(failedPaths.length);
  const requestCountBeforeRetry = probe.tileRequests.length;
  await expectAxeClean(page, 'partial tile error');

  probe.restoreTiles();
  const retry = alert.getByRole('button', { name: 'Retry failed tiles' });
  await retry.evaluate((button: HTMLButtonElement) => {
    button.click();
    button.click();
  });
  await expect(alert).toHaveAttribute('aria-busy', 'true');
  await expect(alert.getByRole('button', { name: 'Retrying…' })).toBeDisabled();
  await expect.poll(() => probe.tileRequests.length).toBeGreaterThan(requestCountBeforeRetry);
  const retriedPaths = probe.tileRequests.slice(requestCountBeforeRetry);
  expect([...new Set(retriedPaths)].sort()).toEqual([...failedPaths].sort());
  expect(retriedPaths).toHaveLength(failedPaths.length);
  await expectAxeClean(page, 'partial tile retry');

  probe.releaseTileRetries();
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  await expect(alert).toHaveCount(0);
  await waitForVisualReady(page);
  await expect(map).toBeFocused();
  expect(await currentRelativeUrl(page)).toBe(preservedUrl);

  probe.failTilesFully();
  const requestCountBeforeMove = probe.tileRequests.length;
  for (let step = 0; step < 12; step += 1) {
    await map.press('ArrowRight', { delay: 80 });
  }
  await expect.poll(() => probe.tileRequests.length).toBeGreaterThan(requestCountBeforeMove);
  const fullAlert = page.locator('.basemap-state--full[role="alert"]');
  await expect(fullAlert).toContainText(/Map tiles failed to load in the visible area: \d+\./);
  await expect(fullAlert).not.toContainText('Loaded areas remain available.');
});

test('uses distinct wording when every visible tile fails', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'Tile error wording runs once on desktop.');
  await installOfflineRoutes(page, { tileFailureMode: 'full' });

  await page.goto(POISON_DEEP_LINK);
  const alert = page.locator('.basemap-state--full[role="alert"]');
  await expect(alert).toContainText(/Map tiles failed to load in the visible area: \d+\./);
  await expect(alert).not.toContainText('Loaded areas remain available.');
  await expect(alert.getByRole('button', { name: 'Retry failed tiles' })).toBeEnabled();
  await expectAxeClean(page, 'full tile error');
});

test('provides focused actions for query, filter, marker, and empty-catalog states', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'The full empty-state action matrix runs once on desktop.');
  const probe = await installOfflineRoutes(page);
  await openDataset(page, POISON_CARD_NAME, POISON_HEADING);
  await waitForVisualReady(page);

  await expect(page.locator('.custom-marker-results')).toHaveCount(0);
  const addMarker = page.locator('button.add-marker-tool');
  await expect(addMarker).toBeEnabled();
  await addMarker.click();
  await expect(addMarker).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('Escape');
  await expect(addMarker).toHaveAttribute('aria-pressed', 'false');

  const search = page.getByRole('searchbox', { name: 'Find a place' });
  const catalogEmpty = page.locator('.place-results > .empty-state');
  await search.fill('no such place');
  await expect(catalogEmpty).toContainText('No places match this query.');
  await catalogEmpty.getByRole('button', { name: 'Clear search' }).click();
  await expect(search).toBeFocused();
  await expect(search).toHaveValue('');
  await expect(page.getByRole('button', { name: new RegExp(`^${POISON_PLACE_NAME}`) })).toBeVisible();

  await page.getByRole('button', { name: 'Vvardenfell', exact: true }).click();
  const filters = page.locator('details.place-filter-drawer');
  await filters.locator('summary').click();
  await filters.getByRole('button', { name: /^Cave(?:\s|$)/ }).click();
  await expect(catalogEmpty).toContainText('No catalog places match these filters.');
  await catalogEmpty.getByRole('button', { name: 'Reset filters' }).click();
  await expect(search).toBeFocused();
  const resetUrl = new URL(page.url());
  expect(resetUrl.searchParams.get('region')).toBe('all');
  expect(resetUrl.searchParams.getAll('type')).toEqual([]);
  expect(resetUrl.searchParams.getAll('status')).toEqual([]);
  await expect(page.getByRole('button', { name: new RegExp(`^${POISON_PLACE_NAME}`) })).toBeVisible();

  probe.showEmptyCatalog(POISON_DATASET_ID);
  await openDataset(page, POISON_CARD_NAME, POISON_HEADING);
  const noExterior = page.locator('.place-results > .empty-state');
  await expect(noExterior).toContainText(
    'This dataset contains no exterior places to display. Choose another version.',
  );
  await noExterior.getByRole('button', { name: 'Back to maps' }).click();
  await expect(page.getByRole('heading', { name: 'Choose your world' })).toBeVisible();
});

test('keeps the map read-only and recovers when IndexedDB becomes available', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'The IndexedDB recovery contract runs once on desktop.');
  await page.addInitScript(() => {
    const originalOpen = IDBFactory.prototype.open.bind(indexedDB);
    let unavailable = true;
    Object.defineProperty(window, '__restoreStage75IndexedDb', {
      value: () => { unavailable = false; },
    });
    Object.defineProperty(IDBFactory.prototype, 'open', {
      configurable: true,
      value(name: string, version?: number) {
        if (unavailable) {
          throw new DOMException('IndexedDB unavailable', 'InvalidStateError');
        }
        return version === undefined
          ? originalOpen(name)
          : originalOpen(name, version);
      },
    });
  });
  await installOfflineRoutes(page);

  await page.goto(POISON_DEEP_LINK);
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  await expect(map).toBeVisible();
  const alert = page.locator('.user-data-state--error[role="alert"]');
  await expect(alert).toContainText('Local progress is unavailable');
  await expect(alert).toContainText('read-only mode');
  await expect(page.locator('button.add-marker-tool')).toBeDisabled();
  const preservedUrl = await currentRelativeUrl(page);
  await expectAxeClean(page, 'IndexedDB unavailable read-only map');

  await page.evaluate(() => {
    (window as unknown as Window & { __restoreStage75IndexedDb: () => void })
      .__restoreStage75IndexedDb();
  });
  await alert.getByRole('button', { name: 'Retry' }).click();
  await expect(alert).toHaveCount(0);
  await expect(map).toBeFocused();
  await expect(page.locator('button.add-marker-tool')).toBeEnabled();
  expect(await currentRelativeUrl(page)).toBe(preservedUrl);
});

test('keeps partial and query-empty actions usable on primary mobile and landscape views', async ({ page }, testInfo) => {
  test.skip(
    !isPrimaryResponsiveViewport(testInfo),
    'Responsive Stage 7.5 behavior is sampled at 390x844 and 844x390.',
  );
  await installOfflineRoutes(page, { failManifestDatasetId: ORIGINAL_DATASET_ID });

  await page.goto('/');
  const partial = page.locator('.error-panel--partial[role="alert"]');
  await expect(partial).toBeVisible();
  await expect(partial.getByRole('button', { name: 'Retry unavailable maps' })).toBeVisible();
  await expect(page.getByRole('button', { name: POISON_CARD_NAME })).toBeVisible();
  await expectNoViewportOverflow(page);
  await expectAxeClean(page, 'responsive partial landing');

  await page.getByRole('button', { name: POISON_CARD_NAME }).click();
  await waitForVisualReady(page);
  const search = page.getByRole('searchbox', { name: 'Find a place' });
  await search.fill('no such place');
  const empty = page.locator('.place-results > .empty-state');
  await expect(empty.getByRole('button', { name: 'Clear search' })).toBeVisible();
  await expectNoViewportOverflow(page);
  await empty.getByRole('button', { name: 'Clear search' }).click();
  await expect(search).toBeFocused();
});

test('pins the stable partial-manifest landing state', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'New Stage 7.5 visual baselines are desktop-only.');
  await installOfflineRoutes(page, { failManifestDatasetId: ORIGINAL_DATASET_ID });

  await page.goto('/');
  await expect(page.locator('.error-panel--partial[role="alert"]')).toBeVisible();
  await waitForLandingReady(page);
  await screenshot(page, 'partial-manifest-landing.png');
});

test('pins the stable partial-tile error state', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'New Stage 7.5 visual baselines are desktop-only.');
  await installOfflineRoutes(page, { tileFailureMode: 'partial' });

  await page.goto(POISON_DEEP_LINK);
  await expect(page.locator('.basemap-state--partial[role="alert"]')).toBeVisible();
  await page.waitForLoadState('networkidle');
  await screenshot(page, 'partial-tile-error.png');
});
