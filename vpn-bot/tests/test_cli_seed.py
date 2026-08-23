"""Тесты сидера тарифов и агрегатора репозиториев."""

from __future__ import annotations

from app.cli import PLAN_SEEDS, seed_plans
from app.db.repositories import UnitOfWork
from app.utils.crypto import decrypt, encrypt


async def test_seed_plans_creates_all_tariffs(uow: UnitOfWork) -> None:
    created, updated = await seed_plans(uow)

    assert (created, updated) == (len(PLAN_SEEDS), 0)
    assert len(await uow.plans.list_all()) == 5


async def test_seed_plans_matches_spec_prices(uow: UnitOfWork) -> None:
    await seed_plans(uow)

    # §4 ТЗ: цены в копейках.
    expected = {
        "trial": (3, 0, 0, 1),
        "1m": (30, 19900, 150, 3),
        "3m": (90, 49900, 375, 3),
        "6m": (180, 89900, 675, 3),
        "12m": (365, 149000, 1120, 5),
    }
    for code, (days, kopeks, stars, devices) in expected.items():
        plan = await uow.plans.get_by_code(code)
        assert plan is not None, code
        assert (plan.duration_days, plan.price_kopeks, plan.price_stars, plan.device_limit) == (
            days,
            kopeks,
            stars,
            devices,
        )


async def test_seed_plans_is_idempotent(uow: UnitOfWork) -> None:
    await seed_plans(uow)
    created, updated = await seed_plans(uow)

    assert (created, updated) == (0, 0)
    assert len(await uow.plans.list_all()) == 5


async def test_seed_plans_keeps_admin_edits_without_force(uow: UnitOfWork) -> None:
    await seed_plans(uow)
    plan = await uow.plans.get_by_code("1m")
    assert plan is not None
    plan.price_kopeks = 1
    await uow.flush()

    await seed_plans(uow)

    refreshed = await uow.plans.get_by_code("1m")
    assert refreshed is not None
    assert refreshed.price_kopeks == 1, "без --force цену менять нельзя"


async def test_seed_plans_force_restores_spec_values(uow: UnitOfWork) -> None:
    await seed_plans(uow)
    plan = await uow.plans.get_by_code("1m")
    assert plan is not None
    plan.price_kopeks = 1
    await uow.flush()

    created, updated = await seed_plans(uow, force=True)

    assert (created, updated) == (0, 1)
    refreshed = await uow.plans.get_by_code("1m")
    assert refreshed is not None
    assert refreshed.price_kopeks == 19900


async def test_trial_plan_is_excluded_from_purchasable(uow: UnitOfWork) -> None:
    await seed_plans(uow)

    purchasable = await uow.plans.list_purchasable()
    codes = [p.code for p in purchasable]

    assert "trial" not in codes
    assert codes == ["1m", "3m", "6m", "12m"], "порядок задаётся sort_order"

    trial = await uow.plans.get_trial()
    assert trial is not None and trial.code == "trial"


async def test_unit_of_work_caches_repositories(uow: UnitOfWork) -> None:
    assert uow.users is uow.users
    assert uow.plans.session is uow.session


def test_panel_password_roundtrip() -> None:
    encrypted = encrypt("s3cret")

    assert encrypted.startswith("enc::")
    assert "s3cret" not in encrypted
    assert decrypt(encrypted) == "s3cret"
