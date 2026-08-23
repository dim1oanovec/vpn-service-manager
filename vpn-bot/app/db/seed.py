from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.repositories import Repos
from app.utils.crypto import encrypt
from app.utils.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlanSeed:
    code: str
    title: str
    duration_days: int
    price_kopeks: int
    price_stars: int
    device_limit: int
    is_trial: bool
    sort_order: int


PLAN_SEEDS: tuple[PlanSeed, ...] = (
    PlanSeed("trial", "Пробный", 3, 0, 0, 1, True, 0),
    PlanSeed("1m", "1 месяц", 30, 19900, 150, 3, False, 10),
    PlanSeed("3m", "3 месяца", 90, 49900, 375, 3, False, 20),
    PlanSeed("6m", "6 месяцев", 180, 89900, 675, 3, False, 30),
    PlanSeed("12m", "1 год", 365, 149000, 1120, 5, False, 40),
)


async def seed_plans(session: AsyncSession, *, overwrite_prices: bool = False) -> int:
    """Создаёт отсутствующие тарифы. Существующие цены не трогает без overwrite_prices."""
    repos = Repos(session)
    created = 0
    for seed in PLAN_SEEDS:
        existing = await repos.plans.by_code(seed.code)
        if existing is not None and not overwrite_prices:
            continue
        values: dict[str, object] = {
            "title": seed.title,
            "duration_days": seed.duration_days,
            "device_limit": seed.device_limit,
            "is_trial": seed.is_trial,
            "sort_order": seed.sort_order,
        }
        if existing is None or overwrite_prices:
            values["price_kopeks"] = seed.price_kopeks
            values["price_stars"] = seed.price_stars
        if existing is None:
            values["is_active"] = True
            created += 1
        await repos.plans.upsert(seed.code, **values)
    log.info("Сидер тарифов: создано %s, всего %s", created, len(PLAN_SEEDS))
    return created


async def seed_server(session: AsyncSession) -> bool:
    """Создаёт первый сервер из .env. Повторный вызов обновляет креды того же code."""
    if not (settings.xui_base_url and settings.xui_username and settings.xui_password):
        raise RuntimeError(
            "Для сида сервера нужны XUI_BASE_URL, XUI_USERNAME, XUI_PASSWORD в окружении"
        )
    if not settings.server_host:
        raise RuntimeError("SERVER_HOST обязателен: из inbound адрес брать нельзя")

    repos = Repos(session)
    existing = await repos.servers.by_code(settings.server_code)
    encrypted_password = encrypt(settings.xui_password)

    if existing is not None:
        existing.xui_base_url = settings.xui_base_url
        existing.xui_username = settings.xui_username
        existing.xui_password = encrypted_password
        existing.server_host = settings.server_host
        existing.inbound_id = settings.xui_inbound_id
        existing.sub_url = settings.xui_sub_url
        existing.country_name = settings.server_country
        existing.country_flag = settings.server_flag
        existing.max_clients = settings.server_max_clients
        await session.flush()
        log.info("Сервер %s обновлён", settings.server_code)
        return False

    await repos.servers.create(
        code=settings.server_code,
        country_name=settings.server_country,
        country_flag=settings.server_flag,
        xui_base_url=settings.xui_base_url,
        xui_username=settings.xui_username,
        xui_password=encrypted_password,
        server_host=settings.server_host,
        inbound_id=settings.xui_inbound_id,
        sub_url=settings.xui_sub_url,
        protocol="vless-reality",
        max_clients=settings.server_max_clients,
        is_active=True,
        sort_order=10,
    )
    log.info("Сервер %s создан", settings.server_code)
    return True
