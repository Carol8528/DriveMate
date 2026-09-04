from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from perception_fusion import fuse_perception, summarize_action_outcome
from ui_chrome import render_page_header, render_panel_header
from views.audit import render_audit_trace
from views.context import WorkspaceContext
from views.utils import listify as _listify, pending_steps, safe as _safe

JsonObject = Dict[str, Any]

def evidence_phases(result: JsonObject) -> List[JsonObject]:
    names = [
        ("perceive", "感知"),
        ("understand", "理解"),
        ("adjudicate", "裁决"),
        ("plan", "规划"),
        ("execute", "执行"),
        ("readback", "回读"),
        ("output", "输出"),
    ]
    provided = result.get("phases")
    if isinstance(provided, list):
        phase_map = {
            str(item.get("name")): item
            for item in provided
            if isinstance(item, dict) and item.get("name")
        }
        return [
            {
                "name": label,
                "status": phase_map.get(key, {}).get("status", "unknown"),
                "duration_ms": phase_map.get(key, {}).get("duration_ms"),
            }
            for key, label in names
        ]
    has_pending = bool(result.get("pending_tools") or pending_steps(result))
    terminal = {"done", "blocked", "failed", "degraded", "cancelled"}
    steps = result.get("steps", [])
    execution_status = "unknown"
    if has_pending:
        execution_status = "waiting"
    elif result.get("calls") or (steps and all(s.get("status") in terminal for s in steps)):
        execution_status = "done"
    readback = bool(result.get("state_diff")) or any(
        bool(step.get("verified_state")) for step in steps
    )
    derived = {
        "感知": "done" if result.get("perception_fusion") else "unknown",
        "理解": "done" if result.get("intent") else "unknown",
        "裁决": "done" if result.get("risk_level") else "unknown",
        "规划": "done" if result.get("plan_summary") is not None else "unknown",
        "执行": execution_status,
        "回读": "done" if readback else "unknown",
        "输出": "done" if result.get("reply") else "unknown",
    }
    return [{"name": label, "status": derived[label]} for _, label in names]


def render_phase_strip(context: WorkspaceContext, result: JsonObject) -> None:
    labels = {
        "done": "已有证据",
        "active": "处理中",
        "waiting": "等待确认",
        "failed": "失败",
        "cancelled": "已取消",
        "unknown": "无返回证据",
        "pending": "未开始",
    }
    nodes = []
    for phase in evidence_phases(result):
        status = str(phase.get("status", "unknown"))
        duration = phase.get("duration_ms")
        suffix = f" · {duration} ms" if duration is not None else ""
        nodes.append(
            f"<div class='phase-node phase-{_safe(status)}'><strong>{_safe(phase['name'])}</strong>"
            f"<span>{_safe(labels.get(status, status))}{suffix}</span></div>"
        )
    st.markdown(
        "<div class='dm-card phase-strip'>" + "".join(nodes) + "</div>",
        unsafe_allow_html=True,
    )
    if not isinstance(result.get("phases"), list):
        st.caption("阶段状态根据本轮返回字段一次性判断；当前接口不提供实时事件。")


def _result_risk_reasons(result: JsonObject) -> List[str]:
    reasons = _listify(result.get("risk_reasons"))
    safety_tip = str(result.get("safety_tip") or "").strip()
    if not reasons and safety_tip and safety_tip != "无":
        reasons.append(safety_tip)
    return reasons


def _result_policies(result: JsonObject) -> List[str]:
    policies = _listify(result.get("policies_hit"))
    if policies:
        return policies
    steps = result.get("steps") if isinstance(result.get("steps"), list) else []
    return [
        str(step.get("strategy"))
        for step in steps
        if isinstance(step, dict) and step.get("strategy")
    ]


