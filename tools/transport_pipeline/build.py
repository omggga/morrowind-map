"""Build travel catalogs without modifying the immutable spatial dataset graph.

Run from the repository root: python3 -m tools.transport_pipeline.build
Only derived travel records are written; game source files remain local.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections import defaultdict, deque
from pathlib import Path

from tools.catalog_pipeline.tes3 import CellKey, PluginInput, canonical_ref_id, merge_plugins
from tools.tes3.records import iter_records, iter_subrecords

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "local-data/inputs"
OUTPUT = ROOT / "apps/web/src/transport/catalogs"
PROFILES = {
    "original": "original-goty-hd",
    "tr": "poison-song-26.08",
    "sky": "dragonstar-26.09",
    "cyr": "abecean-shores-26.09",
}
PLUGIN_PATHS = {
    "Morrowind.esm": "bsa/Morrowind.esm",
    "Tribunal.esm": "bsa/Tribunal.esm",
    "Bloodmoon.esm": "bsa/Bloodmoon.esm",
    "Tamriel_Data.esm": "tamriel-data/Tamriel_Data.esm",
    "TR_Mainland.esm": "tamriel-rebuilt/00 Core/Data Files/TR_Mainland.esm",
    "Sky_Main.esm": "home-of-nords/00 Core/Sky_Main.esm",
    "Cyr_Main.esm": "project-cyrodiil/00 Core/Cyr_Main.esm",
}
REGIONS = {
    "Morrowind.esm": "vvardenfell", "Tribunal.esm": "vvardenfell",
    "Bloodmoon.esm": "solstheim", "TR_Mainland.esm": "tr-mainland",
    "Sky_Main.esm": "skyrim", "Cyr_Main.esm": "cyrodiil",
}
SOURCES = {
    "Morrowind.esm": "https://en.uesp.net/wiki/Morrowind:Transport",
    "Bloodmoon.esm": "https://en.uesp.net/wiki/Morrowind:Transport",
    "TR_Mainland.esm": "https://en.uesp.net/wiki/Tamriel_Rebuilt:Transport",
    "Sky_Main.esm": "https://en.uesp.net/wiki/Project_Tamriel:Skyrim/Transport",
    "Cyr_Main.esm": "https://en.uesp.net/wiki/Project_Tamriel:Cyrodiil/Transport",
}
CARAVANS = {"arvs themyn", "bolvin virenith", "derara ildram", "gilsi aryn", "vunal ralvayn"}
PROVIDER_LABELS = json.loads((Path(__file__).with_name("provider-labels.json")).read_text())
EXCLUDED = {
    "todd": "Development/test actor",
    "pc_m1_annineshotn": "Requires Sky_Main.esm, absent from the Cyrodiil profile",
    "pc_m1_kaltandoralistr": "Requires TR_Mainland.esm, absent from the Cyrodiil profile",
    "sky_xre_kw_cascus": "Requires Cyr_Main.esm, absent from the Skyrim profile",
    "tr_m4_nassuran omoril": "Special quest transport outside the three regular networks",
    "tr_m4_othrys rorivel": "Special quest transport outside the three regular networks",
    "tr_m7_relenu drolan": "Skylamp service, outside the three regular networks",
    "tr_m7_ulath-bael": "Skylamp service, outside the three regular networks",
}


def decode(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("cp1252")


def identity(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]


def load_actors(plugins: list[PluginInput]) -> dict:
    actors = {}
    for plugin in plugins:
        for record in iter_records(plugin.path):
            if record.record_type not in (b"NPC_", b"CREA") or record.flags & 0x1000:
                continue
            subs = list(iter_subrecords(record.payload))
            fields = {s.subrecord_type: s.payload for s in subs}
            key = canonical_ref_id(decode(fields[b"NAME"]))
            # A later complete record without travel also removes earlier travel.
            actors.pop(key, None)
            if b"DELE" in fields or b"DODT" not in fields:
                continue
            destinations = []
            for sub in subs:
                if sub.subrecord_type == b"DODT":
                    destinations.append({"position": struct.unpack("<6f", sub.payload)[:3], "cell": ""})
                elif sub.subrecord_type == b"DNAM" and destinations:
                    destinations[-1]["cell"] = decode(sub.payload)
            actors[key] = {
                "id": key, "name": decode(fields.get(b"FNAM", fields[b"NAME"])),
                "class": decode(fields.get(b"CNAM", b"")),
                "script": decode(fields.get(b"SCRI", b"")), "plugin": plugin.name,
                "destinations": destinations,
            }
    return actors


def classification(actor: dict) -> tuple[str, str] | None:
    cls = actor["class"].lower()
    reviewed = PROVIDER_LABELS.get(actor["name"].lower(), {}).get("section")
    if reviewed in ("Boat", "Vvardenfell Changes and Additions"):
        return "water", "Boat"
    if cls == "guild guide" or actor["id"] == "tr_m1_daedrothgindaman":
        return "guild", "Guild guide"
    if cls == "caravaner":
        return "land", ("Carriage" if actor["plugin"] in ("Sky_Main.esm", "Cyr_Main.esm")
                        else "Caravan" if actor["name"].lower() in CARAVANS else "Silt strider")
    if cls == "slave" and actor["script"] == "TR_m3_HI_FastTravelSlave":
        return "land", "Palanquin"
    if cls == "t_mw_riverstriderservice":
        return "water", "Waterstrider"
    if cls == "gondolier":
        return "water", "Gondola"
    if cls == "shipmaster" or actor["id"] in ("blatta hateria", "vevrana aryon", "rindral dralor", "tr_m3_torosi moren"):
        return "water", "Boat"
    return None


def conditions(actor: dict) -> list[str]:
    key = actor["id"]
    if key in ("blatta hateria", "vevrana aryon"):
        return ["Available after the main quest introduces travel to Holamayan."]
    if key == "veresa alver":
        return ["Requires Raven Rock colony progress (ColonyState 3 or later)."]
    if key == "wind_in_his_hair":
        return ["Quest-specific Solstheim service; availability depends on Bloodmoon progression."]
    if actor["script"].startswith("Sky_qRe_KWMG5_"):
        return ["Requires Turbulent Teleporting (journal stage 120 or later, excluding the failed stage 130)."]
    if actor["script"] == "TR_m3_HI_FastTravelSlave":
        return ["House Indoril membership required.", "Unavailable after this carrier is freed."]
    if key in ("tr_m0_ohmonir", "tr_m1_daedrothgindaman", "tr_m3_barabus inclodios", "tr_m7_lissinia bax"):
        return ["Mages Guild rank Conjurer or higher required for interregional travel."]
    if actor["script"] == "TR_FM_NPC_Stage3_sc":
        return ["Available after Firemoth progression reaches stage 3."]
    return []


def build(profile: str, dataset_id: str) -> dict:
    manifest = json.loads((ROOT / f"apps/web/public/datasets/manifests/{dataset_id}.json").read_text())
    plugins = []
    for entry in sorted((entry for entry in manifest["profile"]["contentFiles"] if entry["enabled"]), key=lambda entry: entry["loadOrder"]):
        path = INPUTS / PLUGIN_PATHS[entry["name"]]
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"Source hash differs from active profile: {entry['name']}")
        plugins.append(PluginInput(entry["name"], path, digest))
    world = merge_plugins(plugins)
    actors = load_actors(plugins)
    refs = [r for r in world.references.values() if not r.deleted and r.position is not None]
    by_actor = defaultdict(list)
    doors = defaultdict(list)
    for ref in refs:
        by_actor[canonical_ref_id(ref.base_id)].append(ref)
        if ref.door_destination is not None and canonical_ref_id(ref.base_id) in world.doors:
            doors[ref.effective_cell].append(ref)
    visible_regions = {r["id"] for r in manifest["regions"]}
    excluded = []
    anchor_cache = {}

    def anchor(cell: CellKey, position: tuple) -> tuple | None:
        if cell.kind == "exterior":
            return position[:2], cell
        if cell in anchor_cache:
            return anchor_cache[cell]
        queue = deque([(cell, position, 0)])
        seen = set()
        result = None
        while queue:
            current, current_position, depth = queue.popleft()
            if current in seen or depth > 8:
                continue
            seen.add(current)
            options = sorted(doors[current], key=lambda r: (math.dist(r.position, current_position), r.key))
            for door in options:
                dest = door.door_destination
                if not door.destination_cell:
                    result = (dest[:2], CellKey.exterior(math.floor(dest[0] / 8192), math.floor(dest[1] / 8192)))
                    break
                queue.append((CellKey.interior(door.destination_cell), dest, depth + 1))
            if result:
                break
        anchor_cache[cell] = result
        return result

    def region(cell: CellKey) -> str:
        found = world.cells.get(cell)
        return REGIONS.get(found.first_plugin, "tr-mainland") if found else "unknown"

    def cell_name(cell: CellKey) -> str:
        found = world.cells.get(cell)
        return re.sub(r"^Solstheim,\s*", "", (found.name or found.region) if found else "External destination")

    providers = []
    stops = {}
    for key, actor in sorted(actors.items()):
        if key in EXCLUDED:
            excluded.append(f"{actor['name']}: {EXCLUDED[key]}")
            continue
        actor_refs = by_actor.get(key, [])
        if not actor_refs:
            excluded.append(f"{actor['name']}: no effective placement")
            continue
        mode = classification(actor)
        if not mode:
            excluded.append(f"{actor['name']}: unclassified service")
            continue
        for ref in actor_refs:
            point = anchor(ref.effective_cell, ref.position)
            if point is None:
                excluded.append(f"{actor['name']}: no exterior door anchor")
                continue
            xy, exterior = point
            # Guild guides sharing a hall share a stop; other services retain boarding points.
            sid = "stop-" + identity(ref.effective_cell.identity if mode[0] == "guild" else key,
                                     mode[0], ref.effective_cell.identity,
                                     "hall" if mode[0] == "guild" else ref.key.local_index)
            stop = {"id": sid, "name": cell_name(ref.effective_cell),
                    "position": [round(v, 3) for v in xy], "regionId": region(exterior)}
            label = PROVIDER_LABELS.get(actor["name"].lower(), {}).get("origin")
            if label and (not stop["name"] or "Region" in stop["name"]):
                stop["name"] = label
            if ref.effective_cell.kind == "interior":
                stop["interior"] = world.cells[ref.effective_cell].name
            if stop["regionId"] not in visible_regions:
                stop["external"] = True
            stops[sid] = stop
            providers.append((actor, ref, mode, sid))

    routes = []
    for actor, ref, mode, sid in providers:
        for index, destination in enumerate(actor["destinations"]):
            pos = destination["position"]
            cell = CellKey.interior(destination["cell"]) if destination["cell"] else CellKey.exterior(math.floor(pos[0] / 8192), math.floor(pos[1] / 8192))
            point = anchor(cell, pos)
            if point is None:
                excluded.append(f"{actor['name']} destination {index + 1}: no exterior door anchor")
                continue
            xy, exterior = point
            # Boats and waterstriders share intercity docks; local gondolas remain separate.
            candidates = [(math.dist(p[1].position, pos), p) for p in providers
                          if (p[1].effective_cell == cell or
                              (cell.kind == "exterior" and p[1].effective_cell.kind == "exterior"
                               and (stops[p[3]]["name"] == cell_name(cell)
                                    or math.dist(p[1].position, pos) <= 2048)))
                          and (p[2] == mode or
                               (p[2][1] in ("Boat", "Waterstrider") and mode[1] in ("Boat", "Waterstrider")))]
            candidates.sort(key=lambda p: (p[0], p[1][3]))
            if candidates and (cell.kind == "interior" or candidates[0][0] <= 2048):
                target = candidates[0][1][3]
                matched_ref = candidates[0][1][1]
                match = {
                    "kind": "same-interior" if cell.kind == "interior" else
                    "same-cell" if matched_ref.effective_cell == cell else
                    "same-settlement" if stops[target]["name"] == cell_name(cell) else "nearby-boarding-point",
                    "distance": round(candidates[0][0], 3),
                    "provider": candidates[0][1][0]["name"],
                }
            else:
                target = "arrival-" + identity(cell.identity, *[round(v, 3) for v in pos], mode[1])
                match = {"kind": "exact-arrival", "distance": 0}
                stops[target] = {"id": target, "name": cell_name(cell), "position": [round(v, 3) for v in xy], "regionId": region(exterior)}
                if cell.kind == "interior":
                    stops[target]["interior"] = world.cells[cell].name
                if stops[target]["regionId"] not in visible_regions:
                    stops[target]["external"] = True
            if sid == target or (stops[sid].get("external") and stops[target].get("external")):
                continue
            routes.append({"id": "route-" + identity(sid, actor["id"], index), "from": sid, "to": target,
                           "mode": mode[0], "subtype": mode[1], "provider": actor["name"],
                           "conditions": conditions(actor), "source": SOURCES[actor["plugin"]],
                           "sourceRecord": actor["id"], "sourcePlugin": actor["plugin"],
                           "arrivalMatch": match,
                           "arrivalPosition": [round(v, 3) for v in pos],
                           **({"arrivalInterior": destination["cell"]} if destination["cell"] else {})})
    used = {r[end] for r in routes for end in ("from", "to")}
    return {"schemaVersion": 1, "datasetId": dataset_id, "snapshotId": manifest["snapshotId"],
            "sourcePlugins": [{"name": p.name, "sha256": p.sha256} for p in plugins],
            "stops": sorted((s for key, s in stops.items() if key in used), key=lambda s: s["id"]),
            "routes": sorted(routes, key=lambda r: r["id"]),
            "review": {"excluded": sorted(set(excluded)), "notes": [
                "Directed travel comes from effective NPC/creature DODT records; reverse services are never inferred.",
                "Interior display anchors follow teleport doors to the exterior; exact arrival coordinates are preserved on routes.",
                "Exterior arrival points share a compatible boarding marker within 2048 world units; exact arrivalPosition and arrivalMatch preserve the difference and matching evidence. Boats/waterstriders share intercity docks; local gondolas are separate.",
                "Services requiring absent optional plugins are excluded. External stops are retained as destinations without map lines.",
                "Quest and faction requirements are reviewed annotations, not live player-state checks.",
                "Skylamps, propylons, intervention spells and other script-only travel are outside these three service groups.",
            ]}}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for profile, dataset in PROFILES.items():
        data = build(profile, dataset)
        (OUTPUT / f"{profile}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        print(f"{profile}: {len(data['stops'])} stops, {len(data['routes'])} directed routes, {len(data['review']['excluded'])} exclusions", flush=True)


if __name__ == "__main__":
    main()
