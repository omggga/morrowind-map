import type { MapUrlState, MapUrlView } from './mapUrlState';

export interface MapUrlConstraints {
  readonly datasetId: string;
  readonly availableRegionIds: ReadonlySet<string>;
  readonly placeRegions: ReadonlyMap<string, string>;
  readonly extent: readonly [number, number, number, number];
  readonly minimumZoom: number;
  readonly maximumZoom: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export function normalizeMapUrlState(
  state: MapUrlState,
  constraints: MapUrlConstraints,
): MapUrlState {
  const requestedRegion = constraints.availableRegionIds.has(state.regionId)
    ? state.regionId
    : 'all';
  const placeRegion = state.placeId === null
    ? undefined
    : constraints.placeRegions.get(state.placeId);
  const placeId = placeRegion === undefined ? null : state.placeId;
  const regionId = placeRegion !== undefined &&
      requestedRegion !== 'all' &&
      placeRegion !== requestedRegion
    ? placeRegion
    : requestedRegion;
  const [minimumX, minimumY, maximumX, maximumY] = constraints.extent;
  const view = state.view === null
    ? null
    : {
        center: [
          clamp(state.view.center[0], minimumX, maximumX),
          clamp(state.view.center[1], minimumY, maximumY),
        ],
        zoom: clamp(state.view.zoom, constraints.minimumZoom, constraints.maximumZoom),
      } satisfies MapUrlView;

  return {
    datasetId: constraints.datasetId,
    regionId: constraints.availableRegionIds.has(regionId) ? regionId : 'all',
    view,
    placeId,
  };
}
