import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type Ref,
} from 'react';
import type { CustomMarkerRecord, Locale } from '@morrowind-map/contracts';
import {
  userDatabase,
  type MorrowindMapDatabase,
} from '../storage/database';
import {
  deleteCustomMarker,
  saveCustomMarker,
} from '../storage/userData';
import { LOCAL_STORAGE_PREFIX } from '../storage/userDataNamespace';
import { getUserDataStrings } from './strings';

interface MarkerDraft {
  readonly markerId: string;
  readonly label: string;
  readonly note: string;
}

interface MarkerFeedback {
  readonly markerId: string;
  readonly tone: 'error' | 'status';
  readonly text: string;
}

export interface CustomMarkerEditorProps {
  readonly marker: CustomMarkerRecord;
  readonly locale: Locale;
  readonly database?: MorrowindMapDatabase;
  readonly disabled?: boolean;
  readonly inputRef?: Ref<HTMLInputElement>;
  readonly onSaved?: (marker: CustomMarkerRecord) => void;
  readonly onDeleted?: (markerId: string) => void;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function markerDraftStorageKey(markerId: string): string {
  return `${LOCAL_STORAGE_PREFIX}:draft:custom-marker:${encodeURIComponent(markerId)}`;
}

function readStoredMarkerDraft(markerId: string): MarkerDraft | null {
  try {
    const serialized = window.localStorage.getItem(markerDraftStorageKey(markerId));
    if (serialized === null) {
      return null;
    }
    const value: unknown = JSON.parse(serialized);
    if (
      typeof value === 'object' &&
      value !== null &&
      'label' in value &&
      typeof value.label === 'string' &&
      'note' in value &&
      typeof value.note === 'string'
    ) {
      return { markerId, label: value.label, note: value.note };
    }
  } catch {
    // Ignore unavailable storage and malformed crash-recovery data.
  }
  return null;
}

function writeStoredMarkerDraft(draft: MarkerDraft): void {
  try {
    window.localStorage.setItem(
      markerDraftStorageKey(draft.markerId),
      JSON.stringify({ label: draft.label, note: draft.note }),
    );
  } catch {
    // IndexedDB remains the primary store; restricted localStorage only disables crash recovery.
  }
}

function clearStoredMarkerDraft(draft: MarkerDraft): void {
  try {
    const key = markerDraftStorageKey(draft.markerId);
    const stored = readStoredMarkerDraft(draft.markerId);
    if (stored?.label === draft.label && stored.note === draft.note) {
      window.localStorage.removeItem(key);
    }
  } catch {
    // See writeStoredMarkerDraft.
  }
}

export function CustomMarkerEditor({
  marker,
  locale,
  database = userDatabase,
  disabled = false,
  inputRef,
  onSaved,
  onDeleted,
}: CustomMarkerEditorProps) {
  const strings = getUserDataStrings(locale);
  const labelId = useId();
  const noteId = useId();
  const [draft, setDraft] = useState<MarkerDraft | null>(() => readStoredMarkerDraft(marker.id));
  const [busy, setBusy] = useState<'save' | 'delete' | null>(null);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<MarkerFeedback | null>(null);
  const saveInFlightRef = useRef<string | null>(null);
  const deleteButtonRef = useRef<HTMLButtonElement>(null);
  const confirmDeleteButtonRef = useRef<HTMLButtonElement>(null);
  const activeDraft = draft?.markerId === marker.id ? draft : null;
  const label = activeDraft?.label ?? marker.label;
  const note = activeDraft?.note ?? marker.note;
  const currentFeedback = feedback?.markerId === marker.id ? feedback : null;
  const confirmingDelete = confirmingDeleteId === marker.id;
  const isDisabled = disabled || busy !== null;

  const persist = useCallback(async (nextLabel: string, nextNote: string) => {
    const revision = `${nextLabel}\0${nextNote}`;
    if (
      isDisabled ||
      saveInFlightRef.current === revision ||
      nextLabel.trim().length === 0
    ) {
      return;
    }
    if (nextLabel.trim() === marker.label && nextNote === marker.note) {
      clearStoredMarkerDraft({ markerId: marker.id, label: nextLabel, note: nextNote });
      return;
    }
    saveInFlightRef.current = revision;
    setBusy('save');
    setFeedback(null);
    try {
      const saved = await saveCustomMarker(database, {
        id: marker.id,
        datasetId: marker.datasetId,
        label: nextLabel,
        note: nextNote,
        position: marker.position,
      });
      clearStoredMarkerDraft({ markerId: marker.id, label: nextLabel, note: nextNote });
      setDraft((current) =>
        current?.markerId === marker.id &&
        (current.label !== nextLabel || current.note !== nextNote)
          ? current
          : { markerId: marker.id, label: saved.label, note: saved.note },
      );
      onSaved?.(saved);
      setFeedback({ markerId: marker.id, tone: 'status', text: strings.saved });
    } catch (error: unknown) {
      setFeedback({
        markerId: marker.id,
        tone: 'error',
        text: `${strings.operationFailed}: ${errorText(error)}`,
      });
    } finally {
      if (saveInFlightRef.current === revision) {
        saveInFlightRef.current = null;
      }
      setBusy(null);
    }
  }, [database, isDisabled, marker, onSaved, strings]);

  useEffect(() => {
    if (
      isDisabled ||
      label.trim().length === 0 ||
      (label.trim() === marker.label && note === marker.note)
    ) {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => void persist(label, note), 350);
    return () => window.clearTimeout(timeoutId);
  }, [isDisabled, label, marker.label, marker.note, note, persist]);

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void persist(label, note);
  };

