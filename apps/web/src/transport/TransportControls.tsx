import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { PixelIcon } from '../ui/PixelIcon';
import { TRANSPORT_MODES, type TransportCatalog, type TransportMode } from './types';
import './transport.css';

export interface TransportControlsProps {
  readonly enabled: boolean;
  readonly modes: readonly TransportMode[];
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly onExpandedChange: (value: boolean) => void;
  readonly onModesChange: (modes: TransportMode[]) => void;
  readonly status: 'idle' | 'loading' | 'ready' | 'error';
  readonly onRetry: () => void;
  readonly catalog: TransportCatalog | null;
  readonly selectedStopId: string | null;
  readonly wikiUrl: string | null;
  readonly onCopyLink: () => Promise<void>;
  readonly onStopSelect: (id: string | null) => void;
  readonly onDestinationSelect: (id: string) => void;
}

const MODE_ORDER: readonly TransportMode[] = ['land', 'water', 'guild'];
const MODE_DESCRIPTIONS: Record<TransportMode, string> = {
  land: 'Silt striders, carriages and other land services',
  water: 'Ships, gondolas and waterstriders',
  guild: 'Mages Guild teleportation',
};

function ModeSample({ mode }: { readonly mode: TransportMode }) {
  const definition = TRANSPORT_MODES[mode];
  return (
    <svg className="transport-mode-sample" viewBox="0 0 48 20" aria-hidden="true" focusable="false">
      <path d="M2 10H46" stroke={definition.color} strokeWidth="1.25" strokeDasharray={definition.dash.join(' ')} />
      {definition.shape === 'circle' ? (
        <circle cx="24" cy="10" r="5" fill={definition.color} stroke="#111b23" strokeWidth="2" />
      ) : definition.shape === 'square' ? (
        <rect x="19" y="5" width="10" height="10" fill={definition.color} stroke="#111b23" strokeWidth="2" />
      ) : (
        <path d="M24 4L30 15H18Z" fill={definition.color} stroke="#111b23" strokeWidth="2" />
      )}
    </svg>
  );
}

