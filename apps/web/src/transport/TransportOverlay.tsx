import { useCallback, useEffect, useMemo, useState } from 'react';
import type { DatasetManifest } from '@morrowind-map/contracts';
import type Map from 'ol/Map.js';
import { unByKey } from 'ol/Observable.js';
import { writeMapUrl, type MapUrlState } from '../navigation/mapUrlState';
import { LOCAL_STORAGE_PREFIX } from '../storage/userDataNamespace';
import type { PlaceView } from '../data/placeSearch';
import { transportWikiUrl } from './transportWiki';
import { TransportControls } from './TransportControls';
import { loadTransport } from './loadTransport';
import { createTransportLayers, transportStopAtPixel, visibleTransportRoutes } from './transportLayer';
import { TRANSPORT_MODE_ORDER, transportModes, type TransportCatalog, type TransportMode } from './types';

interface Props {
  readonly dataset: DatasetManifest;
  readonly places: readonly PlaceView[];
  readonly map: Map | null;
  readonly navigation: MapUrlState;
  readonly placingMarker: boolean;
  readonly onChange: (patch: Pick<MapUrlState, 'transportModes' | 'transportStopId'>, mode?: 'push' | 'replace') => void;
  readonly onSelect: () => void;
}

interface Preference { modes: readonly TransportMode[] }
const NO_MODES: readonly TransportMode[] = [];

function preference(mapKey: string): Preference {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(`${LOCAL_STORAGE_PREFIX}:transport:${mapKey}`) ?? 'null');
    if (raw && typeof raw === 'object' && 'modes' in raw && Array.isArray(raw.modes)) {
      const modes = transportModes(raw.modes.filter((m): m is string => typeof m === 'string'));
      if (modes.length) return { modes };
    }
  } catch { /* Storage can be unavailable without preventing map use. */ }
  return { modes: TRANSPORT_MODE_ORDER };
}

export function TransportOverlay({ dataset, places, map, navigation, placingMarker, onChange, onSelect }: Props) {
  const [saved, setSaved] = useState(() => preference(dataset.mapKey));
  const [emptySelection, setEmptySelection] = useState(false);
  const enabled = (navigation.transportModes?.length ?? 0) > 0;
  const modes = enabled ? navigation.transportModes! : emptySelection ? NO_MODES : saved.modes;
  const [expanded, setExpanded] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<{ catalog: TransportCatalog | null; status: 'idle' | 'loading' | 'ready' | 'error' }>({ catalog: null, status: 'idle' });

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    void loadTransport(dataset).then((catalog) => {
      if (active) setLoaded({ catalog, status: 'ready' });
    }).catch(() => {
      if (active) setLoaded({ catalog: null, status: 'error' });
    });
    return () => { active = false; };
  }, [dataset, enabled, attempt]);

  const catalog = loaded.catalog;
  const display = useMemo(() => catalog ? {
    catalog, modes: enabled ? modes : [],
    selectedStopId: navigation.transportStopId ?? null,
    regionId: navigation.regionId,
  } : null, [catalog, enabled, modes, navigation.transportStopId, navigation.regionId]);
  const visibleCatalog = useMemo(() => {
    if (!display) return null;
    const routes = visibleTransportRoutes(display);
    const ids = new Set(routes.flatMap((route) => [route.from, route.to]));
    return { ...display.catalog, routes, stops: display.catalog.stops.filter((stop) => ids.has(stop.id)) };
  }, [display]);
  const selectedStopId = enabled && visibleCatalog?.stops.some((stop) => stop.id === navigation.transportStopId)
    ? navigation.transportStopId ?? null : null;
  const selectedStop = catalog?.stops.find((stop) => stop.id === selectedStopId);

  useEffect(() => {
    if (enabled && catalog && navigation.transportStopId && selectedStopId === null) {
      onChange({ transportModes: modes, transportStopId: null }, 'replace');
    }
  }, [enabled, catalog, navigation.transportStopId, selectedStopId, modes, onChange]);

  useEffect(() => {
    if (!map || !enabled || !display) return;
    const layers = createTransportLayers(map);
    layers.update({ ...display, selectedStopId });
    return () => layers.dispose();
  }, [map, enabled, display, selectedStopId]);

  const selectStop = useCallback((id: string | null) => {
    setExpanded(false);
    if (id !== null) onSelect();
    onChange({ transportModes: modes, transportStopId: id });
  }, [modes, onChange, onSelect]);

  useEffect(() => {
    if (!map || !enabled || placingMarker) return;
    const key = map.on('singleclick', (event) => {
      const id = transportStopAtPixel(map, event.pixel);
      if (id) selectStop(id);
    });
    return () => unByKey(key);
  }, [map, enabled, placingMarker, selectStop]);

  function remember(next: Preference) {
    setSaved(next);
    try { localStorage.setItem(`${LOCAL_STORAGE_PREFIX}:transport:${dataset.mapKey}`, JSON.stringify(next)); } catch { /* Optional preference. */ }
  }

  return <TransportControls
    enabled={enabled}
    modes={modes}
    expanded={expanded}
    onExpandedChange={setExpanded}
    onToggle={() => {
      setEmptySelection(false);
      if (enabled) remember({ modes });
      onChange({ transportModes: enabled ? [] : saved.modes, transportStopId: null });
    }}
    onModesChange={(next) => {
      setEmptySelection(next.length === 0);
      if (next.length) remember({ modes: next });
      else remember({ modes });
      if (enabled) onChange({ transportModes: next, transportStopId: null });
    }}
    status={enabled && loaded.status === 'idle' ? 'loading' : loaded.status}
    onRetry={() => { setLoaded({ catalog: null, status: 'loading' }); setAttempt((value) => value + 1); }}
    catalog={visibleCatalog}
    selectedStopId={selectedStopId}
    wikiUrl={selectedStop ? transportWikiUrl(dataset.mapKey, selectedStop, places) : null}
    onCopyLink={async () => {
      if (!selectedStop) return;
      await navigator.clipboard.writeText(writeMapUrl(new URL(window.location.pathname, window.location.origin), {
        ...navigation,
        regionId: 'all', placeId: null, typeFilters: [], statusFilters: [],
        transportModes: modes, transportStopId: selectedStop.id,
        view: {
          center: selectedStop.position,
          zoom: Math.min(map?.getView().getMaxZoom() ?? 5, Math.max(5, map?.getView().getZoom() ?? 5)),
        },
      }).href);
    }}
    onStopSelect={selectStop}
    onDestinationSelect={(id) => {
      const stop = catalog?.stops.find((candidate) => candidate.id === id);
      if (!stop || stop.external || !map) return;
      selectStop(id);
      const view = map.getView();
      view.setCenter([...stop.position]);
      view.setZoom(Math.min(view.getMaxZoom(), Math.max(5, view.getZoom() ?? 0)));
    }}
  />;
}
