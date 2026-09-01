import type { PlaceType, ProgressStatus } from '@morrowind-map/contracts';
import type { RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { StatusMark } from '../ui/StatusMark';

const PROGRESS_STATUSES = ['unvisited', 'active', 'visited'] as const satisfies readonly ProgressStatus[];

export interface PlaceFilterControlsProps {
  readonly availableTypes: readonly PlaceType[];
  readonly selectedTypes: ReadonlySet<PlaceType>;
  readonly selectedStatuses: ReadonlySet<ProgressStatus>;
  readonly typeCounts: ReadonlyMap<PlaceType, number>;
  readonly statusCounts: ReadonlyMap<ProgressStatus, number>;
  readonly activeAxisCount: number;
  readonly statusesDisabled?: boolean;
  readonly onToggleType: (type: PlaceType) => void;
  readonly onToggleStatus: (status: ProgressStatus) => void;
  readonly onClearTypes: () => void;
  readonly onClearStatuses: () => void;
  readonly onReset: () => void;
  readonly resetFocusRef: RefObject<HTMLButtonElement | null>;
}

interface FilterOptionProps {
  readonly className?: string;
  readonly label: string;
  readonly count: number;
  readonly pressed: boolean;
  readonly markerKind?: ProgressStatus;
  readonly onClick: () => void;
}

function FilterOption({
  className = '',
  label,
  count,
  pressed,
  markerKind,
  onClick,
}: FilterOptionProps) {
  return (
    <button
      type="button"
      className={`place-filter-option${className ? ` ${className}` : ''}`}
      aria-pressed={pressed}
      onClick={onClick}
    >
      {markerKind ? (
        <StatusMark kind={markerKind} />
      ) : (
        <span className="place-filter-option__check" aria-hidden="true" />
      )}
      <span className="place-filter-option__label">{label}</span>
      {' '}
      <span className="place-filter-option__count">{count.toLocaleString('en-US')}</span>
    </button>
  );
}

function countAvailableTypes(
  availableTypes: readonly PlaceType[],
  typeCounts: ReadonlyMap<PlaceType, number>,
): number {
  return availableTypes.reduce((total, type) => total + (typeCounts.get(type) ?? 0), 0);
}

function countStatuses(statusCounts: ReadonlyMap<ProgressStatus, number>): number {
  return PROGRESS_STATUSES.reduce(
    (total, status) => total + (statusCounts.get(status) ?? 0),
    0,
  );
}

export function PlaceFilterControls({
  availableTypes,
  selectedTypes,
  selectedStatuses,
  typeCounts,
  statusCounts,
  activeAxisCount,
  statusesDisabled = false,
  onToggleType,
  onToggleStatus,
  onClearTypes,
  onClearStatuses,
  onReset,
  resetFocusRef,
}: PlaceFilterControlsProps) {
  const { t } = useTranslation();

  return (
    <details className="place-filter-drawer">
      <summary className="place-filter-drawer__summary">
        <span>{t('map.filters')}</span>
        {activeAxisCount > 0 ? (
          <span className="place-filter-drawer__summary-state">
            {t(
              activeAxisCount === 1 ? 'map.filterSummaryOne' : 'map.filterSummaryMany',
              { active: activeAxisCount },
            )}
          </span>
        ) : null}
      </summary>

      <div className="place-filter-drawer__body">
        <fieldset className="place-filter-axis place-filter-axis--types">
          <legend>{t('map.typeFilters')}</legend>
          <div className="place-filter-options place-filter-options--types">
            <FilterOption
              className="place-filter-option--any"
              label={t('map.allTypes')}
              count={countAvailableTypes(availableTypes, typeCounts)}
              pressed={selectedTypes.size === 0}
              onClick={onClearTypes}
            />
            {availableTypes.map((type) => (
              <FilterOption
                key={type}
                label={t(`placeType.${type}`)}
                count={typeCounts.get(type) ?? 0}
                pressed={selectedTypes.has(type)}
                onClick={() => onToggleType(type)}
              />
            ))}
          </div>
        </fieldset>

        <fieldset
          className="place-filter-axis place-filter-axis--statuses"
          disabled={statusesDisabled}
        >
          <legend>{t('map.statusFilters')}</legend>
          <div className="place-filter-options place-filter-options--statuses">
            <FilterOption
              className="place-filter-option--any"
              label={t('map.allStatuses')}
              count={countStatuses(statusCounts)}
              pressed={selectedStatuses.size === 0}
              onClick={onClearStatuses}
            />
            {PROGRESS_STATUSES.map((status) => (
              <FilterOption
                key={status}
                className={`place-filter-option--status-${status}`}
                label={t(`map.${status}`)}
                count={statusCounts.get(status) ?? 0}
                markerKind={status}
                pressed={selectedStatuses.has(status)}
                onClick={() => onToggleStatus(status)}
              />
            ))}
          </div>
        </fieldset>

        <button
          ref={resetFocusRef}
          className="place-filter-reset"
          type="button"
          disabled={activeAxisCount === 0}
          onClick={onReset}
        >
          {t('map.resetFilters')}
        </button>
      </div>
    </details>
  );
}
