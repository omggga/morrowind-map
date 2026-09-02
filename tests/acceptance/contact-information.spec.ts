import { expect, test } from '@playwright/test';
import {
  ANALYTICS_CONSENT_STORAGE_KEY,
  ANALYTICS_NOTICE_VERSION,
} from '../../apps/web/src/analytics/googleAnalytics';

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

test('opens contact information on the landing page and keeps it off the map', async ({ page }) => {
  await page.goto('/');

  const initialUrl = page.url();
  const trigger = page.getByRole('button', { name: 'Contact information', exact: true });
  await expect(trigger).toBeVisible();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');

  await trigger.click();

  const panel = page.getByRole('complementary', { name: 'Contact information' });
  await expect(panel).toBeVisible();
  await expect(panel).toBeFocused();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('link', { name: 'murashkin.alex@proton.me' }))
    .toHaveAttribute('href', 'mailto:murashkin.alex@proton.me');

  const github = page.getByRole('link', { name: 'github.com/omggga' });
  await expect(github).toHaveAttribute('href', 'https://github.com/omggga');
  await expect(github).toHaveAttribute('target', '_blank');
  await expect(github).toHaveAttribute('rel', /noopener/);
  await expect(github).toHaveAttribute('rel', /noreferrer/);
  expect(page.url()).toBe(initialUrl);

  await page.keyboard.press('Escape');
  await expect(panel).toBeHidden();
  await expect(trigger).toBeFocused();

  await trigger.click();
  await page.getByRole('button', { name: 'Close contact information' }).click();
  await expect(panel).toBeHidden();
  await expect(trigger).toBeFocused();

  await page.getByRole('button', { name: 'Open map: Morrowind Game of the Year' }).click();
  await expect(trigger).toBeHidden();
});
