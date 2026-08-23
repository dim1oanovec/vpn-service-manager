# ТЗ: Telegram-бот VPN-сервиса на базе панели 3x-ui (Python)

> Это исходное техническое задание заказчика. Оно является источником истины.
> Любые расхождения кода с этим документом — баг в коде, а не в ТЗ.

Роль исполнителя: senior Python backend разработчик. Спроектировать и реализовать
production-ready Telegram-бота для продажи VPN-доступа. Бот НЕ управляет сервером
напрямую — он создаёт и продлевает клиентов через HTTP API панели **3x-ui**, где
inbound'ы уже настроены вручную.

Код должен быть чистым, типизированным, асинхронным. Никаких заглушек и
`pass  # TODO` в бизнес-логике. Все секреты — только через переменные окружения.

---

## 1. Стек

- Python 3.11+
- **aiogram 3.x** (Router-архитектура, FSM, свой словарь локалей)
- **httpx** (async клиент 3x-ui, с retry + таймаутами)
- **SQLAlchemy 2.0 (async)** + **Alembic** миграции
  - dev: SQLite (aiosqlite), prod: PostgreSQL (asyncpg) — переключение через `DATABASE_URL`
- **APScheduler** (AsyncIOScheduler) для крон-задач
- **pydantic-settings** для конфига
- **qrcode[pil]** для QR-кодов подписки
- **structlog** или стандартный logging с JSON-форматтером
- Redis (опционально) для FSM-storage и антифлуд-throttling
- Docker + docker-compose (bot, postgres, redis), Makefile
- pytest + pytest-asyncio, respx для мока 3x-ui API

Запуск: **long polling** по умолчанию, с опциональным webhook-режимом (aiohttp)
через флаг в конфиге.

---

## 2. Интеграция с 3x-ui (критически важная часть)

Панель может иметь кастомный `webBasePath`, поэтому базовый URL задаётся полностью:
`XUI_BASE_URL=https://panel.example.com:2053/MySecretPath`

### 2.1 Клиент `XuiClient` (`services/xui/client.py`)

Сессионная cookie-авторизация:

1. `POST {base}/login` — form-data `username`, `password` → сохранить cookie
   `3x-ui`/`session`. Cookie кэшировать в памяти; при получении 401 / редиректа
   на `/login` — автоматически релогиниться **один раз** и повторить запрос
   (декоратор `@with_relogin`).
2. Все запросы возвращают JSON вида `{"success": bool, "msg": str, "obj": ...}` —
   парсить в pydantic-модели, при `success=false` кидать `XuiApiError(msg)`.

Методы (endpoints — именно такие):

| Метод | HTTP | Path |
|---|---|---|
| `login()` | POST | `/login` |
| `list_inbounds()` | GET | `/panel/api/inbounds/list` |
| `get_inbound(id)` | GET | `/panel/api/inbounds/get/{inbound_id}` |
| `add_client(inbound_id, client)` | POST | `/panel/api/inbounds/addClient` |
| `update_client(uuid, inbound_id, client)` | POST | `/panel/api/inbounds/updateClient/{uuid}` |
| `delete_client(inbound_id, uuid)` | POST | `/panel/api/inbounds/{inbound_id}/delClient/{uuid}` |
| `get_client_traffic(email)` | GET | `/panel/api/inbounds/getClientTraffics/{email}` |
| `reset_client_traffic(inbound_id, email)` | POST | `/panel/api/inbounds/resetClientTraffic/{inbound_id}/{email}` |
| `client_ips(email)` | POST | `/panel/api/inbounds/clientIps/{email}` |
| `clear_client_ips(email)` | POST | `/panel/api/inbounds/clearClientIps/{email}` |

Важно: `addClient` и `updateClient` принимают form-data с двумя полями:

- `id` = ID inbound'а (int)
- `settings` = **JSON-строка** вида `{"clients":[{...}]}`

Модель клиента 3x-ui:

```json
{
  "id": "<uuid4>",
  "flow": "xtls-rprx-vision",
  "email": "tg<telegram_id>-<short_token>",
  "limitIp": 3,
  "totalGB": 0,
  "expiryTime": 1767225600000,
  "enable": true,
  "tgId": "",
  "subId": "<16 hex chars>",
  "comment": "",
  "reset": 0
}
```

Правила:

- `expiryTime` — миллисекунды Unix epoch (UTC). `0` = бессрочно.
- `totalGB` — байты (`0` = безлимит). Для наших тарифов всегда `0`.
- `email` — уникальный идентификатор клиента внутри панели, генерируем сами и храним в БД.
- `subId` — используется для subscription-ссылки, генерируем сами (`secrets.token_hex(8)`).
- Для VLESS+Reality всегда ставим `flow` = значение из inbound'а (обычно `xtls-rprx-vision`).

