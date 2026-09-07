import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { DatasetManifest } from '@morrowind-map/contracts';
import { AnalyticsConsentBanner } from './analytics/AnalyticsConsent';
import { presentDataset } from './data/datasetPresentation';
import {
  loadDatasets,
  type DatasetLoadIssue,
} from './data/loadDatasets';
import { LandingContact } from './landing/LandingContact';
import { LandingMapBackdrop } from './map/LandingMapBackdrop';
import { Tes3Map } from './map/Tes3Map';
import {
  readMapUrl,
  writeMapUrl,
  type MapUrlState,
} from './navigation/mapUrlState';

type LoadState =
  | { readonly status: 'loading' }
  | {
      readonly status: 'ready';
      readonly datasets: readonly DatasetManifest[];
      readonly issues: readonly DatasetLoadIssue[];
      readonly retrying: boolean;
    }
  | { readonly status: 'error'; readonly message: string; readonly retrying: boolean };

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown loading error';
}

const LANDING_URL_STATE: MapUrlState = {
  datasetId: null,
  regionId: 'all',
  view: null,
  placeId: null,
  typeFilters: [],
  statusFilters: [],
};

type NavigationMode = 'push' | 'replace';

function mapUrlStatesEqual(left: MapUrlState, right: MapUrlState): boolean {
  return left.datasetId === right.datasetId &&
    left.regionId === right.regionId &&
    left.placeId === right.placeId &&
    left.typeFilters.length === right.typeFilters.length &&
    left.typeFilters.every((value, index) => value === right.typeFilters[index]) &&
    left.statusFilters.length === right.statusFilters.length &&
    left.statusFilters.every((value, index) => value === right.statusFilters[index]) &&
    (left.view === right.view ||
      (left.view !== null &&
        right.view !== null &&
        left.view.center[0] === right.view.center[0] &&
        left.view.center[1] === right.view.center[1] &&
        left.view.zoom === right.view.zoom));
}

function landingChoices(datasets: readonly DatasetManifest[]): readonly DatasetManifest[] {
  const original = datasets.find(({ mapKey }) => mapKey === 'original');
  const tamrielRebuilt = datasets.find(({ mapKey }) => mapKey === 'tamriel-rebuilt');
  const projectCyrodiil = datasets.find(({ mapKey }) => mapKey === 'project-cyrodiil');
  return [original, tamrielRebuilt, projectCyrodiil].filter(
    (dataset): dataset is DatasetManifest => dataset !== undefined,
  );
}

function landingBackdropDataset(
  datasets: readonly DatasetManifest[],
): DatasetManifest | null {
  return datasets.find(({ mapKey }) => mapKey === 'original') ??
    datasets.find(({ mapKey }) => mapKey === 'tamriel-rebuilt') ??
    null;
}