export function TransportControls({
  enabled, modes, expanded, onToggle, onExpandedChange,
  onModesChange, status, onRetry, catalog, selectedStopId,
  onStopSelect, onDestinationSelect, wikiUrl, onCopyLink,
}: TransportControlsProps) {
  const id = useId();
  const controlsRef = useRef<HTMLDivElement>(null);
  const optionsButtonRef = useRef<HTMLButtonElement>(null);
  const firstOptionRef = useRef<HTMLInputElement>(null);
  const cardTitleRef = useRef<HTMLHeadingElement>(null);
  const focusedStopRef = useRef<string | null>(null);
  const copySequence = useRef(0);
  const [copyFeedback, setCopyFeedback] = useState<{ stopId: string | null; sequence: number; failed: boolean } | null>(null);
  const currentCopyFeedback = copyFeedback?.stopId === selectedStopId ? copyFeedback : null;
  useEffect(() => {
    if (!currentCopyFeedback) return;
    const timer = window.setTimeout(() => setCopyFeedback((current) => current === currentCopyFeedback ? null : current), 5000);
    return () => window.clearTimeout(timer);
  }, [currentCopyFeedback]);
  async function copyLink() {
    const sequence = ++copySequence.current;
    setCopyFeedback(null);
    try {
      await onCopyLink();
      if (sequence === copySequence.current) setCopyFeedback({ stopId: selectedStopId, sequence, failed: false });
    } catch {
      if (sequence === copySequence.current) setCopyFeedback({ stopId: selectedStopId, sequence, failed: true });
    }
  }
  const stopsById = useMemo(() => new Map(catalog?.stops.map((stop) => [stop.id, stop])), [catalog]);
  const visibleRoutes = useMemo(() => catalog?.routes.filter((route) =>
    modes.includes(route.mode)) ?? [],
  [catalog, modes]);
  const selectedStop = selectedStopId ? stopsById.get(selectedStopId) : undefined;
  const departures = useMemo(() => visibleRoutes.filter((route) => route.from === selectedStopId)
    .sort((left, right) => (stopsById.get(left.to)?.name ?? left.to)
      .localeCompare(stopsById.get(right.to)?.name ?? right.to)),
  [visibleRoutes, selectedStopId, stopsById]);

  useEffect(() => {
    if (expanded) firstOptionRef.current?.focus();
  }, [expanded]);

  useEffect(() => {
    if (!expanded) return;
    const dismiss = (event: PointerEvent) => {
      if (event.target instanceof Node && !controlsRef.current?.contains(event.target)) {
        onExpandedChange(false);
      }
    };
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, [expanded, onExpandedChange]);

  useEffect(() => {
    if (!enabled || !selectedStopId) {
      focusedStopRef.current = null;
    } else if (!expanded && focusedStopRef.current !== selectedStopId) {
      cardTitleRef.current?.focus({ preventScroll: true });
      focusedStopRef.current = selectedStopId;
    }
  }, [selectedStopId, enabled, expanded]);

  const feedback = enabled && (status === 'loading' || status === 'error') ? (
    <div className="transport-feedback" role="status">
      {status === 'loading' ? 'Loading transport networks…' : (
        <>Transport could not be loaded. <button type="button" onClick={onRetry}>Retry</button></>
      )}
    </div>
  ) : null;

  return (
    <>
      <div
        className="transport-controls"
        ref={controlsRef}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && expanded) {
            event.stopPropagation();
            onExpandedChange(false);
            optionsButtonRef.current?.focus();
          }
        }}
      >
        <div className="transport-toolbar" role="group" aria-label="Transport overlay">
          <button type="button" className="transport-toggle" aria-pressed={enabled} onClick={onToggle}>
            <span>Transport</span><span className="transport-toggle-state" aria-hidden="true">{enabled ? 'On' : 'Off'}</span>
          </button>
          <button
            type="button"
            className="transport-options-toggle"
            ref={optionsButtonRef}
            aria-label="Transport options"
            aria-expanded={expanded}
            aria-controls={`${id}-options`}
            onClick={() => onExpandedChange(!expanded)}
          >
            <span className={`transport-chevron${expanded ? ' transport-chevron--open' : ''}`} aria-hidden="true" />
          </button>
        </div>
        {expanded ? (
          <section id={`${id}-options`} className="transport-options" aria-label="Transport options">
            <fieldset>
              <legend>Transport networks</legend>
              {MODE_ORDER.map((mode, index) => (
                <label className="transport-option" key={mode}>
                  <input
                    ref={index === 0 ? firstOptionRef : undefined}
                    type="checkbox"
                    checked={modes.includes(mode)}
                    onChange={(event) => onModesChange(event.currentTarget.checked
                      ? MODE_ORDER.filter((candidate) => candidate === mode || modes.includes(candidate))
                      : modes.filter((candidate) => candidate !== mode))}
                  />
                  <ModeSample mode={mode} />
                  <span><strong>{TRANSPORT_MODES[mode].label}</strong><small>{MODE_DESCRIPTIONS[mode]}</small></span>
                </label>
              ))}
            </fieldset>
            <p className="transport-help">Lines show connections, not the path travelled.</p>
            {!enabled ? <p className="transport-off-note">Turn Transport on to show the selected networks.</p> : null}
            {feedback}
          </section>
        ) : feedback}
      </div>
      {enabled && selectedStop && !expanded ? (
        <section
          className="transport-stop-card"
          aria-labelledby={`${id}-stop-title`}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.stopPropagation();
              onStopSelect(null);
              optionsButtonRef.current?.focus();
            }
          }}
        >
          <button className="transport-card-close" type="button" aria-label="Close transport stop" onClick={() => {
            onStopSelect(null);
            optionsButtonRef.current?.focus();
          }}><PixelIcon name="close" /></button>
          <p className="transport-card-eyebrow">Transport stop</p>
          <div className="place-card-title">
            <h2 id={`${id}-stop-title`} ref={cardTitleRef} tabIndex={-1}>
              {wikiUrl ? <a href={wikiUrl} target="_blank" rel="noopener noreferrer">{selectedStop.name}</a> : selectedStop.name}
            </h2>
            <button className="place-card-copy-link" type="button" onClick={() => void copyLink()} aria-label="Copy transport stop link" title="Copy transport stop link">
              <PixelIcon name="link" />
            </button>
          </div>
          {currentCopyFeedback ? <p key={currentCopyFeedback.sequence}
            className={`place-share-feedback${currentCopyFeedback.failed ? ' place-share-feedback--error' : ''}`}
            role={currentCopyFeedback.failed ? 'alert' : 'status'}>
            {currentCopyFeedback.failed ? 'Could not copy link. Please try again.' : 'Link copied.'}
          </p> : null}
          {selectedStop.external ? <p className="transport-card-note">Outside this map’s coverage.</p> : null}
          {selectedStop.interior ? <p className="transport-card-note">Service inside {selectedStop.interior}.</p> : null}
          <h3>Departures <span>{departures.length}</span></h3>
          {departures.length === 0 ? <p className="transport-card-note">No departures with the current transport options. This may be an arrival point.</p> : (
            <ul className="transport-departures">
              {departures.map((route) => (
                <li key={route.id}>
                  <div className="transport-destination-row">
                    <ModeSample mode={route.mode} />
                    {stopsById.get(route.to)?.external ? (
                      <span className="transport-destination transport-destination--external"><span className="transport-direction" aria-label="To">→</span> {stopsById.get(route.to)?.name ?? route.to}<small>Outside this map</small></span>
                    ) : (
                      <button type="button" className="transport-destination" onClick={() => onDestinationSelect(route.to)}>
                        <span className="transport-direction" aria-label="To">→</span> {stopsById.get(route.to)?.name ?? route.to}
                      </button>
                    )}
                  </div>
                  <p className="transport-provider">{route.subtype.replaceAll('_', ' ')} · {route.provider}</p>
                  {route.conditions.length > 0 ? (
                    <div className="transport-conditions">
                      <strong>Requires</strong>
                      <ul>{route.conditions.map((condition) => <li key={condition}>{condition}</li>)}</ul>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
    </>
  );
}
