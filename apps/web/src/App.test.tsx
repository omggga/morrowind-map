import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MapUrlState } from './navigation/mapUrlState';
import { App } from './App';

vi.mock('@morrowind-map/contracts', () => ({
  parseDatasetIndex: (value: unknown) => value,
  parseDatasetManifest: (value: unknown) => value,
}));

vi.mock('./map/Tes3Map', () => ({
  Tes3Map: ({
    dataset,
    navigationState,
    focusMapOnMount,
    onNavigationChange,
    onBack,
  }: {
    dataset: { datasetId: string; title: { en: string } };
    navigationState: MapUrlState;
    focusMapOnMount?: boolean;
    onNavigationChange: (
      state: MapUrlState,
      mode: 'push' | 'replace',
    ) => void;
    onBack: () => void;
  }) => (
    <section
      aria-label="mock map"
      tabIndex={-1}
      ref={(node) => {
        if (node && focusMapOnMount) {
          node.focus();
        }
      }}
    >
      <h1>{dataset.title.en}</h1>
      <output aria-label="mock navigation state">
        {JSON.stringify(navigationState)}
      </output>
      <button
        type="button"
        onClick={() =>
          onNavigationChange(
            {
              datasetId: dataset.datasetId,
              regionId: 'vvardenfell',
              view: { center: [1234.4, -5678.6], zoom: 4.126 },
              placeId: 'fixture-place',
              typeFilters: navigationState.typeFilters,
              statusFilters: navigationState.statusFilters,
            },
            'replace',
          )
        }
      >
        Update map URL
      </button>
      <button type="button" onClick={onBack}>
        Versions
      </button>
    </section>
  ),
}));

vi.mock('./map/LandingMapBackdrop', () => ({
  LandingMapBackdrop: ({ dataset }: { dataset: { datasetId: string } | null }) => (
    <div
      data-testid="landing-backdrop"
      data-dataset-id={dataset?.datasetId ?? 'fallback'}
    />
  ),
}));

const indexFixture = {
  schemaVersion: 1,
  defaultDatasetId: 'original-goty-hd',
  datasets: [
    { datasetId: 'original-goty-hd', manifestUrl: '/datasets/original.json', order: 1 },
    { datasetId: 'poison-song', manifestUrl: '/datasets/poison.json', order: 2 },
  ],
};

function manifestFixture(datasetId: string, mapKey: string, title: string) {
  return {
    datasetId,
    mapKey,
    snapshotId: `${datasetId}:fixture`,
    title: { en: title },
    summary: { en: `${title} summary` },
    release:
      mapKey === 'tamriel-rebuilt'
        ? { name: 'Poison Song', version: '26.08', build: '26.08.23' }
        : { name: 'Morrowind Game of the Year Edition', version: '1.6.1820', build: null },
    readiness: { status: 'placeholder', exactProfile: false },
    localization: { locales: [{ locale: 'en' }] },
    map: {
      projection: {
        code: 'TES3:WORLD',
        units: 'world',
        cellSize: 8192,
        extent: [-10, -10, 10, 10],
        center: [0, 0],
      },
    },
  };
}

const manifests = [
  manifestFixture('original-goty-hd', 'original', 'Original GOTY HD'),
  manifestFixture('poison-song', 'tamriel-rebuilt', 'Poison Song 26.08'),
];

