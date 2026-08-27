# ADR 0002: bounded offline exporter поверх OpenMW вместо UI automation

- Status: accepted; runtime validation complete
- Date: 2026-08-27
- Stage: `4.5`
- Profile: `poison-song-26.08`
- Renderer: `openmw-export-spike-v1`
- Quality gate: **passed**

## Контекст

Этап 4 доказал TES3 coordinate model, ordered resource resolution и детерминированную генерацию terrain, но LAND-only не показывает здания, мосты, стены, деревья и другую размещённую NIF geometry. Финальная подложка должна использовать игровой scene/resource pipeline, не превращая проект в собственный NIF renderer и не завися от UESP/CDN.

Для bounded spike рассматривались два способа управлять OpenMW:

1. запуск обычного UI с автоматизацией меню, консоли, камеры и screenshot capture;
2. маленький pinned patch, который вызывает существующий LocalMap scene render для заданной CELL, забирает offscreen image после draw и завершает процесс.

UI automation добавляет не относящиеся к карте переменные: window/input focus, timing меню и console, UI scale, camera interpolation, screenshot framebuffer и host window system. Эти переменные усложняют headless Docker, seam analysis и повторяемость.

## Решение

Выбран **небольшой offline exporter patch поверх OpenMW LocalMap**, а не UI automation. Patch не реализует ESM/BSA/NIF loading или scene graph заново: эти части остаются официальным OpenMW. Его узкая ответственность — принять CELL и output path через environment, зафиксировать render dimensions и north-up raster transform, получить image после первого завершённого draw, атомарно опубликовать PNG и завершить OpenMW.

