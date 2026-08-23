from __future__ import annotations


class XuiError(Exception):
    """Базовая ошибка интеграции с 3x-ui."""


class XuiAuthError(XuiError):
    """Не удалось авторизоваться в панели."""


class XuiApiError(XuiError):
    """Панель ответила success=false."""

    def __init__(self, msg: str, *, endpoint: str | None = None) -> None:
        self.msg = msg
        self.endpoint = endpoint
        super().__init__(f"{endpoint or 'xui'}: {msg}")


class XuiTransportError(XuiError):
    """Сеть/таймаут/5xx после ретраев."""


class XuiClientNotFound(XuiError):
    """Клиента с таким email/uuid нет в панели."""


class InboundConfigError(XuiError):
    """Inbound не подходит: нет reality-настроек, неверный протокол и т.п."""
