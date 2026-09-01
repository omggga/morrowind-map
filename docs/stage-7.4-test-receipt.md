# Stage 7.4 — visual, responsive and accessibility receipt

Дата фиксации: 2026-09-01. Статус: **implementation и automated acceptance завершены; physical screen-reader sign-off остаётся ручным**.

## Зафиксированная среда

- Chromium из `@playwright/test 1.62.1`, locale `en-US`, timezone `UTC`, DPR `1`, dark color scheme, `prefers-reduced-motion: reduce`;
- service workers заблокированы, animations/caret отключены для snapshots, Chromium принудительно использует sRGB;
- deterministic synthetic manifests, catalogs и tiles не зависят от prepared production datasets и внешней сети;
- отдельные baselines сохранены для `darwin` и `linux`, поэтому macOS review и Ubuntu GitHub Actions не сравнивают platform-dependent rasterization друг с другом.

## Viewport matrix

| Project | Viewport | Проверка |
| --- | ---: | --- |
| `desktop-1280x720` | `1280×720` | полная state matrix, keyboard-only, 200% reflow, axe |
| `portrait-390x844` | `390×844` | landing/map snapshots, touch targets, zoom/pan/tap |
| `portrait-320x568` | `320×568` | narrow portrait snapshots и отсутствие clipping |
| `landscape-844x390` | `844×390` | landscape snapshots, touch targets, zoom/pan/tap |
| `landscape-667x375` | `667×375` | short landscape snapshots и scroll ownership |

Каждая платформа хранит `27` PNG: landing и Poison map для всех пяти проектов плюс desktop Original, filters/labels, no-results, selected place, progress/note, personal-marker editor/delete, data tools, loading, tile error/retry, dataset error/retry/missing, 200% reflow, partial manifest landing и partial tile failure.

## Automated acceptance

`tests/ui/stage-7.4.visual.spec.ts` проверяет:

1. обе map themes и общую interactive/system-state matrix;
2. настоящий keyboard-only flow через `Tab`, `Shift+Tab`, `Enter`, `Space` и `Escape`, включая точный focus return;
3. `640×360` как 200% browser-zoom equivalent: без page-level horizontal overflow, с достижимым non-map content;
4. coarse-pointer controls минимум `24×24 CSS px`, основные controls `44×44 CSS px`, trusted touch zoom/pan/tap;
5. обе карты и ключевые selected/editor states через axe: `0` unwaived WCAG 2.2 AA violations и `0` serious/critical best-practice findings.

Прошедшие platform runs:

```text
macOS  darwin  pnpm test:ui:update  -> 26 passed, 74 skipped
Ubuntu linux   pnpm test:ui:update  -> 26 passed, 74 skipped
macOS  darwin  pnpm test:ui         -> 26 passed, 74 skipped
macOS  darwin  pnpm verify          -> exit 0
```

Ожидаемые skips принадлежат project matrix: desktop-only state/a11y/keyboard/reflow cases и touch-only portrait/landscape cases не дублируются на неподходящих проектах.

## Исправления, подтверждённые тестами

- safe-area offsets, narrow portrait и short-landscape layout больше не скрывают ledger, overlays или retry controls;
- вход в dataset сбрасывает сохранённый landing scroll, а полный map title переносится и остаётся видимым на `320px`;
- non-map content имеет одного scroll owner, а интерактивная карта сохраняет допустимую двумерную pan surface;
- map viewport объявлен как keyboard-operable application с постоянной инструкцией, controls и legend объединены в именованные groups;
- selected entries публикуют `aria-current`, Escape закрывает non-modal cards/confirmation и возвращает focus инициатору;
- touch mode не зависит от hover, OpenLayers принимает touch interaction без предварительного focus;
- URL view sync debounced после `moveend`, поэтому initial fit не осциллирует и snapshots воспроизводимы;
- `focus-visible`, reduced-motion, `24px` minimum и `44px` primary target policy применяются к desktop/mobile controls.

## Manual checklist

- [x] Embedded Chromium desktop spot-check: landing/map landmarks, heading order, button/searchbox names, map instructions и named groups присутствуют в accessibility tree.
- [x] Desktop visual spot-check: titlebar, ledger, map, tool rail, legend и status bar не перекрываются.
- [x] Keyboard-only и focus-return path выполнен реальными key events в Playwright, без программного `.focus()` для обхода Tab order.
- [x] 200% reflow, `320px` portrait и обе short-landscape геометрии проверены snapshots и overflow assertions.
- [ ] Physical screen reader: пройти минимум Chrome + VoiceOver на macOS либо Chrome + NVDA на Windows; подтвердить landing cards, search/filter state, selected place, progress announcement, marker confirmation и возврат focus.

Последний пункт требует слышимого пользовательского сеанса и намеренно не подменён axe или Chromium accessibility tree. До этого sign-off Stage 7.4 считается полностью реализованным, но не формально принятым по manual accessibility gate.

## Воспроизведение

```bash
pnpm test:ui
pnpm verify
```

Обновлять snapshots следует только после осознанного visual review:

```bash
pnpm test:ui:update
```

Linux baselines генерируются тем же Playwright `1.62.1` в официальном контейнере; CI никогда не запускает update mode:

```bash
docker run --rm --platform linux/amd64 --ipc=host \
  -v "$PWD":/work \
  -v morrowind-map-stage74-node-modules:/work/node_modules \
  -w /work mcr.microsoft.com/playwright:v1.62.1-noble \
  bash -lc 'corepack enable && pnpm test:ui:update'
```
