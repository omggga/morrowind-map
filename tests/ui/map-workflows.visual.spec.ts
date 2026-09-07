import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';
import {
  ORIGINAL_CARD_NAME,
  ORIGINAL_HEADING,
  ORIGINAL_PLACE_NAME,
  POISON_CARD_NAME,
  POISON_HEADING,
  POISON_PLACE_NAME,
  expectNoViewportOverflow,
  installOfflineRoutes,
  openDataset,
  waitForLandingReady,
  waitForVisualReady,
} from './support';

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] as const;

function isDesktop(testInfo: TestInfo): boolean {
  return testInfo.project.use.viewport?.width === 1280;
}

function hasTouch(testInfo: TestInfo): boolean {
  const viewport = testInfo.project.use.viewport;
  return testInfo.project.use.hasTouch === true && (
    (viewport?.width === 390 && viewport.height === 844) ||
    (viewport?.width === 844 && viewport.height === 390)
  );
}

async function screenshot(page: Page, name: string): Promise<void> {
  await page.evaluate(async () => document.fonts.ready);
  await expect(page).toHaveScreenshot(name, {
    animations: 'disabled',
    caret: 'hide',
    scale: 'css',
  });
}

async function tabTo(
  page: Page,
  target: Locator,
  { reverse = false, limit = 80 }: { readonly reverse?: boolean; readonly limit?: number } = {},
): Promise<void> {
  for (let index = 0; index < limit; index += 1) {
    if (await target.evaluate((element) => element === document.activeElement).catch(() => false)) {
      return;
    }
    await page.keyboard.press(reverse ? 'Shift+Tab' : 'Tab');
  }
  throw new Error(`Keyboard focus did not reach ${await target.first().evaluate((element) => element.outerHTML)}`);
}

async function expectWcagClean(page: Page, state: string): Promise<void> {
  const wcag = await new AxeBuilder({ page }).withTags([...WCAG_TAGS]).analyze();
  expect(wcag.violations, `${state}: WCAG violations\n${JSON.stringify(wcag.violations, null, 2)}`).toEqual([]);

  const bestPractice = await new AxeBuilder({ page }).withTags(['best-practice']).analyze();
  const severe = bestPractice.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical');
  expect(severe, `${state}: serious/critical best-practice violations\n${JSON.stringify(severe, null, 2)}`).toEqual([]);
}

