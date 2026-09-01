// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { PixelIcon } from './PixelIcon';
import { PIXEL_ICON_NAMES } from './pixelIconRegistry';

afterEach(cleanup);

describe('PixelIcon', () => {
  it('renders every local icon as a stable, non-focusable decorative SVG', () => {
    const { container } = render(
      <div>
        {PIXEL_ICON_NAMES.map((name) => (
          <PixelIcon key={name} name={name} />
        ))}
      </div>,
    );

    const icons = [...container.querySelectorAll('svg.pixel-icon')];
    expect(icons).toHaveLength(PIXEL_ICON_NAMES.length);
    expect(icons.map((icon) => icon.getAttribute('data-pixel-icon'))).toEqual(
      PIXEL_ICON_NAMES,
    );

    for (const icon of icons) {
      expect(icon).toHaveAttribute('aria-hidden', 'true');
      expect(icon).toHaveAttribute('focusable', 'false');
      expect(icon).toHaveAttribute('viewBox', '0 0 16 16');
      expect(icon.querySelector('path')).not.toBeNull();
    }
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('preserves a caller class without changing the stable icon marker', () => {
    const { container } = render(<PixelIcon name="back" className="button-icon" />);
    const icon = container.querySelector('[data-pixel-icon="back"]');

    expect(icon).toHaveClass('pixel-icon', 'button-icon');
    expect(icon).toHaveAttribute('aria-hidden', 'true');
  });
});
