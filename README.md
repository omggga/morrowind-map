# Morrowind Map

Локальная интерактивная карта Morrowind с тремя независимыми версиями мира:

1. Original Morrowind + Tribunal + Bloodmoon — EN/RU.
2. Fullrest / Tamriel Rebuilt 25.08 (Grasping Fortune) — EN/RU.
3. Tamriel Rebuilt 26.08 (Poison Song) — EN.

Original уже поддерживает локальные MIM-растры Vvardenfell и Solstheim, 1 010 мест из MIM/ESM, EN/RU, поиск, zoom/pan, MIM-цвета статусов `unvisited` / `active` / `visited`, заметки и личные квадратные маркеры. Прогресс хранится локально в IndexedDB через Dexie и жёстко привязан к snapshot; доступны однократный импорт текущего MIM snapshot и общий переносимый JSON backup v2/import со строгой проверкой совместимости и чтением ранних v1-копий.

Текущий статус: **Этап 5 в работе; production renderer 5.1 и benchmark 5.2 завершены, локальный full render начат**. Pinned headless OpenMW pipeline строит `3×3` native batches с `5×5` scene context, поддерживает два workers, checkpoint/resume, exact provenance, lossless WebP, lower zoom и deterministic inventory. Реальный gate пяти областей прошёл: `45` native tiles за `178.977 s`, resume за `0.080 s`, `0 px` coordinate error и 60 бесшовных overlaps. Оценка полного render + pyramid на текущей машине — около `5.2 h`, разумный рабочий диапазон `5–6 h`. Poison Song basemap ещё не завершён и не прошёл finalize; catalog, immutable ready manifest и UI integration остаются следующими подэтапами.

Подробный план: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
Результаты LAND gate: [docs/adr/0001-land-renderer-spike.md](docs/adr/0001-land-renderer-spike.md).
Архитектура OpenMW exporter: [docs/adr/0002-openmw-offline-exporter.md](docs/adr/0002-openmw-offline-exporter.md).
Production pipeline и реальные измерения: [docs/stage5-openmw-production.md](docs/stage5-openmw-production.md).

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

Smoke пишет `local-data/openmw-spike/poison-song-26.08/smoke-report.json`, полный gate — `report.json`, пять `controls/*.webp` и хэш-привязанный шаблон ручной визуальной квитанции. Production runner уже реализован, но полный basemap пока не запускался. BSA/ESM/ESP/omwscripts, loose Tamriel Data/TR assets, raw PNG, WebP и reports являются локальными ignored artifacts и в Git/Docker image не входят.

### Poison Song production renderer

Нужны соседний `../morr-dev`, Docker Desktop и ImageMagick 7. Команды полностью локальные; профиль, image и encoder проверяются автоматически, вручную придумывать provenance hash не требуется:

```bash
pnpm data:poison:plan
pnpm data:poison:renderer:build
pnpm data:poison:renderer:smoke
pnpm data:poison:renderer:benchmark
```

Полный basemap пока запускается отдельно осознанным решением:

```bash
pnpm data:poison:renderer:render
pnpm data:poison:renderer:finalize
```

`render` по умолчанию использует два встроенных workers и безопасно продолжается тем же command после остановки: готовые WebP повторно проверяются по checkpoint и не рендерятся. Terminal сразу показывает setup, затем после каждой атомарной записи checkpoint печатает прогресс вида `[227/3984]`. Для последовательного деления плана доступны `--shard-count N --shard-index I`; несколько отдельных процессов не должны одновременно писать один checkpoint. Raw `544×544` PNG удаляются после публикации WebP, если явно не указан `--retain-raw`.

OpenMW warning `addAnimSource: can't find bone` означает несовпадение animation controller с уже загруженным NIF, сохраняется в `ignoredCompatibilityWarnings` и не останавливает production render. Настоящие missing mesh/texture/file, отсутствующие логи и non-zero container exit по-прежнему fail closed.

Production profile явно направляет snow/blizzard weather на существующие Bloodmoon-ресурсы `Tx_BM_Sky_Snow.dds` и `Tx_BM_Sky_Blizzard.dds`: универсальные OpenMW defaults с именами `Tx_Sky_*` отсутствуют в GOTY BSA. Контролируемая смена producer source сохраняет готовые тайлы только через отдельный `migrate-resume`; смена profile fingerprint дополнительно требует явного `--allow-profile-change`, полного совпадения `inputAudit`/`assetAudit`, byte-identical backups старого состояния и migration receipt.

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