test('pins landing and map layout across the viewport matrix', async ({ page }, testInfo) => {
  const probe = await installOfflineRoutes(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Choose your world' })).toBeVisible();
  await waitForLandingReady(page);
  await expectNoViewportOverflow(page);
  await screenshot(page, 'landing.png');

  await page.getByRole('button', { name: 'Contact information' }).click();
  const contactPanel = page.getByRole('complementary', { name: 'Contact information' });
  await expect(contactPanel).toBeInViewport({ ratio: 1 });
  await expectNoViewportOverflow(page);
  if (isDesktop(testInfo)) {
    await expectWcagClean(page, 'Landing contact information');
    await screenshot(page, 'landing-contact.png');
  }
  await page.getByRole('button', { name: 'Close contact information' }).click();

  await page.getByRole('button', { name: POISON_CARD_NAME }).click();
  await waitForVisualReady(page);
  await expectNoViewportOverflow(page);
  await screenshot(page, 'poison-map.png');

  expect(probe.externalRequests).toEqual([]);
});

test('pins both themes and the interactive state matrix', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'Detailed visual states are pinned once in the desktop project.');
  await installOfflineRoutes(page);

  await openDataset(page, ORIGINAL_CARD_NAME, ORIGINAL_HEADING);
  await waitForVisualReady(page);
  await screenshot(page, 'original-map.png');
  await page.getByRole('button', { name: 'Back to maps' }).click();

  await page.getByRole('button', { name: POISON_CARD_NAME }).click();
  await waitForVisualReady(page);
  await expect(page.locator('.marker-legend [data-marker-shape="hollow-square"]')).toHaveCount(4);
  await expect(page.getByRole('button', { name: 'Zoom in' })).toHaveText('+');
  await expect(page.getByRole('button', { name: 'Zoom out' })).toHaveText('−');
  const filters = page.locator('details.place-filter-drawer');
  await filters.locator('summary').click();
  await filters.getByRole('button', { name: /^Guild(?:\s|$)/ }).click();
  await screenshot(page, 'labels-and-filters.png');

  await page.getByRole('searchbox', { name: 'Find a place' }).fill('no such place');
  await expect(page.getByText('No catalog places match these filters.')).toBeVisible();
  await screenshot(page, 'no-results.png');
  await page.getByRole('searchbox', { name: 'Find a place' }).fill('');
  await filters.getByRole('button', { name: 'Reset filters' }).click();

  await page.getByRole('searchbox', { name: 'Find a place' }).fill(POISON_PLACE_NAME);
  await page.getByRole('button', { name: new RegExp(`^${POISON_PLACE_NAME}`) }).click();
  await expect(page.getByRole('heading', { name: POISON_PLACE_NAME })).toBeVisible();
  await screenshot(page, 'selected-place.png');

  const progress = page.getByLabel('Place progress');
  const personalNote = progress.getByRole('textbox', { name: 'Personal note' });
  await personalNote.fill('Return after sunset.');
  await personalNote.blur();
  await expect(progress.getByRole('status')).toHaveText('Saved.');
  await progress.getByRole('button', { name: 'Active', exact: true }).click();
  await expect(progress.getByRole('button', { name: 'Active', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await screenshot(page, 'selected-place-progress.png');
  await page.getByRole('button', { name: 'Close place card' }).click();

  await page.locator('button.add-marker-tool').click();
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  await map.focus();
  await map.press('Enter');
  const markerEditor = page.getByLabel('Custom marker');
  const markerName = markerEditor.getByRole('textbox', { name: 'Marker name' });
  await expect(markerName).toBeFocused();
  await markerName.fill('Field note pin');
  await markerEditor.getByRole('textbox', { name: 'Personal note' }).fill('Hidden cache.');
  await markerEditor.getByRole('button', { name: 'Save marker' }).click();
  await expect(markerEditor.getByRole('status')).toHaveText('Saved.');
  await screenshot(page, 'personal-marker-editor.png');
  await markerEditor.getByRole('button', { name: 'Delete marker' }).click();
  await screenshot(page, 'personal-marker-delete.png');
  await markerEditor.getByRole('button', { name: 'Cancel' }).click();
  await page.getByRole('button', { name: 'Close personal marker card' }).click();

  const dataTools = page.locator('.user-data-tools--compact');
  await expect(dataTools.getByRole('button', { name: 'Download JSON backup' })).toBeVisible();
  await expect(dataTools.getByTitle('Import JSON backup')).toBeVisible();
  await screenshot(page, 'data-tools.png');
});

test('keeps the place card fixed while map tiles load', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'Tile loading layout runs once in the desktop project.');

  const probe = await installOfflineRoutes(page, { holdTiles: true });
  await openDataset(page, POISON_CARD_NAME, POISON_HEADING);
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  await expect(map).toHaveAttribute('data-basemap-pending', /^[1-9]\d*$/);
  await expect(page.getByText(/Loading map tiles/)).toHaveCount(0);

  await page.getByRole('searchbox', { name: 'Find a place' }).fill(POISON_PLACE_NAME);
  await page.getByRole('button', { name: new RegExp(`^${POISON_PLACE_NAME}`) }).click();
  const card = page.locator('article.place-card');
  await expect(card).toBeVisible();
  const before = await card.boundingBox();

  probe.releaseTiles();
  await waitForVisualReady(page);
  const after = await card.boundingBox();
  expect(before).not.toBeNull();
  expect(after).not.toBeNull();
  expect(Math.abs((after?.y ?? 0) - (before?.y ?? 0))).toBeLessThanOrEqual(1);
});

test('pins recoverable tile failure and successful retry', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'System-state snapshots are pinned once in the desktop project.');
  const probe = await installOfflineRoutes(page, { failTiles: true });
  await openDataset(page, POISON_CARD_NAME, POISON_HEADING);
  const alert = page.getByRole('alert').filter({ hasText: 'Map tiles failed to load' });
  await expect(alert).toBeVisible();
  await screenshot(page, 'tiles-error.png');
  probe.restoreTiles();
  await alert.getByRole('button', { name: 'Retry failed tiles' }).click();
  await waitForVisualReady(page);
  await screenshot(page, 'tiles-retried.png');
});

test('pins dataset-load failure, retry, and unpublished state', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'System-state snapshots are pinned once in the desktop project.');
  const probe = await installOfflineRoutes(page, { failDatasetAssets: true });
  await page.goto(`/?dataset=poison-song-26.08&region=tr-mainland&x=12288&y=-217088&z=6`);
  const alert = page.getByRole('alert');
  await expect(alert).toContainText('could not be opened');
  await expect(alert.getByRole('button', { name: 'Retry' })).toBeFocused();
  await screenshot(page, 'dataset-error.png');
  probe.restoreDatasetAssets();
  await alert.getByRole('button', { name: 'Retry' }).click();
  await waitForVisualReady(page);
  await screenshot(page, 'dataset-retried.png');

  await page.getByRole('button', { name: 'Back to maps' }).click();
  await page.unrouteAll({ behavior: 'wait' });
  await installOfflineRoutes(page, { blockOriginalManifest: true });
  await page.reload();
  await page.getByRole('button', { name: ORIGINAL_CARD_NAME }).click();
  await expect(page.getByRole('status')).toContainText('not been published locally');
  await screenshot(page, 'dataset-missing.png');
});

