import { useId, useRef, useState, type FormEvent } from 'react';
import type {
  Locale,
  ProgressRecord,
  ProgressStatus,
} from '@morrowind-map/contracts';
import {
  userDatabase,
  type MorrowindMapDatabase,
} from '../storage/database';
import { savePlaceProgress } from '../storage/userData';
import { LOCAL_STORAGE_PREFIX } from '../storage/userDataNamespace';
import { StatusMark } from '../ui/StatusMark';
import { getUserDataStrings } from './strings';

const STATUSES: readonly ProgressStatus[] = ['unvisited', 'active', 'visited'];

interface NoteDraft {
  readonly placeKey: string;
  readonly value: string;
}

interface EditorFeedback {
  readonly placeKey: string;
  readonly tone: 'error' | 'status';
  readonly text: string;
}

interface SaveOperation {
  readonly kind: 'status' | 'note';
  readonly revision: string;
}

export interface PlaceProgressEditorProps {
  readonly datasetId: string;
  readonly placeId: string;
  readonly progress?: ProgressRecord;
  readonly locale: Locale;
  readonly database?: MorrowindMapDatabase;
  readonly disabled?: boolean;
  readonly onSaved?: (progress: ProgressRecord) => void;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function noteDraftStorageKey(placeKey: string): string {
  return `${LOCAL_STORAGE_PREFIX}:draft:place-note:${encodeURIComponent(placeKey)}`;
}

function readStoredNoteDraft(placeKey: string): string | null {
  try {
    return window.localStorage.getItem(noteDraftStorageKey(placeKey));
  } catch {
    return null;
  }
}

function writeStoredNoteDraft(placeKey: string, note: string): void {
  try {
    window.localStorage.setItem(noteDraftStorageKey(placeKey), note);
  } catch {
    // IndexedDB remains the primary store; restricted localStorage only disables crash recovery.
  }
}

function clearStoredNoteDraft(placeKey: string, expectedNote: string): void {
  try {
    const key = noteDraftStorageKey(placeKey);
    if (window.localStorage.getItem(key) === expectedNote) {
      window.localStorage.removeItem(key);
    }
  } catch {
    // See writeStoredNoteDraft.
  }
}

export function PlaceProgressEditor({
  datasetId,
  placeId,
  progress,
  locale,
  database = userDatabase,
  disabled = false,
  onSaved,
}: PlaceProgressEditorProps) {
  const strings = getUserDataStrings(locale);
  const noteId = useId();
  const placeKey = `${datasetId}\0${placeId}`;
  const [draft, setDraft] = useState<NoteDraft | null>(() => {
    const stored = readStoredNoteDraft(placeKey);
    return stored === null ? null : { placeKey, value: stored };
  });
  const [saving, setSaving] = useState<'status' | 'note' | null>(null);
  const [feedback, setFeedback] = useState<EditorFeedback | null>(null);
  const activeOperationRef = useRef<SaveOperation | null>(null);
  const note = draft?.placeKey === placeKey ? draft.value : (progress?.note ?? '');
  const status = progress?.status ?? 'unvisited';
  const currentFeedback = feedback?.placeKey === placeKey ? feedback : null;
  const isDisabled = disabled || saving !== null;

  const beginSave = (kind: SaveOperation['kind'], revision: string) => {
    if (disabled || activeOperationRef.current !== null) {
      return null;
    }
    const operation: SaveOperation = { kind, revision };
    activeOperationRef.current = operation;
    setSaving(kind);
    setFeedback((current) => kind === 'note' || current?.tone === 'error' ? null : current);
    return operation;
  };

  const finishSave = (operation: SaveOperation) => {
    if (activeOperationRef.current === operation) {
      activeOperationRef.current = null;
      setSaving(null);
    }
  };

  const saveStatus = async (nextStatus: ProgressStatus) => {
    const operation = beginSave('status', nextStatus);
    if (operation === null) {
      return;
    }
    try {
      const saved = await savePlaceProgress(database, datasetId, placeId, {
        status: nextStatus,
      });
      onSaved?.(saved);
    } catch (error: unknown) {
      setFeedback({
        placeKey,
        tone: 'error',
        text: strings.operationFailed(errorText(error), strings.statuses[nextStatus]),
      });
    } finally {
      finishSave(operation);
    }
  };

  const persistNote = async (nextNote: string) => {
    if (disabled || activeOperationRef.current !== null) {
      return;
    }
    if (nextNote === (progress?.note ?? '')) {
      clearStoredNoteDraft(placeKey, nextNote);
      return;
    }
    const operation = beginSave('note', nextNote);
    if (operation === null) {
      return;
    }
    try {
      const saved = await savePlaceProgress(database, datasetId, placeId, { note: nextNote });
      clearStoredNoteDraft(placeKey, nextNote);
      setDraft((current) =>
        current?.placeKey === placeKey && current.value !== nextNote
          ? current
          : { placeKey, value: saved.note },
      );
      onSaved?.(saved);
      setFeedback({ placeKey, tone: 'status', text: strings.saved });
    } catch (error: unknown) {
      setFeedback({
        placeKey,
        tone: 'error',
        text: strings.noteSaveFailed(errorText(error)),
      });
    } finally {
      finishSave(operation);
    }
  };

  const saveNote = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void persistNote(note);
  };

  return (
    <section className="place-progress-editor" aria-label={strings.placeProgress} aria-busy={saving !== null}>
      <fieldset disabled={isDisabled}>
        <legend>{strings.status}</legend>
        <div className="place-progress-editor__stamps">
          {STATUSES.map((nextStatus) => (
            <button
              key={nextStatus}
              type="button"
              className={`progress-stamp progress-stamp--${nextStatus}`}
              aria-pressed={status === nextStatus}
              data-status={nextStatus}
              onClick={() => void saveStatus(nextStatus)}
            >
              <StatusMark kind={nextStatus} />
              {strings.statuses[nextStatus]}
            </button>
          ))}
        </div>
      </fieldset>

      <form className="place-progress-editor__note" onSubmit={saveNote}>
        <label htmlFor={noteId}>{strings.note}</label>
        <textarea
          id={noteId}
          value={note}
          maxLength={10_000}
          disabled={isDisabled}
          onChange={(event) => {
            const nextNote = event.currentTarget.value;
            setDraft({ placeKey, value: nextNote });
            writeStoredNoteDraft(placeKey, nextNote);
            setFeedback(null);
          }}
        />
        <button type="submit" disabled={isDisabled}>
          {strings.save}
        </button>
      </form>

      {currentFeedback ? (
        <p
          className={`editor-feedback editor-feedback--${currentFeedback.tone}`}
          role={currentFeedback.tone === 'error' ? 'alert' : 'status'}
        >
          {currentFeedback.text}
        </p>
      ) : null}
    </section>
  );
}
