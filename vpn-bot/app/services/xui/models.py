from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class XuiResponse(BaseModel):
    """Единый конверт ответов 3x-ui: {"success": bool, "msg": str, "obj": ...}."""

    success: bool = False
    msg: str = ""
    obj: Any = None


class XuiClient(BaseModel):
    """Клиент inbound'а в формате, который ждёт панель (camelCase-алиасы)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    email: str
    flow: str = ""
    limit_ip: int = Field(default=0, alias="limitIp")
    total_gb: int = Field(default=0, alias="totalGB")
    expiry_time: int = Field(default=0, alias="expiryTime")
    enable: bool = True
    tg_id: str = Field(default="", alias="tgId")
    sub_id: str = Field(default="", alias="subId")
    comment: str = ""
    reset: int = 0

    def to_settings(self) -> str:
        """3x-ui принимает settings как JSON-строку {"clients":[{...}]}."""
        return json.dumps({"clients": [self.model_dump(by_alias=True)]}, ensure_ascii=False)


class ClientTraffic(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: int | None = None
    inbound_id: int | None = Field(default=None, alias="inboundId")
    enable: bool = True
    email: str = ""
    up: int = 0
    down: int = 0
    total: int = 0
    expiry_time: int = Field(default=0, alias="expiryTime")

    @property
    def used(self) -> int:
        return int(self.up or 0) + int(self.down or 0)


class RealitySettings(BaseModel):
    """Разобранный streamSettings.realitySettings inbound'а."""

    public_key: str = ""
    fingerprint: str = "chrome"
    server_name: str = ""
    short_id: str = ""
    spider_x: str = "/"


class Inbound(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: int
    port: int
    protocol: str = "vless"
    remark: str = ""
    enable: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    stream_settings: dict[str, Any] = Field(default_factory=dict, alias="streamSettings")
    sniffing: Any = None

    @field_validator("settings", "stream_settings", mode="before")
    @classmethod
    def _parse_json_string(cls, value: object) -> object:
        """Панель отдаёт settings/streamSettings строками с JSON внутри."""
        if isinstance(value, str):
            if not value.strip():
                return {}
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return value or {}

    @property
    def network(self) -> str:
        return str(self.stream_settings.get("network") or "tcp")

    @property
    def security(self) -> str:
        return str(self.stream_settings.get("security") or "none")

    @property
    def clients(self) -> list[dict[str, Any]]:
        return list(self.settings.get("clients") or [])

    @property
    def default_flow(self) -> str:
        for client in self.clients:
            flow = client.get("flow")
            if flow:
                return str(flow)
        return "xtls-rprx-vision" if self.security == "reality" else ""

    def reality(self) -> RealitySettings:
        raw = self.stream_settings.get("realitySettings") or {}
        inner = raw.get("settings") or {}
        server_names = raw.get("serverNames") or []
        short_ids = raw.get("shortIds") or []
        return RealitySettings(
            public_key=str(inner.get("publicKey") or ""),
            fingerprint=str(inner.get("fingerprint") or "chrome"),
            server_name=str(server_names[0] if server_names else raw.get("dest", "")).split(":")[0],
            short_id=str(short_ids[0] if short_ids else ""),
            spider_x=str(inner.get("spiderX") or "/"),
        )
