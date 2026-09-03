# -*- coding: utf-8 -*-
"""独立座舱模拟器 HTTP 客户端。执行状态由模拟器回执决定，客户端不得伪造成功。"""
import os
import time
from typing import Dict, Any

import requests
from components.config import SETTINGS


TOOL_ENDPOINTS = {
    "set_climate": "/v1/cabin/climate",
    "set_seat": "/v1/cabin/seat",
    "play_media": "/v1/cabin/media",
    "set_ambient": "/v1/cabin/ambient",
    "plan_route": "/v1/navigation/route",
    "contact_vehicle": "/v1/vehicle/contact",
}


class VehicleGateway:
    def __init__(self, base_url: str = None, token: str = None):
        configured_url = os.environ.get("DRIVEMATE_SIMULATOR_URL", SETTINGS.simulator_url)
        configured_token = os.environ.get("DRIVEMATE_SIMULATOR_TOKEN", SETTINGS.simulator_token)
        self.base_url = (base_url or configured_url).rstrip("/")
        self.token = token if token is not None else configured_token

    def _headers(self):
        return {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}

    def execute(self, tool: str, arguments: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
        endpoint = TOOL_ENDPOINTS.get(tool)
        if not endpoint:
            return {"success": False, "status": "unsupported", "summary": "工具未接入座舱执行网关。", "backend": "none"}
        if not self.token:
            return {"success": False, "status": "auth_missing", "summary": "未配置座舱模拟器访问令牌，拒绝执行。", "backend": "simulator_http"}
        payload = {"arguments": arguments or {}, "context": context or {}}
        t0 = time.perf_counter()
        try:
            r = requests.post(self.base_url + endpoint, json=payload, headers=self._headers(), timeout=3)
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
        except requests.RequestException as e:
            return {"success": False, "status": "backend_unreachable", "summary": "座舱模拟器不可达：%s" % e,
                    "backend": "simulator_http", "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
        try:
            data = r.json()
        except ValueError:
            data = {"success": False, "summary": r.text[:200]}
        data.setdefault("success", r.ok)
        data.setdefault("status", "executed" if r.ok else "failed")
        data.setdefault("backend", "simulator_http")
        data["latency_ms"] = elapsed
        if r.status_code == 401:
            data["status"] = "unauthorized"
            data["success"] = False
        return data

    def health(self) -> Dict[str, Any]:
        if not self.token:
            return {"ok": False, "reason": "token_missing", "summary": "未配置 DRIVEMATE_SIMULATOR_TOKEN"}
        try:
            r = requests.get(self.base_url + "/health", headers=self._headers(), timeout=1.5)
            try:
                data = r.json() if r.content else {}
            except ValueError:
                data = {}
            if r.status_code in (401, 403):
                return {
                    "ok": False,
                    "reason": "unauthorized",
                    "status_code": r.status_code,
                    "summary": "Bearer Token 与座舱模拟器不一致",
                    "data": data,
                }
            if not r.ok:
                return {
                    "ok": False,
                    "reason": "http_error",
                    "status_code": r.status_code,
                    "summary": f"座舱模拟器健康检查返回 HTTP {r.status_code}",
                    "data": data,
                }
            authenticated = data.get("authenticated") is True
            return {
                "ok": authenticated,
                "reason": "authenticated" if authenticated else "auth_not_confirmed",
                "status_code": r.status_code,
                "summary": "已鉴权连接" if authenticated else "健康检查未确认 authenticated=true",
                "data": data,
            }
        except requests.RequestException as e:
            return {"ok": False, "reason": "unreachable", "summary": str(e)}

    def state(self) -> Dict[str, Any]:
        if not self.token:
            return {"success": False, "summary": "token_missing"}
        try:
            r = requests.get(self.base_url + "/v1/state", headers=self._headers(), timeout=2)
        except requests.RequestException as e:
            return {"success": False, "status": "backend_unreachable", "summary": str(e)}
        try:
            data = r.json()
        except ValueError:
            return {
                "success": False,
                "status": "invalid_response",
                "summary": "座舱模拟器返回了非 JSON 内容",
            }
        if not r.ok:
            data["success"] = False
            data.setdefault("status", "unauthorized" if r.status_code in (401, 403) else "failed")
            data.setdefault("summary", "座舱模拟器状态接口返回 HTTP %s" % r.status_code)
        return data
