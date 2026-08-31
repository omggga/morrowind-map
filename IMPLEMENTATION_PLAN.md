# Morrowind Map — план реализации

- Дата фиксации: 2026-08-26
- Последний полный аудит: 2026-09-01
- Статус: этапы 0–6 завершены в зафиксированных границах; Poison Song V4 опубликован и считается immutable; чистый Original GOTY HD отрендерен, прошёл полный аудит, опубликован и принят в browser acceptance; этап 7 выполнен частично
- Целевой репозиторий: `omggga/morrowind-map`

## 1. Цель

Создать локальное браузерное приложение с единой входной страницей и ровно двумя независимыми EN-only картами:

1. **Original GOTY HD** — только английские `Morrowind.esm → Tribunal.esm → Bloodmoon.esm` и соответствующие `Morrowind.bsa`, `Tribunal.bsa`, `Bloodmoon.bsa`. Никакие Tamriel Data / Tamriel Rebuilt / Fullrest данные в этот профиль не монтируются.
2. **Poison Song V4** — уже готовый Tamriel Rebuilt 26.08 Poison Song с Tamriel Data 26.08. Его renderer, tiles, catalog, hashes и immutable publication не изменяются в рамках перехода на две карты.

Приложение должно работать без внешних map/CDN-зависимостей после подготовки datasets и предоставлять:

- landing page с выбором версии;
- pan, zoom, reset view и координаты курсора;
- поиск по названиям и aliases;
- состояния `unvisited`, `active`, `visited`;
- заметки к локациям;
- создание, редактирование и удаление personal markers;
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
- подробные планы всех интерьеров; Mournhold планируется отдельным inset/submap после основной Original-карты;
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

Новый Original строится только из этой английской base trio. Generic EN catalog уже подтверждён на `1 036` places и `1 205` entrances: `944` places на Vvardenfell и `92` на Solstheim, unresolved door destinations `0`. Старые MIM raster/catalog/RU sidecars больше не являются production inputs.

### 3.2 Fullrest 25.08 — архивный inventory, удаляемый из продукта

Следующие факты сохраняются только как историческая provenance прежнего плана. Fullrest 5.0.15 / Tamriel Rebuilt 25.08 больше не является картой продукта: старый Stage 6 superseded, а `morr-dev/game`, Fullrest/MFR/Cyr/Sky/TR25, RU sidecars и `world.dds` подлежат cleanup. Эти данные нельзя подключать ни к чистому Original, ни к неизменяемому Poison Song V4.

`morr-dev/game/Data Files` содержит установленный профиль Fullrest 5.0.15 и 71 272 loose files общим объёмом около 13 GiB:

- локализованную base trio;
- `Tamriel_Data.esm` 25.05;
- `TR_Mainland.esm` 25.08 Grasping Fortune;
- `TR_Factions.esp`;
- `MFR.esm` и `MFR_TR_patch.esp`;
- `Cyr_Main.esm` 25.05a;
- `Sky_Main.esm` 25.05;
- `.cel/.top/.mrk` translation sidecars.

Этот набор нельзя смешивать с английской base trio из `morr-dev/bsa`: base ESM имеют разные размеры и хеши. Fullrest snapshot должен использовать собственную локализованную base trio из `game/Data Files`.

Для base + TD25 + TR25 без MFR все непустые английские CELL names имеют Russian `.cel` pair. У MFR остаётся отдельный gap: 378 уникальных кириллических CELL names не имеют локального английского соответствия.

Точный порядок подтверждён сохранённым `game/Fullrest-Provenance/OpenMW_Config/openmw.cfg`:

```text
Morrowind.esm → Tribunal.esm → Bloodmoon.esm → Tamriel_Data.esm →
MFR.esm → Cyr_Main.esm → Sky_Main.esm → TR_Mainland.esm →
TR_Factions.esp → MFR_TR_patch.esp → MFR.omwscripts
```

Provenance также фиксирует OpenMW `0.50.0`, commit `47d78e004bc182def2904986f8bb54aea1f4b3ae`. MGE-профиль сохранён рядом в `MGE.ini`; `Data Files/distantland/world.dds` содержит объединённый preview `2048×2048`, но после Этапа 4.5 он остаётся только reference, а production basemap должен рендериться собственным OpenMW exporter.

В `openmw.cfg` отдельно объявлены `MFR_Grass.esp`, `Cyr_Main_Grass.esp`, `Sky_Main_Grass.esp` и `TR_Mainland_Grass.esp`, однако самих четырёх файлов сейчас нет ни в `game/Data Files`, ни в остальных сохранённых inputs. Поэтому exact cartographic profile можно начать строить без них, но exact groundcover нельзя заявлять до восстановления файлов либо до явного решения исключить grass из статической карты. Второй открытый вопрос — политика для 378 MFR-only кириллических CELL names. `MFR.omwscripts` присутствует, но отсутствующие Lua resources не блокируют статический renderer только при документированном исключении dynamic gameplay scripts.

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

