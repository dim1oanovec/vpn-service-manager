from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class XuiResponse(BaseModel):
    """Общая обёртка ответов 3x-ui."""

    success: bool = False
    msg: str = ""
    obj: Any = None


class XuiClient(BaseModel):
    """Клиент inbound'а в терминах панели 3x-ui."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    flow: str = ""
    email: str
    limit_ip: int = Field(default=0, alias="limitIp")
    total_gb: int = Field(default=0, alias="totalGB")
    expiry_time: int = Field(default=0, alias="expiryTime")
    enable: bool = True
    tg_id: str = Field(default="", alias="tgId")
    sub_id: str = Field(default="", alias="subId")
    comment: str = ""
    reset: int = 0

    def to_panel(self) -> dict[str, Any]:
        """Панель ждёт camelCase ключи ровно в этом наборе."""
        return {
            "id": self.id,
            "flow": self.flow,
            "email": self.email,
            "limitIp": self.limit_ip,
            "totalGB": self.total_gb,
            "expiryTime": self.expiry_time,
            "enable": self.enable,
            "tgId": self.tg_id,
            "subId": self.sub_id,
            "comment": self.comment,
            "reset": self.reset,
        }

    def settings_payload(self) -> str:
        """`settings` в addClient/updateClient — это JSON-строка."""
        return json.dumps({"clients": [self.to_panel()]}, ensure_ascii=False)


class ClientTraffic(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: int | None = None
    inbound_id: int | None = Field(default=None, alias="inboundId")
    enable: bool = True
    email: str = ""
    up: int = 0
    down: int = 0
    expiry_time: int = Field(default=0, alias="expiryTime")
    total: int = 0

    @property
    def used_bytes(self) -> int:
        return int(self.up or 0) + int(self.down or 0)


class RealitySettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    public_key: str = ""
    fingerprint: str = "chrome"
    server_names: list[str] = Field(default_factory=list)
    short_ids: list[str] = Field(default_factory=list)
    spider_x: str = "/"


class StreamSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    network: str = "tcp"
    security: str = "none"
    reality: RealitySettings | None = None
    header_type: str | None = None
    path: str | None = None
    host: str | None = None
    service_name: str | None = None

    @classmethod
    def parse(cls, raw: str | dict[str, Any] | None) -> StreamSettings:
        data: dict[str, Any] = {}
        if isinstance(raw, str) and raw.strip():
            data = json.loads(raw)
        elif isinstance(raw, dict):
            data = raw

        reality_raw = data.get("realitySettings") or {}
        reality_inner = reality_raw.get("settings") or {}
        reality = None
        if reality_raw:
            reality = RealitySettings(
                public_key=reality_inner.get("publicKey", "")
                or reality_raw.get("publicKey", ""),
                fingerprint=reality_inner.get("fingerprint") or "chrome",
                server_names=list(reality_raw.get("serverNames") or []),
                short_ids=list(reality_raw.get("shortIds") or []),
                spider_x=reality_inner.get("spiderX") or reality_raw.get("spiderX") or "/",
            )

        tcp_settings = data.get("tcpSettings") or {}
        ws_settings = data.get("wsSettings") or {}
        grpc_settings = data.get("grpcSettings") or {}

        return cls(
            network=data.get("network", "tcp"),
            security=data.get("security", "none"),
            reality=reality,
            header_type=(tcp_settings.get("header") or {}).get("type"),
            path=ws_settings.get("path"),
            host=(ws_settings.get("headers") or {}).get("Host"),
            service_name=grpc_settings.get("serviceName"),
        )


class Inbound(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: int
    port: int
    protocol: str = "vless"
    remark: str = ""
    enable: bool = True
    listen: str = ""
    settings_raw: str = Field(default="", alias="settings")
    stream_settings_raw: str = Field(default="", alias="streamSettings")

    @field_validator("settings_raw", "stream_settings_raw", mode="before")
    @classmethod
    def _to_str(cls, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @property
    def stream(self) -> StreamSettings:
        return StreamSettings.parse(self.stream_settings_raw)

    @property
    def clients(self) -> list[XuiClient]:
        if not self.settings_raw:
            return []
        payload = json.loads(self.settings_raw)
        return [XuiClient.model_validate(item) for item in payload.get("clients", [])]

    @property
    def default_flow(self) -> str:
        """Flow берём из первого существующего клиента inbound'а."""
        for client in self.clients:
            if client.flow:
                return client.flow
        return "xtls-rprx-vision" if self.stream.security == "reality" else ""
