# Stage 5 — OpenMW production basemap

Дата последнего полного аудита: 2026-08-31. Статус: **Этап 5 и подэтапы 5.1–5.6 завершены на 100%: quality-first V4 basemap опубликован и активирован Poison Song `ready` manifest-ом, V1 сохранён как immutable rollback, catalog/runtime подключены и real-browser acceptance принят.**

## Production pipeline

- exact Poison Song core profile и fail-closed provenance по игровым inputs, asset tree, profile, producer source, OpenMW image ID и ImageMagick;
- effective LAND/CELL coverage: `3 984` native cells, `492` deterministic shards, plan fingerprint `f291d795804b723b788ccfa16b39fa5af3a987af14c0122fb268b0d2f535e57d`;
- один OpenMW process загружает exporter-only `5×5` context и создаёт до девяти `3×3` RTT captures с native crop `512×512`;
- встроенный `--workers`, стабильные modulo partitions, atomic checkpoint/resume и hash-проверка уже опубликованных tiles;
- lossless WebP method 4, sparse `z0…z7` pyramid и deterministic inventory;
- per-shard engine/resource logs, `process.json`, cgroup `memory.peak` и resource-resolution reports.

OpenMW generic defaults называют погодные текстуры `Tx_Sky_Snow.dds` и `Tx_Sky_Blizzard.dds`, которых нет в GOTY BSA. Canonical profile фиксирует существующие Bloodmoon resources `Tx_BM_Sky_Snow.dds` и `Tx_BM_Sky_Blizzard.dds`; оба проходят asset и runtime audits. Настоящие missing mesh/texture/file, отсутствующие ожидаемые логи и non-zero container exit остаются фатальными. `addAnimSource: can't find bone` учитывается отдельно как известное compatibility warning после успешной загрузки NIF/KF.

## Benchmark 5.2

На Balmora, Old Ebonheart, Othrenis, Gorne и Nan Iban отрендерены пять полных `3×3` batches: `45` native tiles, два workers.

| Метрика | Результат |
| --- | ---: |
| Provenance/hash audit | `36.367 s` |
| Render wall, 5 shards / 45 WebP | `178.977 s` |
| Container time, mean | `52.4 s` |
| Максимальный peak одного shard | `1 137 119 232 bytes` |
| Сумма двух наибольших peaks | `2 208 509 952 bytes` |
| Resume тех же 45 tiles | `0.080 s`, OpenMW не запускался |
| Control finalize | `39.598 s`, `101` tiles |

Lossless WebP method 4 дал тот же decoded RGBA, что method 6, при `0.407 s` вместо `8.667 s` на контрольном Balmora tile и всего `+1.29%` к размеру. Прогноз полного pipeline был `5–6 h`; он использовался только как planning estimate и больше не является статусом выполнения.

## Активный V4 release 5.3

V4 повторяет доказанную координатную модель V1, но использует opaque-water/binary-alpha postprocess, single-pass grade `114/102/92`, stabilizer v2 и presentation contract `mim-opaque-v4`. Poison Song manifest ссылается именно на этот release.

| Release identity | Значение |
| --- | --- |
| Snapshot | `tr:poison-song-26.08:6964517551e0fcb0` |
| Native tiles / shards | `3 984 / 492` |
| Lower-zoom tiles | `1 480` |
| Всего tiles / bytes | `5 464 / 1 703 000 992` |
| Inventory logical SHA-256 | `93758a5e645013821d99a7989d69f3e4aa39373e2c5cb4b97873da421c5052b2` |
| Inventory file SHA-256 | `871f9aaffdb19fba7eca97f89e49c8279cae688161010d1d3d0378505b618ef6` |
| Audit SHA-256 | `9dea3294046201cceb1257f581a4ef9d63a3373042488ca3b4961196803d482e` |
| `map-assets.json` SHA-256 | `b6e8c18b3986b99267eab9f3509a331865e77da978b8652e99054f5c48003de9` |

Release находится в ignored каталоге `local-data/openmw-release/poison-song-26.08-v4`; content-addressed metadata зафиксирована в Git, а тяжёлая tile tree остаётся локальной. Полный audit проверил `5 464` tiles, все lower-zoom derivations, seam/resource/coordinate gates и `16` raw probes / `32` repeat runs. Все release gates прошли.

## Исторический V1 baseline 5.3 (rollback)

Ниже сохранены точные данные первого принятого release. V1 больше не является активной подложкой Poison Song, но его immutable metadata и локальная tile tree не изменены и остаются rollback target.

Production output после `finalize` дополнительно проходит deterministic cross-shard stabilization. Алгоритм обрабатывает только native границы разных OpenMW processes, фиксирует RGBA до/после каждого изменённого tile в receipt и затем полностью перестраивает lower zoom. Исходный production output не изменяется.

