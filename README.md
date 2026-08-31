# Morrowind Map

Локальная интерактивная карта Morrowind с ровно двумя независимыми EN-only картами:

1. **Original GOTY HD** — только английские `Morrowind.esm`, `Tribunal.esm`, `Bloodmoon.esm` и одноимённые BSA; Tamriel Data / Tamriel Rebuilt / Fullrest в этот profile не подключаются.
2. **Tamriel Rebuilt 26.08 (Poison Song V4)** — существующий готовый release, который остаётся immutable и не перерендеривается.

Старый Original на MIM-растровой подложке с EN/RU каталогом и MIM import был завершён в исторических Stage 2–3, но теперь superseded. Новый Original получил scene-rendered HD pyramid для Vvardenfell + Solstheim и generic EN catalog `1 036` places / `1 205` entrances. Mournhold не приклеивается к world LAND: он остаётся отдельным неблокирующим follow-up в виде inset/submap с локальными координатами.

Текущий статус: **этапы 5 и 6 завершены на 100%**. Pinned headless OpenMW pipeline построил для Poison Song `3 984` native tiles, после cross-shard stabilization — полную quality-first V4 sparse lossless WebP pyramid `z0…z7`: `5 464` tiles, `1 703 000 992` bytes, inventory `93758a5e…`. Full audit `9dea3294…` проверил декодирование каждого tile, все `10 467` соседств, точное происхождение всех `1 480` lower-zoom tiles, `492` runtime resource reports, `0 px` coordinate error и независимый raw rerender `32` cells; все release gates прошли. Generic TES3 catalog pipeline выпустил `4 085` places и `4 902` entrances. Poison Song V4 остаётся immutable regression baseline.

Stage 6 опубликовал Original snapshot `original:goty:8b2690c0ce1c954e` из строго изолированного profile `8b2690c0ce1c954e603d317728b19339f4b985ce3c362b0bc0eee93b3841b2a7`; deterministic plan `9ad7c36652b18615234819aba986df32a89125b1365d47eddef0f847af90886c` охватывает `1 540` LAND cells и `198` render shards. Smoke прошёл `5/5`; full render/finalize/stabilize создали `2 114` lossless WebP tiles `z0…z7`. Final basemap inventory — `aade4b98c2fb905fd2617871345292a638e3a4a25c6d036db7a3cc18bb2dd014`, passed audit hash — `44f722800682e23be1ded7dedf27d5eae19a94864b834e92b488a53ae6c7b4a0`.

Browser runtime использует единые `DatasetMap`, dataset loader, `TileLayer` и явную TES3 tile grid с top-left XYZ. Original и Poison Song прошли real-browser acceptance на обоих настоящих prepared datasets; full render/audit/publish и strict validators Original зелёные.

Pinned Playwright/Chromium acceptance запрещает любой non-loopback traffic и проверяет painted WebP canvas, поиск, статусы, заметки, личные маркеры, reload persistence, zoom/pan, missing dataset и восстановление после ошибок metadata/tile. Отдельный local-only `@prepared` gate загружает реальные ignored catalogs и tiles обеих карт.

Подробный план: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
Результаты LAND gate: [docs/adr/0001-land-renderer-spike.md](docs/adr/0001-land-renderer-spike.md).
Архитектура OpenMW exporter: [docs/adr/0002-openmw-offline-exporter.md](docs/adr/0002-openmw-offline-exporter.md).
Production pipeline и реальные измерения: [docs/stage5-openmw-production.md](docs/stage5-openmw-production.md).
Generic catalog pipeline и audit: [docs/stage5-catalog.md](docs/stage5-catalog.md).
Original GOTY HD pipeline: [docs/stage6-original-hd.md](docs/stage6-original-hd.md).

## Данные

Игровые BSA/ESM/ESP, mod assets, исходные растры и сгенерированные datasets не хранятся в Git. Репозиторий содержит код, JSON schemas, manifests без игровых данных, документацию и синтетические тестовые fixtures.

Новый Original собирается локальным offline pipeline из соседнего `../morr-dev/bsa` строго из шести allowlisted inputs:

- `Morrowind.esm`, `Tribunal.esm`, `Bloodmoon.esm`;
- `Morrowind.bsa`, `Tribunal.bsa`, `Bloodmoon.bsa`.

Profile/audit должен fail closed при обнаружении Tamriel Data, Tamriel Rebuilt, Fullrest assets или иных data paths. Pipeline использует proven Poison renderer mechanics, но отдельные profile/checkpoint/release roots; Poison V4 bytes и hashes не изменяются. Original применяет те же V4 presentation rules: native `512×512`, grade `114/102/92`, binary alpha, opaque water, stabilization/seam audit и view-only `1.1×` overscale.

Cleanup удаляет из активного продукта Fullrest placeholder/profile, MIM raster/catalog/import и RU locale/UI paths. Старую IndexedDB не очищаем и не мигрируем разрушительно: приложение переходит на новый logical user-data epoch для двух активных карт, не меняя identity готового Poison dataset, а старые MIM/Fullrest/RU records остаются физически инертными и не показываются в UI. Общий JSON backup/import сохраняется и работает только с Original GOTY HD и Poison Song V4 текущего epoch.

### Original GOTY HD — Stage 6

Stage 6 завершён. Snapshot `original:goty:8b2690c0ce1c954e` содержит только английские `Morrowind.esm`, `Tribunal.esm`, `Bloodmoon.esm` и три одноимённых BSA — без Tamriel Data, Tamriel Rebuilt, Fullrest, loose assets и дополнительных plugins. Profile `8b2690c0ce1c954e603d317728b19339f4b985ce3c362b0bc0eee93b3841b2a7` и plan `9ad7c36652b18615234819aba986df32a89125b1365d47eddef0f847af90886c` прошли fail-closed проверки. Smoke `5/5`, полный render/audit/publish и strict validators зелёные; опубликованы `1 540` native LAND tiles в `198` shards и pyramid из `2 114` tiles. Catalog `1 036` places / `1 205` entrances опубликован с inventory `6ea0c0a0272f6c8456a947c9dc36bac5116a9cd524cc4b351fdad867cf3e0df1`; final basemap inventory — `aade4b98c2fb905fd2617871345292a638e3a4a25c6d036db7a3cc18bb2dd014`, passed audit hash — `44f722800682e23be1ded7dedf27d5eae19a94864b834e92b488a53ae6c7b4a0`. Browser acceptance существует для обеих реальных карт. Mournhold остаётся отдельным неблокирующим follow-up.

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
pnpm exec playwright install chromium
pnpm dev
```

Приложение будет доступно по адресу `http://127.0.0.1:5173`.

Полная локальная проверка, совпадающая с шагами CI:

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm test:acceptance
pnpm build
```

Или одной командой: `pnpm verify`. Она включает default browser acceptance; в CI pinned Chromium устанавливается автоматически. Python data pipeline, LAND и OpenMW spike/production fixture tests входят в `pnpm test`; полная генерация игровых данных запускается отдельно и в CI не выполняется.

После подготовки локальных content-addressed payload обеих карт они дополнительно проверяются так:

```bash
pnpm test:acceptance:prepared
```

Этот gate не входит в обычный CI, потому что proprietary/generated catalogs и полные WebP payload обеих карт не хранятся в Git.