  const remove = async () => {
    if (isDisabled) {
      return;
    }
    setBusy('delete');
    setFeedback(null);
    try {
      await deleteCustomMarker(database, marker.id);
      clearStoredMarkerDraft({ markerId: marker.id, label, note });
      setConfirmingDeleteId(null);
      onDeleted?.(marker.id);
      setFeedback({ markerId: marker.id, tone: 'status', text: strings.deleted });
    } catch (error: unknown) {
      setFeedback({
        markerId: marker.id,
        tone: 'error',
        text: `${strings.operationFailed}: ${errorText(error)}`,
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="custom-marker-editor" aria-label={strings.customMarker} aria-busy={busy !== null}>
      <form
        onSubmit={save}
        onBlur={(event) => {
          const nextTarget = event.relatedTarget;
          if (
            (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) ||
            (nextTarget instanceof HTMLElement &&
              nextTarget.closest('[data-skip-marker-autosave]'))
          ) {
            return;
          }
          void persist(label, note);
        }}
      >
        <label htmlFor={labelId}>{strings.label}</label>
        <input
          id={labelId}
          ref={inputRef}
          type="text"
          required
          maxLength={512}
          value={label}
          disabled={isDisabled}
          onChange={(event) => {
            const nextDraft = { markerId: marker.id, label: event.currentTarget.value, note };
            setDraft(nextDraft);
            writeStoredMarkerDraft(nextDraft);
          }}
        />

        <label htmlFor={noteId}>{strings.note}</label>
        <textarea
          id={noteId}
          maxLength={10_000}
          value={note}
          disabled={isDisabled}
          onChange={(event) => {
            const nextDraft = { markerId: marker.id, label, note: event.currentTarget.value };
            setDraft(nextDraft);
            writeStoredMarkerDraft(nextDraft);
          }}
        />

        <button type="submit" disabled={isDisabled || label.trim().length === 0}>
          {strings.saveMarker}
        </button>
      </form>

      {!confirmingDelete ? (
        <button
          ref={deleteButtonRef}
          type="button"
          data-skip-marker-autosave
          disabled={isDisabled}
          onClick={() => {
            setConfirmingDeleteId(marker.id);
            window.requestAnimationFrame(() => confirmDeleteButtonRef.current?.focus());
          }}
        >
          {strings.deleteMarker}
        </button>
      ) : (
        <div className="custom-marker-editor__delete-confirmation" role="alert">
          <p>{strings.confirmDelete}</p>
          <button
            ref={confirmDeleteButtonRef}
            type="button"
            disabled={isDisabled}
            onClick={() => void remove()}
          >
            {busy === 'delete' ? strings.deleting : strings.confirmDeleteAction}
          </button>
          <button
            type="button"
            disabled={isDisabled}
            onClick={() => {
              setConfirmingDeleteId(null);
              window.requestAnimationFrame(() => deleteButtonRef.current?.focus());
            }}
          >
            {strings.cancel}
          </button>
        </div>
      )}

      {currentFeedback ? (
        <p role={currentFeedback.tone === 'error' ? 'alert' : 'status'} aria-live="polite">
          {currentFeedback.text}
        </p>
      ) : null}
    </section>
  );
}