### 2.2 Генерация ссылки подключения VLESS + Reality

Из `get_inbound(id)` распарсить `streamSettings` (JSON-строка) и собрать ссылку:

```
vless://{uuid}@{host}:{port}?type={network}&security=reality&pbk={publicKey}&fp={fingerprint}&sni={serverName}&sid={shortId}&spx=%2F&flow={flow}#{label}
```

Где:

- `host` — берётся из конфига сервера (`SERVER_HOST`), НЕ из inbound (там может быть пусто/0.0.0.0)
- `pbk` — `streamSettings.realitySettings.settings.publicKey`
- `sni` — первый элемент `realitySettings.serverNames`
- `sid` — первый элемент `realitySettings.shortIds`
- `fp` — `realitySettings.settings.fingerprint` (fallback `chrome`)
- `label` — `urlencode(f"{brand} | {country_flag} {country_name}")`

Все значения URL-энкодить. Покрыть генератор ссылки unit-тестами с фикстурой
реального JSON inbound'а.

Дополнительно генерировать:

- QR-код ссылки (PNG, отдаём как photo)
- Subscription URL (если в конфиге задан `XUI_SUB_URL`): `{XUI_SUB_URL}/{subId}` —
  показывать как основной вариант для клиентов с поддержкой подписок.

### 2.3 Мульти-серверность (заложить сейчас, использовать позже)

Сейчас одна страна. Но архитектура обязана поддерживать N серверов без рефакторинга.

Таблица `servers`:

```
id, code, country_name, country_flag,
xui_base_url, xui_username, xui_password (шифровать через Fernet, ключ в env),
server_host, inbound_id, sub_url, protocol ("vless-reality"),
max_clients, is_active, sort_order, created_at
```

Логика выбора сервера: пользователь выбирает страну → если стран/серверов больше
одного, показывать меню; если один — выбирать автоматически и не спрашивать.
Балансировка: выбирать активный сервер страны с наименьшим числом активных ключей
и `active_clients < max_clients`.

Первый сервер сидится из `.env` через команду `python -m app.cli seed_server`.

---

## 3. Модель данных (SQLAlchemy)

```
users            id, telegram_id (uniq), username, first_name, language_code,
                 referrer_id (FK users, nullable), balance_kopeks (int, default 0),
                 trial_used (bool), is_banned, created_at, last_seen_at

servers          (см. §2.3)

plans            id, code, title, duration_days, price_kopeks, price_stars (int),
                 device_limit, is_trial (bool), is_active, sort_order

subscriptions    id, user_id FK, server_id FK, plan_id FK,
                 xui_client_uuid, xui_email (uniq), xui_sub_id, xui_inbound_id,
                 status enum(active|expired|disabled|deleted),
                 started_at, expires_at (UTC, timezone-aware),
                 traffic_used_bytes, last_synced_at,
                 notified_3d, notified_1d, notified_expired (bool)

payments         id, user_id FK, plan_id FK, subscription_id FK nullable,
                 provider enum(yookassa|stars|manual|balance),
                 amount_kopeks, currency, external_id (uniq nullable),
                 status enum(pending|paid|failed|refunded|canceled),
                 receipt_file_id (для manual), admin_id, payload JSON,
                 created_at, paid_at

promo_codes      id, code (uniq), type enum(percent|fixed|days),
                 value, max_uses, used_count, expires_at, is_active

promo_uses       id, promo_id FK, user_id FK, payment_id FK, created_at

referrals        id, referrer_id FK, referee_id FK, reward_kopeks, paid (bool), created_at

audit_log        id, actor_telegram_id, action, entity, entity_id, payload JSON, created_at
```

Все `datetime` — timezone-aware UTC в БД; в UI выводить в таймзоне из конфига.

---

## 4. Тарифы

Сидируются миграцией/сидером, редактируются из админки:

| code | Название | Дней | Цена | Stars | Устройств |
|---|---|---|---|---|---|
| `trial` | Пробный | 3 | 0 | 0 | 1 |
| `1m` | 1 месяц | 30 | 199 ₽ | 150 | 3 |
| `3m` | 3 месяца | 90 | 499 ₽ | 375 | 3 |
| `6m` | 6 месяцев | 180 | 899 ₽ | 675 | 3 |
| `12m` | 1 год | 365 | 1490 ₽ | 1120 | 5 |

