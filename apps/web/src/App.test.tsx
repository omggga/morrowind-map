import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

vi.mock('@morrowind-map/contracts', () => ({
  parseDatasetIndex: (value: unknown) => value,
  parseDatasetManifest: (value: unknown) => value,
}));

vi.mock('./map/Tes3Map', () => ({
  Tes3Map: ({
    dataset,
    navigationState,
    onNavigationChange,
    onBack,
  }: {
    dataset: { datasetId: string; title: { en: string } };
    navigationState: {
      datasetId: string | null;
      regionId: string;
      view: { center: readonly [number, number]; zoom: number } | null;
      placeId: string | null;
    };
    onNavigationChange: (
      state: {
        datasetId: string | null;
        regionId: string;
        view: { center: readonly [number, number]; zoom: number } | null;
        placeId: string | null;
      },
      mode: 'push' | 'replace',
    ) => void;
    onBack: () => void;
  }) => (
    <section aria-label="mock map">
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
  manifestFixture('poison-song', 'poison-song', 'Poison Song 26.08'),
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

    const datasets = [
      { card: 'Open map: Original GOTY HD', heading: 'Original GOTY HD' },
      { card: 'Open map: Poison Song 26.08', heading: 'Poison Song 26.08' },
    ];

    for (const dataset of datasets) {
      const card = screen.getByRole('button', { name: dataset.card });
      fireEvent.click(card);
      expect(screen.getByRole('region', { name: 'mock map' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: dataset.heading })).toBeInTheDocument();
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
      '/?dataset=poison-song&region=tr-mainland&x=10&y=-20&z=4.25&place=fixture-place',
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

    fireEvent.click(screen.getByRole('button', { name: 'Update map URL' }));

    expect(window.location.search).toBe(
      '?dataset=poison-song&region=vvardenfell&x=1234&y=-5679&z=4.13&place=fixture-place',
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
    expect(window.location.search).toBe(canonicalUrl);
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
