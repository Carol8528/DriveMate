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

    return True, "ok", {}