- Трафик всегда безлимит (`totalGB = 0`).
- `device_limit` → пишется в `limitIp` клиента 3x-ui.
- Триал: только 1 раз на аккаунт. Проверки перед выдачей: `users.trial_used == false`,
  аккаунту Telegram > N дней (эвристика по `telegram_id`, настраивается), нет активной
  подписки, защита через флаг + admin-блэклист. После выдачи — `trial_used = true`
  навсегда (не сбрасывается даже при удалении подписки; сбросить может только админ).

---

## 5. Пользовательские сценарии (aiogram, все тексты на русском)

### 5.1 `/start [ref_code]`

Регистрация пользователя, сохранение реферера (если ref_code валиден и это не сам юзер).
Обязательная проверка подписки на канал (`REQUIRED_CHANNEL_ID`, если задан) — иначе
экран «Подпишитесь на канал» с кнопкой проверки.

Главное меню (inline, один message-flow с `edit_text`):

```
🔑 Мои ключи        💳 Купить VPN
🎁 Пробные 3 дня    👤 Профиль
📖 Инструкция       👥 Партнёрам
🆘 Поддержка
```

### 5.2 Покупка

Выбор страны (если одна — шаг скипается) → выбор тарифа.
Экран подтверждения: тариф, срок, устройства, цена, поле «Промокод».
Выбор способа оплаты: ЮKassa (карта) / Telegram Stars / Оплата вручную / С баланса.
После успешной оплаты — атомарная выдача доступа (см. §7).
Экран «Готово»: ссылка (в `<code>` для копирования по тапу), QR-фото, кнопки
«Инструкция», «Мои ключи».

### 5.3 Мои ключи

Список подписок: страна, тариф, «осталось N дней», трафик за период, статус.
Карточка ключа: Показать ссылку · QR · Продлить · Перевыпустить UUID · Сбросить трафик · Инструкция

- Продление: если подписка ещё активна — `expires_at += duration`; если истекла —
  считать от `now`. Тот же uuid/email сохраняется, в 3x-ui вызывается `updateClient`,
  ссылка не меняется.
- Перевыпуск: генерирует новый uuid + subId (`updateClient`), лимит — не чаще
  1 раза в 24 часа.

### 5.4 Инструкция

Пошагово по платформам с диплинками на клиенты:

- iOS/macOS — Streisand / v2box / Happ
- Android — v2rayNG / Happ
- Windows — Hiddify / v2rayN / Nekoray
- Linux — Nekoray / sing-box

Для каждой платформы: где вставить ссылку, как включить, что делать если не работает.
Тексты хранить в `app/content/guides/*.md`, рендерить с HTML parse_mode.

### 5.5 Профиль

Telegram ID, дата регистрации, баланс, активные подписки, приглашённые,
история платежей (последние 10).

### 5.6 Партнёрская программа

Реф-ссылка `https://t.me/{bot}?start=ref{user_id}`, статистика, начисление X%
(конфиг, дефолт 20%) от каждой оплаты приглашённого на внутренний баланс.
Баланс можно тратить только на покупку/продление внутри бота.

### 5.7 Поддержка

FSM «напиши сообщение» → пересылается в админ-чат с кнопкой «Ответить», ответ
админа доставляется пользователю. Никаких прямых контактов админа.

---

## 6. Оплата — три провайдера

### 6.1 ЮKassa (карты, RUB)

- Создание платежа через REST API (`https://api.yookassa.ru/v3/payments`),
  Basic auth `shop_id:secret_key`, обязательный заголовок `Idempotence-Key` (uuid4).
- `confirmation.type = redirect`, `return_url = https://t.me/{bot}`.
- Подтверждение — только через webhook `POST /webhooks/yookassa` (aiohttp):
  проверять, что событие `payment.succeeded`, IP из списка сетей ЮKassa, и **всегда
  перезапрашивать платёж по API перед выдачей** (не доверять телу вебхука).
- Дополнительно — фоновая задача-реконсиляция: раз в 5 минут проверять pending
  платежи старше 2 минут через API (страховка от потерянных вебхуков).
- Сумму и тариф брать из БД по `payment.metadata.payment_id`, никогда из
  клиентского ввода.

### 6.2 Telegram Stars (XTR)

- `bot.send_invoice(..., currency="XTR", prices=[LabeledPrice(label=..., amount=stars)])`,
  `provider_token=""`.
- `pre_checkout_query` → валидировать payload и тариф → `answer_pre_checkout_query(ok=True)`.
- `message.successful_payment` → сохранить `telegram_payment_charge_id` в
  `external_id` (уникальный индекс = защита от двойного зачисления) → выдать доступ.
