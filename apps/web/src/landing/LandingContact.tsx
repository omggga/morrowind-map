import { useRef, useState } from 'react';
import { createFocusReturnController } from '../ui/focusManagement';
import { PixelIcon } from '../ui/PixelIcon';

const CONTACT_PANEL_ID = 'landing-contact-panel';

export function LandingContact() {
  const [isOpen, setIsOpen] = useState(false);
  const [focusReturn] = useState(createFocusReturnController);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);

  const open = () => {
    focusReturn.remember(triggerRef.current);
    setIsOpen(true);
    focusReturn.focus(() => panelRef.current);
  };

  const close = () => {
    setIsOpen(false);
    focusReturn.restore(() => triggerRef.current);
  };

  return (
    <>
      <button
        ref={triggerRef}
        className="landing-contact-trigger"
        type="button"
        aria-label="Contact information"
        aria-controls={CONTACT_PANEL_ID}
        aria-expanded={isOpen}
        onClick={open}
      >
        <span aria-hidden="true">?</span>
      </button>

      {isOpen ? (
        <aside
          ref={panelRef}
          id={CONTACT_PANEL_ID}
          className="landing-contact-panel"
          tabIndex={-1}
          aria-labelledby="landing-contact-title"
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              event.stopPropagation();
              close();
            }
          }}
        >
          <button
            className="landing-contact-panel__close"
            type="button"
            aria-label="Close contact information"
            onClick={close}
          >
            <PixelIcon name="close" />
          </button>
          <h2 id="landing-contact-title" className="visually-hidden">
            Contact information
          </h2>
          <div className="landing-contact-panel__links">
            <a
              href="mailto:murashkin.alex@proton.me"
              target="_blank"
              rel="noopener noreferrer"
            >
              <PixelIcon name="mail" />
              <span>murashkin.alex@proton.me</span>
            </a>
            <a
              href="https://github.com/omggga"
              target="_blank"
              rel="noopener noreferrer"
            >
              <PixelIcon name="github" />
              <span>github.com/omggga</span>
            </a>
          </div>
        </aside>
      ) : null}
    </>
  );
}
