# Morrowind Map

Локальное EN-only веб-приложение с двумя независимыми картами Morrowind:

| Карта | Назначение | Политика обновления |
| --- | --- | --- |
| Original GOTY HD | Vvardenfell и Solstheim из английских `Morrowind`, `Tribunal` и `Bloodmoon` | Зафиксирована и не входит в процесс обновления |
| Tamriel Rebuilt | Vvardenfell, Solstheim и TR Mainland; сейчас активен релиз 26.08 Poison Song | Каждый новый релиз собирается как новый versioned dataset и активируется после полного release gate |

Обе карты используют общий runtime: OpenLayers tile grid, каталог мест, поиск и фильтры, URL deep links, прогресс, заметки, личные маркеры и JSON backup/import. Пользовательские данные хранятся локально и привязаны к паре `datasetId` / `snapshotId`.

## Локальный запуск

Требуются Node.js `^20.19.0` либо `>=22.12.0` и pnpm `11.19.0`.

```bash
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

Игровые ESM/BSA, mod assets и сгенерированные тайлы не хранятся в Git. Репозиторий содержит приложение, renderer/catalog tooling, схемы, manifests, компактные integrity metadata, синтетические fixtures и документацию. Локальные входы и результаты pipeline находятся вне version control, преимущественно в `../morr-dev` и `local-data/`.

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
- [docs/TESTING.md](docs/TESTING.md) — обязательные проверки;
- [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) — визуальные и интерактивные контракты;
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — лицензии сторонних компонентов.