Между размером TD26, записанным в master metadata core TR, и фактическим TD26 есть расхождение 776 байт. Оно зафиксировано в provenance; Этап 4.5 уже принял этот профиль во всех 20 OpenMW captures с `0` missing-resource messages в 40 проверенных логах. Расхождение не блокирует production pipeline; immutable Poison snapshot выпущен с `ready` manifest без устаревшего предупреждения.

## 4. Обязательные дополнительные входы

Для обеих активных карт дополнительных игровых файлов не требуется. Original использует только шесть файлов английской GOTY base trio из `morr-dev/bsa`; Poison Song V4 использует уже опубликованный immutable payload. Остальная часть этого раздела про Fullrest сохраняется как superseded historical analysis и не задаёт требования актуальному продукту.

Для начала Fullrest profile/catalog/render spike дополнительных core-файлов не требуется: точный load order, masters, loose assets, Cyr/Sky/MFR/TR, translation sidecars и MGE reference уже находятся в `morr-dev/game`, а vanilla BSA — в `morr-dev/bsa`. Выбор basemap также закрыт Этапом 4.5 в пользу собственного offline OpenMW exporter.

Для буквального exact groundcover нужны отсутствующие `MFR_Grass.esp`, `Cyr_Main_Grass.esp`, `Sky_Main_Grass.esp` и `TR_Mainland_Grass.esp`. Если получить их нельзя, допустима явная политика `grass excluded from static cartographic snapshot`; тогда dataset остаётся exact по ESM/ESP world content, но не по растительности groundcover. Для воспроизведения gameplay runtime также потребуются Lua resources, на которые ссылается `MFR.omwscripts`; для статической карты они намеренно исключаются и не являются блокером.

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

Переход на две карты не очищает существующую IndexedDB и не выполняет destructive migration. Приложение использует новый logical user-data epoch поверх неизменных dataset identities Original GOTY HD и Poison Song V4; старые MIM/Fullrest/RU records остаются физически инертными и не появляются в UI. Domain JSON export/import сохраняется, но экспортирует и восстанавливает только две активные карты текущего epoch.

Storage изолируется интерфейсом `ProgressRepository`. Будущий server/OAuth adapter реализует тот же контракт.

### 5.3 Offline tooling

- Python data pipeline для TES3/MIM extraction;
- JSON Schema как межъязыковой контракт;
- libvips/Sharp для pyramids/WebP;
- pytest для extractor/importer;
- pinned OpenMW offline exporter как выбранный scene renderer; LAND renderer остаётся coordinate/resource oracle.

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

Обе активные карты EN-only; locale не создаёт дополнительные snapshot/cards.

Предварительные profiles:

### Original

```text
Morrowind.esm
Tribunal.esm
Bloodmoon.esm
```

Tribunal входит в dataset, но Mournhold позднее получает отдельный inset/submap как quasi-interior.

Для Original регистрируются только одноимённые три BSA. Tamriel Data, Tamriel Rebuilt и любые Fullrest assets являются fail-closed запрещёнными inputs этого profile.

### Fullrest — superseded

Этот прежний profile удалён из active snapshot index и Stage 6. Его описание оставлено только как historical marker; runtime manifest и новый dataset для него не выпускаются.

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
8. формирование EN names/aliases из effective английских records;
9. aliases и нормализацию поиска;
10. resource resolution через ordered loose directories и BSA fallback;
11. генерацию locations/locales/manifests/audit reports;
12. fail-fast validation unresolved effective resources.

`.cel`, `.top`, `.mrk` и MIM не используются новым EN-only Original catalog.

Сотни тысяч raw placed references нужны только offline. В browser dataset попадает компактный каталог places/entrances.

## 10. Legacy MIM data

MIM import был завершён и проверен в историческом Stage 3, но снят с активного продукта вместе со старым raster/catalog Original. Существующие импортированные records не удаляются из браузера: новый namespace делает их инертными. Новый Original GOTY HD начинает progress с нуля; перенос выполняется только через общий JSON contract активных карт, без MIM-specific runtime и без автоматического присваивания старых ordinal IDs новому catalog.

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

- две активные карты имеют независимый progress;
- `active` не переносится автоматически;
- `visited` копируется только при exact migration mapping;
- old removed namespaces не попадают в active export/archive;
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

### 12.1 Basemap adapters

Текущее состояние:

- Original GOTY HD — опубликованная audited sparse lossless WebP pyramid `z0…z7`: `1 540` native LAND tiles, `198` shards и `2 114` tiles для Vvardenfell + Solstheim, inventory `aade4b98c2fb905fd2617871345292a638e3a4a25c6d036db7a3cc18bb2dd014`;
- Poison Song — собственная sparse lossless WebP pyramid `z0…z7`, подключённая через OpenLayers `TileLayer`;
- MIM, UESP и Fullrest `world.dds` не являются production runtime dependencies.

Basemap является сменным adapter. Координаты, IDs, markers, search и progress от него не зависят.

