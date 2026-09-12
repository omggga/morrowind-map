# Changelog

## 2026-09-12

- Keep every marker shape at its normal size when hovered or selected, preserving label backgrounds and color highlighting. Keep wiki-link generation tools and maintainer documentation local.
- Link place-card titles to UESP in a new tab, with an underline on hover or keyboard focus. Match four saved UESP catalogs by source cell IDs, names and nearby entrances, including the dedicated Morrowind catalog for base-game regions in TR. Generate direct article URLs from full place names and map namespaces for unmatched places, and keep Azurian Isles titles unlinked.
- Make screenshot comparisons opt-in and check keyboard reachability without requiring an exact Tab sequence, keeping functional and accessibility checks in CI.
- Changed personal notes and marker edits to save only with Save, preserving recoverable drafts without interrupting typing.
- Aligned personal marker actions with Delete on the left and Save consistently on the right in both note forms, and removed coordinates from the marker card header.
- Show personal marker squares and names from zoom level 2 onward, hiding both below level 2, and limit new or renamed markers to 100 characters.
- Add a copy-link action beside place names, centering shared links on the place at the current zoom and highlighting the selected place with a cyan marker and matching label.
- Use a pointer cursor for the copy-link action and dismiss its success or error message after five seconds with a fade-out.
- Raise hovered and selected place labels above other map labels. Show a 30%-transparent background only while hovering the label text or place square, excluding background padding from hover and click targets.
- Extend map zoom to z9 using existing tiles, preserving zoom levels through z8 and adding one 2× magnification step for crowded locations without rerendering maps. Always show all place labels from z8 onward, including overlapping labels.
- Snap map zoom to whole levels after clicks, taps, wheel and pinch gestures, reaching z9 consistently and opening fractional-zoom links at the nearest available scale.
- Hide Filters and Map section controls on compact layouts up to 860px and devices with a primary coarse pointer and no hover, including landscape phones and tablets.
- Add Map settings beside Import/Export with a saved colorblind-friendly status palette based on Okabe–Ito blue and orange. Apply it immediately to markers, labels, results, legends and place cards.
- Add distinct shapes in colorblind-friendly mode: white squares for unvisited places, blue diamonds for active places, orange circles for visited places, and reddish-purple triangles for personal markers, including their labels and previews.
- Give personal marker labels the same translucent hover background and text-only hit bounds as place labels. Keep marker sizes unchanged on hover and show Saved feedback only for note edits, without flicker when changing place status.
- Dismiss the JSON backup download confirmation after five seconds with a fade-out, restarting the timeout on each successful export.
