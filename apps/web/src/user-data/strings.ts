import type { Locale, ProgressStatus } from '@morrowind-map/contracts';
import type { BackupImportResult, MimImportResult } from '../storage/userData';

interface UserDataStrings {
  readonly dataToolsTitle: string;
  readonly mimImport: string;
  readonly mimUnavailable: string;
  readonly exportJson: string;
  readonly importJson: string;
  readonly importJsonHint: string;
  readonly importing: string;
  readonly exporting: string;
  readonly mimDuplicate: string;
  readonly backupExported: string;
  readonly fileTooLarge: string;
  readonly operationFailed: string;
  readonly placeProgress: string;
  readonly status: string;
  readonly note: string;
  readonly saveNote: string;
  readonly saved: string;
  readonly customMarker: string;
  readonly label: string;
  readonly saveMarker: string;
  readonly deleteMarker: string;
  readonly confirmDelete: string;
  readonly confirmDeleteAction: string;
  readonly cancel: string;
  readonly deleting: string;
  readonly deleted: string;
  readonly statuses: Readonly<Record<ProgressStatus, string>>;
  readonly mimResult: (result: MimImportResult) => string;
  readonly backupResult: (result: BackupImportResult) => string;
}

const EN: UserDataStrings = {
  dataToolsTitle: 'Data and backups',
  mimImport: 'Import MIM progress',
  mimUnavailable: 'This dataset has no MIM import artifact.',
  exportJson: 'Download JSON backup',
  importJson: 'Import JSON backup',
  importJsonHint: 'JSON files up to 10 MB',
  importing: 'Importing…',
  exporting: 'Preparing backup…',
  mimDuplicate: 'This MIM snapshot was already imported. Nothing changed.',
  backupExported: 'JSON backup downloaded.',
  fileTooLarge: 'The selected file is larger than 10 MB.',
  operationFailed: 'The operation failed',
  placeProgress: 'Place progress',
  status: 'Status',
  note: 'Personal note',
  saveNote: 'Save note',
  saved: 'Saved.',
  customMarker: 'Custom marker',
  label: 'Marker name',
  saveMarker: 'Save marker',
  deleteMarker: 'Delete marker',
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
  mimResult: (result) =>
    `MIM imported: ${result.progressImported} places and ${result.markersImported} markers; ` +
    `${result.progressSkipped + result.markersSkipped} skipped, ${result.markersRemoved} removed.`,
  backupResult: (result) =>
    `Backup imported: ${result.progressImported} places and ${result.markersImported} markers; ` +
    `${result.progressSkipped + result.markersSkipped} kept locally.`,
};

const RU: UserDataStrings = {
  dataToolsTitle: 'Данные и резервные копии',
  mimImport: 'Импортировать прогресс MIM',
  mimUnavailable: 'Для этой версии нет артефакта импорта MIM.',
  exportJson: 'Скачать резервную копию JSON',
  importJson: 'Импортировать резервную копию JSON',
  importJsonHint: 'JSON-файлы размером до 10 МБ',
  importing: 'Импортирую…',
  exporting: 'Готовлю резервную копию…',
  mimDuplicate: 'Этот снимок MIM уже импортирован. Данные не изменились.',
  backupExported: 'Резервная копия JSON скачана.',
  fileTooLarge: 'Размер выбранного файла превышает 10 МБ.',
  operationFailed: 'Не удалось выполнить операцию',
  placeProgress: 'Прогресс локации',
  status: 'Статус',
  note: 'Личная заметка',
  saveNote: 'Сохранить заметку',
  saved: 'Сохранено.',
  customMarker: 'Личная отметка',
  label: 'Название отметки',
  saveMarker: 'Сохранить отметку',
  deleteMarker: 'Удалить отметку',
  confirmDelete: 'Удалить эту отметку? Действие нельзя отменить.',
  confirmDeleteAction: 'Да, удалить',
  cancel: 'Отмена',
  deleting: 'Удаляю…',
  deleted: 'Отметка удалена.',
  statuses: {
    unvisited: 'Не посещено',
    active: 'Активно',
    visited: 'Посещено',
  },
  mimResult: (result) =>
    `MIM импортирован: ${result.progressImported} локаций и ${result.markersImported} отметок; ` +
    `пропущено ${result.progressSkipped + result.markersSkipped}, удалено ${result.markersRemoved}.`,
  backupResult: (result) =>
    `Копия импортирована: ${result.progressImported} локаций и ${result.markersImported} отметок; ` +
    `локально сохранено ${result.progressSkipped + result.markersSkipped}.`,
};

export function getUserDataStrings(locale: Locale): UserDataStrings {
  return locale === 'ru' ? RU : EN;
}
