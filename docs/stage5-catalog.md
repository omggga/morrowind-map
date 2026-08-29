# Stage 5.4 — Generic TES3 catalog pipeline

Дата фиксации результата: 2026-08-29. Статус: **выполнено на 100% для Poison Song 26.08**. Catalog quality gate закрыт, а generic browser runtime 5.5 уже подключён; Этап 5 остаётся открыт до product/browser acceptance 5.6.

## Входной snapshot

Pipeline читает игровые данные локально из соседнего `../morr-dev`; ESM и сгенерированный runtime payload не попадают в Git. Порядок плагинов фиксирован и значим:

1. `Morrowind.esm`;
2. `Tribunal.esm`;
3. `Bloodmoon.esm`;
4. `Tamriel_Data.esm`;
5. `TR_Mainland.esm`.

Каждый input связан размером и SHA-256. `MAST` разрешаются только в уже загруженные masters; ordinal identity ссылок повторяет TES3/OpenMW semantics. Advertised master sizes проверяются fail closed, кроме одной hash-bound известной metadata-разницы `TR_Mainland.esm → Tamriel_Data.esm`. Строки декодируются строгим Windows-1252 до первого NUL, а engine identity использует только ASCII `A–Z` case folding.

## Effective-record merge

Merge идёт строго по load order и отдельно моделирует metadata CELL и находящиеся в их record stream references:

- `CELL`, `DOOR`, `LAND` и `REGN` получают last-wins overrides, deletion tombstones и последующее resurrection;
- CELL override без optional `RGNN` не стирает унаследованный region; CELL deletion удаляет metadata и накопленные references до явного resurrection;
- `FRMR` является полной новой версией placed reference, поэтому отсутствующие subrecords не наследуются от прежней версии;
- reference identity учитывает master ordinal и local object index; deleted references удаляются из effective world;
- `MVRF + CNDT + FRMR` проверяются как единая moved-reference версия; несовпадение identity останавливает build;
- teleport публикуется только после разрешения effective placed reference, base `DOOR` и destination `CELL`;
- records с TES3 ignored flag не участвуют в semantic merge и отдельно учитываются audit.

Poison Song audit зафиксировал `9 336` raw / `9 075` effective CELL, `1 039` raw / `984` effective DOOR и `1 706 102` raw / `1 706 101` effective placed references. Для этого snapshot deletion и moved-reference counters равны нулю, но соответствующие ветви являются частью generic model и покрыты synthetic tests.

## Place и Entrance model

Из effective world создаются две категории places:

- teleport entrances группируются по одной destination interior CELL;
- одноимённые named exterior CELL группируются только внутри связной 8-neighbor component.

Один interior place может иметь несколько входов. Его `mapPosition` выбирается как medoid среди реальных entrances, а не как синтетический центр CELL. Exterior place получает позицию из своей связной component. Десять exterior-to-exterior teleports не превращаются в дублирующие places и явно отражены в exclusion audit.

ID не зависят от порядка JSON:

- `Place.id` выводится из dataset и identity destination CELL либо exterior component;
- `Entrance.id` выводится из dataset, origin plugin и локального reference index.

Так сохраняются разные физические входы с одинаковым названием, а progress можно привязывать к stable Place ID. Все ID dataset-scoped; глобальная уникальность entrances, сортировка, cell/coordinate consistency и соответствие locale rows проверяются перед публикацией.

EN primary names берутся из effective CELL. Aliases содержат только отличающиеся исторические/effective spellings, с deterministic normalization и сортировкой. В текущем Poison Song snapshot таких отличающихся aliases `0`; сам alias contract остаётся активным. Типы назначаются версионированными правилами на основе названия, base door и связанного interior evidence. Регион определяется fail closed по source plugin effective `LAND` каждой exterior cell; mixed/unmapped component запрещена.

## Результат

| Метрика | Значение |
| --- | ---: |
| Places | `4 085` |
| Interior places | `3 755` |
| Named exterior places | `330` из `417` named CELL |
| Entrances | `4 902` |
| Multi-entrance places | `697` |
| Entrances в multi-entrance places | `1 844` |
| Максимум entrances у place | `14` |
| EN aliases | `0` |

Распределение places по map region: `941` Vvardenfell, `92` Solstheim, `3 052` TR mainland. Catalog использует `14` типов: ancestral tomb, cave, Dwemer ruin, guild, house, landmark, mine, other, settlement, ship, shop, shrine, stronghold и temple.

Pipeline выпускает canonical UTF-8 JSON с одним завершающим LF:

```text
local-data/catalog-production/poison-song-26.08/
  locations.json
  locales/en.json
  catalog-audit.json
```

`local-data` ignored. После `prepare` runtime artifacts и audit появляются в отдельных immutable trees по catalog inventory SHA-256:

```text
apps/web/public/datasets/generated/poison-song-26.08/catalogs/<inventory>/
  locations.json
  locales/en.json

apps/web/public/datasets/metadata/poison-song-26.08/catalogs/<inventory>/
  catalog-audit.json
```

Publisher запрещает выход за publication root и symlinks, создаёт новый version directory через staging rename, переиспользует только побайтно совпадающий immutable target и иначе завершается ошибкой.

## Deterministic audit

`catalog-audit.json` связывает:

- exact ordered inputs, masters, размеры и SHA-256;
- hashes extractor implementation и всех policy descriptors;
- effective-record, resolution, grouping, type и region counts;
- exclusion policy и число недостижимых interior CELL;
- SHA-256 и размеры `locations.json` / `locales/en.json`;
- canonical serialization, ID uniqueness, coordinate extent и semantic validation gates.

Validator не доверяет сохранённым счётчикам: он заново читает artifacts, проверяет hashes и schema/semantics, пересчитывает artifact-derived metrics и сравнивает их с audit и pinned snapshot expectations. Повторный build при неизменных inputs, implementation и policies даёт те же bytes и inventory SHA-256.

## Воспроизведение

Из корня репозитория:

```bash
pnpm data:poison:catalog:build
pnpm data:poison:catalog:validate
pnpm data:poison:catalog:prepare
```

`build` требует только сохранённые ESM; Docker/OpenMW для catalog не запускается. `validate` не читает ESM заново, но проверяет локальный bundle, текущую identity extractor и pinned audit. `prepare` сначала выполняет ту же строгую validation, затем публикует content-addressed artifacts.

## Что остаётся

5.4 и 5.5 завершены. Prepared catalog и WebP pyramid загружаются единым manifest-driven dataset loader: локали объявляются самим manifest-ом, Poison Song использует EN catalog, а sparse coverage предотвращает запросы отсутствующих tiles. Poison Song manifest имеет статус `ready`. В 5.6 остаётся формально принять network-free browser workflow, включая search, statuses, notes, personal markers и persistence после reload; до этого Этап 5 целиком остаётся в работе.
