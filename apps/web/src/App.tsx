import { useEffect, useRef, useState } from 'react';
import type { DatasetManifest } from '@morrowind-map/contracts';
import { presentDataset } from './data/datasetPresentation';
import { loadDatasets } from './data/loadDatasets';
import { Tes3Map } from './map/Tes3Map';

type LoadState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly datasets: readonly DatasetManifest[] }
  | { readonly status: 'error'; readonly message: string };

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown loading error';
}

export function App() {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [selectedDataset, setSelectedDataset] = useState<DatasetManifest | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const returnFocusIdRef = useRef<string | null>(null);
  const shouldReturnFocusRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();

    void loadDatasets(controller.signal)
      .then((datasets) => {
        if (controller.signal.aborted) {
          return;
        }
        setLoadState({ status: 'ready', datasets });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setLoadState({ status: 'error', message: errorMessage(error) });
        }
      });

    return () => controller.abort();
  }, [loadAttempt]);

  if (selectedDataset) {
    const datasets = loadState.status === 'ready' ? loadState.datasets : [selectedDataset];
    const datasetSnapshots = Object.fromEntries(
      datasets.map(({ datasetId, snapshotId }) => [datasetId, snapshotId]),
    );
    return (
      <Tes3Map
        dataset={selectedDataset}
        datasetSnapshots={datasetSnapshots}
        onBack={() => {
          shouldReturnFocusRef.current = true;
          setSelectedDataset(null);
        }}
      />
    );
  }

  return (
    <main className="archive-shell">
      <header className="window-titlebar archive-titlebar">
        <div className="application-mark" aria-hidden="true">
          M
        </div>
        <div>
          <span className="titlebar-kicker">LOCAL CARTOGRAPHIC LOG</span>
          <h1>Morrowind Map Archive</h1>
        </div>
        <span className="titlebar-state">OFFLINE</span>
      </header>

      <section className="archive-intro" aria-labelledby="archive-heading">
        <p className="section-index">MAP ARCHIVE / 01</p>
        <h2 id="archive-heading">Choose a world</h2>
        <p>
          Two isolated English datasets: the original Morrowind, Tribunal and Bloodmoon world,
          and the current Tamriel Rebuilt Poison Song release. Each map keeps its own places and
          progress.
        </p>
      </section>

      {loadState.status === 'loading' ? (
        <div className="load-panel" role="status">
          <span className="load-indicator" aria-hidden="true" />
          Reading manifests…
        </div>
      ) : null}

      {loadState.status === 'error' ? (
        <div className="error-panel" role="alert">
          <span>DATA ERROR</span>
          <p>{loadState.message}</p>
          <button
            type="button"
            onClick={() => {
              setLoadState({ status: 'loading' });
              setLoadAttempt((attempt) => attempt + 1);
            }}
          >
            Retry
          </button>
        </div>
      ) : null}

      {loadState.status === 'ready' ? (
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
                  returnFocusIdRef.current = event.currentTarget.dataset.datasetId ?? null;
                  setSelectedDataset(dataset);
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
                  OPEN ↗
                </span>
              </button>
            );
          })}
        </section>
      ) : null}

      <footer className="archive-footer">
        <span>ENTER — open</span>
        <span>data: /datasets/index.json</span>
      </footer>
    </main>
  );
}
