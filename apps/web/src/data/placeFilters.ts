import type {
  PlaceType,
  ProgressRecord,
  ProgressStatus,
} from '@morrowind-map/contracts';
import type { PlaceView } from './placeSearch';

export const PLACE_TYPE_ORDER = [
  'settlement',
  'landmark',
  'stronghold',
  'dwemer-ruin',
  'temple',
  'shrine',
  'mine',
  'cave',
  'ancestral-tomb',
  'ship',
  'guild',
  'shop',
  'house',
  'other',
] as const satisfies readonly PlaceType[];

export const PROGRESS_STATUS_ORDER = [
  'active',
  'unvisited',
  'visited',
] as const satisfies readonly ProgressStatus[];

export interface PlaceFilterState {
  readonly regionId: string;
  readonly types: ReadonlySet<PlaceType>;
  readonly statuses: ReadonlySet<ProgressStatus>;
}

interface PlaceVisibilityContext {
  readonly filters: PlaceFilterState;
  readonly zoom: number;
  readonly progressByPlaceId: ReadonlyMap<string, ProgressRecord>;
}

interface PlaceLabelPriorityContext {
  readonly selectedPlaceId: string | null;
  readonly searchMatchIds: ReadonlySet<string>;
  readonly progressByPlaceId: ReadonlyMap<string, ProgressRecord>;
}

const PLACE_TYPE_PRIORITY = new Map<PlaceType, number>(
  PLACE_TYPE_ORDER.map((type, index) => [type, index]),
);
const PROGRESS_STATUS_PRIORITY = new Map<ProgressStatus, number>(
  PROGRESS_STATUS_ORDER.map((status, index) => [status, index]),
);

export function progressStatusFor(
  placeId: string,
  progressByPlaceId: ReadonlyMap<string, ProgressRecord>,
): ProgressStatus {
  return progressByPlaceId.get(placeId)?.status ?? 'unvisited';
}

export function getAvailablePlaceTypes(
  places: readonly PlaceView[],
): PlaceType[] {
  const availableTypes = new Set(places.map(({ place }) => place.type));
  return PLACE_TYPE_ORDER.filter((type) => availableTypes.has(type));
}

export function isPlaceVisible(
  place: PlaceView,
  { filters, zoom, progressByPlaceId }: PlaceVisibilityContext,
): boolean {
  const matchesRegion = filters.regionId === 'all' ||
    place.place.regionId === filters.regionId;
  const matchesType = filters.types.size === 0 || filters.types.has(place.place.type);
  const status = progressStatusFor(place.id, progressByPlaceId);
  const matchesStatus = filters.statuses.size === 0 || filters.statuses.has(status);

  return matchesRegion &&
    matchesType &&
    matchesStatus &&
    place.place.minZoom <= zoom;
}

function comparePreferred(left: boolean, right: boolean): number {
  return Number(right) - Number(left);
}

export function comparePlaceLabelPriority(
  left: PlaceView,
  right: PlaceView,
  {
    selectedPlaceId,
    searchMatchIds,
    progressByPlaceId,
  }: PlaceLabelPriorityContext,
): number {
  const selectedComparison = comparePreferred(
    left.id === selectedPlaceId,
    right.id === selectedPlaceId,
  );
  if (selectedComparison !== 0) {
    return selectedComparison;
  }

  const searchComparison = comparePreferred(
    searchMatchIds.has(left.id),
    searchMatchIds.has(right.id),
  );
  if (searchComparison !== 0) {
    return searchComparison;
  }

  const typeComparison = (PLACE_TYPE_PRIORITY.get(left.place.type) ?? Number.MAX_SAFE_INTEGER) -
    (PLACE_TYPE_PRIORITY.get(right.place.type) ?? Number.MAX_SAFE_INTEGER);
  if (typeComparison !== 0) {
    return typeComparison;
  }

  const statusComparison = (
    PROGRESS_STATUS_PRIORITY.get(progressStatusFor(left.id, progressByPlaceId)) ??
      Number.MAX_SAFE_INTEGER
  ) - (
    PROGRESS_STATUS_PRIORITY.get(progressStatusFor(right.id, progressByPlaceId)) ??
      Number.MAX_SAFE_INTEGER
  );
  if (statusComparison !== 0) {
    return statusComparison;
  }

  return left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
}
