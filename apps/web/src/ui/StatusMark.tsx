import { MARKER_SEMANTICS, type MarkerKind } from './markerSemantics';

interface StatusMarkProps {
  readonly kind: MarkerKind;
  readonly className?: string;
}

export function StatusMark({ kind, className = '' }: StatusMarkProps) {
  const semantic = MARKER_SEMANTICS[kind];
  return (
    <svg
      aria-hidden="true"
      className={`status-mark status-mark--${kind}${className ? ` ${className}` : ''}`}
      data-marker-kind={kind}
      data-marker-shape={semantic.shape}
      focusable="false"
      viewBox="0 0 12 12"
    >
      <path d={semantic.path} fillRule={semantic.fillRule} />
    </svg>
  );
}
