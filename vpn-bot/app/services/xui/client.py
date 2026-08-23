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

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def with_relogin(
    func: Callable[..., Awaitable[R]],
) -> Callable[..., Awaitable[R]]:
    """При 401/редиректе на /login — один релогин и один повтор запроса."""

    @functools.wraps(func)
    async def wrapper(self: XuiPanelClient, *args: Any, **kwargs: Any) -> R:
        try:
            return await func(self, *args, **kwargs)
        except XuiAuthError:
            log.info("3x-ui сессия истекла (%s), релогин", self.safe_base_url)
            self._authorized = False
            await self.login(force=True)
            return await func(self, *args, **kwargs)

    return wrapper


class XuiPanelClient:
    """
    Асинхронный клиент 3x-ui с cookie-сессией.

    base_url задаётся полностью, включая кастомный webBasePath:
    https://panel.example.com:2053/MySecretPath
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = 15.0,
        verify_ssl: bool = False,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._max_retries = max_retries
        self._authorized = False
        self._login_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            verify=verify_ssl,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )

    # ---------- служебное ----------

    @property
    def safe_base_url(self) -> str:
        """URL без webBasePath — безопасно писать в логи."""
        parsed = httpx.URL(self.base_url)
        return f"{parsed.scheme}://{parsed.host}:{parsed.port or ''}".rstrip(":")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> XuiPanelClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def _is_auth_failure(self, response: httpx.Response) -> bool:
        if response.status_code in (401, 403):
            return True
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            return "login" in location.lower()
        if response.status_code == 200 and "text/html" in response.headers.get(
            "content-type", ""
        ):
            # Панель отдала страницу логина вместо JSON
            return "login" in response.text[:2000].lower()
        return False

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        require_auth: bool = True,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._client.request(method, path, data=data)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt == self._max_retries:
                    break
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                continue

            if response.status_code in _RETRY_STATUSES and attempt < self._max_retries:
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                continue

            if require_auth and self._is_auth_failure(response):
                raise XuiAuthError(f"{path}: требуется авторизация")

            return response

        raise XuiTransportError(
            f"{self.safe_base_url}{path}: сеть недоступна ({last_error})"
        ) from last_error

    async def _api(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> XuiResponse:
        response = await self._raw_request(method, path, data=data)
        if response.status_code >= 400:
            raise XuiTransportError(f"{path}: HTTP {response.status_code}")
        try:
            payload = XuiResponse.model_validate(response.json())
        except ValueError as exc:
            raise XuiTransportError(f"{path}: ответ не JSON") from exc
        if not payload.success:
            message = payload.msg or "неизвестная ошибка панели"
            if "not found" in message.lower() or "не найден" in message.lower():
                raise XuiClientNotFound(f"{path}: {message}")
            raise XuiApiError(message, endpoint=path)
        return payload

    # ---------- авторизация ----------

    async def login(self, force: bool = False) -> None:
        async with self._login_lock:
            if self._authorized and not force:
                return
            response = await self._raw_request(
                "POST",
                "/login",
                data={"username": self._username, "password": self._password},
                require_auth=False,
            )
            if response.status_code >= 400:
                raise XuiAuthError(f"login: HTTP {response.status_code}")
            try:
                payload = XuiResponse.model_validate(response.json())
            except ValueError as exc:
                raise XuiAuthError("login: панель ответила не JSON") from exc
            if not payload.success:
                raise XuiAuthError(f"login: {payload.msg or 'неверные креды'}")
            if not self._client.cookies:
                raise XuiAuthError("login: панель не выдала cookie сессии")
            self._authorized = True
            log.info("3x-ui авторизация успешна: %s", self.safe_base_url)

    async def ensure_auth(self) -> None:
        if not self._authorized:
            await self.login()

    # ---------- inbounds ----------

    @with_relogin
    async def list_inbounds(self) -> list[Inbound]:
        await self.ensure_auth()
        payload = await self._api("GET", "/panel/api/inbounds/list")
        items = payload.obj or []
        return [Inbound.model_validate(item) for item in items]

    @with_relogin
    async def get_inbound(self, inbound_id: int) -> Inbound:
        await self.ensure_auth()
        payload = await self._api("GET", f"/panel/api/inbounds/get/{inbound_id}")
        if not payload.obj:
            raise XuiApiError(f"inbound {inbound_id} не найден", endpoint="get_inbound")
        return Inbound.model_validate(payload.obj)

    # ---------- клиенты ----------

    @with_relogin
    async def add_client(self, inbound_id: int, client: XuiClient) -> None:
        await self.ensure_auth()
        await self._api(
            "POST",
            "/panel/api/inbounds/addClient",
            data={"id": inbound_id, "settings": client.settings_payload()},
        )

    @with_relogin
    async def update_client(self, uuid: str, inbound_id: int, client: XuiClient) -> None:
        await self.ensure_auth()
        await self._api(
            "POST",
            f"/panel/api/inbounds/updateClient/{uuid}",
            data={"id": inbound_id, "settings": client.settings_payload()},
        )

    @with_relogin
    async def delete_client(self, inbound_id: int, uuid: str) -> None:
        await self.ensure_auth()
        await self._api("POST", f"/panel/api/inbounds/{inbound_id}/delClient/{uuid}")

    @with_relogin
    async def get_client_traffic(self, email: str) -> ClientTraffic | None:
        await self.ensure_auth()
        try:
            payload = await self._api(
                "GET", f"/panel/api/inbounds/getClientTraffics/{email}"
            )
        except XuiClientNotFound:
            return None
        if not payload.obj:
            return None
        obj = payload.obj[0] if isinstance(payload.obj, list) else payload.obj
        return ClientTraffic.model_validate(obj)

    @with_relogin
    async def reset_client_traffic(self, inbound_id: int, email: str) -> None:
        await self.ensure_auth()
        await self._api(
            "POST", f"/panel/api/inbounds/resetClientTraffic/{inbound_id}/{email}"
        )

    @with_relogin
    async def client_ips(self, email: str) -> list[str]:
        await self.ensure_auth()
        payload = await self._api("POST", f"/panel/api/inbounds/clientIps/{email}")
        obj = payload.obj
        if not obj or obj in ("No IP Record", "No IP Record\n"):
            return []
        if isinstance(obj, list):
            return [str(item) for item in obj]
        if isinstance(obj, str):
            return [line.strip() for line in obj.replace(",", "\n").splitlines() if line.strip()]
        return []

    @with_relogin
    async def clear_client_ips(self, email: str) -> None:
        await self.ensure_auth()
        await self._api("POST", f"/panel/api/inbounds/clearClientIps/{email}")

    async def client_exists(self, inbound_id: int, email: str) -> bool:
        inbound = await self.get_inbound(inbound_id)
        return any(client.email == email for client in inbound.clients)

    async def find_client(self, inbound_id: int, email: str) -> XuiClient | None:
        inbound = await self.get_inbound(inbound_id)
        for client in inbound.clients:
            if client.email == email:
                return client
        return None

    async def ping(self) -> bool:
        try:
            await self.list_inbounds()
        except Exception as exc:  # noqa: BLE001 - пинг не должен ломать админку
            log.warning("Пинг панели %s не прошёл: %s", self.safe_base_url, exc)
            return False
        return True
