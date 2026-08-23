from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import settings

UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def as_utc(value: datetime) -> datetime:
    """Приводит naive datetime (из SQLite) к timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_ms(value: datetime) -> int:
    """3x-ui ожидает expiryTime в миллисекундах Unix epoch."""
    return int(as_utc(value).timestamp() * 1000)


def from_ms(value: int) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def fmt_local(value: datetime | None, with_time: bool = True) -> str:
    if value is None:
        return "—"
    local = as_utc(value).astimezone(settings.tz)
    return local.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


def extend_from(current_expiry: datetime | None, days: int) -> datetime:
    """Продление: от текущей даты окончания, если она в будущем, иначе от now."""
    now = utcnow()
    base = now
    if current_expiry is not None:
        current = as_utc(current_expiry)
        if current > now:
            base = current
    return base + timedelta(days=days)


def humanize_left(expires_at: datetime | None) -> str:
    if expires_at is None:
        return "бессрочно"
    delta = as_utc(expires_at) - utcnow()
    if delta.total_seconds() <= 0:
        return "истекла"
    days = delta.days
    hours = delta.seconds // 3600
    if days > 0:
        return f"{days} дн. {hours} ч."
    minutes = (delta.seconds % 3600) // 60
    return f"{hours} ч. {minutes} мин."


def humanize_bytes(value: int | None) -> str:
    amount = float(value or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if amount < 1024 or unit == "ТБ":
            return f"{amount:.1f} {unit}" if unit != "Б" else f"{int(amount)} {unit}"
        amount /= 1024
    return f"{amount:.1f} ТБ"


def money(kopeks: int) -> str:
    rubles = kopeks / 100
    if rubles.is_integer():
        return f"{int(rubles)} ₽"
    return f"{rubles:.2f} ₽"
