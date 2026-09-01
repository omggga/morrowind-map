import { describe, expect, it } from 'vitest';
import { CurrentBasemapLoadWindow } from './currentBasemapLoadWindow';

describe('CurrentBasemapLoadWindow', () => {
  it('does not carry loaded tiles into a later viewport whose requests all fail', () => {
    const window = new CurrentBasemapLoadWindow<object>();
    const previousTile = {};
    const stalePendingTile = {};
    const failedTile = {};

    window.start(previousTile);
    window.finish(previousTile);
    window.start(stalePendingTile);
    expect(window.loadedCount).toBe(1);

    window.beginViewport();
    window.finish(stalePendingTile);
    window.start(failedTile);
    window.fail(failedTile);

    expect(window.loadedCount).toBe(0);
  });

  it('counts successful requests from the current viewport only', () => {
    const window = new CurrentBasemapLoadWindow<object>();
    const loadedTile = {};
    const failedTile = {};

    window.beginViewport();
    window.start(loadedTile);
    window.start(failedTile);
    window.finish(loadedTile);
    window.fail(failedTile);

    expect(window.loadedCount).toBe(1);
  });
});
