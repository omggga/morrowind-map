# Morrowind Map — план реализации

- Дата фиксации: 2026-08-26
- Статус: утверждённый план локальной версии
- Целевой репозиторий: `omggga/morrowind-map`

## 1. Цель

Создать локальное браузерное приложение с единой входной страницей и тремя независимыми версиями карты:

1. **Original GOTY** — Morrowind, Tribunal и Bloodmoon; названия EN/RU.
2. **Fullrest snapshot** — Tamriel Rebuilt 25.08 Grasping Fortune и фактически активные компоненты сборки Fullrest; названия EN/RU.
3. **Poison Song snapshot** — Tamriel Rebuilt 26.08 Poison Song с Tamriel Data 26.08; названия EN.

Приложение должно работать без внешних map/CDN-зависимостей после подготовки datasets и предоставлять:

- landing page с выбором версии;
- pan, zoom, reset view и координаты курсора;
- поиск по названиям и aliases;
- переключение языка там, где перевод доступен;
- состояния `unvisited`, `active`, `visited`;
- заметки к локациям;
- создание, редактирование и удаление personal markers;
- импорт текущих данных Morrowind Interactive Map (MIM);
- локальное автосохранение;
- переносимый JSON export/import;
- запуск через Docker.

## 2. Границы первого локального релиза

В первый релиз не входят:

- регистрация, OAuth и синхронизация между устройствами;
- публичный сайт и домен;
- серверная БД;
- генерация тайлов по HTTP-запросу;
- автоматическое объединение прогресса разных версий;
- полный редактор маршрутов;
- подробные планы всех интерьеров и Mournhold;
- собственный полноценный NIF/игровой renderer с нуля.

Архитектура обязана позволить позднее добавить backend и OAuth без переделки domain model, карты и формата datasets.

## 3. Текущее состояние исходных данных

### 3.1 Original GOTY

Внешний локальный каталог `morr-dev/bsa` содержит согласованный английский GOTY-набор:

| Файл | Размер | SHA-256 |
| --- | ---: | --- |
| `Morrowind.esm` | 79 837 557 | `5c3c8c2cbd20e25901b59b3ece33d36b7ef0e3d60ad8d11828bcc61a5ead1647` |
| `Tribunal.esm` | 4 565 686 | `2ace511f23cc2a9ddd5f3aa59c7919789b9378cf4b17c8ae3375dd6b782f3f2b` |
| `Bloodmoon.esm` | 9 631 798 | `bd27090d0e6ad4c1bf1abc83f1a2dac56fcc82cae7bfe8263c413fb301801357` |

Там же находятся целые и структурно проверенные:

- `Morrowind.bsa` — 11 090 записей;
- `Tribunal.bsa` — 1 174 записи;
- `Bloodmoon.bsa` — 1 545 записей.

Russian OpenMW-style `.cel` sidecars из `morr-dev/game/Data Files` практически полностью покрывают именованные CELL базовой тройки. Для Original EN названия берутся из английских ESM, для RU — из `.cel` и MIM.

MIM предоставляет:

- Vvardenfell raster `3300×3800`;
- отдельный Bloodmoon raster `3072×3840`;
- 864 Morrowind POI;
- 69 Bloodmoon POI;
- текущий прогресс: 933 записи — 741 visited, 192 unvisited, 0 active;
- одну непустую заметку;
- 6 personal markers;
- transport routes;
- цвета и параметры отображения из `tes.ini`.

### 3.2 Fullrest 25.08

`morr-dev/game/Data Files` содержит установленный профиль Fullrest 5.0.15:

- локализованную base trio;
- `Tamriel_Data.esm` 25.05;
- `TR_Mainland.esm` 25.08 Grasping Fortune;
- `TR_Factions.esp`;
- `MFR.esm` и `MFR_TR_patch.esp`;
- `Cyr_Main.esm` 25.05a;
- `Sky_Main.esm` 25.05;
- grass plugins;
- `.cel/.top/.mrk` translation sidecars.

Этот набор нельзя смешивать с английской base trio из `morr-dev/bsa`: base ESM имеют разные размеры и хеши. Fullrest snapshot должен использовать собственную локализованную base trio из `game/Data Files`.

Для base + TD25 + TR25 без MFR все непустые английские CELL names имеют Russian `.cel` pair. У MFR остаётся отдельный gap: 378 уникальных кириллических CELL names не имеют локального английского соответствия.

