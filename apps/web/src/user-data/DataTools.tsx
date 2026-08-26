import { useId, useRef, useState, type ChangeEvent } from 'react';
import type { DatasetManifest, Locale } from '@morrowind-map/contracts';
import {
  userDatabase,
  type MorrowindMapDatabase,
} from '../storage/database';
import {
  applyMimImport,
  createPortableBackup,
  importPortableBackup,
  type BackupImportResult,
  type MimImportResult,
} from '../storage/userData';
import { getUserDataStrings } from './strings';

const MAX_BACKUP_FILE_BYTES = 10 * 1024 * 1024;

type BusyOperation = 'mim' | 'export' | 'backup' | null;

type Feedback =
  | { readonly tone: 'error'; readonly detail: string }
  | { readonly tone: 'status'; readonly kind: 'mim-duplicate' }
  | { readonly tone: 'status'; readonly kind: 'mim-result'; readonly result: MimImportResult }
  | { readonly tone: 'status'; readonly kind: 'backup-exported' }
  | { readonly tone: 'status'; readonly kind: 'backup-result'; readonly result: BackupImportResult };

export interface DataToolsProps {
  readonly dataset: DatasetManifest;
  readonly knownPlaceIds: ReadonlySet<string>;
  readonly locale: Locale;
  readonly datasetSnapshots: Readonly<Record<string, string>>;
  readonly database?: MorrowindMapDatabase;
  readonly className?: string;
  readonly onMimImport?: (result: MimImportResult) => void;
  readonly onBackupImport?: (result: BackupImportResult) => void;
}

function errorDetail(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function downloadBackup(contents: string, exportedAt: string): void {
  const blob = new Blob([contents], { type: 'application/json;charset=utf-8' });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = `morrowind-map-backup-${exportedAt.slice(0, 10)}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

export function DataTools({
  dataset,
  knownPlaceIds,
  locale,
  datasetSnapshots,
  database = userDatabase,
  className,
  onMimImport,
  onBackupImport,
}: DataToolsProps) {
  const strings = getUserDataStrings(locale);
  const headingId = useId();
  const backupInputId = useId();
  const backupHintId = useId();
  const latestOperationRef = useRef(0);
  const [busy, setBusy] = useState<BusyOperation>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const mimArtifact = dataset.artifacts.mimImport;

  const beginOperation = (operation: Exclude<BusyOperation, null>) => {
    const operationId = latestOperationRef.current + 1;
    latestOperationRef.current = operationId;
    setBusy(operation);
    setFeedback(null);
    return operationId;
  };

  const finishOperation = (operationId: number, nextFeedback: Feedback) => {
    if (latestOperationRef.current === operationId) {
      setBusy(null);
      setFeedback(nextFeedback);
    }
  };

  const failOperation = (operationId: number, error: unknown) => {
    finishOperation(operationId, { tone: 'error', detail: errorDetail(error) });
  };

  const importMim = async () => {
    if (!mimArtifact || busy !== null) {
      return;
    }

    const operationId = beginOperation('mim');
    try {
      const response = await fetch(mimArtifact.url, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${mimArtifact.url}`);
      }
      const result = await applyMimImport(
        database,
        await response.json() as unknown,
        dataset.datasetId,
        dataset.snapshotId,
        knownPlaceIds,
      );
      onMimImport?.(result);
      finishOperation(
        operationId,
        result.duplicate
          ? { tone: 'status', kind: 'mim-duplicate' }
          : { tone: 'status', kind: 'mim-result', result },
      );
    } catch (error: unknown) {
      failOperation(operationId, error);
    }
  };

  const exportJson = async () => {
    if (busy !== null) {
      return;
    }

    const operationId = beginOperation('export');
    try {
      const backup = await createPortableBackup(database, datasetSnapshots);
      downloadBackup(`${JSON.stringify(backup, null, 2)}\n`, backup.exportedAt);
      finishOperation(operationId, { tone: 'status', kind: 'backup-exported' });
    } catch (error: unknown) {
      failOperation(operationId, error);
    }
  };

  const importJsonFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (!file || busy !== null) {
      return;
    }
    if (file.size > MAX_BACKUP_FILE_BYTES) {
      setFeedback({ tone: 'error', detail: strings.fileTooLarge });
      return;
    }

    const operationId = beginOperation('backup');
    try {
      const input: unknown = JSON.parse(await file.text());
      const result = await importPortableBackup(database, input, {
        currentSnapshots: datasetSnapshots,
        knownPlaceIdsByDataset: new Map([[dataset.datasetId, knownPlaceIds]]),
      });
      onBackupImport?.(result);
      finishOperation(operationId, { tone: 'status', kind: 'backup-result', result });
    } catch (error: unknown) {
      failOperation(operationId, error);
    }
  };

  let feedbackText: string | null = null;
  if (feedback?.tone === 'error') {
    feedbackText = feedback.detail === strings.fileTooLarge
      ? feedback.detail
      : `${strings.operationFailed}: ${feedback.detail}`;
  } else if (feedback?.kind === 'mim-duplicate') {
    feedbackText = strings.mimDuplicate;
  } else if (feedback?.kind === 'mim-result') {
    feedbackText = strings.mimResult(feedback.result);
  } else if (feedback?.kind === 'backup-exported') {
    feedbackText = strings.backupExported;
  } else if (feedback?.kind === 'backup-result') {
    feedbackText = strings.backupResult(feedback.result);
  }

  return (
    <section
      className={['user-data-tools', className].filter(Boolean).join(' ')}
      aria-labelledby={headingId}
      aria-busy={busy !== null}
    >
      <h2 id={headingId}>{strings.dataToolsTitle}</h2>
      <div className="user-data-tools__actions">
        <button
          type="button"
          disabled={!mimArtifact || busy !== null}
          onClick={() => void importMim()}
          title={mimArtifact ? undefined : strings.mimUnavailable}
        >
          {busy === 'mim' ? strings.importing : strings.mimImport}
        </button>
        {!mimArtifact ? <p className="user-data-tools__hint">{strings.mimUnavailable}</p> : null}

        <button type="button" disabled={busy !== null} onClick={() => void exportJson()}>
          {busy === 'export' ? strings.exporting : strings.exportJson}
        </button>

        <label htmlFor={backupInputId}>{strings.importJson}</label>
        <input
          id={backupInputId}
          type="file"
          accept="application/json,.json"
          aria-describedby={backupHintId}
          disabled={busy !== null}
          onChange={(event) => void importJsonFile(event)}
        />
        <small id={backupHintId}>{busy === 'backup' ? strings.importing : strings.importJsonHint}</small>
      </div>

      {feedbackText ? (
        <p
          className={`user-data-tools__feedback user-data-tools__feedback--${feedback?.tone ?? 'status'}`}
          role={feedback?.tone === 'error' ? 'alert' : 'status'}
          aria-live="polite"
        >
          {feedbackText}
        </p>
      ) : null}
    </section>
  );
}