Исторические MIM-геопривязки сохраняются только как проверочная evidence Stage 2 и не используются новым renderer:

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

Этап 4.5 завершил выбор: production basemap строится небольшим offline exporter patch поверх pinned OpenMW, а не UI automation. Exporter использует LocalMap scene, orthographic north-up camera, фиксированные lighting/cull settings, render gutters и host-side crop/color grade. LAND pipeline остаётся независимым oracle для координат, effective resources и comparison renders.

Этап 5 уже расширил runner до arbitrary batch coverage с checkpoint/resume, deterministic inventory, full resource audit и построением нижних zoom из native children. В Этапе 6 тот же proven pipeline получает отдельный fail-closed Original profile из base trio; Poison implementation и release при этом не изменяются.

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

Две cards показывают:

- название/version;
- EN-only availability;
- regions/modules;
- visited/active counts;
- дату последнего открытия;
- точный snapshot build;
- dataset readiness/warning.

### Map screen

- fullscreen map;
- responsive sidebar;
- version и region selectors;
- search и filters;
- legend;
- zoom/reset controls;
- cursor/world coordinates;
- snapshot information;
- JSON import/export;
- URL state для version/region/x/y/z.

Location interaction:

- name, type и aliases;
- EN display;
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

Квадратные markers рисуются как Canvas/SVG primitives и остаются резкими при zoom. Labels не запекаются в tiles; declutter применяется преимущественно к text labels.

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
- смена двух manifests сохраняет raw center, где он допустим;
- Place/Entrance grouping и duplicate-name cases;
- status state machine;
- Dexie migrations и atomic JSON import;
- EN search;
- reload сохраняет progress/notes/personal markers;
- E2E pan/zoom/click/search/version;
- deterministic visual fixtures в pinned Playwright container;
- Docker smoke test;
- asset audit: 0 unresolved effective LAND textures;
- OpenMW mode: 0 unresolved effective direct exterior models.

Полные игровые assets и giant tile generation не запускаются в публичном/обычном CI. Parser tests используют synthetic binary fixtures, а локальная dataset verification работает против external ignored inputs.

## 17. Этапы реализации

### Сводный аудит на 2026-09-01

| Этап | Текущий статус | Что означает статус |
| --- | --- | --- |
| 0 — repository/plan | **100% complete** | Private GitHub repository, plan, ignore rules и initial push проверены |
| 1 — contracts/skeleton | **100% complete в historical scope** | Skeleton, contracts, TES3 projection и CI работают; active landing уже сокращён до двух EN-only cards в Stage 6 cleanup |
| 2 — Original MIM | **100% complete, superseded** | Исторический Vvardenfell/Solstheim raster + 1 010 EN/RU places принят, но будет заменён EN-only Original GOTY HD |
| 3 — progress/MIM | **100% complete в historical scope** | Dataset-scoped persistence, MIM import и portable backup были реализованы; MIM runtime снимается, общий JSON backup остаётся |
| 4 — LAND spike | **100% complete в spike scope** | Coordinate/resource oracle принят; LAND-only обоснованно отклонён как финальный basemap |
| 4.5 — OpenMW spike | **100% complete в spike scope** | Bounded exporter и Linux/Docker quality gate приняты |
| 5 — Poison Song | **100% complete** | 5.1–5.6 завершены: V4 pyramid, deterministic EN catalog (`4 085` places / `4 902` entrances), generic runtime, `ready` manifest и offline real-browser acceptance приняты |
| 6 — Original GOTY HD | **100% complete** | Изолированный base-trio profile, smoke `5/5`, full render/audit/publication, EN catalog, strict validators и real-browser acceptance обеих карт приняты |
| 7 — two-map visual/UX polish | **Partially complete** | Functional browser acceptance двух реальных datasets готов; labels, URL/deep links, расширенный visual/a11y polish остаются |

Этапы 0–4.5 считаются закрытыми именно в их исторически зафиксированных границах. Poison V4 закрыт Stage 5 и заморожен; Original HD закрыт Stage 6 как отдельный audited production release.

### Этап 0 — репозиторий и план

Status: **100% complete** (verified 2026-08-27).

Deliverables:

- private `omggga/morrowind-map`;
- `IMPLEMENTATION_PLAN.md`;
- `.gitignore`;
- короткий `README.md`;
- первый commit `docs: add implementation plan`;
- push ветки `main`.

Evidence: GitHub repository `omggga/morrowind-map` приватный, default branch — `main`; первый commit `0c99cdc` содержит ровно plan, `.gitignore` и `README.md`. Remaining: none.

### Этап 1 — contracts и skeleton

Status: **100% complete** (verified 2026-08-27).

Deliverables:

- pnpm workspace;
- Vite/React/TypeScript strict;
- OpenLayers custom `TES3:WORLD` projection;
- shared schemas/contracts;
- dataset index и три manifests-заглушки;
- CI install/typecheck/lint/unit/build.

