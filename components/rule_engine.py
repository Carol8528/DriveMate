# -*- coding: utf-8 -*-
"""规则编排器 2.0：IntentGraph → ConstraintShield → Dependency Planner → RecoveryMesh。

不依赖 Streamlit；所有执行都必须经 ToolExecutor 获取真实回执。
"""
from __future__ import annotations

import re
from typing import Dict, Any, List, Optional

from components.intent_graph import resolve_intent, clarification_reply
from components.constraint_shield import plan_candidates
from components.dependency_planner import execute_plan, DependencyError
from components.decision_ledger import TraceRecorder, build_ledger
from components.audit_store import log_decision_event


RISK_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


def detect_intent(text: str) -> str:
    """兼容旧调用；新主链应使用 resolve_intent。"""
    r = resolve_intent(text, snapshot={}, mode="车主自驾")
    return r.get("selected") or "general"


def _step(sid: str, seq: int, title: str, tool: str, tool_meta: dict, arguments=None,
          depends_on=None, refresh_on_confirm: bool = False) -> dict:
    return {"id": sid, "seq": seq, "title": title, "tool": tool,
            "arguments": arguments or {}, "depends_on": depends_on or [],
            "refresh_on_confirm": refresh_on_confirm,
            "status": "planned", "safety_level": tool_meta.get(tool, {}).get("level", "L0"), "note": ""}


