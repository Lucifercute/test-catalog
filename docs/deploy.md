# Деплой на сервер

Целевой сервер: Oracle Cloud, ARM (aarch64), Oracle Linux 9, Docker уже установлен, рядом работают
другие проекты. Домен: `84-235-235-20.sslip.io` (sslip.io резолвит его в `84.235.235.20`, DNS настраивать не нужно).

Как это устроено:
- `compose.yaml` — базовый файл, безопасный для прода: наружу публикуются только порты Caddy 80/443 (+443/udp для HTTP/3).
- `compose.override.yaml` — только для разработки (Postgres 5432, MinIO 9000/9001, Caddy на 8080). Локально Compose
  подхватывает его автоматически; на сервере он отключён через `COMPOSE_FILE=compose.yaml` в `.env`.
  `scripts/deploy.sh` дополнительно отказывается деплоить, если в итоговом конфиге опубликовано что-то кроме 80/443.
- Caddy берёт адрес сайта из `SITE_ADDRESS`: локально `:80` (HTTP), на сервере — домен, Caddy сам получает
  сертификат Let's Encrypt и редиректит 80 → 443. Сертификаты лежат в volume `caddy_data`, переживают пересборку.
- У каждого сервиса есть лимит памяти и ротация логов (10 МБ × 3) — чтобы не задушить соседей.

Ниже — то, что делается руками **один раз**. Дальше каждый деплой — `scripts/deploy.sh`.

## 1. Oracle Cloud: Security List / NSG

Console → Networking → Virtual Cloud Networks → VCN → подсеть инстанса → Security List (или NSG инстанса)
→ Add Ingress Rules, Source CIDR `0.0.0.0/0`:

| Протокол | Порт | Зачем |
|---|---|---|
| TCP | 80  | ACME HTTP-01 (выпуск сертификата) и редирект на HTTPS |
| TCP | 443 | HTTPS |
| UDP | 443 | HTTP/3 (необязательно) |

5432, 9000, 9001 **не открывать**.

## 2. На сервере: порты, firewalld, SELinux, Docker

```bash
# 80/443 должны быть свободны — рядом другие проекты. Пустой вывод = свободны.
sudo ss -ltnup '( sport = :80 or sport = :443 )'

# firewalld
# --add-service and --add-port can't be combined in one call
sudo firewall-cmd --permanent --add-service=http --add-service=https
sudo firewall-cmd --permanent --add-port=443/udp
sudo firewall-cmd --reload
sudo firewall-cmd --list-all
```

Если 80/443 уже заняты другим reverse proxy, этот стек в таком виде не поднимется — тогда нужно
проксировать на него через существующий прокси (другая схема, в этот чек-лист не входит).

Опубликованные порты Docker обходят правила firewalld (Docker ставит собственные правила nftables).
Поэтому защита Postgres/MinIO — именно отсутствие `ports:` в `compose.yaml`, а не файрвол.

**SELinux.** На Oracle Linux 9 он в режиме Enforcing (`getenforce`) — не отключайте его. Единственный
bind mount в compose (`./infra/Caddyfile`) смонтирован с `:z`, Docker сам перемаркирует файл в `container_file_t`
(остальные данные — в named volumes, им метка не нужна). Если Caddy пишет `permission denied` на Caddyfile:

```bash
ls -Z /opt/test-catalog/infra/Caddyfile   # ожидается ...:container_file_t:...
sudo ausearch -m avc -ts recent           # отказы SELinux
```

Docker без sudo для пользователя деплоя (на Oracle Linux по умолчанию `opc`):

```bash
sudo usermod -aG docker opc   # затем перелогиниться
docker compose version        # нужен Compose v2
```

## 3. Клонировать репозиторий

Репозиторий публичный, ключи для `git pull` не нужны.

```bash
sudo mkdir -p /opt/test-catalog
sudo chown opc: /opt/test-catalog
git clone https://github.com/Lucifercute/test-catalog.git /opt/test-catalog
```

## 4. Серверный `.env`

```bash
cd /opt/test-catalog
cp .env.example .env
chmod 600 .env
```

Сгенерировать секреты (каждый — отдельной командой, значения разные):

