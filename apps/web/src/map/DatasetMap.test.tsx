import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { DatasetManifest } from '@morrowind-map/contracts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DatasetAssetsMissingError,
  loadDataset,
} from '../data/loadDataset';
import { i18n } from '../i18n';
import { DatasetMap } from './DatasetMap';

vi.mock('../data/loadDataset', () => {
  class MissingError extends Error {
    override readonly name = 'DatasetAssetsMissingError';
  }

  return {
    DatasetAssetsMissingError: MissingError,
    loadDataset: vi.fn(),
  };
});

const dataset = {
  datasetId: 'poison-song-26.08',
  mapKey: 'poison-song',
  snapshotId: 'tr:poison-song-26.08:test',
  title: { en: 'Poison Song 26.08' },
  localization: {
    defaultLocale: 'en',
    locales: [{ locale: 'en', status: 'available', coverage: 1, fallbackLocale: null }],
  },
} as DatasetManifest;

describe('DatasetMap loading states', () => {
  beforeEach(async () => {
    vi.mocked(loadDataset).mockReset();
    await i18n.changeLanguage('ru');
  });

  afterEach(cleanup);

  it('shows loading while the generic dataset bundle is pending', () => {
    vi.mocked(loadDataset).mockImplementation(() => new Promise(() => undefined));

    render(<DatasetMap dataset={dataset} datasetSnapshots={{}} onBack={vi.fn()} />);

    expect(screen.getByRole('status')).toHaveTextContent('Открываю набор данных карты');
  });

  it('distinguishes an unpublished local dataset from a runtime error', async () => {
    vi.mocked(loadDataset).mockRejectedValue(
      new DatasetAssetsMissingError('Dataset не содержит location catalog'),
    );

    render(<DatasetMap dataset={dataset} datasetSnapshots={{}} onBack={vi.fn()} />);

    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent('Эта карта ещё не опубликована локально');
    expect(status).toHaveTextContent('Dataset не содержит location catalog');
    expect(screen.queryByRole('button', { name: 'Повторить' })).not.toBeInTheDocument();
  });

  it('shows runtime errors and retries the complete bundle load', async () => {
    vi.mocked(loadDataset)
      .mockRejectedValueOnce(new Error('HTTP 503'))
      .mockImplementationOnce(() => new Promise(() => undefined));

    render(<DatasetMap dataset={dataset} datasetSnapshots={{}} onBack={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 503');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));

    await waitFor(() => expect(loadDataset).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('status')).toHaveTextContent('Открываю набор данных карты');
  });
});
