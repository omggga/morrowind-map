# Развёртывание и восстановление

Конфигурация сверена с vpsdo 2026-09-05: Ubuntu 22.04, nginx 1.18.0,
Python 3.10.12; системные службы `nginx` и `cloudflared`.
Порядок CI и ограничения доступа: [DEPLOYMENT.md](DEPLOYMENT.md).
Команды с `ssh vpsdo` используют административный доступ; CI работает как
`morrowind-map`. Локальные команды выполняются из корня репозитория.

## Как обслуживается сайт

```text
https://morrowindmap.com
  → Cloudflare Tunnel (cloudflared.service)
  → http://127.0.0.1:9003 (nginx.service)
  → /srv/morrowind-map/current → releases/<полный commit SHA>
  → /datasets/generated/* → current/datasets/generated/*
  → /srv/morrowind-map/data/releases/<graphSha256>/*
```

| Путь / настройка | Назначение |
| --- | --- |
| `/srv/morrowind-map/releases/<sha>` | Приложение, index, manifests, компактные metadata, release-manifest |
| `/srv/morrowind-map/current` | Атомарно заменяемый symlink активного приложения |
| `/srv/morrowind-map/releases/<sha>/datasets/generated` | Закреплённая ссылка приложения на его immutable graph |
| `/srv/morrowind-map/data/releases/<graphSha256>` | Загруженный граф generated catalogs/locales/tiles |
| `/srv/morrowind-map/data/generated` | Legacy fallback только для первоначальной миграции |
| `/srv/morrowind-map/incoming-ci/` | Временные пакеты приложения и installer |
| `/srv/morrowind-map/.app-deploy.lock` | Блокировка публикации, проверки и отката приложения |
| `/srv/morrowind-map/data/.dataset-upload.lock` | Блокировка смены данных |
| `/etc/nginx/conf.d/morrowind-map.conf` | [Шаблон сайта](../tools/deployment/nginx/morrowind-map.conf) |
| `/etc/nginx/snippets/morrowind-map-security.conf` | [Общие HTTP headers](../tools/deployment/nginx/morrowind-map-security.conf) |
| `/etc/cloudflared/config.yml` | Маршруты туннеля; на vpsdo общий для нескольких сайтов |
| `/etc/ssh/authorized_keys/morrowind-map` | Разрешённые public keys, владелец root |

Nginx слушает только loopback. TLS завершается в Cloudflare. Docker-контейнеры
на VPS в публикации этой карты не участвуют. Для сайта не нужны Node.js,
renderer или игровые файлы на VPS.

HTML, dataset index и manifests требуют revalidation. Assets, versioned metadata
и generated data имеют годовой immutable cache. Отсутствующие datasets отвечают
404 с `no-store`, без SPA fallback. Повторные include security headers внутри
locations нужны из-за правил наследования `add_header` в nginx 1.18.

## Подготовка пустого VPS

Сначала настройте доверенный административный SSH alias `vpsdo` для нужного
сервера. Следующие команды выполняются **от root на новом сервере**:

```bash
apt-get update
apt-get install -y nginx python3 openssh-server ca-certificates curl rsync
getent passwd morrowind-map || useradd --system --user-group \
  --home-dir /srv/morrowind-map --shell /bin/bash morrowind-map
install -d -o morrowind-map -g morrowind-map -m 750 \
  /srv/morrowind-map /srv/morrowind-map/releases /srv/morrowind-map/data
install -d -o morrowind-map -g morrowind-map -m 700 \
  /srv/morrowind-map/incoming-ci
usermod -a -G morrowind-map www-data
```

Пользователю сайта не выдаётся sudo. Группа позволяет nginx читать каталоги
с правами 750; worker должен получить обновлённые supplementary groups.
`current` и ссылки внутри app releases установит tooling; новый сервер не нуждается в `data/generated`.

### SSH и GitHub

Для нового сервера или утраченного ключа создайте новый отдельный Ed25519 key
во временном локальном каталоге с правами 700. Private key не записывается
в репозиторий. GitHub не позволяет скачать ранее сохранённый private key.

