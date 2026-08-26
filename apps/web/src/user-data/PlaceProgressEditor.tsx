import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
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
  return `morrowind-map:draft:place-note:${encodeURIComponent(placeKey)}`;
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
  const noteSaveInFlightRef = useRef<string | null>(null);
  const noteSaveTimerRef = useRef<number | null>(null);
  const noteFormRef = useRef<HTMLFormElement>(null);
  const recoveredNoteRef = useRef(
    draft?.placeKey === placeKey ? draft.value : null,
  );
  const note = draft?.placeKey === placeKey ? draft.value : (progress?.note ?? '');
  const status = progress?.status ?? 'unvisited';
  const currentFeedback = feedback?.placeKey === placeKey ? feedback : null;
  const isDisabled = disabled || saving !== null;

  useEffect(
    () => () => {
      if (noteSaveTimerRef.current !== null) {
        window.clearTimeout(noteSaveTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    const recoveredNote = recoveredNoteRef.current;
    if (recoveredNote === null) {
      return;
    }
    if (recoveredNote === (progress?.note ?? '')) {
      clearStoredNoteDraft(placeKey, recoveredNote);
      recoveredNoteRef.current = null;
      return;
    }
    noteSaveTimerRef.current = window.setTimeout(() => {
      noteSaveTimerRef.current = null;
      noteFormRef.current?.requestSubmit();
      recoveredNoteRef.current = null;
    }, 350);
    return () => {
      if (noteSaveTimerRef.current !== null) {
        window.clearTimeout(noteSaveTimerRef.current);
        noteSaveTimerRef.current = null;
      }
    };
  }, [placeKey, progress?.note]);

  const clearPendingNoteSave = () => {
    if (noteSaveTimerRef.current !== null) {
      window.clearTimeout(noteSaveTimerRef.current);
      noteSaveTimerRef.current = null;
    }
  };

  const saveStatus = async (nextStatus: ProgressStatus) => {
    if (isDisabled) {
      return;
    }
    setSaving('status');
    setFeedback(null);
    try {
      const saved = await savePlaceProgress(database, datasetId, placeId, {
        status: nextStatus,
      });
      onSaved?.(saved);
      setFeedback({ placeKey, tone: 'status', text: strings.saved });
    } catch (error: unknown) {
      setFeedback({
        placeKey,
        tone: 'error',
        text: `${strings.operationFailed}: ${errorText(error)}`,
      });
    } finally {
      setSaving(null);
    }
  };

  const persistNote = async (nextNote: string) => {
    if (isDisabled || noteSaveInFlightRef.current === nextNote) {
      return;
    }
    if (nextNote === (progress?.note ?? '')) {
      clearStoredNoteDraft(placeKey, nextNote);
      return;
    }
    noteSaveInFlightRef.current = nextNote;
    setSaving('note');
    setFeedback(null);
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
        text: `${strings.operationFailed}: ${errorText(error)}`,
      });
    } finally {
      if (noteSaveInFlightRef.current === nextNote) {
        noteSaveInFlightRef.current = null;
      }
      setSaving(null);
    }
  };

  const saveNote = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    clearPendingNoteSave();
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
              {strings.statuses[nextStatus]}
            </button>
          ))}
        </div>
      </fieldset>

      <form ref={noteFormRef} className="place-progress-editor__note" onSubmit={saveNote}>
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
            clearPendingNoteSave();
            noteSaveTimerRef.current = window.setTimeout(() => {
              noteSaveTimerRef.current = null;
              void persistNote(nextNote);
            }, 350);
          }}
          onBlur={() => {
            clearPendingNoteSave();
            void persistNote(note);
          }}
        />
        <button type="submit" disabled={isDisabled}>
          {strings.saveNote}
        </button>
      </form>

      {currentFeedback ? (
        <p role={currentFeedback.tone === 'error' ? 'alert' : 'status'} aria-live="polite">
          {currentFeedback.text}
        </p>
      ) : null}
    </section>
  );
}
