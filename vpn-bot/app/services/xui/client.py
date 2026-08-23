from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

import httpx

from app.services.xui.exceptions import (
    XuiApiError,
    XuiAuthError,
    XuiClientNotFound,
    XuiTransportError,
)
from app.services.xui.models import ClientTraffic, Inbound, XuiClient, XuiResponse
from app.utils.logging import get_logger

log = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

_RETRYABLE_STATUS = {500, 502, 503, 504}
_NOT_FOUND_MARKERS = ("not found", "no client", "не найден")


def with_relogin(
    func: Callable[..., Awaitable[R]],
) -> Callable[..., Awaitable[R]]:
    """При потере сессии релогинится один раз и повторяет запрос."""

    @functools.wraps(func)
    async def wrapper(self: XuiPanel, *args: Any, **kwargs: Any) -> R:
        try:
            return await func(self, *args, **kwargs)
        except XuiAuthError:
            log.warning("panel[%s]: сессия истекла, релогин", self.label)
            self._authorized = False
            await self.login()
            return await func(self, *args, **kwargs)

    return wrapper


class XuiPanel:
    """HTTP-клиент панели 3x-ui с cookie-сессией.

    base_url включает webBasePath, например https://panel.example.com:2053/secretpath
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        label: str = "xui",
        timeout: float = 20.0,
        verify_tls: bool = False,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.label = label
        self.max_retries = max_retries
        self._authorized = False
        self._login_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            verify=verify_tls,
            headers={"Accept": "application/json"},
        )

    # ---------- инфраструктура ----------

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> XuiPanel:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def login(self) -> None:
        async with self._login_lock:
            if self._authorized:
                return
            try:
                response = await self._client.post(
                    "/login", data={"username": self.username, "password": self.password}
                )
            except httpx.HTTPError as exc:
                raise XuiTransportError(f"panel[{self.label}] недоступна: {exc}") from exc

            if response.status_code != 200:
                raise XuiAuthError(
                    f"panel[{self.label}] /login вернул HTTP {response.status_code}"
                )
            try:
                payload = XuiResponse.model_validate(response.json())
            except Exception as exc:  # noqa: BLE001 - панель может вернуть HTML
                raise XuiAuthError(
                    f"panel[{self.label}]: /login вернул не JSON — проверь XUI_BASE_URL"
                ) from exc
            if not payload.success:
                raise XuiAuthError(f"panel[{self.label}]: {payload.msg or 'неверные креды'}")
            self._authorized = True
            log.info("panel[%s]: авторизация успешна", self.label)

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.request(method, path, data=data)
            except httpx.HTTPError as exc:
                last_exc = exc
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            if response.status_code in _RETRYABLE_STATUS and attempt < self.max_retries:
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            return response
        raise XuiTransportError(f"panel[{self.label}] {path}: {last_exc}")

    @with_relogin
    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> Any:
        if not self._authorized:
            await self.login()

        response = await self._raw_request(method, path, data=data)

        # Панель при истёкшей сессии отдаёт 401 либо 307/302 на /login
        if response.status_code in (401, 403) or (
            response.status_code in (301, 302, 307, 308)
            and "login" in response.headers.get("location", "")
        ):
            raise XuiAuthError("session expired")

        if response.status_code >= 400:
            raise XuiTransportError(
                f"panel[{self.label}] {path}: HTTP {response.status_code}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            if "login" in response.text.lower():
                raise XuiAuthError("session expired") from exc
            raise XuiTransportError(f"panel[{self.label}] {path}: ответ не JSON") from exc

        payload = XuiResponse.model_validate(body)
        if not payload.success:
            message = payload.msg or "unknown error"
            if any(marker in message.lower() for marker in _NOT_FOUND_MARKERS):
                raise XuiClientNotFound(message)
            raise XuiApiError(message, endpoint=path)
        return payload.obj

    # ---------- inbounds ----------

    async def list_inbounds(self) -> list[Inbound]:
        obj = await self._request("GET", "/panel/api/inbounds/list")
        return [Inbound.model_validate(item) for item in (obj or [])]

    async def get_inbound(self, inbound_id: int) -> Inbound:
        obj = await self._request("GET", f"/panel/api/inbounds/get/{inbound_id}")
        if not obj:
            raise XuiApiError(f"inbound {inbound_id} не найден")
        return Inbound.model_validate(obj)

    # ---------- clients ----------

    async def add_client(self, inbound_id: int, client: XuiClient) -> None:
        await self._request(
            "POST",
            "/panel/api/inbounds/addClient",
            data={"id": inbound_id, "settings": client.to_settings()},
        )
        log.info("panel[%s]: клиент %s добавлен в inbound %s", self.label, client.email, inbound_id)

    async def update_client(self, uuid: str, inbound_id: int, client: XuiClient) -> None:
        await self._request(
            "POST",
            f"/panel/api/inbounds/updateClient/{uuid}",
            data={"id": inbound_id, "settings": client.to_settings()},
        )
        log.info("panel[%s]: клиент %s обновлён", self.label, client.email)

    async def delete_client(self, inbound_id: int, uuid: str) -> None:
        await self._request("POST", f"/panel/api/inbounds/{inbound_id}/delClient/{uuid}")
        log.info("panel[%s]: клиент %s удалён", self.label, uuid)

    async def get_client_traffic(self, email: str) -> ClientTraffic | None:
        obj = await self._request("GET", f"/panel/api/inbounds/getClientTraffics/{email}")
        if not obj:
            return None
        if isinstance(obj, list):
            obj = obj[0] if obj else None
        return ClientTraffic.model_validate(obj) if obj else None

    async def reset_client_traffic(self, inbound_id: int, email: str) -> None:
        await self._request(
            "POST", f"/panel/api/inbounds/resetClientTraffic/{inbound_id}/{email}"
        )

    async def client_ips(self, email: str) -> list[str]:
        obj = await self._request("POST", f"/panel/api/inbounds/clientIps/{email}")
        if not obj or obj in ("No IP Record", "No IP Record\n"):
            return []
        if isinstance(obj, list):
            return [str(item) for item in obj]
        return [line.strip() for line in str(obj).splitlines() if line.strip()]

    async def clear_client_ips(self, email: str) -> None:
        await self._request("POST", f"/panel/api/inbounds/clearClientIps/{email}")

    async def find_client(self, inbound_id: int, uuid: str) -> dict[str, Any] | None:
        inbound = await self.get_inbound(inbound_id)
        for client in inbound.clients:
            if client.get("id") == uuid:
                return client
        return None