| Release identity | Значение |
| --- | --- |
| Snapshot | `tr:poison-song-26.08:6964517551e0fcb0` |
| Native tiles / shards | `3 984 / 492` |
| Lower-zoom tiles | `1 480` |
| Всего tiles / bytes | `5 464 / 1 879 019 148` |
| Inventory logical SHA-256 | `d409e627a75beac2caea56cea35bea132091bc851e1b22edbb4dbe3791f5cd17` |
| Inventory file SHA-256 | `870635a629c712ea79d26e84fadcdfdf4e630a6e16f7d19418d955563886cc8b` |
| Stabilization fingerprint | `35336f72d76bc5e41d4f846ef1eb14e432696fe3062be2f23ab8171aedc5ae5a` |
| Receipt logical / file SHA-256 | `e35358a4fe82673234a2e7ac4f9e11e212a53b5156ffc950acd68d3526fe7012` / `995b709e77e1507d39daf34f66ae952e4fabe4e0ddfc4620fd6993afa081c548` |
| Stabilizer implementation SHA-256 | `cd3631e8b10ccc90950627f2d72024cc8ae5f924a9a9d2edb82fc50c3c54e6a3` |
| Touched/changed native tiles | `3 471 / 3 471` |

Release находится в ignored каталоге `local-data/openmw-release/poison-song-26.08`. Stabilizer создаёт immutable source snapshot, пинит CPython/ImageMagick/libwebp/producer identities и публикует release через no-replace rename; повтор с несовместимым состоянием завершается ошибкой.

## Исторический V1 seam/quality audit

Audit fail-closed проверил release целиком и завершился `passes: true`:

- все `5 464` файлов существуют, непусты, совпадают с inventory hashes и декодируются строго в `512×512 RGBA`;
- все `1 480 / 1 480` lower-zoom parents побайтно соответствуют каноническому выводу из children; mismatches — `0`;
- проанализированы все `10 467` соседств, включая `7 729` native и все `2 571` native cross-shard boundaries;
- cross-shard structural failures — `0`, flagged pairs — `0`; mean excess `0.225398867`, p95 `0.262207031`, maximum pair mean `0.289550781`;
- same-shard flagged pairs — `6 / 5 158`; это диагностические природные/геометрические контрасты внутри одного OpenMW capture, не cross-process seams и не release blocker;
- для всей pyramid отмечены `218 / 10 467` диагностических pairs, включая downsampled boundaries; population и absolute gates прошли;
- `16` стратифицированных cross-shard seams независимо перерендерены как `32` raw cells; raw/repeat/released checks прошли, coordinate error — `0 px`;
- проверены `492` resource reports и `3 984` coordinate markers: actionable missing resources — `0`, известных compatibility warning events — `33`;
- runtime подтверждён как headless Linux `amd64`, `llvmpipe`; максимальный container runtime `172 s`, peak memory `1 402 871 808 bytes`;
- released renderer image `sha256:c8f07489f32533d771f1181bb5e8c233d5a5b42162114c7c3bd8ec60b4be190a` независимо rematerialized candidate image `sha256:e3b70d1dacb0daa97b21c25843375a628cc8c311a7d464ad1f2a1266d72a32af`; renderer contract и non-image provenance совпали.

Logical audit SHA-256: `4439782ab6e2cdf0d8330168428c4c5550629beaf607f4b9f5507700daf270d5`; serialized report SHA-256: `0e42de6823b9c25dfb36990cadb7cdd9c93e7e8a5fac0de12c4ad0b4dc968833`. Повторный audit с `--reuse-evidence` получил тот же logical SHA. Contact sheet худших кандидатов просмотрен в native detail; он не показал отдельного необъяснённого cross-shard разрыва, а машинный gate для этой категории имеет нулевую flagged population.

Audit artifacts находятся в `local-data/openmw-release/poison-song-26.08/quality-audit`: `report.json`, `tiles.ndjson`, `seams.ndjson`, `resource-runtime.json`, raw-probe provenance и `worst-seams.webp`.

## Активный dataset contract

Publisher независимо перепроверяет inventory, stabilization receipt, audit, sparse coverage и raw renderer provenance. Затем tiles публикуются по immutable content address:

```text
apps/web/public/datasets/generated/poison-song-26.08/
  93758a5e645013821d99a7989d69f3e4aa39373e2c5cb4b97873da421c5052b2/
```

APFS использует clone-on-write; на другой filesystem допускается обычная проверяемая copy. Полный metadata package, включая `map-assets.json`, появляется одним atomic exclusive directory rename только после полной публикации и проверки tiles:

```text
/datasets/metadata/poison-song-26.08/
  93758a5e645013821d99a7989d69f3e4aa39373e2c5cb4b97873da421c5052b2/
    map-assets.json
```