Точный порядок подтверждён сохранённым `game/Fullrest-Provenance/OpenMW_Config/openmw.cfg`; MGE-профиль сохранён рядом в `MGE.ini`. В `Data Files/distantland/world.dds` также есть готовый объединённый terrain preview 2048×2048. Открытым остаётся языковое решение для 378 MFR-only кириллических CELL names и выбор между preview и собственным более детальным renderer.

### 3.3 Poison Song 26.08

Локально присутствуют:

- `TR_Mainland.esm` 26.08, SHA-256 `661c96c6aa5e517d897f8b9de93c814d2aca16fd17b6e4ce7869486e3737064b`;
- `TR_Factions.esp`;
- optional Firemoth patch;
- полный Tamriel Data 26.08 SD package;
- vanilla GOTY ESM/BSA.

`Tamriel_Data.esm`:

- HEDR `Tamriel Data Version 26.08`;
- размер 17 199 325;
- SHA-256 `e94ca3a5c62e0228ac3782e813cae58c4e10da2e9e8b7611e0a8f5ff9a98d06f`.

Проверка effective exterior scope Poison Song показала:

- 202 реально используемые LAND texture paths, missing `0`;
- 6 113 уникальных direct exterior MODL paths, missing `0`;
- 10 572 teleport references извлекаются;
- все используемые teleport base records разрешаются.

Между размером TD26, записанным в master metadata core TR, и фактическим TD26 есть небольшое расхождение 776 байт. Это фиксируется в provenance и проверяется при первом полном OpenMW/load-order smoke test; asset coverage оно не блокирует.

## 4. Обязательные дополнительные входы

Для начала Original и Poison Song дополнительных файлов не требуется.

Для продолжения Fullrest дополнительных файлов не требуется: профиль, masters, loose assets, Cyr/Sky и сохранённый MGE distant-land raster уже находятся в `morr-dev/game`. До реализации нужно выбрать только политику EN fallback и целевой basemap.

Для Fullrest EN необходимо выбрать одно решение:

1. найти английские источники MFR-модов;
2. подготовить ручной mapping 378 names;
3. временно использовать отмеченный RU fallback;
4. исключить MFR из EN-профиля, явно назвав его не-exact.

Желательные, но не блокирующие материалы:

- pristine English MIM package для буквального воспроизведения его английских формулировок;
- игровые `Data Files/Fonts`, если нужен именно внутриигровой Morrowind font;
- Fullrest screenshots/settings для визуальной калибровки.

MIM использует системные `MS Sans Serif 8` и `Arial 8`, а не поставляемый игровой font. По умолчанию дизайн имитирует MIM с открытым webfont, близким к `MS Sans Serif`.

## 5. Архитектурные решения

### 5.1 Frontend

- React;
- TypeScript `strict`;
- Vite SPA без SSR;
- OpenLayers;
- собственный CSS/theme без тяжёлого component framework;
- i18next только для UI strings;
- Fuse.js для локального поиска.

OpenLayers выбран из-за first-class custom projection, extent, tile grid, origin и resolutions. TES3 `(x,y)` остаются каноническими координатами без fake latitude/longitude.

React управляет panels/dialogs/search/settings. Один imperative экземпляр `ol/Map` управляет raster/vector layers; отдельный React DOM component на каждый marker не создаётся.

### 5.2 Локальное хранение

- IndexedDB через Dexie;
- schema migrations;
- transactional import;
- domain-level JSON export/import;
- запрос persistent browser storage после первого meaningful save.

Bundled JSON является immutable и не может незаметно перезаписываться браузером. Поэтому статические locations/locales хранятся в JSON, а mutable progress — в IndexedDB. JSON остаётся переносимым backup format.

Storage изолируется интерфейсом `ProgressRepository`. Будущий server/OAuth adapter реализует тот же контракт.

### 5.3 Offline tooling

- Python data pipeline для TES3/MIM extraction;
- JSON Schema как межъязыковой контракт;
- libvips/Sharp для pyramids/WebP;
- pytest для extractor/importer;
- OpenMW только как возможный offline scene renderer.

### 5.4 Проверки

- Vitest — domain, coordinates и storage logic;
- React Testing Library — panels/search/import dialogs;
- Playwright — настоящий Canvas/map workflow и visual fixtures;
- dataset validator — manifests, hashes, references, localization и resources.

## 6. Планируемая структура репозитория

