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
        Версии
      </button>
    </section>
  ),
}));

const indexFixture = {
  schemaVersion: 1,
  defaultDatasetId: 'original-goty',
  datasets: [
    { datasetId: 'original-goty', manifestUrl: '/datasets/original.json', order: 1 },
    { datasetId: 'fullrest-old', manifestUrl: '/datasets/fullrest.json', order: 2 },
    { datasetId: 'poison-song', manifestUrl: '/datasets/poison.json', order: 3 },
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
  manifestFixture('original-goty', 'original', 'Original GOTY'),
  manifestFixture('fullrest-old', 'fullrest-old', 'Fullrest 25.08'),
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

    expect(screen.getByRole('status')).toHaveTextContent('Читаю manifests');

    await screen.findByRole('button', { name: 'Открыть карту: Original GOTY' });
    expect(screen.getAllByRole('button', { name: /Открыть карту:/ })).toHaveLength(3);

    const datasets = [
      { card: 'Открыть карту: Original GOTY', heading: 'Original GOTY' },
      { card: 'Открыть карту: Fullrest 25.08', heading: 'Fullrest 25.08' },
      { card: 'Открыть карту: Poison Song 26.08', heading: 'Poison Song 26.08' },
    ];

    for (const dataset of datasets) {
      const card = screen.getByRole('button', { name: dataset.card });
      fireEvent.click(card);
      expect(screen.getByRole('region', { name: 'mock map' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: dataset.heading })).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Версии' }));
      await waitFor(() => expect(screen.getByRole('button', { name: dataset.card })).toHaveFocus());
    }
  });
});
