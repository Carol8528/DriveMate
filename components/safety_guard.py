# -*- coding: utf-8 -*-
"""工具执行前的硬安全闸门：模式权限、L2 确认、闪灯鸣笛真实距离校验。"""
import math
from typing import Dict, Any, Tuple


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _coords(snap: Dict[str, Any], key: str):
    o = snap.get("order_state") or {}
    point = o.get(key) or {}
    try:
        return float(point["lat"]), float(point["lng"])
    except (KeyError, TypeError, ValueError):
        return None


def authorize_tool(name: str, meta: Dict[str, Any], snap: Dict[str, Any], confirmed: bool) -> Tuple[bool, str, Dict[str, Any]]:
    identity = snap.get("identity") or {}
    mode = identity.get("mode")
    domain = meta.get("domain", "both")

    if domain == "owner" and mode != "OWNER_DRIVE":
        return False, "当前身份无车辆控制权限。", {}
    if domain == "robotaxi" and mode != "ROBOTAXI_RIDE":
        return False, "当前身份无 Robotaxi 订单控制权限。", {}

    # L2 一律强制确认；不能依赖模型或单个 Schema 是否遗漏 requires_confirmation。
    if (meta.get("level") == "L2" or meta.get("confirm")) and not confirmed:
        return False, "该操作要求用户强制确认，当前尚未确认。", {"status": "pending_user_confirmation"}

    if name == "contact_vehicle":
        p = _coords(snap, "passenger_coordinates")
        v = _coords(snap, "vehicle_coordinates")
        if not p or not v:
            return False, "缺少乘客/车辆实时经纬度，禁止执行闪灯鸣笛。", {"distance_verified": False}
        distance = haversine_m(p[0], p[1], v[0], v[1])
        if distance > 100.0:
            return False, "车辆距离乘客 %.1f 米，超过 100 米安全限制。" % distance, {
                "distance_verified": True, "distance_m": round(distance, 1), "limit_m": 100.0
            }
        return True, "ok", {"distance_verified": True, "distance_m": round(distance, 1), "limit_m": 100.0}

    if name == "request_curbside_stop":
        controls = snap.get("perception_controls") or {}
        env = snap.get("environment_state") or {}
        parking = str(env.get("parking_policy") or "")
        try:
            curb = float(controls.get("curb_risk"))
        except (TypeError, ValueError):
            curb = None
        if curb is not None and curb > 60:
            return False, "路缘风险 %.0f%% 超过 60%% 阈值，禁止在当前位置靠边停车。" % curb, {
                "status": "safety_blocked", "curb_side_safe": False}
        if any(k in parking for k in ("禁停", "禁止", "不允许")):
            return False, "当前区域禁止临停，禁止在此靠边停车。", {
                "status": "safety_blocked", "curb_side_safe": False}
        return True, "ok", {"curb_side_safe": True}

    if name == "unlock_door":
        # 确定性前置条件：speed == 0 AND gear == P AND curb_side_safe AND vehicle_state_valid。
        # 理解用户意图不构成执行授权；此处只认最新 StateSnapshot。
        v = snap.get("vehicle_state") or {}
        env = snap.get("environment_state") or {}
        controls = snap.get("perception_controls") or {}
        blockers = []
        try:
            speed = float(v.get("speed_kmh"))
        except (TypeError, ValueError):
            speed = None
        if speed is None:
            blockers.append("车辆状态无效：缺少车速读数")
        elif speed != 0:
            blockers.append("车速 %.1f km/h 未归零" % speed)
        gear = str(v.get("gear") or ("P" if speed == 0 else ""))
        if gear != "P":
            blockers.append("档位未处于 P 档")
        try:
            curb = float(controls.get("curb_risk"))
        except (TypeError, ValueError):
            curb = None
        if curb is None:
            blockers.append("缺少路缘安全读数")
        elif curb > 60:
            blockers.append("路缘风险 %.0f%% 超过安全阈值" % curb)
        parking = str(env.get("parking_policy") or "")
        if any(k in parking for k in ("禁停", "禁止", "不允许")):
            blockers.append("当前区域禁止临停")
        if blockers:
            return False, "开门硬条件不满足：" + "；".join(blockers), {
                "status": "safety_blocked", "curb_side_safe": False,
                "speed_kmh": speed, "gear": gear, "vehicle_state_valid": speed is not None}
        return True, "ok", {"curb_side_safe": True, "speed_kmh": speed, "gear": gear,
                            "vehicle_state_valid": True}

    return True, "ok", {}
