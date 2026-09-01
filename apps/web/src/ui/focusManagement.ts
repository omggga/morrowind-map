export interface FocusReturnController {
  readonly remember: (origin: HTMLElement | null) => void;
  readonly focus: (target: () => HTMLElement | null) => void;
  readonly restore: (fallback: () => HTMLElement | null) => void;
  readonly clear: () => void;
}

function focusOnNextFrame(resolveTarget: () => HTMLElement | null): void {
  window.requestAnimationFrame(() => {
    resolveTarget()?.focus({ preventScroll: true });
  });
}

export function isKeyboardActivation(detail: number): boolean {
  return detail === 0;
}

export function createFocusReturnController(): FocusReturnController {
  let origin: HTMLElement | null = null;

  return {
    remember(nextOrigin) {
      origin = nextOrigin;
    },
    focus(target) {
      focusOnNextFrame(target);
    },
    restore(fallback) {
      const rememberedOrigin = origin;
      origin = null;
      focusOnNextFrame(() =>
        rememberedOrigin?.isConnected ? rememberedOrigin : fallback(),
      );
    },
    clear() {
      origin = null;
    },
  };
}
