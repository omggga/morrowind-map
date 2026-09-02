import { expect, test } from '@playwright/test';
import {
  ANALYTICS_CONSENT_STORAGE_KEY,
  ANALYTICS_NOTICE_VERSION,
  GOOGLE_ANALYTICS_MEASUREMENT_ID,
} from '../../apps/web/src/analytics/googleAnalytics';

test('publishes the requested landing copy and search metadata', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveTitle('Morrowind Map - Your Cartographic log');
  await expect(page.locator('meta[name="description"]')).toHaveAttribute(
    'content',
    /interactive map, searchable locations, visit tracking, personal notes, and custom markers/,
  );
  await expect(page.locator('meta[name="keywords"]')).toHaveAttribute(
    'content',
    /Morrowind map.*Tamriel Rebuilt map.*TES3 map/,
  );
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    'href',
    'https://morrowindmap.com/',
  );
  await expect(page.getByRole('heading', { name: 'Choose your world' })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Open map: Morrowind Game of the Year' }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Open map: Tamriel Rebuilt — Poison Song' }),
  ).toBeVisible();
});

test('loads Google Analytics only after consent and honors later withdrawal', async ({ page }) => {
  let googleTagRequests = 0;
  await page.route('https://www.googletagmanager.com/gtag/js**', async (route) => {
    googleTagRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: '',
    });
  });

  await page.goto('/');

  await expect(page.getByRole('complementary', { name: 'Analytics cookies' })).toBeVisible();
  expect(googleTagRequests).toBe(0);
  expect(await page.locator('script[src*="googletagmanager.com"]').count()).toBe(0);
  expect(await page.evaluate(
    (storageKey) => window.localStorage.getItem(storageKey),
    ANALYTICS_CONSENT_STORAGE_KEY,
  )).toBeNull();

  await page.getByRole('button', { name: 'Accept analytics' }).click();

  await expect.poll(() => googleTagRequests).toBe(1);
  await expect(page.locator('#google-analytics-gtag')).toHaveAttribute(
    'src',
    `https://www.googletagmanager.com/gtag/js?id=${GOOGLE_ANALYTICS_MEASUREMENT_ID}`,
  );
  const grantedRecord = await page.evaluate(
    (storageKey) => window.localStorage.getItem(storageKey),
    ANALYTICS_CONSENT_STORAGE_KEY,
  );
  expect(JSON.parse(grantedRecord ?? '{}')).toEqual({
    choice: 'granted',
    decidedAt: expect.any(String),
    noticeVersion: ANALYTICS_NOTICE_VERSION,
  });
  const dataLayer = await page.evaluate(() => {
    const entries = (
      window as typeof window & { dataLayer?: Array<ArrayLike<unknown>> }
    ).dataLayer ?? [];
    return entries.map((entry) => Array.from(entry));
  });
  expect(dataLayer).toEqual(expect.arrayContaining([
    ['consent', 'default', expect.objectContaining({
      ad_personalization: 'denied',
      ad_storage: 'denied',
      ad_user_data: 'denied',
      analytics_storage: 'denied',
    })],
    ['consent', 'update', expect.objectContaining({
      ad_personalization: 'denied',
      ad_storage: 'denied',
      ad_user_data: 'denied',
      analytics_storage: 'granted',
    })],
  ]));

  await page.getByRole('button', { name: 'Analytics settings' }).click();
  await expect(page.getByRole('complementary', { name: 'Analytics cookies' })).toBeFocused();
  await page.getByRole('button', { name: 'Reject' }).click();
  await expect(page.getByRole('button', { name: 'Analytics settings' })).toBeFocused();

  const deniedRecord = await page.evaluate(
    (storageKey) => window.localStorage.getItem(storageKey),
    ANALYTICS_CONSENT_STORAGE_KEY,
  );
  expect(JSON.parse(deniedRecord ?? '{}')).toEqual({
    choice: 'denied',
    decidedAt: expect.any(String),
    noticeVersion: ANALYTICS_NOTICE_VERSION,
  });
  expect(await page.evaluate(() => (
    window as typeof window & { 'ga-disable-G-DGSNQXZ7HC'?: boolean }
  )['ga-disable-G-DGSNQXZ7HC'])).toBe(true);

  await page.reload();

  expect(await page.locator('script[src*="googletagmanager.com"]').count()).toBe(0);
  expect(googleTagRequests).toBe(1);
  const settings = page.getByRole('button', { name: 'Analytics settings' });
  await expect(settings).toBeVisible();

  await page.getByRole('button', { name: 'Open map: Morrowind Game of the Year' }).click();
  await expect(settings).toBeHidden();
});
