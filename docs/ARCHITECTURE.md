# Архитектура

## Состав системы

Morrowind Map состоит из трёх частей:

1. React/Vite web runtime загружает dataset index, manifest, каталог и sparse WebP tile pyramid.
2. Python tooling извлекает каталог TES3 и строит basemap через зафиксированный headless OpenMW renderer.
3. Локальное хранилище сохраняет пользовательский прогресс отдельно от read-only игровых datasets.

Runtime не обращается к внешним CDN или API. Шрифты, иконки, manifests и runtime artifacts обслуживаются с того же origin.

## Dataset contract

`apps/web/public/datasets/index.json` перечисляет ровно две видимые карты:

- `original-goty-hd`;
- один активный versioned dataset Tamriel Rebuilt.

Index содержит только identity, порядок и URL manifest. Manifest задаёт:

- `datasetId`, `snapshotId`, title и release metadata;
- точный профиль источников и load order;
- TES3 world projection, extent, origin и resolutions;
- content-addressed ссылки и hashes каталога, locale, tile metadata и audit;
- readiness и доступные regions.

Loader валидирует JSON schemas, identity и взаимные ссылки до открытия карты. Ошибки index, manifest, catalog, coverage или tile metadata не маскируются пустым состоянием.

## Карты

### Original GOTY HD

Original использует отдельный profile и отдельные producer modules. Его входы ограничены тремя английскими ESM и тремя одноимёнными BSA. Dataset считается зафиксированным: обычные работы с новым Tamriel Rebuilt не запускают Original renderer, catalog или publisher и не меняют его manifest.

### Tamriel Rebuilt

Активная TR-карта собирается из тех же шести base inputs и согласованной пары Tamriel Data / TR Core. Release-specific identity и hashes находятся в release config и сгенерированном lock. Новый релиз получает новый `datasetId` и `snapshotId`; подробный процесс — в [TR_UPDATE.md](TR_UPDATE.md).

## Basemap и каталог

Basemap — sparse lossless WebP pyramid `z0…z7` с нативным tile size `512×512`. Manifest объявляет top-left XYZ grid и coverage, поэтому координаты вне покрытия не создают лишние HTTP requests. Presentation уже запечён producer-ом; runtime не должен повторно менять цвет или alpha.

Каталог объединяет TES3 records по load-order semantics, включая override и deletion. Runtime получает:

- стабильные place identifiers и world coordinates;
- entrances и teleport destinations;
- region/type metadata;
- EN locale;
- audit, связанный с теми же `datasetId` и `snapshotId`.

Basemap и каталог публикуются независимо, но manifest не может смешивать artifacts разных release identities.

## Content-addressed publication

Generated artifacts публикуются в каталог, имя которого выводится из inventory hash. Готовый пакет не перезаписывается. Manifest-кандидат формируется из повторно прочитанных publication metadata, затем проверяется вместе со схемами и файлами.

Активация — последняя атомарная операция. До неё действующий index и manifest продолжают указывать на предыдущий полностью готовый dataset. Ошибка любого producer или gate оставляет активную карту без изменений.

## Browser state

URL хранит `dataset`, `region`, `x`, `y`, `z` и выбранное `place`. Входные параметры валидируются и canonicalize-ятся; Back/Forward восстанавливают meaningful navigation state без новых записей от каждого pan/zoom.

Переход с landing без явной camera открывает карту в `map.projection.center` из manifest на первом каталожном tier `z=2`. Исключение для выбранного региона `tr-mainland` — Old Ebonheart на `z=4`. Явные валидные `x/y/z` из URL всегда authoritative и не заменяются default или region focus.

Region, type, status и zoom-tier применяются ко всему каталогу. Список результатов добавляет DOM-строки последовательными batches по мере прокрутки; поиск, facet counts, map markers и общее число совпадений работают с полным отфильтрованным набором, а не только с уже отрисованным batch.

Dataset и catalog имеют явные состояния loading, missing, invalid, network error, partial failure и retry. Обычная загрузка tile requests не показывает status, spinner или перекрывающий карту overlay. Missing coverage, tile errors и retry остаются видимыми recovery-состояниями. Abort/generation guards не позволяют позднему ответу старой загрузки заменить новое состояние. Tile retry повторяет только текущий failed set и не пересоздаёт карту, camera, filters или selection.

## Пользовательские данные

IndexedDB хранит progress, notes и personal markers отдельно от read-only dataset files. Каждая запись принадлежит `datasetId`; binding дополнительно проверяет `snapshotId`.

Новый TR release обязан получить обе новые identity. Это исключает смешивание координат и записей разных snapshots. Старые записи не удаляются и не переносятся автоматически; они остаются привязаны к предыдущему dataset. JSON export/import валидируется до атомарной записи и не изменяет игровые artifacts.

При недоступном IndexedDB карта остаётся доступной read-only. Ошибка локальной записи сохраняет draft и предлагает повтор операции, не сбрасывая camera или выбранное место.
