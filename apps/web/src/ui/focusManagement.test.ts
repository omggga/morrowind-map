import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createFocusReturnController,
  isKeyboardActivation,
} from './focusManagement';

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

function runAnimationFrames() {
  const callbacks: FrameRequestCallback[] = [];
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    callbacks.push(callback);
    return callbacks.length;
  });
  return () => callbacks.splice(0).forEach((callback) => callback(0));
}

describe('focus management', () => {
  it('focuses a non-modal card and returns to its exact connected initiator', () => {
    const flushAnimationFrames = runAnimationFrames();
    const origin = document.createElement('button');
    const card = document.createElement('article');
    card.tabIndex = -1;
    document.body.append(origin, card);
    const focus = createFocusReturnController();

    origin.focus();
    focus.remember(origin);
    focus.focus(() => card);
    flushAnimationFrames();
    expect(card).toHaveFocus();

    focus.restore(() => null);
    flushAnimationFrames();
    expect(origin).toHaveFocus();
  });

  it('uses a connected fallback after the initiating element is removed', () => {
    const flushAnimationFrames = runAnimationFrames();
    const origin = document.createElement('button');
    const fallback = document.createElement('button');
    document.body.append(origin, fallback);
    const focus = createFocusReturnController();

    focus.remember(origin);
    origin.remove();
    focus.restore(() => fallback);
    flushAnimationFrames();

    expect(fallback).toHaveFocus();
  });

  it('recognizes native keyboard-generated button clicks', () => {
    expect(isKeyboardActivation(0)).toBe(true);
    expect(isKeyboardActivation(1)).toBe(false);
  });
});
