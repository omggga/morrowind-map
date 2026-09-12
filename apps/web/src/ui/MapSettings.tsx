import { useRef, useState } from 'react';
import { PixelIcon } from './PixelIcon';
import { StatusMark } from './StatusMark';

interface MapSettingsProps {
  readonly colorblind: boolean;
  readonly onColorblindChange: (enabled: boolean) => boolean;
}

export function MapSettings({ colorblind, onColorblindChange }: MapSettingsProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  return (
    <>
      <button
        className="map-settings-trigger"
        type="button"
        aria-label="Map settings"
        title="Map settings"
        aria-haspopup="dialog"
        aria-controls="map-settings-panel"
        aria-expanded={isOpen}
        onClick={() => {
          dialogRef.current?.showModal();
          setIsOpen(true);
        }}
      >
        <PixelIcon name="settings" />
      </button>
      <dialog
        ref={dialogRef}
        id="map-settings-panel"
        className="landing-contact-panel map-settings-panel"
        aria-labelledby="map-settings-title"
        onClose={() => setIsOpen(false)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation();
          }
        }}
      >
        <button
          className="landing-contact-panel__close"
          type="button"
          aria-label="Close map settings"
          onClick={() => dialogRef.current?.close()}
        >
          <PixelIcon name="close" />
        </button>
        <h2 id="map-settings-title">Map settings</h2>
        <label className="map-settings-option">
          <input
            type="checkbox"
            checked={colorblind}
            aria-describedby="map-settings-color-description"
            onChange={(event) => {
              setSaveFailed(!onColorblindChange(event.currentTarget.checked));
            }}
          />
          <span>Enable colorblind-friendly mode</span>
        </label>
        <p id="map-settings-color-description">
          Distinguish places and personal markers by both color and shape. Applies immediately to all maps.
        </p>
        <div className="map-settings-preview" role="group" aria-label="Status color preview">
          <span><StatusMark kind="unvisited" />Unvisited</span>
          <span><StatusMark kind="active" />Active</span>
          <span><StatusMark kind="visited" />Visited</span>
          <span><StatusMark kind="custom" />Personal marker</span>
        </div>
        {saveFailed ? (
          <p role="status">Colors changed for this session. Your browser could not save the preference.</p>
        ) : null}
      </dialog>
    </>
  );
}