Передайте public key администратору сервера и установите строку
`restrict ssh-ed25519 <PUBLIC_KEY> github-actions:morrowind-map` в
`/etc/ssh/authorized_keys/morrowind-map` (root:root, 644; родитель root:root, 755).
Установите [sshd-шаблон](../tools/deployment/sshd-morrowind-map.conf) в
`/etc/ssh/sshd_config.d/60-morrowind-map-deploy.conf` (root:root, 644).

```bash
/usr/sbin/sshd -t && systemctl reload ssh
/usr/sbin/sshd -T -C user=morrowind-map,host=localhost,addr=127.0.0.1
sudo -l -U morrowind-map
```

Проверьте вход новым ключом, SCP, отсутствие sudo, запрет PTY/forwarding
и невозможность пользователя изменить root-owned authorized keys. Не закрывайте
административное подключение до успешного отдельного входа.

Получите `/etc/ssh/ssh_host_ed25519_key.pub` через доверенный административный
канал и сформируйте known_hosts: `<DEPLOY_HOST> ssh-ed25519 <HOST_PUBLIC_KEY>`.
Для нового сервера предварительно сверьте fingerprint через консоль провайдера.
Зафиксируйте его в `DEPLOY_KNOWN_HOSTS`; не отключайте strict checking ради входа.
Настройки клиентского SSH приведены в [.github/workflows/ci.yml](../.github/workflows/ci.yml).

Обновите четыре secrets в GitHub environment `production`: `DEPLOY_HOST`,
`DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`. Для файлов используется
`gh secret set NAME --repo omggga/morrowind-map --env production < FILE`.
Environment разрешает только **branch main**, без tags/PR. Этих secrets не
должно быть на уровне repository; fork PR не получают secrets или write-token.
После проверки нового ключа отзовите старый public key и удалите временную
локальную копию private key.

### Данные перед приложением

Готовый graph восстанавливается из выбранного commit: JSON находится в Git,
WebP — в LFS. Сначала проверьте наличие graph на сервере, чтобы не скачивать
tiles повторно. Исходные игровые/mod assets из GitHub не восстанавливаются.

Настройте локальный SSH alias `morrowind-map-deploy` на нужный сервер с
`User morrowind-map`, отдельным ключом и pinned known_hosts, как в CI.
Из checkout выбранного релиза:

```bash
python3 -m tools.deployment.upload_datasets \
  --probe-plan config/dataset-upload-plan.json --host morrowind-map-deploy
```

`already-staged` означает успешную проверку существующего graph на сервере.
Только при `missing` получите payload и установите его:

```bash
git lfs install
git lfs pull --include='apps/web/public/datasets/generated/**/*.webp' --exclude=''
pnpm deploy:datasets:plan
cmp config/dataset-upload-plan.json artifacts/deployment/dataset-upload-plan.json
pnpm deploy:datasets:upload --host morrowind-map-deploy --stage-only
```

Plan проверяет хэши и полный inventory локальных данных; uploader передаёт
только достижимые generated files и проверяет их на сервере. `--stage-only`
не переключает `data/generated` и не удаляет предыдущие graphs. Сохраните
`graphSha256` из committed plan для `install_release --dataset-graph`.
CI выполняет этот же probe/missing/upload порядок автоматически.
Ошибка проверки graph требует диагностики, а не загрузки поверх повреждённого
immutable каталога. Не выдавайте ошибку SSH/validation за `missing`.

### Однократная миграция действующего VPS

Этот шаг нужен **до включения нового deploy workflow**, если старый nginx
обслуживает `data/generated` напрямую. Остановите новые публикации и дождитесь
текущих installer/uploader. Проверьте действующий сайт и наличие корректного
`current/release-manifest.json`: installer использует его для проверки fallback.

```bash
ssh vpsdo 'readlink -f /srv/morrowind-map/current; readlink -f /srv/morrowind-map/data/generated'
pnpm deploy:health --base-url https://morrowindmap.com/
```