describe('App dataset workflow', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/');
    const responses = [indexFixture, ...manifests];
    const fetchMock = vi.fn(() => {
      const body = responses.shift();
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
      });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(cleanup);

  it('loads all manifests, opens a selected map, and returns to the cards', async () => {
    render(<App />);

    expect(screen.getByRole('status')).toHaveTextContent('Reading manifests');

    await screen.findByRole('button', { name: 'Open map: Original GOTY HD' });
    expect(screen.getAllByRole('button', { name: /Open map:/ })).toHaveLength(2);
    expect(screen.getByTestId('landing-backdrop')).toHaveAttribute(
      'data-dataset-id',
      'poison-song',
    );
    expect(screen.getByText('Classic')).toHaveClass('dataset-choice__kind');
    expect(screen.getByText('Tamriel Rebuilt')).toHaveClass('dataset-choice__kind');
    expect(screen.queryByText('LOCAL CARTOGRAPHIC LOG')).not.toBeInTheDocument();

    const datasets = [
      { card: 'Open map: Original GOTY HD', heading: 'Original GOTY HD' },
      { card: 'Open map: Poison Song 26.08', heading: 'Poison Song 26.08' },
    ];

    for (const dataset of datasets) {
      const card = screen.getByRole('button', { name: dataset.card });
      document.documentElement.scrollTop = 96;
      document.body.scrollTop = 96;
      fireEvent.click(card);
      expect(screen.getByRole('region', { name: 'mock map' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: dataset.heading })).toBeInTheDocument();
      expect(document.documentElement.scrollTop).toBe(0);
      expect(document.body.scrollTop).toBe(0);
      expect(window.location.search).toBe(
        `?dataset=${dataset.card.includes('Original') ? 'original-goty-hd' : 'poison-song'}&region=all`,
      );

      fireEvent.click(screen.getByRole('button', { name: 'Versions' }));
      await waitFor(() => expect(screen.getByRole('button', { name: dataset.card })).toHaveFocus());
      expect(window.location.search).toBe('');
    }
  });

  it('hydrates a direct map URL and accepts canonical map updates', async () => {
    window.history.replaceState(
      null,
      '',
      '/?dataset=poison-song&region=tr-mainland&x=10&y=-20&z=4.25&place=fixture-place&type=guild&type=temple&status=visited&status=active',
    );

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Poison Song 26.08' })).toBeInTheDocument();
    expect(screen.getByLabelText('mock navigation state')).toHaveTextContent(
      '"regionId":"tr-mainland"',
    );
    expect(screen.getByLabelText('mock navigation state')).toHaveTextContent(
      '"center":[10,-20]',
    );
    expect(screen.getByLabelText('mock navigation state')).toHaveTextContent(
      '"placeId":"fixture-place"',
    );
    expect(screen.getByLabelText('mock navigation state')).toHaveTextContent(
      '"typeFilters":["temple","guild"]',
    );
    expect(screen.getByLabelText('mock navigation state')).toHaveTextContent(
      '"statusFilters":["active","visited"]',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Update map URL' }));

    expect(window.location.search).toBe(
      '?dataset=poison-song&region=vvardenfell&x=1234&y=-5679&z=4.13&place=fixture-place&type=temple&type=guild&status=active&status=visited',
    );
  });

  it('canonicalizes an unknown dataset to the landing page', async () => {
    window.history.replaceState(
      null,
      '',
      '/?theme=sepia&dataset=missing&region=all&x=1&y=2&z=3&place=stale',
    );

    render(<App />);

    await screen.findByRole('button', { name: 'Open map: Original GOTY HD' });
    await waitFor(() => expect(window.location.search).toBe('?theme=sepia'));
    expect(screen.queryByRole('region', { name: 'mock map' })).not.toBeInTheDocument();
  });

  it('removes orphaned map parameters from a landing URL', async () => {
    window.history.replaceState(
      null,
      '',
      '/?theme=sepia&region=vvardenfell&x=1&y=2&z=3&place=stale',
    );

    render(<App />);

    await waitFor(() => expect(window.location.search).toBe('?theme=sepia'));
    expect(screen.getByRole('heading', { name: 'Choose a world' })).toBeInTheDocument();
  });

  it('canonicalizes and preserves a direct URL while manifest loading fails and retries', async () => {
    const canonicalUrl = '?dataset=poison-song&region=tr-mainland&x=10&y=-21&z=4.26';
    window.history.replaceState(
      null,
      '',
      '/?z=4.256&dataset=poison-song&x=10.4&place=&region=tr-mainland&y=-20.6',
    );
    const responses = [indexFixture, ...manifests];
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockImplementation(() => Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(responses.shift()),
      })));

    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 503');
    await waitFor(() => expect(window.location.search).toBe(canonicalUrl));
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByRole('heading', { name: 'Poison Song 26.08' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('region', { name: 'mock map' })).toHaveFocus());
    expect(window.location.search).toBe(canonicalUrl);
  });

  it('focuses recovered landing content after a fatal catalog retry without changing history', async () => {
    const responses = [indexFixture, ...manifests];
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockImplementation(() => Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(responses.shift()),
      })));
    const historyLength = window.history.length;

    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));

    await screen.findByRole('button', { name: 'Open map: Original GOTY HD' });
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Choose a world' })).toHaveFocus());
    expect(window.location.search).toBe('');
    expect(window.history.length).toBe(historyLength);
  });

  it('returns focus to retry when a fatal catalog retry fails again', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce({ ok: false, status: 502 }));
    const historyLength = window.history.length;

    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));

    const retry = await screen.findByRole('button', { name: 'Retry' });
    await waitFor(() => expect(retry).toHaveFocus());
    expect(screen.getByRole('alert')).toHaveTextContent('HTTP 502');
    expect(window.location.search).toBe('');
    expect(window.history.length).toBe(historyLength);
  });

  it('keeps healthy cards and a failed deep link while retrying one unavailable manifest', async () => {
    const directUrl = '?dataset=poison-song&region=tr-mainland';
    window.history.replaceState(null, '', `/${directUrl}`);
    const ok = (value: unknown) => ({
      ok: true,
      status: 200,
      json: () => Promise.resolve(value),
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(ok(indexFixture))
      .mockResolvedValueOnce(ok(manifests[0]))
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce(ok(indexFixture))
      .mockResolvedValueOnce(ok(manifests[0]))
      .mockResolvedValueOnce(ok(manifests[1]));
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('PARTIAL CATALOG');
    expect(alert).toHaveTextContent('poison-song');
    expect(screen.getByRole('button', { name: 'Open map: Original GOTY HD' }))
      .toBeInTheDocument();
    expect(screen.getByTestId('landing-backdrop')).toHaveAttribute(
      'data-dataset-id',
      'original-goty-hd',
    );
    expect(window.location.search).toBe(directUrl);

    const retry = screen.getByRole('button', { name: 'Retry unavailable maps' });
    fireEvent.click(retry);
    fireEvent.click(retry);

    expect(retry).toBeDisabled();
    expect(retry).toHaveTextContent('Retrying');
    expect(await screen.findByRole('heading', { name: 'Poison Song 26.08' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('region', { name: 'mock map' })).toHaveFocus());
    expect(fetchMock).toHaveBeenCalledTimes(6);
    expect(window.location.search).toBe(directUrl);
  });

  it('shows a fatal catalog state when every indexed manifest fails', async () => {
    const ok = (value: unknown) => ({
      ok: true,
      status: 200,
      json: () => Promise.resolve(value),
    });
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(ok(indexFixture))
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce({ ok: false, status: 404 }));

    render(<App />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('DATA ERROR');
    expect(alert).toHaveTextContent('Could not load any dataset manifests (2 failed)');
    expect(alert).not.toHaveTextContent('PARTIAL CATALOG');
    expect(screen.queryByRole('region', { name: 'Available maps' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
  });

  it('hydrates popstate and returns focus to the previous dataset card', async () => {
    render(<App />);

    const card = await screen.findByRole('button', { name: 'Open map: Original GOTY HD' });
    fireEvent.click(card);
    expect(await screen.findByRole('region', { name: 'mock map' })).toBeInTheDocument();

    window.history.pushState(null, '', '/');
    fireEvent(window, new PopStateEvent('popstate'));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Open map: Original GOTY HD' })).toHaveFocus(),
    );
  });
});
