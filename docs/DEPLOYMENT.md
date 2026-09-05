# Публикация приложения

Рабочая ветка — `dev`. Изменения попадают в `main` через pull request.
Репозиторий остаётся private.

Подготовка VPS, nginx, туннеля и восстановление после сбоя описаны в
[DEPLOYMENT_RUNBOOK.md](DEPLOYMENT_RUNBOOK.md). Рабочие nginx-шаблоны находятся
в [tools/deployment/nginx](../tools/deployment/nginx/).

CI сначала проверяет committed Git objects source/LFS guard и определяет изменения
datasets, publication plan, TR config, deployment tooling и LFS rules. Затем один раз собирает приложение и упаковывает полученный
`dist` командой `pnpm deploy:package --skip-build --commit-sha "$GITHUB_SHA"`.
Пакет с SHA-256 сохраняется как artifact текущего workflow run.

При затронутых data/tool paths отдельный job `datasets` получает LFS objects,
проверяет полный active graph, сравнивает пересозданный план с
`config/dataset-upload-plan.json` и запускает `pnpm test:acceptance:prepared`.
App-only CI не скачивает tiles и оставляет LFS pointers.

После успешного `verify` и успешного либо пропущенного `datasets` job `deploy` запускается только для `push` в `main`
или ручного `workflow_dispatch` на `main`. На `dev`, других ветках и PR
публикация не выполняется. Job скачивает artifact этого же run; повторной
сборки или checkout другой версии приложения на сервере нет.

Ручной запуск: **Actions → CI → Run workflow → main**, либо:

```bash
gh workflow run ci.yml --repo omggga/morrowind-map --ref main
```

Ручной запуск также проходит все проверки перед публикацией. Если `main`
успел измениться, устаревший deploy завершится ошибкой до подключения к серверу.
Публикации выполняются последовательно в группе `morrowind-map-production`.
`queue: max` сохраняет ожидающие jobs, `cancel-in-progress: false` не отменяет
работающий deploy. На сервере дополнительный `flock` защищает переключение
`current`, health checks и возможный откат, включая одновременные ручные
запуски installer. На всё это время блокируется также смена generated datasets.

## Порядок для владельца

1. Подготовьте результат локально, выполните `pnpm deploy:datasets:plan`,
   `pnpm test:acceptance:prepared`, `pnpm datasets:stage` и `pnpm verify`.
   Helper добавляет только проверенные active generated files и записывает/stages
   `config/dataset-upload-plan.json`; contracts добавьте явно по
   [DATASET_CONTRIBUTING.md](DATASET_CONTRIBUTING.md).
2. Создайте PR в `dev` или `main`. Для data/tool changes запустите
   **Actions → Dataset review (trusted) → Run workflow → main**, задав `pr_number`.
   Workflow получает immutable PR SHA, читает Git objects и LFS data без checkout
   candidate кода и строит HTML/JSON report доверенными scripts из `main`.
3. Скачайте `dataset-review-<candidateSHA>`, проверьте `index.html`, полный
   `summary.json` и SHA текущего head PR. Отдельный job прикрепляет check
   `Dataset review (trusted)` к этому SHA. Новый commit требует нового отчёта
   и review; зелёный check подтверждает построение отчёта, а решение принимает maintainer.
4. После review и CI merge в `main` запускает dataset gate и deploy.
   Для data/tool changes `require_dataset_review` проверяет доверенное происхождение
   успешного check и workflow run для head merged PR до подключения к VPS.
   Review PR в `dev` не заменяет review нового PR, который затем входит в `main`.

Для первого bootstrap workflow review ещё отсутствует в `main`: первоначальный
merge устанавливает его, но deploy останавливается на отсутствии trusted review.
После merge вручную запустите review для номера этого initial PR, проверьте
SHA-bound artifact и повторите failed deploy в том же CI run. Новый commit
или другой head PR нельзя одобрить старым отчётом.

Private репозиторий сейчас на GitHub Free; настройка protection `main` вернула
HTTP 403. Required checks не обеспечены branch protection до смены плана и
фактического включения правил. Maintainer соблюдает порядок review/merge вручную;
проверка provenance внутри deploy остаётся отдельным барьером публикации.

## Доступ

Environment secrets в **Settings → Environments → production**:

| Secret | Значение |
| --- | --- |
| `DEPLOY_HOST` | SSH hostname/IP сервера vpsdo |
| `DEPLOY_USER` | `morrowind-map` |
| `DEPLOY_SSH_KEY` | Отдельный private SSH key для CI, без passphrase |
| `DEPLOY_KNOWN_HOSTS` | Проверенная запись host key сервера в формате known_hosts |

У environment включён режим selected deployment branches: разрешена только
ветка `main`, без правил для tags и `refs/pull/*/merge`. Эти secrets отсутствуют
на уровне репозитория. Job `verify` не использует environment или deploy-secrets;
job `datasets` и доверенный dataset-review также не используют deploy environment.
Job `deploy` получает secrets только после CI gates и только на `main` при `push`
или `workflow_dispatch`. `pull_request_target` не используется. Для fork PR
в настройках private-репозитория запрещены secrets/variables и write-токены;
их запуск также отключён. Checkout не сохраняет GitHub token в git config.

