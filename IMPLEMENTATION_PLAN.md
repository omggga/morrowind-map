# Текущее состояние реализации

Этот документ фиксирует только состояние действующего продукта. Технические контракты находятся в тематических документах из [README.md](README.md).

## Готовность

| Область | Состояние |
| --- | --- |
| Web runtime | Готов: landing, две карты, поиск, фильтры, labels, deep links, Back/Forward и обработка loading/error/empty/retry |
| Original GOTY HD | Готова и зафиксирована; renderer inputs, tile pyramid, каталог и manifest не входят в будущий update cycle |
| Tamriel Rebuilt | Активный релиз готов; следующий релиз выпускается через единый profile/lock workflow с новой dataset identity |
| Локальные данные | Готовы: независимый прогресс, заметки, личные маркеры, snapshot binding и JSON backup/import |
| UI | Готов: desktop, narrow portrait, landscape, touch, keyboard, focus, ARIA semantics и автоматизированный axe gate |
| Проверки | `pnpm verify` покрывает типы, lint, unit/Python suites, browser acceptance, visual tests и production build |
| Полные игровые payload | Проверяются локально через `pnpm test:acceptance:prepared`; в Git и обычном CI их нет |
| TR release tooling | Готово для повторного применения: единый orchestrator выполняет check, lock, render, audit, catalog, manifest, verify и internal atomic activation |

## Регулярная работа

Новый цикл данных возникает только при выходе Tamriel Rebuilt. Для него:

1. подготавливаются согласованные Tamriel Data и TR Core inputs;
2. создаётся новый `datasetId` и новый `snapshotId`;
3. выполняется `pnpm data:tr:release` по [TR update runbook](docs/TR_UPDATE.md);
4. активный dataset переключается только последней командой после зелёных проверок.

Каждый опубликованный payload остаётся content-addressed и неизменяемым. Обновление означает создание нового пакета и смену активной ссылки, а не перезапись существующих файлов.

## Границы

- Original GOTY HD не обновляется и не используется как шаблон release identity для TR.
- В канонический TR dataset не добавляются необъявленные плагины или частичные asset trees.
- Игровые данные и тяжёлые generated artifacts не коммитятся.
- Изменение renderer image или параметров качества требует отдельной проверки toolchain; обычный TR content update их не перестраивает.
- Активный dataset не меняется при частично завершённом или не прошедшем проверки выпуске.

## Критерий готовности репозитория

Репозиторий готов к работе, когда `pnpm verify` проходит, manifests ссылаются только на существующие content-addressed packages, а dataset index содержит Original GOTY HD и один активный релиз Tamriel Rebuilt. Для локально подготовленных игровых payload дополнительно должен проходить `pnpm test:acceptance:prepared`.
