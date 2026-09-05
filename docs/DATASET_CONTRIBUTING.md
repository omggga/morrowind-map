# Вклад в готовые datasets

В Git публикуется готовый active graph, который можно открыть в браузере без OpenMW и игровых файлов. Новый render выполняется локально с собственными игровыми inputs; для TR сначала пройдите [TR_UPDATE.md](TR_UPDATE.md). CI проверяет подготовленный результат, но не рендерит игру.

## Что хранится в репозитории

- Git LFS применяется только к `apps/web/public/datasets/generated/**/*.webp`.
- Generated JSON catalogs и locales, index, manifests, metadata, audit reports и `tiles.ndjson` хранятся обычными Git blobs.
- Игровые inputs (`ESM`, `ESP`, `BSA`, `BA2`, `DDS`, `NIF` и другие исходные assets), локальные source trees, renderer checkpoints, промежуточные renders и candidate trees не добавляются ни в Git, ни в LFS.

Старые локальные generated snapshots могут оставаться на диске. Публикуйте только файлы, достижимые из текущего `datasets/index.json`; не добавляйте всё дерево `generated` или весь рабочий каталог одной командой. Не расширяйте LFS rule до всех binary files или JSON.

## Подготовка PR

Из корня репозитория, после подготовки и локальной активации нужного dataset:

```bash
git lfs install
pnpm deploy:datasets:plan
pnpm test:acceptance:prepared
pnpm datasets:stage
```

`deploy:datasets:plan` сверяет active index, manifests, catalogs, locales, audit/inventory metadata и каждый активный WebP по size/hash. План записывается в `artifacts/deployment/dataset-upload-plan.json`; он содержит полный активный graph обеих карт, а не только diff PR. `datasets:stage` снова валидирует graph, намеренно использует `git add -f` только для generated paths из `plan.files`, записывает и добавляет `config/dataset-upload-plan.json`. Общие ignore rules для generated остаются включены. Ранее tracked generated files, больше не входящие в active graph, helper убирает только из Git index, сохраняя локальные файлы. Остальные config/manifests/metadata эта команда не добавляет.

Добавьте изменённые contracts явно. Здесь `<datasetId>` — конкретный новый dataset, а список metadata paths берётся из его manifest:

```bash
git add -- config/tr-release.json apps/web/public/datasets/index.json
git add -- apps/web/public/datasets/manifests/<datasetId>.json
git add -- apps/web/public/datasets/metadata/<datasetId>/<inventorySha>/map-assets.json
```

Последняя строка — пример одного metadata файла: добавьте также каждый актуальный audit, coverage, inventory и catalog metadata файл, на который ссылается пакет. Для ручного staging используйте `git add -f -- <конкретный generated path>` строго для файлов из проверенного плана, добавляя префикс `apps/web/public/datasets/generated/` к `files[].path`; затем сохраните тот же план как `config/dataset-upload-plan.json` и добавьте его обычным `git add`. Helper предпочтительнее, поскольку также удаляет obsolete generated paths из index. Не используйте wildcard, захватывающий старые snapshots.

Просмотрите `git diff --cached --stat` и `git diff --cached --name-only`, выполните `pnpm verify`, затем создайте commit. Для его полного SHA проверьте committed tree:

```bash
python3 -m tools.deployment.git_datasets check --repo-root . --revision <fullSHA>
```

Этот guard проверяет границу source/generated и LFS-представление файлов в указанной ревизии. Проверка source tree дополняет валидацию скачанных payload bytes. После push убедитесь, что нужные LFS objects доступны; JSON pointer вместо WebP не является подготовленным dataset.

## Review, привязанный к commit

Maintainer вручную запускает `.github/workflows/dataset-review.yml` через Actions → Run workflow, выбирает workflow из `main` и задаёт `pr_number`. PR может быть направлен в `dev` или `main`. Workflow использует доверенный код из `main`, извлекает данные конкретного candidate SHA, не исполняет candidate scripts и не использует deploy environment.

