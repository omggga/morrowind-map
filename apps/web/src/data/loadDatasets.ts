import {
  parseDatasetIndex,
  parseDatasetManifest,
  type DatasetIndex,
  type DatasetManifest,
} from '@morrowind-map/contracts';

const DATASET_INDEX_URL = '/datasets/index.json';

export interface DatasetLoadIssue {
  readonly datasetId: string;
  readonly manifestUrl: string;
  readonly message: string;
}

export interface DatasetLoadResult {
  readonly datasets: readonly DatasetManifest[];
  readonly issues: readonly DatasetLoadIssue[];
}

type DatasetManifestLoadOutcome =
  | { readonly dataset: DatasetManifest }
  | { readonly issue: DatasetLoadIssue };

async function fetchJson(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Could not load ${url} (HTTP ${response.status})`);
  }

  return response.json() as Promise<unknown>;
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    error.name === 'AbortError'
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export async function loadDatasets(signal: AbortSignal): Promise<DatasetLoadResult> {
  const index: DatasetIndex = parseDatasetIndex(
    await fetchJson(DATASET_INDEX_URL, signal),
  );
  const entries = [...index.datasets].sort((left, right) => left.order - right.order);

  if (entries.length === 0) {
    throw new Error('Dataset index does not contain any datasets');
  }

  const outcomes = await Promise.all(
    entries.map(async ({ datasetId, manifestUrl }) => {
      try {
        const source = await fetchJson(manifestUrl, signal);
        const manifest = parseDatasetManifest(source);

        if (manifest.datasetId !== datasetId) {
          throw new Error(
            `Manifest ${manifestUrl} declares datasetId ${manifest.datasetId}; expected ${datasetId}`,
          );
        }

        return { dataset: manifest } satisfies DatasetManifestLoadOutcome;
      } catch (error: unknown) {
        if (isAbortError(error)) {
          throw error;
        }
        return {
          issue: {
            datasetId,
            manifestUrl,
            message: errorMessage(error),
          },
        } satisfies DatasetManifestLoadOutcome;
      }
    }),
  );

  const datasets: DatasetManifest[] = [];
  const issues: DatasetLoadIssue[] = [];
  outcomes.forEach((outcome) => {
    if ('dataset' in outcome) {
      datasets.push(outcome.dataset);
    } else {
      issues.push(outcome.issue);
    }
  });

  if (datasets.length === 0) {
    throw new Error(`Could not load any dataset manifests (${issues.length} failed)`);
  }

  return { datasets, issues };
}
