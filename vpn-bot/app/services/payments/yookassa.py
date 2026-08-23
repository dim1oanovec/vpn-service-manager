from __future__ import annotations

import ipaddress
import uuid as uuid_lib
from typing import Any

import httpx

from app.config import settings
from app.services.payments.base import PaymentError
from app.utils.logging import get_logger

log = get_logger(__name__)

API_URL = "https://api.yookassa.ru/v3/payments"

# Официальные сети, с которых ЮKassa отправляет уведомления
TRUSTED_NETWORKS = [
    ipaddress.ip_network("185.71.76.0/27"),
    ipaddress.ip_network("185.71.77.0/27"),
    ipaddress.ip_network("77.75.153.0/25"),
    ipaddress.ip_network("77.75.156.11/32"),
    ipaddress.ip_network("77.75.156.35/32"),
    ipaddress.ip_network("77.75.154.128/25"),
    ipaddress.ip_network("2a02:5180::/32"),
]


def is_trusted_ip(raw_ip: str | None) -> bool:
    if not raw_ip:
        return False
    try:
        address = ipaddress.ip_address(raw_ip.strip())
    except ValueError:
        return False
    return any(address in network for network in TRUSTED_NETWORKS)


class YooKassaClient:
    def __init__(self, shop_id: str, secret_key: str, timeout: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            auth=(shop_id, secret_key),
            timeout=httpx.Timeout(timeout),
            headers={"Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create_payment(
        self,
        *,
        amount_kopeks: int,
        description: str,
        internal_payment_id: int,
        return_url: str,
        receipt_email: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "amount": {"value": f"{amount_kopeks / 100:.2f}", "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description[:128],
            "metadata": {"payment_id": str(internal_payment_id)},
        }
        if receipt_email:
            body["receipt"] = {
                "customer": {"email": receipt_email},
                "items": [
                    {
                        "description": description[:128],
                        "quantity": "1.00",
                        "amount": {
                            "value": f"{amount_kopeks / 100:.2f}",
                            "currency": "RUB",
                        },
                        "vat_code": 1,
                    }
                ],
            }
        try:
            response = await self._client.post(
                API_URL,
                json=body,
                headers={"Idempotence-Key": str(uuid_lib.uuid4())},
            )
        except httpx.HTTPError as exc:
            raise PaymentError(f"ЮKassa недоступна: {exc}") from exc

        if response.status_code >= 400:
            log.error("yookassa create: HTTP %s %s", response.status_code, response.text[:300])
            raise PaymentError("ЮKassa отклонила создание платежа")
        return response.json()

    async def get_payment(self, external_id: str) -> dict[str, Any]:
        try:
            response = await self._client.get(f"{API_URL}/{external_id}")
        except httpx.HTTPError as exc:
            raise PaymentError(f"ЮKassa недоступна: {exc}") from exc
        if response.status_code >= 400:
            raise PaymentError(f"ЮKassa вернула HTTP {response.status_code}")
        return response.json()


_client: YooKassaClient | None = None


def get_client() -> YooKassaClient:
    global _client
    if not settings.yookassa_enabled:
        raise PaymentError("ЮKassa не настроена (нет SHOP_ID / SECRET_KEY)")
    if _client is None:
        _client = YooKassaClient(
            settings.yookassa_shop_id or "", settings.yookassa_secret_key or ""
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
