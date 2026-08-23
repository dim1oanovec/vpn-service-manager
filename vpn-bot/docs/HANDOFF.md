# HANDOFF — передача разработки следующему исполнителю

Дата фиксации: 2026-08-23
Репозиторий: `github.com/dim1oanovec/vpn-service-manager`
Рабочая ветка: `v0/vpn-service-manager-950484e9`

## 0. Что сказать новой нейросети (скопируй в первое сообщение)

> Продолжи разработку Telegram-бота VPN-сервиса в репозитории
> `github.com/dim1oanovec/vpn-service-manager`, папка `vpn-bot/`.
> Полное ТЗ лежит в `vpn-bot/docs/SPEC.md` — читай его первым.
> Текущее состояние и точный план продолжения — в `vpn-bot/docs/HANDOFF.md`.
> Ничего не начинай с нуля: переиспользуй то, что уже есть в `vpn-bot/`.
> Next.js часть в корне репозитория не трогай.
> Начни с шага «Следующий шаг» из HANDOFF.md.

---

## 1. Что это за проект

Python Telegram-бот (aiogram 3) для продажи VPN-доступа. Бот не управляет сервером
напрямую — создаёт/продлевает/удаляет клиентов через HTTP API панели **3x-ui**.
Протокол VLESS + Reality. Полное ТЗ: `vpn-bot/docs/SPEC.md`.

Важно: в корне репозитория лежит пустой скелет Next.js (осталось от шаблона v0).
Он к боту не относится и не используется. Весь Python-код — только в `vpn-bot/`.

---

## 2. ФАКТИЧЕСКОЕ состояние кода (проверено `find`, не по памяти)

Готово и лежит в репозитории:

```
vpn-bot/
├─ requirements.txt          ✅ прод-зависимости
├─ requirements-dev.txt      ✅ dev-зависимости (pytest, respx, ruff, mypy)
├─ .env.example              ✅ все переменные окружения
├─ docs/SPEC.md              ✅ полное ТЗ
├─ docs/HANDOFF.md           ✅ этот файл
├─ app/
│  ├─ config.py              ✅ ГОТОВ. pydantic-settings, все поля из ТЗ,
│  │                            валидаторы admin_ids/url, свойства tz,
│  │                            yookassa_enabled, is_admin(), get_settings() с lru_cache
│  ├─ db/base.py             ✅ ГОТОВ. DeclarativeBase + NAMING_CONVENTION
│  │                            (нужно для Alembic autogenerate) + TimestampMixin
│  ├─ utils/crypto.py        ✅ Fernet шифрование паролей панелей
│  ├─ utils/logging.py       ✅ настройка логирования (JSON-режим по флагу)
│  ├─ utils/time.py          ✅ UTC-хелперы, ms-epoch конвертация для expiryTime
│  ├─ utils/qr.py            ✅ генерация QR PNG в BytesIO
│  ├─ utils/rate_limit.py    ✅ примитивы троттлинга
│  └─ (пустые пакеты с __init__.py: db/repositories, handlers, handlers/admin,
│      keyboards, locales, middlewares, services, services/payments,
│      services/xui, tasks, tasks/jobs, web, tests)
```

**Пустые пакеты — это только каркас папок.** Реального кода в них НЕТ.

### Чего ещё НЕТ (всё нужно написать)

- `app/db/models.py` — ни одной модели ещё нет
- `app/db/session.py`, `app/db/repositories/*` — нет
- `migrations/` (Alembic) — нет вообще, `alembic.ini` тоже нет
- `app/services/xui/*` (client, models, links, exceptions) — нет
- `app/services/provisioning.py`, `billing.py`, `promo.py`, `referral.py`, `notifications.py` — нет
- `app/services/payments/*` (base, yookassa, stars, manual, balance) — нет
- `app/handlers/*` (все) и `app/handlers/admin/*` — нет
- `app/keyboards/*`, `app/middlewares/*`, `app/locales/ru.py` — нет
- `app/tasks/scheduler.py` + `app/tasks/jobs/*` — нет
- `app/web/*` (aiohttp: `/webhooks/yookassa`, `/healthz`) — нет
- `app/bot.py`, `app/__main__.py`, `app/cli.py` — нет
- `app/content/guides/*.md` — нет
- `tests/*` — нет
- `Dockerfile`, `docker-compose.yml`, `Makefile`, `vpn-bot/README.md` — нет

> Предыдущие сессии обрывались из-за лимита кредитов, часть написанного не успела
> попасть в коммит. Список выше — реальное содержимое git-ветки, доверяй ему,
> а не описаниям в чате.

---

## 3. Принятые архитектурные решения (не переделывай без причины)