```text
morrowind-map/
├── IMPLEMENTATION_PLAN.md
├── README.md
├── .gitignore
├── package.json
├── pnpm-workspace.yaml
├── apps/
│   └── web/
├── packages/
│   └── contracts/
├── tools/
│   ├── data-pipeline/
│   ├── mim-importer/
│   ├── land-renderer/
│   └── tile-pipeline/
├── datasets/
│   ├── index.json
│   └── manifests/
├── tests/
│   ├── fixtures/
│   └── e2e/
├── docker/
└── docs/
    └── adr/
```

Game/mod inputs остаются вне Git и подключаются через ignored `.env.local` paths. Сгенерированные полные tiles также не коммитятся.

## 7. Snapshot contract

Stable UI key и immutable content snapshot разделяются:

```text
mapKey                 snapshotId
original               original:goty:<profileHash>
fullrest-old           fullrest:tr-25.08:<profileHash>
poison-song            tr:poison-song-26.08:<profileHash>
```

Каждый manifest фиксирует:

- schema version;
- map key и release/build;
- ordered content files;
- ordered data directories;
- registered BSA;
- SHA-256 всех ESM/ESP/BSA;
- optional modules;
- extractor version;
- renderer version/settings;
- TES3 extent, cell size и tile grid;
- URLs и hashes locations/locales/tiles;
- localization completeness;
- provenance и known warnings.

Язык не входит в snapshot ID. Добавление RU для Poison Song не создаёт четвёртую карту.

Предварительные profiles:

### Original

```text
Morrowind.esm
Tribunal.esm
Bloodmoon.esm
```

Tribunal входит в dataset, но Mournhold позднее получает отдельный inset/submap как quasi-interior.

### Fullrest

Состав создаётся только из подтверждённого профиля. Grass plugins не участвуют в semantic location catalog. `CarryWeightStonks.esp` исключается как не относящийся к карте.

### Poison Song

```text
Morrowind.esm
Tribunal.esm
Bloodmoon.esm
Tamriel_Data.esm 26.08
TR_Mainland.esm 26.08
TR_Factions.esp        # если подтверждено выбранным profile
```

Default Firemoth mode — TR-integrated. Vanilla Firemoth patch включается только явно.

## 8. Domain model локаций

`Place` и `Entrance` разделяются:

```ts
interface Place {
  id: string
  datasetId: string
  canonicalPlaceId?: string
  type: PlaceType
  names: Partial<Record<Locale, string>>
  aliases: string[]
  entrances: Entrance[]
  source: RecordProvenance
}

interface Entrance {
  id: string
  x: number
  y: number
  exteriorCell: [number, number]
  sourcePlugin: string
  sourceRef: string
}
```

Прогресс относится к `Place`, а не к конкретной двери. Один dungeon может иметь несколько entrances. Одинаковое переведённое имя или близкая координата не считаются identity.

`canonicalPlaceId` используется только для проверенных межверсионных соответствий и не заменяет dataset-scoped `id`.

## 9. Data extraction pipeline

Pipeline выполняет:

1. потоковое чтение ESM/ESP;
2. применение load order, overrides и deleted records;
3. извлечение `CELL`, `LAND`, `LTEX`, DOOR и teleport references;
4. разрешение base records и destination cells;
5. построение named exterior places и interior destinations;
6. группировку нескольких entrances одного place;
7. классификацию settlement/cave/mine/tomb/ruin/stronghold/house/shrine/other;
8. присоединение `.cel` EN/RU pairs;
9. aliases и нормализацию поиска;
10. resource resolution через ordered loose directories и BSA fallback;
11. генерацию locations/locales/manifests/audit reports;
12. fail-fast validation unresolved effective resources.

`.top` и `.mrk` не используются как основной location catalog: они преимущественно относятся к dialogue topics/quest text. Для названий CELL основным translation input является `.cel`.

Сотни тысяч raw placed references нужны только offline. В browser dataset попадает компактный каталог places/entrances.

## 10. MIM import

Importer читает:

- `mwmain.gdb`;
- `user.gdb`;
- `markers.gdb`;
- `routes.gdb`;
- `tes.ini`.

Mapping выполняется по сочетанию ordinal position, имени, coordinates и target snapshot. Простой словарь `name → status` запрещён из-за повторяющихся названий.

