# -*- coding: utf-8 -*-
"""统一工具执行层。

执行顺序固定为：SchemaValidator → 同运行幂等去重 → SafetyGuard → 真实/本地后端 → 审计。
真实座舱控制走 HTTP 模拟器；失败不得伪造成功。
"""
import hashlib
import json
import time
import uuid
from typing import Dict, Any, Optional

from components.audit_store import (
    get_idempotency_result,
    get_latest_successful_tool_result,
    log_tool_call,
    put_idempotency_result,
)
from components.schema_validator import validate_arguments
from components.safety_guard import authorize_tool
from components.vehicle_gateway import VehicleGateway, TOOL_ENDPOINTS
from components.crm_agent import create_crm_ticket
from perception_fusion import resolve_pedestrian_distance_m


class ToolExecutor:
    def __init__(self, tool_meta: Dict[str, Dict[str, Any]], run_id: Optional[str] = None):
        self.tool_meta = tool_meta
        self.run_id = run_id
        self.gateway = VehicleGateway()

    def _execution_key(self, name: str, args: Dict[str, Any]) -> str:
        payload = json.dumps({"run_id": self.run_id or "no-run", "tool": name, "arguments": args or {}},
                             ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _call_record(self, name, args, result, latency_ms=None):
        meta = self.tool_meta.get(name, {})
        call = {
            "tool": name,
            "level": meta.get("level", "L0"),
            "result": "success" if result.get("success") else result.get("status", "failed"),
            "summary": result.get("summary", ""),
            "latency_ms": result.get("latency_ms", latency_ms),
            "arguments": args or {},
            "backend": result.get("backend", "local_service"),
            "receipt_id": result.get("receipt_id"),
            "idempotent": bool(meta.get("idempotent", False)),
            "idempotency_replayed": bool(result.get("idempotency_replayed", False)),
            "raw_result": result,
        }
        log_tool_call(self.run_id, call)
        return call

    def execute(self, name: str, args: Dict[str, Any], snap: Dict[str, Any], confirmed: bool = False,
                is_retry: bool = False, force_refresh: bool = False):
        meta = self.tool_meta.get(name)
        if not meta:
            result = {"success": False, "status": "unknown_tool", "summary": "未知工具，拒绝执行。", "backend": "tool_registry"}
            return result, self._call_record(name, args, result)

        validation = validate_arguments(args or {}, meta.get("parameters") or {})
        if not validation["valid"]:
            result = {"success": False, "status": "schema_invalid",
                      "summary": "工具参数未通过 SchemaValidator：" + "；".join(validation["errors"][:4]),
                      "backend": "schema_validator", "validation_errors": validation["errors"]}
            return result, self._call_record(name, args, result)

        # 同一 run 内精确相同的成功写操作/控制操作禁止二次执行；无论 Schema 是否声明 idempotent，
        # 都优先返回原可验证结果。idempotent 标志决定“失败后能否自动重试”，由 RecoveryMesh 使用。
        execution_key = self._execution_key(name, args or {})
        cached = None if force_refresh else get_idempotency_result(execution_key)
        if cached and cached.get("success"):
            replay = dict(cached)
            replay.update({"backend": "idempotency_replay", "idempotency_replayed": True,
                           "summary": "幂等去重：沿用本次 Run 内已验证结果；" + str(cached.get("summary", ""))})
            return replay, self._call_record(name, args, replay)

        allowed, reason, guard_ctx = authorize_tool(name, meta, snap, confirmed)
        if not allowed:
            result = {"success": False, "status": guard_ctx.get("status", "safety_blocked"), "summary": reason,
                      "backend": "safety_guard", **guard_ctx}
            return result, self._call_record(name, args, result)

        if name in TOOL_ENDPOINTS:
            result = self.gateway.execute(name, args, context=guard_ctx)
        else:
            t0 = time.perf_counter()
            result = self._execute_local(name, args, snap)
            result.setdefault("backend", "local_service")
            result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        if result.get("success"):
            put_idempotency_result(execution_key, self.run_id, name, args or {}, result)
        return result, self._call_record(name, args, result)

    def _execute_local(self, name: str, args: Dict[str, Any], snap: Dict[str, Any]):
        v, o, env = snap.get("vehicle_state", {}), snap.get("order_state", {}), snap.get("environment_state", {})
        ok = lambda summary, **extra: {"success": True, "status": "executed", "summary": summary, **extra}

        if name == "get_fatigue_status":
            idx = round(min(0.95, 0.12 + 0.18 * float(v.get("driving_hours", 0)) + (0.15 if env.get("time_of_day") == "夜间" else 0)), 2)
            lvl = "severe" if idx >= 0.75 else ("high" if idx >= 0.5 else ("medium" if idx >= 0.3 else "low"))
            return ok("DMS 疲劳指数 %.2f（%s）" % (idx, lvl), fatigue_index=idx, fatigue_level=lvl)
        if name == "suggest_safety_action":
            return ok("建议立即进入最近安全休息点并休息 20 分钟以上", suggested_action="rest_now")
        if name == "find_rest_area":
            dist = 12 if env.get("area_type") == "高速" else 4
            return ok("找到最近安全休息点，约 %s km" % dist, distance_km=dist, destination="最近安全服务区")
        if name == "get_vehicle_health":
            return ok("电量 %s%%，预估续航 %s km，无故障码" % (v.get("soc_percent"), v.get("range_km")), range_accuracy="high")
        if name == "find_charging_station":
            amenities = args.get("amenities") or []
            station = {"station_id": "cs_demo_01", "distance_km": 12, "idle_piles": 4}
            if "restaurant" in amenities:
                station["amenities"] = ["restaurant", "restroom"]
                station["restaurant"] = True
                return ok("沿途找到可叠加用餐的快充站（含餐饮配套）", stations=[station])
            return ok("沿途找到可用快充站", stations=[station])
        if name == "estimate_range_sufficiency":
            destination = str(args.get("destination") or "目的地")
            try:
                reserve = float(args.get("reserve_percent", 15))
            except (TypeError, ValueError):
                reserve = 15.0
            reserve = min(50.0, max(0.0, reserve))
            rng = float(v.get("range_km") or 0)
            distance = args.get("distance_km")
            estimated = False
            if distance is None:
                distance = float(o.get("distance_km") or 240)
                estimated = True
            distance = float(distance)
            usable = rng * (1 - reserve / 100)
            needs_charging = distance > usable
            summary = ("预计里程 %.0f km（演示估算），可用续航（保留 %.0f%% 电量）约 %.0f km，%s"
                       % (distance, reserve, usable, "需要途中补能" if needs_charging else "可直达"))
            return ok(summary, needs_charging=needs_charging, distance_km=distance,
                      usable_range_km=round(usable, 1), gap_km=round(distance - usable, 1),
                      estimated=estimated)
        if name == "reserve_charging":
            return ok("快充桩预约成功", reservation_id="RSV-" + uuid.uuid4().hex[:12])
        if name == "get_charging_status":
            return ok("充电进行中：62%，预计 18 分钟完成", battery_percent=62)
        if name == "detect_child_presence":
            found = bool(v.get("child_seat_detected"))
            return ok("检测到儿童座椅" if found else "未检测到儿童座椅", child_detected=found)
        if name == "get_order_status":
            distance = resolve_pedestrian_distance_m(snap)
            return ok("订单状态 %s%s" % (o.get("status", "未知"), ("；车辆距乘客 %.1f 米" % distance) if distance is not None else "；实时距离不可用"), distance_m=distance)
        if name == "share_vehicle_location":
            return ok("已生成车辆位置引导", share_ref="AR-DEMO")
        if name == "find_safe_pickup_point":
            q = o.get("vehicle_coordinates") or {}
            try:
                lat, lng = float(q.get("lat")), float(q.get("lng"))
            except Exception:
                return {"success": False, "status": "invalid_state", "summary": "缺少车辆实时坐标，无法生成可复核替代上车点。"}
            candidate = {"lat": round(lat + 0.00045, 6), "lng": round(lng + 0.00012, 6),
                         "address": "前方合规临停点（演示道路策略）"}
            return ok("找到约 50-80 米内的合规替代上车点", candidate=candidate, policy="allow", walk_m=68)
        if name == "find_safe_stop_point":
            q = o.get("vehicle_coordinates") or {}
            try:
                lat, lng = float(q.get("lat")), float(q.get("lng"))
            except Exception:
                return {"success": False, "status": "invalid_state", "summary": "缺少车辆实时坐标，无法确定安全停车点。"}
            controls = snap.get("perception_controls") or {}
            parking = str(env.get("parking_policy") or "")
            try:
                curb = float(controls.get("curb_risk"))
            except (TypeError, ValueError):
                curb = None
            current_safe = (curb is None or curb <= 60) and not any(k in parking for k in ("禁停", "禁止", "不允许"))
            if current_safe:
                candidate = {"lat": round(lat, 6), "lng": round(lng, 6), "address": "当前位置（合规临停区）"}
                return ok("当前位置满足安全停靠条件", candidate=candidate, curb_side_safe=True)
            candidate = {"lat": round(lat + 0.0005, 6), "lng": round(lng + 0.00014, 6),
                         "address": "前方约 80 米合规临停点（演示道路策略）"}
            return ok("当前位置不允许临停，已找到前方合规停车点", candidate=candidate, curb_side_safe=False)
        if name == "check_curbside_safety":
            controls = snap.get("perception_controls") or {}
            blockers = []
            try:
                speed = float(v.get("speed_kmh"))
            except (TypeError, ValueError):
                speed = None
            if speed is None:
                blockers.append("缺少车速读数")
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
                blockers.append("路缘风险 %.0f%%（右侧可能有来车/非机动车）" % curb)
            parking = str(env.get("parking_policy") or "")
            if any(k in parking for k in ("禁停", "禁止", "不允许")):
                blockers.append("当前区域禁止临停")
            side = str(args.get("side") or "right")
            if blockers:
                return ok("开门前安全检查未通过：" + "；".join(blockers),
                          curb_side_safe=False, side=side, blockers=blockers,
                          speed_kmh=speed, gear=gear)
            return ok("开门前安全检查通过：车速 0、档位 P、路边环境安全",
                      curb_side_safe=True, side=side, blockers=[], speed_kmh=speed, gear=gear)
        if name == "modify_pickup_point":
            return ok("新上车点已通过演示可停靠性校验并更新", approved=True, new_location=args.get("new_location"))
        if name == "modify_destination":
            return ok("Robotaxi 订单目的地已更新", destination=args.get("destination"), waypoints=args.get("waypoints") or [], fee_delta=0.0)
        if name == "cancel_order":
            return ok("订单已取消，取消费 3 元", cancelled=True, cancellation_fee=3.0)
        if name == "report_issue":
            return ok("安全求助工单已登记", ticket_id="ISS-" + uuid.uuid4().hex[:12])
        if name == "crm_agent":
            transfer_receipt = (
                get_latest_successful_tool_result(self.run_id, "transfer_to_human")
                if self.run_id else None
            )
            if not transfer_receipt or not transfer_receipt.get("ticket_id"):
                return {"success": False, "status": "missing_transfer", "summary": "缺少已创建的转接工单，拒绝伪造客服接管。"}
            session_id = "CRM-" + uuid.uuid4().hex[:12]
            return ok("客服 Agent 已接管会话并登记审计链", agent_session_id=session_id,
                      ticket_id=transfer_receipt["ticket_id"], skill_group=args.get("skill_group", "other"))
        if name == "transfer_to_human":
            priority = str(args.get("priority", "normal")).lower()
            risk = {"emergency": "L3", "urgent": "L2", "normal": "L1"}.get(priority, "L1")
            ticket = create_crm_ticket(user_id="demo_user", mode="车主自驾" if snap.get("identity", {}).get("mode") == "OWNER_DRIVE" else "Robotaxi 乘客",
                                       risk_level=risk, reason=args.get("summary") or args.get("reason") or "转人工",
                                       recent_messages=[], snapshot=args.get("context_snapshot") or snap, run_id=self.run_id)
            return ok("已创建人工客服工单 %s" % ticket["ticket_id"], ticket_id=ticket["ticket_id"], queue=ticket["queue"])
        if name == "emergency_call":
            return ok("已向演示安全中心发送 SOS 请求", call_connected=True, rescue_eta_minutes=15)
        return {"success": False, "status": "not_implemented", "summary": "%s 尚未接入执行服务" % name}
