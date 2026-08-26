# Morrowind Map

Локальная интерактивная карта Morrowind с тремя независимыми версиями мира:

1. Original Morrowind + Tribunal + Bloodmoon — EN/RU.
2. Fullrest / Tamriel Rebuilt 25.08 (Grasping Fortune) — EN/RU.
3. Tamriel Rebuilt 26.08 (Poison Song) — EN.

Планируются поиск, масштабирование, статусы `unvisited` / `active` / `visited`, заметки, пользовательские маркеры, импорт прогресса Morrowind Interactive Map и локальное сохранение с JSON backup.

Текущий статус: **Этап 1 — contracts и skeleton**.

Подробный план: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Данные

Игровые BSA/ESM/ESP, mod assets, исходные растры и сгенерированные тайлы не хранятся в Git. Репозиторий содержит только код, схемы, manifests без игровых данных, документацию и синтетические тестовые fixtures.

## Локальный запуск

Требуются Node.js 24+ и pnpm 11.

```bash
pnpm install
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

Или одной командой: `pnpm verify`.
