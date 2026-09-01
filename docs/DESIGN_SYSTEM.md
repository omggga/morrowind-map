# Дизайн-система

Обе карты используют один визуальный и интерактивный язык. Dataset-specific различия приходят только из manifest и basemap; отдельные CSS-ветки для Original и TR не допускаются.

## Инварианты

- Fonts и icons поставляются как same-origin build assets.
- Значение не кодируется только цветом: текст, форма и interaction state дублируют смысл.
- Основной текст имеет размер `11–14px`; `10px` допустим только для плотных utility labels.
- Normal text соответствует контрасту WCAG AA `4.5:1`; large text и meaningful component boundaries — `3:1`.
- Hover не заменяет selected или focus state.
- Изменение UI не изменяет basemap tiles, catalogs или dataset manifests.

## Типографика

| Роль | Шрифт | Использование |
| --- | --- | --- |
| UI и controls | Atkinson Hyperlegible Next Variable `400–700` | Body, buttons, inputs, filters, alerts, metadata |
| Display и records | Alegreya Variable `600–700` | Landing title, dataset/place names, record headings |
| Координаты и данные | IBM Plex Mono `400/500` | Coordinates, IDs, status values и map labels |

Type scale: `10 / 11 / 12 / 13 / 14 / 16 / 20 / 28px`; responsive display heading может расти до `54px`. Line-height — минимум `1.35` для compact UI и `1.5` для paragraphs. `font-synthesis: none` исключает platform-dependent synthetic weights.

Лицензии шрифтов находятся в `THIRD_PARTY_NOTICES.md` и `licenses/OFL-1.1.txt`.

## Палитра

| Token | Значение | Назначение |
| --- | --- | --- |
| Ink | `#171914` | Основной тёмный фон |
| Ash / Ash light | `#252821` / `#393d33` | Panel и hover surfaces |
| Paper / Paper dim | `#d2c69b` / `#b8ad84` | Records и вторичная структура |
| Brass / Brass light | `#b09b5f` / `#e2cf8d` | Selection и accent |
| Moss | `#566149` | Positive/local state |
| Ember | `#a5523b` | Error/destructive state |
| Line / Shadow | `#4b5042` / `#080906` | Borders и hard shadows |
| Dark text hierarchy | `#f2ead0` / `#d5ceb2` / `#b9b399` / `#a5a187` | Strong/body/muted/subtle text |
| Paper ink / muted | `#242218` / `#585239` | Text на record surfaces |
| Dark / paper focus | `#fff2b2` / `#233c46` | Keyboard focus ring |

Компоненты используют semantic roles, а не произвольные dataset colours.

## Геометрия и слои

- Spacing grid: `4 / 8 / 12 / 16 / 24 / 32px`.
- Compact controls и desktop icon buttons: `32px`; inputs и primary controls: минимум `36px`.
- На coarse pointer основные controls имеют hit area не меньше `44×44 CSS px`.
- Titlebar имеет adaptive `min-height: 64px`.
- Elevation ограничена тремя уровнями: flat divider, raised/recessed bevel и floating hard shadow.

Порядок map layers: basemap `0` → catalog markers `10` → labels `11` → personal markers `20`.

Порядок DOM overlays: content `0–3` → map controls `4` → legend `5` → ledger `6` → system/placement `7` → cards `8`. Новый уровень добавляется как именованный token, а не случайный `z-index`.

## Иконки

`apps/web/src/ui/PixelIcon.tsx` — единый набор `archive`, `back`, `open`, `zoom-in`, `zoom-out`, `fit-map`, `marker-add` и `close`. SVG используют integer paths в `16×16`, наследуют `currentColor` и остаются декоративными. Accessible name всегда задаёт owning button через visible text или `aria-label`.

## Маркеры

`apps/web/src/ui/markerSemantics.ts` задаёт одинаковые shapes для карты, списка, legend и progress controls.

| Kind | Цвет | Форма | Значение |
| --- | --- | --- | --- |
| `unvisited` | `#f6e27d` | Hollow square | Нет сохранённого progress |
| `active` | `#e88bea` | Hollow diamond | В процессе |
| `visited` | `#e9a15b` | Filled square с check cut-out | Завершено/посещено |
| `custom` | `#78db78` | Cross | Личный marker |

Hover добавляет brass frame. Selection добавляет более крупный focus-coloured frame и повышает render priority, не меняя базовую semantic shape.

## Состояния компонентов

| Состояние | Контракт |
| --- | --- |
| Default | AA text и видимая граница компонента |
| Hover | Изменение surface/border без движения hit target |
| Pressed | Recessed bevel и не более `1px` optical shift |
| Selected | Постоянный frame/rail или `aria-pressed`, не hover-only |
| Focus | `2px` outline с `3px` offset, видимый поверх selected/error |
| Disabled | Native semantics, muted treatment, отсутствие interaction |
| Loading | Стабильная геометрия, `aria-busy`/status, без ложного empty state |
| Error | Ember structure, AA text и recovery action для retryable operations |

Error использует один `alert`, progress — один `status`. Retry control остаётся mounted, блокирует повторную активацию во время операции и возвращает focus на восстановленный content либо на себя после повторной ошибки.

Overlays не создают focus trap без модального поведения. Escape/close и delete confirmation возвращают focus точному инициатору. Все функции доступны с keyboard; touch flow не зависит от hover.
