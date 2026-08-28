# Stage 5 — OpenMW production basemap

Дата последнего полного аудита: 2026-08-29. Статус: **5.1, 5.2 и basemap-часть 5.3 завершены; tile contracts/publication из 5.5 готовы. EN catalog, generic runtime loader и UI integration остаются в работе.**

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

## Полный release 5.3

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

## Full seam/quality audit

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

## Подготовленный dataset contract

Publisher независимо перепроверяет inventory, stabilization receipt, audit, sparse coverage и raw renderer provenance. Затем tiles публикуются по immutable content address:

```text
apps/web/public/datasets/generated/poison-song-26.08/
  d409e627a75beac2caea56cea35bea132091bc851e1b22edbb4dbe3791f5cd17/
```

APFS использует clone-on-write; на другой filesystem допускается обычная проверяемая copy. Полный metadata package, включая `map-assets.json`, появляется одним atomic exclusive directory rename только после полной публикации и проверки tiles:

```text
/datasets/metadata/poison-song-26.08/
  d409e627a75beac2caea56cea35bea132091bc851e1b22edbb4dbe3791f5cd17/
    map-assets.json
```

SHA-256 `map-assets.json` — `b400cc972966f2c0c54cd33b48dafaa4c6873b783ecad67347c92190f2a5ecef`. Contract описывает sparse WebP pyramid, coverage, exact derivation receipt, quality report, полный integrity block и versioned URL template. Poison Song dataset manifest прямо ссылается на этот immutable файл, без отдельного изменяемого stable pointer, но остаётся `placeholder`: tiles готовы, location/localization artifacts ещё `null`.

## Воспроизведение

```bash
pnpm data:poison:renderer:render
pnpm data:poison:renderer:finalize
pnpm data:poison:renderer:stabilize
pnpm data:poison:renderer:audit
pnpm data:poison:dataset:validate
pnpm data:poison:dataset:prepare
```

Повторный deterministic audit без повторного raw render:

```bash
python3 -m tools.openmw_renderer.audit full \
  --workers 4 --render-workers 2 --reuse-evidence
```

`dataset:prepare` выполняет validate → atomic immutable tiles → complete atomic immutable metadata package. Metadata-only публикации нет, поэтому невозможно сделать доступным `map-assets.json`, пока tile tree отсутствует. Все publication operations либо переиспользуют побайтно совпадающий immutable target, либо fail closed; если ОС не предоставляет atomic no-replace directory rename, publisher отказывается работать.

## Остаток Этапа 5

- 5.4: effective-record EN location catalog с stable Place/Entrance IDs, aliases, types и regions;
- 5.5: generic browser loader и OpenLayers TileLayer поверх готового contract;
- 5.6: Poison Song search, statuses, notes, personal markers, loading/error states и offline browser acceptance.

Basemap quality gate больше не блокирует эти работы; полный dataset считается `ready` только после catalog и runtime/UI acceptance.
