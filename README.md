# Morrowind Map

Локальная интерактивная карта Morrowind с тремя независимыми версиями мира:

1. Original Morrowind + Tribunal + Bloodmoon — EN/RU.
2. Fullrest / Tamriel Rebuilt 25.08 (Grasping Fortune) — EN/RU.
3. Tamriel Rebuilt 26.08 (Poison Song) — EN.

Original уже поддерживает локальные MIM-растры Vvardenfell и Solstheim, 1 010 мест из MIM/ESM, EN/RU, поиск, zoom/pan, MIM-цвета статусов `unvisited` / `active` / `visited`, заметки и личные квадратные маркеры. Прогресс хранится локально в IndexedDB через Dexie и жёстко привязан к snapshot; доступны однократный импорт текущего MIM snapshot и общий переносимый JSON backup v2/import со строгой проверкой совместимости и чтением ранних v1-копий.

Текущий статус: **Этап 5 в работе; 5.1–5.5 завершены на 100%, впереди product/browser acceptance 5.6**. Pinned headless OpenMW pipeline построил `3 984` native tiles, после cross-shard stabilization — полную quality-first V4 sparse lossless WebP pyramid `z0…z7`: `5 464` tiles, `1 703 000 992` bytes, inventory `93758a5e…`. Full audit `9dea3294…` проверил декодирование каждого tile, все `10 467` соседств, точное происхождение всех `1 480` lower-zoom tiles, `492` runtime resource reports, `0 px` coordinate error и независимый raw rerender `32` cells; все release gates прошли. Generic TES3 catalog pipeline поверх exact load order выпустил `4 085` places и `4 902` entrances с stable IDs, EN names, types, regions и deterministic audit. Poison Song `ready` manifest активирует V4; immutable V1 сохранён как rollback, Fullrest пока остаётся placeholder.

Browser runtime теперь использует единые `DatasetMap` и dataset loader. Original по-прежнему показывает MIM-подложки через OpenLayers `ImageStatic`, а Poison Song — собственную WebP pyramid через `TileLayer` и явную TES3 tile grid с top-left XYZ. Sparse coverage проверяется до построения URL, поэтому отсутствующие в inventory tiles не вызывают HTTP-запросы. Каталог и все объявленные manifest-ом локали загружаются динамически; интерфейс различает отсутствие подготовленного локального dataset, текущую загрузку и ошибку с возможностью retry.

Подробный план: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
Результаты LAND gate: [docs/adr/0001-land-renderer-spike.md](docs/adr/0001-land-renderer-spike.md).
Архитектура OpenMW exporter: [docs/adr/0002-openmw-offline-exporter.md](docs/adr/0002-openmw-offline-exporter.md).
Production pipeline и реальные измерения: [docs/stage5-openmw-production.md](docs/stage5-openmw-production.md).
Generic catalog pipeline и audit: [docs/stage5-catalog.md](docs/stage5-catalog.md).

## Данные

Игровые BSA/ESM/ESP, mod assets, исходные растры и сгенерированные datasets не хранятся в Git. Репозиторий содержит код, JSON schemas, manifests без игровых данных, документацию и синтетические тестовые fixtures.

Original собирается локальным offline pipeline из соседнего `../morr-dev`:

- `bsa/*.esm` — английские GOTY masters;
- `game/Data Files/*.{cel,mrk,top}` — русские словари;
- `Maps/mim_morrowind` и `Maps/mim_bloodmoon` — MIM-каталоги и растры.

Pipeline проверяет pinned SHA-256 masters, извлекает внешние входы из ESM и пишет ignored-артефакты в `apps/web/public/datasets/generated/original-goty`. Bloodmoon JPEG привязан к точной LAND-сетке; для редких MIM-only точек используется документированная калибровка по 55 входам. Тот же pipeline fail-closed сопоставляет `user.gdb` с `mwmain.gdb` по региону и ordinal и формирует MIM snapshot: 933 статуса (741 visited, 192 unvisited), одну заметку и 6 personal markers.

