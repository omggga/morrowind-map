# Stage 7.5 — loading, error, empty and retry matrix

Дата фиксации: 2026-09-01. Матрица применяется одинаково к Original GOTY HD и Poison Song; published dataset artifacts и IndexedDB/portable-backup schemas не меняются.

## Runtime matrix

| Producer | State | Severity / announcement | Message and action | Recovery contract |
| --- | --- | --- | --- | --- |
| Dataset index | initial / slow | `status`, `aria-busy` | `Reading manifests…`; после 800 ms объясняется задержка | Один request generation; unmount aborts it |
| Dataset index | network, HTTP, malformed or empty | `alert` | `DATA ERROR`, detail, `Retry` / `Retrying…` | Кнопка остаётся mounted и disabled во время retry; duplicate click не создаёт второй request |
| Individual manifests | proper subset failed | `alert`, healthy cards stay interactive | `PARTIAL CATALOG`, per-dataset detail, `Retry unavailable maps` | Исправные cards остаются доступны; direct URL неисправной карты не canonicalize-ится; recovery открывает сохранённый deep link |
| Individual manifests | all indexed manifests failed | `alert` | `DATA ERROR`, combined failure detail, `Retry` | Нулевой usable catalog не маскируется как partial success; retry возвращается на landing/deep link без history mutation |
| Dataset bundle | initial / slow | `status`, `aria-busy` | `Opening the map dataset…`; slow catalog получает отдельное объяснение | `AbortSignal` общий для locations, locale, map-assets и coverage |
| Dataset bundle | artifact not declared | `status` | `DATA MISSING`, `Versions` | Non-retryable unpublished state |
| Dataset bundle | JSON/schema/identity/grid/coverage mismatch | `alert` | `DATA INVALID`, detail, `Versions` | Deterministic invalid state не предлагает бессмысленный Retry |
| Dataset bundle | network / HTTP 404 or 503 | `alert` | `DATA ERROR`, `Retry` / `Retrying…` | Retry guarded; URL остаётся неизменным; success возвращает focus на map |
| Sparse basemap | ordinary load burst | `status` | Unique pending tile count | События одного tile не дублируют counters |
| Sparse basemap | expected uncovered coordinate | `status` | `No map tile exists…` | Не считается network failure и не предлагает Retry |
| Sparse basemap | partial failure | `alert` | Loaded areas remain usable; unique failed count; `Retry failed tiles` | Current-view generation считает только текущий load window; повторно вызывается `load()` только у failed tile set; camera, selection, filters и URL не пересоздаются |
| Sparse basemap | full visible failure | `alert` | Visible area unavailable; `Retry failed tiles` | Pan/zoom начинает новую generation до новых completions; late tiles старого viewport игнорируются; retry disabled while active, recovery focuses map |
| Catalog content | dataset has no exterior places | inline empty state | Причина + `Versions` | Не маскируется сообщением про filters |
| Catalog content | query has no matches | inline empty state | Причина + `Clear search` | Query clears; focus returns to search |
| Catalog content | region/type/status intersection is empty | inline empty state | Причина + `Reset filters` | Filters and URL reset atomically; focus returns to search |
| Catalog content | no places at current minZoom | inline empty state | Причина + zoom guidance | Map view remains unchanged |
| Personal markers | loading / unavailable / empty | `status` only while loading; inline otherwise | Distinct messages; empty state offers `Add personal marker` | No false empty while Dexie query is pending; Add focuses the map |
| Dataset snapshot binding | unavailable IndexedDB | single `alert` | Local data unavailable; map explicitly remains read-only; `Retry` | Map, search and static filters stay usable; writes are disabled; records are not deleted |
| Dataset snapshot binding | snapshot conflict | single `alert` | Records belong to another snapshot; `Versions`; Local log export remains available | Non-retryable, non-destructive read-only state |
| Progress / marker live query | read failure | single aggregated `alert` | Local data unavailable; `Retry` | Dexie observable is unsubscribed and recreated; stale emissions ignored; empty fallback never throws through render |
| Progress / note writes | quota or write failure | `alert` | Detail plus explicit same-control retry instruction | Synchronous in-flight guard; note draft remains in crash-recovery storage until a successful write |
| Marker create/edit/delete | write failure | `alert` | Failed coordinate/draft remains available; explicit retry | Failed autosave revision does not loop; manual Save or a new edit may retry; delete confirmation stays open after failure |
| JSON export/import | unavailable storage, invalid JSON, oversized file, quota/write failure | `alert` | Reason plus explicit action to retry | 10 MB rejected before parse/write; import validation and transaction remain atomic; duplicate operations are blocked synchronously |

## Shared retry and accessibility contract

- Retry controls stay present, use `aria-busy`, become disabled and change to `Retrying…`; a double activation before React rerender is also rejected by an in-flight ref.
- Abort and generation guards prevent an old fetch/live-query result from replacing newer state.
- Error uses one `alert`; progress uses `status`. Components do not combine `role="alert"` with a second `aria-live` declaration.
- Failure leaves navigation state intact. Tile retry never remounts OpenLayers, and dataset/manifest retry does not push a new history entry.
- Recovery either focuses the recovered map/content or returns focus to the same retry control when the operation fails again.

## Deterministic evidence

- `loadDatasets.test.ts`: ordered success, partial/all manifest failure, malformed manifest, empty/malformed index and abort.
- `loadDataset.test.ts`: shared abort signal, malformed JSON/schema for every resource family, snapshot identity, grid/coverage integrity and HTTP 404/503 classification.
- `App.test.tsx` / `DatasetMap.test.tsx`: URL preservation, partial landing, duplicate retry, missing/invalid/recoverable dataset states and busy controls.
- `useDatasetUserData.test.tsx`, `EditorDrafts.test.tsx`, `DataTools.test.tsx`, `userData.test.ts`: recoverable live queries, stale unsubscribe, quota/write failure, autosave blocking, invalid/oversized backup and atomic non-destructive import.
- `currentBasemapLoadWindow.test.ts` и `tests/ui/stage-7.5.states.visual.spec.ts`: viewport generations, delayed, initial partial, later full failure, retry, empty, mobile/landscape и axe fixtures.
- `@prepared` acceptance cases replay dataset and tile recovery on both real prepared payloads without changing published data.

Reproduction remains the repository gate:

```bash
pnpm verify
```

Prepared real-payload transitions remain an explicit local-data check:

```bash
pnpm test:acceptance:prepared
```

Последний prepared receipt: `6 passed` — bundle и failed-tile recovery для Original/Poison плюс полные реальные catalog/tile workflows.
