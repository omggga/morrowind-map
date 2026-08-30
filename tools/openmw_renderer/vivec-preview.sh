#!/usr/bin/env bash
set -euo pipefail

preview_root="${1:-local-data/openmw-production/poison-song-26.08-v4-vivec-smoke-final}"
tile_root="${preview_root}/tiles/7"
output="${2:-${preview_root}/vivec-v4-preview.png}"

tiles=(
  "${tile_root}/30/44.webp"
  "${tile_root}/31/44.webp"
  "${tile_root}/32/44.webp"
  "${tile_root}/30/45.webp"
  "${tile_root}/31/45.webp"
  "${tile_root}/32/45.webp"
  "${tile_root}/30/46.webp"
  "${tile_root}/31/46.webp"
  "${tile_root}/32/46.webp"
)

for tile in "${tiles[@]}"; do
  if [[ ! -f "${tile}" ]]; then
    printf 'Missing Vivec smoke tile: %s\n' "${tile}" >&2
    exit 1
  fi
done

magick -size 1536x1536 canvas:none \
  "${tiles[0]}" -geometry +0+0 -composite \
  "${tiles[1]}" -geometry +512+0 -composite \
  "${tiles[2]}" -geometry +1024+0 -composite \
  "${tiles[3]}" -geometry +0+512 -composite \
  "${tiles[4]}" -geometry +512+512 -composite \
  "${tiles[5]}" -geometry +1024+512 -composite \
  "${tiles[6]}" -geometry +0+1024 -composite \
  "${tiles[7]}" -geometry +512+1024 -composite \
  "${tiles[8]}" -geometry +1024+1024 -composite \
  -strip \
  "${output}"

magick identify "${output}"