```bash
openssl rand -hex 32          # POSTGRES_PASSWORD
openssl rand -hex 32          # MINIO_ROOT_PASSWORD
openssl rand -hex 32          # INTERNAL_TOKEN
openssl rand -hex 32          # WEBHOOK_SECRET
echo "catalog-$(openssl rand -hex 4)"   # MINIO_ROOT_USER
```

Чем серверный `.env` отличается от локального:

| Переменная | На сервере | Почему |
|---|---|---|
| `COMPOSE_FILE` | `compose.yaml` | не грузить dev-override с портами БД |
| `SITE_ADDRESS` | `84-235-235-20.sslip.io` | домен → автоматический HTTPS |
| `PUBLIC_BASE_URL` | `https://84-235-235-20.sslip.io` | сюда `bot-setup` ставит webhook |
| `WEBAPP_URL` | `https://84-235-235-20.sslip.io/` | Mini App |
| `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `INTERNAL_TOKEN`, `WEBHOOK_SECRET` | сгенерированные выше | не дефолты из примера |
| `MINIO_ROOT_USER` | не `minioadmin` | |
| `BOT_TOKEN`, `ADMIN_IDS` | реальные | |
| `POSTGRES_HOST`, `MINIO_ENDPOINT_URL`, `POSTGRES_PORT`, `MINIO_API_PORT`, `MINIO_CONSOLE_PORT`, `CADDY_HTTP_PORT` | можно удалить | нужны только для запуска на хосте / dev-портов |

Важно:
- **Пароли Postgres и MinIO задайте до первого `up`.** Они применяются при инициализации volume;
  поменять их потом в `.env` недостаточно.
- **Отдельный бот для прода** (второй токен у @BotFather). У бота один webhook: `bot-setup` запускается на каждом
  `docker compose up`, так что локальный стек с тем же токеном перехватит webhook у сервера.

Проверить, что конфиг собирается и наружу торчат только 80/443:

```bash
docker compose config | grep published   # только "80" и "443"
```

## 5. Первый деплой (с вашей машины)

```bash
cp scripts/deploy.conf.example scripts/deploy.conf   # gitignored
# DEPLOY_HOST=opc@84.235.235.20
# DEPLOY_SSH_KEY=~/.ssh/<ключ от инстанса>
# DEPLOY_PATH=/opt/test-catalog
# DEPLOY_DOMAIN=84-235-235-20.sslip.io
scripts/deploy.sh
```

Скрипт: проверяет, что вы на `main` и дерево чистое → `git push` → по ssh `git pull --ff-only`, guard портов,
`docker compose up -d --build` (сначала отрабатывают one-shot `migrate`, `minio-init`, `bot-setup`) →
`docker compose ps -a` → `curl https://<домен>/api/health` с ретраями.

Первая сборка на ARM идёт долго (особенно Next.js) и требует ~1–2 ГБ RAM на время билда: лимиты compose
действуют на контейнеры, а не на сборку.

## 6. Проверка после деплоя

```bash
curl -I http://84-235-235-20.sslip.io/             # 308 → https://
curl https://84-235-235-20.sslip.io/api/health     # {"status":"ok"}
curl -I https://84-235-235-20.sslip.io/            # 200, каталог
nc -zv -w 3 84.235.235.20 5432                     # должен НЕ подключиться (так же 9000, 9001)
```

На сервере:

```bash
docker compose ps -a
docker stats --no-stream            # никто не упирается в лимит памяти
docker compose logs caddy | grep -i certificate   # сертификат выпущен
```

В Telegram: кнопка меню открывает каталог (Mini App), фото с подписью от админа создаёт товар.

## Если что-то пошло не так

- **Сертификат не выпускается** — `docker compose logs caddy`. Обычно закрыт 80 (Security List / firewalld) или
  порт занят. sslip.io — общий домен для многих пользователей; если Let's Encrypt упрётся в rate limit,
  Caddy автоматически попробует ZeroSSL.
- **`deploy.sh`: refusing: would publish ports …** — в серверном `.env` нет `COMPOSE_FILE=compose.yaml`.
- **`git pull --ff-only` падает** — на сервере правили файлы руками или история переписана; разобраться руками
  (`git status`, `git log`), на сервере ничего не коммитить.
