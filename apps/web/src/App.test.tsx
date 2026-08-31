import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

vi.mock('@morrowind-map/contracts', () => ({
  parseDatasetIndex: (value: unknown) => value,
  parseDatasetManifest: (value: unknown) => value,
}));

vi.mock('./map/Tes3Map', () => ({
  Tes3Map: ({ dataset, onBack }: { dataset: { title: { en: string } }; onBack: () => void }) => (
    <section aria-label="mock map">
      <h1>{dataset.title.en}</h1>
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

      fireEvent.click(screen.getByRole('button', { name: 'Versions' }));
      await waitFor(() => expect(screen.getByRole('button', { name: dataset.card })).toHaveFocus());
    }
  });
});
