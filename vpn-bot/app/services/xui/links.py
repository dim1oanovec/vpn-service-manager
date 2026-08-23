from __future__ import annotations

from urllib.parse import quote, urlencode

from app.services.xui.exceptions import XuiApiError
from app.services.xui.models import Inbound


def build_vless_reality_link(
    *,
    inbound: Inbound,
    uuid: str,
    host: str,
    label: str,
    flow: str | None = None,
) -> str:
    """Собирает vless://...&security=reality ссылку.

    host берём из настроек сервера, а НЕ из inbound: в панели там часто пусто/0.0.0.0.
    """
    if not host:
        raise XuiApiError("не задан server_host — невозможно собрать ссылку")
    if inbound.security != "reality":
        raise XuiApiError(
            f"inbound {inbound.id}: security={inbound.security}, ожидался reality"
        )

    reality = inbound.reality()
    if not reality.public_key:
        raise XuiApiError(f"inbound {inbound.id}: в realitySettings нет publicKey")

    params: dict[str, str] = {
        "type": inbound.network,
        "security": "reality",
        "pbk": reality.public_key,
        "fp": reality.fingerprint or "chrome",
        "sni": reality.server_name,
        "sid": reality.short_id,
        "spx": reality.spider_x or "/",
    }
    resolved_flow = flow if flow is not None else inbound.default_flow
    if resolved_flow:
        params["flow"] = resolved_flow

    query = urlencode({k: v for k, v in params.items() if v}, quote_via=quote, safe="")
    fragment = quote(label, safe="")
    return f"vless://{uuid}@{host}:{inbound.port}?{query}#{fragment}"


def build_subscription_url(sub_url: str | None, sub_id: str) -> str | None:
    if not sub_url or not sub_id:
        return None
    return f"{sub_url.rstrip('/')}/{sub_id}"


def connection_label(brand: str, country_flag: str, country_name: str) -> str:
    parts = [part for part in (country_flag, country_name) if part]
    return f"{brand} | {' '.join(parts)}".strip()