Exit был достигнут в commit `06693d9`: landing исторически показывал три cards, каждая открывала пустую карту с корректными TES3 coordinates. Затем Original placeholder был заменён реализацией Этапа 2, а Poison — generic runtime Этапа 5.5. Эта evidence сохраняется, но актуальный product contract Stage 6 требует ровно две cards и удаления Fullrest placeholder. Remaining: none within historical Stage 1.

### Этап 2 — Original vertical slice

Status: **100% complete within the historical Original Vvardenfell/Solstheim scope; superseded by Stage 6** (verified 2026-08-27): 933 MIM markers + 77 ESM-only destinations, full EN/RU coverage.

Deliverables:

- MIM Vvardenfell/Bloodmoon rasters;
- Original location catalog;
- EN/RU;
- square markers;
- search;
- zoom/pan/place panel.

Exit исторического slice выполнен. Два локальных raster имеют размеры `3300×3800` и `3072×3840` и совпадают с manifest hashes; audit содержит 1 010 places, EN/RU по 1 010 и unresolved names `0`. Эти artifacts больше не являются active Original; Stage 6 заменяет их EN-only scene-rendered tiles и catalog. Mournhold inset остаётся будущей отдельной функцией. Remaining: none within historical Stage 2.

### Этап 3 — progress и MIM import

Status: **100% complete for local persistence and MIM import scope** (verified 2026-08-27): Dexie schema v3, real MIM snapshot, local editing and portable backup реализованы.

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

Remaining within historical Stage 3: none. Stage 5.6 даёт pinned Playwright E2E настоящего OpenLayers Canvas/browser reload для Poison Song. Stage 6 выводит MIM-specific UI/import из active runtime, создаёт новый IndexedDB namespace без purge и сохраняет общий JSON round-trip только для двух активных карт.

### Этап 4 — LAND renderer spike

Status: **100% complete in LAND spike scope** (verified 2026-08-27): deterministic LAND/VFS oracle принят, финальный basemap эскалирован к OpenMW.

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
- world/pixel round-trip error 0; 60 shared edges проверены в пяти `3×3` control neighborhoods, максимальный source delta равен одному VHGT quantum (8 units);
- два независимых complete five-control spike runs дали побайтно одинаковые пять WebP и renderer fingerprint;
- сравнение Balmora с MIM и всех пяти areas с UESP подтвердило terrain alignment, но показало неприемлемую потерю buildings/bridges/trees/statics;
- LAND renderer остаётся coordinate/resource oracle и fallback; owned basemap переходит к bounded OpenMW offscreen/exporter spike.

Подробности и hashes: `docs/adr/0001-land-renderer-spike.md`.

Exit: выполнен. Remaining within Stage 4: none; генерация полного basemap намеренно относится к Этапу 5.

### Этап 4.5 — OpenMW renderer spike

Status: **100% complete in bounded OpenMW spike scope** (verified 2026-08-27): все automated и hash-bound visual checks пройдены; полный Poison Song basemap намеренно не генерировался.

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
- для Balmora, Old Ebonheart, Othrenis, Gorne и Nan Iban выполняются center/east/north renders, повторный center render и проверки resource logs, runtime camera transform, содержательности изображения и bounded raw-overlap/repeat deltas; exact hashes и hashes всего seam evidence входят в обязательную визуальную квитанцию, а заранее заданный строгий tolerance применяется только к редким alpha-edge pixels;
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

`smoke-report.json` доказывает только работоспособность одного capture и не закрывает gate. Канонический `report.json` полного запуска подтверждает пять controls, реальный runtime world-to-pixel transform с ошибкой не более одного native pixel, ограниченные raster deltas соседних gutter overlaps, repeat comparisons с сохранёнными hashes и строгим tolerance, отсутствие missing resource messages, непустое изображение и Linux/amd64 `llvmpipe` runtime. Визуальное наличие roofs, buildings, bridges, trees, walls, water и alpha geometry отдельно сверяется с LAND/MIM/UESP references; receipt связана с profile/execution fingerprints, WebP/native hashes и полным seam evidence fingerprint.

Фактический результат: **pass**. Образ `sha256:d96ddae3e12196d6b624ffb98dd87e721e3ba6c2a04ce1b410b02fe0e39e3a5b` воспроизводимо выполнил 20 изолированных captures. Четыре repeat WebP/native/graded RGBA совпали побайтно; в Nan Iban изменились 8 из 262 144 alpha-edge pixels (`0.000030518` fraction, `0.000033379/255` mean delta, `4/255` max delta), что укладывается в заранее заданный узкий tolerance. Maximum runtime coordinate error `0 px`; missing resources `0` в 40 проверенных логах. Для десяти east/north overlaps худшие raster deltas составили `0.319738` differing fraction, `0.281264/255` mean absolute channel delta и `25/255` maximum channel delta — ниже зафиксированных пределов, без видимого шва при review в native resolution. Visual receipt подтвердила весь набор statics и LAND/MIM/UESP reference coverage.