Первичный lossless-import направляется в Original snapshot: ordinal identity `mwmain.gdb` и текущий каталог MIM принадлежат именно vanilla-карте, поэтому только здесь соответствие можно доказать без догадок. При появлении каталога Fullrest доказанно совпадающие places переносятся туда отдельной migration operation с явной таблицей `sourcePlaceId → targetPlaceId`; прямое присваивание MIM ordinal IDs профилю Fullrest запрещено.

Personal markers импортируются в raw TES3 world coordinates.

Импорт обязан быть идемпотентным, записывать provenance и не перетирать более новые ручные изменения пользователя.

## 11. Progress model

```ts
interface Progress {
  profileId: string
  datasetId: string
  placeId: string
  status: 'unvisited' | 'active' | 'visited'
  note?: string
  updatedAt: string
  provenance?: ProgressProvenance
}
```

Правила:

- EN/RU разделяют один progress;
- три snapshots имеют независимый progress;
- `active` не переносится автоматически;
- `visited` копируется только при exact migration mapping;
- old removed places сохраняются в export/archive;
- personal marker по умолчанию scoped к dataset;
- переход к server sync не меняет domain JSON.

Portable backup:

```json
{
  "schemaVersion": 2,
  "exportedAt": "...",
  "datasets": {},
  "progress": [],
  "customMarkers": []
}
```

## 12. Rendering strategy

### 12.1 Временные basemaps

Для раннего vertical slice:

- Original Vvardenfell — MIM raster;
- Original Solstheim — отдельный MIM Bloodmoon raster;
- Poison Song — временный reference raster/provider;
- Fullrest — terrain preview до exact assets.

Basemap является сменным adapter. Координаты, IDs, markers, search и progress от него не зависят.

Для Original зафиксированы геопривязки:

- Vvardenfell MIM: extent `[-125000, -130000, 175000, 220000]`;
- Bloodmoon: точный LAND extent `[-229376, 114688, -131072, 237568]`, 32 TES3 units/pixel;
- ESM-backed точки используют прямые canonical coordinates;
- MIM-only Bloodmoon points используют north-up least-squares transform по 55 дверям: RMS 469, median 271 TES3 units.

### 12.2 Owned LAND renderer

Первый собственный renderer читает:

- `LAND.VHGT`;
- `VNML`;
- `VCLR`;
- `VTEX`;
- `LTEX`;
- воду и береговую линию.

Renderer имеет фиксированные world-to-pixel settings, освещение и глобальный MIM-like color grade. Он полностью headless и воспроизводим, но не показывает buildings, trees, bridges и другие placed statics.

Spike рендерит пять контрольных областей:

- Balmora;
- Old Ebonheart;
- Othrenis;
- Gorne;
- Nan Iban.

Acceptance criteria:

- корректный VHGT delta decoding;
- корректная VTEX block transposition;
- shared cell edges совпадают;
- 0 unresolved effective LAND textures;
- world coordinate → pixel error не более 1 native pixel;
- нет tile seams;
- повторный render с теми же inputs даёт одинаковый hash;
- пользователь принимает или отклоняет визуальный результат без statics.

### 12.3 OpenMW scene renderer

Если LAND-only выглядит слишком пусто, выполняется отдельный OpenMW spike:

1. pin release/commit OpenMW;
2. собрать isolated config из snapshot manifest;
3. отрендерить 3×3 cells через LocalMap/offscreen path;
4. отключить UI, fog, weather variability, actors и dynamic objects;
5. проверить roofs, bridges, trees, alpha geometry и water;
6. проверить cell streaming/gutters/seams;
7. доказать reproducibility и headless Linux execution;
8. выбрать UI automation либо небольшой offline exporter на базе OpenMW.

Полный NIF renderer с нуля не входит в план.

### 12.4 Tile format

- native tile `512×512`;
- WebP delivery, ориентир quality 85–90;
- lossless intermediate/master;
- fixed top-left grid origin;
- render gutter + crop;
- lower zoom строится из четырёх children;
- giant monolithic bitmap не создаётся;
- immutable path `tiles/<snapshotId>/<z>/<x>/<y>.webp`;
- tiles keyed одновременно content hash и renderer hash.

## 13. UI/UX

### Landing page

Три cards показывают:

- название/version;
- EN/RU availability;
- regions/modules;
- visited/active counts;
- дату последнего открытия;
- точный snapshot build;
- dataset readiness/warning.

### Map screen

