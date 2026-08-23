from __future__ import annotations

from urllib.parse import quote, urlencode

from app.services.xui.exceptions import InboundConfigError
from app.services.xui.models import Inbound


def build_vless_reality_link(
    *,
    inbound: Inbound,
    uuid: str,
    host: str,
    label: str,
    flow: str | None = None,
) -> str:
    """
    Собирает vless://-ссылку для inbound'а с security=reality.

    host всегда берётся из конфига сервера: в inbound.listen может быть пусто или 0.0.0.0.
    """
    if not host:
        raise InboundConfigError("SERVER_HOST не задан: ссылку собрать невозможно")

    stream = inbound.stream
    if stream.security != "reality" or stream.reality is None:
        raise InboundConfigError(
            f"inbound {inbound.id}: ожидался security=reality, получено {stream.security!r}"
        )

    reality = stream.reality
    if not reality.public_key:
        raise InboundConfigError(f"inbound {inbound.id}: в realitySettings нет publicKey")

    params: dict[str, str] = {
        "type": stream.network or "tcp",
        "security": "reality",
        "pbk": reality.public_key,
        "fp": reality.fingerprint or "chrome",
    }
    if reality.server_names:
        params["sni"] = reality.server_names[0]
    if reality.short_ids:
        params["sid"] = reality.short_ids[0]
    params["spx"] = reality.spider_x or "/"

    effective_flow = flow if flow is not None else inbound.default_flow
    if effective_flow:
        params["flow"] = effective_flow

    if stream.network == "tcp" and stream.header_type:
        params["headerType"] = stream.header_type
    if stream.network == "ws" and stream.path:
        params["path"] = stream.path
    if stream.network == "grpc" and stream.service_name:
        params["serviceName"] = stream.service_name

    query = urlencode(params, quote_via=quote, safe="")
    fragment = quote(label, safe="")
    return f"vless://{uuid}@{host}:{inbound.port}?{query}#{fragment}"


def build_subscription_url(sub_url: str | None, sub_id: str) -> str | None:
    if not sub_url or not sub_id:
        return None
    return f"{sub_url.rstrip('/')}/{sub_id}"


def build_label(brand: str, country_flag: str, country_name: str) -> str:
    country = f"{country_flag} {country_name}".strip()
    return f"{brand} | {country}".strip(" |")