- Реализовать `/refund <charge_id>` для админа (`refundStarPayment`).

### 6.3 Ручная оплата

- Экран с реквизитами из конфига (`MANUAL_PAY_DETAILS`) + сумма + уникальный код платежа.
- Пользователь отправляет скриншот/чек (photo/document) → FSM сохраняет `file_id`.
- В админ-чат уходит карточка: юзер, тариф, сумма, код, вложение + инлайн-кнопки
  ✅ Подтвердить / ❌ Отклонить (с причиной).
- Подтверждение → выдача доступа, уведомление пользователю. Отклонение → причина
  пользователю.
- Все действия админа пишутся в `audit_log`.

### 6.4 Общие требования к платежам

- Идемпотентность: уникальный индекс на `payments.external_id`; выдача доступа
  обёрнута в транзакцию + `SELECT ... FOR UPDATE` (или блокировка по ключу для SQLite).
- Один pending-платёж на пользователя одновременно (остальные — автоотмена).
- Промокоды применяются на сервере, скидка пересчитывается от прайса из БД.
- Логировать каждый переход статуса.

---

## 7. Атомарная выдача доступа (`services/provisioning.py`)

`async def grant_access(user, plan, server, payment) -> Subscription`

1. В транзакции БД: пометить платёж `paid`, зарезервировать/создать запись `subscription`.
2. Выбрать сервер (§2.3). Сгенерировать uuid4, email, subId.
3. Вызвать `xui.add_client(...)` с `expiryTime = now + duration`,
   `limitIp = plan.device_limit`, `totalGB = 0`, `enable = true`.
4. Если 3x-ui вернул ошибку — откатить транзакцию, платёж → `paid` но
   `provision_failed`, уведомить админа и пользователя («доступ выдадим в течение
   нескольких минут»), поставить задачу на retry (3 попытки с экспоненциальной задержкой).
5. Идемпотентность: если для `payment.id` уже есть подписка — вернуть её, не
   создавать вторую.
6. При продлении — `update_client`; если клиент в панели отсутствует (админ удалил
   вручную) — пересоздать его с тем же uuid и залогировать расхождение.

---

## 8. Фоновые задачи (APScheduler)

| Задача | Период | Действие |
|---|---|---|
| `sync_traffic` | 15 мин | `getClientTraffics` по всем активным → обновить `traffic_used_bytes`, `last_synced_at` |
| `expire_check` | 10 мин | подписки с `expires_at <= now` → `status=expired`, в 3x-ui `enable=false` |
| `notify_expiring` | 1 час | напоминания за 3 дня / 1 день / 3 часа (по флагам, без повторов) с кнопкой «Продлить» |
| `cleanup_deleted` | 1 день | подписки, истёкшие > N дней (конфиг, дефолт 14) → `delClient` в панели, `status=deleted` |
| `reconcile_payments` | 5 мин | добить pending-платежи ЮKassa |
| `reconcile_panel` | 6 час | сверка БД ↔ панель: «сироты» в панели без записи в БД и наоборот → отчёт админу |
| `retry_provisioning` | 2 мин | повторная выдача упавших |

Каждая задача — с локом (чтобы не дублировалась), логированием и алертом админу
при исключении.

---

## 9. Админ-панель (в боте, доступ по списку `ADMIN_IDS`)

`/admin` → inline-меню:

- **Статистика**: пользователей всего/за сутки, активных подписок, MRR, выручка за
  день/неделю/месяц, конверсия триал→оплата, разбивка по тарифам и по серверам.
- **Пользователи**: поиск по telegram_id/username → карточка: подписки, платежи,
  рефералы; действия: выдать подписку вручную (дней N), продлить, забанить,
  сбросить триал, начислить баланс.
- **Подписки**: поиск по email/uuid, отключить/включить, сбросить трафик,
  посмотреть IP-подключения (`clientIps`), очистить IP.
- **Серверы**: список, статус (пинг API + число клиентов), добавить/выключить
  сервер, сменить `inbound_id`, тест-подключение (создать тестового клиента и удалить).
- **Тарифы**: включить/выключить, изменить цену/срок/лимит устройств.
- **Промокоды**: создать (тип, значение, лимит, срок), список, деактивировать.
- **Рассылка**: текст + фото + кнопка, сегменты (все / активные / истёкшие /
  триальные / без покупок), предпросмотр, отправка батчами с rate-limit
  (≤ 25 msg/sec) и учётом `TelegramForbiddenError` (пометить пользователя
  неактивным), отчёт по завершении.
