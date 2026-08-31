import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadDatasets } from './loadDatasets';

vi.mock('@morrowind-map/contracts', () => ({
  parseDatasetIndex: (value: unknown) => value,
  parseDatasetManifest: (value: unknown) => value,
}));

describe('loadDatasets', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('rejects a manifest whose datasetId differs from its index entry', async () => {
    const responses = [
      {
        schemaVersion: 1,
        defaultDatasetId: 'expected',
        datasets: [{ datasetId: 'expected', manifestUrl: '/datasets/wrong.json', order: 0 }],
      },
      { datasetId: 'different' },
    ];

    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(responses.shift()),
        }),
      ),
    );

    await expect(loadDatasets(new AbortController().signal)).rejects.toThrow(
      'declares datasetId different; expected expected',
    );
  });
});