def _extract_destination(text: str, snapshot: dict) -> Optional[str]:
    patterns = [
        r"(?:改|换)(?:一下|个)?目的地(?:到|去|为)?\s*([^，。；]{2,30})",
        r"(?:新增|加)(?:一个|个)?途经(?:点)?(?:到|去|为)?\s*([^，。；]{2,30})",
        r"(?:去|到)\s*([^，。；]{2,24})(?:吧|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            value = m.group(1).strip(" ，。吧")
            if value:
                return value
    return None


def _plan_for(intent: str, text: str, mode: str, snap: dict, tool_meta: dict) -> Dict[str, Any]:
    v, o, env = snap.get("vehicle_state", {}), snap.get("order_state", {}), snap.get("environment_state", {})

    if intent == "fatigue":
        hours = float(v.get("driving_hours") or 0)
        severe_handoff = hours >= 3.5 or any(
            signal in text for signal in ("睁不开", "方向飘", "打瞌睡", "困得厉害")
        )
        steps = [
            _step("fatigue-state", 1, "读取 DMS 疲劳状态", "get_fatigue_status", tool_meta, refresh_on_confirm=True),
            _step("fatigue-advice", 2, "生成安全建议", "suggest_safety_action", tool_meta,
                  {"risk_type": "fatigue", "severity": "high" if hours < 4 else "critical",
                  "current_context": {"speed": float(v.get("speed_kmh") or 0), "location": str(o.get("vehicle_location") or "当前位置"),
                                       "road_type": str(env.get("area_type") or "未知")}}, ["fatigue-state"]),
            _step("fatigue-rest", 3, "查询最近安全休息点", "find_rest_area", tool_meta,
                  {"radius_km": 50, "along_route": True, "facilities": ["parking", "restroom"]}, ["fatigue-state"], True),
            _step("fatigue-climate", 4, "开启驾驶位提神空调", "set_climate", tool_meta,
                  {"zone": "driver", "temperature": 21, "fan_speed": 3, "mode": "auto"}, ["fatigue-state"]),
            _step("fatigue-seat", 5, "开启座椅按摩（辅助提神）", "set_seat", tool_meta,
                  {"seat_position": "driver", "mode": "massage", "intensity": 2}, ["fatigue-state"]),
            _step("fatigue-media", 6, "播放提神音乐", "play_media", tool_meta,
                  {"source": "提神歌单", "genre": "music", "volume": 35}, ["fatigue-state"]),
        ]
        if severe_handoff:
            steps.extend([
                _step("fatigue-human", 7, "转接人工安全专员", "transfer_to_human", tool_meta,
                     {"reason": "safety_concern", "priority": "urgent",
                      "summary": "持续高疲劳风险，需人工安全协助", "context_snapshot": snap},
                     ["fatigue-state"]),
                _step("fatigue-crm", 8, "客服 Agent 接管安全会话", "crm_agent", tool_meta,
                     {"skill_group": "vehicle_emergency",
                      "transfer_context": {"upstream_step_id": "fatigue-human"}},
                     ["fatigue-human"]),
            ])
        steps.append(
            _step("fatigue-route", len(steps) + 1, "导航至安全休息点", "plan_route", tool_meta,
                  {"destination": {"$from": "fatigue-rest", "path": "destination"}, "preference": "fastest"}, ["fatigue-rest"])
        )
        handoff_note = "；持续高疲劳风险已同步转接人工安全专员" if severe_handoff else ""
        return {"plan_summary": "疲劳驾驶：状态复核 → 安全休息点 → 确认导航 + 可逆提神措施",
                "reply": f"检测到疲劳相关证据，当前连续驾驶约 {hours:g} 小时。系统先执行可逆的座舱辅助，并查询最近安全休息点{handoff_note}；导航属于行程变更，需确认后执行。",
                "safety_tip": "请勿把座椅按摩或音乐视为继续疲劳驾驶的替代方案，应尽快在安全地点停车休息。", "steps": steps}

    if intent == "parent_child":
        steps = [
            _step("child-state", 1, "读取儿童/后排状态", "detect_child_presence", tool_meta, refresh_on_confirm=True),
            _step("child-climate", 2, "后排空调调至舒适档", "set_climate", tool_meta,
                  {"zone": "rear", "temperature": 25, "fan_speed": 2, "mode": "auto"}, ["child-state"]),
            _step("child-media", 3, "播放儿童内容", "play_media", tool_meta,
                  {"source": "儿童歌单", "genre": "children", "volume": 28}, ["child-state"]),
            _step("child-ambient", 4, "切换舒缓氛围", "set_ambient", tool_meta, {"scene": "relax"}, ["child-state"]),
        ]
        return {"plan_summary": "儿童安全：后排状态读取 → 舒适性联动",
                "reply": "先读取儿童/后排状态，再执行可逆的温度、媒体和氛围调节；驾驶过程中不会建议驾驶员回头或伸手处理后排。",
                "safety_tip": "儿童应使用适龄约束系统；离车时切勿将儿童单独留在车内。", "steps": steps}

    if intent == "charging":
        steps = [
            _step("energy-health", 1, "读取车况与续航", "get_vehicle_health", tool_meta, refresh_on_confirm=True),
            _step("energy-station", 2, "查询沿途快充站", "find_charging_station", tool_meta,
                  {"along_route": True, "distance_max": 80}, ["energy-health"], True),
            _step("energy-route", 3, "规划补能路线", "plan_route", tool_meta,
                  {"destination": {"$from": "energy-station", "path": "stations.0.station_id"}, "preference": "fastest"}, ["energy-station"]),
            _step("energy-reserve", 4, "预约快充桩", "reserve_charging", tool_meta,
                  {"station_id": {"$from": "energy-station", "path": "stations.0.station_id"}}, ["energy-station"]),
        ]
        return {"plan_summary": "补能：车况复核 → 充电资源 → 路线/预约确认",
                "reply": f"当前电量 {v.get('soc_percent')}%，预估续航 {v.get('range_km')} km。将先重新读取车况和充电资源，路线与预约均需确认。",
                "safety_tip": "低电量场景优先保证可达性；非幂等预约失败不会自动重复提交。", "steps": steps}

    if intent == "find_car":
        steps = [
            _step("findcar-status", 1, "读取订单与实时位置", "get_order_status", tool_meta, refresh_on_confirm=True),
            _step("findcar-share", 2, "生成位置/AR 找车引导", "share_vehicle_location", tool_meta,
                  {"share_method": "ar_guide"}, ["findcar-status"]),
            _step("findcar-contact", 3, "远程闪灯鸣笛", "contact_vehicle", tool_meta,
                  {"action": "both", "duration_seconds": 3}, ["findcar-status"]),
        ]
        return {"plan_summary": "找车：实时订单 → 位置引导 → 100m 硬校验后闪灯鸣笛",
                "reply": "系统先读取实时订单位置并提供找车引导；闪灯鸣笛需确认，且执行前会基于当前经纬度重新做 100 米硬校验。",
                "safety_tip": "请在人行区域寻找车辆，不要进入活动机动车道。", "steps": steps}

    if intent == "route_plan":
        destination = _extract_destination(text, snap) or str(o.get("destination") or "").strip()
        if not destination:
            return {"clarify": True, "reply": "已识别路线导航请求，但当前没有明确目的地。请补充要去哪里。"}
        steps = [
            _step("route-start", 1, f"导航至{destination}", "plan_route", tool_meta,
                 {"destination": destination, "preference": "fastest"}),
        ]
        return {"plan_summary": f"路线导航：确认后开始前往{destination}",
                "reply": f"已读取当前目的地“{destination}”并生成导航动作；确认后开始导航。",
                "safety_tip": "请在不影响驾驶的情况下确认导航目标。", "steps": steps}

    if intent == "vehicle_status":
        steps = [
            _step("vehicle-health", 1, "读取车辆与续航状态", "get_vehicle_health", tool_meta),
        ]
        return {"plan_summary": "读取当前车辆、电量与续航状态",
                "reply": f"正在读取车辆状态：当前电量 {v.get('soc_percent')}%，预估续航 {v.get('range_km')} km。",
                "safety_tip": "无", "steps": steps}

    if intent == "human_support":
        steps = [
            _step("support-transfer", 1, "创建人工客服转接", "transfer_to_human", tool_meta,
                 {"reason": "passenger_request", "priority": "normal",
                  "summary": text[:180], "context_snapshot": snap}),
            _step("support-crm", 2, "客服 Agent 接管会话", "crm_agent", tool_meta,
                 {"skill_group": "pax_order_general" if mode == "Robotaxi 乘客" else "vehicle_general",
                  "transfer_context": {"upstream_step_id": "support-transfer"}},
                 ["support-transfer"]),
        ]
        return {"plan_summary": "携带当前行程上下文创建转接并由客服 Agent 接管",
                "reply": "已识别人工客服请求，将携带当前订单与环境上下文创建转接工单，并由客服 Agent 接管。",
                "safety_tip": "涉及账户、费用或人身安全时，请向客服准确说明当前情况。", "steps": steps}

    if intent == "trip_status":
        steps = [
            _step("trip-status", 1, "读取当前订单与车辆位置", "get_order_status", tool_meta),
        ]
        return {"plan_summary": "读取 Robotaxi 当前订单、车辆位置与距离",
                "reply": f"正在查询当前行程状态：{o.get('status', '未知')}。",
                "safety_tip": "无", "steps": steps}

    if intent == "modify_pickup":
        steps = [
            _step("pickup-status", 1, "读取订单当前状态", "get_order_status", tool_meta, refresh_on_confirm=True),
            _step("pickup-safe", 2, "搜索合规替代上车点", "find_safe_pickup_point", tool_meta,
                  {"max_walk_m": 300}, ["pickup-status"], True),
            _step("pickup-change", 3, "更新上车点", "modify_pickup_point", tool_meta,
                  {"new_location": {"$from": "pickup-safe", "path": "candidate"}, "reason": "safety_concern"}, ["pickup-safe"]),
        ]
        return {"plan_summary": "上车点：状态复核 → 安全候选 → 确认后更新订单",
                "reply": "不会按危险位置直接停车。系统会先根据当前订单/道路状态生成合规替代上车点，再在你确认后修改订单。",
                "safety_tip": "路口、消防通道、非机动车道和明确禁停区域均属于硬约束，便利性排序不能覆盖。", "steps": steps}

    if intent == "reroute":
        destination = _extract_destination(text, snap)
        if not destination:
            return {"clarify": True, "reply": "已识别到目的地/途经点变更，但缺少明确的新目的地。请补充要改到哪里。"}
        steps = [
            _step("reroute-status", 1, "读取当前订单状态", "get_order_status", tool_meta, refresh_on_confirm=True),
            _step("reroute-change", 2, "修改订单目的地", "modify_destination", tool_meta,
                  {"destination": destination, "reason": "passenger_request"}, ["reroute-status"]),
        ]
        return {"plan_summary": "订单变更：实时状态复核 → 确认后修改目的地",
                "reply": f"已解析新目的地“{destination}”。会先复核当前订单状态，确认后才提交变更。",
                "safety_tip": "订单/费用相关写操作必须显式确认，失败后不会自动重复提交。", "steps": steps}

    if intent == "cancel_order":
        steps = [
            _step("cancel-status", 1, "读取订单状态与费用信息", "get_order_status", tool_meta, refresh_on_confirm=True),
            _step("cancel-write", 2, "取消订单", "cancel_order", tool_meta, {"reason": "passenger_initiated"}, ["cancel-status"]),
        ]
        return {"plan_summary": "取消订单：实时状态复核 → 确认后取消",
                "reply": "会先重新读取订单状态；取消属于订单写操作，只有确认后才提交。",
                "safety_tip": "非幂等取消操作失败后不自动重试，避免重复状态变更。", "steps": steps}

    if intent == "medical":
        steps = [
            _step("medical-report", 1, "登记紧急求助", "report_issue", tool_meta,
                  {"issue_type": "safety_concern", "description": text[:180], "urgency": "emergency"}),
            _step("medical-human", 2, "紧急转人工安全专员", "transfer_to_human", tool_meta,
                  {"reason": "safety_concern", "priority": "emergency", "summary": text[:180], "context_snapshot": snap}, ["medical-report"]),
            _step("medical-crm", 3, "客服 Agent 接管安全会话", "crm_agent", tool_meta,
                  {"skill_group": "pax_emergency" if mode == "Robotaxi 乘客" else "vehicle_emergency",
                   "transfer_context": {"upstream_step_id": "medical-human"}}, ["medical-human"]),
            _step("medical-call", 4, "SOS/急救呼叫", "emergency_call", tool_meta,
                  {"emergency_type": "medical", "auto_send_location": True}, ["medical-crm"]),
        ]
        return {"plan_summary": "医疗风险：登记 → 人工安全接管 → SOS 确认",
                "reply": "检测到可能的急性身体不适信号，已优先进入安全求助流程；SOS/急救呼叫需你确认后触发。",
                "safety_tip": "如出现失去意识、严重胸痛或呼吸困难等危急情况，应立即联系当地急救服务。", "steps": steps}

    if intent == "climate":
        steps = [_step("climate-set", 1, "调节空调至舒适温度", "set_climate", tool_meta,
                       {"zone": "all", "temperature": 22, "fan_speed": 2, "mode": "auto"})]
        return {"plan_summary": "座舱温度调节", "reply": "将空调调至 22℃ 自动模式。", "safety_tip": "无", "steps": steps}

    if intent == "commute":
        steps = [
            _step("commute-climate", 1, "关闭/降低空调", "set_climate", tool_meta, {"zone": "all", "mode": "off"}),
            _step("commute-ambient", 2, "关闭氛围模式", "set_ambient", tool_meta, {"scene": "off"}),
        ]
        return {"plan_summary": "抵达例程：关闭可逆座舱服务", "reply": "已识别抵达场景，将执行可逆的离车前座舱收尾。", "safety_tip": "离车前请检查随身物品与后排乘员。", "steps": steps}

    return {"clarify": True, "reply": "当前请求没有形成可安全执行的结构化计划，请补充具体目标。"}


def _status_for_ui(status: str) -> str:
    # V5 UI 原契约只认识四类；blocked_dependency 用 failed 显示，但保留 note。
    if status in {"done", "pending_confirm", "failed", "cancelled"}: return status
    if status == "degraded": return "done"
    return "failed"


def run_rule(text: str, mode: str, snap: dict, executor, tool_meta: dict, confirmed: bool = False,
             previous_calls: Optional[List[dict]] = None, intent_resolution: Optional[dict] = None,
             confirmed_grants: Optional[Dict[str, str]] = None) -> dict:
    trace = TraceRecorder()

    with trace.stage("intent.resolve") as box:
        resolution = intent_resolution or resolve_intent(text, snapshot=snap, mode=mode)
        box["output"] = f"{resolution.get('selected_label')} · {resolution.get('confidence')}% · margin {resolution.get('margin')}"
    if resolution.get("needs_clarification"):
        result = {"intent": "clarify", "risk_level": "L0", "plan_summary": "低置信输入：仅澄清，不执行工具",
                  "reply": clarification_reply(resolution), "steps": [], "calls": [], "pending_tools": [], "safety_tip": "无",
                  "intent_resolution": resolution}
        shield = {"algorithm": "ConstraintShield Planner", "version": "2.0.0", "selected_candidate": None,
                  "candidates": [], "principle": "低置信输入先澄清，禁止猜测后执行"}
        result["decision_ledger"] = build_ledger(resolution, shield, {"replans": [], "topology": {"nodes": 0, "cycles": 0, "order": []}}, trace.events)
        return result

    intent = resolution["selected"]
    with trace.stage("constraint.plan") as box:
        shield = plan_candidates(intent, text, snap, mode)
        feasible = [c for c in shield["candidates"] if c["feasible"]]
        box["output"] = f"{len(feasible)}/{len(shield['candidates'])} 候选通过硬约束；selected={shield.get('selected_candidate')}"

    if not shield.get("selected_candidate"):
        result = {"intent": intent, "risk_level": shield.get("risk_level", "L0"), "plan_summary": "所有自动候选均被硬约束拒绝",
                  "reply": "当前身份、状态或安全约束不允许自动执行该请求。请切换正确服务模式或转人工处理。",
                  "steps": [], "calls": [], "pending_tools": [], "safety_tip": "系统采用 fail-closed：没有安全可行候选时不执行。",
                  "intent_resolution": resolution, "constraint_shield": shield}
        result["decision_ledger"] = build_ledger(resolution, shield, {"replans": [], "topology": {"nodes": 0, "cycles": 0, "order": []}}, trace.events)
        return result

    plan = _plan_for(intent, text, mode, snap, tool_meta)
    if plan.get("clarify"):
        result = {"intent": intent, "risk_level": shield.get("risk_level", "L0"), "plan_summary": "语义参数不足：执行前澄清",
                  "reply": plan["reply"], "steps": [], "calls": [], "pending_tools": [], "safety_tip": "无",
                  "intent_resolution": resolution, "constraint_shield": shield}
        result["decision_ledger"] = build_ledger(resolution, shield, {"replans": [], "topology": {"nodes": 0, "cycles": 0, "order": []}}, trace.events)
        return result

    with trace.stage("plan.toposort_execute") as box:
        try:
            execution = execute_plan(plan["steps"], executor, snap, confirmed=confirmed, tool_meta=tool_meta,
                                     previous_calls=previous_calls, confirmed_grants=confirmed_grants)
        except DependencyError as e:
            execution = {"steps": [], "calls": list(previous_calls or []), "pending_tools": [], "replans": [],
                         "topology": {"nodes": len(plan["steps"]), "cycles": 1, "order": []}, "planner_error": str(e)}
        box["output"] = f"nodes={execution['topology'].get('nodes')} cycles={execution['topology'].get('cycles')} replans={len(execution.get('replans', []))}"

    steps = execution.get("steps", [])
    # UI 兼容：保留真实 status_raw，同时映射旧图标状态。
    for s in steps:
        s["status_raw"] = s.get("status")
        s["status"] = _status_for_ui(s.get("status", "failed"))

    reply = plan["reply"]
    if execution.get("replans"):
        reply += "\n\n部分工具发生真实执行故障，RecoveryMesh 已按策略降级/重规划；失败节点仍保留在审计链中。"
    if any(s.get("status_raw") == "blocked_dependency" for s in steps):
        reply += "\n\n部分下游步骤因上游失败被自动阻断，没有继续执行。"

    result = {"intent": intent, "risk_level": shield.get("risk_level", "L0"), "plan_summary": plan["plan_summary"],
              "reply": reply, "steps": steps, "calls": execution.get("calls", []),
              "pending_tools": execution.get("pending_tools", []), "safety_tip": plan.get("safety_tip", "无"),
              "intent_resolution": resolution, "constraint_shield": shield,
              "resilience": {"algorithm": "RecoveryMesh", "version": "2.0.0",
                             "state": "degraded" if execution.get("replans") else "nominal",
                             "replans": execution.get("replans", [])},
              "topology": execution.get("topology", {})}
    result["decision_ledger"] = build_ledger(resolution, shield, execution, trace.events)

    run_id = getattr(executor, "run_id", None)
    if run_id:
        for event in trace.events:
            log_decision_event(run_id, event["stage"], {"output": event.get("output")}, event.get("duration_ms"))
        log_decision_event(run_id, "intent.snapshot", resolution)
        log_decision_event(run_id, "constraint.snapshot", shield)
        if execution.get("replans"):
            log_decision_event(run_id, "recovery.snapshot", {"replans": execution["replans"]})
    return result