SHA-256 активного V4 `map-assets.json` — `b6e8c18b3986b99267eab9f3509a331865e77da978b8652e99054f5c48003de9`. Contract описывает sparse WebP pyramid, coverage, exact derivation receipt, quality report, полный integrity block, baked presentation `mim-opaque-v4` и versioned URL template. Poison Song dataset manifest прямо ссылается на этот immutable файл, без отдельного изменяемого stable pointer. Location/localization artifacts также подготовлены отдельным content-addressed catalog pipeline; после подключения generic runtime manifest переведён в `ready`.

Предыдущий V1 package `d409e627a75beac2caea56cea35bea132091bc851e1b22edbb4dbe3791f5cd17` с `map-assets.json` SHA-256 `b400cc972966f2c0c54cd33b48dafaa4c6873b783ecad67347c92190f2a5ecef` сохранён без изменений. Rollback требует только отдельного manifest commit, возвращающего этот immutable pointer.

Runtime использует единые `DatasetMap` и dataset loader для manifest-driven загрузки map assets, location catalog и всех объявленных локалей. Original MIM остаётся на OpenLayers `ImageStatic`, а Poison Song использует `TileLayer` с явной TES3 grid, fixed top-left XYZ и native `512×512` WebP. Coverage index проверяется до построения tile URL, поэтому sparse holes не создают заведомо ошибочных HTTP-запросов. Отдельные UI states различают отсутствующий подготовленный dataset (`missing`), текущую загрузку и runtime/tile error с retry.

Catalog имеет отдельный inventory, потому что меняется независимо от тяжёлой tile pyramid, но жёстко привязан к тому же `datasetId`/`snapshotId`. Он содержит `4 085` places и `4 902` entrances; exact merge, stable ID, grouping, type/region/alias policies и audit описаны в [stage5-catalog.md](stage5-catalog.md).

## Browser acceptance 5.6

Pinned Playwright `1.62.1` запускает настоящий headless Chromium с blocked service workers и fail-closed routing: любой запрос не к `127.0.0.1:4173` блокируется и делает тест неуспешным. Default suite пригоден для clean CI: production index, Poison manifest, V4 `map-assets.json` и sparse coverage остаются настоящими, а только ignored catalog/WebP payload подменяется минимальными валидными fixtures.

Acceptance проверяет painted basemap canvas и V4 URLs, поиск места, status/note/custom-marker workflow, persistence после reload, zoom, keyboard pan, missing dataset, metadata error/retry и tile error/retry. Во время gate был найден runtime gap: `source.refresh()` не перезапрашивал cached `ERROR` tile. Runtime теперь хранит только упавшие OpenLayers `ImageTile` и повторяет их штатным `tile.load()`, не инвалидируя успешно загруженные tiles.

Отдельный local-only `@prepared` gate не использует synthetic payload: он загружает настоящий catalog из `4 085` places и реальные WebP из активной V4 tree. Таким образом clean CI доказывает функциональный/offline контракт, а prepared gate связывает его с полным локальным release.

## Воспроизведение

```bash
pnpm data:poison:renderer:render
pnpm data:poison:renderer:finalize
pnpm data:poison:renderer:stabilize
pnpm data:poison:renderer:audit
pnpm data:poison:dataset:validate
pnpm data:poison:dataset:prepare
pnpm data:poison:catalog:build
pnpm data:poison:catalog:validate
pnpm data:poison:catalog:prepare
pnpm test:acceptance
pnpm test:acceptance:prepared
```

`test:acceptance` входит в `pnpm verify` и не требует proprietary/generated payload. `test:acceptance:prepared` запускается после публикации полного локального V4 dataset и поэтому намеренно не входит в обычный CI.

Повторный deterministic audit без повторного raw render:

```bash
python3 -m tools.openmw_renderer.audit full \
  --workers 4 --render-workers 2 --reuse-evidence
```

`dataset:prepare` выполняет validate → atomic immutable tiles → complete atomic immutable metadata package. Metadata-only публикации нет, поэтому невозможно сделать доступным `map-assets.json`, пока tile tree отсутствует. Все publication operations либо переиспользуют побайтно совпадающий immutable target, либо fail closed; если ОС не предоставляет atomic no-replace directory rename, publisher отказывается работать.

## Завершение Этапа 5

- 5.5: **выполнено на 100%** — generic loader/`DatasetMap`, OpenLayers `TileLayer`, TES3 sparse grid/coverage, dynamic catalog/locales, `missing`/`loading`/`error` states и `ready` manifest;
- 5.6: **выполнено на 100%** — loopback-only real-Chromium acceptance покрывает search, statuses, notes, personal markers, reload persistence, zoom/pan и негативные сценарии загрузки; prepared gate подтверждает настоящий V4 payload.

Basemap, catalog, runtime и product/browser quality gates закрыты. Poison Song manifest имеет статус `ready`; Exit Этапа 5 достигнут.
