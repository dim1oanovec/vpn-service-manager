from __future__ import annotations


class XuiError(Exception):
    """Базовая ошибка интеграции с 3x-ui."""


class XuiAuthError(XuiError):
    """Не удалось авторизоваться в панели (неверный логин/пароль или путь)."""


class XuiApiError(XuiError):
    """Панель вернула success=false."""

    def __init__(self, message: str, *, endpoint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.endpoint = endpoint


class XuiTransportError(XuiError):
    """Сетевая ошибка / таймаут / 5xx."""


class XuiClientNotFound(XuiError):
    """Клиента нет в панели (например, удалён вручную админом)."""
