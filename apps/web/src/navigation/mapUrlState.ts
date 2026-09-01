export interface MapUrlView {
  readonly center: readonly [number, number];
  readonly zoom: number;
}

export interface MapUrlState {
  readonly datasetId: string | null;
  readonly regionId: string;
  readonly view: MapUrlView | null;
  readonly placeId: string | null;
}

const OWNED_PARAMETERS = ['dataset', 'region', 'x', 'y', 'z', 'place'] as const;

function landingState(): MapUrlState {
  return {
    datasetId: null,
    regionId: 'all',
    view: null,
    placeId: null,
  };
}

function nonEmptyParameter(parameters: URLSearchParams, name: string): string | null {
  const value = parameters.get(name);
  return value === null || value.length === 0 ? null : value;
}

function finiteNumberParameter(parameters: URLSearchParams, name: string): number | null {
  const value = parameters.get(name);
  if (value === null || value.trim().length === 0) {
    return null;
  }

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function readView(parameters: URLSearchParams): MapUrlView | null {
  const x = finiteNumberParameter(parameters, 'x');
  const y = finiteNumberParameter(parameters, 'y');
  const zoom = finiteNumberParameter(parameters, 'z');

  if (x === null || y === null || zoom === null) {
    return null;
  }

  return { center: [x, y], zoom };
}

function hasFiniteView(view: MapUrlView): boolean {
  return Number.isFinite(view.center[0]) &&
    Number.isFinite(view.center[1]) &&
    Number.isFinite(view.zoom);
}

function normalizeNegativeZero(value: number): number {
  return Object.is(value, -0) ? 0 : value;
}

function roundedWorldCoordinate(value: number): string {
  return String(normalizeNegativeZero(Math.round(value)));
}

function roundedZoom(value: number): string {
  return String(normalizeNegativeZero(Number(value.toFixed(2))));
}

export function readMapUrl(url: URL): MapUrlState {
  const datasetId = nonEmptyParameter(url.searchParams, 'dataset');
  if (datasetId === null) {
    return landingState();
  }

  return {
    datasetId,
    regionId: nonEmptyParameter(url.searchParams, 'region') ?? 'all',
    view: readView(url.searchParams),
    placeId: nonEmptyParameter(url.searchParams, 'place'),
  };
}

export function writeMapUrl(baseUrl: URL, state: MapUrlState): URL {
  const url = new URL(baseUrl.href);
  for (const parameter of OWNED_PARAMETERS) {
    url.searchParams.delete(parameter);
  }

  if (state.datasetId === null || state.datasetId.length === 0) {
    return url;
  }

  url.searchParams.append('dataset', state.datasetId);
  url.searchParams.append('region', state.regionId || 'all');

  if (state.view !== null && hasFiniteView(state.view)) {
    url.searchParams.append('x', roundedWorldCoordinate(state.view.center[0]));
    url.searchParams.append('y', roundedWorldCoordinate(state.view.center[1]));
    url.searchParams.append('z', roundedZoom(state.view.zoom));
  }

  if (state.placeId !== null && state.placeId.length > 0) {
    url.searchParams.append('place', state.placeId);
  }

  return url;
}
