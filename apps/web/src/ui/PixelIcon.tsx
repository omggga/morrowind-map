import type { PixelIconName } from './pixelIconRegistry';

interface PixelIconProps {
  readonly name: PixelIconName;
  readonly className?: string;
}

function IconPath({ name }: { readonly name: PixelIconName }) {
  switch (name) {
    case 'archive':
      return <path d="M1 2h4l3 2 3-2h4v12h-4l-3-2-3 2H1V2zm2 2v7l2-1V4H3zm4 2v4l2 1V5L8 6 7 5v1zm4-2v6l2 1V4h-2z" />;
    case 'back':
      return <path d="M1 8l6-6v4h8v4H7v4L1 8z" />;
    case 'open':
      return <path d="M8 1h7v7h-2V4l-6 6-1-2 5-5H8V1zM2 3h5v2H4v7h7V9h2v5H2V3z" />;
    case 'zoom-in':
      return <path d="M2 2h8v2H4v6h6V2h2v8h-2v2H4v-2H2V2zm5 2h2v2h2v2H9v2H7V8H5V6h2V4zm5 8h2v2h-2v-2z" />;
    case 'zoom-out':
      return <path d="M2 2h8v2H4v6h6V2h2v8h-2v2H4v-2H2V2zm3 4h6v2H5V6zm7 6h2v2h-2v-2z" />;
    case 'fit-map':
      return <path d="M1 1h6v2H3v4H1V1zm8 0h6v6h-2V3H9V1zM1 9h2v4h4v2H1V9zm12 0h2v6H9v-2h4V9zM6 6h4v4H6V6z" />;
    case 'marker-add':
      return <path d="M2 1h8v2H4v6h2v2H4V9H2V1zm6 3h3V1h2v3h3v2h-3v3h-2V6H8V4zM6 11h2v2H6v-2zm2 2h2v2H8v-2z" />;
    case 'close':
      return <path d="M2 2h3v2h2v2h2V4h2V2h3v3h-2v2h-2v2h2v2h2v3h-3v-2H9v-2H7v2H5v2H2v-3h2V9h2V7H4V5H2V2z" />;
  }
}

export function PixelIcon({ name, className = '' }: PixelIconProps) {
  return (
    <svg
      aria-hidden="true"
      className={`pixel-icon${className ? ` ${className}` : ''}`}
      data-pixel-icon={name}
      focusable="false"
      viewBox="0 0 16 16"
    >
      <IconPath name={name} />
    </svg>
  );
}
