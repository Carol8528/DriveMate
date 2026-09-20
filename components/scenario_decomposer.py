# -*- coding: utf-8 -*-
"""ComplexScenarioDecomposer：把一句多目标自然语言拆解为子目标依赖图（DAG）。

单命令场景由 IntentGraph + rule_engine._plan_for 处理；当一句话同时包含
多个目标、信息不完整、动作有依赖或部分动作需要授权时，由本模块完成：

1. 目标拆解：从一句话中抽取并存的出行目标与硬约束
   （到达时间、电量安全、充电、用餐、儿童舒适、车内会议、临时下车…）；
2. 依赖编排：生成带依赖关系的执行链
   （状态读取 → 充裕性判断 → 资源匹配 → 可逆座舱动作 → 高风险写操作）；
3. 权限分层：可逆读取/座舱动作直接执行；路线、停车、解锁等高风险写操作
   保留 ConfirmationGrant 确认与执行前状态重检，理解不等于执行权限。

拆解结果仍交给 DependencyPlanner / ToolExecutor / SafetyGuard 的确定性链执行，
本模块本身不执行任何工具。
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional


SCENARIO_FAMILY_LONG_TRIP = "family_long_trip"
SCENARIO_AIRPORT_TRANSFER = "airport_transfer"
SCENARIO_ROBOTAXI_DROPOFF = "robotaxi_dropoff"

COMPLEX_SCENARIO_LABELS = {
    SCENARIO_FAMILY_LONG_TRIP: "家庭长途出行",
    SCENARIO_AIRPORT_TRANSFER: "赶飞机行程",
    SCENARIO_ROBOTAXI_DROPOFF: "临时安全下车",
}

_GOAL_PATTERNS = {
    "deadline": r"[一二两三四五六七八九十\d]{1,2}\s*点(半|[一二三四五六七八九十\d]{1,2}\s*分?)?(前|之前)?(到|前到|到达)|别.*迟到|赶得上|来得及",
    "child_comfort": r"孩子|儿童|宝宝|小朋友|晕车",
    "energy_safety": r"没电|电量|续航|充电|补能|跑不到",
    "dining": r"吃个饭|吃饭|用餐|吃点东西|服务区.*吃",
    "meeting": r"开个会|开会|会议|电话会",
    "smooth_route": r"平稳|稳一点|稳一些|别.*颠|舒适.*路线",
    "airport": r"机场|航班|飞机|赶飞机",
    "dropoff": r"下车|放我下来|就地停车",
}

_CN_DIGIT = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}


def _cn_number(token: str) -> Optional[int]:
    token = str(token or "").strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if "十" in token:
        left, _, right = token.partition("十")
        tens = _CN_DIGIT.get(left, 1) if left else 1
        ones = _CN_DIGIT.get(right, 0) if right else 0
        return tens * 10 + ones
    return _CN_DIGIT.get(token)


def extract_deadline(text: str) -> Optional[str]:
    """把“下午五点前到 / 六点半的航班”解析为 24 小时制 HH:MM，无法确定时返回 None。"""
    m = re.search(
        r"(上午|下午|晚上|早上|中午|凌晨)?\s*([一二两三四五六七八九十\d]{1,2})\s*点\s*(半|([一二两三四五六七八九十\d]{1,2})\s*分?)?",
        text,
    )
    if not m:
        return None
    hour = _cn_number(m.group(2))
    if hour is None or hour > 24:
        return None
    minute = 0
    if m.group(3) == "半":
        minute = 30
    elif m.group(4):
        minute = _cn_number(m.group(4)) or 0
    meridiem = m.group(1)
    if meridiem in {"下午", "晚上"} and hour < 12:
        hour += 12
    elif meridiem == "中午" and hour < 12:
        hour = 12 if hour == 12 else hour
    if hour >= 24 or minute >= 60:
        return None
    return f"{hour:02d}:{minute:02d}"


def extract_destination(text: str, snapshot: Dict[str, Any]) -> Optional[str]:
    patterns = [
        r"(?:去|到|前往)\s*([一-龥A-Za-z0-9]{2,12}?)(?:[，。；,;]|吧|$|\s)",
        r"(?:改|换)(?:一下|个)?目的地(?:到|去|为)?\s*([一-龥A-Za-z0-9]{2,12})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            value = m.group(1).strip(" ，。吧")
            if value and value not in {"机场方向"}:
                return value
    if re.search(r"机场|航班|赶飞机", text):
        return "机场"
    order = snapshot.get("order_state") or {}
    value = str(order.get("destination") or "").strip()
    return value or None


def _goal_hit(text: str, goal: str) -> Optional[str]:
    m = re.search(_GOAL_PATTERNS[goal], text)
    return m.group(0) if m else None


def _make_step(sid: str, seq: int, title: str, tool: str, tool_meta: dict, arguments=None,
               depends_on=None, refresh_on_confirm: bool = False) -> dict:
    return {"id": sid, "seq": seq, "title": title, "tool": tool,
            "arguments": arguments or {}, "depends_on": depends_on or [],
            "refresh_on_confirm": refresh_on_confirm,
            "status": "planned", "safety_level": tool_meta.get(tool, {}).get("level", "L0"), "note": ""}


def decompose_scenario(text: str, snapshot: Dict[str, Any], mode: str) -> Optional[Dict[str, Any]]:
    """识别一句话中的多目标复杂场景；无法匹配时返回 None（走单意图链）。

    返回结构：{scenario_id, label, goals, constraints, primary_intent}
    goals 为 [{id, label, evidence}]，约束放入 constraints 供规划器使用。
    """
    driver = mode == "车主自驾"
    hits = {goal: _goal_hit(text, goal) for goal in _GOAL_PATTERNS}
    hits = {goal: phrase for goal, phrase in hits.items() if phrase}

    if not driver:
        # 复杂场景 4：Robotaxi 乘客要求提前/就地停车下车。
        dropoff_request = hits.get("dropoff")
        stop_here = re.search(r"就(在)?这(里|儿)停|靠边停|停一下|不用到目的地|不到目的地|不去了", text)
        if dropoff_request and (stop_here or re.search(r"这里|这儿|现在|马上|提前", text)):
            goals = [
                {"id": "end_trip", "label": "提前结束行程", "evidence": (stop_here.group(0) if stop_here else dropoff_request)},
                {"id": "safe_stop", "label": "找到安全停车点", "evidence": dropoff_request},
                {"id": "curbside_check", "label": "开门前环境安全检查", "evidence": "确定性前置条件"},
                {"id": "unlock_door", "label": "解锁车门下车", "evidence": dropoff_request},
            ]
            return {
                "scenario_id": SCENARIO_ROBOTAXI_DROPOFF,
                "label": COMPLEX_SCENARIO_LABELS[SCENARIO_ROBOTAXI_DROPOFF],
                "goals": goals,
                "constraints": {"door_side": "right"},
                "primary_intent": SCENARIO_ROBOTAXI_DROPOFF,
            }
        return None

    # 复杂场景 2：赶飞机（航班/机场 + 时间/会议/平稳任一约束）。
    if hits.get("airport") and any(hits.get(k) for k in ("deadline", "meeting", "smooth_route")):
        destination = extract_destination(text, snapshot) or "机场"
        constraints: Dict[str, Any] = {"destination": destination}
        deadline = extract_deadline(text)
        if deadline:
            constraints["arrive_by"] = deadline
        goals = [{"id": "arrive_on_time",
                  "label": "按时到达" + (f"（{constraints['arrive_by']} 前）" if constraints.get("arrive_by") else "（航班时间）"),
                  "evidence": hits.get("deadline") or hits["airport"]}]
        if hits.get("meeting"):
            goals.append({"id": "meeting_mode", "label": "车内会议环境", "evidence": hits["meeting"]})
        if hits.get("smooth_route"):
            goals.append({"id": "smooth_route", "label": "平稳路线偏好", "evidence": hits["smooth_route"]})
        goals.append({"id": "energy_aware", "label": "电量与能耗持续评估", "evidence": "状态约束"})
        return {
            "scenario_id": SCENARIO_AIRPORT_TRANSFER,
            "label": COMPLEX_SCENARIO_LABELS[SCENARIO_AIRPORT_TRANSFER],
            "goals": goals,
            "constraints": constraints,
            "primary_intent": SCENARIO_AIRPORT_TRANSFER,
        }

    # 复杂场景 1：家庭长途出行（目的地 + 多个并存目标）。
    destination = extract_destination(text, snapshot)
    multi = [k for k in ("child_comfort", "energy_safety", "dining", "deadline") if hits.get(k)]
    long_trip = re.search(r"长途|出去玩|旅游|自驾", text)
    if destination and (len(multi) >= 2 or (long_trip and multi)):
        constraints = {"destination": destination}
        deadline = extract_deadline(text)
        if deadline:
            constraints["arrive_by"] = deadline
        goal_labels = {
            "deadline": "按时到达" + (f"（{deadline} 前）" if deadline else ""),
            "energy_safety": "电量安全",
            "dining": "途中用餐安排",
            "child_comfort": "儿童乘坐舒适",
        }
        goals = [{"id": key, "label": goal_labels[key], "evidence": hits[key]} for key in
                 ("deadline", "energy_safety", "dining", "child_comfort") if hits.get(key)]
        goals.append({"id": "driving_safety", "label": "驾驶安全", "evidence": "全局约束"})
        return {
            "scenario_id": SCENARIO_FAMILY_LONG_TRIP,
            "label": COMPLEX_SCENARIO_LABELS[SCENARIO_FAMILY_LONG_TRIP],
            "goals": goals,
            "constraints": constraints,
            "primary_intent": SCENARIO_FAMILY_LONG_TRIP,
        }
    return None


def build_complex_plan(decomposition: Dict[str, Any], text: str, mode: str, snap: Dict[str, Any],
                       tool_meta: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """把拆解结果编译为 DependencyPlanner 可执行的 DAG（不执行任何工具）。"""
    scenario = decomposition["scenario_id"]
    constraints = decomposition.get("constraints") or {}
    builder: Callable[[], Dict[str, Any]] = {
        SCENARIO_FAMILY_LONG_TRIP: lambda: _family_long_trip_plan(constraints, snap, tool_meta),
        SCENARIO_AIRPORT_TRANSFER: lambda: _airport_transfer_plan(constraints, snap, tool_meta),
        SCENARIO_ROBOTAXI_DROPOFF: lambda: _robotaxi_dropoff_plan(text, snap, tool_meta),
    }[scenario]
    plan = builder()
    plan["scenario_decomposition"] = {
        "scenario_id": scenario,
        "label": decomposition["label"],
        "goals": decomposition["goals"],
        "constraints": constraints,
    }
    return plan


def _family_long_trip_plan(constraints: Dict[str, Any], snap: Dict[str, Any], tool_meta: dict) -> Dict[str, Any]:
    destination = str(constraints.get("destination") or "").strip()
    if not destination:
        return {"clarify": True, "reply": "已识别家庭长途出行需求，但缺少目的地。请补充要去哪里。"}
    arrive_by = constraints.get("arrive_by")
    route_args: Dict[str, Any] = {
        "destination": destination,
        "waypoints": [{"$from": "lt-charge", "path": "stations.0.station_id"}],
        "preference": "fastest",
    }
    if arrive_by:
        route_args["arrive_by"] = arrive_by
    steps = [
        _make_step("lt-health", 1, "读取车辆状态与预计续航", "get_vehicle_health", tool_meta, refresh_on_confirm=True),
        _make_step("lt-range", 2, "估算可达里程与补能需求", "estimate_range_sufficiency", tool_meta,
                   {"destination": destination, "reserve_percent": 15}, ["lt-health"]),
        _make_step("lt-charge", 3, "寻找沿途充电+用餐合并节点", "find_charging_station", tool_meta,
                   {"along_route": True, "distance_max": 80, "amenities": ["restaurant"]}, ["lt-range"], True),
        _make_step("lt-dining", 4, "匹配休息/用餐点", "find_rest_area", tool_meta,
                   {"radius_km": 50, "along_route": True, "facilities": ["restaurant", "parking"]}, ["lt-range"]),
        _make_step("lt-child", 5, "读取儿童/后排状态", "detect_child_presence", tool_meta, refresh_on_confirm=True),
        _make_step("lt-child-climate", 6, "儿童防晕车座舱（后排温度与柔和风量）", "set_climate", tool_meta,
                   {"zone": "rear", "temperature": 24, "fan_speed": 1, "mode": "auto"}, ["lt-child"]),
        _make_step("lt-child-media", 7, "播放儿童舒缓内容", "play_media", tool_meta,
                   {"source": "儿童歌单", "genre": "children", "volume": 26}, ["lt-child"]),
        _make_step("lt-route", 8, "生成最终路线（含补能/用餐途经点）", "plan_route", tool_meta,
                   route_args, ["lt-charge", "lt-dining"]),
        _make_step("lt-reserve", 9, "预约快充桩", "reserve_charging", tool_meta,
                   {"station_id": {"$from": "lt-charge", "path": "stations.0.station_id"}}, ["lt-charge"]),
    ]
    deadline_note = f"、{arrive_by} 前到达的时间约束" if arrive_by else ""
    return {
        "plan_summary": "家庭长途：状态读取 → 续航估算 → 充电/用餐合并节点 → 儿童座舱 → 最终路线确认",
        "reply": (
            f"已把这句需求拆解为多个并存目标：按时到达{deadline_note}、电量安全、充电安排、途中用餐、儿童乘坐舒适与驾驶安全。"
            "执行链：读取车辆状态 → 估算可达里程 → 规划主路线 → 锁定充电与用餐合并节点 → 调整儿童友好座舱 → 生成最终路线。"
            "其中路线导航与充电预约属于行程变更，需你确认后执行；确认前会重新校验车况与充电资源。"
        ),
        "safety_tip": "儿童应使用适龄约束系统；充电/用餐停靠时请确认车辆停稳后再照顾后排儿童。",
        "steps": steps,
    }


def _airport_transfer_plan(constraints: Dict[str, Any], snap: Dict[str, Any], tool_meta: dict) -> Dict[str, Any]:
    destination = str(constraints.get("destination") or "机场").strip() or "机场"
    arrive_by = constraints.get("arrive_by")
    route_args: Dict[str, Any] = {"destination": destination, "preference": "comfort"}
    if arrive_by:
        route_args["arrive_by"] = arrive_by
    steps = [
        _make_step("ap-health", 1, "读取车辆状态与续航", "get_vehicle_health", tool_meta, refresh_on_confirm=True),
        _make_step("ap-range", 2, "评估机场行程续航与能耗", "estimate_range_sufficiency", tool_meta,
                   {"destination": destination, "reserve_percent": 20}, ["ap-health"]),
        _make_step("ap-meeting-climate", 3, "座舱会议模式（低噪空调）", "set_climate", tool_meta,
                   {"zone": "all", "temperature": 23, "fan_speed": 1, "mode": "auto"}),
        _make_step("ap-meeting-ambient", 4, "切换专注会议氛围", "set_ambient", tool_meta, {"scene": "focus"}),
        _make_step("ap-route", 5, f"规划平稳机场路线（{arrive_by or '按航班时间'} 前到达）", "plan_route", tool_meta,
                   route_args, ["ap-range"]),
    ]
    return {
        "plan_summary": "赶飞机：状态/续航评估 → 会议座舱 → 平稳路线（时间约束）确认",
        "reply": (
            f"已识别并存约束：目的地 {destination}、{arrive_by or '航班'} 前到达、路线平稳优先、车内会议环境。"
            "系统先评估续航与能耗，再把座舱切换为低噪会议模式；最终路线按“平稳优先”生成，"
            "若途中出现拥堵或电量不足会重新计算整个任务链而不是单独改一个动作。路线变更需确认后执行。"
        ),
        "safety_tip": "车内会议请使用免提；如续航评估不足，系统会优先给出最小绕行补能方案而不是牺牲到达时间。",
        "steps": steps,
    }


def _robotaxi_dropoff_plan(text: str, snap: Dict[str, Any], tool_meta: dict) -> Dict[str, Any]:
    v = snap.get("vehicle_state") or {}
    speed = float(v.get("speed_kmh") or 0)
    steps = [
        _make_step("do-order", 1, "读取订单与车辆实时状态", "get_order_status", tool_meta, refresh_on_confirm=True),
        _make_step("do-stop-point", 2, "寻找安全停车点", "find_safe_stop_point", tool_meta,
                   {"reason": "passenger_request"}, ["do-order"], True),
        _make_step("do-stop", 3, "减速靠边并停稳", "request_curbside_stop", tool_meta,
                   {"stop_point": {"$from": "do-stop-point", "path": "candidate"},
                    "reason": "passenger_request"}, ["do-stop-point"]),
        _make_step("do-check", 4, "开门前右侧环境安全检查", "check_curbside_safety", tool_meta,
                   {"side": "right"}, ["do-stop"], True),
        _make_step("do-unlock", 5, "解锁右侧车门", "unlock_door", tool_meta,
                   {"door": "right_rear", "reason": "passenger_dropoff"}, ["do-check"]),
    ]
    return {
        "plan_summary": "临时下车：安全停车点 → 靠边停稳 → 开门前状态重检 → 确认解锁",
        "reply": (
            f"理解你想尽快下车（当前车速 {speed:g} km/h），但“听懂了”不等于“直接开门”。"
            "拆解后的执行链：寻找安全停车点 → 减速靠边停稳 → 检查右侧环境 → 才允许解锁车门。"
            "解锁必须满足确定性条件：车速为 0、档位 P、路边环境安全、车辆状态有效；"
            "停车与解锁会分步请你确认，确认前会重新读取实时状态，状态变化时旧授权自动作废。"
        ),
        "safety_tip": "请勿在车辆未停稳或右侧有来车/非机动车时开门；禁止临停区域不会执行就地停车。",
        "steps": steps,
    }