Убедитесь, что первый путь — существующий `releases/<appSHA>`, а второй —
реальный `data/releases/<graphSha256>`, соответствующий manifests текущего
приложения. Для ранее подготовленного VPS наличие и валидность предыдущего
release-manifest уже проверены; повторите проверку при восстановлении другого
сервера. Если `current/datasets/generated` уже существует, проверьте его target
и не заменяйте ссылку. Если пути ещё нет, закрепите **фактически текущий graph**:

```bash
ssh vpsdo 'flock /srv/morrowind-map/.app-deploy.lock sh -eu -c '\''
  graph=$(readlink -f /srv/morrowind-map/data/generated)
  case "$graph" in /srv/morrowind-map/data/releases/*) ;; *) exit 1 ;; esac
  test -d "$graph"
  test -f /srv/morrowind-map/current/release-manifest.json
  test ! -e /srv/morrowind-map/current/datasets/generated
  test ! -L /srv/morrowind-map/current/datasets/generated
  ln -s "$graph" /srv/morrowind-map/current/datasets/generated
'\'''
```

После pin установите новый nginx template по следующему разделу, выполните
`nginx -t`, затем reload и обе origin/public health checks. Alias теперь идёт
через `current/datasets/generated`; старый `current` остаётся рабочим fallback.
Legacy `data/generated` не удаляйте ради миграции и не используйте для смены
новых graphs. Новые deployments всегда передают `--dataset-graph`.

### Nginx

Скопируйте шаблоны с локальной машины:

```bash
scp tools/deployment/nginx/morrowind-map.conf vpsdo:/tmp/morrowind-map.conf
scp tools/deployment/nginx/morrowind-map-security.conf vpsdo:/tmp/morrowind-map-security.conf
```

Установите от root на VPS:

```bash
install -d -m 755 /etc/nginx/snippets
install -o root -g root -m 644 /tmp/morrowind-map-security.conf /etc/nginx/snippets/morrowind-map-security.conf
install -o root -g root -m 644 /tmp/morrowind-map.conf /etc/nginx/conf.d/morrowind-map.conf
nginx -t && systemctl reload nginx
```

Основной `/etc/nginx/nginx.conf` должен включать `/etc/nginx/mime.types` и
`/etc/nginx/conf.d/*.conf` внутри `http`, а workers работать как `www-data`.
Если nginx на новом сервере ещё не запущен, после `nginx -t` используйте
`systemctl enable --now nginx`. После добавления группы перезапустите nginx
на этапе первичной настройки. Для последующих изменений шаблона достаточно
`nginx -t && systemctl reload nginx`; замена приложения reload не требует.
Не заменяйте общий nginx.conf и конфигурации остальных сайтов.

### Cloudflare Tunnel

На существующем VPS сохраните остальные маршруты в `/etc/cloudflared/config.yml`.
Маршрут карты должен находиться **до** завершающего catch-all:

```yaml
ingress:
  # Здесь остаются маршруты остальных сайтов.
  - hostname: morrowindmap.com
    service: http://127.0.0.1:9003
  - service: http_status:404
```

На новом VPS установите cloudflared по [официальной инструкции](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/).
Для locally managed tunnel восстановите доступ через Cloudflare account,
создайте tunnel и DNS route для `morrowindmap.com` или подключите сохранённый
tunnel credential. Задайте `tunnel` и `credentials-file` в config; credential
JSON хранится только на сервере с правами root:root 600. Эти credentials и
account certificate не входят в репозиторий. Создание tunnel/route описано в
[официальном руководстве](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/).

```bash
cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate
cloudflared --config /etc/cloudflared/config.yml tunnel ingress rule https://morrowindmap.com/
```

На новом сервере установите systemd service через
`cloudflared --config /etc/cloudflared/config.yml service install` и запустите
`systemctl enable --now cloudflared`. На существующем сервере после успешной
валидации reload конфигурации выполняется `systemctl restart cloudflared`;
это общий туннель, поэтому перезапуск затронет и другие его маршруты.

### Первая публикация