Решение quality gate: для дальнейшего basemap используется bounded offline exporter поверх OpenMW, а не UI automation. Этап 5 разблокирован, однако в рамках Этапа 4.5 полный Poison Song basemap не создавался.

Архитектурное решение и ожидаемые artifacts: `docs/adr/0002-openmw-offline-exporter.md`.

Exit: выполнен — все пять участков воспроизводимо в пределах принятого tolerance рендерятся с необходимыми statics, world coordinate → pixel error равен `0`, между соседними tiles нет видимых швов и подтверждён headless Linux/Docker pipeline. Remaining within Stage 4.5: none. Runtime report и manual visual receipt хранятся в ignored local artifacts и для повторной генерации требуют proprietary game assets и Docker; core-only render profile намеренно исключает `.omwscripts`, `TR_Factions.esp` и Firemoth patch. Полный Poison Song basemap относится к Этапу 5.

### Этап 5 — Poison Song

Status: **100% complete (verified 2026-08-31): 5.1–5.6 завершены; полный V4 release отрендерен, стабилизирован, прошёл audit, опубликован и активирован с сохранением V1 rollback; generic catalog/runtime и product/browser acceptance приняты**.

Уже готово для переиспользования:

- exact Poison core profile, canonical TES3 grid и `0` unresolved LAND textures/direct exterior models;
- LAND coordinate/resource oracle и прошедший quality gate OpenMW exporter;
- contracts, Place/Entrance model, search primitives, dataset-scoped Dexie progress/notes/personal markers и portable backup;
- basemap-bound `ready` manifest с подтверждённым core load order, extent, BSA hashes и прямой content-addressed ссылкой на immutable tile metadata;
- generic TES3 effective-record catalog pipeline с deterministic audit и content-addressed публикацией `locations.json` / `locales/en.json`.

Подэтапы:

1. **5.1 — production renderer: выполнено на 100%.** Реализованы effective LAND/CELL coverage, immutable plan `3 984 CELL → 492 shard`, exporter-only `5×5` scene context с `3×3` RTT, arbitrary cell sets, стабильные modulo partitions, `--workers`, atomic checkpoint/resume, fail-closed profile/source/image/encoder provenance, resource audit, cgroup memory evidence, gutter crop/grade, pixel-exact lossless WebP, sparse `z0…z7` pyramid и deterministic inventory. Production profile явно заменяет отсутствующие generic OpenMW snow/blizzard filenames на существующие Bloodmoon DDS; контролируемая миграция producer/profile повторно проверяет все готовые WebP и игровые audits, сохраняет immutable backups и receipt. CLI запускается пользователем из Terminal; отдельные процессы с одним checkpoint нельзя запускать одновременно, для параллелизма используется встроенный `--workers`.
2. **5.2 — five-control production benchmark: выполнено на 100%.** На тех же Balmora, Old Ebonheart, Othrenis, Gorne и Nan Iban реально отрендерены пять полных `3×3` batch (`45` native tiles) с двумя workers. Render wall `178.977 s`, container mean `52.4 s`, peak одного shard `1.137 GB`, сумма двух наибольших peaks `2.209 GB`, повторный запуск по checkpoint `0.080 s` без OpenMW. Проверены `60` overlaps, `0 px` coordinate error, сравнение со старыми `1×1`, lower zoom и inventory (`101` tiles, hash `6528bcc…`). Экстраполяция на эту машину: `4.89 h` native render + `0.29 h` pyramid + `36 s` provenance = `5.19 h`; рабочий запас для полного запуска — `5–6 h`. Полный отчёт: `docs/stage5-openmw-production.md`.
3. **5.3 — full Poison basemap: выполнено на 100%.** Все `492` shards дали `3 984` native tiles; после deterministic cross-shard stabilization и полного rebuild lower zoom опубликована sparse lossless WebP pyramid `z0…z7`: `5 464` tiles (`1 480` lower), `1 879 019 148` bytes, inventory `d409e627a75beac2caea56cea35bea132091bc851e1b22edbb4dbe3791f5cd17`. Full audit декодировал каждый tile, точно воспроизвёл `1 480 / 1 480` parents, проверил все `10 467` соседств и `2 571` native cross-shard boundaries, `492` runtime reports, `16` независимых raw seam probes / `32` cells и coordinate error `0 px`. Cross-shard flagged/structural failures — `0/0`, actionable missing resources — `0`; повтор с reused evidence дал тот же audit SHA `4439782ab6e2cdf0d8330168428c4c5550629beaf607f4b9f5507700daf270d5`.
   **V4 visual regeneration: full render/finalize/stabilization/audit/publication/activation complete.** Отдельные roots `poison-song-26.08-v4` и Docker tag `stage5-v4` исключают смешивание с V1. Production v2 применяет single-pass grade `114/102/92` к исходному `544×544` capture после gutter crop и нормализует alpha по правилу `0→0, >0→255`; parent tiles, seam blend, stabilizer v2, audit v4 и publish contract повторяют и проверяют это правило на всей pyramid. Repeat-gate v4 сохраняет лимиты fraction/mean/p99/hard/alpha и вместо несовместимого с binary-alpha требования `opaqueDifferingPixels == 0` ограничивает максимальный opaque delta значением `48` и крупнейший связный hard-компонент значением `16 px`; publisher независимо перепроверяет все эти границы, сохраняя точный zero-opaque контракт V1. Optional `tilePyramid.presentation` отключает browser canvas/CSS correction только для baked V4, сохраняя V1 совместимость и view-only overscale `1.1×`. Полный audit прошёл с inventory `93758a5e…`, audit SHA `9dea3294…`, `5 464` tiles, `1 703 000 992` bytes и всеми `16` raw probes / `32` repeat runs. Content-addressed metadata опубликована, committed Poison Song manifest указывает на V4 `map-assets.json`; V1 inventory `d409e627…` и его metadata не изменены и доступны для rollback. Короткие generic producer-команды являются V4 aliases; immutable V1 доступен для отдельной validation.
