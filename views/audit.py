from __future__ import annotations

import json
from typing import Any, Dict, List

import streamlit as st

from api_client import BackendApiError
from views.context import WorkspaceContext
from views.utils import safe as _safe

JsonObject = Dict[str, Any]

def load_audit_trace(context: WorkspaceContext, result: JsonObject) -> JsonObject | None:
    try:
        return context.client.audit_run(str(result["run_id"]))
    except BackendApiError as exc:
        st.caption(f"审计链读取失败：{exc}")
        return None


def render_download_audit(context: WorkspaceContext, 
    result: JsonObject, audit: JsonObject | None = None
) -> None:
    trace = audit if audit is not None else load_audit_trace(context, result)
    if trace is None:
        return
    st.download_button(
        "下载完整审计链",
        data=json.dumps(trace, ensure_ascii=False, indent=2),
        file_name=f"audit_{result['run_id']}.json",
        mime="application/json",
        key=f"orchestration_audit_{result['run_id']}",
        use_container_width=True,
    )


def _audit_records(audit: JsonObject, key: str) -> List[JsonObject]:
    records = audit.get(key)
    if not isinstance(records, list):
        return []
    return [item for item in records if isinstance(item, dict)]


def _audit_time(value: Any) -> str:
    text = str(value or "—").replace("T", " ")
    return text[:23]


def _audit_stage(stage: Any) -> str:
    value = str(stage or "unknown")
    labels = {
        "perceive": "感知",
        "understand": "理解",
        "adjudicate": "裁决",
        "plan": "规划",
        "execute": "执行",
        "readback": "回读",
        "output": "输出",
        "intent.snapshot": "意图快照",
        "constraint.snapshot": "约束快照",
        "recovery.snapshot": "恢复快照",
    }
    return labels.get(value, value)


def _confirmation_decision(value: Any) -> str:
    decision = str(value or "unknown")
    return {
        "confirmed": "已确认",
        "cancelled": "已取消",
        "confirmation_invalidated": "确认已失效",
    }.get(decision, decision)


