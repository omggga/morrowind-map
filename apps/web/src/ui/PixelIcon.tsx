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