Результат — Actions artifact `dataset-review-<candidateSHA>`. Скачайте и распакуйте его, откройте `index.html`: он показывает before/after tiles и изменения мест/названий. Полный список изменений находится в `summary.json`; число изображений и строк в HTML ограничено, поэтому отсутствие объекта в preview не означает отсутствие изменения. При первой публикации без базового prepared graph отчёт показывает bootstrap additions.

Перед merge maintainer сверяет candidate SHA отчёта с текущим head PR, проверяет содержимое отчёта, полный JSON и результаты CI. Отдельный job прикрепляет `Dataset review (trusted)` check к этому SHA; deploy проверяет его provenance для merged PR при data/tool changes. Любое обновление candidate commit требует нового отчёта и нового review. Зелёный check означает успешное построение отчёта; одобрение его содержимого остаётся решением maintainer. После review merge в `main` запускает CI и deploy. Если PR сначала шёл в `dev`, новый PR в `main` также проходит review своего head SHA. Bootstrap первого workflow требует review initial PR после его merge и повторного запуска blocked deploy; порядок описан в [DEPLOYMENT.md](DEPLOYMENT.md).

На момент настройки 2026-09-05 репозиторий private на GitHub Free: запрос branch protection для `main` вернул HTTP 403. Обязательные required checks сейчас **не обеспечены серверной защитой ветки**. До перехода на подходящий план и фактического включения protection maintainer соблюдает review/merge порядок вручную. Доступность защиты private branches описана в [GitHub Docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

## Локальный отчёт

С доверенным tooling и двумя подготовленными public trees выполните:

```bash
python3 -m tools.deployment.review_datasets \
  --base-public-root /absolute/path/to/base/apps/web/public \
  --base-sha <fullBaseSHA> \
  --candidate-public-root /absolute/path/to/candidate/apps/web/public \
  --candidate-sha <fullCandidateSHA> \
  --output-dir /absolute/path/to/new-review-output \
  --preview-limit 100
```

Output directory должен быть новым и находиться вне обоих input trees. Для bootstrap опустите `--base-public-root` и `--base-sha`. Открывайте созданный `index.html` вместе с соседними images и `summary.json`; OpenMW для этого не нужен. Локальный отчёт помогает исследованию, а обязательный maintainer review использует artifact доверенного workflow на точном SHA.

## CI, публикация и rollback

Обычный CI всегда проверяет source/LFS boundary. При изменениях данных, committed plan, TR config, deployment tooling или LFS rules dataset job скачивает payload, пересоздаёт полный план, сравнивает его с `config/dataset-upload-plan.json` и запускает prepared browser acceptance. App-only CI оставляет LFS pointers и не загружает тяжёлые tiles.

При deploy из `main` workflow сначала отправляет committed plan серверу через `--probe-plan`. Если graph уже проверен на сервере, LFS download/upload пропускается; только `missing` вызывает получение LFS objects публикуемого commit и uploader в `--stage-only`. Он устанавливает проверенный immutable graph в `/srv/morrowind-map/data/releases/<graphSha256>`, сохраняя предыдущие graphs и legacy `data/generated`. Installer создаёт `datasets/generated` внутри app release как ссылку на этот конкретный graph. Nginx обслуживает данные через `current/datasets/generated`, поэтому переключение `current` и rollback переключают приложение вместе с его данными. Подробности — в [DEPLOYMENT.md](DEPLOYMENT.md) и [DEPLOYMENT_RUNBOOK.md](DEPLOYMENT_RUNBOOK.md).

App releases и dataset graphs сохраняются до будущей отдельной процедуры deliberate garbage collection. Ошибка app deploy не удаляет staged graph. Автоматический backup не настроен: сохранение releases на том же сервере обеспечивает rollback, но не восстановление при потере сервера.

Git LFS имеет отдельные storage/bandwidth quotas; повторные скачивания в Actions расходуют bandwidth владельца репозитория, а новые версии файлов добавляют storage. Перед большим dataset update проверьте usage и budget в аккаунте. Текущие условия и ограничения — в [Git LFS billing](https://docs.github.com/en/billing/concepts/product-billing/git-lfs).
