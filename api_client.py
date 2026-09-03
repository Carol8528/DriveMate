from __future__ import annotations

import copy
import os
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol
from urllib.parse import quote, urlparse

import requests

from perception_fusion import fuse_perception, summarize_action_outcome


JsonObject = Dict[str, Any]
RUN_RESULT_FIELDS = (
    "run_id",
    "intent",
    "reply",
    "risk_level",
    "plan_summary",
    "steps",
    "safety_tip",
    "calls",
    "pending_tools",
    "perception_fusion",
    "action_outcome",
)


class BackendApiError(RuntimeError):
    """Raised when the frontend cannot use a backend response safely."""


class BackendClient(Protocol):
    def health(self) -> JsonObject: ...

    def meta(self) -> JsonObject: ...

    def run_agent(
        self,
        message: str,
        mode: str,
        engine: str,
        snapshot: JsonObject,
        session_id: Optional[str] = None,
    ) -> JsonObject: ...

    def confirm_run(self, run_id: str, snapshot: JsonObject) -> JsonObject: ...

    def cancel_run(self, run_id: str) -> JsonObject: ...

    def simulator_state(self) -> JsonObject: ...

    def audit_run(self, run_id: str) -> JsonObject: ...


def _require_object(value: Any, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise BackendApiError(f"{label} must be a JSON object.")
    return value


def validate_run_result(value: Any) -> JsonObject:
    result = _require_object(value, "Run response")
    missing = [field for field in RUN_RESULT_FIELDS if field not in result]
    if missing:
        raise BackendApiError(
            "Run response is missing required fields: " + ", ".join(missing)
        )
    if result["risk_level"] not in {"L0", "L1", "L2", "L3"}:
        raise BackendApiError("Run response has an invalid risk_level.")
    for field in ("steps", "calls", "pending_tools"):
        if not isinstance(result[field], list):
            raise BackendApiError(f"Run response field '{field}' must be an array.")
    for field in ("perception_fusion", "action_outcome"):
        if not isinstance(result[field], dict):
            raise BackendApiError(f"Run response field '{field}' must be an object.")
    modalities = result["perception_fusion"].get("modalities")
    if not isinstance(modalities, list):
        raise BackendApiError(
            "Run response field 'perception_fusion.modalities' must be an array."
        )
    return result


@dataclass(frozen=True)
class HttpBackendClient:
    base_url: str
    api_token: str
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BackendApiError(
                "DRIVEMATE_BACKEND_URL must be an absolute http:// or https:// URL."
            )
        if not self.api_token:
            raise BackendApiError(
                "DRIVEMATE_API_TOKEN is required when DRIVEMATE_API_MODE=http."
            )
        if self.timeout_seconds <= 0:
            raise BackendApiError(
                "DRIVEMATE_API_TIMEOUT_SECONDS must be greater than 0."
            )

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[JsonObject] = None,
    ) -> JsonObject:
        url = self.base_url.rstrip("/") + path
        try:
            response = requests.request(
                method,
                url,
                json=payload,
                timeout=self.timeout_seconds,
                headers={
                    "Accept": "application/json",
                    "Authorization": "Bearer " + self.api_token,
                },
            )
        except requests.RequestException as exc:
            raise BackendApiError(f"Backend request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text.strip()[:500] or "empty response"
            raise BackendApiError(
                f"Backend returned HTTP {response.status_code} for {path}: {detail}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise BackendApiError(
                f"Backend returned non-JSON content for {path}."
            ) from exc
        return _require_object(data, f"Response from {path}")

    def health(self) -> JsonObject:
        return self._request("GET", "/health")

    def meta(self) -> JsonObject:
        return self._request("GET", "/api/v1/meta")

    def run_agent(
        self,
        message: str,
        mode: str,
        engine: str,
        snapshot: JsonObject,
        session_id: Optional[str] = None,
    ) -> JsonObject:
        payload = {
            "message": message,
            "mode": mode,
            "engine": engine,
            "snapshot": snapshot,
        }
        if session_id:
            payload["session_id"] = session_id
        result = self._request(
            "POST",
            "/api/v1/agent/runs",
            payload,
        )
        return validate_run_result(result)

    def confirm_run(self, run_id: str, snapshot: JsonObject) -> JsonObject:
        result = self._request(
            "POST",
            f"/api/v1/agent/runs/{quote(run_id, safe='')}/confirm",
            {"snapshot": snapshot},
        )
        return validate_run_result(result)

    def cancel_run(self, run_id: str) -> JsonObject:
        result = self._request(
            "POST",
            f"/api/v1/agent/runs/{quote(run_id, safe='')}/cancel",
        )
        return validate_run_result(result)

    def simulator_state(self) -> JsonObject:
        return self._request("GET", "/api/v1/simulator/state")

    def audit_run(self, run_id: str) -> JsonObject:
        return self._request(
            "GET",
            f"/api/v1/audit/runs/{quote(run_id, safe='')}",
        )


class MockBackendClient:
    """Frontend-only preview data. It never performs a real vehicle action."""

    def __init__(self) -> None:
        self._runs: Dict[str, JsonObject] = {}
        self._lock = threading.Lock()

    def health(self) -> JsonObject:
        return {
            "ok": True,
            "service": "drivemate-frontend-mock",
            "authenticated": True,
            "mode": "mock",
        }

    def meta(self) -> JsonObject:
        return {
            "api_version": "v1",
            "backend": "frontend_mock",
            "tool_count": 21,
            "engines": ["融合编排引擎（本地可审计）"],
            "validation": {
                "task_success_rate_percent": 100,
                "average_latency_ms": 4.98,
                "p95_latency_ms": 8.14,
            },
        }

    def run_agent(
        self,
        message: str,
        mode: str,
        engine: str,
        snapshot: JsonObject,
        session_id: Optional[str] = None,
    ) -> JsonObject:
        run_id = "MOCK-" + uuid.uuid4().hex[:12]
        session_id = session_id or ("S-MOCK-" + uuid.uuid4().hex[:10])
        route_destination = str(
            snapshot.get("order_state", {}).get("destination") or "上海外滩"
        )
        if mode == "Robotaxi 乘客":
            intent = "find_car"
            reply = "已定位车辆并生成找车指引；闪灯鸣笛需要确认后执行。"
            steps = [
                self._step(1, "读取订单状态", "get_order_status", "done", "L0"),
                self._step(
                    2, "共享车辆位置", "share_vehicle_location", "done", "L0"
                ),
                self._step(
                    3,
                    "车辆闪灯鸣笛",
                    "contact_vehicle",
                    "pending_confirm",
                    "L2",
                    "等待用户确认",
                ),
            ]
            calls = [
                self._call("get_order_status", "L0", {"status": "arriving"}),
                self._call(
                    "share_vehicle_location",
                    "L0",
                    {"location": "延安路与平海路交叉口"},
                ),
            ]
            pending = [
                {
                    "step_id": "contact_vehicle",
                    "name": "contact_vehicle",
                    "arguments": {"action": "both", "duration_seconds": 3},
                }
            ]
            risk = "L2"
            summary = "核验订单与车辆位置，确认后执行近距离找车动作"
            safety_tip = "请确认您位于车辆附近，并在安全位置观察车辆提示。"
        else:
            intent = "fatigue"
            reply = (
                "您的疲劳度已接近安全红线，请务必把安全放在第一位！"
                "我已帮您：空调降至 21.0℃、风量加大、座椅靠背调至 105°，"
                "建议前往「黄村服务区」休息（12km）。\n\n"
                "为什么这么安排：疲劳驾驶是高速事故的主要原因之一，"
                "短暂休息比硬撑更安全。我会持续监测您的状态。\n\n"
                "【可解释干预】当前事故风险 3.7%，已执行安全干预后降至 "
                "2.6%（-31.03%）。"
            )
            steps = [
                self._step(1, "读取疲劳状态", "get_fatigue_status", "done", "L0"),
                self._step(2, "调节座舱温度", "set_climate", "done", "L1"),
                self._step(3, "调整主驾座椅", "set_seat", "done", "L1"),
                self._step(4, "播放提神歌单", "play_media", "done", "L1"),
                self._step(
                    5,
                    "导航至黄村服务区",
                    "plan_route",
                    "pending_confirm",
                    "L2",
                    "等待用户确认",
                ),
            ]
            calls = [
                self._call("get_fatigue_status", "L0", {"fatigue_index": 0.72}),
                self._call(
                    "set_climate", "L1", {"temperature": 21.0, "fan_level": 4}
                ),
                self._call("set_seat", "L1", {"backrest_angle": 105}),
                self._call("play_media", "L1", {"source": "提神歌单"}),
            ]
            pending = [
                {
                    "step_id": "plan_route",
                    "name": "plan_route",
                    "arguments": {"destination": "黄村服务区", "distance_km": 12},
                }
            ]
            risk = "L3"
            summary = "先执行座舱安全干预，再由用户确认是否导航至黄村服务区"
            safety_tip = "请务必把安全放在第一位！"

        if mode == "Robotaxi 乘客":
            if "规划前往" in message or "规划路线" in message:
                intent = "route_plan"
                reply = f"已生成前往{route_destination}的路线预览，确认后更新本次行程。"
                steps = [
                    self._step(1, "读取实时路况", "get_traffic", "done", "L0"),
                    self._step(
                        2,
                        f"更新目的地至{route_destination}",
                        "update_trip",
                        "pending_confirm",
                        "L2",
                        "行程变更可能影响费用与到达时间",
                    ),
                ]
                calls = [self._call("get_traffic", "L0", {"status": "clear"})]
                pending = [
                    {
                        "step_id": "update_trip",
                        "name": "update_trip",
                        "arguments": {"field": "目的地", "value": route_destination},
                    }
                ]
                risk = "L2"
                summary = f"规划前往{route_destination}的路线并等待行程变更确认"
                safety_tip = "行程变更可能影响费用和预计到达时间，请确认后继续。"
            elif "人工" in message:
                intent = "human_support"
                reply = "已为当前订单发起人工客服连接。"
                steps = [
                    self._step(1, "核验当前订单", "get_order_status", "done", "L0"),
                    self._step(2, "连接人工客服", "contact_support", "done", "L0"),
                ]
                calls = [
                    self._call("get_order_status", "L0", {"status": "in_trip"}),
                    self._call("contact_support", "L0", {"channel": "in_app"}),
                ]
                pending, risk = [], "L0"
                summary = "核验当前订单后连接人工客服"
                safety_tip = "无"
            elif "上车点" in message or "目的地" in message:
                target = "上车点" if "上车点" in message else "目的地"
                intent = "modify_trip"
                reply = f"已核验当前订单；修改{target}会影响行程，等待你确认后提交。"
                steps = [
                    self._step(1, "核验当前订单", "get_order_status", "done", "L0"),
                    self._step(
                        2,
                        f"修改{target}",
                        "update_trip",
                        "pending_confirm",
                        "L2",
                        "行程变更可能影响费用与到达时间",
                    ),
                ]
                calls = [self._call("get_order_status", "L0", {"status": "in_trip"})]
                pending = [
                    {
                        "step_id": "update_trip",
                        "name": "update_trip",
                        "arguments": {"field": target, "value": "等待用户补充或确认"},
                    }
                ]
                risk = "L2"
                summary = f"核验订单并在确认后修改{target}"
                safety_tip = "行程变更可能影响费用和预计到达时间，请确认后继续。"
            elif "不舒服" in message:
                intent = "passenger_comfort"
                reply = "已降低座舱温度并为你保留人工求助入口。"
                steps = [
                    self._step(1, "读取座舱状态", "get_climate", "done", "L0"),
                    self._step(2, "调节座舱温度", "set_climate", "done", "L1"),
                ]
                calls = [
                    self._call("get_climate", "L0", {"temperature": 26}),
                    self._call("set_climate", "L1", {"temperature": 23}),
                ]
                pending, risk = [], "L1"
                summary = "读取并调节座舱温度，保留人工求助"
                safety_tip = "如果身体持续不适，请立即联系人工客服或紧急服务。"
        else:
            if "规划前往" in message or "规划路线" in message:
                intent = "route_plan"
                reply = f"已生成前往{route_destination}的导航预览，确认后开始导航。"
                steps = [
                    self._step(1, "读取实时路况", "get_traffic", "done", "L0"),
                    self._step(
                        2,
                        f"导航至{route_destination}",
                        "plan_route",
                        "pending_confirm",
                        "L2",
                        "导航目标变更等待用户确认",
                    ),
                ]
                calls = [self._call("get_traffic", "L0", {"status": "clear"})]
                pending = [
                    {
                        "step_id": "plan_route",
                        "name": "plan_route",
                        "arguments": {"destination": route_destination},
                    }
                ]
                risk = "L2"
                summary = f"规划前往{route_destination}的路线并等待导航确认"
                safety_tip = "请在不影响驾驶的情况下确认导航变更。"
            elif "温度" in message or "热" in message:
                intent = "climate_comfort"
                reply = "已读取座舱环境，并将温度调节至 22°C。"
                steps = [
                    self._step(1, "读取座舱温度", "get_climate", "done", "L0"),
                    self._step(2, "调节座舱温度", "set_climate", "done", "L1"),
                ]
                calls = [
                    self._call("get_climate", "L0", {"temperature": 26}),
                    self._call("set_climate", "L1", {"temperature": 22}),
                ]
                pending, risk = [], "L1"
                summary = "读取座舱环境并完成舒适温度调节"
                safety_tip = "调节温度时请继续关注道路。"
            elif "补能" in message or "充电" in message:
                intent = "charging_plan"
                reply = "已读取电量并生成沿途补能方案；开始导航前需要你确认。"
                steps = [
                    self._step(1, "读取电量与续航", "get_vehicle_status", "done", "L0"),
                    self._step(
                        2,
                        "导航至推荐充电站",
                        "plan_route",
                        "pending_confirm",
                        "L2",
                        "导航目标变更等待用户确认",
                    ),
                ]
                calls = [
                    self._call(
                        "get_vehicle_status",
                        "L0",
                        {
                            "soc_percent": snapshot["vehicle_state"]["soc_percent"],
                            "range_km": snapshot["vehicle_state"]["range_km"],
                        },
                    )
                ]
                pending = [
                    {
                        "step_id": "plan_route",
                        "name": "plan_route",
                        "arguments": {"destination": "沿途推荐充电站"},
                    }
                ]
                risk = "L2"
                summary = "依据电量与续航生成补能方案，确认后开始导航"
                safety_tip = "请在不影响驾驶的情况下确认导航变更。"
            elif "孩子" in message:
                intent = "family_trip"
                reply = "已检查儿童座椅，并完成座舱温度与儿童音频设置。"
                steps = [
                    self._step(1, "检查儿童座椅", "get_vehicle_status", "done", "L0"),
                    self._step(2, "调节座舱温度", "set_climate", "done", "L1"),
                    self._step(3, "播放儿童音频", "play_media", "done", "L1"),
                ]
                calls = [
                    self._call(
                        "get_vehicle_status",
                        "L0",
                        {
                            "child_seat_detected": snapshot["vehicle_state"][
                                "child_seat_detected"
                            ]
                        },
                    ),
                    self._call("set_climate", "L1", {"temperature": 23}),
                    self._call("play_media", "L1", {"source": "儿童精选"}),
                ]
                pending, risk = [], "L1"
                summary = "检查儿童乘员状态并设置舒适座舱"
                safety_tip = "请确认儿童已正确使用安全座椅并系好安全带。"
            elif "车辆状态" in message or "行驶状态" in message:
                intent = "vehicle_status"
                reply = (
                    f"当前车速 {snapshot['vehicle_state']['speed_kmh']} km/h，"
                    f"剩余电量 {snapshot['vehicle_state']['soc_percent']}%，"
                    f"预估续航 {snapshot['vehicle_state']['range_km']} km。"
                )
                steps = [
                    self._step(1, "读取车辆状态", "get_vehicle_status", "done", "L0")
                ]
                calls = [
                    self._call(
                        "get_vehicle_status",
                        "L0",
                        copy.deepcopy(snapshot["vehicle_state"]),
                    )
                ]
                pending, risk = [], "L0"
                summary = "读取并汇总当前车辆关键状态"
                safety_tip = "无"

        perception_fusion = fuse_perception(snapshot, intent)

        if intent == "find_car":
            mock_state_diff = {
                "order.vehicle_location": {
                    "before": "未知",
                    "after": "延安路与平海路交叉口",
                }
            }
        elif intent == "route_plan":
            mock_state_diff = {
                "navigation.destination": {
                    "before": None,
                    "after": route_destination,
                }
            }
        elif intent in {"fatigue", "climate_comfort"}:
            mock_state_diff = {
                "climate.temperature": {"before": 26, "after": 22}
            }
            if intent == "fatigue":
                mock_state_diff["climate.temperature"]["after"] = 21.0
                mock_state_diff["climate.fan_level"] = {
                    "before": 2,
                    "after": 4,
                }
                mock_state_diff["seat.driver_backrest_angle"] = {
                    "before": 98,
                    "after": 105,
                }
                mock_state_diff["media.playing"] = {
                    "before": False,
                    "after": True,
                }
        elif intent == "passenger_comfort":
            mock_state_diff = {
                "climate.temperature": {"before": 26, "after": 23}
            }
        elif intent == "family_trip":
            mock_state_diff = {
                "climate.temperature": {"before": 26, "after": 23},
                "media.source": {"before": "无", "after": "儿童精选"},
            }
        else:
            mock_state_diff = {}
        has_pending = bool(pending)
        mock_phases = [
            {"name": "perceive", "status": "done", "duration_ms": 4},
            {"name": "understand", "status": "done", "duration_ms": 6},
            {"name": "adjudicate", "status": "done", "duration_ms": 3},
            {"name": "plan", "status": "done", "duration_ms": 5},
            {
                "name": "execute",
                "status": "waiting" if has_pending else "done",
            },
            {
                "name": "readback",
                "status": "done" if mock_state_diff else "pending",
            },
            {"name": "output", "status": "done", "duration_ms": 2},
        ]

        payload = {
            "run_id": run_id,
            "session_id": session_id,
            "intent": intent,
            "reply": reply,
            "risk_level": risk,
            "plan_summary": summary,
            "steps": steps,
            "safety_tip": safety_tip,
            "calls": calls,
            "pending_tools": pending,
            "perception_fusion": perception_fusion,
            "safety_score": {
                "L0": 94,
                "L1": 82,
                "L2": 62,
                "L3": 38,
            }[risk],
            "run_status": (
                "waiting_confirmation" if has_pending else "completed"
            ),
            "phases": mock_phases,
            "state_diff": mock_state_diff,
            "navigation": (
                {
                    "destination": route_destination,
                    "eta_minutes": 58 if "迪士尼" in route_destination else 42,
                    "distance_km": 46.3 if "迪士尼" in route_destination else 22.4,
                    "recommended_poi": "张江" if "迪士尼" in route_destination else "静安寺",
                    "route_summary": (
                        "虹桥枢纽 → 延安高架 → 中环路 → 张江 → 上海迪士尼度假区"
                        if "迪士尼" in route_destination
                        else f"虹桥枢纽 → 城市快速路 → {route_destination}"
                    ),
                }
                if intent == "route_plan"
                else {}
            ),
            "decision_ledger": {
                "source": "frontend_mock",
                "notice": "仅用于页面联调，不代表真实后端决策或执行结果。",
                "perception_fusion": perception_fusion,
            },
            "topology": [step["tool"] for step in steps],
        }
        payload["action_outcome"] = summarize_action_outcome(payload)
        result = validate_run_result(payload)
        with self._lock:
            self._runs[run_id] = {
                "request": {
                    "message": message,
                    "mode": mode,
                    "engine": engine,
                    "snapshot": copy.deepcopy(snapshot),
                },
                "result": copy.deepcopy(result),
                "events": [{"type": "run_created", "source": "frontend_mock"}],
            }
        return copy.deepcopy(result)

    def confirm_run(self, run_id: str, snapshot: JsonObject) -> JsonObject:
        with self._lock:
            run = self._get_run(run_id)
            result = copy.deepcopy(run["result"])
            for step in result["steps"]:
                if step.get("status") == "pending_confirm":
                    step["status"] = "done"
                    step["note"] = "用户已确认，Mock 预览标记为完成"
            for pending in result["pending_tools"]:
                result["calls"].append(
                    self._call(
                        pending.get("name", "unknown"),
                        "L2",
                        pending.get("arguments", {}),
                    )
                )
            result["pending_tools"] = []
            result["reply"] += " 已收到确认，页面已展示确认后的结果状态。"
            result["run_status"] = "completed"
            for phase in result.get("phases", []):
                if phase.get("name") in {"execute", "readback"}:
                    phase["status"] = "done"
            result["action_outcome"] = summarize_action_outcome(result)
            run["result"] = copy.deepcopy(result)
            run["request"]["snapshot"] = copy.deepcopy(snapshot)
            run["events"].append(
                {"type": "confirmation_recorded", "source": "frontend_mock"}
            )
            return copy.deepcopy(result)

    def cancel_run(self, run_id: str) -> JsonObject:
        with self._lock:
            run = self._get_run(run_id)
            result = copy.deepcopy(run["result"])
            for step in result["steps"]:
                if step.get("status") == "pending_confirm":
                    step["status"] = "cancelled"
                    step["note"] = "用户已取消"
            result["pending_tools"] = []
            result["reply"] += " 待确认操作已取消。"
            result["run_status"] = "cancelled"
            for phase in result.get("phases", []):
                if phase.get("name") == "execute":
                    phase["status"] = "cancelled"
            result["action_outcome"] = summarize_action_outcome(result)
            run["result"] = copy.deepcopy(result)
            run["events"].append(
                {"type": "run_cancelled", "source": "frontend_mock"}
            )
            return copy.deepcopy(result)

    def simulator_state(self) -> JsonObject:
        return {
            "success": True,
            "source": "frontend_mock",
            "notice": "此状态仅用于页面预览。",
            "state": {
                "climate": {"temperature": 22, "active": True},
                "media": {"source": "提神歌单", "playing": True},
            },
        }

    def audit_run(self, run_id: str) -> JsonObject:
        with self._lock:
            return copy.deepcopy(self._get_run(run_id))

    def _get_run(self, run_id: str) -> JsonObject:
        run = self._runs.get(run_id)
        if run is None:
            raise BackendApiError(f"Mock run not found: {run_id}")
        return run

    @staticmethod
    def _step(
        seq: int,
        title: str,
        tool: str,
        status: str,
        safety_level: str,
        note: str = "",
    ) -> JsonObject:
        strategies = {
            "get_fatigue_status": "先读取驾驶时长与疲劳证据，不直接控制车辆",
            "set_climate": "用低影响座舱调节缓解不适",
            "play_media": "通过非驾驶控制提供辅助提醒",
            "plan_route": "改变导航目标前保留用户确认",
            "get_order_status": "先核验有效订单，避免误操作其他车辆",
            "share_vehicle_location": "仅返回当前订单关联的车辆位置",
            "contact_vehicle": "近距离外部提示可能影响周边，需要明确确认",
        }
        return {
            "seq": seq,
            "title": title,
            "tool": tool,
            "status": status,
            "safety_level": safety_level,
            "note": note,
            "strategy": strategies.get(tool, "按当前上下文执行并保留结果证据"),
            "depends_on": [] if seq == 1 else [seq - 1],
        }

    @staticmethod
    def _call(tool: str, level: str, arguments: JsonObject) -> JsonObject:
        return {
            "tool": tool,
            "level": level,
            "result": "success",
            "backend": "frontend_mock",
            "receipt_id": "PREVIEW-" + uuid.uuid4().hex[:10],
            "summary": "Mock 预览数据，未执行真实后端动作",
            "latency_ms": 0,
            "arguments": arguments,
        }


def create_backend_client(
    api_mode: Optional[str] = None,
    base_url: Optional[str] = None,
    api_token: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
) -> BackendClient:
    mode = (
        api_mode or os.environ.get("DRIVEMATE_API_MODE", "http")
    ).strip().lower()
    if mode == "mock":
        return MockBackendClient()
    if mode != "http":
        raise BackendApiError(
            "DRIVEMATE_API_MODE must be either 'mock' or 'http'."
        )

    resolved_url = (
        base_url
        or os.environ.get("DRIVEMATE_BACKEND_URL", "http://127.0.0.1:8000")
    ).strip()
    if not resolved_url:
        raise BackendApiError(
            "DRIVEMATE_BACKEND_URL is required when DRIVEMATE_API_MODE=http."
        )
    resolved_token = (
        api_token or os.environ.get("DRIVEMATE_API_TOKEN", "")
    ).strip()
    if not resolved_token:
        raise BackendApiError(
            "DRIVEMATE_API_TOKEN is required when DRIVEMATE_API_MODE=http."
        )
    if timeout_seconds is None:
        raw_timeout = os.environ.get("DRIVEMATE_API_TIMEOUT_SECONDS", "60")
        try:
            timeout_seconds = float(raw_timeout)
        except ValueError as exc:
            raise BackendApiError(
                "DRIVEMATE_API_TIMEOUT_SECONDS must be a number."
            ) from exc
    return HttpBackendClient(resolved_url, resolved_token, timeout_seconds)
