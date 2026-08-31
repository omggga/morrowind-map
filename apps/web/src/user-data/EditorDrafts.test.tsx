import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { MorrowindMapDatabase, progressKey } from '../storage/database';
import {
  ensureDatasetSnapshot,
  saveCustomMarker,
} from '../storage/userData';
import { CustomMarkerEditor } from './CustomMarkerEditor';
import { PlaceProgressEditor } from './PlaceProgressEditor';

const datasetId = 'original-goty';
const snapshotId = 'original:goty:drafts';
const placeId = 'original-goty.vvardenfell.mim-0000';

describe('editor crash-recovery drafts', () => {
  let database: MorrowindMapDatabase;

  beforeEach(async () => {
    window.localStorage.clear();
    database = new MorrowindMapDatabase(`morrowind-map-drafts-${crypto.randomUUID()}`);
    await ensureDatasetSnapshot(database, datasetId, snapshotId);
  });

  afterEach(async () => {
    cleanup();
    window.localStorage.clear();
    database.close();
    await database.delete();
  });

  it('restores an unsaved place note after an immediate unmount and persists it', async () => {
    const first = render(
      <PlaceProgressEditor
        datasetId={datasetId}
        placeId={placeId}
        locale="en"
        database={database}
      />,
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Personal note' }), {
      target: { value: 'Recovered after reload' },
    });
    first.unmount();

    render(
      <PlaceProgressEditor
        datasetId={datasetId}
        placeId={placeId}
        locale="en"
        database={database}
      />,
    );
    expect(screen.getByRole('textbox', { name: 'Personal note' })).toHaveValue(
      'Recovered after reload',
    );
    await waitFor(async () => {
      expect(await database.progress.get(progressKey(datasetId, placeId))).toMatchObject({
        note: 'Recovered after reload',
      });
    });
  });

  it('ignores a place-note draft from the retired user-data epoch', async () => {
    const placeKey = `${datasetId}\0${placeId}`;
    window.localStorage.setItem(
      `morrowind-map:draft:place-note:${encodeURIComponent(placeKey)}`,
      'Retired draft',
    );

    render(
      <PlaceProgressEditor
        datasetId={datasetId}
        placeId={placeId}
        locale="en"
        database={database}
      />,
    );

    expect(screen.getByRole('textbox', { name: 'Personal note' })).toHaveValue('');
    await new Promise((resolve) => window.setTimeout(resolve, 400));
    expect(await database.progress.get(progressKey(datasetId, placeId))).toBeUndefined();
  });

  it('restores an unsaved marker edit after an immediate unmount and persists it', async () => {
    const marker = await saveCustomMarker(
      database,
      { datasetId, label: 'Original label', note: '', position: [10, 20] },
      undefined,
      () => 'draft-marker',
    );
    const first = render(
      <CustomMarkerEditor marker={marker} locale="en" database={database} />,
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Marker name' }), {
      target: { value: 'Recovered marker' },
    });
    first.unmount();

    render(<CustomMarkerEditor marker={marker} locale="en" database={database} />);
    expect(screen.getByRole('textbox', { name: 'Marker name' })).toHaveValue('Recovered marker');
    await waitFor(async () => {
      expect(await database.customMarkers.get(marker.id)).toMatchObject({
        label: 'Recovered marker',
      });
    });
  });

  it('ignores a custom-marker draft from the retired user-data epoch', async () => {
    const marker = await saveCustomMarker(
      database,
      { datasetId, label: 'Current marker', note: '', position: [10, 20] },
      undefined,
      () => 'retired-draft-marker',
    );
    window.localStorage.setItem(
      `morrowind-map:draft:custom-marker:${encodeURIComponent(marker.id)}`,
      JSON.stringify({ label: 'Retired marker', note: 'Retired note' }),
    );

    render(<CustomMarkerEditor marker={marker} locale="en" database={database} />);

    expect(screen.getByRole('textbox', { name: 'Marker name' })).toHaveValue('Current marker');
  });

  it('moves focus into marker deletion confirmation and returns it on cancel', async () => {
    const marker = await saveCustomMarker(
      database,
      { datasetId, label: 'Focus marker', note: '', position: [10, 20] },
      undefined,
      () => 'focus-marker',
    );
    render(<CustomMarkerEditor marker={marker} locale="en" database={database} />);

    fireEvent.click(screen.getByRole('button', { name: 'Delete marker' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Yes, delete' })).toHaveFocus(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Delete marker' })).toHaveFocus(),
    );
  });
});