def _result_evidence(result: JsonObject) -> List[str]:
    evidence = _listify(result.get("evidence"))
    calls = result.get("calls") if isinstance(result.get("calls"), list) else []
    for call in calls:
        if not isinstance(call, dict):
            continue
        tool = str(call.get("tool") or "工具")
        receipt = call.get("receipt_id")
        summary = call.get("summary")
        if receipt:
            evidence.append(f"{tool} · 回执 {receipt}")
        elif summary:
            evidence.append(f"{tool} · {summary}")
    state_diff = result.get("state_diff")
    if isinstance(state_diff, dict):
        for path, change in state_diff.items():
            if isinstance(change, dict):
                evidence.append(
                    f"{path} · {change.get('before', '—')} → {change.get('after', '—')}"
                )
    return evidence


def _compact_list_markup(
    items: List[str],
    fallback: str,
    limit: int = 2,
) -> str:
    values = items or [fallback]
    markup = "".join(f"<li>{_safe(item)}</li>" for item in values[:limit])
    remaining = len(values) - limit
    if remaining > 0:
        markup += (
            f"<li class='compact-more'>另有 {remaining} 项，详见服务编排</li>"
        )
    return markup
















def render_navigation_console(context: WorkspaceContext) -> None:
    destination = str(context.state.destination or "").strip()
    has_destination = bool(destination and destination != "未设置")
    origin_label = context.state.vehicle_loc or "上海虹桥火车站"
    destination_label = destination if has_destination else "上海外滩"
    is_bund_route = "外滩" in destination_label and "虹桥" in origin_label
    result = context.state.current_run
    navigation = result.get("navigation") if isinstance(result, dict) else None
    navigation = navigation if isinstance(navigation, dict) else {}
    has_route_info = (
        bool(navigation)
        and str(navigation.get("destination") or "") == destination_label
    )
    eta_minutes = navigation.get("eta_minutes") if has_route_info else None
    distance_km = navigation.get("distance_km") if has_route_info else None
    eta_label = (
        f"{eta_minutes:g} 分钟"
        if isinstance(eta_minutes, (int, float))
        else ("42 分钟" if is_bund_route else "待规划")
    )
    distance_label = (
        f"{distance_km:g} km"
        if isinstance(distance_km, (int, float))
        else ("22.4 km" if is_bund_route else "待规划")
    )
    recommended_poi = str(
        navigation.get("recommended_poi")
        if has_route_info
        else ("静安寺" if is_bund_route else "等待路线回传")
    )
    origin_short = "虹桥枢纽" if "虹桥" in origin_label else origin_label
    route_title = f"{origin_short} → {destination_label}"
    route_state = (
        "路线已更新 · 模拟路况畅通"
        if has_route_info
        else "延安高架 · 全程路况畅通"
        if is_bund_route
        else "修改目的地后，提交 DriveMate 重新规划"
    )
    route_guidance = (
        str(navigation.get("route_summary"))
        if has_route_info and navigation.get("route_summary")
        else "虹桥枢纽 → 延安高架 → 静安寺 → 人民广场 → 外滩"
        if is_bund_route
        else f"{origin_short} → {destination_label} · 等待 Agent 返回路线"
    )
    map_markup = (
        """
        <div class="route-map" aria-label="上海虹桥火车站至外滩真实地理导航图">
          <small>DriveMate 导航预览 · 以实际工具回传为准</small>
        </div>
        """
        if is_bund_route
        else f"""
        <div class="route-map route-map-pending{' is-ready' if has_route_info else ''}" aria-label="新目的地路线{'已更新' if has_route_info else '等待规划'}">
          <div><span>ROUTE UPDATE</span><strong>{'路线数据已更新' if has_route_info else '正在等待新路线'}</strong><small>{_safe(destination_label)}</small></div>
        </div>
        """
    )
    render_page_header(
        "NAVIGATION",
        route_title,
        "路线摘要、关键行程指标与地图共享同一任务卡。",
        route_state,
        tone="success" if is_bund_route or has_route_info else "accent",
    )
    st.markdown(
        f"""
        <section class="dm-card navigation-stage">
          <div class="route-endpoints">
            <div class="route-endpoint">
              <span>当前位置</span>
              <strong>{_safe(origin_label)}</strong>
            </div>
            <div class="route-endpoint route-endpoint-destination">
              <span>目的地</span>
              <strong>{_safe(destination_label)}</strong>
            </div>
          </div>
          <div class="dm-metric-grid route-metrics">
            <div class="dm-unit"><span>预计时间</span><strong>{_safe(eta_label)}</strong></div>
            <div class="dm-unit"><span>剩余里程</span><strong>{_safe(distance_label)}</strong></div>
            <div class="dm-unit"><span>推荐 POI</span><strong>{_safe(recommended_poi)}</strong></div>
          </div>
          <div class="dm-unit route-guidance">
            <span>推荐路线</span>
            <strong>{_safe(route_guidance)}</strong>
            <small>{"模拟路线" if has_route_info else "避开拥堵 8 分钟" if is_bund_route else "待后端回传"}</small>
          </div>
          {map_markup}
        </section>
        """,
        unsafe_allow_html=True,
    )
