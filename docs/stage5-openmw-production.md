# Stage 5.1–5.2 — OpenMW production renderer

Дата измерения: 2026-08-27. Статус: **5.1 и 5.2 выполнены; локальный full render 5.3 начат, но ещё не завершён и не finalized**.

## Что реализовано

- exact Poison Song core profile и fail-closed provenance по asset tree, profile, source, OpenMW image ID и ImageMagick;
- effective LAND/CELL coverage и immutable plan: `3 984` native cells, `492` deterministic shards, plan fingerprint `f291d795804b723b788ccfa16b39fa5af3a987af14c0122fb268b0d2f535e57d`;
- один OpenMW process загружает exporter-only `5×5` context и создаёт до девяти `3×3` RTT с native crop `512×512`;
- встроенный `--workers`, стабильные `--shard-count/--shard-index`, atomic checkpoint/resume и hash-проверка уже опубликованных tiles;
- pixel-exact lossless WebP method 4, sparse `z0…z7` pyramid и deterministic inventory;
- per-shard engine/resource logs, `process.json`, cgroup `memory.peak` и resource-resolution report.

Stage 4.5 parent сначала проверяется по labels, затем получает уникальный local tag из image ID. Production image хранит этот parent ID в labels. Docker compile отделён от host provenance-label layer, поэтому изменения CLI не компилируют OpenMW заново.

OpenMW generic defaults называют погодные текстуры `Tx_Sky_Snow.dds` и `Tx_Sky_Blizzard.dds`, которых нет в исходных loose assets и GOTY BSA. Production profile поэтому фиксирует канонические Bloodmoon overrides `Tx_BM_Sky_Snow.dds` и `Tx_BM_Sky_Blizzard.dds`; оба ресурса проверены asset audit и реально разрешаются из Bloodmoon data. Это не ослабляет missing-resource gate.

## Реальный benchmark 5.2

Пять областей: Balmora, Old Ebonheart, Othrenis, Gorne и Nan Iban. Для каждой отрендерен полный `3×3`; итого `45` native tiles и пять Docker processes с двумя workers.

| Метрика | Результат |
| --- | ---: |
| Provenance/hash audit | `36.367 s` |
| Render wall, 5 shards / 45 WebP | `178.977 s` |
| Container time, mean | `52.4 s` |
| Container time, range | `43–65 s` |
| Максимальный peak одного shard | `1 137 119 232 bytes` |
| Сумма двух наибольших peaks | `2 208 509 952 bytes` |
| Resume тех же 45 tiles | `0.080 s`, OpenMW не запускался |
| Control finalize | `39.598 s`, `101` total tiles |
| Control inventory | `20 389 642 bytes`, SHA-256 `6528bcc6381dd2219741c0b13bcf1ca2c6f0d4087f5c95d83feb47eeca39a115` |

WebP method 6 оказался host bottleneck: на фиксированном Balmora tile он занимал `8.667 s`. Method 4 занял `0.407 s`, увеличил файл только с `346 934` до `351 394` bytes (`+1.29%`) и после decode дал тот же RGBA SHA-256. Поэтому production использует method 4: формат остаётся строго lossless.

## Quality evidence

- world coordinate → pixel error: `0`;
- проверено `60` внутренних raw-gutter overlaps;
- worst overlap: differing fraction `0.338753`, mean channel delta `0.342314 / 255`, max delta `128` на единичных alpha-edge samples;
- production tolerance: fraction `≤0.35`, mean `≤0.5`, max `≤128`; stitched `3×3` просмотрен без видимых seams;
- со старыми Stage 4.5 `1×1` сравнились 9 доступных raw center/east/north samples: максимум `628 / 295 936` pixels (`0.2122%`), mean channel delta `0.012887`; пять center images визуально совпадают.

Локальные доказательства находятся в ignored каталоге `local-data/openmw-production/poison-song-26.08/benchmark/five-controls-workers2-method4`: `benchmark-report.json`, `comparison.webp`, `checkpoint.json`, `provenance.json`, raw, tiles, logs и runtime evidence.

## Реальная оценка полного запуска

Полный coverage содержит `492` render shards и `1 480` lower-zoom tiles. Экстраполяция фактического wall throughput даёт:

- native render, два workers: `4.892 h`;
- full pyramid/finalize: `0.291 h`;
- разовый provenance: `36 s`;
- point estimate полного pipeline: **`5.193 h`**.

Практический бюджет на той же машине и текущих Docker Desktop settings: **5–6 часов**. Это оценка, а не уже выполненный full render: пять controls являются сложными населенными областями и все имели по 9 targets, тогда как средняя заполненность полного shard — `8.10`; с другой стороны, thermal throttling и параллельная нагрузка могут увеличить wall time.

Старый подход `1 CELL = 1 OpenMW process` давал `35.95 h`. Production batching сокращает число startup/load cycles с `3 984` до `492`.

## Запуск из Terminal

```bash
pnpm data:poison:plan
pnpm data:poison:renderer:build
pnpm data:poison:renderer:smoke
pnpm data:poison:renderer:benchmark
```

Полный запуск, когда будет принято решение генерировать весь basemap:

```bash
pnpm data:poison:renderer:render
pnpm data:poison:renderer:finalize
```

Повтор той же команды `render` продолжает checkpoint. Встроенные два workers безопасно публикуют результаты последовательно. После проверки provenance Terminal печатает текущее durable значение, например `[227/3984]`, и обновляет его после каждого полностью опубликованного shard. Несколько отдельных Terminal processes нельзя направлять в один output одновременно; modulo partitions предназначены для последовательных job slices либо для разных output roots с отдельным последующим merge workflow.

После совместимого изменения host producer готовый checkpoint переносится только отдельной командой `migrate-resume` с точным старым provenance и причиной. По умолчанию смена profile fingerprint запрещена; осознанная коррекция профиля требует `--allow-profile-change`. Перед записью pipeline повторно проверяет каждый WebP и полное совпадение игровых `inputAudit`/`assetAudit`, сохраняет byte-identical backup старого checkpoint/provenance и пишет migration receipt со старыми и новыми fingerprint.

Информационный OpenMW warning `addAnimSource: can't find bone` возникает после успешной загрузки NIF/KF, когда отдельный animation controller не находит кость. Он остаётся видимым в `resource-resolution.json` как `ignoredCompatibilityWarnings`, но не считается отсутствующим ресурсом. Любой настоящий `Failed to load`, missing mesh/texture/file, отсутствующий ожидаемый лог или non-zero exit остаётся фатальным.

## Что остаётся в Этапе 5

5.3 — фактический full render/finalize и full-scope gates; 5.4 — полный EN catalog; 5.5 — WebP tile contract/immutable ready manifest/runtime loader; 5.6 — Poison Song UI integration. До 5.3 generated full basemap не существует и в приложение не подключается.
