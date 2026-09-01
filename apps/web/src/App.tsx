import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { DatasetManifest } from '@morrowind-map/contracts';
import { presentDataset } from './data/datasetPresentation';
import {
  loadDatasets,
  type DatasetLoadIssue,
} from './data/loadDatasets';
import { Tes3Map } from './map/Tes3Map';
import {
  readMapUrl,
  writeMapUrl,
  type MapUrlState,
} from './navigation/mapUrlState';
import { PixelIcon } from './ui/PixelIcon';

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
    );
  }

  return (
    <main className="archive-shell">
      <header className="window-titlebar archive-titlebar">
        <div className="application-mark" aria-hidden="true">
          <PixelIcon name="archive" />
        </div>
        <div>
          <span className="titlebar-kicker">LOCAL CARTOGRAPHIC LOG</span>
          <h1>Morrowind Map Archive</h1>
        </div>
        <span className="titlebar-state">OFFLINE</span>
      </header>

      <section className="archive-intro" aria-labelledby="archive-heading">
        <p className="section-index">MAP ARCHIVE / 01</p>
        <h2 id="archive-heading" ref={landingHeadingRef} tabIndex={-1}>Choose a world</h2>
        <p>
          Two isolated English datasets: the original Morrowind, Tribunal and Bloodmoon world,
          and the current Tamriel Rebuilt Poison Song release. Each map keeps its own places and
          progress.
        </p>
      </section>

      {loadState.status === 'loading' ? (
        <div className="load-panel" role="status">
          <span className="load-indicator" aria-hidden="true" />
          {loadIsSlow ? 'Reading manifests… This is taking longer than usual.' : 'Reading manifests…'}
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
          <section className="dataset-grid" aria-label="Available maps">
            {loadState.datasets.map((dataset) => {
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
                className={`dataset-card dataset-card--${presentation.tone}`}
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
                <span className="card-rail" aria-hidden="true">
                  {presentation.plate}
                </span>
                <span className="card-body">
                  <span className="card-metadata">
                    <span>{presentation.era}</span>
                    <span>{presentation.scope}</span>
                  </span>
                  <span className="card-heading">{presentation.title}</span>
                  <span className="card-summary">{presentation.summary}</span>
                  <span className="card-survey" aria-hidden="true">
                    <i className="survey-axis survey-axis--x" />
                    <i className="survey-axis survey-axis--y" />
                    <i className="survey-origin" />
                  </span>
                  <span className="card-footer">
                    <span className="dataset-language">EN</span>
                    <span className={`readiness readiness--${presentation.readiness}`}>
                      {presentation.readiness}
                    </span>
                  </span>
                  <span className="snapshot-id" title={dataset.snapshotId}>
                    {dataset.snapshotId}
                  </span>
                </span>
                <span className="open-cue" aria-hidden="true">
                  OPEN <PixelIcon name="open" />
                </span>
              </button>
            );
            })}
          </section>
        </>
      ) : null}

      <footer className="archive-footer">
        <span>ENTER — open</span>
        <span>data: /datasets/index.json</span>
      </footer>
    </main>
  );
}