Public key с опцией `restrict` хранится в root-owned файле
`/etc/ssh/authorized_keys/morrowind-map`. Учётная запись не имеет sudo и
не может самостоятельно добавить другой разрешённый ключ. Account-level
ограничения из `tools/deployment/sshd-morrowind-map.conf` запрещают пароли,
PTY, user rc, agent/X11/TCP forwarding и tunnels. Выполнение команд установки
и SFTP для SCP остаются доступны от имени пользователя сайта.

SSH принимает только закреплённый Ed25519 host key из `DEPLOY_KNOWN_HOSTS`:
`StrictHostKeyChecking yes`, `HostKeyAlgorithms ssh-ed25519`,
`GlobalKnownHostsFile /dev/null`, `UpdateHostKeys no`. `ssh-keyscan` во время
deploy не используется. При смене host key требуется сверить новый ключ через
доверенный административный доступ и обновить environment secret.

GitHub не позволяет прочитать сохранённый private key. При его замене новый
ключ сначала проверяется, затем сохраняется в production environment; старый
ключ удаляется из серверного списка. Локальная временная копия уничтожается.

## Установка

Существующий nginx на `127.0.0.1:9003` читает
`/srv/morrowind-map/current`; публичный домен подключён через Cloudflare Tunnel.

Сначала deploy отправляет только сохранённый `config/dataset-upload-plan.json`
через `upload_datasets --probe-plan ... --host production`. Сервер проверяет
план и содержимое immutable graph. Ответ `already-staged` позволяет продолжить
без скачивания и передачи примерно 2,3 GB tiles; это обычный app-only путь.
Только ответ `missing` запускает LFS fetch публикуемого commit, полную локальную
валидацию, сравнение плана и upload с `--stage-only`. Ошибка проверки или связи
останавливает deploy, а не считается отсутствующим graph.

Uploader устанавливает `/srv/morrowind-map/data/releases/<graphSha256>` и возвращает
его путь. Он не меняет legacy `data/generated`, не удаляет другие graphs и
очищает только временный каталог своей передачи.

Затем job передаёт пакет и Python tooling того же коммита во временный каталог
`incoming-ci/<run-id>-<attempt>`. Installer проверяет checksum, полный commit SHA,
содержимое архива, manifests, hashes установленных каталогов и наличие всех
ожидаемых тайлов с суммарным размером. Тайл-хэши целиком проверяются отдельным
dataset uploader/probe на сервере; installer проверяет контракты приложения с выбранным graph.

Installer получает `--dataset-graph` из committed plan. После проверки пакет
устанавливается в `releases/<full-commit-sha>`; его `datasets/generated` ссылается
на конкретный immutable graph, а `current`
переключается атомарной заменой symlink. Повторная установка того же пакета
допускается; изменение уже установленного immutable release отвергается.
До переключения также проверяется предыдущий релиз с его generated artifacts:
если он повреждён или его данные отсутствуют, публикация останавливается,
поскольку рабочего fallback нет.

После переключения installer запускает существующий `deploy:health`
(`python3 -m tools.deployment.health_check`) для локального nginx и публичного
HTTPS-сайта. Каждой проверке отводится не более 120 секунд. Ошибка любой
проверки или таймаут атомарно возвращают прежний symlink `current`; job остаётся
failed. При первой установке без предыдущего релиза неудачный `current`
удаляется. Сам каталог неудачного релиза сохраняется для диагностики.

Nginx alias `/datasets/generated/` ведёт через `current/datasets/generated`.
Откат возвращает приложение и его dataset graph одним переключением symlink.
Он не создаёт резервных копий и не исправляет
отказ nginx, туннеля или потерю datasets. При принудительном завершении процесса
или потере сервера откат не гарантирован — нужен runbook.

До первого запуска этого workflow на существующем VPS требуется однократная
миграция: закрепить graph существующего current release и сменить nginx alias
по runbook. `data/generated` остаётся только legacy fallback для первоначальной
миграции/администрирования. Новые публикации используют явный `--dataset-graph`.

Резервное копирование, расписание snapshots и управление retention старых
релизов в этот workflow не входят. App releases и dataset graphs не удаляются
автоматически; будущая deliberate garbage collection должна учитывать ссылки
всех сохраняемых app releases. Ошибка deploy не удаляет staged graph.
Временные файлы передачи и SSH key удаляются
после job. Artifacts CI хранятся 7 дней для передачи проверенного пакета между jobs.

Для проверки пакета без переключения сайта у installer есть `--check-only`:

```bash
python3 -m tools.deployment.install_release \
  --archive <package.tar.gz> --archive-sha256 <sha256> \
  --commit-sha <full-commit-sha> --dataset-graph <graphSha256-from-plan> --check-only
```
