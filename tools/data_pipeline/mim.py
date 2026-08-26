from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class MimLocation:
    index: int
    name: str
    category: int
    detail_level: int
    position: tuple[float, float]
    source_name: str | None = None


@dataclass(frozen=True)
class MimProgress:
    index: int
    name: str
    status: str
    note: str


@dataclass(frozen=True)
class MimMarker:
    index: int
    text: str
    position: tuple[int, int]


MIM_CATEGORY_TYPES = {
    10: "guild",
    11: "temple",
    19: "settlement",
    20: "house",
    21: "mine",
    22: "ship",
    23: "shrine",
    24: "ancestral-tomb",
    25: "stronghold",
    26: "shop",
    27: "dwemer-ruin",
    28: "stronghold",
    29: "cave",
}

MIM_STATUS_NAMES = {
    "1": "unvisited",
    "2": "active",
    "3": "visited",
}

MIM_LOCATION_FIELDS = {"nm", "pc", "lt", "dl", "np", "ps", "pd", "pt"}
MIM_PROGRESS_FIELDS = {"nm", "status", "note"}
MIM_MARKER_FIELDS = {"text", "pos"}
INTEGER_POINT = re.compile(r"^[+-]?\d+\s*,\s*[+-]?\d+$")


def _read_cp1251(path: Path) -> str:
    try:
        return path.read_bytes().decode("cp1251", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError(f"Invalid CP1251 in {path} at byte {error.start}") from error


def _parse_blocks(
    lines: Iterable[str],
    block_name: str,
    *,
    source: Path | None = None,
    required_fields: set[str] | None = None,
    allowed_fields: set[str] | None = None,
) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if current is None and not line:
            continue
        if line == block_name:
            if current is not None:
                raise ValueError(
                    f"Nested {block_name!r} block at line {line_number} in {source}"
                )
            current = {}
            continue
        if line == "end":
            if current is None:
                raise ValueError(f"Unexpected end at line {line_number} in {source}")
            missing = (required_fields or set()) - current.keys()
            if missing:
                fields = ", ".join(sorted(missing))
                raise ValueError(
                    f"Missing {fields} in {block_name!r} block {len(blocks)} in {source}"
                )
            blocks.append(current)
            current = None
            continue
        if current is None:
            raise ValueError(f"Unexpected line {line_number} in {source}: {raw_line!r}")
        if not line or "=" not in raw_line:
            raise ValueError(
                f"Invalid field at line {line_number} in {source}: {raw_line!r}"
            )
        key_text, value = raw_line.lstrip(" \t").split("=", 1)
        key = key_text.strip()
        if allowed_fields is not None and key not in allowed_fields:
            raise ValueError(
                f"Unknown field {key!r} at line {line_number} in {source}"
            )
        if key in current:
            raise ValueError(
                f"Duplicate field {key!r} at line {line_number} in {source}"
            )
        if value.startswith(" "):
            value = value[1:]
        current[key] = value

    if current is not None:
        raise ValueError(f"Unterminated {block_name!r} block in {source}")
    return blocks


def _parse_integer_point(value: str, field: str, index: int, path: Path) -> tuple[int, int]:
    normalized = value.strip()
    if INTEGER_POINT.fullmatch(normalized) is None:
        raise ValueError(f"Invalid {field} in block {index} in {path}: {value!r}")
    x_text, y_text = normalized.split(",", 1)
    return int(x_text), int(y_text)


def parse_mim_locations(path: Path) -> list[MimLocation]:
    text = _read_cp1251(path)
    locations: list[MimLocation] = []

    blocks = _parse_blocks(
        text.splitlines(),
        "loc",
        source=path,
        required_fields={"nm", "pc", "dl", "pd"},
        allowed_fields=MIM_LOCATION_FIELDS,
    )
    for index, fields in enumerate(blocks):
        try:
            x, y = _parse_integer_point(fields["pd"], "pd", index, path)
            source_name = fields["nm"]
            locations.append(
                MimLocation(
                    index=index,
                    name=source_name.strip(),
                    category=int(fields["pc"].strip()),
                    detail_level=int(fields["dl"].strip()),
                    position=(float(x), float(y)),
                    source_name=source_name,
                )
            )
        except (KeyError, ValueError) as error:
            raise ValueError(f"Invalid loc block {index} in {path}") from error

    return locations


def parse_mim_progress(path: Path) -> list[MimProgress]:
    text = _read_cp1251(path)
    blocks = _parse_blocks(
        text.splitlines(),
        "loc",
        source=path,
        required_fields=MIM_PROGRESS_FIELDS,
        allowed_fields=MIM_PROGRESS_FIELDS,
    )
    progress: list[MimProgress] = []
    for index, fields in enumerate(blocks):
        status_value = fields["status"].strip()
        if status_value not in MIM_STATUS_NAMES:
            raise ValueError(
                f"Invalid status in block {index} in {path}: {fields['status']!r}"
            )
        progress.append(
            MimProgress(
                index=index,
                name=fields["nm"],
                status=MIM_STATUS_NAMES[status_value],
                note=fields["note"],
            )
        )
    return progress


def parse_mim_markers(path: Path) -> list[MimMarker]:
    text = _read_cp1251(path)
    blocks = _parse_blocks(
        text.splitlines(),
        "marker",
        source=path,
        required_fields=MIM_MARKER_FIELDS,
        allowed_fields=MIM_MARKER_FIELDS,
    )
    markers: list[MimMarker] = []
    for index, fields in enumerate(blocks):
        if not fields["text"].strip():
            raise ValueError(f"Empty marker text in block {index} in {path}")
        markers.append(
            MimMarker(
                index=index,
                text=fields["text"],
                position=_parse_integer_point(fields["pos"], "pos", index, path),
            )
        )
    return markers


def match_mim_progress(
    region_id: str,
    locations: list[MimLocation],
    progress: list[MimProgress],
) -> list[tuple[MimLocation, MimProgress]]:
    if len(locations) != len(progress):
        raise ValueError(
            f"MIM {region_id} progress count mismatch: "
            f"mwmain has {len(locations)}, user has {len(progress)}"
        )

    matches: list[tuple[MimLocation, MimProgress]] = []
    for ordinal, (location, record) in enumerate(zip(locations, progress, strict=True)):
        expected_name = location.source_name if location.source_name is not None else location.name
        if expected_name != record.name:
            raise ValueError(
                f"MIM {region_id} name mismatch at ordinal {ordinal}: "
                f"mwmain has {expected_name!r}, user has {record.name!r}"
            )
        matches.append((location, record))
    return matches


def classify_place(category: int | None, name: str) -> str:
    if category in MIM_CATEGORY_TYPES:
        return MIM_CATEGORY_TYPES[category]

    folded = name.casefold().replace("ё", "е")
    keyword_types = (
        (("guild", "гильд"), "guild"),
        (("ancestral tomb", "barrow", "tomb", "гробниц", "курган", "могил"), "ancestral-tomb"),
        (("mine", "шахт"), "mine"),
        (("ship", "wreck", "кораб", "судн"), "ship"),
        (("shrine", "altar", "stone", "святилищ", "алтар", "камень"), "shrine"),
        (("fort", "stronghold", "крепост", "форт"), "stronghold"),
        (("dwemer", "arkng", "bthu", "nch", "двемер", "аркн"), "dwemer-ruin"),
        (("house", "hut", "lodge", "дом", "хижин", "жилищ"), "house"),
        (("shop", "trader", "smith", "лавк", "торгов", "кузнец"), "shop"),
        (("temple", "chapel", "храм", "часовн"), "temple"),
        (("village", "camp", "посел", "лагер"), "settlement"),
        (("cave", "cavern", "grotto", "lair", "пещер", "грот"), "cave"),
    )
    for keywords, place_type in keyword_types:
        if any(keyword in folded for keyword in keywords):
            return place_type
    return "other"