def render_control_slider(context: WorkspaceContext, 
    *,
    title: str,
    description: str,
    label: str,
    state_key: str,
    control_key: str,
    minimum: Any,
    maximum: Any,
    step: Any,
    on_change: Any,
    current_text: str,
) -> None:
    value_kwargs: JsonObject = {}
    if control_key in context.state:
        context.state[control_key] = context.state[state_key]
    else:
        value_kwargs["value"] = context.state[state_key]
    st.markdown(
        f"""
        <div class="dm-control-card-head">
          <span class="dm-control-marker"></span>
          <div><strong>{_safe(title)}</strong><small>{_safe(description)}</small></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.slider(
        label,
        minimum,
        maximum,
        step=step,
        key=control_key,
        on_change=on_change,
        label_visibility="collapsed",
        **value_kwargs,
    )
    st.markdown(
        f"<div class='dm-control-current'>{_safe(current_text)}</div>",
        unsafe_allow_html=True,
    )


def render_vehicle_control_console(context: WorkspaceContext) -> None:
    render_page_header(
        "VEHICLE CONTROL",
        "座舱控制调节",
        "滑杆只更新本地预览，提交后仍由后端评估、确认与执行。",
        "本地预览",
    )
    row_one_left, row_one_right = st.columns(2, gap="small")
    with row_one_left:
        render_control_slider(
            context,
            title="温度",
            description="当前设定预览",
            label="空调温度",
            state_key="cabin_temp",
            control_key="cabin_temp_control",
            minimum=16.0,
            maximum=30.0,
            step=0.5,
            on_change=context.sync_cabin_temp,
            current_text=f"{context.state.cabin_temp:g}°C · 风量 {context.state.fan_level} 档",
        )
    with row_one_right:
        render_control_slider(
            context,
            title="座椅",
            description="主驾靠背角度",
            label="座椅角度",
            state_key="seat_angle",
            control_key="seat_angle_control",
            minimum=85,
            maximum=125,
            step=1,
            on_change=context.sync_seat_angle,
            current_text=f"{context.state.seat_angle}° · 标准支撑",
        )
    row_two_left, row_two_right = st.columns(2, gap="small")
    with row_two_left:
        render_control_slider(
            context,
            title="车窗",
            description="统一开启比例",
            label="车窗比例",
            state_key="window_percent",
            control_key="window_percent_control",
            minimum=0,
            maximum=100,
            step=1,
            on_change=context.sync_window_percent,
            current_text=f"{context.state.window_percent}% · 本地预览",
        )
    with row_two_right:
        render_control_slider(
            context,
            title="氛围灯",
            description="座舱灯光主题",
            label="氛围灯亮度",
            state_key="ambient_light",
            control_key="ambient_light_control",
            minimum=0,
            maximum=100,
            step=1,
            on_change=context.sync_ambient_light,
            current_text=f"主题联动 · {context.state.ambient_light}% · 本地预览",
        )
    control_prompt = (
        f"请评估并设置座舱：空调温度 {context.state.cabin_temp} 度，"
        f"主驾座椅 {context.state.seat_angle} 度，"
        f"车窗开启 {context.state.window_percent}%，"
        f"{context.state.theme}氛围灯亮度 {context.state.ambient_light}%"
    )
    if st.button(
        "交给 DriveMate 评估并执行",
        key="submit_control_preview",
        type="primary",
        use_container_width=True,
    ):
        context.submit_message(control_prompt)


def _modality_icon(modality: str) -> str:
    icons = {
        "video": "◉",
        "audio": "≋",
        "telemetry": "⌁",
        "position": "⌖",
        "environment": "◎",
    }
    return icons.get(modality, "•")


def render_perception_console(context: WorkspaceContext) -> None:
    result = context.state.current_run
    pending = context.state.pending_request
    if result:
        snapshot = result.get("snapshot")
        snapshot = snapshot if isinstance(snapshot, dict) else context.build_snapshot()
        fusion = result.get("perception_fusion")
        fusion = (
            fusion
            if isinstance(fusion, dict)
            else fuse_perception(snapshot, str(result.get("intent") or ""))
        )
        outcome = result.get("action_outcome")
        outcome = (
            outcome
            if isinstance(outcome, dict)
            else summarize_action_outcome(result)
        )
    else:
        snapshot = (
            pending.get("snapshot")
            if isinstance(pending, dict) and isinstance(pending.get("snapshot"), dict)
            else context.build_snapshot()
        )
        fusion = fuse_perception(snapshot)
        outcome = {
            "status": "advisory",
            "status_label": "等待任务",
            "title": "感知通道已就绪",
            "detail": "发送需求后，融合结论将进入意图识别与安全裁决。",
            "next_action": "等待用户指令",
            "receipt_count": 0,
            "state_change_count": 0,
        }

    modalities = fusion.get("modalities")
    modalities = modalities if isinstance(modalities, list) else []
    cards = []
    for item in modalities[:4]:
        if not isinstance(item, dict):
            continue
        confidence = max(0, min(100, int(item.get("confidence") or 0)))
        status = str(item.get("status") or "offline")
        status_class = "is-online" if status == "online" else "is-offline"
        cards.append(
            f"""
            <article class="dm-unit modality-card {status_class}">
              <header>
                <span class="modality-icon">{_modality_icon(str(item.get("modality") or ""))}</span>
                <div><strong>{_safe(item.get("label") or "感知输入")}</strong><small>{_safe(item.get("source") or "unknown")}</small></div>
                <em>{confidence}%</em>
              </header>
              <p>{_safe(item.get("signal") or "等待有效读数")}</p>
              <div class="modality-confidence" aria-label="输入置信度 {confidence}%">
                <i style="--confidence:{confidence}%"></i>
              </div>
              <footer><span>{_safe(item.get("value") or "—")}</span><small>融合贡献 {int(item.get("contribution") or 0)}%</small></footer>
            </article>
            """
        )
    confidence_trace = fusion.get("confidence_trace")
    confidence_trace = (
        confidence_trace if isinstance(confidence_trace, list) else []
    )
    trace_html = "".join(
        f"""
        <div>
          <span>{_safe(item.get("stage") or "融合阶段")}</span>
          <strong>{int(item.get("confidence") or 0)}%</strong>
          <i><b style="--confidence:{max(0, min(100, int(item.get('confidence') or 0)))}%"></b></i>
        </div>
        """
        for item in confidence_trace
        if isinstance(item, dict)
    )
    fusion_confidence = max(
        0, min(100, int(fusion.get("fusion_confidence") or 0))
    )
    risk_score = fusion.get("risk_score")
    risk_score_text = (
        f"{float(risk_score):.0f}%"
        if isinstance(risk_score, (int, float))
        else "—"
    )
    outcome_status = str(outcome.get("status") or "advisory")
    if outcome_status not in {
        "advisory",
        "blocked",
        "cancelled",
        "completed",
        "waiting",
    }:
        outcome_status = "advisory"
    source_label = (
        "演示数据 · Mock Sensor Bus"
        if fusion.get("simulated")
        else "车辆感知总线"
    )
    run_label = (
        f"Run {_safe(result.get('run_id') or '—')}"
        if result
        else "尚未发起 Run"
    )
    render_page_header(
        "MULTIMODAL PERCEPTION",
        "多传感器融合感知",
        f"视频、音频、车辆与环境信号完成时空对齐；{source_label}。",
        f"{int(fusion.get('online_count') or 0)} / {int(fusion.get('total_count') or 0)} 路在线",
        tone="success",
    )
    markup = f"""
        <section class="dm-card fusion-console fusion-{outcome_status}">
          <div class="modality-grid">{"".join(cards)}</div>
          <div class="fusion-pipeline" aria-label="融合处理流程">
            <span>多路输入</span><i></i><span>时空同步</span><i></i><span>交叉验证</span>
          </div>
          <div class="fusion-decision-grid">
            <section class="dm-unit confidence-evolution">
              <header><span>置信度变化</span><small>{int(fusion.get("latency_ms") or 0)} ms 窗口</small></header>
              {trace_html}
            </section>
            <section class="fusion-core" style="--fusion-confidence:{fusion_confidence}%">
              <div>
                <span>融合置信度</span>
                <strong>{fusion_confidence}<small>%</small></strong>
                <em>{_safe(fusion.get("focus_label") or "环境态势")}</em>
              </div>
              <small>风险信号 {risk_score_text}</small>
            </section>
            <section class="dm-unit final-action-card action-{outcome_status}">
              <header><span>最终行动结果</span><em>{_safe(outcome.get("status_label") or "等待任务")}</em></header>
              <strong>{_safe(outcome.get("title") or "等待决策")}</strong>
              <p>{_safe(outcome.get("detail") or "暂无行动结果")}</p>
              <footer>
                <span>下一步 · {_safe(outcome.get("next_action") or "—")}</span>
                <small>{int(outcome.get("receipt_count") or 0)} 回执 · {int(outcome.get("state_change_count") or 0)} 状态变化</small>
              </footer>
            </section>
          </div>
          <div class="dm-unit fusion-finding">
            <span>融合判断</span>
            <strong>{_safe(fusion.get("primary_finding") or "等待有效感知证据")}</strong>
            <small>{run_label}</small>
          </div>
        </section>
        """
    if hasattr(st, "html"):
        st.html(markup)
    else:
        st.markdown(markup, unsafe_allow_html=True)
    with st.popover("查看本次融合证据", use_container_width=True):
        st.json(
            {
                "perception_fusion": fusion,
                "sensor_state": snapshot.get("sensor_state"),
                "action_outcome": outcome,
            }
        )


def render_orchestration_progress(context: WorkspaceContext, result: JsonObject) -> None:
    phases = evidence_phases(result)
    completed = sum(phase.get("status") == "done" for phase in phases)
    total = len(phases) or 7
    progress = round(completed / total * 100)
    current_phase = next(
        (
            str(phase["name"])
            for phase in phases
            if phase.get("status") in {"active", "waiting", "pending_confirm"}
        ),
        "流程已完成" if completed == total else "等待更多后端证据",
    )
    st.markdown(
        f"""
        <section class="dm-card orchestration-progress">
          <div>
            <span>当前阶段</span>
            <strong>{_safe(current_phase)}</strong>
            <small>{completed} / {total} 个阶段已有完成证据</small>
          </div>
          <div class="orchestration-progress-track" aria-label="已完成 {progress}%">
            <i style="width:{progress}%"></i>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_orchestration_console(context: WorkspaceContext) -> None:
    result = context.state.current_run
    pending = context.state.pending_request
    if (
        context.state.request_state in {"queued", "waiting"}
        and isinstance(pending, dict)
    ):
        stage = (
            "请求已提交"
            if context.state.request_state == "queued"
            else "等待 Agent 返回"
        )
        render_page_header(
            "SERVICE ORCHESTRATION",
            stage,
            "后端返回后按真实 phases 更新七阶段证据。",
            "处理中",
            tone="warning",
        )
        st.markdown(
            f"""
            <section class="dm-card orchestration-progress is-live">
              <div>
                <span>当前阶段</span>
                <strong>{_safe(stage)}</strong>
                <small>后端返回后将按真实 phases 更新七阶段证据</small>
              </div>
              <div class="orchestration-progress-track" aria-label="正在等待后端返回">
                <i></i>
              </div>
              <p>{_safe(str(pending.get("message") or ""))}</p>
            </section>
            <div class="waiting-stage-grid live-stage-grid">
              <span><i>01</i>感知</span>
              <span><i>02</i>理解</span>
              <span><i>03</i>裁决</span>
              <span><i>04</i>规划</span>
              <span><i>05</i>执行</span>
              <span><i>06</i>回读</span>
              <span><i>07</i>输出</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    if not result:
        phase_labels = ("感知", "理解", "裁决", "规划", "执行", "回读", "输出")
        waiting_stages = "".join(
            f"<span><i>{index:02d}</i>{_safe(name)}</span>"
            for index, name in enumerate(phase_labels, start=1)
        )
        render_page_header(
            "SERVICE ORCHESTRATION",
            "服务编排",
            "执行计划、工具调用和状态回读只在收到后端证据后显示。",
            "待命",
        )
        st.markdown(
            f"""
            <section class="dm-card empty-console orchestration-empty">
              <div class="empty-console-icon">⌘</div>
              <h3>等待一次明确的出行请求</h3>
              <p>从右侧助手或车控、导航入口提交需求。</p>
              <div class="waiting-stage-grid">{waiting_stages}</div>
            </section>
            """,
            unsafe_allow_html=True,
        )
        return
    status = str(result.get("run_status") or result.get("status") or "completed")
    render_page_header(
        "SERVICE ORCHESTRATION",
        f"运行 {result.get('run_id', '—')}",
        "阶段、方案、工具回执与状态回读均来自本轮 Run。",
        context.status_labels.get(status, status),
        tone=(
            "success"
            if status == "completed"
            else "danger"
            if status in {"failed", "blocked", "cancelled"}
            else "warning"
        ),
    )
    render_orchestration_progress(context, result)
    render_phase_strip(context, result)
    plan = _listify(result.get("execution_plan"))
    steps = result.get("steps") if isinstance(result.get("steps"), list) else []
    if not plan:
        plan = [
            str(step.get("title"))
            for step in steps
            if isinstance(step, dict) and step.get("title")
        ]
    if not plan and result.get("plan_summary"):
        plan = [str(result["plan_summary"])]
    calls = result.get("calls") if isinstance(result.get("calls"), list) else []
    plan_html = "".join(
        f"<li><i>{index:02d}</i><span>{_safe(item)}</span></li>"
        for index, item in enumerate(plan, start=1)
    ) or "<li class='empty-row'>后端未返回执行计划</li>"
    receipt_html = "".join(
        (
            f"<li><i>{index:02d}</i><span><strong>{_safe(call.get('tool') or '工具调用')}</strong>"
            f"<small>{_safe(call.get('receipt_id') or call.get('summary') or call.get('result') or '已记录')}</small></span></li>"
        )
        for index, call in enumerate(calls, start=1)
        if isinstance(call, dict)
    ) or "<li class='empty-row'>后端未返回工具回执</li>"
    st.markdown(
        f"""
        <div class="dm-evidence-grid orchestration-evidence-grid">
          <section class="dm-card evidence-card">
            <span>编排方案</span>
            <ol class="console-list">{plan_html}</ol>
          </section>
          <section class="dm-card evidence-card">
            <span>工具回执</span>
            <ol class="console-list">{receipt_html}</ol>
          </section>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_audit_trace(context, result)


def render_situation_stage(context: WorkspaceContext) -> None:
    result = context.state.current_run
    risk = result.get("risk_level") if result else None
    raw_score = result.get("safety_score") if result else None
    score = (
        raw_score
        if isinstance(raw_score, (int, float)) and 0 <= raw_score <= 100
        else None
    )
    halo_value = f"{score:g}" if score is not None else (risk or "—")
    halo_label = (
        "安全评分" if score is not None else ("风险等级" if risk else "等待评估")
    )
    risk_label = context.risk_labels.get(risk, "尚未评估")
    risk_class = f"risk-{str(risk or 'idle').lower()}"
    conclusion = (
        result.get("safety_tip") or risk_label
        if result
        else "发送需求后，DriveMate 会先完成风险评估。"
    )
    if context.state.mode == "Robotaxi 乘客":
        scene_location = context.state.vehicle_loc or "车辆位置待回读"
        scene_detail = f"上车点 · {context.state.passenger_loc or '未设置'}"
    else:
        scene_location = context.state.vehicle_loc or f"{context.state.area_type}道路"
        scene_detail = (
            f"{context.state.weather} · {context.state.traffic} · "
            f"{context.state.time_of_day}"
        )
    phases = evidence_phases(result) if result else []
    completed_phases = sum(phase.get("status") == "done" for phase in phases)
    total_phases = len(phases) or 7
    progress_percent = round(completed_phases / total_phases * 100)
    if context.state.request_state == "waiting":
        run_state = "正在评估"
    elif result and (result.get("pending_tools") or context.pending_steps(result)):
        run_state = "等待确认"
    elif result and result.get("run_status") == "completed":
        run_state = "执行完成"
    elif result and result.get("run_status") == "cancelled":
        run_state = "已取消"
    elif result:
        run_state = "已有返回"
    else:
        run_state = "等待需求"
    phase_names = "".join(
        f"<span class='stage-phase {'is-done' if phase.get('status') == 'done' else ''}'>{_safe(phase['name'])}</span>"
        for phase in phases
    ) or "".join(
        f"<span class='stage-phase'>{name}</span>"
        for name in ("感知", "理解", "裁决", "规划", "执行", "回读", "输出")
    )
    source = "Mock 响应" if context.api_mode == "mock" else "后端响应"
    tone = (
        "success"
        if risk == "L0"
        else "warning"
        if risk in {"L1", "L2"}
        else "danger"
        if risk == "L3"
        else "accent"
    )
    render_page_header(
        "SAFETY STATUS ASSESSMENT",
        "安全状态评估",
        "风险原值、场景与执行证据在同一视野内汇合。",
        run_state,
        tone=tone,
    )
    st.markdown(
        f"""
        <section class="dm-card safety-stage {risk_class}">
          <div class="safety-stage-grid">
            <div class="safety-halo {risk_class}" title="来源：{_safe(source)}">
              <div class="halo-core">
              <span>{_safe(halo_label)}</span>
              <strong>{_safe(halo_value)}</strong>
              <em>{_safe(risk or "—")} · {_safe(risk_label)}</em>
              </div>
            </div>
            <div class="safety-support-grid">
              <section class="dm-unit safety-context-card">
              <span class="stage-label">场景位置</span>
              <strong>{_safe(scene_location)}</strong>
              <p>{_safe(scene_detail)}</p>
              <div class="scene-signals">
                <span>{_safe(context.state.area_type)}</span>
                <span>{_safe(context.state.weather)}</span>
                <span>{_safe(context.state.traffic)}</span>
              </div>
              </section>
              <section class="dm-unit safety-progress-card">
              <span class="stage-label">执行进度</span>
              <strong>{completed_phases}<small> / {total_phases}</small></strong>
              <div class="stage-progress" aria-label="执行进度 {progress_percent}%">
                <i style="width: {progress_percent}%"></i>
              </div>
              <p>{_safe(run_state)} · 仅统计已有返回证据</p>
              <div class="stage-phases">{phase_names}</div>
              </section>
            </div>
          </div>
          <div class="dm-unit safety-verdict">
            <span>风险判断</span>
            <strong>{_safe(risk_label)}</strong>
            <p>{_safe(conclusion)}</p>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_safety_guard_console(context: WorkspaceContext) -> None:
    render_situation_stage(context)
    result = context.state.current_run
    if not result:
        st.markdown(
            """
            <div class="dm-card safety-empty-note">
              Safety Halo 当前处于待评估态。发起请求后，这里会同步后端风险等级、策略命中与执行后验证。
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    reasons = _result_risk_reasons(result)
    policies = _result_policies(result)
    evidence = _result_evidence(result)
    reason_html = _compact_list_markup(reasons, "后端未返回风险原因")
    policy_html = _compact_list_markup(policies, "未命中额外策略")
    evidence_html = _compact_list_markup(evidence, "等待状态回读证据")
    st.markdown(
        f"""
        <div class="dm-evidence-grid safety-evidence-grid">
          <section class="dm-card safety-brief"><span>风险依据</span><ul>{reason_html}</ul></section>
          <section class="dm-card safety-brief"><span>策略约束</span><ul>{policy_html}</ul></section>
          <section class="dm-card safety-brief"><span>验证证据</span><ul>{evidence_html}</ul></section>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_memory_console(context: WorkspaceContext) -> None:
    recent_requests = [
        str(message.get("content", ""))
        for message in context.state.messages
        if message.get("role") == "user"
    ][-4:]
    recent_html = "".join(
        f"<li><i>{index:02d}</i><span>{_safe(item)}</span></li>"
        for index, item in enumerate(reversed(recent_requests), start=1)
    ) or "<li class='empty-row'>本次会话还没有请求</li>"
    if context.state.mode == "车主自驾":
        profile_items = [
            ("当前模式", "车主自驾"),
            ("道路偏好", context.state.area_type),
            ("乘员线索", "儿童座椅" if context.state.child_seat else "无儿童座椅证据"),
            ("座舱偏好", f"{context.state.cabin_temp}°C · 冰蓝 {context.state.ambient_light}%"),
        ]
    else:
        profile_items = [
            ("当前模式", "Robotaxi 乘客"),
            ("上车点", context.state.passenger_loc),
            ("目的地", context.state.destination),
            ("订单状态", context.state.order_status),
        ]
    profile_html = "".join(
        f"<div class='dm-unit'><span>{_safe(label)}</span><strong>{_safe(value or '未设置')}</strong></div>"
        for label, value in profile_items
    )
    render_page_header(
        "SESSION MEMORY",
        "指令记录",
        "仅展示本页输入与本次会话已发生的指令，不推断长期偏好。",
        context.state.mode,
    )
    st.markdown(
        f"""
        <div class="dm-card memory-profile">{profile_html}</div>
        <section class="dm-card evidence-card memory-history">
          <span>最近请求</span>
          <ol class="console-list">{recent_html}</ol>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_command_workspace(context: WorkspaceContext) -> None:
    result = context.state.current_run
    risk_level = str(result.get("risk_level", "—")) if result else "—"
    render_panel_header(
        "center-pane-marker",
        "MISSION CONTROL",
        "智能中控",
        f"当前风险 {risk_level}",
    )
    options = {
        "导航": "路线导航",
        "车控": "座舱控制",
        "安全守护": "安全评估",
        "融合感知": "融合感知",
        "服务编排": "服务编排",
        "记忆": "指令记录",
    }
    if context.state.center_view not in options:
        context.state.center_view = "导航"
    if context.state.center_view_control != context.state.center_view:
        context.state.center_view_control = context.state.center_view
    selected = st.segmented_control(
        "中控页面",
        options=list(options),
        key="center_view_control",
        format_func=options.get,
        on_change=context.sync_center_view,
        label_visibility="collapsed",
    )
    selected = selected or context.state.center_view
    if selected == "导航":
        render_navigation_console(context)
    elif selected == "车控":
        render_vehicle_control_console(context)
    elif selected == "融合感知":
        render_perception_console(context)
    elif selected == "服务编排":
        render_orchestration_console(context)
    elif selected == "安全守护":
        render_safety_guard_console(context)
    elif selected == "记忆":
        render_memory_console(context)