export function App() {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [navigationState, setNavigationState] = useState<MapUrlState>(() =>
    readMapUrl(new URL(window.location.href)),
  );
  const [navigationRevision, setNavigationRevision] = useState(0);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadIsSlow, setLoadIsSlow] = useState(false);
  const [focusRecoveredContent, setFocusRecoveredContent] = useState(false);
  const loadInFlightRef = useRef(false);
  const retryRequestedRef = useRef(false);
  const retryButtonRef = useRef<HTMLButtonElement>(null);
  const landingHeadingRef = useRef<HTMLHeadingElement>(null);
  const returnFocusIdRef = useRef<string | null>(null);
  const shouldReturnFocusRef = useRef(false);

  useLayoutEffect(() => {
    if (navigationState.datasetId === null) {
      return;
    }
    document.documentElement.scrollLeft = 0;
    document.documentElement.scrollTop = 0;
    document.body.scrollLeft = 0;
    document.body.scrollTop = 0;
  }, [navigationState.datasetId]);

  const commitNavigationState = useCallback((nextState: MapUrlState, mode: NavigationMode) => {
    const currentUrl = new URL(window.location.href);
    const nextUrl = writeMapUrl(currentUrl, nextState);
    const canonicalState = readMapUrl(nextUrl);

    if (nextUrl.href !== currentUrl.href) {
      const relativeUrl = `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
      if (mode === 'push') {
        window.history.pushState(null, '', relativeUrl);
      } else {
        window.history.replaceState(null, '', relativeUrl);
      }
    }
    setNavigationState((current) =>
      mapUrlStatesEqual(current, canonicalState) ? current : canonicalState,
    );
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadInFlightRef.current = true;
    const slowTimer = window.setTimeout(() => setLoadIsSlow(true), 800);

    void loadDatasets(controller.signal)
      .then(({ datasets, issues }) => {
        if (controller.signal.aborted) {
          return;
        }
        loadInFlightRef.current = false;
        window.clearTimeout(slowTimer);
        setLoadState({ status: 'ready', datasets, issues, retrying: false });
        const shouldFocusRecoveredContent = retryRequestedRef.current && issues.length === 0;
        retryRequestedRef.current = false;
        if (shouldFocusRecoveredContent) {
          setFocusRecoveredContent(true);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          loadInFlightRef.current = false;
          window.clearTimeout(slowTimer);
          retryRequestedRef.current = false;
          setLoadState({ status: 'error', message: errorMessage(error), retrying: false });
        }
      });

    return () => {
      controller.abort();
      window.clearTimeout(slowTimer);
      loadInFlightRef.current = false;
    };
  }, [loadAttempt]);

  useEffect(() => {
    const shouldFocusRetry = loadState.status !== 'loading' &&
      !loadState.retrying &&
      (loadState.status === 'error' || loadState.issues.length > 0);
    if (!shouldFocusRetry) {
      return undefined;
    }
    const animationFrame = window.requestAnimationFrame(() => {
      retryButtonRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [loadState]);

  const retryDatasets = () => {
    if (loadInFlightRef.current || loadState.status === 'loading') {
      return;
    }
    loadInFlightRef.current = true;
    retryRequestedRef.current = true;
    setLoadIsSlow(false);
    setFocusRecoveredContent(false);
    setLoadState({ ...loadState, retrying: true });
    setLoadAttempt((attempt) => attempt + 1);
  };

  useEffect(() => {
    const handlePopState = () => {
      const nextState = readMapUrl(new URL(window.location.href));
      setNavigationState((current) => {
        if (current.datasetId !== null && nextState.datasetId === null) {
          returnFocusIdRef.current = current.datasetId;
          shouldReturnFocusRef.current = true;
        }
        return mapUrlStatesEqual(current, nextState) ? current : nextState;
      });
      setNavigationRevision((revision) => revision + 1);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const selectedDataset = loadState.status === 'ready' && navigationState.datasetId !== null
    ? loadState.datasets.find(({ datasetId }) => datasetId === navigationState.datasetId) ?? null
    : null;

  useEffect(() => {
    if (
      !focusRecoveredContent ||
      loadState.status !== 'ready' ||
      loadState.issues.length > 0 ||
      (navigationState.datasetId !== null && selectedDataset === null)
    ) {
      return undefined;
    }
    const animationFrame = window.requestAnimationFrame(() => {
      if (navigationState.datasetId === null) {
        landingHeadingRef.current?.focus({ preventScroll: true });
      }
      setFocusRecoveredContent(false);
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [focusRecoveredContent, loadState, navigationState.datasetId, selectedDataset]);

  useEffect(() => {
    const currentUrl = new URL(window.location.href);
    const parserCanonicalState = navigationState.datasetId === null
      ? LANDING_URL_STATE
      : navigationState;
    const parserNeedsCanonicalization =
      writeMapUrl(currentUrl, parserCanonicalState).href !== currentUrl.href;
    const datasetIsUnknown =
      loadState.status === 'ready' &&
      navigationState.datasetId !== null &&
      selectedDataset === null &&
      !loadState.issues.some(({ datasetId }) => datasetId === navigationState.datasetId);
    if (parserNeedsCanonicalization || datasetIsUnknown) {
      const timeoutId = window.setTimeout(() => {
        commitNavigationState(
          datasetIsUnknown ? LANDING_URL_STATE : parserCanonicalState,
          'replace',
        );
      }, 0);
      return () => window.clearTimeout(timeoutId);
    }
    return undefined;
  }, [
    commitNavigationState,
    loadState,
    navigationRevision,
    navigationState,
    selectedDataset,
  ]);

  if (selectedDataset && loadState.status === 'ready') {
    const datasetSnapshots = Object.fromEntries(
      loadState.datasets.map(({ datasetId, snapshotId }) => [datasetId, snapshotId]),
    );
    return (
      <>
        <Tes3Map
          key={selectedDataset.datasetId}
          dataset={selectedDataset}
          datasetSnapshots={datasetSnapshots}
          focusMapOnMount={focusRecoveredContent}
          navigationState={navigationState}
          navigationRevision={navigationRevision}
          onNavigationChange={commitNavigationState}
          onBack={() => {
            returnFocusIdRef.current = selectedDataset.datasetId;
            shouldReturnFocusRef.current = true;
            commitNavigationState(LANDING_URL_STATE, 'push');
          }}
        />
        <AnalyticsConsentBanner showSettings={false} />
      </>
    );
  }

  const availableChoices = loadState.status === 'ready'
    ? landingChoices(loadState.datasets)
    : [];
  const backdropDataset = loadState.status === 'ready'
    ? landingBackdropDataset(loadState.datasets)
    : null;

  return (
    <>
      <main className="landing-screen">
      <LandingMapBackdrop
        key={backdropDataset === null
          ? 'fallback'
          : `${backdropDataset.datasetId}:${backdropDataset.snapshotId}`}
        dataset={backdropDataset}
      />
      <div className="landing-atmosphere" aria-hidden="true" />
      <div className="landing-layout">
      <section className="landing-content" aria-labelledby="landing-heading">
        <h1
          id="landing-heading"
          className="landing-heading"
          ref={landingHeadingRef}
          tabIndex={-1}
        >
          Choose your world
        </h1>

        {loadState.status === 'loading' ? (
          <div className="load-panel" role="status">
            <span className="load-indicator" aria-hidden="true" />
            {loadIsSlow
              ? 'Reading manifests… This is taking longer than usual.'
              : 'Reading manifests…'}
          </div>
        ) : null}

        {loadState.status === 'error' ? (
          <div className="error-panel" role="alert" aria-busy={loadState.retrying}>
            <span>DATA ERROR</span>
            <p>{loadState.message}</p>
            <button
              ref={retryButtonRef}
              type="button"
              disabled={loadState.retrying}
              onClick={retryDatasets}
            >
              {loadState.retrying ? 'Retrying…' : 'Retry'}
            </button>
          </div>
        ) : null}

        {loadState.status === 'ready' ? (
          <>
            {loadState.issues.length > 0 ? (
              <div
                className="error-panel error-panel--partial"
                role="alert"
                aria-busy={loadState.retrying}
              >
                <span>PARTIAL CATALOG</span>
                <p>
                  {loadState.issues.length === 1
                    ? 'One map manifest is unavailable. The available map remains usable.'
                    : `${loadState.issues.length} map manifests are unavailable. Available maps remain usable.`}
                </p>
                {loadState.retrying && loadIsSlow ? (
                  <p>The manifest retry is still in progress.</p>
                ) : null}
                <ul>
                  {loadState.issues.map((issue) => (
                    <li key={`${issue.datasetId}\0${issue.manifestUrl}`}>
                      <strong>{issue.datasetId}</strong>: {issue.message}
                    </li>
                  ))}
                </ul>
                <button
                  ref={retryButtonRef}
                  type="button"
                  disabled={loadState.retrying}
                  onClick={retryDatasets}
                >
                  {loadState.retrying ? 'Retrying…' : 'Retry unavailable maps'}
                </button>
              </div>
            ) : null}
            <section className="landing-choice-list" aria-label="Available maps">
              {availableChoices.map((dataset) => {
                const presentation = presentDataset(dataset);

                return (
                  <button
                    key={dataset.datasetId}
                    ref={(node) => {
                      if (
                        node &&
                        shouldReturnFocusRef.current &&
                        returnFocusIdRef.current === dataset.datasetId
                      ) {
                        node.focus();
                        shouldReturnFocusRef.current = false;
                      }
                    }}
                    className="dataset-choice"
                    type="button"
                    data-dataset-id={dataset.datasetId}
                    onClick={(event) => {
                      const datasetId = event.currentTarget.dataset.datasetId ?? dataset.datasetId;
                      returnFocusIdRef.current = datasetId;
                      commitNavigationState(
                        {
                          datasetId,
                          regionId: 'all',
                          view: null,
                          placeId: null,
                          typeFilters: [],
                          statusFilters: [],
                        },
                        'push',
                      );
                    }}
                    aria-label={`Open map: ${presentation.title}`}
                  >
                    <span className="dataset-choice__title">{presentation.title}</span>
                    <span className="dataset-choice__arrow" aria-hidden="true">→</span>
                  </button>
                );
              })}
            </section>
          </>
        ) : null}
      </section>
      <section className="landing-about" aria-labelledby="landing-about-heading">
        <h2 id="landing-about-heading">Interactive maps for The Elder Scrolls III: Morrowind</h2>
        <p>
          Explore detailed maps, mark places as visited, and add your own markers and notes
          {' '}— on desktop or phone.
        </p>
        <p>
          Discover high-resolution maps of Morrowind Game of the Year, Tamriel Rebuilt
          {' '}— Poison Song, and Project Cyrodiil — Abecean Shores.
        </p>
        <p>
          Search for towns, caves, ruins, and dungeon entrances, and find your next destination.
        </p>
      </section>
      </div>
      {navigationState.datasetId === null ? <LandingContact /> : null}
      </main>
      <AnalyticsConsentBanner showSettings={navigationState.datasetId === null} />
    </>
  );
}