test('supports a real keyboard-only primary workflow and focus return', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'The complete keyboard path runs once in the desktop project.');
  await installOfflineRoutes(page);
  await page.goto('/');

  const originalCard = page.getByRole('button', { name: ORIGINAL_CARD_NAME });
  await tabTo(page, originalCard);
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: ORIGINAL_HEADING })).toBeVisible();

  const search = page.getByRole('searchbox', { name: 'Find a place' });
  await tabTo(page, search);
  await page.keyboard.type(ORIGINAL_PLACE_NAME);
  const filterSummary = page.locator('details.place-filter-drawer > summary');
  await tabTo(page, filterSummary);
  await page.keyboard.press('Enter');
  const guildFilter = page.locator('fieldset.place-filter-axis--types').getByRole('button', { name: /^Guild(?:\s|$)/ });
  await tabTo(page, guildFilter);
  await page.keyboard.press('Space');

  const result = page.getByRole('button', { name: new RegExp(`^${ORIGINAL_PLACE_NAME}`) });
  await tabTo(page, result);
  await page.keyboard.press('Enter');
  await expect(page.locator('article.place-card')).toBeFocused();
  const note = page.getByRole('textbox', { name: 'Personal note' });
  await tabTo(page, note);
  await page.keyboard.type('Keyboard route.');
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Place progress').getByRole('status')).toHaveText('Saved.');
  const activeStatus = page.getByLabel('Place progress').getByRole('button', { name: 'Active', exact: true });
  await tabTo(page, activeStatus, { reverse: true });
  await page.keyboard.press('Space');
  await expect(activeStatus).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('Escape');
  await expect(result).toBeFocused();

  const addMarker = page.locator('button.add-marker-tool');
  await tabTo(page, addMarker);
  await page.keyboard.press('Enter');
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  await tabTo(page, map, { reverse: true, limit: 8 });
  await page.keyboard.press('Enter');
  const markerName = page.getByRole('textbox', { name: 'Marker name' });
  await expect(markerName).toBeFocused();
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.type('Keyboard marker');
  const markerNote = page.getByLabel('Custom marker').getByRole('textbox', { name: 'Personal note' });
  await tabTo(page, markerNote);
  await page.keyboard.type('Created without a pointer.');
  const saveMarker = page.getByRole('button', { name: 'Save marker' });
  await tabTo(page, saveMarker);
  await page.keyboard.press('Enter');
  const deleteMarker = page.getByRole('button', { name: 'Delete marker' });
  await tabTo(page, deleteMarker);
  await page.keyboard.press('Enter');
  const cancelDelete = page.getByRole('button', { name: 'Cancel' });
  await expect(cancelDelete).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(deleteMarker).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(cancelDelete).toBeFocused();
  const confirmDelete = page.getByRole('button', { name: 'Yes, delete' });
  await tabTo(page, confirmDelete, { reverse: true, limit: 3 });
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Keyboard marker' })).toHaveCount(0);

  const compactDataTools = page.locator('.user-data-tools--compact');
  const importData = compactDataTools.getByLabel('Import JSON backup');
  await tabTo(page, importData, { reverse: true });
  await expect(importData).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(compactDataTools.getByRole('button', { name: 'Download JSON backup' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  const back = page.getByRole('button', { name: 'Back to maps' });
  await expect(back).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(originalCard).toBeFocused();
});

test('reflows at the 200% desktop equivalent without viewport overflow', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'The desktop 200% equivalent runs once.');
  await page.setViewportSize({ width: 640, height: 360 });
  await installOfflineRoutes(page);
  await openDataset(page, POISON_CARD_NAME, POISON_HEADING);
  await waitForVisualReady(page);
  await page.getByRole('searchbox', { name: 'Find a place' }).fill(POISON_PLACE_NAME);
  const result = page.getByRole('button', { name: new RegExp(`^${POISON_PLACE_NAME}`) });
  await result.focus();
  await page.keyboard.press('Enter');
  await expectNoViewportOverflow(page);
  await expect(page.getByRole('button', { name: 'Close place card' })).toBeInViewport();
  await screenshot(page, 'reflow-200-percent.png');
});

