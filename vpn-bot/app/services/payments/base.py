from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PaymentMethod(str, Enum):
    yookassa = "yookassa"
    stars = "stars"
    manual = "manual"
    balance = "balance"


@dataclass(slots=True)
class Quote:
    """Итоговый расчёт заказа. Считается только на сервере."""

    plan_id: int
    plan_title: str
    duration_days: int
    device_limit: int
    base_price_kopeks: int
    price_kopeks: int
    price_stars: int
    bonus_days: int = 0
    promo_code: str | None = None

    @property
    def discount_kopeks(self) -> int:
        return max(0, self.base_price_kopeks - self.price_kopeks)

    @property
    def total_days(self) -> int:
        return self.duration_days + self.bonus_days


class PaymentError(Exception):
    """Ошибка на стороне платёжного провайдера."""