- fullscreen map;
- responsive sidebar;
- version, region и language selectors;
- search и filters;
- legend;
- zoom/reset controls;
- cursor/world coordinates;
- snapshot information;
- JSON import/export;
- URL state для version/region/x/y/z/lang.

Location interaction:

- name, type и aliases;
- EN/RU display;
- status buttons;
- note;
- entrances/coordinates;
- source plugin/provenance.

Personal marker создаётся через context action/right click либо long press и поддерживает rename, note, move, delete и явное copy to another snapshot.

### MIM visual language

Проверенная palette:

```text
visited   #FFA040
active    #FF80FF
unvisited #FFF19B
personal  #40FF40
```

Квадратные markers рисуются как Canvas/SVG primitives и остаются резкими при zoom. Labels не запекаются в tiles. Их язык меняется динамически; declutter применяется преимущественно к text labels.

## 14. Search

Для активного dataset строится небольшой Fuse.js index по:

- выбранному locale name с максимальным весом;
- alternate locale name;
- aliases;
- type;
- cell/plugin identifiers;
- personal marker names.

Нормализация: Unicode NFKC, locale-aware lowercase, collapse whitespace и русский вариант `ё/е`. Search result всегда показывает snapshot/region и zooms к primary/selected entrance.

## 15. Docker/runtime

Frontend собирается Vite multi-stage image и обслуживается Nginx.

```text
Node builder → static dist → Nginx runtime
                           ↘ read-only datasets volume
```

Правила:

- Node/toolchain отсутствует в runtime image;
- большие datasets/tiles монтируются read-only и не запекаются в app layer;
- renderer является offline build job, не runtime service;
- SPA fallback через `try_files`;
- immutable cache для hashed JS/CSS/tiles;
- `index.html` и mutable `datasets/index.json` получают `no-cache`;
- same-origin JSON/tiles, без CORS/CDN;
- fixed local origin сохраняется между container restarts, чтобы IndexedDB оставался доступным.

## 16. Verification strategy

Обязательные automated checks:

- TES3 XY ↔ pixel ↔ tile round-trip, включая bounds и negative coordinates;
- top-left origin/Y inversion/off-by-one boundaries;
- смена трёх manifests сохраняет raw center, где он допустим;
- Place/Entrance grouping и duplicate-name cases;
- status state machine;
- Dexie migrations и atomic JSON import;
- EN/RU/`ё-е` search;
- reload сохраняет progress/notes/personal markers;
- MIM duplicate-safe import и idempotency;
- E2E pan/zoom/click/search/language/version;
- deterministic visual fixtures в pinned Playwright container;
- Docker smoke test;
- asset audit: 0 unresolved effective LAND textures;
- OpenMW mode: 0 unresolved effective direct exterior models.

Полные игровые assets и giant tile generation не запускаются в публичном/обычном CI. Parser tests используют synthetic binary fixtures, а локальная dataset verification работает против external ignored inputs.

## 17. Этапы реализации

### Этап 0 — репозиторий и план

Status: complete.

Deliverables:

- private `omggga/morrowind-map`;
- `IMPLEMENTATION_PLAN.md`;
- `.gitignore`;
- короткий `README.md`;
- первый commit `docs: add implementation plan`;
- push ветки `main`.

### Этап 1 — contracts и skeleton

Status: complete.

Deliverables:

- pnpm workspace;
- Vite/React/TypeScript strict;
- OpenLayers custom `TES3:WORLD` projection;
- shared schemas/contracts;
- dataset index и три manifests-заглушки;
- CI install/typecheck/lint/unit/build.

Exit: landing показывает три cards, каждая открывает пустую карту с корректными TES3 coordinates.

### Этап 2 — Original vertical slice

Status: complete (2026-08-26): 933 MIM markers + 77 ESM-only destinations, full EN/RU coverage.

Deliverables:

- MIM Vvardenfell/Bloodmoon rasters;
- Original location catalog;
- EN/RU;
- square markers;
- search;
- zoom/pan/place panel.

Exit: Original функционально работает без user persistence.

### Этап 3 — progress и MIM import

Status: complete (2026-08-26): Dexie schema v3, real MIM snapshot, local editing and portable backup verified end-to-end.

Deliverables:

- Dexie schema/migrations;
- statuses, notes, personal markers;
- MIM importer;
- JSON export/import;
- persistence/reload behavior.

Реализованный результат:

