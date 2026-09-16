# Transport catalogs

Run `python3 -m tools.transport_pipeline.build` from the repository root with the
existing ignored game inputs restored. The standard library is sufficient.

The builder reads the four active dataset manifests, verifies every enabled
plugin's SHA-256, merges placed references in load order, and derives directed
travel from the winning NPC and creature records. It writes only small derived
catalogs to `apps/web/src/transport/catalogs/`. These application resources are
bound to their exact spatial snapshot IDs; they do not mutate the immutable
dataset graph or require terrain rerendering. A changed snapshot must be reviewed
and regenerated before its transport overlay can be used.

`provider-labels.json` contains factual boarding-place labels from the four saved
UESP Transport pages reviewed on 2026-09-16. It supplies human-readable names where
the game places a carrier in an unnamed regional exterior cell, and disambiguates
boat operators who retain the generic riverstrider class. Route existence and
coordinates always come from the enabled game profile, not the wiki tables.
The supplied page fingerprints are recorded in `docs/TRANSPORT_OVERLAYS.md`.

## Geometry and review rules

- Exterior origins use the actual placed carrier coordinates. Interior guild
  origins and destinations follow the door graph to an exterior exit. A hall
  shared by guild guides is one stop with separate provider services.
- Nearby arrival points can share a boarding marker of the same service subtype:
  at most 2048 world units. Each route's `arrivalMatch` records the matching rule,
  distance and matched provider for review.
  Boat and waterstrider arrivals can share intercity docks; local gondolas stay
  separate. This is display normalization, not evidence of a new service. Each route keeps
  its exact three-dimensional `arrivalPosition` and optional `arrivalInterior`.
  The connection is schematic and does not describe a walking or sailing path.
- Every route retains its originating actor record and plugin. No reverse edge,
  transit connection or complete guild network is inferred.
- Deleted/unplaced/test actors and missing-plugin variants are omitted. Skyrim's
  Anvil-bound carrier and Cyrodiil's TR/Skyrim-dependent variants are excluded by
  reviewed script conditions. The disabled optional TR Factions plugin is not
  loaded. Active inter-province journeys retain external destinations; the UI
  should omit their map lines where the destination lies outside map coverage.
- Explicit quest/faction annotations cover Holamayan, Raven Rock, the Skyrim
  guild quest, TR's interregional guild guides, Firemoth and Indoril palanquins.
  These annotations do not simulate a savegame, generic service refusal,
  disposition, crime or whether the player has killed a carrier.
- Thazlorakis is a creature with travel services and is included. The two TR
  Skylamp carriers use the Caravaner class but are explicitly excluded from
  these land/water/guild networks. Special quest-only travel, intervention,
  propylons and other script-only travel are outside the current overlay.

The source catalogs' `review.excluded` and `review.notes` preserve coverage limits.
The saved wiki tables contain fewer TR routes and omit Cyrodiil gondolas; the
active plugin records determine the published network. Source data is read as
data only; no downloaded page or game script is executed.
