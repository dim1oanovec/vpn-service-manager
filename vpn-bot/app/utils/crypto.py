from __future__ import annotations

import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_PREFIX = "enc::"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.secret_key.strip()
    if not key:
        raise RuntimeError("SECRET_KEY не задан: невозможно шифровать пароли панелей")
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    """Шифрует значение. Возвращает строку с маркером enc::."""
    return _PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Расшифровывает значение. Значения без маркера считаются plaintext (legacy/сид)."""
    if not value.startswith(_PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX) :].encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError("Не удалось расшифровать пароль панели: неверный SECRET_KEY") from exc


def new_sub_id() -> str:
    """subId для subscription-ссылки 3x-ui (16 hex символов)."""
    return secrets.token_hex(8)


def short_token(length: int = 6) -> str:
    return secrets.token_hex(length // 2 or 3)


def payment_code() -> str:
    """Короткий человекочитаемый код платежа для ручной оплаты."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))
