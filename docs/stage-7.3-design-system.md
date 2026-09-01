# Stage 7.3 — MIM design system

Status: **approved reference system (2026-09-01)**.

This document is the normative visual contract shared by the landing page and both map workspaces. It fixes the Stage 7.3 typography, tokens, icons, marker semantics and component states without changing either published basemap. Stage 7.4 consumes this contract when it creates pinned visual-regression projects and completes the responsive/accessibility gate.

## Invariants

- Original GOTY HD and Poison Song V4 use one component and token system. Dataset-specific presentation is limited to manifest-backed titles, metadata and existing basemap treatment.
- Published tiles, catalogs, manifests and their hashes are not changed or corrected by this design system.
- Fonts and icons are same-origin build assets. The browser must not contact Google Fonts, a CDN or another external font/icon service.
- Meaning is not encoded by colour alone. Text labels, geometry and interaction state remain available when colour cannot be distinguished.
- Core body copy and values use `11–14px`; dense utility labels may use the `10px` floor only with the high-contrast data/UI faces. The former meaningful `7–9px` styles are removed.

## Typography

The application imports version-pinned Fontsource packages before application CSS. Vite emits their WOFF2 files as hashed same-origin assets; the primary UI and data faces are preloaded. `font-synthesis: none` prevents platform-dependent synthetic weights.

| Role | Family | Supported use |
| --- | --- | --- |
| UI and controls | Atkinson Hyperlegible Next Variable, weights `400–700` | Body copy, buttons, inputs, filters, alerts and supporting metadata. Its differentiated letterforms are the readability baseline. |
| Record and display | Alegreya Variable, weights `600–700` | Landing hero, dataset/place names and parchment-like record headings. It is used sparingly and never for compact controls or coordinates. |
| Coordinates and map data | IBM Plex Mono, weights `400` and `500` | Coordinates, cell IDs, snapshot IDs, titlebar kickers, status readouts and OpenLayers place labels. Map labels use `11px`; selected labels use weight `500`. |

The type scale is `10 / 11 / 12 / 13 / 14 / 16 / 20 / 28px`, with responsive display headings allowed to grow to `54px`. Line height is at least `1.35` for compact content and `1.5` for paragraphs. Letter spacing may identify utility metadata, but it does not replace size or weight hierarchy.

Font provenance and the complete SIL Open Font License 1.1 text are recorded in `THIRD_PARTY_NOTICES.md` and `licenses/OFL-1.1.txt`.

## Semantic tokens

Components consume roles, not dataset-specific colours. The current reference palette is:

| Role | Value | Purpose |
| --- | --- | --- |
| Ink | `#171914` | Primary dark background and marker cut-outs |
| Ash | `#252821` | Raised panel/control surface |
| Ash light | `#393d33` | Hovered or secondary raised surface |
| Paper | `#d2c69b` | Record/card surface |
| Paper dim | `#b8ad84` | Muted parchment structure |
| Brass | `#b09b5f` | Selection rail and structural accent |
| Brass light | `#e2cf8d` | High-emphasis accent on dark surfaces |
| Moss | `#566149` | Quiet positive/local state |
| Ember | `#a5523b` | Error/destructive structure |
| Line | `#4b5042` | Flat borders and dividers |
| Shadow | `#080906` | Recessed edge and floating shadow |
| Strong/body/muted/subtle text | `#f2ead0` / `#d5ceb2` / `#b9b399` / `#a5a187` | Dark-surface text hierarchy |
| Paper ink/muted | `#242218` / `#585239` | Record/card text hierarchy |
| Paper positive/error | `#3c4d32` / `#6b281f` | Saved and failed editor feedback |
| Dark-surface focus | `#fff2b2` | Keyboard focus ring and selected-marker halo |
| Paper-surface focus | `#233c46` | Keyboard focus ring on record/card surfaces |

Marker colours are semantic tokens of their own and are listed with their shapes below. Foreground/background pairs must meet WCAG 2.2 AA: `4.5:1` for normal text, `3:1` for large text and `3:1` for meaningful component boundaries or graphics.

### Structure, spacing and elevation

- The spacing grid is `4px`: `4 / 8 / 12 / 16 / 24 / 32px`. Optical one-to-three-pixel border corrections do not create new spacing tokens.
- Compact controls and icon-only desktop buttons are `32px` high; text inputs and primary controls are at least `36px`. Coarse-pointer controls expose a `44px` hit area without scaling the `16px` icon.
- Titlebars have an adaptive `min-height: 64px`. Text may wrap or truncate according to the component contract; the titlebar does not shrink below its controls.
- Border/elevation has three levels: flat (`1px` divider), raised/recessed (paired light and dark inset edges), and floating (structural border plus a hard offset shadow). Soft generic card shadows and rounded pills are not part of the MIM language.

OpenLayers and DOM overlays use separate ordered stacks:

