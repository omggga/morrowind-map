import { readFileSync } from 'node:fs';
import { resolve, sep } from 'node:path';
import { expect, test } from '@playwright/test';

import type {
  DatasetIndex, DatasetManifest, LocationCatalog, PlaceLocaleCatalog,
} from '../../packages/contracts/src/types';

const configuredRoot = process.env.MORROWIND_RENDER_PUBLIC_ROOT;
const root = resolve(configuredRoot ?? 'apps/web/public');

function readPublic<T>(url: string): T {
  const path = resolve(root, `.${url}`);
  if (!url.startsWith('/datasets/') || !path.startsWith(`${root}${sep}`)) {
    throw new Error(`Candidate URL escapes its public root: ${url}`);
  }
  return JSON.parse(readFileSync(path, 'utf8')) as T;
}

const entries = configuredRoot
  ? readPublic<DatasetIndex>('/datasets/index.json').datasets
  : [];

test('rendered candidate gate requires an explicit public tree', () => {
  test.skip(!configuredRoot, 'Used by the local render workflow.');
  expect(entries.length).toBeGreaterThanOrEqual(2);
  expect(entries.length).toBeLessThanOrEqual(3);
  const keys = entries.map((entry) => readPublic<DatasetManifest>(entry.manifestUrl).mapKey);
  expect(new Set(keys).size).toBe(entries.length);
  expect(keys).toContain('original');
  expect(keys).toContain('tamriel-rebuilt');
});

for (const entry of entries) {
  test(`renders and searches candidate ${entry.datasetId}`, async ({ page }) => {
    const manifest = readPublic<DatasetManifest>(entry.manifestUrl);
    const english = manifest.artifacts.locales.find(({ locale }) => locale === 'en');
    if (!manifest.artifacts.locations || !english?.artifact) {
      throw new Error('A rendered candidate must contain a catalog and English locale');
    }
    const locations = readPublic<LocationCatalog>(manifest.artifacts.locations.url);
    const locale = readPublic<PlaceLocaleCatalog>(english.artifact.url);
    const selected = locations.places.find((place) =>
      locale.places.some((name) => name.placeId === place.id && name.name.trim().length > 0));
    expect(selected).toBeDefined();
    const name = locale.places.find((place) => place.placeId === selected!.id)!.name;
    const failures: string[] = [];
    const external: string[] = [];
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.hostname !== '127.0.0.1' && url.hostname !== 'localhost') {
        external.push(url.origin);
        await route.abort();
      } else {
        await route.continue();
      }
    });
    page.on('response', (response) => {
      if (response.status() >= 400 && response.url().includes('/datasets/')) failures.push(response.url());
    });
    const query = new URLSearchParams({
      dataset: entry.datasetId, region: 'all',
      x: String(selected!.mapPosition[0]), y: String(selected!.mapPosition[1]),
      z: String(Math.max(5, selected!.minZoom)), place: selected!.id,
    });
    await page.goto(`/?${query}`);
    await expect(page.getByLabel('Interactive map in TES3 world coordinates')).toBeVisible();
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await page.getByRole('searchbox', { name: 'Find a place' }).fill(name);
    await expect(page.locator('button.place-result--selected')).toContainText(name);
    await expect.poll(() => page.locator('.dataset-basemap-layer canvas').evaluateAll((elements) =>
      elements.some((element) => {
        const canvas = element as HTMLCanvasElement;
        const context = canvas.getContext('2d');
        if (!context || !canvas.width || !canvas.height) return false;
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
        for (let offset = 3; offset < pixels.length; offset += 64) {
          if ((pixels[offset] ?? 0) > 0) return true;
        }
        return false;
      }))
    ).toBe(true);
    expect(failures).toEqual([]);
    expect(external).toEqual([]);
  });
}

const cyrodiil = entries.find((entry) =>
  readPublic<DatasetManifest>(entry.manifestUrl).mapKey === 'project-cyrodiil');

if (cyrodiil) {
  test('opens Cyrodiil closer without a redundant region filter and preserves shared views', async ({ page }, testInfo) => {
    const manifest = readPublic<DatasetManifest>(cyrodiil.manifestUrl);
    await page.goto('/');
    await page.getByRole('button', {
      name: `Open map: Project Cyrodiil — ${manifest.release.name}`,
    }).click();
    const map = page.getByLabel('Interactive map in TES3 world coordinates');
    await expect(map).toHaveAttribute('data-view-z', '3');
    await expect(map).toHaveAttribute('data-view-x', String(manifest.map.projection.center[0]));
    await expect(map).toHaveAttribute('data-view-y', String(manifest.map.projection.center[1]));
    await expect(page.getByRole('group', { name: 'Map section', exact: true })).toHaveCount(0);
    await expect(map).toHaveAttribute('data-basemap-loaded', /^[1-9]\d*$/);
    await expect(map).toHaveAttribute('data-basemap-pending', '0');
    await page.screenshot({ path: testInfo.outputPath('cyrodiil-default.png') });

    const query = new URLSearchParams({
      dataset: cyrodiil.datasetId, region: 'all',
      x: String(manifest.map.projection.center[0]),
      y: String(manifest.map.projection.center[1]), z: '5',
    });
    await page.goto(`/?${query}`);
    await expect(map).toHaveAttribute('data-view-z', '5');
  });
}
