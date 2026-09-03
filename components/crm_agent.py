# -*- coding: utf-8 -*-
"""客服 CRM 组件：默认使用本地持久化工单；配置真实端点时可转发到 CRM API。"""
import os
import uuid
from datetime import datetime, timedelta

import requests

from components.audit_store import log_ticket


CRM_CONFIG = {
    "api_endpoint": os.environ.get("CRM_API_ENDPOINT", "").strip(),
    "api_key": os.environ.get("CRM_API_KEY", "").strip(),
    "response_time_sla_minutes": {"L3": 1, "L2": 5, "L1": 30, "L0": 120},
}


class CRMAgent:
    QUEUE_MAP = {
        "车主自驾": {"L3": "vehicle_emergency", "L2": "vehicle_urgent", "L1": "vehicle_general", "L0": "vehicle_general"},
        "Robotaxi 乘客": {"L3": "pax_emergency", "L2": "pax_order_urgent", "L1": "pax_order_general", "L0": "pax_order_general"},
    }

    def __init__(self, config=None):
        self.cfg = config or CRM_CONFIG

    def _determine_queue(self, mode, risk_level, category):
        queue = self.QUEUE_MAP.get(mode, self.QUEUE_MAP["车主自驾"]).get(risk_level, "general")
        if category == "payment":
            return "payment"
        if category == "complaint":
            return "complaint"
        if category == "emergency":
            return "emergency"
        return queue

    def _categorize(self, reason, recent_messages):
        texts = [reason or ""] + [str(m.get("content", "")) for m in (recent_messages or [])[-5:] if isinstance(m, dict)]
        text = " ".join(texts).lower()
        if any(k in text for k in ["退款", "扣款", "支付", "费用", "收费"]):
            return "payment"
        if any(k in text for k in ["投诉", "不满", "赔偿"]):
            return "complaint"
        if any(k in text for k in ["报警", "危险", "威胁", "急病", "受伤", "车祸", "碰撞", "sos"]):
            return "emergency"
        if any(k in text for k in ["找不到车", "等车", "上车点", "订单", "行程"]):
            return "order"
        if any(k in text for k in ["故障", "报警灯", "胎压", "续航", "充电", "车辆"]):
            return "vehicle"
        return "general"

    def create_ticket(self, user_id, order_id="", mode="车主自驾", risk_level="L0", reason="",
                      recent_messages=None, snapshot=None, run_id=None):
        category = self._categorize(reason, recent_messages)
        queue = self._determine_queue(mode, risk_level, category)
        sla = self.cfg["response_time_sla_minutes"].get(risk_level, 120)
        now = datetime.now().astimezone()
        ticket = {
            "success": True,
            "user_id": user_id,
            "order_id": order_id or "",
            "mode": mode,
            "risk_level": risk_level,
            "category": category,
            "queue": queue,
            "priority": risk_level,
            "reason": reason,
            "ticket_id": "TK-" + uuid.uuid4().hex[:16],
            "created_at": now.isoformat(timespec="milliseconds"),
            "estimated_response_time": (now + timedelta(minutes=sla)).isoformat(timespec="milliseconds"),
            "sla_minutes": sla,
            "summary": "[%s|%s|%s] %s" % (mode, risk_level, category, reason or "用户请求转人工"),
            "context": {"snapshot": snapshot or {}, "recent_messages": recent_messages or []},
            "status": "created",
            "persistence": "sqlite",
        }

        endpoint = self.cfg.get("api_endpoint")
        key = self.cfg.get("api_key")
        if endpoint:
            if not key:
                ticket.update({"success": False, "status": "auth_missing", "error": "CRM_API_KEY 未配置"})
            else:
                try:
                    r = requests.post(endpoint, json=ticket, headers={"Authorization": "Bearer " + key}, timeout=5)
                    ticket["remote_status_code"] = r.status_code
                    if not r.ok:
                        ticket.update({"success": False, "status": "remote_failed", "error": r.text[:200]})
                    else:
                        ticket["persistence"] = "remote_crm+sqlite"
                except requests.RequestException as e:
                    ticket.update({"success": False, "status": "remote_unreachable", "error": str(e)})

        log_ticket(ticket, run_id=run_id)
        return ticket


CRM_AGENT = CRMAgent()


def create_crm_ticket(**kwargs):
    return CRM_AGENT.create_ticket(**kwargs)
