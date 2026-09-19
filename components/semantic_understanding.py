# -*- coding: utf-8 -*-
"""语义理解层：外接 LLM 只做意图/槽位理解，不拥有任何工具执行权限。

设计原则：
1. 外接模型只接收最小必要上下文，不接收 tool schema；
2. 模型输出被当作不可信的概率性语义证据；
3. 本地 IntentGraph 的安全覆盖优先级更高；
4. 最终动作仍必须经过 ConstraintShield、DependencyPlanner、ConfirmationGrant、
   SafetyGuard / SchemaValidator 与 ToolExecutor。
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

import requests

from components.config import SETTINGS
from components.intent_graph import DEFINITIONS, SCENARIO_LABELS, resolve_intent


JsonObject = Dict[str, Any]

_SCENARIO_GUIDE = {
    "medical": "急性身体不适、急救、严重呼吸/胸部症状或失去意识风险",
    "fatigue": "驾驶疲劳、犯困、反应下降、需要安全休息",
    "parent_child": "儿童乘车、安全带、儿童座椅或驾驶员回头处理儿童",
    "charging": "充电、补能、续航、电量不足、充电站规划",
    "find_car": "Robotaxi 人车会合、找不到车辆、位置/车牌/闪灯鸣笛",
    "modify_pickup": "Robotaxi 上车点变更、临停接客、危险停车位置",
    "reroute": "Robotaxi 修改目的地、新增途经点、行程路线变更",
    "cancel_order": "取消 Robotaxi 订单或行程",
    "climate": "座舱空调、温度、风量调节",
    "commute": "自驾抵达、停车/离车前收尾服务",
    "route_plan": "自驾导航、前往某地点、路线规划",
    "vehicle_status": "查询车辆、电量、续航、车况",
    "human_support": "联系、转接人工客服",
    "trip_status": "查询 Robotaxi 订单、车辆位置、预计到达时间",
}


class SemanticUnderstandingError(RuntimeError):
    pass


def _json_from_text(content: str) -> JsonObject:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise SemanticUnderstandingError("External LLM did not return a JSON object.")
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SemanticUnderstandingError("External LLM returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise SemanticUnderstandingError("External LLM JSON must be an object.")
    return value


def _confidence_0_100(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if 0 <= number <= 1:
        number *= 100
    return max(0, min(100, round(number)))


def _clean_slots(value: Any) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    clean: JsonObject = {}
    for raw_key, raw_value in list(value.items())[:16]:
        key = str(raw_key).strip()[:48]
        if not key:
            continue
        if isinstance(raw_value, str):
            clean[key] = raw_value.strip()[:160]
        elif isinstance(raw_value, (int, float, bool)) or raw_value is None:
            clean[key] = raw_value
        elif isinstance(raw_value, list):
            clean[key] = [
                item.strip()[:120] if isinstance(item, str) else item
                for item in raw_value[:8]
                if isinstance(item, (str, int, float, bool)) or item is None
            ]
    return clean


def _semantic_snapshot(snapshot: JsonObject) -> JsonObject:
    """Only send state fields that can materially help semantic interpretation."""
    vehicle = snapshot.get("vehicle_state") if isinstance(snapshot, dict) else {}
    order = snapshot.get("order_state") if isinstance(snapshot, dict) else {}
    environment = snapshot.get("environment_state") if isinstance(snapshot, dict) else {}
    vehicle = vehicle if isinstance(vehicle, dict) else {}
    order = order if isinstance(order, dict) else {}
    environment = environment if isinstance(environment, dict) else {}
    return {
        "vehicle_state": {
            key: vehicle.get(key)
            for key in (
                "speed_kmh",
                "soc_percent",
                "range_km",
                "driving_hours",
                "child_seat_detected",
            )
            if key in vehicle
        },
        "order_state": {
            key: order.get(key)
            for key in ("status", "destination", "vehicle_location")
            if key in order
        },
        "environment_state": {
            key: environment.get(key)
            for key in ("time_of_day", "area_type", "parking_policy", "weather", "traffic")
            if key in environment
        },
    }


class ExternalSemanticClient:
    """OpenAI-compatible semantic classifier/slot filler with no tool interface."""

    def __init__(self, *, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 model: Optional[str] = None, timeout_seconds: Optional[int] = None) -> None:
        self.api_key = (api_key if api_key is not None else SETTINGS.llm_api_key).strip()
        self.base_url = (base_url if base_url is not None else SETTINGS.llm_base_url).rstrip("/")
        self.model = (model if model is not None else SETTINGS.llm_model).strip()
        self.timeout_seconds = timeout_seconds or SETTINGS.llm_timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def understand(self, message: str, *, mode: str, snapshot: JsonObject,
                   history: Optional[List[JsonObject]] = None) -> JsonObject:
        if not self.enabled:
            raise SemanticUnderstandingError("API_KEY is not configured.")

        catalog = {
            scenario_id: {
                "label": SCENARIO_LABELS[scenario_id],
                "description": _SCENARIO_GUIDE.get(scenario_id, ""),
                "native_mode": DEFINITIONS.get(scenario_id, {}).get("mode"),
            }
            for scenario_id in SCENARIO_LABELS
        }
        recent_history = []
        for item in (history or [])[-4:]:
            if not isinstance(item, dict):
                continue
            recent_history.append(
                {
                    "user": str(item.get("user") or "")[:300],
                    "assistant": str(item.get("assistant") or "")[:300],
                }
            )

        system_prompt = (
            "你是 DriveMate 的语义理解模块，只负责自然语言意图分类和槽位抽取。"
            "你没有、也不得假设任何工具调用或执行权限；不要规划动作，不要声称已经执行任何操作。"
            "只输出一个 JSON 对象，不要 Markdown。intent 必须是给定 catalog 中的键或 null。"
            "对否定、转折、多意图和指代要谨慎；信息不足时 needs_clarification=true。"
            "slots 只抽取用户明确表达或可由上下文直接消解的参数，例如 destination、temperature_c。"
        )
        user_payload = {
            "mode": mode,
            "message": message,
            "recent_history": recent_history,
            "state_context": _semantic_snapshot(snapshot),
            "catalog": catalog,
            "output_schema": {
                "intent": "catalog key or null",
                "confidence": "0..1 or 0..100",
                "needs_clarification": "boolean",
                "reason": "short semantic reason, no execution claim",
                "slots": "object",
                "alternatives": ["catalog key"],
                "negated_intents": ["catalog key"],
            },
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_tokens": 600,
        }
        response = requests.post(
            self.base_url + "/chat/completions",
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise SemanticUnderstandingError(
                f"External LLM returned HTTP {response.status_code}: {response.text[:240]}"
            )
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise SemanticUnderstandingError("External LLM response shape is invalid.") from exc
        if isinstance(content, list):
            content = "".join(
                str(item.get("text") or "") if isinstance(item, dict) else str(item)
                for item in content
            )
        data = _json_from_text(str(content))

        intent = str(data.get("intent") or "").strip() or None
        if intent not in SCENARIO_LABELS:
            intent = None
        alternatives = []
        for item in data.get("alternatives") or []:
            value = str(item).strip()
            if value in SCENARIO_LABELS and value not in alternatives:
                alternatives.append(value)
        negated = []
        for item in data.get("negated_intents") or []:
            value = str(item).strip()
            if value in SCENARIO_LABELS and value not in negated:
                negated.append(value)
        return {
            "intent": intent,
            "confidence": _confidence_0_100(data.get("confidence")),
            "needs_clarification": bool(data.get("needs_clarification")) or intent is None,
            "reason": str(data.get("reason") or "").strip()[:240],
            "slots": _clean_slots(data.get("slots")),
            "alternatives": alternatives[:3],
            "negated_intents": negated[:5],
            "provider": "openai_compatible",
            "model": self.model,
        }


def _external_alternatives(external: JsonObject) -> List[JsonObject]:
    output = []
    seen = set()
    for scenario_id in [external.get("intent"), *(external.get("alternatives") or [])]:
        scenario_id = str(scenario_id or "")
        if not scenario_id or scenario_id in seen or scenario_id not in SCENARIO_LABELS:
            continue
        seen.add(scenario_id)
        output.append(
            {
                "scenario_id": scenario_id,
                "label": SCENARIO_LABELS[scenario_id],
                "mode": DEFINITIONS.get(scenario_id, {}).get("mode", ""),
                "score": round(float(external.get("confidence") or 0) / 10, 2),
            }
        )
    return output[:3]


def merge_semantic_resolution(local: JsonObject, external: JsonObject) -> JsonObject:
    """Fuse LLM semantics into local evidence without allowing it to bypass safety."""
    result = copy.deepcopy(local)
    external_intent = external.get("intent")
    external_confidence = int(external.get("confidence") or 0)
    local_intent = local.get("selected")
    local_confidence = int(local.get("confidence") or 0)

    source = "local_intent_graph"
    fusion_note = "local resolution retained"
    selected = local_intent
    needs_clarification = bool(local.get("needs_clarification"))

    if local.get("safety_override"):
        source = "local_safety_override"
        fusion_note = "local safety override has priority over external semantics"
    elif external_intent and not external.get("needs_clarification"):
        if local_intent == external_intent:
            selected = external_intent
            needs_clarification = False
            source = "local_external_agreement"
            fusion_note = "local and external semantic resolutions agree"
            result["confidence"] = max(local_confidence, external_confidence)
        elif local.get("needs_clarification") and external_confidence >= 70:
            selected = external_intent
            needs_clarification = False
            source = "external_llm"
            fusion_note = "external semantics resolved a locally ambiguous utterance"
            result["confidence"] = external_confidence
        elif local_intent and local_intent != external_intent:
            source = "local_external_conflict_local_retained"
            fusion_note = "semantic conflict detected; deterministic local resolution retained"

    if selected:
        result["status"] = "resolved"
        result["selected"] = selected
        result["selected_label"] = SCENARIO_LABELS[selected]
        result["needs_clarification"] = False
    else:
        result["status"] = "clarify"
        result["selected"] = None
        result["selected_label"] = "需要澄清"
        result["needs_clarification"] = True

    if source.startswith("external_llm"):
        result["alternatives"] = _external_alternatives(external)
        reason = str(external.get("reason") or "").strip()
        result.setdefault("signals", [])
        result["signals"] = [
            {
                "scenario_id": selected,
                "label": "外接模型语义理解",
                "phrase": reason or SCENARIO_LABELS.get(str(selected), ""),
                "contribution": 0.0,
                "negated": False,
                "source": "external_llm",
            },
            *list(result.get("signals") or []),
        ][:7]

    result["algorithm"] = "SemanticUnderstandingFusion"
    result["version"] = "3.0.0"
    result["semantic_source"] = source
    result["semantic_slots"] = (
        _clean_slots(external.get("slots"))
        if external_intent == selected and not external.get("needs_clarification")
        else {}
    )
    result["semantic_fusion_note"] = fusion_note
    result["external_semantics"] = {
        "intent": external_intent,
        "confidence": external_confidence,
        "needs_clarification": bool(external.get("needs_clarification")),
        "reason": str(external.get("reason") or "")[:240],
        "alternatives": list(external.get("alternatives") or [])[:3],
        "negated_intents": list(external.get("negated_intents") or [])[:5],
        "provider": external.get("provider"),
        "model": external.get("model"),
    }
    return result


def resolve_with_external_llm(message: str, *, snapshot: JsonObject, mode: str,
                              history: Optional[List[JsonObject]] = None,
                              client: Optional[ExternalSemanticClient] = None) -> JsonObject:
    """Resolve semantics with LLM assistance; fail safely to local IntentGraph on API errors."""
    local = resolve_intent(message, snapshot=snapshot, mode=mode)
    semantic_client = client or ExternalSemanticClient()
    try:
        external = semantic_client.understand(
            message, mode=mode, snapshot=snapshot, history=history
        )
    except Exception as exc:
        result = copy.deepcopy(local)
        result["algorithm"] = "SemanticUnderstandingFusion"
        result["version"] = "3.0.0"
        result["semantic_source"] = "local_fallback"
        result["semantic_slots"] = {}
        result["semantic_fusion_note"] = "external semantic service failed; local IntentGraph retained"
        result["external_semantics"] = {
            "error": str(exc)[:240],
            "provider": "openai_compatible",
            "model": semantic_client.model,
        }
        return result
    return merge_semantic_resolution(local, external)
