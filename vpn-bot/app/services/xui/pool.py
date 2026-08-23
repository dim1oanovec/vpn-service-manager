from __future__ import annotations

import asyncio

from app.db.models import Server
from app.services.xui.client import XuiPanelClient
from app.utils.crypto import decrypt
from app.utils.logging import get_logger

log = get_logger(__name__)


class XuiPool:
    """
    Кеш httpx-клиентов по серверам: одна cookie-сессия на панель.
    Ключ — (server.id, base_url, username), чтобы смена кредов создавала новый клиент.
    """

    def __init__(self) -> None:
        self._clients: dict[tuple[int, str, str], XuiPanelClient] = {}
        self._lock = asyncio.Lock()

    async def get(self, server: Server) -> XuiPanelClient:
        key = (server.id, server.xui_base_url, server.xui_username)
        client = self._clients.get(key)
        if client is not None:
            return client

        async with self._lock:
            client = self._clients.get(key)
            if client is not None:
                return client
            client = XuiPanelClient(
                base_url=server.xui_base_url,
                username=server.xui_username,
                password=decrypt(server.xui_password),
            )
            self._clients[key] = client
            return client

    async def drop(self, server: Server) -> None:
        key = (server.id, server.xui_base_url, server.xui_username)
        client = self._clients.pop(key, None)
        if client is not None:
            await client.aclose()

    async def aclose(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 - graceful shutdown
                log.warning("Не удалось закрыть httpx-клиент панели", exc_info=True)


pool = XuiPool()