| Stack | Order |
| --- | --- |
| Map layers | basemap `0` → catalog markers `10` → catalog labels `11` → personal markers `20` |
| DOM overlays | canvas/content `0–3` → map controls `4` → legend `5` → ledger `6` → system status/placement `7` → cards `8` |

No component may introduce an arbitrary z-index above these roles. A new modal layer, if ever required, must be added as a named token rather than a one-off number.

## Pixel icons

`apps/web/src/ui/PixelIcon.tsx` is the single icon vocabulary: `archive`, `back`, `open`, `zoom-in`, `zoom-out`, `fit-map`, `marker-add` and `close`. Icons use integer paths in a `16×16` view box and render with crisp edges. They inherit `currentColor`, remain decorative (`aria-hidden="true"`) and never supply an accessible name themselves.

The owning button retains its existing translated visible text or `aria-label`. Hover, pressed, selected, focus and disabled states belong to the button; the icon does not create a second interaction state. A text glyph must not be used as a platform-dependent substitute for one of the defined icons.

## Marker semantics

`apps/web/src/ui/markerSemantics.ts` is the shared source for OpenLayers marker SVGs, result rows, the legend and progress controls. `StatusMark` renders the DOM representation; the map uses the same integer paths in cached data-URL images. All four shapes use a `12×12` grid.

| Kind | Colour | Shape/pattern | Meaning |
| --- | --- | --- | --- |
| `unvisited` | `#f6e27d` | Hollow square | Catalog place with no saved progress record |
| `active` | `#e88bea` | Hollow diamond | Place currently in progress |
| `visited` | `#e9a15b` | Filled square with a cut-out check | Completed/visited place |
| `custom` | `#78db78` | Cross | User-created personal marker |

Colour, shape and adjacent text agree everywhere. Hover adds a brass outer frame; selection adds the larger focus-coloured outer frame and higher render priority without replacing the underlying semantic shape. OpenLayers caches the default, hover and selected styles so marker state stays stable at both normal and HiDPI scale.

## Component state contract

Every interactive component implements the same state vocabulary:

| State | Required treatment |
| --- | --- |
| Default | AA text and a visible component boundary on its surface |
| Hover | Ash/brass surface or border change; no layout movement that changes the hit target |
| Pressed | Recessed bevel and at most a one-pixel optical shift |
| Selected | Persistent brass rail/frame or `aria-pressed` surface; not hover-only |
| Focus | `2px` focus-colour outline with `3px` offset; it remains visible on selected and error states |
| Disabled | Native disabled semantics, non-interactive cursor and a visibly muted treatment; no state conveyed only by opacity |
| Loading | Stable component geometry, `aria-busy`/status semantics and no false empty state |
| Error | Ember structure, AA error text and a recovery action where the operation is retryable |

Landing cards, titlebars, ledger/search, filters, map controls, place and personal-marker cards, data tools and current loading/error/empty surfaces use this matrix. Stage 7.5 remains responsible for completing the behavioural state/fixture matrix; it does not redefine these visual states.

## Reference screenshot matrix

Stage 7.3 reference captures are review artifacts, not golden tests. The checked-in set contains real-map readability references; Stage 7.4 will add deterministic synthetic component fixtures before promoting any image to a golden test.

Capture defaults: Chromium, `1280×720`, DPR `1`, reduced motion, cleared browser storage, local network only, fonts loaded and the map idle before capture.

| Reference | Data | Required evidence |
| --- | --- | --- |
| Landing | Two real manifests | Display/UI/data fonts, both dataset cards, archive/open icons and keyboard focus |
| Original default map | Original GOTY HD | Labels and all overlays remain readable on the Original basemap; legend and controls use final icons |
| Poison default map | Poison Song V4 | The same components remain readable on the denser Poison basemap without a dataset-specific CSS branch |
| Filters and place record | Original GOTY HD | Open filters, selected label, record card, progress choices and note field |
| Personal marker | Synthetic marker (7.4 fixture) | Result, selected map marker, editor and delete-confirmation treatment |

Accepted desktop files are `visual-baselines/stage-7.3/landing-desktop.png`, `original-desktop.png`, `poison-desktop.png` and `filter-card-desktop.png`.

`390×844` landing, open filter drawer and place/editor captures are Stage 7.3 smoke references only. Stage 7.4 owns golden snapshots for desktop, narrow portrait and both landscape sizes, plus browser zoom/reflow and interaction-path evidence. Loading, partial failure, empty and retry screenshots become golden only after Stage 7.5 supplies their deterministic behavioural fixtures.

## Stage 7.4 hand-off

Stage 7.3 is complete when the local assets, semantic styles and reference matrix above are stable on both basemaps. Stage 7.4 must not redesign them. It must:

1. pin browser, viewport, DPR, font readiness, animation and fixture state;
2. turn the approved references into maintained Playwright snapshots;
3. cover `390×844`, `320×568`, `844×390` and `667×375`, safe areas and 200% reflow;
4. verify keyboard-only and touch flows, target sizes, focus order and automated/manual accessibility;
5. keep functional two-dataset acceptance as a separate required gate.
