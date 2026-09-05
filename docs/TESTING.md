# Проверки

## Основной gate

Перед commit выполняется одна команда:

```bash
pnpm verify
```

Она последовательно запускает:

- TypeScript typecheck;
- ESLint без warnings;
- Vitest unit/component suites;
- Python tests для catalog, LAND, TR renderer/release и Original renderer tooling;
- Playwright functional acceptance;
- Playwright visual/responsive/interaction suite;
- production build.

Успех означает exit code `0` всей команды. Исправление отдельного failing test не заменяет повтор полного gate.

## Полные локальные datasets

Активные prepared WebP pyramids хранятся в Git LFS, generated JSON catalogs/locales — в обычном Git. После локальной подготовки или получения реальных LFS payload bytes запускается отдельный gate:

```bash
pnpm test:acceptance:prepared
```

Он открывает обе текущие реальные карты, загружает полные catalogs и tiles и повторяет основные workflows и recovery paths. Для неактивного нового TR release используется candidate-вариант ниже.

До browser gate проверьте весь активный graph:

```bash
pnpm deploy:datasets:plan
```

Он сверяет active index, manifests, metadata и size/hash всех reachable generated files. Git LFS pointers вместо WebP не проходят проверку подготовленного graph. Для committed revision дополнительно выполняется source/LFS guard:

```bash
python3 -m tools.deployment.git_datasets check --repo-root . --revision <fullSHA>
```

Обычный CI проверяет dataset payload при изменениях данных, committed plan, TR config, deployment tooling или LFS rules: пересоздаёт план, сравнивает его с `config/dataset-upload-plan.json` и запускает prepared acceptance. App-only CI оставляет LFS pointers и не скачивает tiles. Render остаётся локальным и требует собственных игровых inputs, но просмотр готовых данных в браузере и prepared acceptance не требуют OpenMW.

Dataset PR также требует визуального review artifact `dataset-review-<candidateSHA>` из вручную запущенного на `main` workflow `dataset-review.yml` с input `pr_number`. Он использует доверенные scripts, не исполняет код candidate и не получает deploy environment. Maintainer проверяет HTML preview, полный `summary.json` и соответствие SHA текущему PR; новый commit требует нового review. Порядок и локальная команда отчёта — в [DATASET_CONTRIBUTING.md](DATASET_CONTRIBUTING.md).

В текущем private GitHub Free репозитории branch protection для `main` недоступна (при настройке получен HTTP 403). До смены плана и включения защиты прохождение проверок и review является ручным правилом maintainer; сервером required checks пока не принуждаются.

## Release-specific gate

Перед активацией нового TR dataset выполняется:

```bash
pnpm data:tr:release:verify
```

Он проверяет соответствие config, lock, plan, renderer audit, catalog audit, publication metadata и manifest-кандидата одной release identity. Этот gate дополняет, но не заменяет `pnpm verify` и prepared acceptance.

До internal activation нового TR release prepared gate читает неактивный candidate index/manifest:

```bash
pnpm test:acceptance:prepared:candidate
```

Команда использует `local-data/tr-release/candidate`, а Original и content-addressed payload продолжает читать из обычного `apps/web/public`.

Оба release-specific browser/full gates запускает `pnpm data:tr:release`; отдельная activation-команда не публикуется.

## Browser matrix

Functional acceptance работает в pinned Chromium, блокирует non-loopback traffic и проверяет:

- обе dataset cards и direct URL load;
- painted WebP canvas, pan, zoom и sparse coverage;
- search, filters, labels и place selection;
- progress, notes, personal markers и reload persistence;
- Back/Forward и URL canonicalization;
- missing, invalid, loading, partial failure, retry и recovery;
- JSON export/import и local-storage failures.

Visual suite фиксирует DPR, fonts, reduced motion и отдельные platform baselines. Обязательные viewports: `1280×720`, `390×844`, `320×568`, `844×390` и `667×375`; desktop suite также проверяет 200% reflow.

Keyboard tests покрывают порядок фокуса, видимый focus ring, Escape/close, возврат фокуса, map controls и отсутствие недостижимых действий. Automated accessibility gate использует axe для WCAG 2.2 AA, проверяет ARIA names/states, landmark structure, alerts/status и отсутствие serious/critical violations.

Touch tests используют trusted pointer/touch events для zoom, pan, marker selection и editor flow без зависимости от hover.

## Snapshot policy

Обычный test run не обновляет baselines. При намеренном изменении UI snapshots пересоздаются отдельно:

```bash
pnpm test:ui:update
```

Новые изображения принимаются только после проверки layout, текста, focus, loading/error states и обеих карт. Затем повторно запускается `pnpm verify`.

## Data pipeline tests

Pipeline tests используют synthetic inputs и не требуют proprietary game files. Они обязаны проверять:

- строгий parser release config и отказ от неизвестных/небезопасных paths;
- file/tree hashes, case-fold collisions и source identity;
- точный порядок workflow и остановку после первой ошибки;
- генерацию нового release без изменения Python-кода под конкретную версию;
- schema/identity validation manifest и content-addressed artifacts;
- атомарность активации и сохранение действующего index при ошибке.

Полный render не выполняется в обычном CI: он требует локальных игровых inputs, Docker/OpenMW и значительного времени.
