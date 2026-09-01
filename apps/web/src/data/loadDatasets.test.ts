import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadDatasets } from './loadDatasets';

vi.mock('@morrowind-map/contracts', () => ({
  parseDatasetIndex: (value: unknown) => {
    if (typeof value === 'object' && value !== null && 'malformed' in value) {
      throw new Error('Malformed dataset index');
    }
    return value;
  },
  parseDatasetManifest: (value: unknown) => {
    if (typeof value === 'object' && value !== null && 'malformed' in value) {
      throw new Error('Malformed dataset manifest');
    }
    return value;
  },
}));

function jsonResponse(value: unknown) {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(value),
  };
}

function errorResponse(status: number) {
  return {
    ok: false,
    status,
    json: () => Promise.resolve({}),
  };
}

describe('loadDatasets', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('returns successful manifests in index order', async () => {
    const index = {
      schemaVersion: 1,
      defaultDatasetId: 'first',
      datasets: [
        { datasetId: 'second', manifestUrl: '/datasets/second.json', order: 1 },
        { datasetId: 'first', manifestUrl: '/datasets/first.json', order: 0 },
      ],
    };

    vi.stubGlobal(
      'fetch',
      vi.fn()
        .mockResolvedValueOnce(jsonResponse(index))
        .mockResolvedValueOnce(jsonResponse({ datasetId: 'first' }))
        .mockResolvedValueOnce(jsonResponse({ datasetId: 'second' })),
    );

    await expect(loadDatasets(new AbortController().signal)).resolves.toEqual({
      datasets: [{ datasetId: 'first' }, { datasetId: 'second' }],
      issues: [],
    });
  });

  it('keeps a healthy manifest when another manifest fails', async () => {
    const index = {
      schemaVersion: 1,
      defaultDatasetId: 'healthy',
      datasets: [
        { datasetId: 'healthy', manifestUrl: '/datasets/healthy.json', order: 0 },
        { datasetId: 'failed', manifestUrl: '/datasets/failed.json', order: 1 },
      ],
    };

    vi.stubGlobal(
      'fetch',
      vi.fn()
        .mockResolvedValueOnce(jsonResponse(index))
        .mockResolvedValueOnce(jsonResponse({ datasetId: 'healthy' }))
        .mockResolvedValueOnce(errorResponse(503)),
    );

    await expect(loadDatasets(new AbortController().signal)).resolves.toEqual({
      datasets: [{ datasetId: 'healthy' }],
      issues: [{
        datasetId: 'failed',
        manifestUrl: '/datasets/failed.json',
        message: 'Could not load /datasets/failed.json (HTTP 503)',
      }],
    });
  });

  it('reports a malformed manifest as an issue', async () => {
    const index = {
      schemaVersion: 1,
      defaultDatasetId: 'healthy',
      datasets: [
        { datasetId: 'healthy', manifestUrl: '/datasets/healthy.json', order: 0 },
        { datasetId: 'malformed', manifestUrl: '/datasets/malformed.json', order: 1 },
      ],
    };

    vi.stubGlobal(
      'fetch',
      vi.fn()
        .mockResolvedValueOnce(jsonResponse(index))
        .mockResolvedValueOnce(jsonResponse({ datasetId: 'healthy' }))
        .mockResolvedValueOnce(jsonResponse({ malformed: true })),
    );

    await expect(loadDatasets(new AbortController().signal)).resolves.toEqual({
      datasets: [{ datasetId: 'healthy' }],
      issues: [{
        datasetId: 'malformed',
        manifestUrl: '/datasets/malformed.json',
        message: 'Malformed dataset manifest',
      }],
    });
  });

  it('treats a non-empty index with no usable manifests as fatal', async () => {
    const index = {
      schemaVersion: 1,
      defaultDatasetId: 'first',
      datasets: [
        { datasetId: 'first', manifestUrl: '/datasets/first.json', order: 0 },
        { datasetId: 'second', manifestUrl: '/datasets/second.json', order: 1 },
      ],
    };

    vi.stubGlobal(
      'fetch',
      vi.fn()
        .mockResolvedValueOnce(jsonResponse(index))
        .mockResolvedValueOnce(errorResponse(503))
        .mockResolvedValueOnce(jsonResponse({ malformed: true })),
    );

    await expect(loadDatasets(new AbortController().signal)).rejects.toThrow(
      'Could not load any dataset manifests (2 failed)',
    );
  });

  it('treats an empty index as fatal', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(jsonResponse({
        schemaVersion: 1,
        defaultDatasetId: 'missing',
        datasets: [],
      })),
    );

    await expect(loadDatasets(new AbortController().signal)).rejects.toThrow(
      'Dataset index does not contain any datasets',
    );
  });

  it('propagates an AbortError from a manifest load', async () => {
    const abortError = new DOMException('The operation was aborted', 'AbortError');
    vi.stubGlobal(
      'fetch',
      vi.fn()
        .mockResolvedValueOnce(jsonResponse({
          schemaVersion: 1,
          defaultDatasetId: 'aborted',
          datasets: [
            { datasetId: 'aborted', manifestUrl: '/datasets/aborted.json', order: 0 },
          ],
        }))
        .mockRejectedValueOnce(abortError),
    );

    await expect(loadDatasets(new AbortController().signal)).rejects.toBe(abortError);
  });

  it('keeps a malformed index fatal', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(jsonResponse({ malformed: true })),
    );

    await expect(loadDatasets(new AbortController().signal)).rejects.toThrow(
      'Malformed dataset index',
    );
  });
});
