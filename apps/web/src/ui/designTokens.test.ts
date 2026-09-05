import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(process.cwd(), 'apps/web/src/styles.css'), 'utf8');

function colorToken(name: string): string {
  const match = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'));
  if (!match?.[1]) {
    throw new Error(`Missing color token --${name}`);
  }
  return match[1].toLowerCase();
}

function relativeLuminance(hex: string): number {
  const channels = hex.match(/[0-9a-f]{2}/gi)?.map((value) => Number.parseInt(value, 16) / 255);
  if (!channels || channels.length !== 3) {
    throw new Error(`Invalid color ${hex}`);
  }
  const [red = 0, green = 0, blue = 0] = channels.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrast(left: string, right: string): number {
  const leftLuminance = relativeLuminance(left);
  const rightLuminance = relativeLuminance(right);
  return (Math.max(leftLuminance, rightLuminance) + 0.05) /
    (Math.min(leftLuminance, rightLuminance) + 0.05);
}

describe('Dunmer atlas design tokens', () => {
  it.each([
    ['ui-gold', 'ui-void'],
    ['ui-gold', 'ui-panel'],
    ['book-ink', 'book-paper'],
  ])('keeps normal text token %s on %s at WCAG AA contrast', (foreground, background) => {
    expect(contrast(colorToken(foreground), colorToken(background))).toBeGreaterThanOrEqual(4.5);
  });

  it('keeps brass structural lines distinguishable from the dark panel', () => {
    expect(contrast(colorToken('ui-brass'), colorToken('ui-panel'))).toBeGreaterThanOrEqual(3);
  });
});
