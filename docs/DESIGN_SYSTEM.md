# Design system

Both maps share the visual language **Dunmer atlas under glass**. Differences between Original and Tamriel Rebuilt come only from their manifests, basemaps, and catalogs; datasets do not have separate CSS themes. All application copy is in English.

## Character

- The landing page displays Original Morrowind around Balmora across the viewport as a static backdrop beneath a smoky vignette.
- Map choices are two flat typographic rows without card containers, bevels, or decorative frames.
- The main interface uses warm near-black surfaces, sandy gold text, and thin brass dividers.
- The selected-place card resembles a separate page from an in-game journal: parchment, dark ink, a title, progress, and a personal note.
- Decoration does not imitate an operating system or technical console. Structural labels appear only when they help the user make a decision.

## Palette

| Token | Value | Purpose |
| --- | --- | --- |
| `--ui-void` | `#090806` | Canvas, map before loading, deep shadows |
| `--ui-panel` | `#1b1710` | Ledger, titlebar, and dark controls |
| `--ui-brass` | `#8c7344` | Hairline dividers and component boundaries |
| `--ui-gold` | `#d6b96f` | Main text and action accents on dark surfaces |
| `--book-paper` | `#d9c79c` | Selected-place page |
| `--book-ink` | `#241b10` | Text and controls on parchment |

`--ui-gold` has a contrast ratio of `10.51:1` against `--ui-void` and `9.37:1` against `--ui-panel`. `--book-ink` against `--book-paper` is `10.17:1`. `--ui-brass` is for structural boundaries, not small text.

Progress and personal markers retain a separate semantic palette:

| Kind | Color | Shape |
| --- | --- | --- |
| `unvisited` | `#f6e27d` | Thin hollow square |
| `active` | `#e88bea` | Thin hollow square |
| `visited` | `#e9a15b` | Thin hollow square |
| `custom` | `#78db78` | Thin hollow square |

Color is never the only way to convey meaning: the legend, filters, and progress controls include visible text, while selection uses `aria-pressed` and an additional border.

## Typography

All fonts ship as same-origin build assets.

| Role | Typeface | Use |
| --- | --- | --- |
| Display and book | Alegreya Variable `500–700` | Landing page, dataset/place names, titlebar, progress labels on parchment |
| UI and input | Atkinson Hyperlegible Next Variable `400–600` | Search, filters, buttons, notes, alerts |
| Diagnostics | IBM Plex Mono `400/500` | Actual IDs, error codes, and technical data |

IBM Plex Mono is not used for ordinary navigation or decorative labels. `Alegreya` is preloaded alongside the main UI font so the main heading does not change metrics after the first frame.

## Geometry

- Spacing grid: `4 / 8 / 12 / 16 / 24 / 32px`.
- Map titlebar: `46px`, with safe-area inset handling.
- Desktop ledger: `304px`; `284px` on medium viewports.
- Compact icon control: `32px`; a coarse pointer increases the hit area to `44×44px`.
- Place card: up to `376px`, with a single `1px` ochre boundary and no inset bevel or corner ornament.
- Elevation is reserved for actual overlays: the parchment card, runtime alerts, and import/export feedback.

## Landing backdrop

The tile mosaic uses a verified `3×3` coverage window at `z5` around Balmora, rendered by `.landing-map-backdrop__grid` with `--preview-columns` and `--preview-rows`. It uses only Original basemap tiles, without catalog labels. Tiles accept no pointer or keyboard input. Loading/fallback states do not change content geometry; the fallback remains a dark atmospheric canvas.

On hover/focus, a map-choice row gains only a subtle warm background and a stronger arrow. Transitions are disabled under `prefers-reduced-motion: reduce`.

## Map and overlays

Map layer order: basemap `0` → catalog markers `10` → labels `11` → personal markers `20`.

DOM overlay order: content `0–3` → controls `4` → legend `5` → ledger `6` → system states `7` → cards `8`. Any new level must be added as a named token.

Map controls use simple `+` and `−` symbols. Import/export sits on the right side of the titlebar as compact tray-and-arrow controls. Entrance and personal markers on the canvas are small, thin hollow squares; place labels are smaller than the main UI text and have no background plate or border. Lists, the legend, and editors preserve the same square semantics at sizes suitable for reading and interaction.

The initial camera after map selection uses `map.projection.center` from the manifest and the first catalog tier, `z=2`. For a selected `TR Mainland` region, it starts at Old Ebonheart at `z=4`. Valid `x/y/z` URL coordinates take precedence over defaults and region focus.

Catalog results appear in successive batches as the ledger scrolls. Batching affects only the number of DOM rows created: search, counters, markers, and filters continue to reflect the full set of matches.

Routine map-tile loading is visually silent: no status text, spinner, or overlay over the map. A visible system state appears only for missing coverage, a loading error, or an available retry; it does not reset the camera, filters, or selection.

## Responsive behavior and accessibility

- `1280×720`: full-viewport backdrop with choices on the left; the map uses a ledger and canvas.
- Up to `860px`: the ledger narrows to `284px`, and the parchment card stays at most `360px` wide.
- Up to `560px`: landing choices stack vertically across the available width; the ledger and map stage stack vertically; the place card uses the viewport width minus `16px`.
- Landscape up to `480px` high: the titlebar stays `46px`, and the ledger scrolls independently.
- Safe-area tokens apply to the titlebar, landing page, and overlays.

Keyboard focus always has a contrasting `2px` outline. With the map focused, arrow keys pan the viewport, `+`/`−` change zoom, and `M` cycles through saved personal markers. Touch flows do not depend on hover. Controls retain accessible names, disabled/busy semantics, and recovery actions. Errors remain `alert`; saving and loading datasets, catalogs, or user data use `status`. Individual tile requests are not announced as status updates. Overlays do not trap focus unless they are modal.