4. **5.4 — generic catalog pipeline: выполнено на 100%.** Exact order `Morrowind.esm → Tribunal.esm → Bloodmoon.esm → Tamriel_Data.esm → TR_Mainland.esm` объединяется с TES3 master-ordinal identity, last-wins overrides, deletion tombstones/resurrection и отдельной обработкой CELL metadata/references, DOOR base records, LAND/REGN и teleport/MVRF. Внутренние destination CELL и 8-neighbor components одноимённых exterior CELL сгруппированы в stable dataset-scoped Place/Entrance IDs; координатой multi-entrance place служит фактический entrance medoid. Выпущены `4 085` places (`3 755` interior + `330` named exterior) и `4 902` entrances, EN names/aliases, `14` типов и `3` региона. `locations.json`, `locales/en.json` и audit имеют canonical JSON, input/implementation/policy/output hashes, pinned counts и deterministic повторяемость; artifacts публикуются по catalog inventory hash. Текущий snapshot имеет `0` дополнительных aliases, что явно зафиксировано audit, а не означает отсутствие alias contract. Подробности: `docs/stage5-catalog.md`.
5. **5.5 — contracts/runtime: выполнено на 100%.** WebP tile-pyramid/coverage/derivation contracts, catalog audit reference, fingerprint binding, строгие dataset/catalog validators и immutable content-addressed publication подключены к generic browser runtime. Единые `DatasetMap` и dataset loader динамически загружают каталог и объявленные manifest-ом локали: Original использует MIM `ImageStatic`, Poison Song — OpenLayers `TileLayer` с явной TES3 grid, fixed top-left XYZ и native `512×512` WebP. Sparse coverage отсекает отсутствующие tiles до URL/HTTP-запроса. Runtime различает `missing`, `loading` и `error`, включая retry для tile errors; Poison manifest переведён в `ready`. Backward-compatible optional presentation contract различает legacy V1 runtime adjustment и baked V4 без двойной обработки.
6. **5.6 — product integration/acceptance: выполнено на 100%.** Pinned Playwright `1.62.1` запускает настоящий headless Chromium и fail-closed блокирует любой non-loopback traffic. Default CI suite использует реальные production index/manifest/V4 map-assets/coverage и подменяет только отсутствующие в Git тяжёлые catalog/tile bytes минимальными валидными fixtures. Он проверяет painted WebP canvas, поиск, status/note/custom-marker workflow, reload persistence, zoom и keyboard pan, non-retryable missing dataset, metadata failure/retry и tile failure/retry. Найденный acceptance-ом дефект повторной загрузки исправлен через штатный `ImageTile.load()` только для упавших tiles. Отдельный local-only `@prepared` gate загружает настоящий каталог `4 085` places и реальные tiles из полного ignored V4 payload.

Deliverables:

- immutable ready Poison manifest, связанный hashes с profile, assets, extractor, renderer, catalog и tile inventory;
- полный EN location catalog;
- собственная полная WebP pyramid без UESP/CDN runtime dependency;
- search, statuses, notes, personal markers и independent reload persistence;
- offline/no-network E2E и full-scope resource/coordinate/seam/determinism reports.

Exit: **достигнут.** Полный Poison catalog и owned tile pyramid hash-bound immutable manifest-ом; приложение без внешней сети поддерживает search/status/note/personal markers/reload/zoom/pan; default real-browser CI gate и prepared full-payload gate зелёные; effective LAND textures и direct exterior models имеют `0` unresolved; coordinate, seam и determinism gates проходят на полном scope.

### Этап 6 — Original GOTY HD

Status: **100% complete (verified 2026-09-01): cleanup, storage boundary, isolated profile, deterministic plan, smoke, production render, audit, publication, catalog и browser acceptance выполнены**.

Stage 6 выполняется строго в dependency order:

