import type { Locale, ProgressStatus } from '@morrowind-map/contracts';
import type { BackupImportResult } from '../storage/userData';

interface UserDataStrings {
  readonly dataToolsTitle: string;
  readonly exportJson: string;
  readonly importJson: string;
  readonly importJsonHint: string;
  readonly importing: string;
  readonly exporting: string;
  readonly backupExported: string;
  readonly fileTooLarge: string;
  readonly operationFailed: (detail: string, retryLabel: string) => string;
  readonly placeProgress: string;
  readonly status: string;
  readonly note: string;
  readonly noteSaveFailed: (detail: string) => string;
  readonly saved: string;
  readonly customMarker: string;
  readonly label: string;
  readonly save: string;
  readonly deleteMarker: string;
  readonly confirmDelete: string;
  readonly confirmDeleteAction: string;
  readonly cancel: string;
  readonly deleting: string;
  readonly deleted: string;
  readonly statuses: Readonly<Record<ProgressStatus, string>>;
  readonly backupResult: (result: BackupImportResult) => string;
}

const EN: UserDataStrings = {
  dataToolsTitle: 'Data and backups',
  exportJson: 'Download JSON backup',
  importJson: 'Import JSON backup',
  importJsonHint: 'JSON files up to 10 MB',
  importing: 'Importing…',
  exporting: 'Preparing backup…',
  backupExported: 'JSON backup downloaded.',
  fileTooLarge: 'The selected file is larger than 10 MB. Choose a smaller JSON file and try again.',
  operationFailed: (detail, retryLabel) =>
    `The operation failed: ${detail}. Select “${retryLabel}” to try again.`,
  placeProgress: 'Place progress',
  status: 'Status',
  note: 'Personal note',
  noteSaveFailed: (detail) =>
    `The note could not be saved: ${detail}. Select “Save” to try again.`,
  saved: 'Saved.',
  customMarker: 'Custom marker',
  label: 'Marker name',
  save: 'Save',
  deleteMarker: 'Delete',
  confirmDelete: 'Delete this marker? This action cannot be undone.',
  confirmDeleteAction: 'Yes, delete',
  cancel: 'Cancel',
  deleting: 'Deleting…',
  deleted: 'Marker deleted.',
  statuses: {
    unvisited: 'Unvisited',
    active: 'Active',
    visited: 'Visited',
  },
  backupResult: (result) =>
    `Backup imported: ${result.progressImported} places and ${result.markersImported} markers; ` +
    `${result.progressSkipped + result.markersSkipped} kept locally.`,
};

export function getUserDataStrings(locale: Locale): UserDataStrings {
  void locale;
  return EN;
}