1. **Python-проект живёт в подпапке `vpn-bot/`**, Next.js в корне не трогаем.
2. **Конфиг** — единственный источник настроек: `from app.config import settings`.
   Новые параметры добавлять в `Settings` + в `.env.example`, а не читать `os.environ`.
3. **Naming convention в `db/base.py`** обязательна — без неё Alembic autogenerate
   генерирует безымянные constraint'ы и downgrade ломается на SQLite.
4. **Все datetime — timezone-aware UTC** в БД. Конвертация в локальную зону только
   на слое отображения (`settings.tz`).
5. **Деньги — целые копейки** (`*_kopeks: int`). Никаких float.
6. **Пароли панелей 3x-ui в БД шифруются Fernet** (`utils/crypto.py`, ключ
   `SECRET_KEY`). В логи пароли/ключи/полные vless-ссылки не попадают никогда.
7. **`expiryTime` в 3x-ui — миллисекунды epoch**, `totalGB` — байты, `0` = безлимит.
   Хелперы для этого — в `utils/time.py`.
8. **Уникальность `payments.external_id`** — основной механизм идемпотентности
   платежей. `subscriptions.xui_email` тоже уникален.
9. **Не доверять телу вебхука ЮKassa** — всегда перезапрашивать платёж по API.
10. **Известная ловушка, уже вылезала:** не ставить одновременно `unique=True` на
    колонку и отдельный `UniqueConstraint`/`Index` по ней — получается дубль
    индексов и расхождение с миграцией. Выбирать что-то одно (предпочтительно
    именованный constraint в `__table_args__`).

---

## 4. План продолжения (по порядку, каждый пункт — коммит)

1. **Слой БД**: `app/db/models.py` (все таблицы из §3 ТЗ), `app/db/session.py`
   (async engine + sessionmaker), `app/db/repositories/*` + агрегатор
   (unit-of-work) в `repositories/__init__.py`.
2. **Alembic**: `alembic.ini`, `migrations/env.py` (async), `script.py.mako`,
   начальная миграция `0001_initial`. Проверить `upgrade head` и `downgrade base`
   на SQLite. Затем сидер: `app/cli.py` с командами `seed_plans`, `seed_server`.
3. **3x-ui**: `services/xui/exceptions.py`, `models.py`, `client.py` (cookie-auth +
   `@with_relogin`), `links.py` (сборка VLESS+Reality ссылки), пул панелей на
   несколько серверов.
4. **Бизнес-логика**: `provisioning.py` (атомарная выдача, §7 ТЗ), `billing.py`
   (quote → платёж → выдача), `promo.py`, `referral.py`, `notifications.py`,
   `services/payments/*` (base, yookassa, stars, manual, balance).
5. **Локали и клавиатуры**: `locales/ru.py`, `keyboards/*` на `CallbackData` фабриках.
6. **Middlewares**: db-session DI, get-or-create user, ban-check, throttling.
7. **Хендлеры пользователя**: start, buy, trial, keys, profile, referral, guides,
   support, payments_* + `content/guides/*.md`.
8. **Админ-панель**: stats, users, subscriptions, servers, plans, promo, broadcast,
   payments, logs.
9. **Фоновые задачи**: `tasks/scheduler.py` + 7 джобов из §8 ТЗ (каждый с локом).
10. **Web + entrypoint**: `web/` (`/webhooks/yookassa`, `/healthz`), `bot.py`,
    `__main__.py` (polling/webhook), graceful shutdown.
11. **Инфраструктура и тесты**: `Dockerfile`, `docker-compose.yml`, `Makefile`,
    тесты из §13 ТЗ, `vpn-bot/README.md`.

### Следующий шаг

Пункт 1 — `app/db/models.py`. Все таблицы: `users`, `servers`, `plans`,
`subscriptions`, `payments`, `promo_codes`, `promo_uses`, `referrals`, `audit_log`
(+ таблица тикетов поддержки, если решишь хранить переписку). Затем `session.py`
и репозитории.

---

## 5. Как запустить локально (когда код появится)

```bash
cd vpn-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # заполнить BOT_TOKEN, SECRET_KEY, XUI_*
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # SECRET_KEY
alembic upgrade head
python -m app.cli seed_plans
python -m app.cli seed_server
python -m app
```

---

## 6. Правила работы для следующего исполнителя

- Читай `docs/SPEC.md` целиком перед кодом — там точные endpoint'ы 3x-ui и формат
  form-data, ошибиться легко.
- Коммить после каждого крупного блока (см. план §4). Сессия может прерваться в
  любой момент — незакоммиченное теряется.
- После каждого блока обновляй §2 этого файла (что реально готово).
- Не переписывай уже готовые `config.py`, `db/base.py`, `utils/*` — расширяй.
- Никаких заглушек и `pass # TODO` в бизнес-логике (требование ТЗ).
- Секреты только через env. В репозиторий `.env` не коммитить.
