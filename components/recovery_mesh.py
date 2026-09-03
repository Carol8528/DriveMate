# -*- coding: utf-8 -*-
"""RecoveryMesh 2.0：真实失败分类、幂等重试策略、降级工具与重规划记录。"""
from __future__ import annotations
from typing import Any, Dict, Optional

TRANSIENT = {"backend_unreachable", "timeout", "unavailable", "invalid_response", "http_5xx"}

# fallback 仅使用 V5 中真实存在的工具；不把失败伪造成成功。
FALLBACKS = {
    "contact_vehicle": {"tool": "share_vehicle_location", "policy_id": "XC-RES-01", "reason": "闪灯鸣笛不可用时退化为位置/AR 引导"},
    "plan_route": {"tool": "transfer_to_human", "policy_id": "XC-RES-02", "reason": "导航执行不可验证时冻结行程变更并转人工"},
    "find_rest_area": {"tool": "transfer_to_human", "policy_id": "XC-RES-03", "reason": "休息点查询失败时由人工提供安全停车支持"},
    "find_charging_station": {"tool": "transfer_to_human", "policy_id": "XC-RES-04", "reason": "补能资源查询失败时转人工核验"},
    "reserve_charging": {"tool": "transfer_to_human", "policy_id": "XC-RES-05", "reason": "资源占用操作失败后不自动重复预约，转人工核验"},
    "get_order_status": {"tool": "transfer_to_human", "policy_id": "XC-RES-06", "reason": "订单状态不可验证时冻结订单写操作并转人工"},
    "find_safe_pickup_point": {"tool": "transfer_to_human", "policy_id": "XC-RES-07A", "reason": "安全上车点查询失败时转人工道路复核"},
    "modify_pickup_point": {"tool": "transfer_to_human", "policy_id": "XC-RES-07", "reason": "改点失败后不重复写订单，转人工处理"},
    "modify_destination": {"tool": "transfer_to_human", "policy_id": "XC-RES-07B", "reason": "目的地变更失败后不自动重复写订单，转人工核验"},
    "cancel_order": {"tool": "transfer_to_human", "policy_id": "XC-RES-08", "reason": "取消失败后禁止自动二次提交，转人工核验订单状态"},
    "set_climate": None,
    "set_seat": None,
    "play_media": None,
    "set_ambient": None,
}


def classify_failure(result: Dict[str, Any]) -> str:
    status = str(result.get("status") or "failed").lower()
    if status in {"backend_unreachable", "auth_missing", "unauthorized", "invalid_arguments", "schema_invalid", "safety_blocked", "permission_denied"}:
        return status
    if "timeout" in status: return "timeout"
    if result.get("success") is False and result.get("backend") == "simulator_http" and status == "failed": return "unavailable"
    return status or "failed"


def recovery_decision(tool: str, result: Dict[str, Any], idempotent: bool, retry_count: int = 0) -> Dict[str, Any]:
    failure_type = classify_failure(result)
    # 只有 Schema 声明 idempotent 的工具才允许对瞬态故障自动重试，且最多一次。
    if idempotent and failure_type in TRANSIENT and retry_count < 1:
        return {"action": "retry", "retry": True, "failure_type": failure_type,
                "policy_id": "XC-RES-RETRY", "reason": "工具声明 idempotent 且发生瞬态故障，允许一次安全重试"}
    fallback = FALLBACKS.get(tool)
    if fallback:
        return {"action": "fallback", "retry": False, "failure_type": failure_type, **fallback}
    return {"action": "stop", "retry": False, "failure_type": failure_type,
            "policy_id": "XC-RES-STOP", "reason": "没有等价安全降级工具；保留失败并停止依赖分支"}


def fallback_arguments(failed_tool: str, fallback_tool: str, snapshot: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    if fallback_tool == "share_vehicle_location":
        return {"share_method": "ar_guide"}
    if fallback_tool == "transfer_to_human":
        return {"reason": "technical_issue", "priority": "urgent",
                "summary": f"工具 {failed_tool} 执行失败：{result.get('summary', '')}",
                "context_snapshot": snapshot}
    return {}
