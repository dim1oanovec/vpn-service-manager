from __future__ import annotations

import asyncio

from app.db.models import Server
from app.services.xui.client import XuiPanel
from app.utils.crypto import decrypt
from app.utils.logging import get_logger

log = get_logger(__name__)


class PanelPool:
    """Один XuiPanel на сервер, переиспользуемый между запросами.

    Ключ кеша включает креды: смена пароля/URL в админке пересоздаёт клиент.
    """

    def __init__(self) -> None:
        self._panels: dict[str, XuiPanel] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(server: Server) -> str:
        return f"{server.id}:{server.xui_base_url}:{server.xui_username}:{hash(server.xui_password)}"

    async def get(self, server: Server) -> XuiPanel:
        key = self._key(server)
        panel = self._panels.get(key)
        if panel is not None:
            return panel
        async with self._lock:
            panel = self._panels.get(key)
            if panel is None:
                panel = XuiPanel(
                    base_url=server.xui_base_url,
                    username=server.xui_username,
                    password=decrypt(server.xui_password),
                    label=server.code,
                )
                # Старые клиенты этого же сервера с другими кредами больше не нужны
                for old_key in [
                    k for k in self._panels if k.startswith(f"{server.id}:") and k != key
                ]:
                    await self._panels.pop(old_key).aclose()
                self._panels[key] = panel
            return panel

    async def aclose(self) -> None:
        for panel in list(self._panels.values()):
            await panel.aclose()
        self._panels.clear()
        log.info("panel pool закрыт")


panel_pool = PanelPool()
