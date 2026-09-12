import type { PixelIconName } from './pixelIconRegistry';

interface PixelIconProps {
  readonly name: PixelIconName;
  readonly className?: string;
}

function IconPath({ name }: { readonly name: PixelIconName }) {
  switch (name) {
    case 'back':
      return <path d="M1 8l6-6v4h8v4H7v4L1 8z" />;
    case 'import':
      return (
        <>
          <path d="M7 1h2v7l2-2 2 2-5 5-5-5 2-2 2 2V1z" />
          <path d="M1 10h2v3h10v-3h2v5H1v-5z" />
        </>
      );
    case 'export':
      return (
        <>
          <path d="M7 12h2V5l2 2 2-2-5-5-5 5 2 2 2-2v7z" />
          <path d="M1 10h2v3h10v-3h2v5H1v-5z" />
        </>
      );
    case 'close':
      return <path d="M2 2h3v2h2v2h2V4h2V2h3v3h-2v2h-2v2h2v2h2v3h-3v-2H9v-2H7v2H5v2H2v-3h2V9h2V7H4V5H2V2z" />;
    case 'mail':
      return (
        <>
          <path d="M1 3h14v2L8 10 1 5V3zm0 4 7 5 7-5v6H1V7z" />
          <path d="M3 5h10L8 8 3 5z" />
        </>
      );
    case 'github':
      return <path d="M8 1C4 1 1 4 1 8c0 3 2 6 5 7v-2c-2 0-2-1-3-2 0-1-1-1-1-1 1 0 1 1 2 1 1 1 2 0 2 0 0-1 0-1 1-2-2 0-4-1-4-4 0-1 0-2 1-3 0-1 0-2 0-2 2 0 2 1 3 1h2c1 0 2-1 3-1 0 0 0 1 0 2 1 1 1 2 1 3 0 3-2 4-4 4 1 1 1 2 1 4v2c3-1 5-4 5-7 0-4-3-7-7-7z" />;
    case 'link':
      return <path d="M9 1h4v2h2v4h-2v2h-3V7h2V6h1V4h-1V3h-2v1H9v2H7V3h2V1zM6 7v2H4v1H3v2h1v1h2v-1h1v-2h2v3H7v2H3v-2H1V9h2V7h3zM9 5h2v2H9v2H7v2H5V9h2V7h2V5z" />;
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