- `progress`, `customMarkers`, `importReceipts` и snapshot bindings хранятся в dataset-scoped Dexie tables; schema v2 мигрирует ранние unbounded receipt IDs, а v3 запрещает неявно показывать данные в другом snapshot;
- данные из pre-v3 IndexedDB требуют однократного явного подтверждения snapshot; смена manifest под тем же dataset ID требует отдельной migration/archive operation;
- текущие `user.gdb`/`markers.gdb` строго декодируются как CP1251 и связываются с `mwmain.gdb` по `region + zero-based ordinal` после проверки count/name layout;
- артефакт содержит 933 статуса (741 visited, 192 unvisited), одну заметку и 6 personal markers;
- pinned `mwmain.gdb` layout guards ordinal IDs; mapping version `mim-progress-v2` и SHA-256 шести исходных GDB входят в deterministic source fingerprint;
- receipt делает повтор того же MIM import no-op; manual provenance защищает последующие правки;
- tombstones не дают удалённым импортированным markers появиться после нового snapshot;
- общий JSON backup v2 охватывает все зарегистрированные datasets; export отказывается молча терять или перемаркировать данные, если snapshot metadata отсутствует/не совпадает; строгий legacy reader переносит ранние v1 backup;
- note/marker drafts пишутся синхронно в маленький localStorage recovery journal и debounce-сохраняются в Dexie, поэтому активное поле переживает немедленный reload;
- restore до единой write transaction проверяет schema, точное совпадение `datasetId → snapshotId` и известные place IDs открытого каталога, затем merge-ит записи по хронологическому `updatedAt`;
- browser smoke подтвердил MIM import, duplicate protection, JSON export/import, EN/RU UI, status/note/marker persistence после reload и mobile layout.

Exit: текущие 741 visited, одна note и 6 personal markers воспроизводятся без duplicate-name loss.

### Этап 4 — LAND renderer spike

Status: complete (2026-08-27): deterministic LAND/VFS oracle принят, финальный basemap эскалирован к OpenMW.

Deliverables:

- LAND/LTEX parser;
- ordered loose/BSA VFS;
- пять control renders;
- WebP tile pipeline;
- coordinate/seam/determinism report;
- решение LAND-only versus OpenMW escalation.

Реализованный результат:

- strict TES3 record, LAND/LTEX и BSA parsers, ordered loose/BSA VFS и plugin-scoped LTEX resolution;
- полный Poison Song audit: 3 986 effective LAND cells, 365/365 plugin-scoped VTEX references, unresolved 0;
- пять native `512×512` lossless WebP по сетке 16 world units/pixel;
- world/pixel round-trip error 0; 60 shared edges проверены, максимальный source delta равен одному VHGT quantum (8 units);
- два независимых полных запуска дали побайтно одинаковые пять WebP и renderer fingerprint;
- сравнение Balmora с MIM и всех пяти areas с UESP подтвердило terrain alignment, но показало неприемлемую потерю buildings/bridges/trees/statics;
- LAND renderer остаётся coordinate/resource oracle и fallback; owned basemap переходит к bounded OpenMW offscreen/exporter spike.

Подробности и hashes: `docs/adr/0001-land-renderer-spike.md`.

### Этап 4.5 — OpenMW renderer spike

Status: complete (2026-08-27): все automated и hash-bound visual checks пройдены; полный Poison Song basemap намеренно не генерировался.

Цель: проверить, может ли ограниченный headless/offscreen pipeline на базе OpenMW дать воспроизводимую полноценную подложку со статическими объектами, сохранив доказанную на Этапе 4 координатную модель.

Deliverables:

- pinned release/commit OpenMW и воспроизводимый способ сборки;
- isolated Poison Song 26.08 profile с точным load order и asset override order;
- рендер тех же пяти контрольных областей для прямого сравнения с LAND/MIM/UESP;
- roofs, buildings, bridges, trees, walls, water и alpha geometry при отключённых UI, actors, fog, weather variability и dynamic objects;
- фиксированные orthographic camera, lighting, world-to-pixel transform и MIM-like color grade;
- native `512×512` WebP с render gutters и crop без tile seams;
- отчёт по resource resolution, coordinate alignment, reproducibility и headless Linux/Docker execution;
- решение между OpenMW UI automation и небольшим offline exporter на базе OpenMW.

Реализованная архитектура:

