# Morrowind Map

Локальная интерактивная карта Morrowind с тремя независимыми версиями мира:

1. Original Morrowind + Tribunal + Bloodmoon — EN/RU.
2. Fullrest / Tamriel Rebuilt 25.08 (Grasping Fortune) — EN/RU.
3. Tamriel Rebuilt 26.08 (Poison Song) — EN.

Original уже поддерживает локальные MIM-растры Vvardenfell и Solstheim, 1 010 мест из MIM/ESM, EN/RU, поиск, квадратные маркеры, карточку места и zoom/pan. Далее планируются статусы `unvisited` / `active` / `visited`, заметки, пользовательские маркеры, импорт прогресса Morrowind Interactive Map и локальное сохранение с JSON backup.

Текущий статус: **Этап 2 — Original end-to-end завершён**. Fullrest и Poison Song пока открывают координатные заглушки.

Подробный план: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Данные

Игровые BSA/ESM/ESP, mod assets, исходные растры и сгенерированные datasets не хранятся в Git. Репозиторий содержит код, JSON schemas, manifests без игровых данных, документацию и синтетические тестовые fixtures.

Original собирается локальным offline pipeline из соседнего `../morr-dev`:

- `bsa/*.esm` — английские GOTY masters;
- `game/Data Files/*.{cel,mrk,top}` — русские словари;
- `Maps/mim_morrowind` и `Maps/mim_bloodmoon` — MIM-каталоги и растры.

Pipeline проверяет pinned SHA-256 masters, извлекает внешние входы из ESM и пишет ignored-артефакты в `apps/web/public/datasets/generated/original-goty`. Bloodmoon JPEG привязан к точной LAND-сетке; для редких MIM-only точек используется документированная калибровка по 55 входам.

## Локальный запуск

Требуются Node.js 24+ и pnpm 11.

```bash
pnpm install
pnpm data:original
pnpm dev
```

Приложение будет доступно по адресу `http://127.0.0.1:5173`.

Полная локальная проверка, совпадающая с шагами CI:

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

Или одной командой: `pnpm verify`. Python pipeline tests входят в `pnpm test`; полная генерация игровых данных запускается отдельно и в CI не выполняется.
