# ADR 0001: LAND renderer остаётся oracle, basemap эскалируется к OpenMW

- Status: accepted
- Date: 2026-08-27
- Profile: `poison-song-26.08`
- Renderer: `land-spike-v1`
- Renderer fingerprint: `0e4439242ee61e3e09202df3bdfa05687d85514fbde7f9552c8ec6cba2d601aa`
- Effective asset fingerprint: `268f16ee8afaf15ef3e19c7b04d2bafb9cc89dbca22404b30132b88526bace9a`

## Контекст

Этап 4 должен был доказать две независимые вещи:

1. мы можем сами, без UESP/CDN, корректно прочитать и геопривязать terrain Poison Song;
2. LAND-only изображение достаточно содержательно для финального basemap либо проект должен контролируемо перейти к OpenMW scene rendering.

Спайк использует локальные proprietary inputs только из ignored `../morr-dev`. В Git входят parser, renderer, тесты и этот отчёт; ESM/BSA, loose textures и сгенерированные WebP не входят.

Формат реализован по зафиксированному исходному коду OpenMW commit `a042cd34d832625d251ddaf2ca730ad80dc7eff4`: [LAND parser](https://gitlab.com/OpenMW/openmw/-/blob/a042cd34d832625d251ddaf2ca730ad80dc7eff4/components/esm3/loadland.cpp), [LAND record layout](https://gitlab.com/OpenMW/openmw/-/blob/a042cd34d832625d251ddaf2ca730ad80dc7eff4/components/esm3/landrecorddata.hpp), [LTEX parser](https://gitlab.com/OpenMW/openmw/-/blob/a042cd34d832625d251ddaf2ca730ad80dc7eff4/components/esm3/loadltex.cpp), [TES3 BSA reader](https://gitlab.com/OpenMW/openmw/-/blob/a042cd34d832625d251ddaf2ca730ad80dc7eff4/components/bsa/bsafile.cpp) и [terrain texture resolution](https://gitlab.com/OpenMW/openmw/-/blob/a042cd34d832625d251ddaf2ca730ad80dc7eff4/components/esmterrain/storage.cpp).

## Входной профиль

Load order спайка:

1. `Morrowind.esm`;
2. `Tribunal.esm`;
3. `Bloodmoon.esm`;
4. `Tamriel_Data.esm` 26.08;
5. `TR_Mainland.esm` 26.08;
6. `TR_Factions.esp`;
7. `TR_Firemoth_Vanilla_patch.esp`.

VFS регистрирует `Morrowind.bsa`, `Tribunal.bsa`, `Bloodmoon.bsa`, затем loose directories Tamriel Data/TR. Loose resource всегда перекрывает BSA; более поздний mount выигрывает внутри своего класса. Пути нормализуются case-insensitive только для ASCII, запрещают absolute/parent traversal и применяют OpenMW-style `.dds`/original/basename fallback.

CLI fail-closed проверяет SHA-256 десяти ESM/ESP/BSA. Полный список pinned hashes находится в `tools/land_renderer/spike.py` и дублируется в ignored `report.json`.

## Реализовано

- bounded streaming TES3 record/subrecord reader с flags/offsets;
- строгий TES3 BSA `0x100` index и lazy reads;
- ordered loose/BSA VFS;
- LAND `INTV`, `DATA`, `VHGT`, `VNML`, `VCLR`, `VTEX`, `DELE`;
- точное VHGT delta decoding с scale `8`;
- точная 4×4-block VTEX transposition;
- LTEX `NAME`, `INTV`, `DATA`, `DELE`;
- plugin-scoped `(source plugin, VTEX - 1)` palette и global LTEX ID overrides;
- effective LAND whole-record overrides/deletes;
- compact full-world texture audit без хранения vertex arrays всех клеток;
- 65×65 height sampling, 16×16 texture splatting, VCLR, hillshade и water plane;
- north-up TES3 georeference, 16 units/pixel, gutter + exact 512×512 crop;
- metadata-free lossless WebP через закреплённые encoder options ImageMagick;
- deterministic JSON report с input/asset/image hashes.

Renderer fingerprint включает SHA-256 семи Python modules, pinned ESM/ESP/BSA, aggregate mapping/payload hash всех effective terrain textures, Python version, полный ImageMagick build string и параметры render/WebP. Поэтому изменение loose override или кода не сохраняет прежний fingerprint.

LAND renderer намеренно не читает placed `STAT`/`ACTI`/`DOOR`/`CONT` geometry и NIF. Он также использует детерминированное bilinear texture splatting, а не полностью переносит GPU blendmap path OpenMW; этого достаточно для quality gate, но не заявляется как pixel parity с движком.

## Контрольные участки

Сетка проекта закреплена top-left origin `[-229376, 278528]`. На native zoom `7` один custom tile равен одной TES3 cell: `8192 / 512 = 16` world units/pixel. Это координаты нашего будущего tile pyramid, а не номера тайлов UESP.

| Участок | CELL | World extent | Custom z7 tile | WebP SHA-256 |
| --- | ---: | --- | ---: | --- |
| Balmora | `(-3,-2)` | `[-24576,-16384,-16384,-8192]` | `25/35` | `ec73cfd1e2b9585520d74b3cee040251aff551536324961f7624bb93ff369518` |
| Old Ebonheart | `(7,-19)` | `[57344,-155648,65536,-147456]` | `35/52` | `62d2c80fca8b7beeb4e832ae90cb45e4e977d508cc4dbb55598ccea9533b6f9f` |
| Othrenis | `(16,-29)` | `[131072,-237568,139264,-229376]` | `44/62` | `b844ab7bfc0f631655754d68874d38eca9a5f1b0db533be970d7cf1d9d3a2375` |
| Gorne | `(19,-14)` | `[155648,-114688,163840,-106496]` | `47/47` | `f284e2cdf5255469cf8986eb9f573bb2a7cb80d2d629636f4fb9cde93eea639a` |
| Nan Iban | `(41,-30)` | `[335872,-245760,344064,-237568]` | `69/63` | `222439a9baf17367e4160fbc681203781d83bcf14a054f41d09ea47997355b3d` |

Все пять файлов имеют формат WebP и размер `512×512`.

## Измерения quality gate

| Проверка | Результат |
| --- | --- |
| Effective LAND | `3 986` cells |
| Unique effective non-default VTEX references | `365` |
| Effective cell/VTEX associations | `24 143` |
| VFS resolution | `365/365`, unresolved `0` |
| Fingerprinted mappings / unique asset payloads | `366` (включая default) / `210` |
| World → pixel → world max error | `0` world units |
| Shared control-neighborhood edges | `60` |
| Maximum real height-edge delta | `8` world units, ровно один VHGT quantum |
| Synthetic edge/gutter tests | pass |
| Independent full runs | все пять WebP побайтно идентичны |
| Renderer fingerprint in both runs | одинаковый |

Один квант расхождения высот на границе `(7,-18) → (8,-18)` является свойством исходных LAND и составляет `0.5` native pixel по горизонтальному масштабу. Renderer берёт global соседние cells для gutter, normals и texture weights; искусственного clamp-seam на границе он не добавляет.

## Сравнение MIM и UESP

Для Balmora использован геопривязанный MIM crop из `bigmap_hi.jpg`. Для всех пяти центров выполнено визуальное сравнение с [UESP Project Tamriel Map](https://gamemap.uesp.net/ptr/?world=tamrielrebuilt&x=61440&y=-151552&zoom=7). Эталонные screenshots и comparison sheets находятся только в ignored `local-data/renderer-spike/poison-song-26.08/`.

Наблюдения:

- берег, river/lake silhouette, большие перепады высот и материал дорог совпадают по положению;
- LAND-only уверенно различает terrain-типы и годится для coordinate/resource oracle;
- Balmora без placed geometry превращается в русло и грунтовые пятна: исчезают дома, стены, мосты и городская форма, которые видны в MIM;
- Old Ebonheart, Othrenis, Gorne и Nan Iban теряют здания, башни, деревья, причалы и landmarks, которые формируют читаемость UESP basemap;
- настройка света, контраста или texture blend не может восстановить отсутствующую NIF geometry.

Численный pixel similarity не используется: MIM имеет приблизительную Vvardenfell georeference, UESP включает statics/labels и использует другую camera/render/color pipeline. Источником истины для координат остаётся аналитическая TES3 CELL grid.

## Решение

**LAND-only отклонён как финальный пользовательский basemap.** Он не удовлетворяет исходной цели — карта должна быть визуально узнаваема как MIM/игра — потому что в поселениях отсутствуют основные пространственные ориентиры.

**LAND renderer сохраняется в проекте** как:

- parser/VFS foundation;
- exact coordinate and tile-grid oracle;
- effective-resource auditor;
- deterministic terrain fallback;
- regression reference для будущего scene renderer.

**Основной rendering path эскалируется к OpenMW.** Следующий bounded spike должен:

1. pin конкретный OpenMW release/commit и toolchain/container digest;
2. собрать isolated config из того же ordered profile/VFS;
3. рендерить 3×3 cells offscreen с orthographic north-up camera и crop центральной клетки;
4. отключить UI, actors, weather/fog variability и dynamic objects;
5. включить terrain, water и static NIF geometry с alpha;
6. повторить эти пять controls и проверки coordinates/seams/determinism;
7. предпочесть небольшой offline exporter на базе OpenMW вместо UI automation, если объём изменения приемлем.

Эта эскалация не блокирует semantic Stage 5: catalog, search, progress и marker layers независимы от basemap adapter. Но owned Poison Song basemap нельзя считать завершённым до успешного OpenMW quality gate.

## Воспроизведение

Требуются Python 3, ImageMagick 7 и внешний `../morr-dev` с точными pinned inputs.

```bash
python3 -m tools.land_renderer.spike \
  --source-root ../morr-dev \
  --output-root local-data/renderer-spike/poison-song-26.08

python3 -m unittest discover -s tools/land_renderer/tests -t . -v
magick identify local-data/renderer-spike/poison-song-26.08/controls/*.webp
```

Generated outputs остаются ignored. Канонический audit находится в `local-data/renderer-spike/poison-song-26.08/report.json`.