- выбран небольшой offline exporter patch поверх официального OpenMW `openmw-0.51.0`, commit `f4bec41444214a7903bebd178389ca22ca13f646`; UI automation отклонена как источник лишней вариативности камеры, масштаба UI, input timing и framebuffer capture;
- build закреплён на `linux/amd64`, base image `ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517` и Ubuntu package snapshot `20260826T000000Z`; Docker label и runtime manifest проверяют commit, platform, base image, snapshot и renderer fingerprint;
- каждый render получает отдельный generated OpenMW profile. Data override order: vanilla `bsa` → Tamriel Data 26.08 `00 Data Files` → Poison Song `00 Core/Data Files`; archives: `Morrowind.bsa` → `Tribunal.bsa` → `Bloodmoon.bsa`; render content: base trio → `Tamriel_Data.esm` → `TR_Mainland.esm`;
- `Tamriel_Data.omwscripts` и `tamrielrebuilt.omwscripts` остаются pinned/fingerprinted source inputs, но исключены из статического render profile: в предоставленных distributions отсутствуют указанные ими Lua resources, а UI, actors и dynamic gameplay не входят в задачу exporter;
- `TR_Factions.esp` и Firemoth patch намеренно не входят в bounded core profile; все pinned ESM/BSA/omwscripts и целиком все три asset trees fingerprint-ятся до запуска;
- OpenMW LocalMap scene используется с orthographic north-up camera, fixed lighting и cull mask `Scene | SimpleWater | Terrain | Static`; `Mask_Object` (items/containers и прочие runtime objects), UI, actor/player, sky/weather, fog и shadows исключены, а здания/деревья/двери/activator geometry остаются в OpenMW `Mask_Static`;
- exporter создаёт raw `544×544` PNG на world extent `8704×8704`: центральная TES3 CELL остаётся `8192×8192`, то есть `16` world units/pixel, и окружена render gutter по `16` pixels (`256` world units) с каждой стороны;
- host pipeline делает точный crop `16 px` до native `512×512`, применяет детерминированный MIM-like grade и пишет lossless WebP; соседние независимые renders сравниваются по всему общему raw overlap `32 px`;
- для Balmora, Old Ebonheart, Othrenis, Gorne и Nan Iban выполняются center/east/north renders, повторный center render и проверки resource logs, runtime camera transform, содержательности изображения, bounded raw-overlap seam deltas и побайтной воспроизводимости; hashes всего seam evidence входят в обязательную визуальную квитанцию;
- контейнер запускается без сети, с read-only root filesystem и game mounts, без capabilities, с `no-new-privileges`, Xvfb и Mesa `llvmpipe`; профиль и output находятся только в ignored `local-data/openmw-spike/poison-song-26.08`.

Команды проверки:

```bash
# Pinned Docker build и первый Balmora smoke.
python3 -m tools.openmw_renderer.spike --smoke-only

# Повторный smoke на уже собранном образе.
python3 -m tools.openmw_renderer.spike --skip-build --smoke-only

# Полный gate: 15 primary/relation renders и 5 independent repeats.
python3 -m tools.openmw_renderer.spike --skip-build
```

`smoke-report.json` доказывает только работоспособность одного capture и не закрывает gate. Канонический `report.json` полного запуска подтверждает пять controls, реальный runtime world-to-pixel transform с ошибкой не более одного native pixel, ограниченные raster deltas соседних gutter overlaps, идентичные repeat WebP/RGBA, отсутствие missing resource messages, непустое изображение и Linux/amd64 `llvmpipe` runtime. Визуальное наличие roofs, buildings, bridges, trees, walls, water и alpha geometry отдельно сверяется с LAND/MIM/UESP references; receipt связана с profile/execution fingerprints, WebP/native hashes и полным seam evidence fingerprint.

Фактический результат: **pass**. Образ `sha256:d96ddae3e12196d6b624ffb98dd87e721e3ba6c2a04ce1b410b02fe0e39e3a5b` воспроизводимо выполнил 20 изолированных captures. Четыре repeat WebP/native/graded RGBA совпали побайтно; в Nan Iban изменились 8 из 262 144 alpha-edge pixels (`0.000030518` fraction, `0.000033379/255` mean delta, `4/255` max delta), что укладывается в заранее заданный узкий tolerance. Maximum runtime coordinate error `0 px`; missing resources `0` в 40 проверенных логах. Для десяти east/north overlaps худшие raster deltas составили `0.319738` differing fraction, `0.281264/255` mean absolute channel delta и `25/255` maximum channel delta — ниже зафиксированных пределов, без видимого шва при review в native resolution. Visual receipt подтвердила весь набор statics и LAND/MIM/UESP reference coverage.

