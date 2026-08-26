from __future__ import annotations

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


def _parse_blocks(lines: Iterable[str], block_name: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if line == block_name:
            if current is not None:
                raise ValueError(f"Nested {block_name!r} block")
            current = {}
            continue
        if line == "end":
            if current is not None:
                blocks.append(current)
                current = None
            continue
        if current is not None and "=" in line:
            key, value = line.split("=", 1)
            current[key.strip()] = value.strip()

    if current is not None:
        raise ValueError(f"Unterminated {block_name!r} block")
    return blocks


def parse_mim_locations(path: Path) -> list[MimLocation]:
    text = path.read_text(encoding="cp1251")
    locations: list[MimLocation] = []

    for index, fields in enumerate(_parse_blocks(text.splitlines(), "loc")):
        try:
            x_text, y_text = fields["pd"].split(",", 1)
            locations.append(
                MimLocation(
                    index=index,
                    name=fields["nm"],
                    category=int(fields["pc"]),
                    detail_level=int(fields["dl"]),
                    position=(float(x_text), float(y_text)),
                )
            )
        except (KeyError, ValueError) as error:
            raise ValueError(f"Invalid loc block {index} in {path}") from error

    return locations


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
