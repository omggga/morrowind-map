# Stage 6 — Original GOTY HD

Статус: pipeline подготовлен; production render и публикация ещё не выполнены.

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

## Координаты и объём

- extent: `[-229376, -155648, 196608, 237568]`;
- tight top-left tile origin: `[-229376, 237568]`;
- `1 540` effective LAND cells на native `z7`, `198` deterministic render shards;
- sparse pyramid `z0…z7`: `1 + 1 + 4 + 10 + 33 + 115 + 410 + 1540 = 2 114` tiles;
- `4 000` соседств во всей pyramid, из них `2 964` native и `999` native cross-shard;
- EN catalog: `1 036` places / `1 205` entrances, включая `944` Vvardenfell и `92` Solstheim, unresolved destinations `0`.

Tribunal ESM/BSA входят в точный профиль и catalog, но Mournhold не имеет обычного exterior LAND. Основная карта поэтому покрывает Vvardenfell и Solstheim; Mournhold будет отдельным interior inset с собственной системой координат и не блокирует Original HD release.

## Воспроизведение

Команды выполняются из корня репозитория. Сначала проверяется план и пять независимых smoke-областей — Balmora, Vivec, Ald-ruhn, Seyda Neen и Solstheim/Fort Frostmoth — затем запускается полный render с checkpoint/resume:

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

Общий smoke вызывает пять именованных команд с shard-centres `(-3,-3)`, `(3,-12)`, `(-3,6)`, `(-3,-9)` и `(-21,18)`. Каждый результат хранится в собственном каталоге под `local-data/openmw-production/original-goty-hd-smoke`, поэтому resource logs и raw evidence не перезаписывают друг друга.

Renderer использует отдельный image `morrowind-map-openmw:0.51.0-original-hd-v1`, production root `local-data/openmw-production/original-goty-hd` и release root `local-data/openmw-release/original-goty-hd`. `dataset:prepare` разрешён только после проходящего full quality audit; catalog публикуется независимо и content-addressed.

Проверки кода pipeline:

```bash
pnpm test:original-renderer
pnpm test:catalog
```