1. **Freeze Poison Song V4 — complete.** Manifest SHA-256 остаётся `cca410d5…`; frozen renderer/profile/catalog/presentation artifacts не изменены.
2. **Cleanup active product — complete (`3717f7d`).** Fullrest card/manifest/runtime references, MIM raster/catalog/import adoption и RU locale/UI paths удалены. Локальные `morr-dev/game`, MIM maps и старый generated Original удалены; `morr-dev/bsa`, текущие TR inputs и полный Poison V4 сохранены.
3. **Storage boundary — complete.** Новый namespace `morrowind-map-two-map-en-v1` не открывает и не очищает прежнюю IndexedDB. Generic JSON export/import охватывает только две активные карты текущего epoch.
4. **Original profile/plan — complete.** Fail-closed profile содержит только `Morrowind.esm → Tribunal.esm → Bloodmoon.esm` и три одноимённых BSA, включая необходимые Bloodmoon snow/blizzard aliases; Tamriel Data, Tamriel Rebuilt и Fullrest отсутствуют. Snapshot `original:goty:8b2690c0ce1c954e`; profile `8b2690c0ce1c954e603d317728b19339f4b985ce3c362b0bc0eee93b3841b2a7`; plan `9ad7c36652b18615234819aba986df32a89125b1365d47eddef0f847af90886c`, `1 540` LAND / `198` shards.
5. **Smoke — complete, `5/5`.** Balmora, Vivec, Ald’ruhn, Seyda Neen и Solstheim прошли с теми же V4 presentation rules: native `512×512`, grade `114/102/92`, binary alpha, opaque water, render gutters и view-only `1.1×` overscale.
6. **Production render/audit/publication — complete.** Все `1 540` LAND cells отрендерены в `198` shards; finalize/stabilize построили lossless WebP pyramid `z0…z7` из `2 114` tiles. Final basemap inventory: `aade4b98c2fb905fd2617871345292a638e3a4a25c6d036db7a3cc18bb2dd014`; full audit имеет статус `passed`, hash `44f722800682e23be1ded7dedf27d5eae19a94864b834e92b488a53ae6c7b4a0`. Publish и strict validators прошли.
7. **Catalog — complete and published.** Generic EN catalog содержит `1 036` places / `1 205` entrances (`944` Vvardenfell, `92` Solstheim), unresolved door destinations `0`, inventory `6ea0c0a0272f6c8456a947c9dc36bac5116a9cd524cc4b351fdad867cf3e0df1`.
8. **Runtime/acceptance — complete.** Original активирован через общий OpenLayers tile runtime. Real-browser acceptance существует для обоих реальных datasets и покрывает search/status/note/personal markers/reload/zoom/pan, missing/error/retry и JSON backup.
9. **Mournhold follow-up — отдельно и не блокирует Stage 6.** Основная карта содержит Vvardenfell + Solstheim. Tribunal входит в profile и catalog, но Mournhold, состоящий из interior cells без обычного LAND, будет выпущен отдельным inset/submap с собственной локальной системой координат.

Deliverables:

- two-card EN-only landing и active dataset index;
- immutable Poison V4 regression gate без изменения его bytes;
- clean base-trio Original profile с запрещающим TR/TD/Fullrest audit;
- `1 540` native tiles / `198` shards / `2 114` total tiles;
- EN catalog `1 036` places / `1 205` entrances;
- новый logical IndexedDB user-data epoch без purge и generic two-map JSON backup;
- full-scope resource/coordinate/seam/determinism и real-browser acceptance reports;
- отдельный post-release plan для Mournhold inset.

Exit: **достигнут.** Доступны ровно две EN-only cards; Poison Song V4 byte/hash-identical исходному release; Original опубликован из base trio без TR/TD/Fullrest contamination, имеет audited pyramid и catalog; обе реальные карты прошли browser acceptance и работают offline в новом user-data epoch с независимым progress; старые browser data не удалены и не видны в UI. Mournhold остаётся отдельным неблокирующим follow-up.

### Этап 7 — visual/UX polish

Status: **partially complete foundation; functional acceptance двух реальных datasets выполнен, расширенный visual/UX/a11y polish остаётся**.

Уже реализовано:

- MIM-like palette, square markers и базовая typography/pixel стилизация;
- responsive breakpoints для desktop/mobile, `focus-visible`, reduced-motion и tab-focus карты;
- базовые keyboard actions (`/`, `Escape`), возврат focus на landing и ARIA labels;
- loading/error/no-results states и ручной mobile/browser smoke.
- pinned real-browser functional acceptance для Original GOTY HD и Poison Song V4 на настоящих prepared datasets.

Остаток работ:

1. Довести generic regions, types, statuses, strings и controls двух реальных datasets за пределами уже принятого functional Stage 6 scope; убрать оставшийся snapshot-specific UX.
2. Добавить OpenLayers text-label layer с deterministic declutter и zoom/type/status/region filters; сейчас labels на карте отсутствуют.
3. Ввести стабильный URL contract как минимум для `dataset`, `region`, `x`, `y`, `z`, `place`, включая back/forward, invalid-state fallback и shareable deep links. Сейчас `App` хранит выбор только в React state.
4. Расширить уже готовые functional tile `missing`/`loading`/`error`/retry cases двух datasets дополнительными большими payload и visual fixtures.
5. Провести финальный MIM-like font/icon/pixel tuning на готовых Poison/Original подложках.
6. Расширить существующий two-dataset Playwright functional suite до visual fixtures desktop/mobile/landscape и ключевых UI states; OpenMW visual receipt проверяет basemap, но не UI.
7. Выполнить keyboard-only/manual focus matrix и automated accessibility checks, включая dialog focus, contrast, touch, 200% reflow и screen-reader names.

