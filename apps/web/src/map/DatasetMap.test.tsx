import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { DatasetManifest } from '@morrowind-map/contracts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DatasetAssetsInvalidError,
  DatasetAssetsMissingError,
  loadDataset,
} from '../data/loadDataset';
import { i18n } from '../i18n';
import { DatasetMap, MapTitlebar } from './DatasetMap';

vi.mock('../data/loadDataset', () => {
  class MissingError extends Error {
    override readonly name = 'DatasetAssetsMissingError';
  }

  class InvalidError extends Error {
    override readonly name = 'DatasetAssetsInvalidError';
  }

  return {
    DatasetAssetsInvalidError: InvalidError,
    DatasetAssetsMissingError: MissingError,
    loadDataset: vi.fn(),
  };
});

const dataset = {
  datasetId: 'poison-song-26.08',
  mapKey: 'tamriel-rebuilt',
  snapshotId: 'tr:poison-song-26.08:test',
  title: { en: 'Poison Song 26.08' },
  release: { name: 'Poison Song' },
  localization: {
    defaultLocale: 'en',
    locales: [{ locale: 'en', status: 'available', coverage: 1, fallbackLocale: null }],
  },
} as DatasetManifest;
const navigationState = {
  datasetId: dataset.datasetId,
  regionId: 'all',
  view: null,
  placeId: null,
  typeFilters: [],
  statusFilters: [],
} as const;

describe('MapTitlebar', () => {
  afterEach(cleanup);

  it.each([
    ['original', null],
    ['tamriel-rebuilt', 'https://www.nexusmods.com/morrowind/mods/42145'],
    ['project-cyrodiil', 'https://www.nexusmods.com/morrowind/mods/44922'],
    ['home-of-nords', 'https://www.nexusmods.com/morrowind/mods/44921'],
    ['azurian-isles', 'https://www.nexusmods.com/morrowind/mods/43749'],
  ] as const)('shows navigation, the %s title, its mod link and optional header tools', (mapKey, modUrl) => {
    render(
      <MapTitlebar
        dataset={{ ...dataset, mapKey }}
        onBack={vi.fn()}
        tools={<span>Data actions</span>}
      />,
    );

    expect(screen.getByRole('button', { name: 'Back to maps' })).toBeEnabled();
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toBeVisible();
    if (modUrl) {
      const link = within(heading).getByRole('link');
      expect(link).toHaveAttribute('href', modUrl);
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    } else {
      expect(within(heading).queryByRole('link')).not.toBeInTheDocument();
    }
    expect(screen.getByText('Data actions')).toBeVisible();
    expect(screen.queryByText('TR / TES3:WORLD')).not.toBeInTheDocument();
    expect(screen.queryByText('LOCAL')).not.toBeInTheDocument();
  });
});

describe('DatasetMap loading states', () => {
  beforeEach(async () => {
    vi.mocked(loadDataset).mockReset();
    await i18n.changeLanguage('en');
  });

  afterEach(cleanup);

  it('shows loading while the generic dataset bundle is pending', () => {
    vi.mocked(loadDataset).mockImplementation(() => new Promise(() => undefined));

    render(
      <DatasetMap
        dataset={dataset}
        datasetSnapshots={{}}
        navigationState={navigationState}
        navigationRevision={0}
        onNavigationChange={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('Opening the map dataset');
  });

  it('distinguishes an unpublished local dataset from a runtime error', async () => {
    vi.mocked(loadDataset).mockRejectedValue(
      new DatasetAssetsMissingError('Dataset does not contain a location catalog'),
    );

    render(
      <DatasetMap
        dataset={dataset}
        datasetSnapshots={{}}
        navigationState={navigationState}
        navigationRevision={0}
        onNavigationChange={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('This map has not been published locally yet');
    });
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Dataset does not contain a location catalog');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('does not offer a futile retry for invalid published artifacts', async () => {
    vi.mocked(loadDataset).mockRejectedValue(
      new DatasetAssetsInvalidError('Location catalog belongs to a different dataset snapshot'),
    );

    render(
      <DatasetMap
        dataset={dataset}
        datasetSnapshots={{}}
        navigationState={navigationState}
        navigationRevision={0}
        onNavigationChange={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('published map data is inconsistent');
    expect(alert).toHaveTextContent('different dataset snapshot');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(within(alert).getByRole('button', { name: 'Back to maps' })).toBeEnabled();
  });

  it('shows runtime errors and retries the complete bundle load', async () => {
    vi.mocked(loadDataset)
      .mockRejectedValueOnce(new Error('HTTP 503'))
      .mockImplementationOnce(() => new Promise(() => undefined));

    render(
      <DatasetMap
        dataset={dataset}
        datasetSnapshots={{}}
        navigationState={navigationState}
        navigationRevision={0}
        onNavigationChange={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 503');
    const retry = screen.getByRole('button', { name: 'Retry' });
    await waitFor(() => expect(retry).toHaveFocus());
    fireEvent.click(retry);
    fireEvent.click(retry);

    await waitFor(() => expect(loadDataset).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('alert')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('button', { name: 'Retrying…' })).toBeDisabled();
  });
});