Повторный импорт того же MIM snapshot является no-op. Более поздние ручные изменения не перезаписываются новым MIM import, а удалённые импортированные markers сохраняются как tombstones и не появляются снова.

LAND renderer spike воспроизводится отдельно из Poison Song 26.08, Tamriel Data 26.08 и трёх vanilla BSA. Требуется ImageMagick 7; ESM/BSA и generated renders остаются вне Git:

```bash
pnpm data:renderer-spike
```

Пять контрольных WebP и полный hash/coordinate/resource report появятся в `local-data/renderer-spike/poison-song-26.08`.

OpenMW renderer spike использует тот же внешний `../morr-dev`, Docker Desktop и ImageMagick 7. Первый запуск собирает pinned `linux/amd64` image и делает Balmora smoke; следующие команды переиспользуют image:

```bash
# Build + smoke.
python3 -m tools.openmw_renderer.spike --smoke-only

# Smoke без rebuild.
pnpm data:openmw-smoke

# Полный gate пяти участков без rebuild.
python3 -m tools.openmw_renderer.spike --skip-build

# Повторная оценка готовых artifacts после визуального review.
python3 -m tools.openmw_renderer.spike --skip-build --evaluate-only
```

Smoke пишет `local-data/openmw-spike/poison-song-26.08/smoke-report.json`, полный gate — `report.json`, пять `controls/*.webp` и хэш-привязанный шаблон ручной визуальной квитанции. BSA/ESM/ESP/omwscripts, loose Tamriel Data/TR assets и полный WebP payload остаются локальными ignored artifacts и в Docker image не входят; Git хранит код, contracts и компактные publication/quality metadata.

### Poison Song production renderer

Нужны соседний `../morr-dev`, Docker Desktop и ImageMagick 7. Команды полностью локальные; профиль, image и encoder проверяются автоматически, вручную придумывать provenance hash не требуется:

Опубликованный V1 release остаётся immutable и продолжает работать. Для утверждённого quality-first варианта 04 используется отдельный V4 pipeline: он никогда не пишет в старые production/release roots, применяет к исходному OpenMW capture один grade `brightness=114`, `contrast=102`, `saturation=92`, делает любой отрендеренный pixel непрозрачным и оставляет прозрачными только sparse holes. Binary alpha повторно нормализуется после seam stabilization и каждого downsample. Browser применяет старую runtime-коррекцию только к V1 metadata без `presentation`; V4 metadata с `mim-opaque-v4` загружается без canvas/CSS double processing. Дополнительный zoom `1.1×` остаётся view-only.

Контрольный Вивек (`CELL x=2…4, y=-13…-11`) рендерится отдельно от полного checkpoint:

```bash
pnpm data:poison:v4:renderer:build
pnpm data:poison:v4:renderer:smoke
```

Smoke автоматически собирает `1536×1536` PNG preview из девяти native tiles. Tiles и preview находятся в `local-data/openmw-production/poison-song-26.08-v4-vivec-smoke-final`; эта директория ignored и не участвует в полном render. Повторно собрать PNG без рендера можно командой `pnpm data:poison:v4:renderer:preview`.

Полная V4 последовательность:

```bash
pnpm data:poison:v4:renderer:build
pnpm data:poison:v4:plan
pnpm data:poison:v4:renderer:render
pnpm data:poison:v4:renderer:finalize
pnpm data:poison:v4:renderer:stabilize
pnpm data:poison:v4:renderer:audit
pnpm data:poison:v4:dataset:validate
pnpm data:poison:v4:dataset:prepare
```

`render` использует два workers и продолжает `local-data/openmw-production/poison-song-26.08-v4/checkpoint.json`. V4 release публикуется в `local-data/openmw-release/poison-song-26.08-v4`. `prepare` создаёт новый immutable content-addressed package, а отдельный activation commit фиксирует его `map-assets` pointer в Poison Song manifest. Сейчас активен V4 inventory `93758a5e…`; V1 inventory `d409e627…` не изменён и остаётся локальным rollback target.

Короткие команды без `:v4` являются алиасами текущего V4 pipeline и не могут случайно продолжить старый V1 checkpoint. Опубликованный immutable V1 можно отдельно перепроверить командой `pnpm data:poison:v1:dataset:validate`; его producer-команды намеренно больше не экспонируются.

