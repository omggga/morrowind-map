# Stage 6 — Original GOTY HD

Статус: **Stage 6 завершён**; smoke, production render, finalize/stabilize, full audit, publication, strict validators и browser acceptance пройдены.

## Изолированный профиль

Original HD строится только из шести файлов английского GOTY-релиза в `../morr-dev/bsa`:

| Load / asset order | SHA-256 |
| --- | --- |
| `Morrowind.esm` | `5c3c8c2cbd20e25901b59b3ece33d36b7ef0e3d60ad8d11828bcc61a5ead1647` |
| `Tribunal.esm` | `2ace511f23cc2a9ddd5f3aa59c7919789b9378cf4b17c8ae3375dd6b782f3f2b` |
| `Bloodmoon.esm` | `bd27090d0e6ad4c1bf1abc83f1a2dac56fcc82cae7bfe8263c413fb301801357` |
| `Morrowind.bsa` | `3dcd5e6bfa08245521a53374bf733ee5c920df49103898a15aa31144ad64cf48` |
| `Tribunal.bsa` | `3901e7a146f7a64a4ae9534c80d5974f7ab15adf5c48c4561d9313c0f7831d69` |
| `Bloodmoon.bsa` | `7c20956791400d958cb407f0b7c1c19ceaf46719df7eb724d0b450299360bd7c` |

Mount допускает ровно эту директорию и ровно эти файлы. Tamriel Data, Tamriel Rebuilt, Fullrest, loose assets и дополнительные plugins не входят ни в load order, ни в asset resolution; лишний файл, symlink или несовпадающий hash останавливает pipeline до запуска OpenMW. Poison Song V4 использует отдельный profile/image/output и остаётся immutable: Original wrappers не меняют его renderer, tiles, catalog или manifest.

Проверенный production snapshot — `original:goty:8b2690c0ce1c954e`; полный profile hash — `8b2690c0ce1c954e603d317728b19339f4b985ce3c362b0bc0eee93b3841b2a7`. Таким образом, Original строго ограничен `Morrowind → Tribunal → Bloodmoon` и не содержит TR, Tamriel Data или Fullrest.

## Координаты и объём

- extent: `[-229376, -155648, 196608, 237568]`;
- tight top-left tile origin: `[-229376, 237568]`;
- `1 540` effective LAND cells на native `z7`, `198` deterministic render shards;
- sparse pyramid `z0…z7`: `1 + 1 + 4 + 10 + 33 + 115 + 410 + 1540 = 2 114` tiles;
- `4 000` соседств во всей pyramid, из них `2 964` native и `999` native cross-shard;
- EN catalog: `1 036` places / `1 205` entrances, включая `944` Vvardenfell и `92` Solstheim, unresolved destinations `0`, inventory `6ea0c0a0272f6c8456a947c9dc36bac5116a9cd524cc4b351fdad867cf3e0df1`.

Tribunal ESM/BSA входят в точный профиль и catalog, но Mournhold не имеет обычного exterior LAND. Основная карта поэтому покрывает Vvardenfell и Solstheim; Mournhold будет отдельным interior inset с собственной системой координат и не блокирует Original HD release.

## Release evidence

- deterministic plan: `9ad7c36652b18615234819aba986df32a89125b1365d47eddef0f847af90886c`;
- coverage: `1 540` LAND cells, `198` render shards, `2 114` published tiles;
- final basemap inventory: `aade4b98c2fb905fd2617871345292a638e3a4a25c6d036db7a3cc18bb2dd014`;
- full quality audit: `passed`, hash `44f722800682e23be1ded7dedf27d5eae19a94864b834e92b488a53ae6c7b4a0`;
- smoke: `5/5` — Balmora, Vivec, Ald-ruhn, Seyda Neen и Solstheim/Fort Frostmoth;
- full render, finalize/stabilize, audit, publish и strict validators: passed;
- real-browser acceptance: passed для Original GOTY HD и immutable Poison Song V4 на обоих настоящих prepared datasets.

В active dataset index и landing доступны ровно две независимые EN-only карты: Original GOTY HD и Poison Song V4.

## Воспроизведение

Каноническая прошедшая последовательность выполняется из корня репозитория. Сначала проверяется план и пять независимых smoke-областей — Balmora, Vivec, Ald-ruhn, Seyda Neen и Solstheim/Fort Frostmoth — затем запускается полный render с checkpoint/resume:

```bash
pnpm data:original:plan
pnpm data:original:renderer:build
pnpm data:original:renderer:smoke
pnpm data:original:renderer:render
pnpm data:original:renderer:finalize
pnpm data:original:renderer:stabilize
pnpm data:original:renderer:audit
pnpm data:original:dataset:validate
pnpm data:original:dataset:prepare
pnpm data:original:catalog:build
pnpm data:original:catalog:validate
pnpm data:original:catalog:prepare
```

Общий smoke вызывает пять именованных команд с shard-centres `(-3,-3)`, `(3,-12)`, `(-3,6)`, `(-3,-9)` и `(-21,18)`. Все пять прошли. Каждый результат хранится в собственном каталоге под `local-data/openmw-production/original-goty-hd-smoke`, поэтому resource logs и raw evidence не перезаписывают друг друга.

Renderer использует отдельный image `morrowind-map-openmw:0.51.0-original-hd-v1`, production root `local-data/openmw-production/original-goty-hd` и release root `local-data/openmw-release/original-goty-hd`. `dataset:prepare` был разрешён только после прошедшего full quality audit; basemap и catalog опубликованы независимо и content-addressed.

Проверки кода pipeline:

```bash
pnpm test:original-renderer
pnpm test:catalog
```

После подготовки обоих настоящих payload browser integration проверяется отдельным local-only gate:

```bash
pnpm test:acceptance:prepared
```

Mournhold в этот release намеренно не входит и остаётся отдельным неблокирующим inset/submap follow-up.