Когда nginx/tunnel готовы и действующий VPS мигрирован, используйте порядок
review → merge → CI из [DEPLOYMENT.md](DEPLOYMENT.md). Для первой установки
workflow в `main` initial merge блокирует deploy до trusted review: запустите
`dataset-review.yml` из `main` с номером initial PR, проверьте artifact его
head SHA, затем повторите failed deploy в прежнем CI run.

Для обычного повторного запуска уже проверенного `main`:

```bash
gh workflow run ci.yml --repo omggga/morrowind-map --ref main
```

Workflow должен уже присутствовать в `main`. Он проверит commit, скачает
artifact этого же run, проверит SHA-bound review при data/tool changes,
проверит graph на сервере (скачав LFS только при отсутствии), установит
приложение и проверит origin/public URL.
Без прежнего релиза неудачный первый deploy убирает `current` и остаётся failed.

## Диагностика и восстановление

Начните с read-only проверок:

```bash
ssh vpsdo 'readlink /srv/morrowind-map/current; readlink -f /srv/morrowind-map/current/datasets/generated'
ssh vpsdo 'systemctl is-active nginx cloudflared; nginx -t'
ssh vpsdo 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9003/'
pnpm deploy:health --base-url https://morrowindmap.com/
ssh vpsdo 'tail -n 60 /var/log/nginx/morrowind-map.error.log'
ssh vpsdo 'journalctl -u cloudflared -n 60 --no-pager'
```

| Симптом | Действие |
| --- | --- |
| CI сообщает `restored current` | Автооткат выполнен, job намеренно failed. Сравните readlink с `previous current` в job log; проверьте сайт и исправьте причину перед повтором. |
| Origin здоров, публичный URL не работает | Проверьте `cloudflared`, ingress rule, DNS route и Cloudflare cache rules. Откат приложения не устраняет сетевой отказ. |
| Nginx 403 | Проверьте `id www-data`, права 750 на родительских каталогах и чтение файлов; www-data должен входить в группу morrowind-map. |
| Dataset 404 или installer сообщает missing artifact | Проверьте `datasets/generated` конкретного app release, затем восстановите именно его graph через LFS, plan и stage-only upload. Legacy `data/generated` может относиться к другой версии. |
| Deploy требует trusted dataset review | Проверьте merged PR head SHA и provenance check, запустите доверенный workflow из main для этого PR, проверьте report и повторите failed deploy. |
| Host key mismatch | Сверьте host fingerprint административным каналом и обновите environment secret. |
| Публикация ожидает | Проверьте Actions concurrency и активные installer/uploader процессы; не удаляйте lock-файлы, поскольку это нарушит блокировку. |

### Ручное восстановление проверенного пакета

Используйте при неудачном релизе, потере `current` или прерванном installer.
Сначала остановите новые публикации и дождитесь окончания текущего deploy.
Выберите CI run с успешными **verify**, применимыми dataset gates и maintainer review для известного рабочего commit. Обычный
workflow отказывается публиковать устаревший SHA, поэтому для возврата на него
используется installer напрямую. Artifacts хранятся 7 дней.

В локальном checkout с доверенными deployment tools:

```bash
RUN_ID=123456789  # Замените на выбранный реальный run.
gh run view "$RUN_ID" --repo omggga/morrowind-map --json headSha,headBranch,jobs
COMMIT_SHA=$(gh run view "$RUN_ID" --repo omggga/morrowind-map --json headSha --jq .headSha)
DATASET_GRAPH=$(git show "$COMMIT_SHA:config/dataset-upload-plan.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["graphSha256"])')
PACKAGE_DIR=$(mktemp -d)
gh run download "$RUN_ID" --repo omggga/morrowind-map \
  --name "application-$COMMIT_SHA" --dir "$PACKAGE_DIR"
ARCHIVE="morrowind-map-$(printf '%.12s' "$COMMIT_SHA").tar.gz"
(cd "$PACKAGE_DIR" && shasum -a 256 -c "$ARCHIVE.sha256")
ARCHIVE_SHA=$(shasum -a 256 "$PACKAGE_DIR/$ARCHIVE" | cut -d ' ' -f 1)
tar -czf "$PACKAGE_DIR/deploy-tools.tar.gz" \
  tools/__init__.py tools/deployment/__init__.py tools/deployment/common.py \
  tools/deployment/package_release.py tools/deployment/install_release.py tools/deployment/health_check.py
REMOTE_DIR="/srv/morrowind-map/incoming-ci/recovery-$RUN_ID"
ssh vpsdo "install -d -o morrowind-map -g morrowind-map -m 750 '$REMOTE_DIR'"
scp "$PACKAGE_DIR/$ARCHIVE" "$PACKAGE_DIR/deploy-tools.tar.gz" "vpsdo:$REMOTE_DIR/"
ssh vpsdo "chown morrowind-map:morrowind-map '$REMOTE_DIR/$ARCHIVE' '$REMOTE_DIR/deploy-tools.tar.gz'"
ssh vpsdo "runuser -u morrowind-map -- sh -c 'cd $REMOTE_DIR && tar -xzf deploy-tools.tar.gz && \
  python3 -m tools.deployment.install_release --archive $ARCHIVE --archive-sha256 $ARCHIVE_SHA \
  --commit-sha $COMMIT_SHA --dataset-graph $DATASET_GRAPH --check-only'"
```

При успешном `validated` активируйте тот же пакет с обеими health checks:

```bash
ssh vpsdo "runuser -u morrowind-map -- sh -c 'cd $REMOTE_DIR && \
  python3 -m tools.deployment.install_release --archive $ARCHIVE --archive-sha256 $ARCHIVE_SHA \
  --commit-sha $COMMIT_SHA --dataset-graph $DATASET_GRAPH --health-url http://127.0.0.1:9003/ --health-url https://morrowindmap.com/'"
```

Installer использует ту же блокировку, валидацию и автоматический откат, что CI.
После проверки результата удалите только временные каталоги этой операции:
`ssh vpsdo "rm -rf -- '$REMOTE_DIR'"` и `rm -rf -- "$PACKAGE_DIR"`.

Если старый commit предшествует committed plan, получите `DATASET_GRAPH` из
закреплённого target `/srv/morrowind-map/releases/$COMMIT_SHA/datasets/generated`,
проверьте 64-символьный SHA и соответствие graph manifests этого release.
Если ссылка отсутствует у legacy release, сначала восстановите его mapping
по процедуре миграции; не назначайте ему новый graph по имени `data/generated`.

Если `current` указывает на повреждённый/утраченный релиз, installer откажется
использовать его как fallback. Сначала восстановите его файлы/данные. Если это
невозможно, при остановленных публикациях администратор может удалить **только
symlink current** под `.app-deploy.lock` и повторить процедуру как первую установку.
Не удаляйте release/data каталоги ради обхода проверки.

Если artifact истёк, повторно соберите выбранный commit в отдельном чистом
checkout: `pnpm install --frozen-lockfile`, `pnpm exec playwright install chromium`,
`pnpm verify`, `pnpm deploy:package --skip-build --commit-sha "$(git rev-parse HEAD)"`.
Получится новый проверенный пакет, а не восстановленный побайтово прежний CI artifact.
Передавайте его через тот же installer с graph выбранного commit. Потерянные
generated files восстановите из Git/LFS этого commit через stage-only uploader.
Если старый payload никогда не публиковался в Git/LFS, нужны сохранённые локальные
данные или повторный renderer/catalog pipeline с собственными inputs.

После физической потери VPS восстановление идёт в порядке: доступ и каталоги →
данные → nginx и tunnel → приложение → health. Репозиторий содержит active
prepared data (WebP через LFS), но не server backups, игровые inputs,
SSH private keys или Cloudflare credentials. Автоматический backup не настроен.
App releases и graph releases сохраняются без автоматического pruning;
будущая deliberate garbage collection должна сохранить все graphs, на которые
ссылаются остающиеся app releases. Сохранённые каталоги на одном VPS не защищают
от потери сервера.