`render` использует два встроенных workers и безопасно продолжается тем же command после остановки: готовые WebP повторно проверяются по checkpoint и не рендерятся. Terminal сразу показывает setup, затем после каждой атомарной записи checkpoint печатает прогресс вида `[227/3984]`. Для последовательного деления плана доступны `--shard-count N --shard-index I`; несколько отдельных процессов не должны одновременно писать один checkpoint. Raw `544×544` PNG удаляются после публикации WebP, если явно не указан `--retain-raw`.

OpenMW warning `addAnimSource: can't find bone` означает несовпадение animation controller с уже загруженным NIF, сохраняется в `ignoredCompatibilityWarnings` и не останавливает production render. Настоящие missing mesh/texture/file, отсутствующие логи и non-zero container exit по-прежнему fail closed.

Production profile явно направляет snow/blizzard weather на существующие Bloodmoon-ресурсы `Tx_BM_Sky_Snow.dds` и `Tx_BM_Sky_Blizzard.dds`: универсальные OpenMW defaults с именами `Tx_Sky_*` отсутствуют в GOTY BSA. Контролируемая смена producer source сохраняет готовые тайлы только через отдельный `migrate-resume`; смена profile fingerprint дополнительно требует явного `--allow-profile-change`, полного совпадения `inputAudit`/`assetAudit`, byte-identical backups старого состояния и migration receipt.

`stabilize` создаёт immutable release в `local-data/openmw-release/poison-song-26.08-v4`, исправляет только границы разных render shards и заново выводит lower zoom. `audit` fail-closed проверяет всю release tree. Его 32 raw render probes сохраняются в content-addressed checkpoint внутри `quality-audit` и при обычном повторном `pnpm data:poison:v4:renderer:audit` автоматически проверяются и переиспользуются. Флаг `--reuse-evidence` дополнительно переиспользует готовые результаты остальных gates, но допустим только без изменения версии и реализации audit; после изменения audit-кода надо запускать обычную команду без этого флага. V4 repeat-gate допускает только малую рассеянную вариативность binary-alpha foliage и отдельно ограничивает максимальный opaque delta (`48`) и крупнейший связный hard-компонент (`16 px`). `dataset:prepare` сначала повторяет строгую валидацию, затем APFS clone/copy публикует tiles по immutable inventory hash в `apps/web/public/datasets/generated/poison-song-26.08/<inventory-sha256>` и одним atomic exclusive rename публикует полный metadata package, включая `map-assets.json`, по тому же content-addressed version path. Отдельного изменяемого stable pointer и metadata-only режима нет: committed dataset manifest прямо ссылается на immutable package, поэтому частично подготовленный dataset не становится видимым приложению.

EN catalog строится и публикуется отдельно, но привязан к тому же dataset/snapshot и собственному deterministic inventory:

```bash
pnpm data:poison:catalog:build
pnpm data:poison:catalog:validate
pnpm data:poison:catalog:prepare
```

`build` объединяет `Morrowind.esm → Tribunal.esm → Bloodmoon.esm → Tamriel_Data.esm → TR_Mainland.esm` по TES3 load-order semantics, разрешает effective `CELL`/`DOOR`/teleport/base records и создаёт `locations.json`, `locales/en.json` и `catalog-audit.json`. `prepare` публикует два runtime artifacts и audit в immutable content-addressed каталог; игровые ESM и локальная рабочая копия остаются вне Git.

## Локальный запуск

Требуются Node.js `^20.19.0` либо `>=22.12.0` и pnpm `11.19.0`.

```bash
pnpm install
pnpm data:original
pnpm dev
```

Приложение будет доступно по адресу `http://127.0.0.1:5173`.

Полная локальная проверка, совпадающая с шагами CI:

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

Или одной командой: `pnpm verify`. Python data pipeline, LAND и OpenMW spike/production fixture tests входят в `pnpm test`; полная генерация игровых данных запускается отдельно и в CI не выполняется.