Решение quality gate: для дальнейшего basemap используется bounded offline exporter поверх OpenMW, а не UI automation. Этап 5 разблокирован, однако в рамках Этапа 4.5 полный Poison Song basemap не создавался.

Архитектурное решение и ожидаемые artifacts: `docs/adr/0002-openmw-offline-exporter.md`.

Exit: выполнен — все пять участков воспроизводимо рендерятся с необходимыми statics, world coordinate → pixel error равен `0`, между соседними tiles нет видимых швов и подтверждён headless Linux/Docker pipeline. Полный Poison Song basemap до закрытия gate не генерировался.

### Этап 5 — Poison Song

Deliverables:

- immutable Poison manifest;
- полный EN catalog;
- owned либо временно approved tiles;
- search/statuses/personal markers;
- independent progress;
- offline operation.

Exit: Poison Song работает без UESP/CDN и с `0` unresolved effective LAND resources.

### Этап 6 — Fullrest exact

Зависит от получения profile/assets.

Deliverables:

- подтверждённый load order и asset override order;
- immutable Fullrest manifest;
- old TD/TR/MFR render;
- выбранная политика 378 MFR EN gaps;
- EN/RU search;
- MIM progress import;
- явная политика Cyr/Sky/grass/optional plugins.

### Этап 7 — visual/UX polish

Deliverables:

- MIM-like typography и pixel tuning;
- responsive/mobile layout;
- keyboard navigation и accessibility;
- label declutter/filtering;
- loading/error/empty states;
- visual regression fixtures;
- stable URL/deep links.

### Этап 8 — Docker local release

Deliverables:

- multi-stage Dockerfile;
- Nginx config;
- Docker Compose;
- read-only dataset mount;
- cache policy;
- clean-machine smoke test;
- documented backup/restore.

## 18. Definition of Done локальной версии

- доступны три version cards;
- каждой версии соответствуют собственные immutable manifest, tiles, locations и progress;
- Original и Fullrest поддерживают EN/RU с документированной политикой MFR fallback;
- Poison Song поддерживает EN;
- поиск работает по доступным языкам и aliases;
- pan/zoom/search/select сохраняют точные world coordinates;
- statuses, notes и personal markers переживают reload;
- MIM import не теряет duplicated names;
- JSON export/import проходит атомарно;
- никакой runtime dependency от UESP/CloudFront отсутствует;
- Docker запускает приложение локально одной командой;
- BSA/ESM/ESP/assets/полные tiles отсутствуют в Git;
- snapshot manifest позволяет воспроизвести dataset;
- обязательные unit/integration/E2E/build checks зелёные.

## 19. Основные риски и принятые ответы

| Риск | Ответ |
| --- | --- |
| Неизвестный Fullrest load order | Не называть dataset exact до получения profile |
| Нет старых Fullrest assets | Этап 6 блокируется, остальные этапы продолжаются |
| 378 MFR RU-only names | Явный fallback или отдельный mapping, без скрытой подмены |
| LAND-only выглядит пусто | Controlled escalation к OpenMW renderer |
| OpenMW не имеет stable export CLI | Отдельный 3×3-cell spike до fork/automation решения |
| Изменение TR под тем же названием | Immutable snapshot/content hash |
| Межверсионная порча progress | Dataset-scoped storage и explicit migration map |
| Browser storage eviction | Persistent storage request + portable JSON backup |
| Очень большие tiles | 512px pyramid, active dataset loading, external volume |
| Случайная публикация игровых файлов | External paths, `.gitignore`, verification перед commit/push |

## 20. Полезные технические источники

- [OpenLayers custom Projection](https://openlayers.org/en/latest/apidoc/module-ol_proj_Projection-Projection.html)
- [OpenLayers TileGrid](https://openlayers.org/en/latest/apidoc/module-ol_tilegrid_TileGrid-TileGrid.html)
- [Dexie IndexedDB export/import](https://dexie.org/docs/ExportImport/dexie-export-import)
- [OpenMW map settings](https://openmw.readthedocs.io/en/latest/reference/modding/settings/map.html)
- [OpenMW LAND parser](https://gitlab.com/OpenMW/openmw/-/raw/master/components/esm3/loadland.cpp)
- [Playwright browser testing](https://playwright.dev/docs/writing-tests)