Deliverables:

- MIM-like typography/pixel tuning для всех datasets;
- responsive/mobile/touch layout без overflow;
- keyboard navigation и accessibility acceptance;
- deterministic label declutter/filtering;
- complete loading/error/empty/retry states;
- pinned Playwright functional/visual regression fixtures;
- stable URL/deep links с browser history.

Exit: обе готовые карты проходят URL round-trip/back-forward, keyboard-only flow, automated + manual accessibility checks, desktop/mobile/landscape visual fixtures, deterministic label/filter behavior и полные loading/error/empty scenarios.

### Этап 8 — Docker local release

Deliverables:

- multi-stage Dockerfile;
- Nginx config;
- Docker Compose;
- read-only dataset mount;
- cache policy;
- clean-machine smoke test;
- documented backup/restore.

Stage 8 публикует только два EN-only manifests/datasets. Read-only mount содержит Original GOTY HD и неизменяемый Poison Song V4; Fullrest/MIM/RU artifacts туда не входят. Backup/restore документирует новый logical IndexedDB user-data epoch и generic JSON без browser purge.

## 18. Definition of Done локальной версии

- доступны ровно две EN-only version cards: Original GOTY HD и Poison Song V4;
- каждой карте соответствуют собственные immutable manifest, tiles, locations и progress;
- Original использует только английские GOTY ESM+BSA base trio и не содержит Tamriel Data / Tamriel Rebuilt / Fullrest данных;
- Poison Song V4 остаётся byte/hash-identical опубликованному release;
- поиск работает по EN names и aliases;
- pan/zoom/search/select сохраняют точные world coordinates;
- statuses, notes и personal markers переживают reload;
- старые IndexedDB records не очищаются, остаются инертными и не попадают в UI;
- generic JSON export/import двух активных карт проходит атомарно;
- никакой runtime dependency от UESP/CloudFront отсутствует;
- Docker запускает приложение локально одной командой;
- BSA/ESM/ESP/assets/полные tiles отсутствуют в Git;
- snapshot manifest позволяет воспроизвести dataset;
- обязательные unit/integration/E2E/build checks зелёные.

## 19. Основные риски и принятые ответы

| Риск | Ответ |
| --- | --- |
| Случайное попадание TR/TD/Fullrest в Original | Fail-closed allowlist ровно трёх ESM и трёх BSA плюс audit ordered inputs/data paths |
| Изменение готового Poison V4 при переиспользовании pipeline | Freeze manifest/catalog/tile hashes до cleanup и проверять byte/hash identity после integration |
| Старые MIM/Fullrest/RU records в браузере | Новый logical user-data epoch; без purge/destructive migration; старые records не перечисляются UI/export |
| LAND-only выглядит пусто | **Resolved:** LAND остаётся oracle, финальный basemap строится OpenMW exporter |
| OpenMW exporter/reproducibility | **Resolved для Poison V4 и Original GOTY HD:** оба production releases прошли соответствующие full-scope audit gates |
| Тысячи OpenMW captures слишком медленны/велики | Batch targets, checkpoint/resume, native masters, lower zoom from children, inventory/hash/size budget до полного run |
| Изменение TR под тем же названием | Immutable snapshot/content hash |
| Межверсионная порча progress | Новый dataset-scoped namespace без автоматической миграции старых MIM IDs |
| Browser storage eviction | Persistent storage request + portable JSON backup |
| Очень большие tiles | 512px pyramid, active dataset loading, external volume |
| Ручной browser smoke невоспроизводим | **Resolved для Poison functional flow в Этапе 5.6;** two-map visual/a11y matrix остаётся в Этапе 7 |
| Случайная публикация игровых файлов | External paths, `.gitignore`, verification перед commit/push |

## 20. Полезные технические источники

- [OpenLayers custom Projection](https://openlayers.org/en/latest/apidoc/module-ol_proj_Projection-Projection.html)
- [OpenLayers TileGrid](https://openlayers.org/en/latest/apidoc/module-ol_tilegrid_TileGrid-TileGrid.html)
- [Dexie IndexedDB export/import](https://dexie.org/docs/ExportImport/dexie-export-import)
- [OpenMW map settings](https://openmw.readthedocs.io/en/latest/reference/modding/settings/map.html)
- [OpenMW LAND parser](https://gitlab.com/OpenMW/openmw/-/raw/master/components/esm3/loadland.cpp)
- [Playwright browser testing](https://playwright.dev/docs/writing-tests)
