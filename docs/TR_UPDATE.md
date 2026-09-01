# Обновление Tamriel Rebuilt

Этот runbook применяется только к новому релизу Tamriel Rebuilt. Original GOTY HD в него не входит.

## Требуемые входы

### Зафиксированная база

Используются те же шесть base files, что и в текущем профиле:

- `Morrowind.esm`;
- `Tribunal.esm`;
- `Bloodmoon.esm`;
- `Morrowind.bsa`;
- `Tribunal.bsa`;
- `Bloodmoon.bsa`.

Их hashes должны совпасть с release config. Замена base file является отдельным изменением renderer profile, а не обычным обновлением TR.

### Tamriel Data

Нужен полный набор из одного и того же релиза:

- `Tamriel_Data.esm`;
- `Tamriel_Data.omwscripts`;
- полное распакованное дерево Tamriel Data `Data Files` со всеми meshes, textures и другими assets.

### Tamriel Rebuilt Core

Нужен полный matching-набор из одного релиза:

- `TR_Mainland.esm`;
- `tamrielrebuilt.omwscripts`;
- полное распакованное дерево TR Core `Data Files` со всеми assets.

Нельзя смешивать ESM, scripts и asset trees разных версий или копировать только файлы, которые потребовались отдельному smoke. Optional plugins не входят в канонический profile.

Совместимость версий является входной операторской проверкой: tooling не угадывает номер релиза по содержимому ESM или asset. Берите Tamriel Data и TR Core из официально заявленной matching-пары. После этого pipeline хэширует каждый файл полных mounted trees, запрещает неожиданные ESM/ESP/OMW/BSA/scripts внутри них и связывает все результаты с одним lock; смешать набор после `lock` уже нельзя.

## Порядок загрузки

OpenMW data directories применяются в порядке base assets → Tamriel Data → TR Core, чтобы поздние деревья имели ожидаемый override priority. BSA регистрируются как `Morrowind.bsa` → `Tribunal.bsa` → `Bloodmoon.bsa`.

Content load order фиксирован:

1. `Morrowind.esm`;
2. `Tribunal.esm`;
3. `Bloodmoon.esm`;
4. `Tamriel_Data.esm`;
5. `TR_Mainland.esm`.

Оба `.omwscripts` входят в inventory и provenance, но не добавляются как `content=`.

## Release config и lock

`config/tr-release.json` — единственный human-authored профиль активной сборки. Перед новым выпуском:

1. задайте уникальный versioned `datasetId`, английские title/summary и release name/version/build;
2. обновите пути Tamriel Data и TR Core относительно `--source-root`;
3. удалите `adoptedSnapshotId` — он разрешён только точному уже опубликованному seed 26.08;
4. сохраните неизменяемые hashes шести base inputs;
5. удалите старые `sha256` у четырёх Tamriel Data/TR inputs: `check` покажет фактические hashes, а `lock` зафиксирует их;
6. удалите старую MAST exception; добавляйте новую только если parser нового matching-релиза обнаружил конкретное расхождение advertised/actual bytes;
7. проверьте regions и shard-aligned smoke controls для новой LAND topology.

Нельзя сохранять старый `datasetId` и менять только `snapshotId`: существующие пользовательские записи такого dataset намеренно вызывают snapshot conflict. Новый выпуск всегда получает обе новые identity.

Новый `snapshotId` всегда выводится из profile/source fingerprint. Нельзя задавать для будущего релиза произвольный adopted snapshot.

`local-data/tr-release/release.lock.json` генерируется из config и фактических inputs. Lock содержит нормализованные пути, hashes, tree fingerprints, derived snapshot, LAND extent/plan/topology, catalog counts и renderer/catalog producer fingerprints. Его не редактируют вручную; все последующие команды читают один и тот же lock и fail closed при расхождении входов.

## Обязательная последовательность

Сначала распакуйте matching Tamriel Data и TR Core и обновите `config/tr-release.json`. Затем запустите официальный orchestrator:

```bash
pnpm data:tr:release
```

Он выполняет следующие публичные этапы строго по порядку:

```bash
pnpm data:tr:check
pnpm data:tr:lock
pnpm data:tr:plan
pnpm data:tr:renderer:smoke
pnpm data:tr:renderer:render
pnpm data:tr:renderer:finalize
pnpm data:tr:renderer:stabilize
pnpm data:tr:renderer:audit
pnpm data:tr:dataset:validate
pnpm data:tr:dataset:prepare
pnpm data:tr:catalog:build
pnpm data:tr:catalog:validate
pnpm data:tr:catalog:prepare
pnpm data:tr:manifest:build
pnpm data:tr:release:verify
pnpm test:acceptance:prepared:candidate
pnpm verify
```

После последнего зелёного gate orchestrator сам вызывает internal atomic activation. Отдельной публичной команды activation нет.

Назначение этапов:

1. `check` валидирует config, layout, identity, exact files и отсутствие неожиданных inputs.
2. `lock` хэширует файлы и полные trees и создаёт единый immutable input contract.
3. `plan` вычисляет LAND extent, render cells, shards и output identity из lock.
4. `smoke` проверяет renderer и representative cells до полного рендера.
5. `render` создаёт native tiles с checkpoint/resume; `finalize` строит нижние zoom levels.
6. `stabilize` исправляет только границы render shards; `audit` проверяет весь release и независимые probes.
7. `dataset:*` проверяет и публикует content-addressed basemap package.
8. `catalog:*` объединяет пять ESM, проверяет audit и публикует content-addressed catalog package.
9. `manifest:build` создаёт неактивный manifest-кандидат из фактически опубликованных metadata.
10. `release:verify`, candidate prepared browser acceptance и repository gate проверяют candidate end to end.
11. internal activation повторно сверяет каждый опубликованный WebP с `tiles.ndjson`, проверяет candidate bytes и атомарно переключает manifest/index последними filesystem operations.

Если любой шаг завершился ошибкой, orchestrator останавливается до activation. Исправьте input/config или producer и снова запустите `pnpm data:tr:release`; готовые immutable outputs переиспользуются, а `render` продолжится с checkpoint только при неизменном lock и producer identity.

## Команды только для изменения toolchain

Обычный content update не пересобирает renderer image. Его собирают отдельно только при изменении OpenMW version, container recipe, rendering parameters или encoder:

```bash
pnpm data:tr:renderer:build
```

После toolchain change требуется новый smoke и весь обязательный release gate, даже если игровые inputs не изменились.

## Что попадает в Git

После activation проверяются и коммитятся только актуальные tracked contracts:

- `config/tr-release.json`;
- `apps/web/public/datasets/index.json`;
- новый `apps/web/public/datasets/manifests/<datasetId>.json`;
- компактные integrity/audit metadata в `apps/web/public/datasets/metadata/<datasetId>/`.

`local-data/tr-release/release.lock.json`, candidate tree, renderer checkpoints и generated tile/catalog payload остаются ignored local artifacts. Original manifest, metadata и generated package не меняются.

## Результат активации

После успешного `activate`:

- dataset index по-прежнему содержит ровно Original GOTY HD и один активный TR dataset;
- новый manifest ссылается только на проверенные content-addressed basemap и catalog packages;
- `datasetId` и `snapshotId` соответствуют lock и всем artifacts;
- предыдущий пакет не изменён;
- пользовательские данные нового dataset начинаются в отдельном namespace.
