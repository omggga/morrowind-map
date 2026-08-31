import {
  parseDatasetIndex,
  parseDatasetManifest,
  type DatasetIndex,
  type DatasetManifest,
} from '@morrowind-map/contracts';

const DATASET_INDEX_URL = '/datasets/index.json';

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

export async function loadDatasets(signal: AbortSignal): Promise<DatasetManifest[]> {
  const index: DatasetIndex = parseDatasetIndex(
    await fetchJson(DATASET_INDEX_URL, signal),
  );
  const entries = [...index.datasets].sort((left, right) => left.order - right.order);

  return Promise.all(
    entries.map(async ({ datasetId, manifestUrl }) => {
      const source = await fetchJson(manifestUrl, signal);
      const manifest = parseDatasetManifest(source);

      if (manifest.datasetId !== datasetId) {
        throw new Error(
          `Manifest ${manifestUrl} declares datasetId ${manifest.datasetId}; expected ${datasetId}`,
        );
      }

      return manifest;
    }),
  );
}