test('exposes minimum targets and keeps north up during touch pan, pinch, and tap', async ({ page }, testInfo) => {
  test.skip(!hasTouch(testInfo), 'Touch behavior runs only in touch projects.');
  await installOfflineRoutes(page);
  await openDataset(page, POISON_CARD_NAME, POISON_HEADING);
  await waitForVisualReady(page);
  const undersized = await page.locator(
    'button:visible, summary:visible, input:visible:not([type="file"]), textarea:visible',
  ).evaluateAll((elements) =>
    elements.flatMap((element) => {
      const rect = element.getBoundingClientRect();
      return rect.width + 0.01 < 24 || rect.height + 0.01 < 24
        ? [{ label: element.getAttribute('aria-label') ?? element.textContent?.trim() ?? element.tagName, width: rect.width, height: rect.height }]
        : [];
    }),
  );
  expect(undersized).toEqual([]);

  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  const box = await map.boundingBox();
  if (!box) throw new Error('Map has no touchable bounding box');
  const beforeZoom = Number(await map.getAttribute('data-view-z'));
  const zoomIn = page.getByRole('button', { name: 'Zoom in' });
  await zoomIn.tap();
  await zoomIn.tap();
  await zoomIn.tap();
  await expect.poll(async () => Number(await map.getAttribute('data-view-z'))).toBeGreaterThan(beforeZoom);

  const beforeCenter = {
    x: Number(await map.getAttribute('data-view-x')),
    y: Number(await map.getAttribute('data-view-y')),
  };
  const cdp = await page.context().newCDPSession(page);
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  const touchPoint = (offset: number) => ({
    x: x + offset,
    y: y + offset,
    id: 1,
    radiusX: 1,
    radiusY: 1,
    force: 1,
  });
  await cdp.send('Input.dispatchTouchEvent', {
    type: 'touchStart',
    touchPoints: [touchPoint(0)],
  });
  await page.waitForTimeout(50);
  for (const offset of [24, 48, 72, 96]) {
    await cdp.send('Input.dispatchTouchEvent', {
      type: 'touchMove',
      touchPoints: [touchPoint(offset)],
    });
    await page.waitForTimeout(32);
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(async () => ({
    x: Number(await map.getAttribute('data-view-x')),
    y: Number(await map.getAttribute('data-view-y')),
  })).not.toEqual(beforeCenter);
  const zoomBeforePinch = Number(await map.getAttribute('data-view-z'));
  const pinchPoints = (step: number) => {
    const angle = step * Math.PI / 16;
    const radius = 24 + step * 4;
    return [-1, 1].map((direction, id) => ({
      x: x + direction * radius * Math.cos(angle),
      y: y + direction * radius * Math.sin(angle),
      id,
      radiusX: 1,
      radiusY: 1,
      force: 1,
    }));
  };
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: pinchPoints(0) });
  for (let step = 1; step <= 8; step += 1) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: pinchPoints(step) });
    await page.waitForTimeout(32);
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(async () => Number(await map.getAttribute('data-view-z')))
    .toBeGreaterThan(zoomBeforePinch + 0.5);
  await expect(map).toHaveAttribute('data-view-rotation', '0');
  await page.locator('button.add-marker-tool').tap();
  await page.touchscreen.tap(x, y);
  await expect(page.getByLabel('Custom marker')).toBeVisible();
});

test('has no unwaived WCAG 2.2 AA or severe best-practice violations', async ({ page }, testInfo) => {
  test.skip(!isDesktop(testInfo), 'The complete axe state matrix runs once.');
  await installOfflineRoutes(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Choose your world' })).toBeVisible();
  await expectWcagClean(page, 'landing');

  await page.getByRole('button', { name: ORIGINAL_CARD_NAME }).click();
  await waitForVisualReady(page);
  await expectWcagClean(page, 'Original map');
  await page.getByRole('searchbox', { name: 'Find a place' }).fill(ORIGINAL_PLACE_NAME);
  await page.getByRole('button', { name: new RegExp(`^${ORIGINAL_PLACE_NAME}`) }).click();
  await expectWcagClean(page, 'Original selected place');
  await page.getByRole('button', { name: 'Close place card' }).click();
  await page.locator('button.add-marker-tool').click();
  const map = page.getByLabel('Interactive map in TES3 world coordinates');
  await map.focus();
  await map.press('Enter');
  await page.getByLabel('Custom marker').getByRole('button', { name: 'Delete marker' }).click();
  await expectWcagClean(page, 'custom-marker delete confirmation');

  await page.getByRole('button', { name: 'Back to maps' }).click();
  await page.getByRole('button', { name: POISON_CARD_NAME }).click();
  await waitForVisualReady(page);
  await expectWcagClean(page, 'Poison Song map');
});
