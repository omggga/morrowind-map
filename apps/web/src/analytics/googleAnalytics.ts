export const GOOGLE_ANALYTICS_MEASUREMENT_ID = 'G-DGSNQXZ7HC' as const;
export const ANALYTICS_CONSENT_STORAGE_KEY =
  'morrowind-map:analytics-consent:v1' as const;
export const ANALYTICS_NOTICE_VERSION = 1 as const;

export type AnalyticsConsent = 'denied' | 'granted';

const GOOGLE_ANALYTICS_SCRIPT_ID = 'google-analytics-gtag';
const GOOGLE_ANALYTICS_DISABLE_KEY = 'ga-disable-G-DGSNQXZ7HC' as const;

type GoogleAnalyticsWindow = Window & typeof globalThis & {
  dataLayer?: Array<ArrayLike<unknown>>;
  gtag?: (...args: unknown[]) => void;
  'ga-disable-G-DGSNQXZ7HC'?: boolean;
};

interface AnalyticsConsentRecord {
  choice: AnalyticsConsent;
  decidedAt: string;
  noticeVersion: typeof ANALYTICS_NOTICE_VERSION;
}

const DENIED_CONSENT = {
  ad_personalization: 'denied',
  ad_storage: 'denied',
  ad_user_data: 'denied',
  analytics_storage: 'denied',
} as const;

function googleWindow(): GoogleAnalyticsWindow {
  return window;
}

function ensureGtag(): (...args: unknown[]) => void {
  const target = googleWindow();
  target.dataLayer ??= [];
  target.gtag ??= function gtag() {
    // Google documents gtag as queueing the function's Arguments object.
    // eslint-disable-next-line prefer-rest-params
    target.dataLayer?.push(arguments);
  };
  return target.gtag;
}

function cookieDomainCandidates(hostname: string): string[] {
  const labels = hostname.split('.').filter(Boolean);
  return labels.slice(0, -1).map((_, index) => `.${labels.slice(index).join('.')}`);
}

function clearGoogleAnalyticsCookies(): void {
  const cookieNames = document.cookie
    .split(';')
    .map((cookie) => cookie.split('=', 1)[0]?.trim())
    .filter((name): name is string => Boolean(name?.startsWith('_ga')));

  for (const name of cookieNames) {
    document.cookie = `${name}=; Max-Age=0; Path=/; SameSite=Lax`;
    for (const domain of cookieDomainCandidates(window.location.hostname)) {
      document.cookie = `${name}=; Max-Age=0; Path=/; Domain=${domain}; SameSite=Lax`;
    }
  }
}

function isConsentRecord(value: unknown): value is AnalyticsConsentRecord {
  if (typeof value !== 'object' || value === null) {
    return false;
  }

  const record = value as Partial<AnalyticsConsentRecord>;
  return (
    (record.choice === 'granted' || record.choice === 'denied')
    && record.noticeVersion === ANALYTICS_NOTICE_VERSION
    && typeof record.decidedAt === 'string'
    && !Number.isNaN(Date.parse(record.decidedAt))
  );
}

export function readAnalyticsConsent(): AnalyticsConsent | null {
  try {
    const stored = window.localStorage.getItem(ANALYTICS_CONSENT_STORAGE_KEY);
    if (stored === null) {
      return null;
    }
    const record: unknown = JSON.parse(stored);
    return isConsentRecord(record) ? record.choice : null;
  } catch {
    return null;
  }
}

export function storeAnalyticsConsent(consent: AnalyticsConsent): void {
  try {
    window.localStorage.setItem(ANALYTICS_CONSENT_STORAGE_KEY, JSON.stringify({
      choice: consent,
      decidedAt: new Date().toISOString(),
      noticeVersion: ANALYTICS_NOTICE_VERSION,
    }));
  } catch {
    // The in-memory choice still applies for this page when storage is unavailable.
  }
}

export function enableGoogleAnalytics(): void {
  const target = googleWindow();
  const existingScript = document.getElementById(
    GOOGLE_ANALYTICS_SCRIPT_ID,
  ) as HTMLScriptElement | null;

  target[GOOGLE_ANALYTICS_DISABLE_KEY] = false;
  const gtag = ensureGtag();

  if (existingScript) {
    if (existingScript.dataset.analyticsConsent !== 'granted') {
      gtag('consent', 'update', {
        ...DENIED_CONSENT,
        analytics_storage: 'granted',
      });
      existingScript.dataset.analyticsConsent = 'granted';
    }
    return;
  }

  gtag('consent', 'default', DENIED_CONSENT);
  gtag('consent', 'update', {
    ...DENIED_CONSENT,
    analytics_storage: 'granted',
  });
  gtag('js', new Date());
  gtag('config', GOOGLE_ANALYTICS_MEASUREMENT_ID, {
    allow_ad_personalization_signals: false,
    allow_google_signals: false,
  });

  const script = document.createElement('script');
  script.id = GOOGLE_ANALYTICS_SCRIPT_ID;
  script.async = true;
  script.dataset.analyticsConsent = 'granted';
  script.src =
    `https://www.googletagmanager.com/gtag/js?id=${GOOGLE_ANALYTICS_MEASUREMENT_ID}`;
  document.head.append(script);
}

export function disableGoogleAnalytics(): void {
  const target = googleWindow();
  target[GOOGLE_ANALYTICS_DISABLE_KEY] = true;

  const existingScript = document.getElementById(
    GOOGLE_ANALYTICS_SCRIPT_ID,
  ) as HTMLScriptElement | null;
  if (target.gtag && existingScript) {
    target.gtag('consent', 'update', DENIED_CONSENT);
    existingScript.dataset.analyticsConsent = 'denied';
  }
  clearGoogleAnalyticsCookies();
}
