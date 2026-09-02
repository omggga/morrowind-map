import { useEffect, useRef, useState } from 'react';
import {
  ANALYTICS_CONSENT_STORAGE_KEY,
  disableGoogleAnalytics,
  enableGoogleAnalytics,
  readAnalyticsConsent,
  storeAnalyticsConsent,
  type AnalyticsConsent,
} from './googleAnalytics';

interface AnalyticsConsentBannerProps {
  readonly showSettings?: boolean;
}

export function AnalyticsConsentBanner({ showSettings = true }: AnalyticsConsentBannerProps) {
  const [consent, setConsent] = useState<AnalyticsConsent | null>(readAnalyticsConsent);
  const [isOpen, setIsOpen] = useState(consent === null);
  const bannerRef = useRef<HTMLElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const shouldFocusBannerRef = useRef(false);
  const shouldRestoreFocusRef = useRef(false);

  useEffect(() => {
    if (consent === 'granted') {
      enableGoogleAnalytics();
    }
  }, [consent]);

  useEffect(() => {
    const syncConsent = (event: StorageEvent) => {
      if (event.key !== null && event.key !== ANALYTICS_CONSENT_STORAGE_KEY) {
        return;
      }

      const nextConsent = readAnalyticsConsent();
      if (nextConsent !== 'granted') {
        disableGoogleAnalytics();
      }
      setConsent(nextConsent);
      setIsOpen(nextConsent === null);
    };

    window.addEventListener('storage', syncConsent);
    return () => window.removeEventListener('storage', syncConsent);
  }, []);

  useEffect(() => {
    if (isOpen && shouldFocusBannerRef.current) {
      bannerRef.current?.focus();
      shouldFocusBannerRef.current = false;
      return;
    }

    if (!isOpen && shouldRestoreFocusRef.current && showSettings) {
      const settingsButton = settingsButtonRef.current;
      if (settingsButton) {
        settingsButton.focus();
        shouldRestoreFocusRef.current = false;
      }
      return;
    }

    if (!isOpen && shouldRestoreFocusRef.current && !showSettings) {
      const focusMap = () => {
        const target = document.querySelector<HTMLElement>(
          '.dataset-map-screen .back-button, .map-canvas',
        );
        if (!target) {
          return false;
        }
        target.focus({ preventScroll: true });
        shouldRestoreFocusRef.current = false;
        return true;
      };

      if (focusMap()) {
        return;
      }

      document.getElementById('landing-heading')?.focus({ preventScroll: true });
      const observer = new MutationObserver(() => {
        if (focusMap()) {
          observer.disconnect();
          window.clearTimeout(timeoutId);
        }
      });
      observer.observe(document.getElementById('root') ?? document.body, {
        childList: true,
        subtree: true,
      });
      const timeoutId = window.setTimeout(() => {
        observer.disconnect();
        const fallback = document.querySelector<HTMLElement>(
          '.error-panel button, #landing-heading',
        );
        fallback?.focus({ preventScroll: true });
        shouldRestoreFocusRef.current = false;
      }, 10_000);
      return () => {
        observer.disconnect();
        window.clearTimeout(timeoutId);
      };
    }

    return undefined;
  }, [isOpen, showSettings]);

  const chooseConsent = (nextConsent: AnalyticsConsent) => {
    storeAnalyticsConsent(nextConsent);
    if (nextConsent === 'denied') {
      disableGoogleAnalytics();
    }
    shouldRestoreFocusRef.current = true;
    setConsent(nextConsent);
    setIsOpen(false);
  };

  return (
    <>
      {isOpen ? (
        <aside
          ref={bannerRef}
          className="analytics-consent-banner"
          aria-labelledby="analytics-consent-title"
          tabIndex={-1}
        >
          <div className="analytics-consent-banner__copy">
            <h2 id="analytics-consent-title">Analytics cookies</h2>
            <p>
              Your map progress, notes, and markers stay on this device. If you agree,
              Google Analytics receives usage and device data and may set analytics
              cookies. Advertising storage stays disabled.{' '}
              <a
                href="https://business.safety.google/privacy/"
                target="_blank"
                rel="noreferrer"
              >
                How Google uses data
              </a>
              . You can change your choice later in Analytics settings.
            </p>
          </div>
          <div className="analytics-consent-banner__actions">
            <button type="button" onClick={() => chooseConsent('denied')}>
              Reject
            </button>
            <button type="button" onClick={() => chooseConsent('granted')}>
              Accept analytics
            </button>
          </div>
        </aside>
      ) : consent !== null && showSettings ? (
        <button
          ref={settingsButtonRef}
          className="analytics-settings-button"
          type="button"
          onClick={() => {
            shouldFocusBannerRef.current = true;
            shouldRestoreFocusRef.current = true;
            setIsOpen(true);
          }}
        >
          Analytics settings
        </button>
      ) : null}
    </>
  );
}
