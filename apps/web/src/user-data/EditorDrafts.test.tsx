import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MorrowindMapDatabase, progressKey } from '../storage/database';
import { LOCAL_STORAGE_PREFIX } from '../storage/userDataNamespace';
import * as userData from '../storage/userData';
import {
  ensureDatasetSnapshot,
  saveCustomMarker,
} from '../storage/userData';
import { CustomMarkerEditor } from './CustomMarkerEditor';
import { PlaceProgressEditor } from './PlaceProgressEditor';

const datasetId = 'original-goty';
const snapshotId = 'original:goty:drafts';
const placeId = 'original-goty.vvardenfell.mim-0000';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

function clickTwiceBeforeRender(button: HTMLElement): void {
  act(() => {
    button.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    button.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

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
    vi.restoreAllMocks();
    database.close();
    await database.delete();
  });

  it('restores an unsaved place note and waits for Save before persisting it', async () => {
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
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    expect(await database.progress.get(progressKey(datasetId, placeId))).toBeUndefined();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(async () => {
      expect(await database.progress.get(progressKey(datasetId, placeId))).toMatchObject({
        note: 'Recovered after reload',
      });
    });
  });

  it('keeps a place note editable across pauses and blur, saving the exact text only on Save', async () => {
    render(
      <PlaceProgressEditor
        datasetId={datasetId}
        placeId={placeId}
        locale="en"
        database={database}
      />,
    );
    const note = screen.getByRole('textbox', { name: 'Personal note' });

    fireEvent.focus(note);
    fireEvent.change(note, { target: { value: 'First line' } });
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    expect(note).toBeEnabled();
    expect(await database.progress.get(progressKey(datasetId, placeId))).toBeUndefined();
    fireEvent.change(note, { target: { value: '  First line\nSecond line  ' } });
    fireEvent.blur(note);
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    expect(await database.progress.get(progressKey(datasetId, placeId))).toBeUndefined();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(async () => {
      expect(await database.progress.get(progressKey(datasetId, placeId))).toMatchObject({
        note: '  First line\nSecond line  ',
      });
    });
    expect(screen.getByRole('status')).toHaveTextContent('Saved.');
    const savedFeedback = screen.getByRole('status');
    fireEvent.click(screen.getByRole('button', { name: 'Active' }));
    expect(screen.getByRole('status')).toBe(savedFeedback);
    await waitFor(async () => {
      expect(await database.progress.get(progressKey(datasetId, placeId))).toMatchObject({
        status: 'active',
        note: '  First line\nSecond line  ',
      });
    });
    expect(screen.getByRole('status')).toBe(savedFeedback);
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

  it('restores marker name and note drafts and saves them together only on Save', async () => {
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
    fireEvent.change(screen.getByRole('textbox', { name: 'Personal note' }), {
      target: { value: '  Marker note\nSecond line  ' },
    });
    fireEvent.blur(screen.getByRole('textbox', { name: 'Personal note' }));
    first.unmount();

    render(<CustomMarkerEditor marker={marker} locale="en" database={database} />);
    expect(screen.getByRole('textbox', { name: 'Marker name' })).toHaveValue('Recovered marker');
    expect(screen.getByRole('textbox', { name: 'Personal note' })).toHaveValue('  Marker note\nSecond line  ');
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    expect(await database.customMarkers.get(marker.id)).toMatchObject({ label: 'Original label', note: '' });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(async () => {
      expect(await database.customMarkers.get(marker.id)).toMatchObject({
        label: 'Recovered marker',
        note: '  Marker note\nSecond line  ',
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

  it('focuses the safe delete action and returns focus when Escape cancels', async () => {
    const marker = await saveCustomMarker(
      database,
      { datasetId, label: 'Focus marker', note: '', position: [10, 20] },
      undefined,
      () => 'focus-marker',
    );
    render(<CustomMarkerEditor marker={marker} locale="en" database={database} />);

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus(),
    );
    expect(screen.getByRole('button', { name: 'Yes, delete' })).not.toHaveFocus();

    fireEvent.keyDown(screen.getByRole('group', { name: /Delete this marker/ }), { key: 'Escape' });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Delete' })).toHaveFocus(),
    );
  });

  it('blocks duplicate progress writes before disabled state renders and allows retry', async () => {
    const operation = deferred<Awaited<ReturnType<typeof userData.savePlaceProgress>>>();
    const saveProgress = vi
      .spyOn(userData, 'savePlaceProgress')
      .mockReturnValue(operation.promise);
    render(
      <PlaceProgressEditor
        datasetId={datasetId}
        placeId={placeId}
        locale="en"
        database={database}
      />,
    );

    const activeButton = screen.getByRole('button', { name: 'Active' });
    clickTwiceBeforeRender(activeButton);
    expect(saveProgress).toHaveBeenCalledTimes(1);

    operation.reject(new Error('Quota exceeded'));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Select “Active” to try again.');
    expect(alert).not.toHaveAttribute('aria-live');
    expect(await database.progress.get(progressKey(datasetId, placeId))).toBeUndefined();

    saveProgress.mockRejectedValueOnce(new Error('Still full'));
    fireEvent.click(activeButton);
    await waitFor(() => expect(saveProgress).toHaveBeenCalledTimes(2));
  });

  it('keeps failed marker edits for manual retry without saving on subsequent edits', async () => {
    const marker = await saveCustomMarker(
      database,
      { datasetId, label: 'Original label', note: '', position: [10, 20] },
      undefined,
      () => 'failed-autosave-marker',
    );
    const saveMarker = vi
      .spyOn(userData, 'saveCustomMarker')
      .mockRejectedValue(new Error('Quota exceeded'));
    render(<CustomMarkerEditor marker={marker} locale="en" database={database} />);
    const labelInput = screen.getByRole('textbox', { name: 'Marker name' });
    fireEvent.change(labelInput, { target: { value: 'Unsaved marker' } });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(saveMarker).toHaveBeenCalledTimes(1));
    expect(labelInput).toHaveValue('Unsaved marker');
    expect(window.localStorage.getItem(
      `${LOCAL_STORAGE_PREFIX}:draft:custom-marker:${encodeURIComponent(marker.id)}`,
    )).toContain('Unsaved marker');

    await new Promise((resolve) => window.setTimeout(resolve, 500));
    expect(saveMarker).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(saveMarker).toHaveBeenCalledTimes(2));

    await new Promise((resolve) => window.setTimeout(resolve, 500));
    expect(saveMarker).toHaveBeenCalledTimes(2);

    fireEvent.change(labelInput, { target: { value: 'Edited again' } });
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    expect(saveMarker).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(saveMarker).toHaveBeenCalledTimes(3));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Select “Save” to try again.');
    expect(alert).not.toHaveAttribute('aria-live');
    expect(await database.customMarkers.get(marker.id)).toMatchObject({
      label: 'Original label',
    });
  });

  it('blocks duplicate marker deletion and keeps the record available for retry', async () => {
    const marker = await saveCustomMarker(
      database,
      { datasetId, label: 'Keep marker', note: '', position: [10, 20] },
      undefined,
      () => 'failed-delete-marker',
    );
    const operation = deferred<void>();
    const deleteMarker = vi
      .spyOn(userData, 'deleteCustomMarker')
      .mockReturnValue(operation.promise);
    render(<CustomMarkerEditor marker={marker} locale="en" database={database} />);

    const labelInput = screen.getByRole('textbox', { name: 'Marker name' });
    fireEvent.change(labelInput, { target: { value: 'Keep this draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    const confirmButton = screen.getByRole('button', { name: 'Yes, delete' });
    expect(screen.getByRole('group', { name: /Delete this marker/ })).toBeInTheDocument();
    clickTwiceBeforeRender(confirmButton);
    expect(deleteMarker).toHaveBeenCalledTimes(1);

    operation.reject(new Error('Storage unavailable'));
    const feedback = await screen.findByText(/Select “Yes, delete” to try again\./);
    expect(feedback).toHaveAttribute('role', 'alert');
    expect(feedback).not.toHaveAttribute('aria-live');
    expect(screen.getAllByRole('alert')).toEqual([feedback]);
    expect(screen.getByRole('group', { name: /Delete this marker/ })).toBeInTheDocument();
    expect(confirmButton).toBeEnabled();
    expect(labelInput).toHaveValue('Keep this draft');
    expect(window.localStorage.getItem(
      `${LOCAL_STORAGE_PREFIX}:draft:custom-marker:${encodeURIComponent(marker.id)}`,
    )).toContain('Keep this draft');
    expect(await database.customMarkers.get(marker.id)).toMatchObject({
      label: 'Keep marker',
      deletedAt: null,
    });

    const retryOperation = deferred<void>();
    deleteMarker.mockReturnValueOnce(retryOperation.promise);
    fireEvent.click(confirmButton);
    expect(deleteMarker).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Deleting…' })).toBeDisabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    retryOperation.reject(new Error('Still unavailable'));
    const retryFeedback = await screen.findByRole('alert');
    expect(retryFeedback).toHaveTextContent('Still unavailable');
    expect(retryFeedback).toHaveTextContent('Select “Yes, delete” to try again.');
    expect(screen.getAllByRole('alert')).toEqual([retryFeedback]);
    expect(confirmButton).toBeEnabled();
  });
});
