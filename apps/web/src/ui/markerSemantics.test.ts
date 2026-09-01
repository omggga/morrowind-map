import { describe, expect, it } from 'vitest';
import { MARKER_KINDS, MARKER_SEMANTICS } from './markerSemantics';

describe('marker semantics', () => {
  it('uses one thin hollow-square geometry for every requested marker kind', () => {
    expect(MARKER_KINDS).toEqual(['unvisited', 'active', 'visited', 'custom']);
    expect(
      Object.fromEntries(
        MARKER_KINDS.map((kind) => [kind, MARKER_SEMANTICS[kind].shape]),
      ),
    ).toEqual({
      unvisited: 'hollow-square',
      active: 'hollow-square',
      visited: 'hollow-square',
      custom: 'hollow-square',
    });

    expect(new Set(MARKER_KINDS.map((kind) => MARKER_SEMANTICS[kind].path))).toEqual(
      new Set(['M1 1H11V11H1ZM2 2V10H10V2Z']),
    );
    expect(MARKER_KINDS.every((kind) => MARKER_SEMANTICS[kind].fillRule === 'evenodd'))
      .toBe(true);
  });

  it('keeps the four MIM marker colors explicit and distinct', () => {
    const colors = MARKER_KINDS.map((kind) => MARKER_SEMANTICS[kind].color);

    expect(colors).toEqual(['#f6e27d', '#e88bea', '#e9a15b', '#78db78']);
    expect(new Set(colors).size).toBe(MARKER_KINDS.length);
  });
});
