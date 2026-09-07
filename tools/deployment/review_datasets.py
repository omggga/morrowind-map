"""Review verified public dataset trees as data, without executing either tree.

Run this module from a trusted checkout. Public roots may be untrusted snapshots;
only reachable JSON, NDJSON, and image bytes are read. No game inputs are needed.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

from tools.deployment.common import (
    DeploymentError, canonical_json_bytes, relative_public_path, require_mapping,
    require_sequence, require_string, safe_file, sha256_bytes, strict_json_object,
)
from tools.deployment.upload_datasets import build_dataset_plan

MAX_PREVIEW_LIMIT = 200
MAX_IMAGE_BYTES = 64 * 1024 * 1024


def _read(root: Path, url: str) -> dict[str, Any]:
    return strict_json_object(safe_file(root, relative_public_path(url), url).read_bytes(), url)


def _snapshot(root: Path) -> dict[str, Any]:
    plan = build_dataset_plan(public_root=root)
    files = {record['path']: record for record in plan['files']}
    datasets = {}
    for item in plan['datasets']:
        dataset_id = item['datasetId']
        manifest = _read(root, item['manifest']['url'])
        catalog = _read(root, manifest['artifacts']['locations']['url'])
        places = {}
        for raw in require_sequence(catalog.get('places'), 'catalog.places'):
            place = dict(require_mapping(raw, 'place'))
            identity = require_string(place.get('id'), 'place.id')
            if identity in places:
                raise DeploymentError(f'Duplicate place ID in {dataset_id}: {identity}')
            places[identity] = {**place, 'locales': {}}
        seen_locales = set()
        for url in item['localeArtifacts']:
            locale = _read(root, url)
            locale_id = require_string(locale.get('locale'), 'locale')
            if locale_id in seen_locales:
                raise DeploymentError(f'Duplicate locale in {dataset_id}: {locale_id}')
            seen_locales.add(locale_id)
            seen_places = set()
            for raw in require_sequence(locale.get('places'), 'locale.places'):
                translation = dict(require_mapping(raw, 'localized place'))
                identity = require_string(translation.get('placeId'), 'localized place.placeId')
                if identity not in places or identity in seen_places:
                    raise DeploymentError(f'Unknown or duplicate localized place: {identity}')
                seen_places.add(identity)
                places[identity]['locales'][locale_id] = translation
        tiles = {}
        for pyramid in item['tilePyramids']:
            inventory_url = str(Path(pyramid['qualityReport']['url']).with_name('tiles.ndjson'))
            inventory = safe_file(root, relative_public_path(inventory_url), 'tile inventory')
            with inventory.open('rb') as stream:
                for line in stream:
                    tile = strict_json_object(line, 'tile')
                    key = (tile['z'], tile['x'], tile['y'])
                    url = pyramid['urlTemplate'].format(z=key[0], x=key[1], y=key[2])
                    record = files[url.removeprefix('/datasets/generated/')]
                    value = {'url': url, 'sha256': record['sha256'], 'bytes': record['bytes']}
                    if key in tiles and tiles[key] != value:
                        raise DeploymentError(f'Ambiguous tile coordinate in {dataset_id}: {key}')
                    tiles[key] = value
        datasets[dataset_id] = {'manifest': manifest, 'plan': item, 'places': places, 'tiles': tiles}
    index = safe_file(root, Path('datasets/index.json'), 'dataset index').read_bytes()
    return {'datasets': datasets, 'graphSha256': plan['graphSha256'], 'indexSha256': sha256_bytes(index),
            'fileCount': plan['fileCount'], 'totalBytes': plan['totalBytes']}


def _pairs(before: dict, after: dict) -> list[tuple[str | None, str | None, str]]:
    pairs = [(key, key, 'datasetId') for key in sorted(before.keys() & after.keys())]
    left, right = set(before) - set(after), set(after) - set(before)
    # A recognized mapKey is a stable product identity. Match only when unique
    # across the entire snapshot, including datasets already paired by exact ID.
    for map_key in ('original', 'tamriel-rebuilt', 'project-cyrodiil', 'home-of-nords'):
        old = [key for key, value in before.items() if value['manifest'].get('mapKey') == map_key]
        new = [key for key, value in after.items() if value['manifest'].get('mapKey') == map_key]
        if len(old) == len(new) == 1 and old[0] in left and new[0] in right:
            pairs.append((old[0], new[0], 'unique-mapKey'))
            left.remove(old[0]); right.remove(new[0])
    pairs += [(key, None, 'unmatched-or-ambiguous') for key in sorted(left)]
    pairs += [(None, key, 'unmatched-or-ambiguous') for key in sorted(right)]
    return pairs


def _normalize_place(value: Any, dataset_id: str, field: str = '') -> Any:
    if isinstance(value, dict):
        return {key: _normalize_place(item, dataset_id, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_place(item, dataset_id, field) for item in value]
    if field in ('id', 'placeId') and isinstance(value, str):
        return value.removeprefix(dataset_id + '.')
    return value


def _places(dataset: dict | None, dataset_id: str | None) -> dict:
    result = {}
    for identity, value in (dataset or {}).get('places', {}).items():
        key = identity.removeprefix(str(dataset_id) + '.')
        if key in result:
            raise DeploymentError(f'Ambiguous normalized place identity: {key}')
        result[key] = value
    return result


def _source(snapshot: dict | None, sha: str | None) -> dict | None:
    if snapshot is None:
        return None
    return {'sha': sha, **{key: snapshot[key] for key in ('graphSha256', 'indexSha256', 'fileCount', 'totalBytes')}}


def _status(before: Any, after: Any) -> str:
    return 'added' if before is None else 'removed' if after is None else 'changed'


def _short_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) > 8000:
        text = text[:8000] + '\n… [preview truncated; full record in summary.json]'
    return html.escape(text)


def _gallery(summary: dict) -> str:
    escape = html.escape
    preview = summary['preview']
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             '<title>Dataset change review</title><style>body{font:16px system-ui;margin:24px auto;padding:0 24px;max-width:1200px;background:#f7f4ed;color:#23221f}h1{margin:0 0 8px;font-size:28px}h2{margin:24px 0 12px;font-size:22px}h3{margin:0 0 12px;font-size:17px;overflow-wrap:anywhere}h4{margin:0 0 8px}p{margin:8px 0;line-height:1.5}article{background:white;padding:16px;margin:12px 0;border:1px solid #ccc;border-radius:6px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pair>div{min-width:0}img{display:block;width:100%;max-height:512px;object-fit:contain;background:#ddd}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.muted{color:#625e54;font-size:14px}a{color:#235c78}table{border-collapse:collapse;background:white;width:100%;margin:12px 0}th,td{text-align:right;padding:9px 14px;border-bottom:1px solid #dedbd3;font-variant-numeric:tabular-nums}th:first-child,td:first-child{text-align:left}thead{font-size:13px;color:#625e54}details{margin:8px 0}summary{cursor:pointer;color:#235c78}.dataset{display:inline-block;background:#e7e2d7;padding:4px 9px;border-radius:4px;margin:3px 6px 3px 0;font-size:14px}.empty{padding:24px;background:#f1eee8;color:#625e54}@media(max-width:600px){body{padding:0 12px}.pair{grid-template-columns:1fr}th,td{padding:8px 5px}}</style><body>',
             '<h1>Dataset change review</h1>']
    sources = []
    for key, label in [('base', 'Base'), ('candidate', 'Candidate')]:
        source = summary[key]
        sha = source.get('sha') if source else None
        value = escape(sha[:12]) if sha else 'bootstrap' if source is None else 'not supplied'
        sources.append(label + ': <a href="#provenance" title="' + escape(sha or value, quote=True) + '"><code>' + value + '</code></a>')
    parts.append('<p class="muted">' + ' &rarr; '.join(sources) + ' &nbsp;·&nbsp; <a href="summary.json">Download all changes (JSON)</a></p>')
    parts.append('<table aria-label="Actual change counts"><thead><tr><th>Actual totals</th><th>Added</th><th>Changed</th><th>Removed</th><th>Unchanged</th></tr></thead><tbody>')
    for kind, label in [('tiles', 'Tiles'), ('places', 'Places')]:
        parts.append('<tr><th scope="row">' + label + '</th>' + ''.join('<td>' + format(summary['counts'][kind][status], ',') + '</td>' for status in ('added', 'changed', 'removed', 'unchanged')) + '</tr>')
    parts.append('</tbody></table><p>')
    for dataset in summary['datasets']:
        old, new = dataset['beforeDatasetId'], dataset['afterDatasetId']
        label = f'{old} → {new}' if old and new and old != new else new or old
        parts.append('<span class="dataset">' + escape(label) + '</span>')
    parts.append('</p><p class="muted">Preview: ' + str(preview['tilesShown']) + ' of ' + str(len(summary['tileChanges'])) + ' tile changes; ' + str(preview['placesShown']) + ' of ' + str(len(summary['placeChanges'])) + ' place changes. First ' + str(preview['limit']) + ' per category, in deterministic dataset/coordinate/ID order. All changes are in JSON; copied images are capped at ' + str(MAX_IMAGE_BYTES // (1024 * 1024)) + ' MiB.</p>')
    parts.append('<details id="provenance"><summary>Source hashes, dataset matching, and preview limits</summary><p class="muted">Verified artifact hashes; input trees were read as data. Source commit labels are supplied by the caller.</p><h3>Sources</h3><pre>' + _short_json({'base': summary['base'], 'candidate': summary['candidate']}) + '</pre><h3>Dataset matching</h3><pre>' + _short_json(summary['datasets']) + '</pre><h3>Preview limits</h3><pre>' + _short_json(preview) + '</pre></details><h2>Tile changes</h2>')
    if not summary['tileChanges']:
        parts.append('<p class="muted">No tile changes.</p>')
    for change in summary['tileChanges'][:preview['limit']]:
        label = f"{change['dataset']} · {change['z']}/{change['x']}/{change['y']} · {change['status']}"
        parts.append('<article><h3>' + escape(label) + '</h3><div class="pair">')
        for side, title in [('before', 'Before'), ('after', 'After')]:
            tile = change[side]
            parts.append('<div><h4>' + title + '</h4>')
            if tile and tile.get('previewImage'):
                parts.append('<img loading="lazy" src="' + escape(tile['previewImage'], quote=True) + '" alt="' + title + ' tile">')
            else:
                parts.append('<p class="empty">' + escape(tile.get('previewOmitted', 'Absent') if tile else 'Absent') + '</p>')
            parts.append('</div>')
        parts.append('</div><details><summary>Tile paths and SHA-256 hashes</summary><pre>' + _short_json({'before': change['before'], 'after': change['after']}) + '</pre></details></article>')
    parts.append('<h2>Place changes (including localized names)</h2>')
    if not summary['placeChanges']:
        parts.append('<p class="muted">No place changes.</p>')
    for change in summary['placeChanges'][:preview['limit']]:
        parts.append('<article><h3>' + escape(f"{change['dataset']} · {change['placeId']} · {change['status']}") + '</h3><p>Changed fields: ' + escape(', '.join(change['changedFields'])) + '</p><div class="pair"><div><h4>Before</h4><pre>' + _short_json(change['before']) + '</pre></div><div><h4>After</h4><pre>' + _short_json(change['after']) + '</pre></div></div></article>')
    parts.append('</body></html>')
    return '\n'.join(parts)


def review_datasets(*, candidate_public_root: Path, output_dir: Path,
                    base_public_root: Path | None = None, base_sha: str | None = None,
                    candidate_sha: str | None = None, preview_limit: int = 100) -> dict[str, Any]:
    if not 1 <= preview_limit <= MAX_PREVIEW_LIMIT:
        raise DeploymentError(f'preview-limit must be between 1 and {MAX_PREVIEW_LIMIT}')
    for label, sha in [('base-sha', base_sha), ('candidate-sha', candidate_sha)]:
        if sha is not None and re.fullmatch(r'(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})', sha) is None:
            raise DeploymentError(f'{label} must be a full Git object ID')
    if base_sha and base_public_root is None:
        raise DeploymentError('base-sha requires base-public-root')
    roots = {'after': candidate_public_root.absolute(), 'before': base_public_root.absolute() if base_public_root else None}
    output = output_dir.absolute()
    for root in roots.values():
        if root and (output.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(output.resolve())):
            raise DeploymentError('output-dir must be separate from input trees')
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise DeploymentError('output-dir must be absent or an empty real directory')
    base = _snapshot(roots['before']) if roots['before'] else None
    candidate = _snapshot(roots['after'])
    old, new = (base or {}).get('datasets', {}), candidate['datasets']
    summary: dict[str, Any] = {'schemaVersion': 1, 'bootstrap': base is None, 'base': _source(base, base_sha),
        'candidate': _source(candidate, candidate_sha), 'datasets': [], 'tileChanges': [], 'placeChanges': [],
        'counts': {kind: dict.fromkeys(('added', 'removed', 'changed', 'unchanged'), 0) for kind in ('tiles', 'places')},
        'preview': {'limit': preview_limit, 'imageByteLimit': MAX_IMAGE_BYTES}}
    for old_id, new_id, reason in _pairs(old, new):
        before, after = old.get(old_id), new.get(new_id)
        identity = new_id or old_id
        dataset = {'dataset': identity, 'beforeDatasetId': old_id, 'afterDatasetId': new_id, 'matchReason': reason}
        for side, value in [('before', before), ('after', after)]:
            dataset[side] = None if value is None else {'manifest': value['plan']['manifest'], 'mapKey': value['manifest'].get('mapKey'),
                'release': value['manifest'].get('release'), 'snapshotId': value['manifest'].get('snapshotId'),
                'tileCount': len(value['tiles']), 'placeCount': len(value['places']), 'staticRasters': value['plan']['staticRasters']}
        dataset['mapDefinitionChanged'] = bool(before and after and before['manifest'].get('map') != after['manifest'].get('map'))
        summary['datasets'].append(dataset)
        old_tiles, new_tiles = (before or {}).get('tiles', {}), (after or {}).get('tiles', {})
        for key in sorted(old_tiles.keys() | new_tiles.keys()):
            a, b = old_tiles.get(key), new_tiles.get(key)
            status = 'unchanged' if a and b and a['sha256'] == b['sha256'] else _status(a, b)
            summary['counts']['tiles'][status] += 1
            if status != 'unchanged':
                summary['tileChanges'].append({'dataset': identity, 'z': key[0], 'x': key[1], 'y': key[2], 'status': status,
                                               'before': dict(a) if a else None, 'after': dict(b) if b else None})
        old_places, new_places = _places(before, old_id), _places(after, new_id)
        for key in sorted(old_places.keys() | new_places.keys()):
            a, b = old_places.get(key), new_places.get(key)
            normal_a, normal_b = _normalize_place(a, str(old_id)), _normalize_place(b, str(new_id))
            status = 'unchanged' if normal_a == normal_b else _status(a, b)
            summary['counts']['places'][status] += 1
            if status != 'unchanged':
                fields = sorted(k for k in (normal_a or {}).keys() | (normal_b or {}).keys() if (normal_a or {}).get(k) != (normal_b or {}).get(k))
                summary['placeChanges'].append({'dataset': identity, 'placeId': key, 'status': status, 'changedFields': fields,
                    'before': a, 'after': b, 'beforeSha256': sha256_bytes(canonical_json_bytes(a)) if a else None,
                    'afterSha256': sha256_bytes(canonical_json_bytes(b)) if b else None})
    output.mkdir(parents=True, exist_ok=True)
    images = output / 'images'; images.mkdir()
    copied, copied_bytes = set(), 0
    for change in summary['tileChanges'][:preview_limit]:
        for side in ('before', 'after'):
            tile = change[side]
            if tile is None:
                continue
            filename = tile['sha256'] + '.webp'
            if filename not in copied:
                if copied_bytes + tile['bytes'] > MAX_IMAGE_BYTES:
                    tile['previewOmitted'] = 'Image byte budget exceeded; see full source path and SHA-256.'
                    continue
                payload = safe_file(roots[side], relative_public_path(tile['url']), 'preview tile').read_bytes()
                if sha256_bytes(payload) != tile['sha256']:
                    raise DeploymentError('Tile changed after validation')
                if payload[:4] != b'RIFF' or payload[8:12] != b'WEBP':
                    raise DeploymentError('Preview tile is not a WebP image')
                (images / filename).write_bytes(payload); copied.add(filename); copied_bytes += len(payload)
            tile['previewImage'] = 'images/' + filename
    summary['preview'].update(tilesShown=min(preview_limit, len(summary['tileChanges'])),
                              placesShown=min(preview_limit, len(summary['placeChanges'])), imageCount=len(copied), imageBytes=copied_bytes)
    (output / 'summary.json').write_bytes(canonical_json_bytes(summary))
    (output / 'index.html').write_text(_gallery(summary), encoding='utf-8')
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-public-root', type=Path)
    parser.add_argument('--candidate-public-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--base-sha')
    parser.add_argument('--candidate-sha', required=True)
    parser.add_argument('--preview-limit', type=int, default=100)
    args = parser.parse_args(argv)
    try:
        summary = review_datasets(**vars(args))
    except (DeploymentError, OSError) as error:
        print(f'Dataset review failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps({'outputDir': str(args.output_dir), 'counts': summary['counts'], 'preview': summary['preview']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
