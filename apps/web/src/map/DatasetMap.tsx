import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type Ref,
  type ReactNode,
} from 'react';
import {
  ContractValidationError,
  type CustomMarkerRecord,
  type DatasetManifest,
  type Locale,
  type PlaceType,
  type ProgressRecord,
  type ProgressStatus,
} from '@morrowind-map/contracts';
import Feature, { type FeatureLike } from 'ol/Feature.js';
import Map from 'ol/Map.js';
import View from 'ol/View.js';
import Point from 'ol/geom/Point.js';
import { defaults as defaultInteractions } from 'ol/interaction/defaults.js';
import ImageLayer from 'ol/layer/Image.js';
import TileLayer from 'ol/layer/Tile.js';
import VectorLayer from 'ol/layer/Vector.js';
import { unByKey } from 'ol/Observable.js';
import type Tile from 'ol/Tile.js';
import ImageStatic from 'ol/source/ImageStatic.js';
import VectorSource from 'ol/source/Vector.js';
import XYZ from 'ol/source/XYZ.js';
import Fill from 'ol/style/Fill.js';
import Icon from 'ol/style/Icon.js';
import Stroke from 'ol/style/Stroke.js';
import Style from 'ol/style/Style.js';
import Text from 'ol/style/Text.js';
import { useTranslation } from 'react-i18next';
import {
  DatasetAssetsInvalidError,
  DatasetAssetsMissingError,
  loadDataset,
  type DatasetBundle,
} from '../data/loadDataset';
import {
  PLACE_TYPE_ORDER,
  PROGRESS_STATUS_ORDER,
  comparePlaceLabelPriority,
  getAvailablePlaceTypes,
  isPlaceVisible,
  progressStatusFor,
  type PlaceFilterState,
} from '../data/placeFilters';
import { buildPlaceViews, PlaceSearch, type PlaceView } from '../data/placeSearch';
import { presentDataset } from '../data/datasetPresentation';
import { placeWikiUrl } from '../data/placeWiki';
import { writeMapUrl, type MapUrlState, type MapUrlView } from '../navigation/mapUrlState';
import { normalizeMapUrlState } from '../navigation/normalizeMapUrlState';
import { userDatabase } from '../storage/database';
import {
  DatasetSnapshotConflictError,
  MAX_MARKER_LABEL_LENGTH,
  ensureDatasetSnapshot,
  saveCustomMarker,
} from '../storage/userData';
import {
  CustomMarkerEditor,
  DataTools,
  PlaceProgressEditor,
  useDatasetCustomMarkers,
  useDatasetProgress,
} from '../user-data';
import { PixelIcon } from '../ui/PixelIcon';
import { StatusMark } from '../ui/StatusMark';
import { MapSettings } from '../ui/MapSettings';
import { MarkerAppearanceContext } from '../ui/MarkerAppearanceContext';
import { readColorblindPreference, saveColorblindPreference } from '../ui/mapPreferences';
import {
  createFocusReturnController,
  isKeyboardActivation,
} from '../ui/focusManagement';
import {
  MARKER_KINDS,
  MARKER_SEMANTICS,
  markerColor,
  markerAppearance,
  type MarkerKind,
} from '../ui/markerSemantics';
import { CurrentBasemapLoadWindow } from './currentBasemapLoadWindow';
import {
  BASEMAP_BRIGHTNESS_FACTOR,
  BASEMAP_CONTRAST_FACTOR,
  createOverscaledViewResolutions,
  loadOpaqueImageTile,
  requiresRuntimeBasemapAdjustment,
} from './basemapPresentation';
import { PlaceFilterControls } from './PlaceFilterControls';
import {
  SparseTileCoverageIndex,
  createSparseTileUrlFunction,
  createTes3TileGrid,
} from './sparseTiles';
import {
  configureTes3Projection,
  type WorldCoordinate,
} from './tes3Projection';

interface MapTitlebarProps {
  readonly dataset: DatasetManifest;
  readonly onBack: () => void;
  readonly tools?: ReactNode;
}

interface DatasetMapProps extends MapTitlebarProps {
  readonly datasetSnapshots: Readonly<Record<string, string>>;
  readonly focusMapOnMount?: boolean;
  readonly navigationState: MapUrlState;
  readonly navigationRevision: number;
  readonly onNavigationChange: (
    state: MapUrlState,
    mode: 'push' | 'replace',
  ) => void;
}

type RegionFilter = string;

type LoadState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly bundle: DatasetBundle }
  | { readonly status: 'missing'; readonly message: string }
  | { readonly status: 'invalid'; readonly message: string }
  | { readonly status: 'error'; readonly message: string; readonly retrying: boolean };

type UserDataBindingState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready' }
  | { readonly status: 'conflict'; readonly message: string }
  | { readonly status: 'error'; readonly message: string };

interface BasemapRuntimeState {
  readonly pending: number;
  readonly failures: number;
  readonly loaded: number;
  readonly missing: boolean;
  readonly retrying: boolean;
}

type MarkerEmphasis = 'default' | 'hovered' | 'selected';

const RESULT_BATCH_SIZE = 80;
const DEFAULT_MAP_ZOOM = 3;
const OLD_EBONHEART_VIEW: MapUrlView = {
  center: [53_248, -151_552],
  zoom: 4,
};

const MARKER_STYLE_CACHE = new globalThis.Map<string, Style[]>();

const SELECTED_PLACE_COLOR = '#6fe7ff';
const SELECTED_PLACE_ICON_SOURCE = `data:image/svg+xml,${encodeURIComponent(
  `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 12 12" shape-rendering="crispEdges"><path d="${MARKER_SEMANTICS.unvisited.path}" fill="${SELECTED_PLACE_COLOR}" fill-rule="evenodd"/></svg>`,
)}`;

function createMarkerStyles(kind: MarkerKind, emphasis: MarkerEmphasis, colorblind = false): Style[] {
  const key = `${kind}:${emphasis}:${colorblind}`;
  const cached = MARKER_STYLE_CACHE.get(key);
  if (cached) {
    return cached;
  }
  const semantic = markerAppearance(kind, colorblind);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 12 12" shape-rendering="crispEdges"><path d="${semantic.path}" fill="${markerColor(kind, colorblind)}" fill-rule="${semantic.fillRule}"/></svg>`;
  const baseZIndex = emphasis === 'selected' ? 112 : emphasis === 'hovered' ? 102 : 92;
  const selectedPlace = emphasis === 'selected' && kind !== 'custom';
  const styles = [new Style({
    image: new Icon({
      src: selectedPlace && !colorblind ? SELECTED_PLACE_ICON_SOURCE : `data:image/svg+xml,${encodeURIComponent(svg)}`,
      scale: 0.35,
    }),
    zIndex: baseZIndex,
  })];
  MARKER_STYLE_CACHE.set(key, styles);
  return styles;
}

const PLACE_LABEL_STYLE_CACHE = new globalThis.Map<string, Style>();
const BASEMAP_PRESENTATION_STYLE = {
  '--basemap-brightness': String(BASEMAP_BRIGHTNESS_FACTOR),
  '--basemap-contrast': String(BASEMAP_CONTRAST_FACTOR),
} as CSSProperties;

function createPlaceLabelStyle(
  name: string,
  selected: boolean,
  searchMatch: boolean,
  status: MarkerKind,
  showAll: boolean,
  hovered = false,
  colorblind = false,
): Style {
  const emphasized = selected || hovered;
  const tone = selected ? 'selected' : searchMatch ? 'match' : 'default';
  const cacheKey = `${tone}\0${hovered}\0${status}\0${showAll}\0${colorblind}\0${name}`;
  const cached = PLACE_LABEL_STYLE_CACHE.get(cacheKey);
  if (cached) {
    return cached;
  }

  const style = new Style({
    text: new Text({
      text: name,
      font: emphasized || searchMatch
        ? '600 10px "Atkinson Hyperlegible Next Variable", Arial, sans-serif'
        : '500 10px "Atkinson Hyperlegible Next Variable", Arial, sans-serif',
      offsetY: -11,
      padding: hovered ? [3, 5, 3, 5] : [1, 2, 1, 2],
      backgroundFill: hovered ? new Fill({ color: 'rgba(23, 19, 13, 0.7)' }) : undefined,
      fill: new Fill({ color: selected && status !== 'custom' && !colorblind ? SELECTED_PLACE_COLOR : markerColor(status, colorblind) }),
      stroke: new Stroke({ color: '#17130d', width: 2 }),
      declutterMode: emphasized || showAll ? 'none' : 'declutter',
      overflow: true,
    }),
    zIndex: hovered ? 2 : selected ? 1 : 0,
  });
  PLACE_LABEL_STYLE_CACHE.set(cacheKey, style);
  return style;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown dataset error';
}

function regionTitle(dataset: DatasetManifest, regionId: string): string {
  const region = dataset.regions.find(({ id }) => id === regionId);
  return region?.title.en ?? regionId;
}

function regionNavigationView(
  dataset: DatasetManifest,
  regionId: string,
  minimumZoom: number,
  maximumZoom: number,
): MapUrlView | null {
  const clampZoom = (zoom: number) => Math.min(maximumZoom, Math.max(minimumZoom, zoom));
  if (regionId === 'all') {
    return {
      center: [...dataset.map.projection.center],
      zoom: clampZoom(DEFAULT_MAP_ZOOM + (
        dataset.mapKey === 'home-of-nords' || dataset.mapKey === 'project-cyrodiil' || dataset.mapKey === 'azurian-isles' ? 1 : 0
      )),
    };
  }
  if (dataset.mapKey === 'tamriel-rebuilt' && regionId === 'tr-mainland') {
    return {
      center: [...OLD_EBONHEART_VIEW.center],
      zoom: clampZoom(OLD_EBONHEART_VIEW.zoom),
    };
  }
  return null;
}

function regionExtent(
  bundle: DatasetBundle,
  regionId: string,
  worldExtent: readonly [number, number, number, number],
  cellSize: number,
): readonly [number, number, number, number] | null {
  const rasterExtents = bundle.mapAssets.rasters
    .filter((raster) => raster.regionId === regionId)
    .map(({ extent }) => extent);
  if (rasterExtents.length > 0) {
    return [
      Math.min(...rasterExtents.map(([minX]) => minX)),
      Math.min(...rasterExtents.map(([, minY]) => minY)),
      Math.max(...rasterExtents.map(([, , maxX]) => maxX)),
      Math.max(...rasterExtents.map(([, , , maxY]) => maxY)),
    ];
  }

  const positions = bundle.locations.places
    .filter((place) => place.regionId === regionId)
    .map(({ mapPosition }) => mapPosition);
  if (positions.length === 0) {
    return null;
  }
  const padding = cellSize * 2;
  const [worldMinX, worldMinY, worldMaxX, worldMaxY] = worldExtent;
  return [
    Math.max(worldMinX, Math.min(...positions.map(([x]) => x)) - padding),
    Math.max(worldMinY, Math.min(...positions.map(([, y]) => y)) - padding),
    Math.min(worldMaxX, Math.max(...positions.map(([x]) => x)) + padding),
    Math.min(worldMaxY, Math.max(...positions.map(([, y]) => y)) + padding),
  ];
}