- **Платежи**: pending manual — очередь на подтверждение; экспорт CSV.
- **Логи**: последние записи `audit_log`.

---

## 10. Надёжность, безопасность, UX

- Глобальный error-handler aiogram: пользователю — вежливое сообщение, админу — traceback.
- Антифлуд middleware (throttling, 1 сообщение / 0.5 с на пользователя).
- Middleware: DI сессии БД, получение/создание пользователя, проверка бана,
  обновление `last_seen_at`.
- Никогда не логировать пароли панели, ключи ЮKassa, полные ссылки vless.
- Пароли панелей в БД — шифровать Fernet (`SECRET_KEY` из env).
- Валидировать все `callback_data` через aiogram `CallbackData` фабрики (никаких
  сырых строк).
- Проверять, что callback принадлежит пользователю (защита от подделки id в payload).
- Graceful shutdown: закрыть httpx-клиенты, дождаться планировщика, закрыть engine.
- Healthcheck endpoint `/healthz` (если webhook-режим).
- Все тексты — в одном модуле локалей, чтобы позже добавить en/uk.

---

## 11. Структура проекта

```
vpn-bot/
├─ app/
│  ├─ __main__.py            # entrypoint: polling/webhook
│  ├─ config.py              # pydantic-settings
│  ├─ bot.py                 # Bot/Dispatcher factory
│  ├─ db/
│  │  ├─ base.py  models.py  session.py
│  │  └─ repositories/       # users, subs, payments, servers, plans, promo
│  ├─ handlers/
│  │  ├─ start.py  buy.py  trial.py  keys.py  profile.py
│  │  ├─ referral.py  guides.py  support.py
│  │  ├─ payments_yookassa.py  payments_stars.py  payments_manual.py
│  │  └─ admin/  (stats.py users.py servers.py plans.py promo.py broadcast.py payments.py)
│  ├─ keyboards/             # inline фабрики + CallbackData
│  ├─ middlewares/           # db, user, throttle, ban, i18n
│  ├─ services/
│  │  ├─ xui/ (client.py models.py links.py exceptions.py)
│  │  ├─ provisioning.py  billing.py  promo.py  referral.py  notifications.py
│  │  └─ payments/ (base.py yookassa.py stars.py manual.py balance.py)
│  ├─ tasks/                 # scheduler.py + jobs/
│  ├─ web/                   # aiohttp app: /webhooks/yookassa, /healthz
│  ├─ content/guides/*.md
│  ├─ locales/ru.py
│  └─ utils/ (crypto.py qr.py time.py rate_limit.py logging.py)
├─ migrations/               # alembic
├─ tests/
├─ .env.example  Dockerfile  docker-compose.yml  Makefile  README.md
```

---

## 12. `.env.example`

```env
BOT_TOKEN=
ADMIN_IDS=
ADMIN_CHAT_ID=-1001234567890
REQUIRED_CHANNEL_ID=
BRAND_NAME=
TIMEZONE=

DATABASE_URL=
REDIS_URL=
SECRET_KEY=            # Fernet key, base64 32 bytes

# 3x-ui (сид первого сервера)
XUI_BASE_URL=
XUI_USERNAME=
XUI_PASSWORD=
XUI_INBOUND_ID=1
XUI_SUB_URL=
SERVER_HOST=
SERVER_CODE=
SERVER_COUNTRY=
SERVER_FLAG=
SERVER_MAX_CLIENTS=300

# Платежи
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
STARS_ENABLED=true
MANUAL_PAY_ENABLED=true
MANUAL_PAY_DETAILS=

# Логика
TRIAL_ENABLED=true
TRIAL_DAYS=3
REFERRAL_PERCENT=20
DELETE_EXPIRED_AFTER_DAYS=14
WEBHOOK_ENABLED=false
WEBHOOK_BASE_URL=
WEB_PORT=8080
LOG_LEVEL=INFO
```

---

## 13. Что сдать

1. Полный рабочий код по структуре выше.
2. Alembic-миграции + сидер тарифов и первого сервера.
3. Тесты: генерация vless-reality ссылки, `XuiClient` на respx-моках, расчёт
   продления, идемпотентность выдачи, применение промокода.
4. `README.md`: установка, настройка 3x-ui (что включить в панели, где взять
   `inbound_id`, `pbk`/`sni`/`sid`), настройка вебхука ЮKassa, деплой через
   docker-compose, добавление второго сервера/страны, бэкап БД.
5. Короткий раздел «Как масштабировать»: добавление стран, вынос воркера отдельным
   процессом, переход на PostgreSQL.
