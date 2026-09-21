# -*- coding: utf-8 -*-
"""Headless Agent service shared by the REST API and tests."""
from __future__ import annotations

import copy
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple


from components.audit_store import (
    create_session,
    finish_run,
    get_session,
    get_session_history,
    get_run_context,
    get_run_trace,
    init_db,
    log_confirmation,
    start_run,
)
from components.config import SETTINGS
from components.intent_graph import resolve_intent
from components.knowledge_retriever import retrieve_knowledge
from components.semantic_understanding import resolve_with_external_llm
from components.rule_engine import run_rule
from components.tool_executor import ToolExecutor
from components.tool_registry import load_tool_registry
from components.vehicle_gateway import VehicleGateway
from perception_fusion import (
    calculate_safety_score,
    fuse_perception,
    summarize_action_outcome,
)


JsonObject = Dict[str, Any]

LOCAL_ENGINE = "融合编排引擎（本地可审计）"
EXTERNAL_LLM_ENGINE = "外接模型（语义理解）"
MODE_IDENTITIES = {
    "车主自驾": "OWNER_DRIVE",
    "Robotaxi 乘客": "ROBOTAXI_RIDE",
}
REQUIRED_SNAPSHOT_SECTIONS = (
    "identity",
    "vehicle_state",
    "order_state",
    "environment_state",
)
VALID_STEP_STATUSES = {
    "planned",
    "done",
    "degraded",
    "pending_confirm",
    "waiting_dependency",
    "failed",
    "blocked",
    "blocked_dependency",
    "cancelled",
}


class ServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class AgentRunService:
    """Coordinates semantic understanding and deterministic decision components."""

    def __init__(self) -> None:
        self.tool_meta, self.tool_schemas = load_tool_registry()
        if not self.tool_meta:
            raise RuntimeError("No tool definitions were loaded from tools/**/*.json.")
        init_db()
        self._lock = threading.RLock()

    def available_engines(self) -> List[str]:
        engines = [LOCAL_ENGINE]
        if SETTINGS.llm_api_key:
            engines.append(EXTERNAL_LLM_ENGINE)
        return engines

    def health(self) -> JsonObject:
        simulator = VehicleGateway().health()
        return {
            "ok": True,
            "status": "ok" if simulator.get("ok") else "degraded",
            "service": "drivemate-agent-api",
            "api_version": "v1",
            "simulator": simulator,
            "audit": {"ok": True, "backend": "sqlite"},
        }

    def meta(self) -> JsonObject:
        tools = []
        for name, metadata in sorted(self.tool_meta.items()):
            tools.append(
                {
                    "name": name,
                    "domain": metadata.get("domain"),
                    "level": metadata.get("level"),
                    "confirm": bool(metadata.get("confirm")),
                    "idempotent": bool(metadata.get("idempotent")),
                    "description": metadata.get("description", ""),
                }
            )
        return {
            "api_version": "v1",
            "backend": "v10-semantic-safety-core",
            "tool_count": len(tools),
            "tools": tools,
            "modes": list(MODE_IDENTITIES),
            "engines": self.available_engines(),
            "external_semantic": {
                "enabled": bool(SETTINGS.llm_api_key),
                "model": SETTINGS.llm_model,
                "base_url": SETTINGS.llm_base_url,
                "scope": "semantic_understanding_only",
            },
        }

    def create_run(self, payload: Any) -> JsonObject:
        message, mode, engine, snapshot, requested_session_id = self._validate_create_payload(payload)
        user_id = str(snapshot["identity"].get("user_id") or "demo_user")
        with self._lock:
            session_id = self._resolve_session(requested_session_id, user_id, mode)
            history = get_session_history(session_id)
            run_id = start_run(session_id, message, snapshot)
            before_state = self._simulator_values()
            try:
                if engine == EXTERNAL_LLM_ENGINE:
                    result = self._run_external_semantic(
                        message, mode, snapshot, run_id=run_id, history=history
                    )
                else:
                    result = self._run_local(
                        message, mode, snapshot, run_id=run_id, history=history
                    )
                if "session_context" not in result:
                    result = self._attach_context_evidence(result, message, history)
            except Exception as exc:
                result = self._failed_result(str(exc))
                result = self._finalize_result(
                    result,
                    run_id=run_id,
                    session_id=session_id,
                    engine=engine,
                    snapshot=snapshot,
                    before_state=before_state,
                    after_state=self._simulator_values(),
                )
                finish_run(run_id, result)
                raise ServiceError(
                    f"Agent execution failed for run {run_id}: {exc}", 500
                ) from exc
            else:
                after_state = self._simulator_values()
                result = self._finalize_result(
                    result,
                    run_id=run_id,
                    session_id=session_id,
                    engine=engine,
                    snapshot=snapshot,
                    before_state=before_state,
                    after_state=after_state,
                )
                finish_run(run_id, result)
                return copy.deepcopy(result)

    def confirm_run(self, run_id: str, payload: Any) -> JsonObject:
        snapshot = self._validate_confirmation_payload(payload)
        with self._lock:
            context = self._require_run(run_id)
            current = context["result"]
            status = str(current.get("run_status") or "")
            if status == "cancelled":
                raise ServiceError("Cancelled runs cannot be confirmed.", 409)
            pending = current.get("pending_tools")
            pending = pending if isinstance(pending, list) else []
            if not pending:
                return copy.deepcopy(current)

            mode = str(context["mode"])
            self._validate_snapshot(snapshot, mode)
            before_state = self._simulator_values()
            engine = str(current.get("engine") or LOCAL_ENGINE)
            grants = {
                str(item.get("step_id")): str(item.get("grant_id"))
                for item in pending
                if item.get("step_id") and item.get("grant_id")
            }
            for item in pending:
                log_confirmation(run_id, str(item.get("name") or ""), "confirmed")
            preserved_resolution = (
                current.get("intent_resolution")
                if engine == EXTERNAL_LLM_ENGINE
                and isinstance(current.get("intent_resolution"), dict)
                else None
            )
            result = self._run_local(
                str(context["user_text"]),
                mode,
                snapshot,
                run_id=run_id,
                confirmed=True,
                previous_calls=list(current.get("calls") or []),
                confirmed_grants=grants,
                intent_resolution=preserved_resolution,
            )
            if any(
                item.get("confirmation_invalidated")
                for item in result.get("pending_tools", [])
                if isinstance(item, dict)
            ):
                result["reply"] = (
                    str(result.get("reply") or "")
                    + "\n\n实时状态已变化，原确认已失效，请核对更新后的方案后再次确认。"
                ).strip()
                for item in result.get("pending_tools", []):
                    if isinstance(item, dict):
                        log_confirmation(
                            run_id,
                            str(item.get("name") or ""),
                            "confirmation_invalidated",
                        )

            after_state = self._simulator_values()
            result = self._finalize_result(
                result,
                run_id=run_id,
                session_id=str(context["session_id"]),
                engine=engine,
                snapshot=snapshot,
                before_state=before_state,
                after_state=after_state,
                previous=current,
            )
            finish_run(run_id, result)
            return copy.deepcopy(result)

    def cancel_run(self, run_id: str) -> JsonObject:
        with self._lock:
            context = self._require_run(run_id)
            result = copy.deepcopy(context["result"])
            status = str(result.get("run_status") or "")
            if status == "cancelled":
                return result
            pending = result.get("pending_tools")
            pending = pending if isinstance(pending, list) else []
            if not pending:
                raise ServiceError("This run has no pending operation to cancel.", 409)

            pending_ids = {str(item.get("step_id")) for item in pending}
            pending_names = {str(item.get("name")) for item in pending}
            for item in pending:
                log_confirmation(run_id, str(item.get("name") or ""), "cancelled")
            for step in result.get("steps", []):
                if not isinstance(step, dict):
                    continue
                if (
                    str(step.get("id")) in pending_ids
                    or (
                        step.get("status") == "pending_confirm"
                        and str(step.get("tool")) in pending_names
                    )
                ):
                    step["status"] = "cancelled"
                    step["status_raw"] = "cancelled"
                    step["note"] = "用户已取消待确认操作"
            result["pending_tools"] = []
            result["run_status"] = "cancelled"
            if "待确认操作已取消" not in str(result.get("reply") or ""):
                result["reply"] = (
                    str(result.get("reply") or "") + "\n\n待确认操作已取消。"
                ).strip()
            result["phases"] = self._build_phases(result)
            result["action_outcome"] = summarize_action_outcome(result)
            finish_run(run_id, result)
            return copy.deepcopy(result)

    def simulator_state(self) -> JsonObject:
        state = VehicleGateway().state()
        if not state.get("success"):
            raise ServiceError(
                "Cockpit simulator state is unavailable: "
                + str(state.get("summary") or "unknown error"),
                503,
            )
        return state

    def audit_run(self, run_id: str) -> JsonObject:
        self._require_run(run_id)
        return get_run_trace(run_id)

    def _validate_create_payload(
        self, payload: Any
    ) -> Tuple[str, str, str, JsonObject, Optional[str]]:
        if not isinstance(payload, dict):
            raise ServiceError("Request body must be a JSON object.")
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ServiceError("message is required.")
        if len(message) > 4000:
            raise ServiceError("message must not exceed 4000 characters.")
        mode = str(payload.get("mode") or "").strip()
        if mode not in MODE_IDENTITIES:
            raise ServiceError("mode must be either 车主自驾 or Robotaxi 乘客.")
        engine = str(payload.get("engine") or LOCAL_ENGINE).strip()
        if engine not in self.available_engines():
            raise ServiceError(
                f"Engine is unavailable: {engine}. Configure the required credentials or use {LOCAL_ENGINE}.",
                503 if engine == EXTERNAL_LLM_ENGINE else 400,
            )
        snapshot = payload.get("snapshot")
        self._validate_snapshot(snapshot, mode)
        session_id = str(payload.get("session_id") or "").strip() or None
        if session_id and (len(session_id) > 64 or not session_id.startswith("S-")):
            raise ServiceError("session_id is invalid.")
        return message, mode, engine, copy.deepcopy(snapshot), session_id

    @staticmethod
    def _resolve_session(session_id: Optional[str], user_id: str, mode: str) -> str:
        if not session_id:
            return create_session(user_id, mode)
        session = get_session(session_id)
        if not session:
            raise ServiceError(f"Session not found: {session_id}", 404)
        if session["user_id"] != user_id or session["mode"] != mode:
            raise ServiceError("session_id does not belong to this user and mode.", 409)
        return session_id

    def _validate_confirmation_payload(self, payload: Any) -> JsonObject:
        if not isinstance(payload, dict):
            raise ServiceError("Request body must be a JSON object.")
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ServiceError("snapshot is required for confirmation.")
        return copy.deepcopy(snapshot)

    @staticmethod
    def _validate_snapshot(snapshot: Any, mode: str) -> None:
        if not isinstance(snapshot, dict):
            raise ServiceError("snapshot must be a JSON object.")
        for section in REQUIRED_SNAPSHOT_SECTIONS:
            if not isinstance(snapshot.get(section), dict):
                raise ServiceError(f"snapshot.{section} must be a JSON object.")
        actual_mode = snapshot["identity"].get("mode")
        if actual_mode != MODE_IDENTITIES[mode]:
            raise ServiceError(
                "mode does not match snapshot.identity.mode; refusing cross-domain execution."
            )

    @staticmethod
    def _require_run(run_id: str) -> JsonObject:
        context = get_run_context(run_id)
        if not context:
            raise ServiceError(f"Run not found: {run_id}", 404)
        if not isinstance(context.get("result"), dict):
            raise ServiceError(f"Run has no persisted result: {run_id}", 409)
        return context

    def _run_local(
        self,
        message: str,
        mode: str,
        snapshot: JsonObject,
        *,
        run_id: str,
        confirmed: bool = False,
        previous_calls: Optional[List[JsonObject]] = None,
        confirmed_grants: Optional[Dict[str, str]] = None,
        history: Optional[List[JsonObject]] = None,
        intent_resolution: Optional[JsonObject] = None,
    ) -> JsonObject:
        contextual_message = self._contextualize_message(message, history or [])
        resolution = intent_resolution or resolve_intent(
            contextual_message, snapshot=snapshot, mode=mode
        )
        result = run_rule(
            contextual_message,
            mode,
            snapshot,
            executor=ToolExecutor(self.tool_meta, run_id=run_id),
            tool_meta=self.tool_meta,
            confirmed=confirmed,
            previous_calls=list(previous_calls or []),
            intent_resolution=resolution,
            confirmed_grants=confirmed_grants,
        )
        return self._attach_context_evidence(result, message, history or [])

    def _run_external_semantic(
        self,
        message: str,
        mode: str,
        snapshot: JsonObject,
        *,
        run_id: str,
        history: Optional[List[JsonObject]] = None,
    ) -> JsonObject:
        """Use the external LLM only for semantics, then execute the local deterministic chain."""
        contextual_message = self._contextualize_message(message, history or [])
        resolution = resolve_with_external_llm(
            contextual_message,
            snapshot=snapshot,
            mode=mode,
            history=history or [],
        )
        result = run_rule(
            contextual_message,
            mode,
            snapshot,
            executor=ToolExecutor(self.tool_meta, run_id=run_id),
            tool_meta=self.tool_meta,
            intent_resolution=resolution,
        )
        return self._attach_context_evidence(result, message, history or [])

    @staticmethod
    def _contextualize_message(message: str, history: List[JsonObject]) -> str:
        if not history or not re.search(r"^(再|然后|那|把|改成|还是|刚才|继续)|它|这个|那里", message):
            return message
        previous = str(history[-1].get("user") or "").strip()
        return f"上一轮用户请求：{previous}\n本轮用户补充：{message}"

    @staticmethod
    def _attach_context_evidence(result: JsonObject, message: str, history: List[JsonObject]) -> JsonObject:
        result["session_context"] = {
            "history_turns_used": min(len(history), 8),
            "previous_run_ids": [item.get("run_id") for item in history[-8:]],
        }
        refs = retrieve_knowledge(message)
        result["knowledge_refs"] = refs
        if refs:
            citations = "、".join(f"`{item['source']}`" for item in refs)
            result["reply"] = (str(result.get("reply") or "") + f"\n\n本轮已检索本地知识库：{citations}。").strip()
        return result

    def _finalize_result(
        self,
        raw_result: JsonObject,
        *,
        run_id: str,
        session_id: str,
        engine: str,
        snapshot: JsonObject,
        before_state: JsonObject,
        after_state: JsonObject,
        previous: Optional[JsonObject] = None,
    ) -> JsonObject:
        result = copy.deepcopy(raw_result)
        result.setdefault("intent", "unknown")
        result.setdefault("reply", "")
        result.setdefault("risk_level", "L0")
        result.setdefault("plan_summary", "")
        result.setdefault("steps", [])
        result.setdefault("safety_tip", "无")
        result.setdefault("calls", [])
        result.setdefault("pending_tools", [])
        result["run_id"] = run_id
        result["session_id"] = session_id
        result["engine"] = engine

        fusion = fuse_perception(snapshot, str(result.get("intent") or ""))
        result["perception_fusion"] = fusion
        current_diff = self._state_diff(
            before_state, after_state, result.get("calls", []), snapshot
        )
        result["state_diff"] = self._merge_state_diff(
            previous.get("state_diff") if isinstance(previous, dict) else {},
            current_diff,
        )
        result["run_status"] = self._derive_run_status(result)
        result["execution_plan"] = [
            str(step.get("title"))
            for step in result.get("steps", [])
            if isinstance(step, dict) and step.get("title")
        ]
        result["risk_reasons"] = self._risk_reasons(result)
        result["policies_hit"] = self._policies(result)
        result["evidence"] = list(fusion.get("evidence") or [])
        navigation = self._navigation(result)
        if navigation:
            result["navigation"] = navigation
        elif isinstance(previous, dict) and isinstance(
            previous.get("navigation"), dict
        ):
            result["navigation"] = copy.deepcopy(previous["navigation"])
        result["phases"] = self._build_phases(result)
        result["action_outcome"] = summarize_action_outcome(result)
        result["safety_score"] = calculate_safety_score(result)
        return result

    @staticmethod
    def _derive_run_status(result: JsonObject) -> str:
        explicit = str(result.get("run_status") or "")
        if explicit in {"cancelled", "failed"}:
            return explicit
        if result.get("pending_tools"):
            return "waiting_confirmation"
        raw_statuses = {
            str(step.get("status_raw") or step.get("status") or "")
            for step in result.get("steps", [])
            if isinstance(step, dict)
        }
        if "degraded" in raw_statuses:
            return "degraded"
        if raw_statuses.intersection({"failed", "blocked", "blocked_dependency"}):
            return "failed"
        return "completed"

    @staticmethod
    def _build_phases(result: JsonObject) -> List[JsonObject]:
        trace = (
            result.get("decision_ledger", {}).get("trace", [])
            if isinstance(result.get("decision_ledger"), dict)
            else []
        )
        durations = {
            str(item.get("stage")): item.get("duration_ms")
            for item in trace
            if isinstance(item, dict)
        }
        status = str(result.get("run_status") or "")
        calls = [
            item for item in result.get("calls", []) if isinstance(item, dict)
        ]
        has_failed_call = any(
            call.get("result")
            not in {"success", "app_side", "pending_user_confirmation"}
            for call in calls
        )
        execute_status = (
            "cancelled"
            if status == "cancelled"
            else "waiting"
            if status == "waiting_confirmation"
            else "failed"
            if status == "failed" or has_failed_call
            else "done"
        )
        readback_status = (
            "done"
            if result.get("state_diff")
            or any(call.get("receipt_id") for call in calls)
            else "pending"
            if calls
            else "done"
        )

        def phase(name: str, status_value: str, stage: str = "") -> JsonObject:
            item: JsonObject = {"name": name, "status": status_value}
            duration = durations.get(stage)
            if isinstance(duration, (int, float)):
                item["duration_ms"] = duration
            return item

        return [
            phase("perceive", "done"),
            phase("understand", "done", "intent.resolve"),
            phase("adjudicate", "done", "constraint.plan"),
            phase("plan", "done", "plan.toposort_execute"),
            phase("execute", execute_status, "plan.toposort_execute"),
            phase("readback", readback_status),
            phase("output", "done"),
        ]

    @staticmethod
    def _risk_reasons(result: JsonObject) -> List[str]:
        resolution = result.get("intent_resolution")
        resolution = resolution if isinstance(resolution, dict) else {}
        reasons = []
        for signal in resolution.get("signals", []):
            if not isinstance(signal, dict):
                continue
            label = str(signal.get("label") or "").strip()
            phrase = str(signal.get("phrase") or "").strip()
            if label:
                reasons.append(f"{label}：{phrase}" if phrase else label)
        return reasons[:5]

    @staticmethod
    def _policies(result: JsonObject) -> List[str]:
        shield = result.get("constraint_shield")
        shield = shield if isinstance(shield, dict) else {}
        policies = []
        principle = str(shield.get("principle") or "").strip()
        if principle:
            policies.append(principle)
        for candidate in shield.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            policies.extend(
                str(item)
                for item in candidate.get("hard_violations", [])
                if str(item).strip()
            )
        return list(dict.fromkeys(policies))[:5]

    @staticmethod
    def _navigation(result: JsonObject) -> JsonObject:
        candidates: Iterable[JsonObject] = list(result.get("pending_tools") or []) + list(
            result.get("calls") or []
        )
        for item in reversed(list(candidates)):
            if not isinstance(item, dict):
                continue
            tool = str(item.get("name") or item.get("tool") or "")
            if tool not in {"plan_route", "modify_destination"}:
                continue
            arguments = item.get("arguments")
            arguments = arguments if isinstance(arguments, dict) else {}
            destination = arguments.get("destination")
            if isinstance(destination, dict):
                destination = destination.get("address") or destination.get("name")
            if destination:
                return {"destination": str(destination)}
        return {}

    @staticmethod
    def _failed_result(message: str) -> JsonObject:
        return {
            "intent": "backend_error",
            "reply": "后端执行失败，未继续执行车辆或订单操作。",
            "risk_level": "L0",
            "plan_summary": "执行链异常终止",
            "steps": [],
            "safety_tip": "请检查后端配置与日志后重试。",
            "calls": [],
            "pending_tools": [],
            "run_status": "failed",
            "error": {"message": message[:500]},
        }

    @staticmethod
    def _simulator_values() -> JsonObject:
        response = VehicleGateway().state()
        state = response.get("state") if isinstance(response, dict) else None
        if not isinstance(state, dict):
            return {}
        values = {}
        for namespace, record in state.items():
            if not isinstance(record, dict):
                continue
            value = record.get("value")
            if isinstance(value, dict):
                values[str(namespace)] = copy.deepcopy(value)
        return values

    @staticmethod
    def _state_diff(
        before: JsonObject,
        after: JsonObject,
        calls: Any,
        snapshot: JsonObject,
    ) -> JsonObject:
        aliases = {"climate.fan_speed": "climate.fan_level"}
        changes: JsonObject = {}
        namespaces = set(before) | set(after)
        for namespace in namespaces:
            old_value = before.get(namespace)
            new_value = after.get(namespace)
            if not isinstance(new_value, dict):
                continue
            old_value = old_value if isinstance(old_value, dict) else {}
            for key, value in new_value.items():
                if old_value.get(key) == value:
                    continue
                path = aliases.get(
                    f"{namespace}.{key}", f"{namespace}.{key}"
                )
                changes[path] = {"before": old_value.get(key), "after": value}

        order_state = snapshot.get("order_state")
        order_state = order_state if isinstance(order_state, dict) else {}
        for call in calls if isinstance(calls, list) else []:
            if not isinstance(call, dict) or call.get("result") != "success":
                continue
            raw = call.get("raw_result")
            raw = raw if isinstance(raw, dict) else {}
            tool = str(call.get("tool") or "")
            if tool == "modify_destination" and raw.get("destination"):
                changes["order.destination"] = {
                    "before": order_state.get("destination"),
                    "after": raw["destination"],
                }
            elif tool == "modify_pickup_point" and raw.get("new_location"):
                changes["order.pickup_location"] = {
                    "before": order_state.get("passenger_location"),
                    "after": raw["new_location"],
                }
            elif tool == "cancel_order" and raw.get("cancelled"):
                changes["order.status"] = {
                    "before": order_state.get("status"),
                    "after": "cancelled",
                }
            elif tool == "request_curbside_stop":
                vehicle_state = snapshot.get("vehicle_state")
                vehicle_state = vehicle_state if isinstance(vehicle_state, dict) else {}
                changes["vehicle_motion.speed_kmh"] = {
                    "before": vehicle_state.get("speed_kmh"),
                    "after": raw.get("speed_kmh", 0),
                }
                changes["vehicle_motion.gear"] = {
                    "before": vehicle_state.get("gear"),
                    "after": raw.get("gear", "P"),
                }
        return changes

    @staticmethod
    def _merge_state_diff(previous: Any, current: JsonObject) -> JsonObject:
        merged = copy.deepcopy(previous) if isinstance(previous, dict) else {}
        for path, change in current.items():
            if path in merged and isinstance(merged[path], dict):
                merged[path]["after"] = change.get("after")
            else:
                merged[path] = change
        return merged
