# -*- coding: utf-8 -*-
"""ConstraintShield Planner 2.0。

先生成候选，再执行硬约束过滤；仅在可行集上按
SafetyMargin > GoalFit > TimeEfficiency > Comfort 做真正的字典序排序。
"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple

from components.safety_guard import haversine_m


def _mode_for(intent: str) -> str:
    return "robotaxi" if intent in {
        "medical", "find_car", "modify_pickup", "reroute", "cancel_order",
        "human_support", "trip_status",
    } else "driver"


def _distance(snapshot: Dict[str, Any]):
    o = snapshot.get("order_state") or {}
    p, v = o.get("passenger_coordinates") or {}, o.get("vehicle_coordinates") or {}
    try:
        return haversine_m(float(p["lat"]), float(p["lng"]), float(v["lat"]), float(v["lng"]))
    except Exception:
        return None


def _risk_level(intent: str, text: str, snapshot: Dict[str, Any]) -> str:
    v = snapshot.get("vehicle_state") or {}
    if intent == "medical": return "L3"
    if intent == "fatigue":
        hours = float(v.get("driving_hours") or 0)
        return "L3" if hours >= 3 or any(k in text for k in ("睁不开", "方向飘", "打瞌睡", "犯困")) else "L2"
    if intent in {"modify_pickup", "reroute", "cancel_order", "find_car", "charging"}: return "L2"
    if intent == "route_plan": return "L2"
    if intent == "human_support": return "L1"
    if intent in {"parent_child", "climate", "commute"}: return "L1"
    return "L0"


def _hard_violations(intent: str, candidate_id: str, text: str, snapshot: Dict[str, Any], mode: str) -> List[str]:
    violations: List[str] = []
    expected = _mode_for(intent)
    actual = "driver" if mode == "车主自驾" else "robotaxi"
    if expected != actual:
        violations.append("当前身份/运行模式无权执行该领域动作")
        return violations

    v = snapshot.get("vehicle_state") or {}
    env = snapshot.get("environment_state") or {}
    if candidate_id == "direct_action":
        if intent == "medical":
            violations.append("疑似急性医疗风险时不得继续普通行程而不升级安全处置")
        elif intent == "fatigue":
            if float(v.get("driving_hours") or 0) >= 3 or any(k in text for k in ("睁不开", "方向飘", "打瞌睡", "犯困", "想睡")):
                violations.append("高疲劳风险下不得以继续驾驶作为便利性优先方案")
        elif intent == "modify_pickup":
            parking = str(env.get("parking_policy") or "")
            risky_text = any(k in text for k in ("路口", "交叉口", "消防通道", "非机动车道", "主路", "禁停", "不能停"))
            if risky_text or any(k in parking for k in ("禁停", "禁止", "不允许")):
                violations.append("当前上车点违反停车/道路安全硬约束")
        elif intent == "find_car":
            d = _distance(snapshot)
            if d is None:
                violations.append("缺少可验证人车距离，不得直接闪灯鸣笛")
            elif d > 100:
                violations.append(f"人车距离 {d:.1f}m 超过闪灯鸣笛 100m 限制")
        elif intent in {"reroute", "cancel_order"}:
            violations.append("订单/费用变更不得绕过用户确认")
        elif intent == "route_plan":
            violations.append("导航目标变更不得绕过用户确认")
        elif intent == "charging" and float(v.get("soc_percent") or 100) <= 10:
            violations.append("极低电量下不得跳过补能安全计划")
        elif intent == "parent_child" and float(v.get("speed_kmh") or 0) > 0 and any(k in text for k in ("回头", "伸手", "边开边哄")):
            violations.append("车辆行驶中不得要求驾驶员回头/伸手处理后排")
    return violations


def _metrics(intent: str, candidate_id: str, risk: str) -> Dict[str, int]:
    severe = risk in {"L2", "L3"}
    if candidate_id == "safe_closure":
        return {"safety_margin": 99, "goal_fit": 94, "time_efficiency": 72 if severe else 88, "comfort": 80 if severe else 91}
    if candidate_id == "direct_action":
        return {"safety_margin": 32 if severe else 80, "goal_fit": 76, "time_efficiency": 98, "comfort": 75}
    return {"safety_margin": 98, "goal_fit": 76 if severe else 64, "time_efficiency": 48, "comfort": 68}


def _lex_key(metrics: Dict[str, int]) -> Tuple[int, int, int, int]:
    return (metrics["safety_margin"], metrics["goal_fit"], metrics["time_efficiency"], metrics["comfort"])


def plan_candidates(intent: str, text: str, snapshot: Dict[str, Any], mode: str) -> Dict[str, Any]:
    risk = _risk_level(intent, text, snapshot)
    names = {
        "safe_closure": "当前安全闭环",
        "direct_action": "便利优先直达",
        "human_handoff": "人工接管兜底",
    }
    candidates = []
    for cid in ("safe_closure", "direct_action", "human_handoff"):
        violations = _hard_violations(intent, cid, text, snapshot, mode)
        metrics = _metrics(intent, cid, risk)
        candidates.append({"id": cid, "name": names[cid], "feasible": not violations,
                           "metrics": metrics, "hard_violations": violations, "rank": None})
    feasible = sorted((c for c in candidates if c["feasible"]), key=lambda c: _lex_key(c["metrics"]), reverse=True)
    for idx, c in enumerate(feasible, 1):
        c["rank"] = idx
    selected = feasible[0]["id"] if feasible else None
    return {
        "algorithm": "ConstraintShield Planner", "version": "2.0.0",
        "principle": "先硬约束过滤，再按 SafetyMargin > GoalFit > TimeEfficiency > Comfort 字典序排序",
        "formula": "P_safe={p | hardViolations(p)=0}; p*=lexmax<Safety, GoalFit, Time, Comfort>",
        "risk_level": risk, "candidates": candidates, "selected_candidate": selected,
    }


def tool_allowed_for_intent(intent: str, tool: str) -> bool:
    """约束 LLM/规则提议工具的领域集合；最终仍须 SafetyGuard 再校验。"""
    allowed = {
        "fatigue": {"get_fatigue_status", "suggest_safety_action", "find_rest_area", "plan_route", "set_seat", "play_media", "set_climate", "transfer_to_human"},
        "parent_child": {"detect_child_presence", "set_climate", "play_media", "set_ambient", "transfer_to_human"},
        "charging": {"get_vehicle_health", "find_charging_station", "plan_route", "reserve_charging", "transfer_to_human"},
        "find_car": {"get_order_status", "share_vehicle_location", "contact_vehicle", "transfer_to_human"},
        "modify_pickup": {"get_order_status", "find_safe_pickup_point", "modify_pickup_point", "share_vehicle_location", "transfer_to_human"},
        "reroute": {"get_order_status", "modify_destination", "transfer_to_human"},
        "cancel_order": {"get_order_status", "cancel_order", "transfer_to_human"},
        "medical": {"report_issue", "transfer_to_human", "crm_agent", "emergency_call", "set_climate"},
        "climate": {"set_climate"},
        "commute": {"set_climate", "set_ambient", "plan_route"},
        "route_plan": {"plan_route", "transfer_to_human"},
        "vehicle_status": {"get_vehicle_health", "transfer_to_human"},
        "human_support": {"transfer_to_human", "crm_agent"},
        "trip_status": {"get_order_status", "share_vehicle_location", "transfer_to_human"},
    }
    return tool in allowed.get(intent, set())