function visibilityZoomFor(
  thresholds: readonly number[],
  zoom: number,
): number {
  let lower = 0;
  let upper = thresholds.length - 1;
  let visibleThreshold = Number.NEGATIVE_INFINITY;

  while (lower <= upper) {
    const middle = Math.floor((lower + upper) / 2);
    const threshold = thresholds[middle] ?? Number.POSITIVE_INFINITY;
    if (threshold <= zoom) {
      visibleThreshold = threshold;
      lower = middle + 1;
    } else {
      upper = middle - 1;
    }
  }

  return visibleThreshold;
}

function navigationStatesMatch(
  left: MapUrlState,
  right: MapUrlState,
  coordinateTolerance = 0,
  zoomTolerance = 0,
): boolean {
  return left.datasetId === right.datasetId &&
    left.regionId === right.regionId &&
    left.placeId === right.placeId &&
    left.typeFilters.length === right.typeFilters.length &&
    left.typeFilters.every((value, index) => value === right.typeFilters[index]) &&
    left.statusFilters.length === right.statusFilters.length &&
    left.statusFilters.every((value, index) => value === right.statusFilters[index]) &&
    (left.view === right.view ||
      (left.view !== null &&
        right.view !== null &&
        Math.abs(left.view.center[0] - right.view.center[0]) <= coordinateTolerance &&
        Math.abs(left.view.center[1] - right.view.center[1]) <= coordinateTolerance &&
        Math.abs(left.view.zoom - right.view.zoom) <= zoomTolerance));
}

export function DatasetMap({
  dataset,
  datasetSnapshots,
  focusMapOnMount = false,
  navigationState,
  navigationRevision,
  onNavigationChange,
  onBack,
}: DatasetMapProps) {
  const { t } = useTranslation();
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadIsSlow, setLoadIsSlow] = useState(false);
  const loadInFlightRef = useRef(false);
  const [focusMapAfterRecovery, setFocusMapAfterRecovery] = useState(focusMapOnMount);
  const retryButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (loadState.status !== 'error' || loadState.retrying) {
      return undefined;
    }

    const animationFrame = window.requestAnimationFrame(() => {
      retryButtonRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [loadState]);

  useEffect(() => {
    const controller = new AbortController();
    loadInFlightRef.current = true;
    const slowTimer = window.setTimeout(() => setLoadIsSlow(true), 800);
    void loadDataset(dataset, controller.signal)
      .then((bundle) => {
        if (controller.signal.aborted) {
          return;
        }
        loadInFlightRef.current = false;
        window.clearTimeout(slowTimer);
        setLoadState({ status: 'ready', bundle });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          loadInFlightRef.current = false;
          window.clearTimeout(slowTimer);
          setLoadState(
            error instanceof DatasetAssetsMissingError
              ? { status: 'missing', message: error.message }
              : error instanceof DatasetAssetsInvalidError ||
                  error instanceof ContractValidationError ||
                  error instanceof SyntaxError
                ? { status: 'invalid', message: error.message }
              : { status: 'error', message: errorMessage(error), retrying: false },
          );
        }
      });
    return () => {
      controller.abort();
      window.clearTimeout(slowTimer);
      loadInFlightRef.current = false;
    };
  }, [dataset, loadAttempt]);

  const retryDataset = () => {
    if (loadInFlightRef.current || loadState.status !== 'error') {
      return;
    }
    loadInFlightRef.current = true;
    setLoadIsSlow(false);
    setFocusMapAfterRecovery(true);
    setLoadState({ ...loadState, retrying: true });
    setLoadAttempt((attempt) => attempt + 1);
  };

  if (loadState.status !== 'ready') {
    return (
      <main className="map-screen dataset-map-screen" aria-labelledby="map-title">
        <MapTitlebar dataset={dataset} onBack={onBack} />
        <section
          className="dataset-load-state"
          role={loadState.status === 'error' || loadState.status === 'invalid' ? 'alert' : 'status'}
          aria-busy={loadState.status === 'loading' ||
            (loadState.status === 'error' && loadState.retrying)}
        >
          {loadState.status === 'loading' ? (
            <>
              <span className="load-indicator" aria-hidden="true" />
              <p>{loadIsSlow ? t('map.loadingSlow') : t('map.loading')}</p>
            </>
          ) : loadState.status === 'missing' || loadState.status === 'invalid' ? (
            <>
              <span className="load-state-code">
                {loadState.status === 'missing' ? 'DATA MISSING' : 'DATA INVALID'}
              </span>
              <h2>
                {loadState.status === 'missing' ? t('map.missingData') : t('map.invalidData')}
              </h2>
              <p>{loadState.message}</p>
              <button type="button" onClick={onBack}>{t('map.versions')}</button>
            </>
          ) : (
            <>
              <span className="load-state-code">DATA ERROR</span>
              <h2>{t('map.loadError')}</h2>
              <p>{loadState.message}</p>
              {loadState.retrying && loadIsSlow ? <p>{t('map.retrySlow')}</p> : null}
              <button
                ref={retryButtonRef}
                type="button"
                disabled={loadState.retrying}
                onClick={retryDataset}
              >
                {loadState.retrying ? t('map.retrying') : t('map.retry')}
              </button>
            </>
          )}
        </section>
      </main>
    );
  }

  return (
    <DatasetMapReady
      dataset={dataset}
      datasetSnapshots={datasetSnapshots}
      bundle={loadState.bundle}
      focusMapOnMount={focusMapAfterRecovery}
      navigationState={navigationState}
      navigationRevision={navigationRevision}
      onNavigationChange={onNavigationChange}
      onBack={onBack}
    />
  );
}

export function MapTitlebar({ dataset, onBack, tools }: MapTitlebarProps) {
  const { t } = useTranslation();
  const presentation = presentDataset(dataset);
  return (
    <header className="window-titlebar map-titlebar">
      <button className="back-button" type="button" onClick={onBack}>
        <PixelIcon name="back" />
        {t('map.versions')}
      </button>
      <div className="map-title-copy">
        <h1 id="map-title">
          {presentation.modUrl ? (
            <a
              href={presentation.modUrl}
              target="_blank"
              rel="noopener noreferrer"
              title="View mod on Nexus Mods (opens in a new tab)"
            >
              {presentation.title}
            </a>
          ) : presentation.title}
        </h1>
      </div>
      {tools ? <div className="map-titlebar-tools">{tools}</div> : null}
    </header>
  );
}

interface DatasetMapReadyProps extends DatasetMapProps {
  readonly bundle: DatasetBundle;
  readonly focusMapOnMount: boolean;
}