Исходная база закреплена на официальном [OpenMW `openmw-0.51.0`](https://gitlab.com/OpenMW/openmw/-/tags/openmw-0.51.0), commit [`f4bec41444214a7903bebd178389ca22ca13f646`](https://gitlab.com/OpenMW/openmw/-/commit/f4bec41444214a7903bebd178389ca22ca13f646). Patch основан на существующем [OpenMW LocalMap renderer](https://gitlab.com/OpenMW/openmw/-/blob/openmw-0.51.0/apps/openmw/mwrender/localmap.cpp); правила профиля соответствуют официальной документации [OpenMW paths/configuration](https://openmw.readthedocs.io/en/stable/reference/modding/paths.html) и [map settings](https://openmw.readthedocs.io/en/stable/reference/modding/settings/map.html).

Это архитектурное решение принято и прошло bounded quality gate ниже. Полная генерация basemap остаётся отдельным этапом.

## Воспроизводимый build

| Pin | Значение |
| --- | --- |
| OpenMW release | `openmw-0.51.0` |
| OpenMW commit | `f4bec41444214a7903bebd178389ca22ca13f646` |
| Platform | `linux/amd64` |
| Base image | `ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517` |
| Ubuntu packages snapshot | `20260826T000000Z` через `snapshot.ubuntu.com` |
| Local image tag | `morrowind-map-openmw:0.51.0-stage45` |

`tools/openmw_renderer/Dockerfile` делает detached checkout точного commit, проверяет patch через `git apply --check`, собирает только нужный `openmw` Release binary и сохраняет compiler/CMake/package manifest. Image labels закрепляют OpenMW revision, base digest, Ubuntu snapshot, Stage 4.5 и SHA-256 текущего renderer source set. Runner fail-closed сравнивает labels, image OS/architecture и runtime build manifest до первого render.

Первичная сборка и Balmora smoke выполняются одной командой, чтобы image сразу проверялся тем же runner, который вычисляет renderer fingerprint:

```bash
python3 -m tools.openmw_renderer.spike --smoke-only
```

Повторный smoke и полный gate не требуют rebuild:

```bash
python3 -m tools.openmw_renderer.spike --skip-build --smoke-only
python3 -m tools.openmw_renderer.spike --skip-build
```

## Изолированный Poison Song profile

Все пути генерируются в отдельный per-run profile; глобальный пользовательский OpenMW config не читается. Data directories перечислены от нижнего к верхнему приоритету override:

1. `bsa` — vanilla masters и BSA;
2. `Tamriel Data (SD) 44537 26.08 2026-08-23T18-34Z 9AnoA0Zl/00 Data Files`;
3. `tamriel/00 Core/Data Files` — Poison Song 26.08 core.

Fallback archive order:

1. `Morrowind.bsa`;
2. `Tribunal.bsa`;
3. `Bloodmoon.bsa`.

Render content load order:

1. `Morrowind.esm`;
2. `Tribunal.esm`;
3. `Bloodmoon.esm`;
4. `Tamriel_Data.esm`;
5. `TR_Mainland.esm`.

`Tamriel_Data.omwscripts` и `tamrielrebuilt.omwscripts` входят в pinned source-input contract и asset fingerprints, но не в render content. Реальный smoke с ними показал отсутствующие Lua resources: предоставленные Tamriel Data/TR distributions содержат manifests, но не отдельный `TD_Lua_Addons` payload. Поскольку UI, actors и dynamic gameplay намеренно исключены, статический exporter fail-closed использует ESM-only content вместо маскировки missing-resource сообщений. `TR_Factions.esp` и Firemoth patch также исключены: цель spike — точный core Poison Song basemap без необязательных gameplay layers.

Runner проверяет pinned SHA-256 обязательных ESM/BSA/omwscripts и fingerprint каждого файла во всех трёх data trees. Поэтому loose override нельзя поменять незаметно, даже если pinned top-level files остались прежними.

Игровые BSA/ESM/omwscripts, loose meshes/textures и generated profile не копируются в image. При render data trees подключаются read-only bind mounts из ignored внешнего `../morr-dev`.

## Scene и детерминизм

Exporter использует orthographic north-up LocalMap camera и scene cull mask:

`Scene | SimpleWater | Terrain | Static`

Он включает terrain, water и размещённую OpenMW `Mask_Static` geometry, в том числе meshes с alpha path, необходимую для roofs, buildings, bridges, trees и walls. `Mask_Object` (items, containers и другие runtime objects), UI, actor/player, sky/weather, fog и shadows в capture не входят; двери и activators остаются в `Mask_Static`, как их классифицирует pinned OpenMW, и захватываются в исходном состоянии без gameplay/Lua progression. LocalMap lighting зафиксирован на ambient `0.3`, diffuse `0.7`, direction `(-0.3,-0.3,0.7)`; antialiasing, reflections/refraction и wobbly shores отключены. OpenMW/OSG работают в `SingleThreaded`, random seed равен `1`, звук отключён.

Runtime контейнер дополнительно ограничен:

- `--network none` и read-only root filesystem;
- read-only game mounts, writable только generated profile/output;
- `--cap-drop ALL`, `no-new-privileges`, PID/memory limits и bounded tmpfs;
- process UID/GID текущего пользователя;
- Xvfb и Mesa software renderer `llvmpipe`;
- immutable image ID используется во всех renders одного запуска.

Эти ограничения относятся к runtime. Docker build ожидаемо требует сеть для pinned Ubuntu snapshot и OpenMW Git checkout.

## Геопривязка и tile transform

Native basemap grid сохраняет доказанный на Этапе 4 масштаб:

- одна TES3 CELL: `8192×8192` world units;
- native tile: `512×512` pixels;
- масштаб: `16` world units/pixel;
- north-up raster: `+x` вправо, `+y` вверх в world и вниз по raster идёт `-y`;
- raw capture: `544×544` pixels на `8704×8704` world units;
- symmetric gutter: `16 px = 256` world units с каждой стороны;
- crop `[16:528, 16:528]`: точные `512×512` pixels центральной CELL;
- два соседних raw captures разделяют overlap `32 px = 512` world units.

Exporter пишет lossless raw PNG. Host pipeline делает точный crop, применяет fixed integer MIM-like grade и пишет metadata-free lossless WebP. Numeric grade, ImageMagick build provenance, raw/graded/encoded hashes и world-to-pixel evidence сохраняются в report.

Runtime log обязан сообщить фактические CELL, dimensions, extent, center, bounds, raster orientation и vertical flip. Gate сравнивает эти значения с аналитической TES3 grid независимо для каждого capture; допустимая ошибка — не более одного native pixel (`16` world units).

## Пять контрольных областей

Используются те же участки, что и в LAND spike:

| Участок | CELL | World extent центрального tile |
| --- | ---: | --- |
| Balmora | `(-3,-2)` | `[-24576,-16384] × [-16384,-8192]` |
| Old Ebonheart | `(7,-19)` | `[57344,65536] × [-155648,-147456]` |
| Othrenis | `(16,-29)` | `[131072,139264] × [-237568,-229376]` |
| Gorne | `(19,-14)` | `[155648,163840] × [-114688,-106496]` |
| Nan Iban | `(41,-30)` | `[335872,344064] × [-245760,-237568]` |

Для каждого участка полный запуск делает independent center, east и north captures; затем повторяет center в новом контейнере. Center становится финальным `controls/<site>.webp`, east/north дают seam evidence, repeat даёт deterministic evidence.

## Quality gate

Автоматическая часть считается пройденной только при одновременном выполнении всех условий:

- существуют все пять native `512×512` control WebP;
- каждый runtime log подтверждает ожидаемые camera bounds/extent/orientation с ошибкой `≤ 1` native pixel;
- каждый center WebP проходит минимальные проверки содержательности, а не является пустым/чёрным кадром;
- повторные raw native RGBA, graded RGBA и encoded WebP сравниваются побайтно; дополнительно задан узкий fail-closed raster tolerance для программного renderer (`≤ 0.0001` differing fraction, `≤ 0.0001/255` mean delta, `≤ 4/255` max channel delta);
- east и north raw overlaps каждого участка сравниваются по всей полосе `32 px`; допустимы только bounded subpixel/alpha raster deltas (`≤ 0.35` differing fraction, `≤ 0.3/255` mean delta, `≤ 32/255` max channel delta), а отсутствие видимого шва обязательно подтверждается вручную;
- все ожидаемые logs присутствуют и не содержат missing resource/load messages;
- image identity, Linux/amd64 platform, pinned build manifest и software `llvmpipe` runtime подтверждены.

Автоматика не доказывает семантическое наличие конкретных объектов. Отдельный visual receipt должен подтвердить roofs, buildings, bridges, trees, walls, water и alpha geometry прямым сравнением controls с LAND/MIM/UESP references. Receipt валидна только для точных profile/execution fingerprints, SHA-256 пяти WebP/native RGBA и fingerprint полного seam evidence; stale или неполная квитанция закрывает gate.

Полный Poison Song basemap запрещено генерировать, пока обе части gate не пройдены.

## Artifacts и отчёт

Все runtime artifacts ignored и создаются в `local-data/openmw-spike/poison-song-26.08/`:

| Artifact | Назначение |
| --- | --- |
| `smoke/balmora.webp` | один быстрый capture, не закрывающий gate |
| `smoke-report.json` | pins/profile/runtime/resource evidence smoke run |
| `controls/*.webp` | пять итоговых control tiles |
| `repeat-controls/*.webp` | независимые повторные tiles для reproducibility |
| `raw/primary/*.png` | center/east/north captures с gutters |
| `raw/repeat/*.png` | повторные center captures |
| `logs/**/*.log` | OpenMW stdout/stderr и camera/resource evidence |
| `runtime/openmw-build-manifest.txt` | фактический OpenMW commit и build toolchain/packages |
| `runtime/glxinfo.txt` | доказательство Linux software OpenGL renderer |
| `report.json` | канонический full-run gate report |
| `visual-receipt.template.json` | fail-closed шаблон ручного review, привязанный к текущим artifacts |
| `visual-receipt.json` | локальная заполненная квитанция; не коммитится |

`report.json` должен содержать pins, hashes всех обязательных inputs и asset trees, exact profile order, Docker image identity, renderer/execution fingerprints, per-run timing/log paths, capture transform, control image hashes, seam deltas, repeat comparison, resource audit, runtime audit и итоговый `gate`.

## Результат выполнения

**Pass.** Полный bounded запуск выполнил 15 primary captures (center/east/north) и 5 independent repeat captures в отдельных networkless containers.

| Evidence | Фактическое значение |
| --- | --- |
| Docker image ID | `sha256:d96ddae3e12196d6b624ffb98dd87e721e3ba6c2a04ce1b410b02fe0e39e3a5b` |
| Renderer fingerprint | `5dfce52e0c1e901fcd997d74edb6ff9a62f02afd3f9cdf957c46527783c827f1` |
| Execution fingerprint | `4cfed1a3130af8b5bda72ef0d7e6d0ad315bbacb2b66ebc5892d9911c34eccef` |
| Profile fingerprint | `6964517551e0fcb0ab7614cf27c7099087eaf88075007ce2b10784809cfd5469` |
| Runtime | Linux/amd64, Mesa `llvmpipe (LLVM 20.1.2, 256 bits)` |
| Coordinate alignment | maximum runtime camera/world-to-pixel error `0 px` |
| Resource resolution | 40 logs inspected; `0` missing-resource messages |
| Reproducibility | 4/5 controls побайтно идентичны; Nan Iban: 8/262 144 pixels, `0.000030518` fraction, `0.000033379/255` mean delta, `4/255` max delta; tolerance gate passed |
| Worst seam overlap | differing fraction `0.319738`; mean channel delta `0.281264/255`; max channel delta `25/255`; numeric и visual gates passed |
| Visual coverage | roofs, buildings, bridges, trees, walls, water, alpha geometry; LAND/MIM/UESP references |

Control WebP SHA-256:

| Участок | SHA-256 |
| --- | --- |
| Balmora | `b8574f54158d7312d86d21dd944142d684e51f1dae1610a364fc2bba9dd63b84` |
| Old Ebonheart | `21df5eb1bde7011f75b848ae2bf54fb26419649332dac9682cb86f14bc0d44b6` |
| Othrenis | `f2d6f9d4da20809922c10a9cc1a061ef6726bac0f54cc61dcf384b39b01104bd` |
| Gorne | `7c01791f6df47e622c58a8988ed433b59cc92787a8855c0c4857d6f7f2196462` |
| Nan Iban | `28e292f7485874ffc85db622c167d1dc8f89c3b146b4c1da655e162d6cd25ab4` |

Визуальный review всех пяти controls и десяти east/north stitch composites не обнаружил видимых швов и подтвердил требуемые statics/alpha geometry. Итоговый `report.json` имеет все eleven gate flags `true`.

Решение: для owned Poison Song basemap использовать небольшой offline exporter поверх pinned OpenMW, не UI automation. Stage 5 разблокирован; в рамках этого spike полный basemap не генерировался.
