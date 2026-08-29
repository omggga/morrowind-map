import { useEffect, useRef, useState } from 'react';
import type { DatasetManifest } from '@morrowind-map/contracts';
import { presentDataset } from './data/datasetPresentation';
import { loadDatasets } from './data/loadDatasets';
import { Tes3Map } from './map/Tes3Map';
import { userDatabase } from './storage/database';
import {
  adoptLegacyDatasetSnapshots,
  ensureDatasetSnapshot,
} from './storage/userData';

interface LegacyDatasetBinding {
  readonly dataset: DatasetManifest;
  readonly storedRecords: number;
}

type LoadState =
  | { readonly status: 'loading' }
  | {
      readonly status: 'ready';
      readonly datasets: readonly DatasetManifest[];
      readonly legacyBindings: readonly LegacyDatasetBinding[];
    }
  | { readonly status: 'error'; readonly message: string };

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Неизвестная ошибка загрузки';
}

export function App() {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [selectedDataset, setSelectedDataset] = useState<DatasetManifest | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [adoptingSnapshots, setAdoptingSnapshots] = useState(false);
  const returnFocusIdRef = useRef<string | null>(null);
  const shouldReturnFocusRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();

    void loadDatasets(controller.signal)
      .then(async (datasets) => {
        const readiness = await Promise.all(
          datasets.map(async (dataset) => ({
            dataset,
            readiness: await ensureDatasetSnapshot(
              userDatabase,
              dataset.datasetId,
              dataset.snapshotId,
            ),
          })),
        );
        if (controller.signal.aborted) {
          return;
        }
        setLoadState({
          status: 'ready',
          datasets,
          legacyBindings: readiness.flatMap(({ dataset, readiness: result }) =>
            result.kind === 'needs-legacy-adoption'
              ? [{ dataset, storedRecords: result.storedRecords }]
              : [],
          ),
        });
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
        <p className="section-index">КАРТОТЕКА / 01</p>
        <h2 id="archive-heading">Выберите версию мира</h2>
        <p>
          Каждый профиль — отдельный снимок координат, локаций и прогресса. Original
          использует локальные MIM-растры и EN/RU, а Poison Song — собственную WebP-карту
          и английский каталог Tamriel Rebuilt.
        </p>
      </section>

      {loadState.status === 'loading' ? (
        <div className="load-panel" role="status">
          <span className="load-indicator" aria-hidden="true" />
          Читаю manifests…
        </div>
      ) : null}

      {loadState.status === 'error' ? (
        <div className="error-panel" role="alert">
          <span>ОШИБКА ДАННЫХ</span>
          <p>{loadState.message}</p>
          <button
            type="button"
            onClick={() => {
              setLoadState({ status: 'loading' });
              setLoadAttempt((attempt) => attempt + 1);
            }}
          >
            Повторить
          </button>
        </div>
      ) : null}

      {loadState.status === 'ready' && loadState.legacyBindings.length > 0 ? (
        <section className="error-panel snapshot-adoption-panel" role="status" aria-live="polite">
          <span>ЛОКАЛЬНЫЕ ДАННЫЕ</span>
          <h2>Привязать прежние записи к снимкам карт?</h2>
          <p>
            Эти записи появились до строгой привязки к snapshot. Подтвердите её один раз,
            прежде чем открывать карты или создавать резервную копию.
          </p>
          <ul>
            {loadState.legacyBindings.map(({ dataset, storedRecords }) => (
              <li key={dataset.datasetId}>
                <strong>{dataset.title.ru ?? dataset.title.en}</strong>
                <small>{dataset.snapshotId} · {storedRecords} записей</small>
              </li>
            ))}
          </ul>
          <button
            type="button"
            disabled={adoptingSnapshots}
            onClick={() => {
              setAdoptingSnapshots(true);
              void adoptLegacyDatasetSnapshots(
                userDatabase,
                loadState.legacyBindings.map(({ dataset }) => ({
                  datasetId: dataset.datasetId,
                  snapshotId: dataset.snapshotId,
                })),
              )
                .then(() => {
                  setLoadState({ ...loadState, legacyBindings: [] });
                  setAdoptingSnapshots(false);
                })
                .catch((error: unknown) => {
                  setAdoptingSnapshots(false);
                  setLoadState({ status: 'error', message: errorMessage(error) });
                });
            }}
          >
            {adoptingSnapshots ? 'Привязываю…' : 'Привязать и продолжить'}
          </button>
        </section>
      ) : null}

      {loadState.status === 'ready' && loadState.legacyBindings.length === 0 ? (
        <section className="dataset-grid" aria-label="Доступные версии карты">
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
                aria-label={`Открыть карту: ${presentation.title}`}
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
                    <span className="language-list" aria-label="Языки данных">
                      {presentation.languages.map((language) => (
                        <span key={language}>{language}</span>
                      ))}
                    </span>
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
        <span>ENTER — открыть</span>
        <span>данные: /datasets/index.json</span>
      </footer>
    </main>
  );
}
