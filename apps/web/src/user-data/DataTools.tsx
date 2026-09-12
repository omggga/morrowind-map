import { useEffect, useId, useRef, useState, type ChangeEvent } from 'react';
import type { Locale } from '@morrowind-map/contracts';
import {
  userDatabase,
  type MorrowindMapDatabase,
} from '../storage/database';
import {
  createPortableBackup,
  createPortableBackupForStoredDataset,
  importPortableBackup,
  type BackupImportResult,
} from '../storage/userData';
import { PixelIcon } from '../ui/PixelIcon';
import { getUserDataStrings } from './strings';

const MAX_BACKUP_FILE_BYTES = 10 * 1024 * 1024;

type BusyOperation = 'export' | 'backup' | null;

type Feedback =
  | { readonly tone: 'error'; readonly text: string }
  | { readonly tone: 'status'; readonly kind: 'backup-exported'; readonly operationId: number }
  | { readonly tone: 'status'; readonly kind: 'backup-result'; readonly result: BackupImportResult };

export interface DataToolsProps {
  readonly datasetId: string;
  readonly knownPlaceIds: ReadonlySet<string>;
  readonly locale: Locale;
  readonly datasetSnapshots: Readonly<Record<string, string>>;
  readonly database?: MorrowindMapDatabase;
  readonly className?: string;
  readonly onBackupImport?: (result: BackupImportResult) => void;
  readonly disabled?: boolean;
  readonly mode?: 'read-write' | 'conflict-export-only';
  readonly variant?: 'panel' | 'compact';
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
  datasetId,
  knownPlaceIds,
  locale,
  datasetSnapshots,
  database = userDatabase,
  className,
  onBackupImport,
  disabled = false,
  mode = 'read-write',
  variant = 'panel',
}: DataToolsProps) {
  const strings = getUserDataStrings(locale);
  const headingId = useId();
  const backupInputId = useId();
  const backupHintId = useId();
  const latestOperationRef = useRef(0);
  const activeOperationRef = useRef<number | null>(null);
  const [busy, setBusy] = useState<BusyOperation>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const compact = variant === 'compact';
  const isDisabled = disabled || busy !== null;
  const importDisabled = isDisabled || mode === 'conflict-export-only';
  const exportFeedback = feedback?.tone === 'status' && feedback.kind === 'backup-exported'
    ? feedback : null;

  useEffect(() => {
    if (exportFeedback === null) {
      return;
    }
    const timeout = window.setTimeout(() => {
      setFeedback((current) => current === exportFeedback ? null : current);
    }, 5000);
    return () => window.clearTimeout(timeout);
  }, [exportFeedback]);

  const beginOperation = (operation: Exclude<BusyOperation, null>) => {
    if (disabled || activeOperationRef.current !== null) {
      return null;
    }
    const operationId = latestOperationRef.current + 1;
    latestOperationRef.current = operationId;
    activeOperationRef.current = operationId;
    setBusy(operation);
    setFeedback(null);
    return operationId;
  };

  const finishOperation = (operationId: number, nextFeedback: Feedback) => {
    if (
      latestOperationRef.current === operationId &&
      activeOperationRef.current === operationId
    ) {
      activeOperationRef.current = null;
      setBusy(null);
      setFeedback(nextFeedback);
    }
  };

  const failOperation = (operationId: number, error: unknown, retryLabel: string) => {
    finishOperation(operationId, {
      tone: 'error',
      text: strings.operationFailed(errorDetail(error), retryLabel),
    });
  };

  const exportJson = async () => {
    const operationId = beginOperation('export');
    if (operationId === null) {
      return;
    }

    try {
      const backup = mode === 'conflict-export-only'
        ? await createPortableBackupForStoredDataset(database, datasetId)
        : await createPortableBackup(database, datasetSnapshots);
      downloadBackup(`${JSON.stringify(backup, null, 2)}\n`, backup.exportedAt);
      finishOperation(operationId, { tone: 'status', kind: 'backup-exported', operationId });
    } catch (error: unknown) {
      failOperation(operationId, error, strings.exportJson);
    }
  };

  const importJsonFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (
      !file ||
      disabled ||
      mode === 'conflict-export-only' ||
      activeOperationRef.current !== null
    ) {
      return;
    }
    if (file.size > MAX_BACKUP_FILE_BYTES) {
      setFeedback({ tone: 'error', text: strings.fileTooLarge });
      return;
    }

    const operationId = beginOperation('backup');
    if (operationId === null) {
      return;
    }
    try {
      const input: unknown = JSON.parse(await file.text());
      const result = await importPortableBackup(database, input, {
        currentSnapshots: datasetSnapshots,
        knownPlaceIdsByDataset: new Map([[datasetId, knownPlaceIds]]),
      });
      onBackupImport?.(result);
      finishOperation(operationId, { tone: 'status', kind: 'backup-result', result });
    } catch (error: unknown) {
      failOperation(operationId, error, strings.importJson);
    }
  };

  let feedbackText: string | null = null;
  if (feedback?.tone === 'error') {
    feedbackText = feedback.text;
  } else if (feedback?.kind === 'backup-exported') {
    feedbackText = strings.backupExported;
  } else if (feedback?.kind === 'backup-result') {
    feedbackText = strings.backupResult(feedback.result);
  }

  return (
    <section
      className={[
        'user-data-tools',
        compact ? 'user-data-tools--compact' : '',
        className,
      ].filter(Boolean).join(' ')}
      aria-labelledby={headingId}
      aria-busy={busy !== null}
    >
      <h2 id={headingId} className={compact ? 'visually-hidden' : undefined}>
        {strings.dataToolsTitle}
      </h2>
      <div className="user-data-tools__actions">
        <button
          type="button"
          disabled={isDisabled}
          onClick={() => void exportJson()}
          {...(compact ? { 'aria-label': strings.exportJson, title: strings.exportJson } : {})}
        >
          {compact ? (
            <PixelIcon name="export" />
          ) : busy === 'export' ? strings.exporting : strings.exportJson}
        </button>

        <label
          htmlFor={backupInputId}
          aria-disabled={importDisabled}
          {...(compact ? { title: strings.importJson } : {})}
        >
          {compact ? (
            <>
              <PixelIcon name="import" />
              <span className="visually-hidden">{strings.importJson}</span>
            </>
          ) : strings.importJson}
        </label>
        <input
          id={backupInputId}
          type="file"
          accept="application/json,.json"
          aria-describedby={backupHintId}
          disabled={importDisabled}
          onChange={(event) => void importJsonFile(event)}
        />
        <small id={backupHintId} className={compact ? 'visually-hidden' : undefined}>
          {busy === 'backup' ? strings.importing : strings.importJsonHint}
        </small>
      </div>

      {feedbackText ? (
        <p
          key={exportFeedback?.operationId ?? 'feedback'}
          className={`user-data-tools__feedback user-data-tools__feedback--${feedback?.tone ?? 'status'}${exportFeedback ? ' user-data-tools__feedback--transient' : ''}`}
          role={feedback?.tone === 'error' ? 'alert' : 'status'}
        >
          {feedbackText}
        </p>
      ) : null}
    </section>
  );
}
