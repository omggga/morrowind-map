# Дизайн-система

Обе карты используют единый визуальный язык **Dunmer atlas under glass**. Различия Original и Tamriel Rebuilt приходят только из manifests, basemap и каталога; отдельных CSS-тем для datasets нет.

## Характер

- Главная страница показывает Original Morrowind вокруг Balmora на весь viewport как неподвижную подложку под дымчатой виньеткой.
- Выбор карты — две плоские типографические строки без card container, bevel и декоративной рамы.
- Основной интерфейс использует тёплый почти чёрный фон, песочно-золотой текст и тонкие латунные разделители.
- Карточка выбранного места выглядит как отдельный лист игрового журнала: parchment, тёмные чернила, название, progress и personal note.
- Декор не имитирует операционную систему или техническую консоль. Структурные labels показываются только когда помогают принять решение.

## Палитра

| Token | Значение | Назначение |
| --- | --- | --- |
| `--ui-void` | `#090806` | Canvas, карта до загрузки, глубокая тень |
| `--ui-panel` | `#1b1710` | Ledger, titlebar и тёмные controls |
| `--ui-brass` | `#8c7344` | Hairline-разделители и component boundaries |
| `--ui-gold` | `#d6b96f` | Основной текст и action accent на тёмном фоне |
| `--book-paper` | `#d9c79c` | Лист выбранного места |
| `--book-ink` | `#241b10` | Текст и controls на parchment |

`--ui-gold` имеет контраст `10.51:1` на `--ui-void` и `9.37:1` на `--ui-panel`. `--book-ink` на `--book-paper` — `10.17:1`. `--ui-brass` используется как structural boundary, а не как мелкий текст.

Progress и personal markers сохраняют отдельную семантическую палитру:

| Kind | Цвет | Форма |
| --- | --- | --- |
| `unvisited` | `#f6e27d` | Тонкий пустой квадрат |
| `active` | `#e88bea` | Тонкий пустой квадрат |
| `visited` | `#e9a15b` | Тонкий пустой квадрат |
| `custom` | `#78db78` | Тонкий пустой квадрат |

Цвет никогда не является единственным носителем значения: legend, filter и progress control содержат видимый текст, а selection использует `aria-pressed` и дополнительную рамку.

## Типографика

Все fonts поставляются как same-origin build assets.

| Роль | Шрифт | Использование |
| --- | --- | --- |
| Display и book | Alegreya Variable `500–700` | Landing, dataset/place names, titlebar, progress labels на parchment |
| UI и ввод | Atkinson Hyperlegible Next Variable `400–600` | Search, filters, buttons, notes, alerts |
| Диагностика | IBM Plex Mono `400/500` | Реальные IDs, error codes и технические данные |

IBM Plex Mono не используется для обычной навигации или декоративных labels. `Alegreya` preload-ится вместе с основным UI font, чтобы главный заголовок не менял метрики после первого кадра.

## Геометрия

- Spacing grid: `4 / 8 / 12 / 16 / 24 / 32px`.
- Map titlebar: `46px`, с учётом safe-area inset.
- Desktop ledger: `304px`; на средних viewport — `284px`.
- Compact icon control: `32px`; на coarse pointer hit area увеличивается до `44×44px`.
- Place card: до `376px`, одна `1px` ochre boundary, без inset bevel и corner gadget.
- Elevation используется только у настоящих overlays: parchment card, runtime alert и import/export feedback.

## Landing backdrop

Tile mosaic собирается из проверенного coverage-окна `3×3` на `z5` вокруг Balmora через `.landing-map-backdrop__grid` с `--preview-columns` и `--preview-rows`. Используются только basemap tiles Original без каталожных labels. Tiles не принимают pointer или keyboard input. Состояния loading/fallback не меняют геометрию контента; fallback остаётся тёмным атмосферным canvas.

На hover/focus строка выбора получает только лёгкую тёплую подложку и усиление стрелки. При `prefers-reduced-motion: reduce` переходы отключаются.

## Карта и overlays

Порядок map layers: basemap `0` → catalog markers `10` → labels `11` → personal markers `20`.

Порядок DOM overlays: content `0–3` → controls `4` → legend `5` → ledger `6` → system states `7` → cards `8`. Новый уровень добавляется как именованный token.

Map controls используют простые `+` и `−`. Import/export находятся справа в titlebar как компактные tray-and-arrow controls. Entrance и personal markers на canvas — небольшие тонкие пустые квадраты; подписи мест меньше основного UI-текста и рисуются без фоновой плашки или рамки. В list, legend и editor сохраняется та же square semantics с размером, подходящим для чтения и управления.

Стартовая camera после выбора карты использует `map.projection.center` из manifest и первый catalog tier `z=2`. Для выбранного `TR Mainland` стартовая точка — Old Ebonheart на `z=4`. Если URL содержит валидные `x/y/z`, эта camera authoritative: default и region focus её не заменяют.

Catalog results появляются последовательными batches при прокрутке ledger. Batch влияет только на число созданных DOM-строк: поиск, counters, markers и filters продолжают отражать полный набор совпадений.

Штатная загрузка map tiles визуально бесшумна: без status-текста, spinner и overlay поверх карты. Видимый system state появляется только для missing coverage, ошибки загрузки или доступного retry; он не сбрасывает camera, filters и selection.

## Responsive и доступность

- `1280×720`: full-viewport backdrop, выбор слева; карта использует ledger + canvas.
- До `860px`: ledger сужается до `284px`, parchment card остаётся не шире `360px`.
- До `560px`: landing choices складываются вертикально на всю доступную ширину; ledger и map stage располагаются один над другим; place card занимает ширину viewport минус `16px`.
- Landscape высотой до `480px`: titlebar остаётся `46px`, ledger самостоятельно scrollable.
- Safe-area tokens применяются к titlebar, landing и overlays.

Keyboard focus всегда имеет `2px` контрастный outline. На сфокусированной карте стрелки двигают viewport, `+`/`−` меняют zoom, а `M` по очереди открывает сохранённые personal markers. Touch flow не зависит от hover. Controls сохраняют accessible names, disabled/busy semantics и recovery actions. Error остаётся `alert`; сохранение и загрузка dataset, catalog или user data — `status`. Ожидание отдельных tiles не анонсируется как status. Overlays не создают focus trap без модального поведения.