function DatasetMapReady({
  dataset,
  datasetSnapshots,
  bundle,
  focusMapOnMount,
  navigationState,
  navigationRevision,
  onNavigationChange,
  onBack,
}: DatasetMapReadyProps) {
  const { t } = useTranslation();
  const locale: Locale = 'en';
  const [colorblind, setColorblind] = useState(readColorblindPreference);
  const colorblindRef = useRef(colorblind);
  const targetRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const mapRef = useRef<Map | null>(null);
  const failedTilesRef = useRef(new Set<Tile>());
  const pendingTilesRef = useRef(new Set<Tile>());
  const currentBasemapLoadWindowRef = useRef(new CurrentBasemapLoadWindow<Tile>());
  const basemapRetryInFlightRef = useRef(false);
  const basemapRetryButtonRef = useRef<HTMLButtonElement>(null);
  const markerLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const labelLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const focusedLabelLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const customMarkerLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const focusedCustomLabelLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const visiblePlaceIdsRef = useRef<ReadonlySet<string>>(new Set<string>());
  const labelPriorityContextRef = useRef<{
    selectedPlaceId: string | null;
    searchMatchIds: ReadonlySet<string>;
    progressByPlaceId: ReadonlyMap<string, ProgressRecord>;
  }>({
    selectedPlaceId: null,
    searchMatchIds: new Set<string>(),
    progressByPlaceId: new globalThis.Map<string, ProgressRecord>(),
  });
  const customMarkerEditorInputRef = useRef<HTMLInputElement>(null);
  const filterResetRef = useRef<HTMLButtonElement>(null);
  const resultSentinelRef = useRef<HTMLDivElement>(null);
  const userDataRetryButtonRef = useRef<HTMLButtonElement>(null);
  const placeCardRef = useRef<HTMLElement>(null);
  const placeCardFocus = useMemo(() => createFocusReturnController(), []);
  const customMarkerCardFocus = useMemo(() => createFocusReturnController(), []);
  const progressByPlaceIdRef = useRef<ReadonlyMap<string, ProgressRecord>>(
    new globalThis.Map<string, ProgressRecord>(),
  );
  const placingMarkerRef = useRef(false);
  const markerSaveInFlightRef = useRef(false);
  const userDataDisabledRef = useRef(true);
  const userDataRetryInFlightRef = useRef(false);
  const bindingInFlightRef = useRef(false);
  const progress = useDatasetProgress(dataset.datasetId);
  const customMarkers = useDatasetCustomMarkers(dataset.datasetId);
  const [bindingAttempt, setBindingAttempt] = useState(0);
  const [bindingState, setBindingState] = useState<UserDataBindingState>({ status: 'loading' });
  const [userDataRetrying, setUserDataRetrying] = useState(false);
  const [userDataRetryMessage, setUserDataRetryMessage] = useState<string | null>(null);
  const [markerSaving, setMarkerSaving] = useState(false);
  const [failedMarkerPosition, setFailedMarkerPosition] = useState<WorldCoordinate | null>(null);

  useEffect(() => {
    let active = true;
    bindingInFlightRef.current = true;
    void ensureDatasetSnapshot(
      userDatabase,
      dataset.datasetId,
      dataset.snapshotId,
    )
      .then(() => {
        if (!active) {
          return;
        }
        bindingInFlightRef.current = false;
        setBindingState({ status: 'ready' });
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        bindingInFlightRef.current = false;
        setBindingState(
          error instanceof DatasetSnapshotConflictError
            ? { status: 'conflict', message: error.message }
            : { status: 'error', message: errorMessage(error) },
        );
      });
    return () => {
      active = false;
      bindingInFlightRef.current = false;
    };
  }, [bindingAttempt, dataset.datasetId, dataset.snapshotId]);

  useEffect(() => {
    if (!focusMapOnMount) {
      return undefined;
    }
    const animationFrame = window.requestAnimationFrame(() => {
      targetRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [focusMapOnMount]);
  const projectionDescriptor = dataset.map.projection;
  const extent = useMemo<[number, number, number, number]>(() => {
    const [minX, minY, maxX, maxY] = projectionDescriptor.extent;
    return [minX, minY, maxX, maxY];
  }, [projectionDescriptor.extent]);
  const center = useMemo<[number, number]>(() => {
    const [x, y] = projectionDescriptor.center;
    return [x, y];
  }, [projectionDescriptor.center]);
  const availableRegionIds = useMemo(() => {
    const placeRegions = new Set(bundle.locations.places.map(({ regionId }) => regionId));
    return dataset.regions
      .filter(
        ({ id, kind, status }) =>
          kind === 'exterior' && status === 'available' && placeRegions.has(id) &&
          !(dataset.mapKey === 'tamriel-rebuilt' && id === 'solstheim'),
      )
      .map(({ id }) => id);
  }, [bundle.locations.places, dataset.mapKey, dataset.regions]);

  const places = useMemo(
    () =>
      buildPlaceViews(bundle.locations.places, [...bundle.locales.values()], locale).sort(
        (left, right) => left.name.localeCompare(right.name, locale),
      ),
    [bundle, locale],
  );
  const primaryPyramid = bundle.mapAssets.tilePyramids?.[0];
  const viewResolutions = useMemo(
    () => primaryPyramid ? createOverscaledViewResolutions(primaryPyramid) : undefined,
    [primaryPyramid],
  );
  const minimumZoom = primaryPyramid?.minZoom ?? 0;
  const maximumZoom = viewResolutions ? viewResolutions.length - 1 : 12;
  const availableTypes = useMemo(() => getAvailablePlaceTypes(places), [places]);
  const visibilityZoomThresholds = useMemo(
    () => [...new Set(places.map(({ place }) => place.minZoom))].sort((left, right) => left - right),
    [places],
  );
  const availablePlaceTypeSet = useMemo(
    () => new Set<PlaceType>(availableTypes),
    [availableTypes],
  );
  const placeRegions = useMemo(
    () => new globalThis.Map(places.map(({ id, place }) => [id, place.regionId])),
    [places],
  );
  const normalizedNavigationState = useMemo(
    () => {
      const normalized = normalizeMapUrlState(navigationState, {
        datasetId: dataset.datasetId,
        availableRegionIds: new Set(availableRegionIds),
        availablePlaceTypes: availablePlaceTypeSet,
        placeRegions,
        extent,
        minimumZoom,
        maximumZoom,
      });
      const requestedPlace = normalized.placeId === null
        ? null
        : places.find(({ id }) => id === normalized.placeId) ?? null;
      if (requestedPlace === null) {
        return normalized;
      }
      const matchesStaticFilters = isPlaceVisible(requestedPlace, {
        filters: {
          regionId: normalized.regionId,
          types: new Set(normalized.typeFilters),
          statuses: new Set(),
        },
        zoom: normalized.view?.zoom ?? Number.POSITIVE_INFINITY,
        progressByPlaceId: new globalThis.Map(),
      });
      return matchesStaticFilters ? normalized : { ...normalized, placeId: null };
    },
    [
      availableRegionIds,
      availablePlaceTypeSet,
      dataset.datasetId,
      extent,
      maximumZoom,
      minimumZoom,
      navigationState,
      placeRegions,
      places,
    ],
  );
  const initialNavigationRef = useRef(normalizedNavigationState);
  const navigationStateRef = useRef(normalizedNavigationState);
  const selfAuthoredNavigationRef = useRef<MapUrlState | null>(null);
  const handledNavigationRevisionRef = useRef(navigationRevision);
  const hasHandledInitialNavigationRef = useRef(false);
  const selectedIdRef = useRef<string | null>(normalizedNavigationState.placeId);
  const selectedMarkerIdRef = useRef<string | null>(null);
  const keyboardMarkerCursorRef = useRef(0);
  const hoveredPlaceIdRef = useRef<string | null>(null);
  const hoveredMarkerIdRef = useRef<string | null>(null);
  const zoomRef = useRef(normalizedNavigationState.view?.zoom ?? 0);
  const [query, setQuery] = useState('');
  const [region, setRegion] = useState<RegionFilter>(normalizedNavigationState.regionId);
  const [typeFilters, setTypeFilters] = useState<ReadonlySet<PlaceType>>(
    () => new Set(normalizedNavigationState.typeFilters),
  );
  const [statusFilters, setStatusFilters] = useState<ReadonlySet<ProgressStatus>>(
    () => new Set(normalizedNavigationState.statusFilters),
  );
  const [selectedId, setSelectedId] = useState<string | null>(
    normalizedNavigationState.placeId,
  );
  const [selectedMarkerId, setSelectedMarkerId] = useState<string | null>(null);
  const [placingMarker, setPlacingMarker] = useState(false);
  const [markerError, setMarkerError] = useState<string | null>(null);
  const [viewState, setViewState] = useState<(MapUrlView & { readonly rotation?: number }) | null>(normalizedNavigationState.view);
  const [zoom, setZoom] = useState(normalizedNavigationState.view?.zoom ?? 0);
  const [basemapState, setBasemapState] = useState<BasemapRuntimeState>({
    pending: 0,
    failures: 0,
    loaded: 0,
    missing: false,
    retrying: false,
  });
  const filterState = useMemo<PlaceFilterState>(
    () => ({ regionId: region, types: typeFilters, statuses: statusFilters }),
    [region, statusFilters, typeFilters],
  );
  const progressReadReady = !progress.loading && progress.error === null;
  const catalogFiltersReady = progressReadReady || statusFilters.size === 0;
  const userDataReadError = progress.error ?? customMarkers.error;
  const userDataLoading = bindingState.status === 'loading' ||
    progress.loading || customMarkers.loading;
  const userDataDisabled = bindingState.status !== 'ready' ||
    userDataReadError !== null || progress.loading || customMarkers.loading;
  const userDataRuntimeMessage = bindingState.status === 'error'
    ? bindingState.message
    : userDataReadError === null
      ? null
      : errorMessage(userDataReadError);
  const displayedUserDataRuntimeMessage = userDataRuntimeMessage ??
    (userDataRetrying ? userDataRetryMessage : null);
  const visibilityZoom = visibilityZoomFor(visibilityZoomThresholds, zoom);
  const visiblePlaces = useMemo(
    () => catalogFiltersReady
      ? places.filter((place) => isPlaceVisible(place, {
          filters: filterState,
          zoom: visibilityZoom,
          progressByPlaceId: progress.byPlaceId,
        }))
      : [],
    [catalogFiltersReady, filterState, places, progress.byPlaceId, visibilityZoom],
  );
  const visiblePlaceIds = useMemo(
    () => new Set(visiblePlaces.map(({ id }) => id)),
    [visiblePlaces],
  );
  const placeSearch = useMemo(() => new PlaceSearch(visiblePlaces), [visiblePlaces]);
  const allResults = useMemo(
    () => placeSearch.search(query, visiblePlaces.length),
    [placeSearch, query, visiblePlaces.length],
  );
  const [resultWindow, setResultWindow] = useState(() => ({
    source: allResults,
    count: RESULT_BATCH_SIZE,
  }));
  if (resultWindow.source !== allResults) {
    const sameResults = allResults.length === resultWindow.source.length &&
      allResults.every((place, index) => place.id === resultWindow.source[index]?.id);
    setResultWindow({
      source: allResults,
      count: sameResults ? resultWindow.count : RESULT_BATCH_SIZE,
    });
  }
  const renderedResultCount = typeof IntersectionObserver === 'undefined'
    ? allResults.length
    : resultWindow.source === allResults
      ? resultWindow.count
      : RESULT_BATCH_SIZE;
  const results = useMemo(
    () => allResults.slice(0, renderedResultCount),
    [allResults, renderedResultCount],
  );
  const hasMoreResults = results.length < allResults.length;

  useEffect(() => {
    if (!hasMoreResults) {
      return undefined;
    }
    const sentinel = resultSentinelRef.current;
    if (sentinel === null) {
      return undefined;
    }
    if (typeof IntersectionObserver === 'undefined') {
      return undefined;
    }
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some(({ isIntersecting }) => isIntersecting)) {
        return;
      }
      setResultWindow((current) => current.source === allResults
        ? {
            source: current.source,
            count: Math.min(allResults.length, current.count + RESULT_BATCH_SIZE),
          }
        : current
      );
    }, { rootMargin: '240px 0px' });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [allResults, hasMoreResults, renderedResultCount]);
  const searchMatchIds = useMemo(
    () => query.trim().length === 0
      ? new Set<string>()
      : new Set(allResults.map(({ id }) => id)),
    [allResults, query],
  );
  const labelPriorityOrder = useMemo(
    () => [...visiblePlaces]
      .sort((left, right) => comparePlaceLabelPriority(left, right, {
        selectedPlaceId: selectedId,
        searchMatchIds,
        progressByPlaceId: progress.byPlaceId,
      }))
      .slice(0, 20)
      .map(({ id }) => id),
    [progress.byPlaceId, searchMatchIds, selectedId, visiblePlaces],
  );
  const selectedPlace = useMemo(
    () => places.find(({ id }) => id === selectedId) ?? null,
    [places, selectedId],
  );
  const selectedMarker = selectedMarkerId === null
    ? null
    : (customMarkers.byId.get(selectedMarkerId) ?? null);
  const selectedMarkerFocusTargetId = selectedMarker?.id ?? null;
  const knownPlaceIds = useMemo(
    () => new Set(bundle.locations.places.map(({ id }) => id)),
    [bundle.locations.places],
  );
  const typeCounts = useMemo(() => {
    const counts = new globalThis.Map<PlaceType, number>(
      availableTypes.map((type) => [type, 0]),
    );
    if (!catalogFiltersReady) {
      return counts;
    }
    const filtersWithoutType: PlaceFilterState = {
      ...filterState,
      types: new Set<PlaceType>(),
    };
    places.forEach((place) => {
      if (!isPlaceVisible(place, {
        filters: filtersWithoutType,
        zoom: visibilityZoom,
        progressByPlaceId: progress.byPlaceId,
      })) {
        return;
      }
      counts.set(place.place.type, (counts.get(place.place.type) ?? 0) + 1);
    });
    return counts;
  }, [
    availableTypes,
    catalogFiltersReady,
    filterState,
    places,
    progress.byPlaceId,
    visibilityZoom,
  ]);
  const statusCounts = useMemo(() => {
    const counts = new globalThis.Map<ProgressStatus, number>(
      PROGRESS_STATUS_ORDER.map((status) => [status, 0]),
    );
    if (!catalogFiltersReady) {
      return counts;
    }
    const filtersWithoutStatus: PlaceFilterState = {
      ...filterState,
      statuses: new Set<ProgressStatus>(),
    };
    places.forEach((place) => {
      if (!isPlaceVisible(place, {
        filters: filtersWithoutStatus,
        zoom: visibilityZoom,
        progressByPlaceId: progress.byPlaceId,
      })) {
        return;
      }
      const status = progressStatusFor(place.id, progress.byPlaceId);
      counts.set(status, (counts.get(status) ?? 0) + 1);
    });
    return counts;
  }, [
    catalogFiltersReady,
    filterState,
    places,
    progress.byPlaceId,
    visibilityZoom,
  ]);
  const activeFilterAxisCount = Number(region !== 'all') +
    Number(typeFilters.size > 0) +
    Number(statusFilters.size > 0);
  const retryUserData = () => {
    if (
      userDataRetryInFlightRef.current ||
      bindingState.status === 'conflict' ||
      (bindingState.status !== 'error' && userDataReadError === null)
    ) {
      return;
    }
    userDataRetryInFlightRef.current = true;
    setUserDataRetryMessage(userDataRuntimeMessage);
    setUserDataRetrying(true);
    if (bindingState.status === 'error' && !bindingInFlightRef.current) {
      setBindingAttempt((attempt) => attempt + 1);
    }
    progress.retry();
    customMarkers.retry();
    userDatabase.close({ disableAutoOpen: false });
  };

  useEffect(() => {
    if (
      !userDataRetrying ||
      bindingInFlightRef.current ||
      bindingState.status === 'loading' ||
      progress.loading ||
      customMarkers.loading
    ) {
      return;
    }
    userDataRetryInFlightRef.current = false;
    setUserDataRetryMessage(null);
    setUserDataRetrying(false);
    const hasError = bindingState.status === 'error' ||
      progress.error !== null || customMarkers.error !== null;
    window.requestAnimationFrame(() => {
      if (hasError) {
        userDataRetryButtonRef.current?.focus({ preventScroll: true });
      } else {
        targetRef.current?.focus({ preventScroll: true });
      }
    });
  }, [
    bindingState,
    customMarkers.error,
    customMarkers.loading,
    progress.error,
    progress.loading,
    userDataRetrying,
  ]);

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      const target = event.target;
      if (event.key === 'Escape' && placingMarkerRef.current) {
        placingMarkerRef.current = false;
        setPlacingMarker(false);
        return;
      }
      if (
        event.key !== '/' ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        (target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
      ) {
        return;
      }
      event.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener('keydown', focusSearch);
    return () => window.removeEventListener('keydown', focusSearch);
  }, []);

  useEffect(() => {
    colorblindRef.current = colorblind;
    markerLayerRef.current?.changed();
    labelLayerRef.current?.changed();
    focusedLabelLayerRef.current?.changed();
    customMarkerLayerRef.current?.changed();
    focusedCustomLabelLayerRef.current?.changed();
  }, [colorblind]);

  useEffect(() => {
    selectedIdRef.current = selectedId;
    labelPriorityContextRef.current = {
      ...labelPriorityContextRef.current,
      selectedPlaceId: selectedId,
    };
    markerLayerRef.current?.changed();
    labelLayerRef.current?.changed();
    focusedLabelLayerRef.current?.changed();
  }, [selectedId]);

  useEffect(() => {
    selectedMarkerIdRef.current = selectedMarkerId;
    customMarkerLayerRef.current?.changed();
    focusedCustomLabelLayerRef.current?.changed();
    if (selectedMarkerFocusTargetId === null) {
      return undefined;
    }
    const animationFrame = window.requestAnimationFrame(() => {
      customMarkerEditorInputRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [selectedMarkerFocusTargetId, selectedMarkerId]);

  useEffect(() => {
    progressByPlaceIdRef.current = progress.byPlaceId;
    labelPriorityContextRef.current = {
      ...labelPriorityContextRef.current,
      progressByPlaceId: progress.byPlaceId,
    };
    markerLayerRef.current?.changed();
    labelLayerRef.current?.changed();
    focusedLabelLayerRef.current?.changed();
  }, [progress.byPlaceId]);

  useEffect(() => {
    if (!document.fonts) {
      return undefined;
    }
    let cancelled = false;
    void Promise.all([
      document.fonts.load('500 12px "Atkinson Hyperlegible Next Variable"'),
      document.fonts.load('600 12px "Atkinson Hyperlegible Next Variable"'),
    ]).then(() => {
      if (cancelled) {
        return;
      }
      PLACE_LABEL_STYLE_CACHE.clear();
      labelLayerRef.current?.changed();
      focusedLabelLayerRef.current?.changed();
      customMarkerLayerRef.current?.changed();
      focusedCustomLabelLayerRef.current?.changed();
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    visiblePlaceIdsRef.current = visiblePlaceIds;
    labelPriorityContextRef.current = {
      ...labelPriorityContextRef.current,
      searchMatchIds,
    };
    markerLayerRef.current?.changed();
    labelLayerRef.current?.changed();
    focusedLabelLayerRef.current?.changed();
  }, [searchMatchIds, visiblePlaceIds]);

  useEffect(() => {
    placingMarkerRef.current = placingMarker;
    targetRef.current?.classList.toggle('map-canvas--placing-marker', placingMarker);
  }, [placingMarker]);

  useEffect(() => {
    userDataDisabledRef.current = userDataDisabled;
  }, [userDataDisabled]);

  const commitNavigation = useCallback(
    (nextState: MapUrlState, mode: 'push' | 'replace') => {
      navigationStateRef.current = nextState;
      selfAuthoredNavigationRef.current = nextState;
      onNavigationChange(nextState, mode);
    },
    [onNavigationChange],
  );

  useEffect(() => {
    if (
      !catalogFiltersReady ||
      selectedPlace === null ||
      visiblePlaceIds.has(selectedPlace.id)
    ) {
      return;
    }
    const shouldReturnFilterFocus =
      placeCardRef.current?.contains(document.activeElement) ?? false;
    const hiddenPlaceId = selectedPlace.id;
    const timeoutId = window.setTimeout(() => {
      if (selectedIdRef.current !== hiddenPlaceId) {
        return;
      }
      selectedIdRef.current = null;
      setSelectedId(null);
      if (navigationStateRef.current.placeId !== null) {
        commitNavigation(
          { ...navigationStateRef.current, placeId: null },
          'replace',
        );
      }
      if (shouldReturnFilterFocus) {
        window.requestAnimationFrame(() => {
          const resetButton = filterResetRef.current;
          if (!resetButton || resetButton.disabled) {
            targetRef.current?.focus({ preventScroll: true });
            return;
          }
          const drawer = resetButton.closest('details');
          if (drawer instanceof HTMLDetailsElement) {
            drawer.open = true;
          }
          resetButton?.focus({ preventScroll: true });
        });
      }
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [catalogFiltersReady, commitNavigation, selectedPlace, visiblePlaceIds]);

  const createMarkerAt = useCallback(
    (position: readonly [number, number]) => {
      if (markerSaveInFlightRef.current || userDataDisabledRef.current) {
        return;
      }
      markerSaveInFlightRef.current = true;
      customMarkerCardFocus.remember(targetRef.current);
      placingMarkerRef.current = false;
      setPlacingMarker(false);
      setMarkerError(null);
      setMarkerSaving(true);
      setFailedMarkerPosition([position[0], position[1]]);
      void saveCustomMarker(userDatabase, {
        datasetId: dataset.datasetId,
        label: 'Personal marker',
        note: '',
        position,
        })
        .then((marker) => {
          setFailedMarkerPosition(null);
          setSelectedId(null);
          selectedMarkerIdRef.current = marker.id;
          setSelectedMarkerId(marker.id);
          if (navigationStateRef.current.placeId !== null) {
            commitNavigation(
              { ...navigationStateRef.current, placeId: null },
              'push',
            );
          }
        })
        .catch((error: unknown) => setMarkerError(errorMessage(error)))
        .finally(() => {
          markerSaveInFlightRef.current = false;
          setMarkerSaving(false);
        });
    },
    [
      dataset.datasetId,
      commitNavigation,
      customMarkerCardFocus,
      setMarkerError,
      setPlacingMarker,
      setSelectedId,
      setSelectedMarkerId,
    ],
  );

  useEffect(() => {
    if (!targetRef.current) {
      return undefined;
    }

    const failedTiles = failedTilesRef.current;
    const pendingTiles = pendingTilesRef.current;
    const currentBasemapLoadWindow = currentBasemapLoadWindowRef.current;
    const projection = configureTes3Projection(extent);
    const rasterLayers = bundle.mapAssets.rasters.map(
      (raster) =>
        new ImageLayer({
          source: new ImageStatic({
            url: raster.imageUrl,
            imageExtent: [...raster.extent],
            projection,
            interpolate: true,
          }),
        }),
    );
    const pyramidContexts = (bundle.mapAssets.tilePyramids ?? []).map((pyramid) => {
      const coverage = bundle.tileCoverages.get(pyramid.id);
      if (!coverage) {
        throw new Error(`Missing validated coverage for ${pyramid.id}`);
      }
      const tileGrid = createTes3TileGrid(pyramid);
      const coverageIndex = new SparseTileCoverageIndex(coverage);
      const runtimeAdjustment = requiresRuntimeBasemapAdjustment(pyramid);
      const source = new XYZ({
        projection,
        tileGrid,
        tileUrlFunction: createSparseTileUrlFunction(pyramid, coverage),
        ...(runtimeAdjustment ? { tileLoadFunction: loadOpaqueImageTile } : {}),
        wrapX: false,
        interpolate: true,
        transition: 0,
      });
      const layer = new TileLayer({
        className: runtimeAdjustment
          ? 'ol-layer dataset-basemap-layer dataset-basemap-layer--runtime-adjusted'
          : 'ol-layer dataset-basemap-layer',
        source,
        extent: [...pyramid.extent],
      });
      return { coverageIndex, layer, pyramid, source, tileGrid };
    });
    const tileSources = pyramidContexts.map(({ source }) => source);
    failedTiles.clear();
    pendingTiles.clear();
    currentBasemapLoadWindow.reset();
    basemapRetryInFlightRef.current = false;
    const publishBasemapState = () => {
      const pending = pendingTiles.size;
      const failures = failedTiles.size;
      const retrying = basemapRetryInFlightRef.current;
      setBasemapState((current) => ({
        pending,
        failures,
        loaded: currentBasemapLoadWindow.loadedCount,
        missing: current.missing,
        retrying,
      }));
      if (!retrying || pending > 0) {
        return;
      }
      basemapRetryInFlightRef.current = false;
      setBasemapState((current) => ({ ...current, retrying: false }));
      window.requestAnimationFrame(() => {
        if (failedTiles.size > 0) {
          basemapRetryButtonRef.current?.focus({ preventScroll: true });
        } else {
          targetRef.current?.focus({ preventScroll: true });
        }
      });
    };
    setBasemapState({ pending: 0, failures: 0, loaded: 0, missing: false, retrying: false });
    const tileEventKeys = tileSources.flatMap((source) => [
      source.on('tileloadstart', (event) => {
        currentBasemapLoadWindow.start(event.tile);
        pendingTiles.add(event.tile);
        publishBasemapState();
      }),
      source.on('tileloadend', (event) => {
        pendingTiles.delete(event.tile);
        failedTiles.delete(event.tile);
        currentBasemapLoadWindow.finish(event.tile);
        publishBasemapState();
      }),
      source.on('tileloaderror', (event) => {
        pendingTiles.delete(event.tile);
        failedTiles.add(event.tile);
        currentBasemapLoadWindow.fail(event.tile);
        publishBasemapState();
      }),
    ]);
    const orderedPlaces = [...places].sort((left, right) =>
      left.id < right.id ? -1 : left.id > right.id ? 1 : 0
    );
    const markerFeatures = orderedPlaces.map(
      ({ id, place }) =>
        new Feature({
          geometry: new Point([...place.mapPosition]),
          placeId: id,
        }),
    );
    const markerLayer = new VectorLayer({
      source: new VectorSource({ features: markerFeatures }),
      style: (feature) => {
        const placeId = feature.get('placeId') as string;
        if (!visiblePlaceIdsRef.current.has(placeId)) {
          return undefined;
        }
        const status = progressByPlaceIdRef.current.get(placeId)?.status ?? 'unvisited';
        if (placeId === selectedIdRef.current) {
          return createMarkerStyles(status, 'selected', colorblindRef.current);
        }
        return createMarkerStyles(
          status,
          placeId === hoveredPlaceIdRef.current ? 'hovered' : 'default',
          colorblindRef.current,
        );
      },
      updateWhileAnimating: true,
      updateWhileInteracting: true,
    });
    markerLayer.setZIndex(10);
    markerLayerRef.current = markerLayer;
    const labelFeatures = orderedPlaces.map(
      (place) =>
        new Feature({
          geometry: new Point([...place.place.mapPosition]),
          placeId: place.id,
          placeView: place,
        }),
    );
    const labelLayer = new VectorLayer({
      source: new VectorSource({ features: labelFeatures }),
      declutter: 'catalog-place-labels',
      renderBuffer: 180,
      renderOrder: (left, right) => comparePlaceLabelPriority(
        left.get('placeView') as PlaceView,
        right.get('placeView') as PlaceView,
        labelPriorityContextRef.current,
      ),
      style: (feature, resolution) => {
        const placeId = feature.get('placeId') as string;
        if (
          !visiblePlaceIdsRef.current.has(placeId) ||
          placeId === selectedIdRef.current ||
          placeId === hoveredPlaceIdRef.current
        ) {
          return undefined;
        }
        const place = feature.get('placeView') as PlaceView;
        return createPlaceLabelStyle(
          place.name,
          placeId === selectedIdRef.current,
          labelPriorityContextRef.current.searchMatchIds.has(placeId),
          progressByPlaceIdRef.current.get(placeId)?.status ?? 'unvisited',
          resolution <= view.getResolutionForZoom(8) * 1.001,
          false,
          colorblindRef.current,
        );
      },
      updateWhileAnimating: true,
      updateWhileInteracting: true,
    });
    labelLayer.setZIndex(11);
    labelLayerRef.current = labelLayer;
    const focusedLabelLayer = new VectorLayer({
      source: labelLayer.getSource()!,
      declutter: 'focused-place-labels',
      renderBuffer: 180,
      style: (feature) => {
        const placeId = feature.get('placeId') as string;
        const selected = placeId === selectedIdRef.current;
        const hovered = placeId === hoveredPlaceIdRef.current;
        if (!visiblePlaceIdsRef.current.has(placeId) || (!selected && !hovered)) {
          return undefined;
        }
        const place = feature.get('placeView') as PlaceView;
        return createPlaceLabelStyle(
          place.name,
          selected,
          false,
          progressByPlaceIdRef.current.get(placeId)?.status ?? 'unvisited',
          true,
          hovered,
          colorblindRef.current,
        );
      },
      updateWhileAnimating: true,
      updateWhileInteracting: true,
    });
    focusedLabelLayer.setZIndex(30);
    focusedLabelLayerRef.current = focusedLabelLayer;
    const customMarkerLayer = new VectorLayer({
      source: new VectorSource(),
      style: (feature, resolution) => {
        if (resolution > view.getResolutionForZoom(2)) {
          return undefined;
        }
        const markerId = feature.get('markerId') as string;
        const selected = markerId === selectedMarkerIdRef.current;
        const markerStyles = createMarkerStyles(
          'custom',
          selected ? 'selected' : markerId === hoveredMarkerIdRef.current ? 'hovered' : 'default',
          colorblindRef.current,
        );
        if (selected || markerId === hoveredMarkerIdRef.current) {
          return markerStyles;
        }
        return [
          ...markerStyles,
          createPlaceLabelStyle(
            Array.from(feature.get('label') as string).slice(0, MAX_MARKER_LABEL_LENGTH).join(''),
            selected,
            false,
            'custom',
            true,
            false,
            colorblindRef.current,
          ),
        ];
      },
      updateWhileAnimating: true,
      updateWhileInteracting: true,
    });
    customMarkerLayer.setZIndex(20);
    customMarkerLayerRef.current = customMarkerLayer;
    const focusedCustomLabelLayer = new VectorLayer({
      source: customMarkerLayer.getSource()!,
      renderBuffer: 180,
      style: (feature, resolution) => {
        if (resolution > view.getResolutionForZoom(2)) {
          return undefined;
        }
        const markerId = feature.get('markerId') as string;
        const selected = markerId === selectedMarkerIdRef.current;
        const hovered = markerId === hoveredMarkerIdRef.current;
        return selected || hovered ? createPlaceLabelStyle(
          Array.from(feature.get('label') as string).slice(0, MAX_MARKER_LABEL_LENGTH).join(''),
          selected,
          false,
          'custom',
          true,
          hovered,
          colorblindRef.current,
        ) : undefined;
      },
      updateWhileAnimating: true,
      updateWhileInteracting: true,
    });
    focusedCustomLabelLayer.setZIndex(29);
    focusedCustomLabelLayerRef.current = focusedCustomLabelLayer;
    const initialNavigation = initialNavigationRef.current;
    const initialPlace = initialNavigation.placeId === null
      ? null
      : places.find(({ id }) => id === initialNavigation.placeId) ?? null;
    const initialRegionView = initialNavigation.view === null && initialPlace === null
      ? regionNavigationView(
          dataset,
          initialNavigation.regionId,
          minimumZoom,
          maximumZoom,
        )
      : null;
    const initialView = initialNavigation.view ?? (
      initialPlace === null
        ? initialRegionView
        : {
            center: initialPlace.place.mapPosition,
            zoom: Math.min(
              maximumZoom,
              Math.max(minimumZoom, initialPlace.place.minZoom + 1, 5),
            ),
          }
    );
    const view = new View({
      projection,
      center: initialView ? [...initialView.center] : center,
      zoom: initialView?.zoom ?? 1,
      minZoom: minimumZoom,
      maxZoom: maximumZoom,
      constrainResolution: true,
      smoothResolutionConstraint: false,
      enableRotation: false,
      ...(viewResolutions ? { resolutions: viewResolutions } : {}),
      extent,
      showFullExtent: true,
      constrainOnlyCenter: true,
    });
    const map = new Map({
      target: targetRef.current,
      layers: [
        ...rasterLayers,
        ...pyramidContexts.map(({ layer }) => layer),
        markerLayer,
        labelLayer,
        customMarkerLayer,
        focusedLabelLayer,
        focusedCustomLabelLayer,
      ],
      view,
      controls: [],
      interactions: defaultInteractions({
        altShiftDragRotate: false,
        pinchRotate: false,
        onFocusOnly: false,
        zoomDuration: prefersReducedMotion() ? 0 : 250,
      }),
    });
    mapRef.current = map;
    if (initialView === null) {
      const initialExtent = initialNavigation.regionId === 'all'
        ? extent
        : regionExtent(
            bundle,
            initialNavigation.regionId,
            extent,
            projectionDescriptor.cellSize,
          ) ?? extent;
      view.fit([...initialExtent], {
        duration: 0,
        maxZoom: Math.min(4, view.getMaxZoom()),
        padding: [44, 44, 44, 44],
      });
    }
    zoomRef.current = view.getZoom() ?? 0;
    setZoom(zoomRef.current);
    markerLayer.changed();
    labelLayer.changed();

    const updateCoverageAtCenter = () => {
      const viewCenter = view.getCenter();
      const resolution = view.getResolution();
      if (!viewCenter || resolution === undefined || pyramidContexts.length === 0) {
        setBasemapState((current) => current.missing
          ? { ...current, missing: false }
          : current);
        return;
      }
      const covered = pyramidContexts.some(({ coverageIndex, pyramid, tileGrid }) => {
        const z = tileGrid.getZForResolution(resolution);
        if (z < pyramid.minZoom || z > pyramid.maxZoom) {
          return false;
        }
        return coverageIndex.has(tileGrid.getTileCoordForCoordAndZ(viewCenter, z));
      });
      const missing = !covered;
      setBasemapState((current) => current.missing === missing
        ? current
        : { ...current, missing });
    };
    updateCoverageAtCenter();

    const labelHitContext = document.createElement('canvas').getContext('2d');
    // Match text bounds rather than the padded background, so it cannot trap hover or clicks.
    const featureAtPixel = (pixel: number[]) => {
      const hitTolerance = (view.getZoom() ?? 0) >= view.getMaxZoom() - 0.01 ? 10 : 6;
      const labelAtPixel = (candidate: FeatureLike) => {
        if (!labelHitContext) {
          return undefined;
        }
        const markerId = candidate.get('markerId') as string | undefined;
        const place = candidate.get('placeView') as PlaceView | undefined;
        const name = markerId
          ? Array.from(candidate.get('label') as string).slice(0, MAX_MARKER_LABEL_LENGTH).join('')
          : place!.name;
        const text = createPlaceLabelStyle(
          name,
          markerId ? markerId === selectedMarkerIdRef.current : place!.id === selectedIdRef.current,
          markerId ? false : labelPriorityContextRef.current.searchMatchIds.has(place!.id),
          markerId ? 'custom' : progressByPlaceIdRef.current.get(place!.id)?.status ?? 'unvisited',
          true,
          markerId ? markerId === hoveredMarkerIdRef.current : place!.id === hoveredPlaceIdRef.current,
          colorblindRef.current,
        ).getText()!;
        labelHitContext.font = text.getFont()!;
        labelHitContext.textAlign = 'center';
        labelHitContext.textBaseline = 'middle';
        const metrics = labelHitContext.measureText(name);
        const anchor = map.getPixelFromCoordinate((candidate.getGeometry() as Point).getCoordinates());
        const x = pixel[0]! - anchor[0]! - text.getOffsetX();
        const y = pixel[1]! - anchor[1]! - text.getOffsetY();
        return x >= -metrics.actualBoundingBoxLeft && x <= metrics.actualBoundingBoxRight &&
          y >= -metrics.actualBoundingBoxAscent && y <= metrics.actualBoundingBoxDescent
          ? candidate : undefined;
      };
      return map.forEachFeatureAtPixel(pixel, labelAtPixel, {
        hitTolerance: 0,
        layerFilter: (layer) => layer === focusedLabelLayer || layer === focusedCustomLabelLayer,
      }) ?? map.forEachFeatureAtPixel(pixel, (candidate, layer) => {
        const styles = (layer as VectorLayer<VectorSource>).getStyleFunction()?.(candidate, view.getResolution()!);
        const image = (Array.isArray(styles) ? styles[0] : styles)?.getImage();
        const size = image?.getSize();
        const scale = image?.getScaleArray();
        if (!size || !scale) {
          return undefined;
        }
        const anchor = map.getPixelFromCoordinate((candidate.getGeometry() as Point).getCoordinates());
        const [width = 0, height = 0] = size;
        const [scaleX = 1, scaleY = 1] = scale;
        return Math.abs(pixel[0]! - anchor[0]!) <= width * scaleX / 2 &&
          Math.abs(pixel[1]! - anchor[1]!) <= height * scaleY / 2
          ? candidate : undefined;
      }, {
        hitTolerance,
        layerFilter: (layer) => layer === markerLayer || layer === customMarkerLayer,
      }) ?? map.forEachFeatureAtPixel(pixel, labelAtPixel, {
        hitTolerance: 0,
        layerFilter: (layer) => layer === labelLayer || layer === customMarkerLayer,
      });
    };
    const pointerMoveKey = map.on('pointermove', (event) => {
      if (event.dragging) {
        return;
      }
      const feature = featureAtPixel(event.pixel);
      const nextMarkerId = feature?.get('markerId') as string | undefined;
      const nextPlaceId = feature?.get('placeId') as string | undefined;
      const markerId = nextMarkerId ?? null;
      const placeId = nextPlaceId ?? null;
      if (hoveredMarkerIdRef.current !== markerId) {
        hoveredMarkerIdRef.current = markerId;
        customMarkerLayer.changed();
        focusedCustomLabelLayer.setZIndex(markerId === null ? 29 : 31);
        focusedCustomLabelLayer.changed();
      }
      if (hoveredPlaceIdRef.current !== placeId) {
        hoveredPlaceIdRef.current = placeId;
        markerLayer.changed();
        labelLayer.changed();
        focusedLabelLayer.changed();
      }
      map.getTargetElement().classList.toggle(
        'map-canvas--marker-hover',
        markerId !== null || placeId !== null,
      );
    });
    const clickKey = map.on('singleclick', (event) => {
      if (placingMarkerRef.current) {
        const [x = 0, y = 0] = event.coordinate;
        createMarkerAt([x, y]);
        return;
      }
      const feature = featureAtPixel(event.pixel);
      if (feature) {
        const markerId = feature.get('markerId') as string | undefined;
        if (markerId) {
          customMarkerCardFocus.remember(targetRef.current);
          setSelectedId(null);
          selectedMarkerIdRef.current = markerId;
          setSelectedMarkerId(markerId);
          if (navigationStateRef.current.placeId !== null) {
            commitNavigation(
              { ...navigationStateRef.current, placeId: null },
              'push',
            );
          }
        } else {
          const placeId = feature.get('placeId') as string;
          placeCardFocus.remember(targetRef.current);
          setSelectedMarkerId(null);
          setSelectedId(placeId);
          selectedIdRef.current = placeId;
          commitNavigation(
            { ...navigationStateRef.current, placeId },
            'push',
          );
        }
      }
    });
    let viewportMovementActive = false;
    const beginViewportMovement = () => {
      if (viewportMovementActive) {
        return;
      }
      viewportMovementActive = true;
      currentBasemapLoadWindow.beginViewport();
      publishBasemapState();
    };
    const centerKey = view.on('change:center', beginViewportMovement);
    const resolutionKey = view.on('change:resolution', () => {
      beginViewportMovement();
      const nextZoom = view.getZoom() ?? 0;
      zoomRef.current = nextZoom;
      setZoom((currentZoom) =>
        visibilityZoomFor(visibilityZoomThresholds, currentZoom) ===
          visibilityZoomFor(visibilityZoomThresholds, nextZoom)
          ? currentZoom
          : nextZoom
      );
    });
    const updateNavigationFromView = () => {
      const currentCenter = view.getCenter();
      const currentZoom = view.getZoom();
      if (!currentCenter || currentZoom === undefined) {
        return;
      }
      const [currentX = 0, currentY = 0] = currentCenter;
      const nextView: MapUrlView = {
        center: [currentX, currentY],
        zoom: currentZoom,
      };
      setViewState({ ...nextView, rotation: view.getRotation() });
      commitNavigation(
        {
          ...navigationStateRef.current,
          datasetId: dataset.datasetId,
          view: nextView,
        },
        'replace',
      );
    };
    let navigationSyncTimer: number | null = null;
    const scheduleNavigationFromView = () => {
      if (navigationSyncTimer !== null) {
        window.clearTimeout(navigationSyncTimer);
      }
      navigationSyncTimer = window.setTimeout(() => {
        navigationSyncTimer = null;
        updateNavigationFromView();
      }, 50);
    };
    const handleMoveEnd = () => {
      viewportMovementActive = false;
      setZoom(zoomRef.current);
      updateCoverageAtCenter();
      scheduleNavigationFromView();
    };
    const moveEndKey = map.on('moveend', handleMoveEnd);
    scheduleNavigationFromView();
    const viewport = map.getViewport();
    const clearCursor = () => {
      hoveredPlaceIdRef.current = null;
      hoveredMarkerIdRef.current = null;
      markerLayer.changed();
      labelLayer.changed();
      focusedLabelLayer.changed();
      customMarkerLayer.changed();
      map.getTargetElement().classList.remove('map-canvas--marker-hover');
      focusedCustomLabelLayer.setZIndex(29);
      focusedCustomLabelLayer.changed();
    };
    viewport.addEventListener('pointerleave', clearCursor);

    return () => {
      unByKey(pointerMoveKey);
      unByKey(clickKey);
      unByKey(centerKey);
      unByKey(resolutionKey);
      unByKey(moveEndKey);
      unByKey(tileEventKeys);
      if (navigationSyncTimer !== null) {
        window.clearTimeout(navigationSyncTimer);
      }
      viewport.removeEventListener('pointerleave', clearCursor);
      map.setTarget(undefined);
      mapRef.current = null;
      failedTiles.clear();
      pendingTiles.clear();
      currentBasemapLoadWindow.reset();
      basemapRetryInFlightRef.current = false;
      markerLayerRef.current = null;
      labelLayerRef.current = null;
      focusedLabelLayerRef.current = null;
      customMarkerLayerRef.current = null;
      focusedCustomLabelLayerRef.current = null;
    };
  }, [
    bundle,
    center,
    commitNavigation,
    createMarkerAt,
    customMarkerCardFocus,
    dataset,
    dataset.datasetId,
    extent,
    maximumZoom,
    minimumZoom,
    places,
    placeCardFocus,
    projectionDescriptor.cellSize,
    visibilityZoomThresholds,
    viewResolutions,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    if (!hasHandledInitialNavigationRef.current) {
      hasHandledInitialNavigationRef.current = true;
      return;
    }

    const isExternalPop = handledNavigationRevisionRef.current !== navigationRevision;
    handledNavigationRevisionRef.current = navigationRevision;
    const selfAuthored = selfAuthoredNavigationRef.current;
    const isSelfAuthored = !isExternalPop && selfAuthored !== null && navigationStatesMatch(
      selfAuthored,
      normalizedNavigationState,
      1,
      0.01,
    );
    selfAuthoredNavigationRef.current = null;
    navigationStateRef.current = normalizedNavigationState;
    selectedIdRef.current = normalizedNavigationState.placeId;
    setRegion(normalizedNavigationState.regionId);
    setTypeFilters((current) =>
      current.size === normalizedNavigationState.typeFilters.length &&
      normalizedNavigationState.typeFilters.every((type) => current.has(type))
        ? current : new Set(normalizedNavigationState.typeFilters));
    setStatusFilters((current) =>
      current.size === normalizedNavigationState.statusFilters.length &&
      normalizedNavigationState.statusFilters.every((status) => current.has(status))
        ? current : new Set(normalizedNavigationState.statusFilters));
    setSelectedId(normalizedNavigationState.placeId);

    if (
      isExternalPop ||
      !navigationStatesMatch(navigationState, normalizedNavigationState)
    ) {
      onNavigationChange(normalizedNavigationState, 'replace');
    }
    if (isSelfAuthored) {
      return;
    }

    setSelectedMarkerId(null);
    setPlacingMarker(false);
    const view = map.getView();
    view.cancelAnimations();
    if (normalizedNavigationState.view !== null) {
      const requestedView = normalizedNavigationState.view;
      const currentCenter = view.getCenter();
      const currentZoom = view.getZoom();
      const [currentX = 0, currentY = 0] = currentCenter ?? [];
      if (
        !currentCenter ||
        Math.abs(currentX - requestedView.center[0]) > 1 ||
        Math.abs(currentY - requestedView.center[1]) > 1
      ) {
        view.setCenter([...requestedView.center]);
      }
      if (currentZoom === undefined || Math.abs(currentZoom - requestedView.zoom) > 0.01) {
        view.setZoom(requestedView.zoom);
      }
      return;
    }

    const requestedPlace = normalizedNavigationState.placeId === null
      ? null
      : places.find(({ id }) => id === normalizedNavigationState.placeId) ?? null;
    if (requestedPlace) {
      view.setCenter([...requestedPlace.place.mapPosition]);
      view.setZoom(Math.min(
        view.getMaxZoom(),
        Math.max(view.getMinZoom(), requestedPlace.place.minZoom + 1, 5),
      ));
      return;
    }
    const requestedRegionView = regionNavigationView(
      dataset,
      normalizedNavigationState.regionId,
      minimumZoom,
      maximumZoom,
    );
    if (requestedRegionView !== null) {
      view.setCenter([...requestedRegionView.center]);
      view.setZoom(requestedRegionView.zoom);
      return;
    }
    const requestedExtent = normalizedNavigationState.regionId === 'all'
      ? extent
      : regionExtent(
          bundle,
          normalizedNavigationState.regionId,
          extent,
          projectionDescriptor.cellSize,
        ) ?? extent;
    view.fit([...requestedExtent], {
      duration: 0,
      maxZoom: Math.min(4, view.getMaxZoom()),
      padding: [48, 48, 48, 48],
    });
  }, [
    bundle,
    dataset,
    extent,
    maximumZoom,
    minimumZoom,
    navigationState,
    navigationRevision,
    normalizedNavigationState,
    onNavigationChange,
    places,
    projectionDescriptor.cellSize,
  ]);

  useEffect(() => {
    const source = customMarkerLayerRef.current?.getSource();
    if (!source) {
      return;
    }
    source.clear();
    source.addFeatures(
      customMarkers.records.map(
        (marker) =>
          new Feature({
            geometry: new Point([...marker.position]),
            markerId: marker.id,
            label: marker.label,
          }),
      ),
    );
    customMarkerLayerRef.current?.changed();
  }, [customMarkers.records]);

  const changeZoom = (delta: number) => {
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }
    const current = Math.round(view.getZoom() ?? 0);
    const next = Math.max(view.getMinZoom(), Math.min(view.getMaxZoom(), current + delta));
    if (prefersReducedMotion()) {
      view.setZoom(next);
    } else {
      view.animate({ zoom: next, duration: 120 });
    }
  };

  const fitExtent = (nextExtent: readonly [number, number, number, number]) => {
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }
    view.fit([...nextExtent], {
      duration: prefersReducedMotion() ? 0 : 180,
      maxZoom: Math.min(4, view.getMaxZoom()),
      padding: [48, 48, 48, 48],
    });
  };

  const moveToView = (nextView: MapUrlView) => {
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }
    view.cancelAnimations();
    if (prefersReducedMotion()) {
      view.setCenter([...nextView.center]);
      view.setZoom(nextView.zoom);
      return;
    }
    view.animate({
      center: [...nextView.center],
      zoom: nextView.zoom,
      duration: 180,
    });
  };

  const navigationWithCurrentView = (): MapUrlState => {
    const view = mapRef.current?.getView();
    const currentCenter = view?.getCenter();
    const currentZoom = view?.getZoom();
    const [currentX = 0, currentY = 0] = currentCenter ?? [];
    return {
      ...navigationStateRef.current,
      datasetId: dataset.datasetId,
      view: currentCenter && currentZoom !== undefined
        ? { center: [currentX, currentY], zoom: currentZoom }
        : navigationStateRef.current.view,
    };
  };

  const openNextCustomMarker = () => {
    if (customMarkers.records.length === 0) {
      return false;
    }
    const markerIndex = keyboardMarkerCursorRef.current % customMarkers.records.length;
    const marker = customMarkers.records[markerIndex];
    if (marker === undefined) {
      return false;
    }
    keyboardMarkerCursorRef.current = (markerIndex + 1) % customMarkers.records.length;
    customMarkerCardFocus.remember(targetRef.current);
    setPlacingMarker(false);
    setSelectedId(null);
    selectedIdRef.current = null;
    selectedMarkerIdRef.current = marker.id;
    setSelectedMarkerId(marker.id);
    if (navigationStateRef.current.placeId !== null) {
      commitNavigation(
        { ...navigationWithCurrentView(), placeId: null },
        'push',
      );
    }
    const view = mapRef.current?.getView();
    if (view) {
      if (prefersReducedMotion()) {
        view.setCenter([...marker.position]);
      } else {
        view.animate({ center: [...marker.position], duration: 180 });
      }
    }
    return true;
  };

  const selectRegion = (nextRegion: RegionFilter) => {
    const nextPlaceId = selectedPlace !== null &&
        nextRegion !== 'all' &&
        selectedPlace.place.regionId !== nextRegion
      ? null
      : selectedId;
    const nextRegionView = regionNavigationView(
      dataset,
      nextRegion,
      minimumZoom,
      maximumZoom,
    );
    selectedIdRef.current = nextPlaceId;
    setRegion(nextRegion);
    setSelectedId(nextPlaceId);
    commitNavigation(
      {
        ...navigationWithCurrentView(),
        regionId: nextRegion,
        placeId: nextPlaceId,
        ...(nextRegionView === null ? {} : { view: nextRegionView }),
      },
      'push',
    );
    if (nextRegionView !== null) {
      moveToView(nextRegionView);
      return;
    }
    const nextExtent = regionExtent(
      bundle,
      nextRegion,
      extent,
      projectionDescriptor.cellSize,
    );
    if (nextExtent) {
      fitExtent(nextExtent);
    }
  };

  const toggleTypeFilter = (type: PlaceType) => {
    const next = new Set(typeFilters);
    if (next.has(type)) {
      next.delete(type);
    } else {
      next.add(type);
    }
    const canonical = next.size === availableTypes.length
      ? new Set<PlaceType>()
      : next;
    setTypeFilters(canonical);
    commitNavigation(
      {
        ...navigationWithCurrentView(),
        typeFilters: PLACE_TYPE_ORDER.filter((candidate) => canonical.has(candidate)),
      },
      'push',
    );
  };

  const toggleStatusFilter = (status: ProgressStatus) => {
    const next = new Set(statusFilters);
    if (next.has(status)) {
      next.delete(status);
    } else {
      next.add(status);
    }
    const canonical = next.size === PROGRESS_STATUS_ORDER.length
      ? new Set<ProgressStatus>()
      : next;
    setStatusFilters(canonical);
    commitNavigation(
      {
        ...navigationWithCurrentView(),
        statusFilters: PROGRESS_STATUS_ORDER.filter((candidate) => canonical.has(candidate)),
      },
      'push',
    );
  };

  const clearTypeFilters = () => {
    if (typeFilters.size === 0) {
      return;
    }
    setTypeFilters(new Set());
    commitNavigation(
      { ...navigationWithCurrentView(), typeFilters: [] },
      'push',
    );
  };

  const clearStatusFilters = () => {
    if (statusFilters.size === 0) {
      return;
    }
    setStatusFilters(new Set());
    commitNavigation(
      { ...navigationWithCurrentView(), statusFilters: [] },
      'push',
    );
  };

  const resetFilters = () => {
    if (activeFilterAxisCount === 0) {
      return;
    }
    setRegion('all');
    setTypeFilters(new Set());
    setStatusFilters(new Set());
    commitNavigation(
      {
        ...navigationWithCurrentView(),
        regionId: 'all',
        typeFilters: [],
        statusFilters: [],
      },
      'push',
    );
    if (region !== 'all') {
      fitExtent(extent);
    }
  };

  const selectPlace = (
    place: PlaceView,
    origin: HTMLElement,
    focusCard: boolean,
  ) => {
    placeCardFocus.remember(origin);
    setPlacingMarker(false);
    setSelectedMarkerId(null);
    setSelectedId(place.id);
    selectedIdRef.current = place.id;
    commitNavigation(
      { ...navigationWithCurrentView(), placeId: place.id },
      'push',
    );
    const view = mapRef.current?.getView();
    if (!view) {
      return;
    }
    const nextZoom = Math.min(
      view.getMaxZoom(),
      Math.max(view.getZoom() ?? 0, place.place.minZoom + 1, 5),
    );
    if (prefersReducedMotion()) {
      view.setCenter([...place.place.mapPosition]);
      view.setZoom(nextZoom);
    } else {
      view.animate({ center: [...place.place.mapPosition], zoom: nextZoom, duration: 220 });
    }
    if (focusCard) {
      placeCardFocus.focus(() => placeCardRef.current);
    }
  };

  const toggleMarkerPlacement = () => {
    if (userDataDisabledRef.current || markerSaveInFlightRef.current) {
      return;
    }
    setMarkerError(null);
    setFailedMarkerPosition(null);
    setSelectedId(null);
    setSelectedMarkerId(null);
    selectedIdRef.current = null;
    if (navigationStateRef.current.placeId !== null) {
      commitNavigation(
        { ...navigationWithCurrentView(), placeId: null },
        'push',
      );
    }
    setPlacingMarker((current) => !current);
  };

  const closeSelectedPlace = () => {
    setSelectedId(null);
    selectedIdRef.current = null;
    commitNavigation(
      { ...navigationWithCurrentView(), placeId: null },
      'push',
    );
    placeCardFocus.restore(() => targetRef.current);
  };

  const closeSelectedCustomMarker = () => {
    selectedMarkerIdRef.current = null;
    setSelectedMarkerId(null);
    customMarkerCardFocus.restore(() => targetRef.current);
  };

  const finishCustomMarkerDeletion = () => {
    selectedMarkerIdRef.current = null;
    setSelectedMarkerId(null);
    customMarkerCardFocus.clear();
    window.requestAnimationFrame(() => {
      targetRef.current?.focus({ preventScroll: true });
    });
  };

  useEffect(() => {
    const closeCardOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || placingMarkerRef.current) {
        return;
      }
      if (selectedMarkerIdRef.current !== null) {
        closeSelectedCustomMarker();
      } else if (selectedIdRef.current !== null) {
        closeSelectedPlace();
      }
    };
    window.addEventListener('keydown', closeCardOnEscape);
    return () => window.removeEventListener('keydown', closeCardOnEscape);
  });

  const retryBasemap = () => {
    if (basemapRetryInFlightRef.current) {
      return;
    }
    const failedTiles = [...failedTilesRef.current];
    if (failedTiles.length === 0) {
      return;
    }
    basemapRetryInFlightRef.current = true;
    setBasemapState((current) => ({ ...current, retrying: true }));
    failedTiles.forEach((tile) => tile.load());
  };

  return (
    <MarkerAppearanceContext.Provider value={colorblind}>
    <main
      className="map-screen dataset-map-screen"
      aria-labelledby="map-title"
      style={Object.fromEntries(MARKER_KINDS.map((kind) =>
        [`--mim-${kind}`, markerColor(kind, colorblind)]
      ))}
    >
      <MapTitlebar
        dataset={dataset}
        onBack={onBack}
        tools={(
          <>
            <MapSettings
              colorblind={colorblind}
              onColorblindChange={(enabled) => {
                setColorblind(enabled);
                return saveColorblindPreference(enabled);
              }}
            />
            <DataTools
              datasetId={dataset.datasetId}
              datasetSnapshots={datasetSnapshots}
              knownPlaceIds={knownPlaceIds}
              locale={locale}
              mode={bindingState.status === 'conflict' ? 'conflict-export-only' : 'read-write'}
              disabled={bindingState.status !== 'conflict' && userDataDisabled}
              variant="compact"
            />
          </>
        )}
      />

      <section className="dataset-workspace">
        <aside className="map-ledger" aria-label={t('map.searchLabel')}>
          {bindingState.status === 'conflict' ? (
            <div className="user-data-state user-data-state--error" role="alert">
              <strong>{t('map.localDataConflict')}</strong>
              <p>{bindingState.message}</p>
              <p>{t('map.localDataPreserved')}</p>
              <button type="button" onClick={onBack}>{t('map.versions')}</button>
            </div>
          ) : displayedUserDataRuntimeMessage !== null ? (
            <div
              className="user-data-state user-data-state--error"
              role="alert"
              aria-busy={userDataRetrying}
            >
              <strong>{t('map.localDataError')}</strong>
              <p>{displayedUserDataRuntimeMessage}</p>
              <p>{t('map.localDataReadOnly')}</p>
              <button
                ref={userDataRetryButtonRef}
                type="button"
                disabled={userDataRetrying}
                onClick={retryUserData}
              >
                {userDataRetrying ? t('map.retrying') : t('map.retry')}
              </button>
            </div>
          ) : userDataLoading ? (
            <p className="user-data-state" role="status" aria-busy="true">
              {t('map.localDataLoading')}
            </p>
          ) : null}

          <label className="place-search">
            <span>{t('map.searchLabel')}</span>
            <span className="search-field">
              <input
                ref={searchRef}
                type="search"
                value={query}
                placeholder={t('map.searchPlaceholder')}
                onChange={(event) => setQuery(event.currentTarget.value)}
              />
              <kbd aria-hidden="true">/</kbd>
            </span>
          </label>

          {availableRegionIds.length > 1 ? (
            <fieldset className="region-filter">
              <legend>{t('map.regions')}</legend>
              {(['all', ...availableRegionIds] as const).map((regionId) => (
                <button
                  key={regionId}
                  type="button"
                  aria-pressed={region === regionId}
                  onClick={() => selectRegion(regionId)}
                >
                  {regionId === 'all'
                    ? t('map.allRegions')
                    : regionTitle(dataset, regionId)}
                </button>
              ))}
            </fieldset>
          ) : null}

          <PlaceFilterControls
            availableTypes={availableTypes}
            selectedTypes={typeFilters}
            selectedStatuses={statusFilters}
            typeCounts={typeCounts}
            statusCounts={statusCounts}
            activeAxisCount={activeFilterAxisCount}
            statusesDisabled={!progressReadReady}
            onToggleType={toggleTypeFilter}
            onToggleStatus={toggleStatusFilter}
            onClearTypes={clearTypeFilters}
            onClearStatuses={clearStatusFilters}
            onReset={resetFilters}
            resetFocusRef={filterResetRef}
          />

          <div className="place-results">
            {results.length ? (
              results.map((place) => {
                const status = progress.byPlaceId.get(place.id)?.status ?? 'unvisited';
                return (
                  <button
                    key={place.id}
                    type="button"
                    className={selectedId === place.id ? 'place-result place-result--selected' : 'place-result'}
                    style={{ '--place-status-color': markerColor(status, colorblind) } as CSSProperties}
                    aria-current={selectedId === place.id ? 'location' : undefined}
                    onClick={(event) => selectPlace(
                      place,
                      event.currentTarget,
                      isKeyboardActivation(event.detail),
                    )}
                  >
                    <StatusMark kind={status} className="result-marker" />
                    <span>
                      <strong>{place.name}</strong>
                      <small>
                        {t(`placeType.${place.place.type}`)} ·{' '}
                        {regionTitle(dataset, place.place.regionId)}
                      </small>
                    </span>
                  </button>
                );
              })
            ) : places.length === 0 ? (
              <div className="empty-state">
                <p>{t('map.noExteriorContent')}</p>
                <button type="button" onClick={onBack}>{t('map.versions')}</button>
              </div>
            ) : !catalogFiltersReady ? (
              <p className="no-results" role="status">{t('map.progressFilterUnavailable')}</p>
            ) : visiblePlaces.length === 0 && activeFilterAxisCount > 0 ? (
              <div className="empty-state">
                <p>{t('map.noFilteredPlaces')}</p>
                <button
                  type="button"
                  onClick={() => {
                    resetFilters();
                    window.requestAnimationFrame(() => searchRef.current?.focus());
                  }}
                >
                  {t('map.resetFilters')}
                </button>
              </div>
            ) : query.trim().length > 0 ? (
              <div className="empty-state">
                <p>{t('map.noResults')}</p>
                <button
                  type="button"
                  onClick={() => {
                    setQuery('');
                    window.requestAnimationFrame(() => searchRef.current?.focus());
                  }}
                >
                  {t('map.clearSearch')}
                </button>
              </div>
            ) : (
              <p className="no-results">{t('map.noPlacesAtZoom')}</p>
            )}
            {hasMoreResults ? (
              <div
                ref={resultSentinelRef}
                className="place-results__sentinel"
                data-rendered-result-count={results.length}
                aria-hidden="true"
              />
            ) : null}
          </div>
        </aside>

        <div className="dataset-map-stage">
          <div
            ref={targetRef}
            className="map-canvas"
            style={BASEMAP_PRESENTATION_STYLE}
            tabIndex={0}
            data-view-x={viewState?.center[0]}
            data-view-y={viewState?.center[1]}
            data-view-z={viewState?.zoom}
            data-view-rotation={viewState?.rotation ?? 0}
            data-basemap-pending={basemapState.pending}
            data-basemap-loaded={basemapState.loaded}
            data-custom-marker-count={customMarkers.records.length}
            data-visible-place-count={visiblePlaces.length}
            data-label-candidate-count={visiblePlaces.length}
            data-label-priority={labelPriorityOrder.join(',')}
            aria-busy={!catalogFiltersReady}
            role="application"
            aria-label={t('map.mapAria')}
            aria-describedby={placingMarker
              ? 'map-keyboard-instructions marker-placement-hint'
              : 'map-keyboard-instructions'}
            onKeyDown={(event) => {
              if (
                !placingMarker &&
                event.key.toLowerCase() === 'm' &&
                !event.metaKey &&
                !event.ctrlKey &&
                !event.altKey
              ) {
                if (openNextCustomMarker()) {
                  event.preventDefault();
                }
                return;
              }
              if (!placingMarker || (event.key !== 'Enter' && event.key !== ' ')) {
                return;
              }
              const [x = 0, y = 0] = mapRef.current?.getView().getCenter() ?? center;
              event.preventDefault();
              createMarkerAt([x, y]);
            }}
          />

          <p id="map-keyboard-instructions" className="visually-hidden">
            Use arrow keys to pan the map and plus or minus to zoom. Press M to open the next personal marker.
          </p>

          <div className="map-tools" role="group" aria-label={t('map.controls')}>
            <button type="button" onClick={() => changeZoom(1)} aria-label={t('map.zoomIn')}>
              <span className="map-tool-symbol" aria-hidden="true">+</span>
            </button>
            <button type="button" onClick={() => changeZoom(-1)} aria-label={t('map.zoomOut')}>
              <span className="map-tool-symbol" aria-hidden="true">−</span>
            </button>
            <button
              type="button"
              className="add-marker-tool"
              disabled={userDataDisabled || markerSaving}
              aria-label={placingMarker ? t('map.cancelMarker') : t('map.addMarker')}
              aria-pressed={placingMarker}
              onClick={toggleMarkerPlacement}
            >
              <StatusMark kind="custom" />
            </button>
          </div>

          <div className="marker-legend" role="group" aria-label="Marker legend">
            <span><StatusMark kind="unvisited" />{t('map.unvisited')}</span>
            <span><StatusMark kind="active" />{t('map.active')}</span>
            <span><StatusMark kind="visited" />{t('map.visited')}</span>
            <span><StatusMark kind="custom" />{t('map.personalMarker')}</span>
          </div>

          {basemapState.failures > 0 ? (
            <div
              className={`basemap-state basemap-state--error basemap-state--${basemapState.loaded > 0 ? 'partial' : 'full'}`}
              role="alert"
              aria-busy={basemapState.retrying}
            >
              <span>
                {t(
                  basemapState.loaded > 0 ? 'map.basemapPartialError' : 'map.basemapFullError',
                  { count: basemapState.failures },
                )}
              </span>
              <button
                ref={basemapRetryButtonRef}
                type="button"
                disabled={basemapState.retrying}
                onClick={retryBasemap}
              >
                {basemapState.retrying ? t('map.retrying') : t('map.retryFailedTiles')}
              </button>
            </div>
          ) : basemapState.missing ? (
            <p className="basemap-state basemap-state--missing" role="status">
              {t('map.basemapMissing')}
            </p>
          ) : null}

          {placingMarker ? (
            <p id="marker-placement-hint" className="marker-placement-hint" role="status">
              {t('map.placeMarkerHint')}
            </p>
          ) : null}
          {markerError ? (
            <div className="marker-placement-error" role="alert" aria-busy={markerSaving}>
              <span>{markerError}</span>
              {failedMarkerPosition ? (
                <button
                  type="button"
                  disabled={markerSaving || userDataDisabled}
                  onClick={() => createMarkerAt(failedMarkerPosition)}
                >
                  {markerSaving ? t('map.retrying') : t('map.retryMarker')}
                </button>
              ) : null}
            </div>
          ) : null}

          {catalogFiltersReady && selectedPlace ? (
            <PlaceCard
              cardRef={placeCardRef}
              datasetId={dataset.datasetId}
              wikiUrl={placeWikiUrl(dataset.mapKey, selectedPlace.place.regionId, selectedPlace.name, selectedPlace.id)}
              place={selectedPlace}
              locale={locale}
              progress={progress.byPlaceId.get(selectedPlace.id)}
              disabled={userDataDisabled}
              onClose={closeSelectedPlace}
              onCopyLink={() => navigator.clipboard.writeText(writeMapUrl(
                new URL(window.location.pathname, window.location.origin),
                {
                  datasetId: dataset.datasetId,
                  regionId: 'all',
                  placeId: selectedPlace.id,
                  view: {
                    center: selectedPlace.place.mapPosition,
                    zoom: mapRef.current?.getView().getZoom() ?? zoomRef.current,
                  },
                  typeFilters: [],
                  statusFilters: [],
                },
              ).href)}
            />
          ) : null}
          {selectedMarker ? (
            <CustomMarkerCard
              marker={selectedMarker}
              locale={locale}
              inputRef={customMarkerEditorInputRef}
              disabled={userDataDisabled}
              onClose={closeSelectedCustomMarker}
              onDeleted={finishCustomMarkerDeletion}
            />
          ) : null}
        </div>
      </section>
    </main>
    </MarkerAppearanceContext.Provider>
  );
}

interface PlaceCardProps {
  readonly cardRef: Ref<HTMLElement>;
  readonly datasetId: string;
  readonly wikiUrl: string | null;
  readonly place: PlaceView;
  readonly locale: Locale;
  readonly progress: ProgressRecord | undefined;
  readonly disabled: boolean;
  readonly onClose: () => void;
  readonly onCopyLink: () => Promise<void>;
}

function PlaceCard({
  cardRef,
  datasetId,
  wikiUrl,
  place,
  locale,
  progress,
  disabled,
  onClose,
  onCopyLink,
}: PlaceCardProps) {
  const { t } = useTranslation();
  const [copyFeedback, setCopyFeedback] = useState<{
    readonly sequence: number;
    readonly placeId: string;
    readonly failed: boolean;
  } | null>(null);
  const copySequenceRef = useRef(0);
  const currentCopyFeedback = copyFeedback?.placeId === place.id ? copyFeedback : null;
  useEffect(() => {
    if (currentCopyFeedback === null) {
      return;
    }
    const timeout = window.setTimeout(() => {
      setCopyFeedback((current) => current === currentCopyFeedback ? null : current);
    }, 5000);
    return () => window.clearTimeout(timeout);
  }, [currentCopyFeedback]);
  const copyLink = async () => {
    const sequence = ++copySequenceRef.current;
    setCopyFeedback(null);
    try {
      await onCopyLink();
      if (sequence === copySequenceRef.current) {
        setCopyFeedback({ sequence, placeId: place.id, failed: false });
      }
    } catch {
      if (sequence === copySequenceRef.current) {
        setCopyFeedback({ sequence, placeId: place.id, failed: true });
      }
    }
  };
  return (
    <article
      ref={cardRef}
      className="place-card"
      tabIndex={-1}
      aria-labelledby="selected-place-title"
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <button className="place-card-close" type="button" onClick={onClose} aria-label={t('map.closeCard')}>
        <PixelIcon name="close" />
      </button>
      <div className="place-card-title">
        <h2 id="selected-place-title">
          {wikiUrl ? (
            <a href={wikiUrl} target="_blank" rel="noopener noreferrer">{place.name}</a>
          ) : place.name}
        </h2>
        <button
          className="place-card-copy-link"
          type="button"
          onClick={() => void copyLink()}
          aria-label={t('map.copyPlaceLink')}
          title={t('map.copyPlaceLink')}
        >
          <PixelIcon name="link" />
        </button>
      </div>
      {currentCopyFeedback ? (
        <p
          key={currentCopyFeedback.sequence}
          className={`place-share-feedback${currentCopyFeedback.failed ? ' place-share-feedback--error' : ''}`}
          role={currentCopyFeedback.failed ? 'alert' : 'status'}
        >
          {t(currentCopyFeedback.failed ? 'map.placeLinkCopyFailed' : 'map.placeLinkCopied')}
        </p>
      ) : null}
      <PlaceProgressEditor
        key={`${datasetId}\0${place.id}`}
        datasetId={datasetId}
        placeId={place.id}
        locale={locale}
        disabled={disabled}
        {...(progress ? { progress } : {})}
      />
    </article>
  );
}

interface CustomMarkerCardProps {
  readonly marker: CustomMarkerRecord;
  readonly locale: Locale;
  readonly inputRef: Ref<HTMLInputElement>;
  readonly disabled: boolean;
  readonly onClose: () => void;
  readonly onDeleted: () => void;
}

function CustomMarkerCard({
  marker,
  locale,
  inputRef,
  disabled,
  onClose,
  onDeleted,
}: CustomMarkerCardProps) {
  const { t } = useTranslation();
  return (
    <article
      className="place-card custom-marker-card"
      aria-labelledby="selected-marker-title"
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <button
        className="place-card-close"
        type="button"
        onClick={onClose}
        aria-label={t('map.closeMarker')}
      >
        <PixelIcon name="close" />
      </button>
      <span className="place-card-index">{t('map.personalMarker')}</span>
      <h2 id="selected-marker-title">{marker.label}</h2>
      <CustomMarkerEditor
        key={marker.id}
        marker={marker}
        locale={locale}
        inputRef={inputRef}
        disabled={disabled}
        onDeleted={onDeleted}
      />
    </article>
  );
}
