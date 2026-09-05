# Morrowind Map

Локальное EN-only веб-приложение с двумя независимыми картами Morrowind:

| Карта | Назначение | Политика обновления |
| --- | --- | --- |
| Original GOTY HD | Vvardenfell и Solstheim из английских `Morrowind`, `Tribunal` и `Bloodmoon` | Зафиксирована и не входит в процесс обновления |
| Tamriel Rebuilt | Vvardenfell, Solstheim и TR Mainland; сейчас активен релиз 26.08 Poison Song | Каждый новый релиз собирается как новый versioned dataset и активируется после полного release gate |

Обе карты используют общий runtime: OpenLayers tile grid, каталог мест, поиск и фильтры, URL deep links, прогресс, заметки, личные маркеры и JSON backup/import. Пользовательские данные хранятся локально и привязаны к паре `datasetId` / `snapshotId`.

## Локальный запуск

Требуются Node.js `^20.19.0` либо `>=22.12.0` и pnpm `11.19.0`.
Для готовых реальных карт установите Git LFS и получите активные tiles; игровые
файлы и OpenMW для браузерного просмотра не нужны.

```bash
git lfs install
git lfs pull --include='apps/web/public/datasets/generated/**/*.webp' --exclude=''
pnpm install
pnpm exec playwright install chromium
pnpm dev
```

Приложение будет доступно на `http://127.0.0.1:5173`.

Основная проверка репозитория:

```bash
pnpm verify
```

Если локально подготовлены полные каталоги и тайлы обеих карт, дополнительно запускается:

```bash
pnpm test:acceptance:prepared
```

## Данные

Готовые активные WebP tiles в `apps/web/public/datasets/generated/**/*.webp` хранятся
в Git LFS; generated JSON catalogs/locales и metadata — в обычном Git.
Игровые ESM/ESP/BSA/BA2/DDS/NIF, mod inputs и промежуточные renderer outputs
остаются локальными, преимущественно в `../morr-dev` и `local-data/`.

Вклад в данные проходит plan validation, prepared browser acceptance и ручной
review HTML/JSON artifact конкретного PR SHA. `pnpm datasets:stage` добавляет
только проверенный active graph и его publication plan; stale локальные snapshots
не попадают в commit. Порядок описан в [docs/DATASET_CONTRIBUTING.md](docs/DATASET_CONTRIBUTING.md).
App-only CI не скачивает tiles. Deploy из `main` проверяет наличие immutable
graph на VPS и получает LFS payload только при его отсутствии; app release
закреплён за своим graph, поэтому rollback возвращает приложение и данные вместе.

Original GOTY HD построена только из шести зафиксированных файлов:

- `Morrowind.esm`, `Tribunal.esm`, `Bloodmoon.esm`;
- `Morrowind.bsa`, `Tribunal.bsa`, `Bloodmoon.bsa`.

Для следующего релиза Tamriel Rebuilt используется отдельный воспроизводимый workflow. После подготовки официальной matching-пары Tamriel Data / TR Core одна команда проверяет и фиксирует точные входы, создаёт новый lock, basemap, каталог и manifest, выполняет все gates и только затем атомарно переключает активную TR-карту:

```bash
pnpm data:tr:release
```

Полный набор файлов, внутренний порядок и правила публикации описаны в [docs/TR_UPDATE.md](docs/TR_UPDATE.md).

## Документация

- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — текущая готовность и границы проекта;
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — runtime, datasets и хранение данных;
- [docs/TR_UPDATE.md](docs/TR_UPDATE.md) — входы и порядок обновления Tamriel Rebuilt;
- [docs/DATASET_CONTRIBUTING.md](docs/DATASET_CONTRIBUTING.md) — Git LFS, active graph, PR и доверенный review;
- [docs/TESTING.md](docs/TESTING.md) — обязательные проверки;
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — CI artifact, автоматическая и ручная публикация `main`;
- [docs/DEPLOYMENT_RUNBOOK.md](docs/DEPLOYMENT_RUNBOOK.md) — nginx-шаблоны, подготовка VPS, диагностика и восстановление;
- [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) — визуальные и интерактивные контракты;
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — лицензии сторонних компонентов.
