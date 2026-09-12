# Changelog

## 2026-09-12

- Changed personal notes and marker edits to save only with Save, preserving recoverable drafts without interrupting typing.
- Aligned personal marker actions with Delete on the left and Save consistently on the right in both note forms, and removed coordinates from the marker card header.
- Show personal marker squares and names from zoom level 2 onward, hiding both below level 2, and limit new or renamed markers to 100 characters.
- Add a copy-link action beside place names, centering shared links on the place at the current zoom and highlighting the selected place with a larger cyan marker and matching label.
- Use a pointer cursor for the copy-link action and dismiss its success or error message after five seconds with a fade-out.
- Raise hovered and selected place labels above other map labels. Show a 30%-transparent background only while hovering the label text or place square, excluding background padding from hover and click targets.
- Extend map zoom to z9 using existing tiles, preserving zoom levels through z8 and adding one 2× magnification step for crowded locations without rerendering maps. Always show all place labels from z8 onward, including overlapping labels.
