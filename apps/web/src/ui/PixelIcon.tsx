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
      return <path d="M7 1h2v8l3-3 2 2-6 6-6-6 2-2 3 3V1z" />;
    case 'export':
      return <path d="M7 15h2V7l3 3 2-2-6-6-6 6 2 2 3-3v8z" />;
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
