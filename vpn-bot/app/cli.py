"""CLI обслуживания: сид тарифов и первого сервера, проверка БД.

Запуск::

    python -m app.cli seed              # тарифы + сервер из .env
    python -m app.cli seed-plans        # только тарифы
    python -m app.cli seed-server       # только сервер из .env
    python -m app.cli show              # что лежит в БД
    python -m app.cli healthcheck       # доступность БД

Все операции идемпотентны: повторный запуск не создаёт дублей и по умолчанию
НЕ перетирает то, что администратор мог поменять в админке.
Чтобы принудительно вернуть значения из ТЗ/`.env`, добавьте `--force`.

Миграции CLI не подменяет — сначала `alembic upgrade head`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

from app.config import settings
from app.db.repositories import UnitOfWork
from app.db.session import dispose_engine, healthcheck, session_scope
from app.utils.crypto import encrypt
from app.utils.logging import setup_logging

logger = logging.getLogger("app.cli")


@dataclass(frozen=True)
class PlanSeed:
    code: str
    title: str
    duration_days: int
    price_kopeks: int
    price_stars: int
    device_limit: int
    is_trial: bool = False
    sort_order: int = 100


# §4 ТЗ. Цены в копейках: 199 ₽ -> 19900.
PLAN_SEEDS: tuple[PlanSeed, ...] = (
    PlanSeed("trial", "Пробный", 3, 0, 0, 1, is_trial=True, sort_order=0),
    PlanSeed("1m", "1 месяц", 30, 19900, 150, 3, sort_order=10),
    PlanSeed("3m", "3 месяца", 90, 49900, 375, 3, sort_order=20),
    PlanSeed("6m", "6 месяцев", 180, 89900, 675, 3, sort_order=30),
    PlanSeed("12m", "1 год", 365, 149000, 1120, 5, sort_order=40),
)

# Поля, которые админ правит из админки: перезаписываем только с --force.
_PLAN_MANAGED_FIELDS = (
    "title",
    "duration_days",
    "price_kopeks",
    "price_stars",
    "device_limit",
    "is_trial",
    "sort_order",
)


async def seed_plans(uow: UnitOfWork, *, force: bool = False) -> tuple[int, int]:
    """Создаёт/обновляет тарифы из §4 ТЗ. Возвращает (создано, обновлено)."""
    created = updated = 0

    for seed in PLAN_SEEDS:
        plan = await uow.plans.get_by_code(seed.code)

        if plan is None:
            await uow.plans.create(
                code=seed.code,
                title=seed.title,
                duration_days=seed.duration_days,
                price_kopeks=seed.price_kopeks,
                price_stars=seed.price_stars,
                device_limit=seed.device_limit,
                is_trial=seed.is_trial,
                is_active=True,
                sort_order=seed.sort_order,
            )
            created += 1
            logger.info("тариф %s создан", seed.code)
            continue

        if not force:
            logger.debug("тариф %s уже есть — пропуск", seed.code)
            continue

        changed = False
        for field in _PLAN_MANAGED_FIELDS:
            new_value = getattr(seed, field)
            if getattr(plan, field) != new_value:
                setattr(plan, field, new_value)
                changed = True
        if changed:
            updated += 1
            logger.info("тариф %s обновлён (--force)", seed.code)

    await uow.flush()
    return created, updated


def _server_seed_ready() -> bool:
    return bool(settings.xui_base_url and settings.xui_username and settings.xui_password)


async def seed_server(uow: UnitOfWork, *, force: bool = False) -> str:
    """Создаёт первый сервер из `.env`. Возвращает 'created' | 'updated' | 'skipped'."""
    if not _server_seed_ready():
        logger.warning("сид сервера пропущен: заполните XUI_BASE_URL, XUI_USERNAME, XUI_PASSWORD")
        return "skipped"

    host = (
        settings.server_host or settings.xui_base_url.split("//", 1)[-1].split("/")[0].split(":")[0]
    )
    server = await uow.servers.get_by_code(settings.server_code)

    if server is None:
        await uow.servers.create(
            code=settings.server_code,
            country_name=settings.server_country,
            country_flag=settings.server_flag,
            xui_base_url=settings.xui_base_url,
            xui_username=settings.xui_username,
            # Пароль панели хранится только зашифрованным (§6 ТЗ).
            xui_password=encrypt(settings.xui_password),
            server_host=host,
            inbound_id=settings.xui_inbound_id,
            sub_url=settings.xui_sub_url,
            protocol="vless-reality",
            max_clients=settings.server_max_clients,
            is_active=True,
            sort_order=10,
        )
        await uow.flush()
        logger.info("сервер %s создан", settings.server_code)
        return "created"

    if not force:
        logger.info("сервер %s уже есть — пропуск (--force чтобы обновить)", settings.server_code)
        return "skipped"

    server.country_name = settings.server_country
    server.country_flag = settings.server_flag
    server.xui_base_url = settings.xui_base_url
    server.xui_username = settings.xui_username
    server.xui_password = encrypt(settings.xui_password)
    server.server_host = host
    server.inbound_id = settings.xui_inbound_id
    server.sub_url = settings.xui_sub_url
    server.max_clients = settings.server_max_clients
    await uow.flush()
    logger.info("сервер %s обновлён (--force)", settings.server_code)
    return "updated"


async def _cmd_seed(args: argparse.Namespace) -> int:
    async with session_scope() as session:
        uow = UnitOfWork(session)
        if args.what in ("all", "plans"):
            created, updated = await seed_plans(uow, force=args.force)
            print(f"тарифы: создано {created}, обновлено {updated}")
        if args.what in ("all", "server"):
            result = await seed_server(uow, force=args.force)
            print(f"сервер: {result}")
    return 0


async def _cmd_show(_args: argparse.Namespace) -> int:
    async with session_scope() as session:
        uow = UnitOfWork(session)
        plans = await uow.plans.list_all()
        servers = await uow.servers.list_all()

        print(f"Тарифы ({len(plans)}):")
        for plan in plans:
            flags = []
            if plan.is_trial:
                flags.append("trial")
            if not plan.is_active:
                flags.append("выключен")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            print(
                f"  {plan.code:<6} {plan.title:<12} {plan.duration_days:>4}д "
                f"{plan.price_kopeks / 100:>8.2f}₽ {plan.price_stars:>5}⭐ "
                f"{plan.device_limit} устр.{suffix}"
            )

        print(f"\nСерверы ({len(servers)}):")
        for server in servers:
            state = "активен" if server.is_active else "выключен"
            print(
                f"  {server.code:<8} {server.title:<16} {server.server_host:<24} "
                f"inbound={server.inbound_id} лимит={server.max_clients} {state}"
            )
    return 0


async def _cmd_healthcheck(_args: argparse.Namespace) -> int:
    ok = await healthcheck()
    print("БД доступна" if ok else "БД недоступна")
    return 0 if ok else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="перезаписать существующие записи значениями из ТЗ/.env",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="тарифы и первый сервер")
    seed.set_defaults(func=_cmd_seed, what="all")

    seed_plans_cmd = sub.add_parser("seed-plans", help="только тарифы")
    seed_plans_cmd.set_defaults(func=_cmd_seed, what="plans")

    seed_server_cmd = sub.add_parser("seed-server", help="только сервер из .env")
    seed_server_cmd.set_defaults(func=_cmd_seed, what="server")

    show = sub.add_parser("show", help="показать тарифы и серверы")
    show.set_defaults(func=_cmd_show, what=None)

    health = sub.add_parser("healthcheck", help="проверить подключение к БД")
    health.set_defaults(func=_cmd_healthcheck, what=None)

    return parser


async def _run(args: argparse.Namespace) -> int:
    try:
        return await args.func(args)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    setup_logging(level=settings.log_level, as_json=settings.log_json)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":
    sys.exit(main())
