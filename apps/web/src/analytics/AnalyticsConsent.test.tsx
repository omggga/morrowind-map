import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AnalyticsConsentBanner } from './AnalyticsConsent';
import {
  ANALYTICS_CONSENT_STORAGE_KEY,
  ANALYTICS_NOTICE_VERSION,
  GOOGLE_ANALYTICS_MEASUREMENT_ID,
} from './googleAnalytics';

type TestWindow = Window & typeof globalThis & {
  dataLayer?: Array<ArrayLike<unknown>>;
  gtag?: (...args: unknown[]) => void;
  'ga-disable-G-DGSNQXZ7HC'?: boolean;
};

const testWindow = window as TestWindow;

function analyticsScript(): HTMLScriptElement | null {
  return document.querySelector<HTMLScriptElement>('#google-analytics-gtag');
}

function storedConsent(): Record<string, unknown> {
  return JSON.parse(
    window.localStorage.getItem(ANALYTICS_CONSENT_STORAGE_KEY) ?? '{}',
  ) as Record<string, unknown>;
}

function expectStoredConsent(choice: 'denied' | 'granted'): void {
  const consent = storedConsent();

  expect(consent).toMatchObject({
    choice,
    noticeVersion: ANALYTICS_NOTICE_VERSION,
  });
  expect(typeof consent.decidedAt).toBe('string');
  expect(Number.isNaN(Date.parse(String(consent.decidedAt)))).toBe(false);
}

function seedStoredConsent(choice: 'denied' | 'granted'): string {
  const record = JSON.stringify({
    choice,
    decidedAt: '2026-09-02T00:00:00.000Z',
    noticeVersion: ANALYTICS_NOTICE_VERSION,
  });
  window.localStorage.setItem(ANALYTICS_CONSENT_STORAGE_KEY, record);
  return record;
}

function normalizedDataLayer(): unknown[][] {
  return (testWindow.dataLayer ?? []).map((entry) => Array.from(entry));
}

beforeEach(() => {
  window.localStorage.clear();
  analyticsScript()?.remove();
  delete testWindow.dataLayer;
  delete testWindow.gtag;
  delete testWindow['ga-disable-G-DGSNQXZ7HC'];
  document.cookie = '_ga=; Max-Age=0; Path=/';
});

afterEach(cleanup);

describe('AnalyticsConsentBanner', () => {
  it('does not contact or initialize Google before a choice and keeps rejection local', () => {
    render(<AnalyticsConsentBanner />);

    expect(screen.getByRole('complementary', { name: 'Analytics cookies' })).toBeVisible();
    expect(analyticsScript()).toBeNull();
    expect(testWindow.dataLayer).toBeUndefined();

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));

    expectStoredConsent('denied');
    expect(analyticsScript()).toBeNull();
    expect(testWindow.dataLayer).toBeUndefined();
    expect(screen.getByRole('button', { name: 'Analytics settings' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Analytics settings' })).toHaveFocus();
  });

  it('loads GA4 only after consent with advertising signals denied', async () => {
    render(<AnalyticsConsentBanner />);

    fireEvent.click(screen.getByRole('button', { name: 'Accept analytics' }));

    await waitFor(() => expect(analyticsScript()).not.toBeNull());
    expect(analyticsScript()?.src).toBe(
      `https://www.googletagmanager.com/gtag/js?id=${GOOGLE_ANALYTICS_MEASUREMENT_ID}`,
    );
    expect(analyticsScript()?.async).toBe(true);
    expectStoredConsent('granted');
    expect(normalizedDataLayer()).toEqual(expect.arrayContaining([
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
      ['config', GOOGLE_ANALYTICS_MEASUREMENT_ID, expect.objectContaining({
        allow_ad_personalization_signals: false,
        allow_google_signals: false,
      })],
    ]));
  });

  it('restores a prior choice and supports withdrawing it later', async () => {
    seedStoredConsent('granted');
    document.cookie = '_ga=fixture; Path=/';
    render(<AnalyticsConsentBanner />);

    await waitFor(() => expect(analyticsScript()).not.toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Analytics settings' }));
    expect(screen.getByRole('complementary', { name: 'Analytics cookies' })).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));

    expectStoredConsent('denied');
    expect(screen.getByRole('button', { name: 'Analytics settings' })).toHaveFocus();
    expect(testWindow['ga-disable-G-DGSNQXZ7HC']).toBe(true);
    expect(document.cookie).not.toContain('_ga=');
    expect(normalizedDataLayer().at(-1)).toEqual([
      'consent',
      'update',
      expect.objectContaining({ analytics_storage: 'denied' }),
    ]);
  });

  it('applies a withdrawal made in another tab', async () => {
    seedStoredConsent('granted');
    render(<AnalyticsConsentBanner />);

    await waitFor(() => expect(analyticsScript()).not.toBeNull());
    const deniedRecord = seedStoredConsent('denied');
    window.dispatchEvent(new StorageEvent('storage', {
      key: ANALYTICS_CONSENT_STORAGE_KEY,
      newValue: deniedRecord,
    }));

    await waitFor(() => {
      expect(testWindow['ga-disable-G-DGSNQXZ7HC']).toBe(true);
    });
    expect(screen.getByRole('button', { name: 'Analytics settings' })).toBeVisible();
    expect(normalizedDataLayer().at(-1)).toEqual([
      'consent',
      'update',
      expect.objectContaining({ analytics_storage: 'denied' }),
    ]);
  });

  it('asks again when a stored consent record is outdated', () => {
    window.localStorage.setItem(ANALYTICS_CONSENT_STORAGE_KEY, JSON.stringify({
      choice: 'granted',
      decidedAt: '2026-09-02T00:00:00.000Z',
      noticeVersion: ANALYTICS_NOTICE_VERSION + 1,
    }));

    render(<AnalyticsConsentBanner />);

    expect(screen.getByRole('complementary', { name: 'Analytics cookies' })).toBeVisible();
    expect(analyticsScript()).toBeNull();
  });

  it('hides settings off the landing page and restores focus when the map mounts', async () => {
    render(<AnalyticsConsentBanner showSettings={false} />);

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    expect(screen.queryByRole('button', { name: 'Analytics settings' })).not.toBeInTheDocument();

    const mapScreen = document.createElement('main');
    mapScreen.className = 'dataset-map-screen test-map-screen';
    const backButton = document.createElement('button');
    backButton.className = 'back-button';
    backButton.textContent = 'Versions';
    mapScreen.append(backButton);
    document.body.append(mapScreen);

    await waitFor(() => expect(backButton).toHaveFocus());
    mapScreen.remove();
  });
});
