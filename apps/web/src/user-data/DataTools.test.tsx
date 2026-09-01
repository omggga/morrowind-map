import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createPortableBackup,
  createPortableBackupForStoredDataset,
  importPortableBackup,
} from '../storage/userData';
import { DataTools } from './DataTools';

vi.mock('../storage/userData', () => ({
  createPortableBackup: vi.fn(),
  createPortableBackupForStoredDataset: vi.fn(),
  importPortableBackup: vi.fn(),
}));

const props = {
  datasetId: 'poison-song-26.08',
  datasetSnapshots: { 'poison-song-26.08': 'tr:poison-song-26.08:test' },
  knownPlaceIds: new Set(['poison-song-26.08.place-test']),
  locale: 'en' as const,
};

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

beforeEach(() => {
  vi.mocked(createPortableBackup).mockReset();
  vi.mocked(createPortableBackupForStoredDataset).mockReset();
  vi.mocked(importPortableBackup).mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('DataTools', () => {
  it('exposes portable JSON backup actions without the retired MIM importer', () => {
    render(
      <DataTools {...props} />,
    );

    expect(screen.getByRole('button', { name: 'Download JSON backup' })).toBeEnabled();
    expect(screen.getByLabelText('Import JSON backup')).toHaveAttribute('type', 'file');
    expect(screen.queryByText(/MIM/i)).not.toBeInTheDocument();
  });

  it('blocks duplicate export before the busy render and exposes an actionable retry', async () => {
    const operation = deferred<Awaited<ReturnType<typeof createPortableBackup>>>();
    vi.mocked(createPortableBackup).mockReturnValue(operation.promise);
    render(<DataTools {...props} />);

    const exportButton = screen.getByRole('button', { name: 'Download JSON backup' });
    clickTwiceBeforeRender(exportButton);

    expect(createPortableBackup).toHaveBeenCalledTimes(1);
    operation.reject(new Error('Storage unavailable'));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      'Select “Download JSON backup” to try again.',
    );
    expect(alert).not.toHaveAttribute('aria-live');
    await waitFor(() => expect(exportButton).toBeEnabled());

    vi.mocked(createPortableBackup).mockRejectedValueOnce(new Error('Still unavailable'));
    fireEvent.click(exportButton);
    await waitFor(() => expect(createPortableBackup).toHaveBeenCalledTimes(2));
  });

  it('disables and guards both backup actions when the parent is unavailable', () => {
    render(<DataTools {...props} disabled />);

    const exportButton = screen.getByRole('button', { name: 'Download JSON backup' });
    const importInput = screen.getByLabelText('Import JSON backup');
    expect(exportButton).toBeDisabled();
    expect(importInput).toBeDisabled();

    exportButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    fireEvent.change(importInput, {
      target: { files: [new File(['{}'], 'backup.json', { type: 'application/json' })] },
    });

    expect(createPortableBackup).not.toHaveBeenCalled();
    expect(importPortableBackup).not.toHaveBeenCalled();
  });

  it('keeps only stored-binding export available during a snapshot conflict', async () => {
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:conflict-backup'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    vi.mocked(createPortableBackupForStoredDataset).mockResolvedValueOnce({
      schemaVersion: 3,
      kind: 'morrowind-map-backup',
      exportedAt: '2026-08-31T12:05:00.000Z',
      datasets: { [props.datasetId]: 'tr:poison-song-26.08:stored' },
      progress: [],
      customMarkers: [],
    });

    render(<DataTools {...props} mode="conflict-export-only" />);

    const exportButton = screen.getByRole('button', { name: 'Download JSON backup' });
    const importInput = screen.getByLabelText('Import JSON backup');
    expect(exportButton).toBeEnabled();
    expect(importInput).toBeDisabled();

    fireEvent.click(exportButton);

    expect(await screen.findByRole('status')).toHaveTextContent('JSON backup downloaded');
    expect(createPortableBackupForStoredDataset).toHaveBeenCalledWith(
      expect.anything(),
      props.datasetId,
    );
    expect(createPortableBackup).not.toHaveBeenCalled();
    expect(importPortableBackup).not.toHaveBeenCalled();
  });

  it('rejects oversized and invalid JSON before any storage write', async () => {
    render(<DataTools {...props} />);
    const input = screen.getByLabelText('Import JSON backup');
    const oversized = new File(['{}'], 'oversized.json', { type: 'application/json' });
    Object.defineProperty(oversized, 'size', { value: 10 * 1024 * 1024 + 1 });

    fireEvent.change(input, { target: { files: [oversized] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('larger than 10 MB');
    expect(importPortableBackup).not.toHaveBeenCalled();

    const invalid = new File(['{'], 'invalid.json', { type: 'application/json' });
    Object.defineProperty(invalid, 'text', { value: () => Promise.resolve('{') });
    fireEvent.change(input, { target: { files: [invalid] } });

    expect(await screen.findByRole('alert')).toHaveTextContent('The operation failed');
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Select “Import JSON backup” to try again.',
    );
    expect(importPortableBackup).not.toHaveBeenCalled();
  });

  it('recovers from an import failure without issuing a duplicate operation', async () => {
    const operation = deferred<Awaited<ReturnType<typeof importPortableBackup>>>();
    vi.mocked(importPortableBackup).mockReturnValue(operation.promise);
    render(<DataTools {...props} />);
    const input = screen.getByLabelText('Import JSON backup');
    const backup = new File(['{}'], 'backup.json', { type: 'application/json' });
    Object.defineProperty(backup, 'text', { value: () => Promise.resolve('{}') });

    fireEvent.change(input, { target: { files: [backup] } });
    fireEvent.change(input, { target: { files: [backup] } });
    await waitFor(() => expect(importPortableBackup).toHaveBeenCalledTimes(1));
    operation.reject(new Error('Quota exceeded'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Quota exceeded');
    vi.mocked(importPortableBackup).mockResolvedValueOnce({
      progressImported: 1,
      progressSkipped: 0,
      markersImported: 1,
      markersSkipped: 0,
    });
    const retryFile = new File(['{}'], 'backup.json', { type: 'application/json' });
    Object.defineProperty(retryFile, 'text', { value: () => Promise.resolve('{}') });
    fireEvent.change(input, { target: { files: [retryFile] } });

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Backup imported: 1 places and 1 markers',
    );
    expect(importPortableBackup).toHaveBeenCalledTimes(2);
  });
});
