# Morrowind Map

Локальная интерактивная карта Morrowind с тремя независимыми версиями мира:

1. Original Morrowind + Tribunal + Bloodmoon — EN/RU.
2. Fullrest / Tamriel Rebuilt 25.08 (Grasping Fortune) — EN/RU.
3. Tamriel Rebuilt 26.08 (Poison Song) — EN.

Original уже поддерживает локальные MIM-растры Vvardenfell и Solstheim, 1 010 мест из MIM/ESM, EN/RU, поиск, zoom/pan, MIM-цвета статусов `unvisited` / `active` / `visited`, заметки и личные квадратные маркеры. Прогресс хранится локально в IndexedDB через Dexie и жёстко привязан к snapshot; доступны однократный импорт текущего MIM snapshot и общий переносимый JSON backup v2/import со строгой проверкой совместимости и чтением ранних v1-копий.

Текущий статус: **Этап 4.5 — OpenMW renderer spike пройден**. Собственный LAND parser/VFS доказал точную геопривязку, а pinned headless OpenMW exporter воспроизводимо отрендерил пять `512×512` control WebP со зданиями, мостами, деревьями, стенами, водой и alpha geometry при отключённых actors и `Mask_Object` runtime objects. Итоговый gate: `0 px` coordinate error, `0` missing resources в 40 логах, 4/5 побайтно идентичных повторов и только 8 alpha-edge pixels в Nan Iban в пределах узкого tolerance, невидимые швы и подтверждённый Linux/amd64 `llvmpipe` pipeline. Полный Poison Song basemap намеренно ещё не генерировался; Fullrest и Poison Song в UI пока открывают координатные заглушки.

Подробный план: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
Результаты LAND gate: [docs/adr/0001-land-renderer-spike.md](docs/adr/0001-land-renderer-spike.md).
Архитектура OpenMW exporter: [docs/adr/0002-openmw-offline-exporter.md](docs/adr/0002-openmw-offline-exporter.md).

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

Smoke пишет `local-data/openmw-spike/poison-song-26.08/smoke-report.json`, полный запуск — `report.json`, пять `controls/*.webp` и хэш-привязанный шаблон ручной визуальной квитанции. Полный basemap создаётся отдельным будущим этапом; BSA/ESM/ESP/omwscripts, loose Tamriel Data/TR assets, raw PNG, WebP, reports и заполненная visual receipt являются локальными ignored artifacts и в Git/Docker image не входят.

## Локальный запуск

Требуются Node.js 24+ и pnpm 11.

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

Или одной командой: `pnpm verify`. Python pipeline и LAND renderer fixture tests входят в `pnpm test`; полная генерация игровых данных запускается отдельно и в CI не выполняется.