def render_audit_trace(context: WorkspaceContext, result: JsonObject) -> None:
    audit = load_audit_trace(context, result)
    if audit is None:
        return
    run = audit.get("run")
    run = run if isinstance(run, dict) else {}
    events = _audit_records(audit, "decision_events")
    calls = _audit_records(audit, "tool_calls")
    confirmations = _audit_records(audit, "confirmations")
    tickets = _audit_records(audit, "tickets")
    run_id = str(run.get("run_id") or result.get("run_id") or "—")

    metrics = [
        ("运行编号", run_id),
        ("风险等级", str(run.get("risk_level") or result.get("risk_level") or "—")),
        ("决策事件", str(len(events))),
        ("工具调用", str(len(calls))),
        ("确认记录", str(len(confirmations))),
        ("工单记录", str(len(tickets))),
    ]
    metric_html = "".join(
        f"<div class='audit-metric'><span>{_safe(label)}</span>"
        f"<strong>{_safe(value)}</strong></div>"
        for label, value in metrics
    )

    timeline: List[JsonObject] = []
    for event in events:
        duration = event.get("duration_ms")
        detail = f"{duration:g} ms" if isinstance(duration, (int, float)) else "已持久化"
        timeline.append(
            {
                "kind": "decision",
                "title": f"决策 · {_audit_stage(event.get('stage'))}",
                "detail": detail,
                "time": event.get("created_at"),
            }
        )
    for call in calls:
        status = context.status_labels.get(str(call.get("status")), str(call.get("status") or "未知"))
        receipt = str(call.get("receipt_id") or "").strip()
        detail = f"{call.get('level', 'L0')} · {status}"
        if receipt:
            detail += f" · 回执 {receipt}"
        timeline.append(
            {
                "kind": "tool",
                "title": f"工具 · {call.get('tool') or '未知工具'}",
                "detail": detail,
                "time": call.get("created_at"),
            }
        )
    for confirmation in confirmations:
        timeline.append(
            {
                "kind": "confirmation",
                "title": f"确认 · {confirmation.get('tool') or '未知工具'}",
                "detail": _confirmation_decision(confirmation.get("decision")),
                "time": confirmation.get("decided_at"),
            }
        )
    for ticket in tickets:
        payload = ticket.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        timeline.append(
            {
                "kind": "ticket",
                "title": f"工单 · {ticket.get('ticket_id') or '未知编号'}",
                "detail": str(payload.get("status") or "已持久化"),
                "time": ticket.get("created_at"),
            }
        )
    timeline.sort(key=lambda item: str(item.get("time") or ""))
    timeline_html = "".join(
        "<li class='audit-timeline-item'>"
        f"<i class='audit-kind audit-kind-{item['kind']}'></i>"
        "<div>"
        f"<strong>{_safe(item['title'])}</strong>"
        f"<span>{_safe(item['detail'])}</span>"
        "</div>"
        f"<time>{_safe(_audit_time(item['time']))}</time>"
        "</li>"
        for item in timeline
    ) or "<li class='audit-empty-row'>本轮尚无审计事件</li>"

    with st.container(key="audit_trace", border=False):
        st.markdown(
            "<div class='audit-section-heading'><span>完整审计链</span>"
            "<small>按后端持久化时间排序</small></div>"
            f"<div class='dm-card audit-metrics'>{metric_html}</div>"
            "<section class='dm-card audit-timeline-card'>"
            f"<ol class='audit-timeline'>{timeline_html}</ol>"
            "</section>",
            unsafe_allow_html=True,
        )

        with st.expander("运行上下文与最终结果", expanded=False):
            st.markdown(
                f"**用户请求：** {_safe(run.get('user_text') or '—')}  \n"
                f"**会话编号：** `{_safe(run.get('session_id') or '—')}`  \n"
                f"**意图：** `{_safe(run.get('intent') or '—')}`  \n"
                f"**创建时间：** {_safe(_audit_time(run.get('created_at')))}"
            )
            st.markdown("**状态快照**")
            st.json(run.get("snapshot") or {}, expanded=False)
            st.markdown("**最终结果**")
            st.json(run.get("result") or {}, expanded=False)

        with st.expander(f"决策事件（{len(events)}）", expanded=bool(events)):
            if not events:
                st.caption("本轮没有决策事件。")
            for event in events:
                duration = event.get("duration_ms")
                duration_label = (
                    f"{duration:g} ms"
                    if isinstance(duration, (int, float))
                    else "未记录耗时"
                )
                st.markdown(
                    "<div class='audit-detail-head'>"
                    f"<strong>{_safe(_audit_stage(event.get('stage')))}</strong>"
                    f"<span>{_safe(duration_label)} · "
                    f"{_safe(_audit_time(event.get('created_at')))}</span>"
                    "</div>",
                    unsafe_allow_html=True,
                )
                st.json(event.get("payload") or {}, expanded=False)

        with st.expander(f"工具调用（{len(calls)}）", expanded=bool(calls)):
            if not calls:
                st.caption("本轮没有工具调用。")
            for call in calls:
                latency = call.get("latency_ms")
                latency_label = (
                    f"{latency:g} ms"
                    if isinstance(latency, (int, float))
                    else "未记录耗时"
                )
                st.markdown(
                    "<div class='audit-detail-head'>"
                    f"<strong>{_safe(call.get('tool') or '未知工具')} · "
                    f"{_safe(call.get('level') or 'L0')}</strong>"
                    f"<span>{_safe(call.get('status') or '未知状态')} · "
                    f"{_safe(call.get('backend') or '未知后端')} · "
                    f"{_safe(latency_label)}</span>"
                    "</div>",
                    unsafe_allow_html=True,
                )
                if call.get("receipt_id"):
                    st.caption(f"执行回执：{call['receipt_id']}")
                st.markdown("**调用参数**")
                st.json(call.get("arguments") or {}, expanded=False)
                st.markdown("**返回结果**")
                st.json(call.get("result") or {}, expanded=False)

        with st.expander(
            f"确认记录（{len(confirmations)}）",
            expanded=bool(confirmations),
        ):
            if not confirmations:
                st.caption("本轮没有需要用户确认的操作。")
            else:
                rows = "".join(
                    "<li class='audit-record-row'>"
                    f"<strong>{_safe(item.get('tool') or '未知工具')}</strong>"
                    f"<span>{_safe(_confirmation_decision(item.get('decision')))}</span>"
                    f"<time>{_safe(_audit_time(item.get('decided_at')))}</time>"
                    "</li>"
                    for item in confirmations
                )
                st.markdown(
                    f"<ol class='audit-record-list'>{rows}</ol>",
                    unsafe_allow_html=True,
                )

        with st.expander(f"工单记录（{len(tickets)}）", expanded=bool(tickets)):
            if not tickets:
                st.caption("本轮没有创建客服工单。")
            for ticket in tickets:
                st.markdown(
                    "<div class='audit-detail-head'>"
                    f"<strong>{_safe(ticket.get('ticket_id') or '未知工单')}</strong>"
                    f"<span>{_safe(_audit_time(ticket.get('created_at')))}</span>"
                    "</div>",
                    unsafe_allow_html=True,
                )
                st.json(ticket.get("payload") or {}, expanded=False)

        render_download_audit(context, result, audit)
