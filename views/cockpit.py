from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from ui_chrome import render_panel_header
from views.context import WorkspaceContext
from views.utils import haversine_m, safe as _safe, script_json as _script_json

def render_cockpit_instruments(context: WorkspaceContext) -> None:
    if context.state.mode == "Robotaxi 乘客":
        distance = haversine_m(
            context.state.passenger_lat,
            context.state.passenger_lng,
            context.state.vehicle_lat,
            context.state.vehicle_lng,
        )
    else:
        distance = 0.0
    speed_percent = min(max(float(context.state.speed) / 160 * 100, 0), 100)
    soc_percent = min(max(float(context.state.soc), 0), 100)
    range_percent = min(max(float(context.state.range_km) / 800 * 100, 0), 100)
    fatigue_percent = min(max(float(context.state.drive_hours) / 10 * 100, 0), 100)
    speed_text = f"{float(context.state.speed):.0f}"
    soc_text = f"{float(context.state.soc):.1f}"
    range_text = f"{float(context.state.range_km):.1f}"
    drive_text = f"{float(context.state.drive_hours):.2f}"
    trip_text = f"{float(context.state.trip_km):.2f}"
    order_html = ""
    order_layout_class = ""
    if context.state.mode == "Robotaxi 乘客":
        order_layout_class = " has-order"
        order_html = f"""
        <section class="dm-card order-card">
          <div><span>ROBOTAXI ORDER</span><strong>{_safe(context.state.order_status)}</strong></div>
          <dl>
            <dt>上车点</dt><dd>{_safe(context.state.passenger_loc or "未设置")}</dd>
            <dt>车辆位置</dt><dd>{_safe(context.state.vehicle_loc or "等待定位")}</dd>
            <dt>车辆距离</dt><dd>{distance:.0f} m</dd>
            <dt>目的地</dt><dd>{_safe(context.state.destination or "未设置")}</dd>
          </dl>
        </section>
        """
    st.markdown(
        f"""
        <section class="cockpit-instruments{order_layout_class}">
          <div class="instrument-grid">
            <article class="dm-unit instrument-card speed-instrument">
              <span>当前车速</span>
              <svg id="dm-speed-gauge" viewBox="0 0 120 68" role="img" aria-label="当前车速 {_safe(speed_text)} 千米每小时">
                <path d="M14 58 A46 46 0 0 1 106 58" pathLength="100"></path>
                <path id="dm-speed-arc" class="instrument-value" d="M14 58 A46 46 0 0 1 106 58" pathLength="100" stroke-dasharray="{speed_percent:.1f} 100"></path>
              </svg>
              <strong><span id="dm-speed-value">{_safe(speed_text)}</span><small> km/h</small></strong>
            </article>
            <article class="dm-unit instrument-card">
              <span>剩余电量</span>
              <strong><span id="dm-soc-value">{_safe(soc_text)}</span><small>%</small></strong>
              <div class="meter-track"><i id="dm-soc-meter" style="width:{soc_percent:.1f}%"></i></div>
              <p>预计续航 <span id="dm-range-secondary">{_safe(range_text)}</span> km</p>
            </article>
            <article class="dm-unit instrument-card">
              <span>预估续航</span>
              <strong><span id="dm-range-value">{_safe(range_text)}</span><small> km</small></strong>
              <div class="meter-track"><i id="dm-range-meter" style="width:{range_percent:.1f}%"></i></div>
              <p>本程已行驶 <span id="dm-trip-value">{_safe(trip_text)}</span> km</p>
            </article>
            <article class="dm-unit instrument-card fatigue-instrument">
              <span>连续驾驶</span>
              <strong><span id="dm-drive-value">{_safe(drive_text)}</span><small> h</small></strong>
              <div class="meter-track"><i id="dm-drive-meter" style="width:{fatigue_percent:.1f}%"></i></div>
              <p>{_safe(context.state.weather)} · {_safe(context.state.traffic)}</p>
            </article>
          </div>
          <div class="dm-unit cockpit-live-controls">
            <span>座舱同步</span>
            <strong>{_safe(f'{context.state.cabin_temp:g}')}℃</strong>
            <i></i>
            <span>风量 {_safe(context.state.fan_level)} 档</span>
            <i></i>
            <span>座椅 {_safe(context.state.seat_angle)}°</span>
            <i></i>
            <span>{_safe(context.state.media_status)}</span>
          </div>
          {order_html}
        </section>
        """,
        unsafe_allow_html=True,
    )
    simulation_state = {
        "speed": float(context.state.speed),
        "soc": float(context.state.soc),
        "range": float(context.state.range_km),
        "drive": float(context.state.drive_hours),
        "trip": float(context.state.trip_km),
        "target": 72.0 if context.state.mode == "Robotaxi 乘客" else 96.0,
    }
    components.html(
        f"""
        <!doctype html><html lang="zh-CN"><body><script>
        (() => {{
          "use strict";
          const state = {_script_json(simulation_state)};
          const doc = window.parent.document;
          let last = performance.now();
          const setText = (id, value) => {{
            const node = doc.getElementById(id);
            if (node) node.textContent = value;
          }};
          const setWidth = (id, value) => {{
            const node = doc.getElementById(id);
            if (node) node.style.width = `${{Math.max(0, Math.min(100, value))}}%`;
          }};
          const render = () => {{
            const speedText = state.speed.toFixed(0);
            setText("dm-speed-value", speedText);
            setText("dm-scene-speed-value", speedText);
            setText("dm-soc-value", state.soc.toFixed(1));
            setText("dm-range-value", state.range.toFixed(1));
            setText("dm-range-secondary", state.range.toFixed(1));
            setText("dm-trip-value", state.trip.toFixed(2));
            setText("dm-drive-value", state.drive.toFixed(2));
            setWidth("dm-soc-meter", state.soc);
            setWidth("dm-range-meter", state.range / 8);
            setWidth("dm-drive-meter", state.drive * 10);
            const arc = doc.getElementById("dm-speed-arc");
            if (arc) arc.setAttribute("stroke-dasharray", `${{Math.max(0, Math.min(100, state.speed / 1.6)).toFixed(1)}} 100`);
            const gauge = doc.getElementById("dm-speed-gauge");
            if (gauge) gauge.setAttribute("aria-label", `当前车速 ${{speedText}} 千米每小时`);
          }};
          render();
          window.setInterval(() => {{
            const now = performance.now();
            const elapsed = Math.min(Math.max((now - last) / 1000, 0), 2);
            last = now;
            const variation = Math.sin(Date.now() / 1000 * 0.72) * 1.4;
            const blend = Math.min(1, elapsed * 0.38);
            state.speed += (state.target + variation - state.speed) * blend;
            const distance = Math.max(state.speed, 0) * elapsed / 3600;
            state.trip += distance;
            state.drive += elapsed / 3600;
            state.soc = Math.max(0, state.soc - elapsed * 0.00035);
            state.range = Math.max(0, state.range - distance * 0.16);
            render();
          }}, 1000);
        }})();
        </script></body></html>
        """,
        height=0,
        scrolling=False,
    )


def render_cockpit_context(context: WorkspaceContext) -> None:
    context.advance_simulation()
    if context.state.mode == "Robotaxi 乘客":
        distance = haversine_m(
            context.state.passenger_lat,
            context.state.passenger_lng,
            context.state.vehicle_lat,
            context.state.vehicle_lng,
        )
        scene_title = context.state.vehicle_loc or "车辆位置待回读"
        scene_detail = f"距上车点约 {distance:.0f} m"
        scene_mode = "Robotaxi 接驾"
    else:
        scene_title = "延安高架 · 虹桥枢纽段"
        scene_detail = (
            f"{context.state.weather} · {context.state.traffic} · "
            f"{context.state.time_of_day} · 高架巡航"
        )
        scene_mode = "高架巡航"
        distance = 0.0
    result = context.state.current_run
    risk_level = str(result.get("risk_level") or "") if result else ""
    render_panel_header(
        "left-pane-marker",
        "LIVE DRIVE",
        "驾驶舱",
        context.state.mode,
    )
    st.markdown(
        f"""
        <section class="dm-card cockpit-static-scene" aria-label="静态实景高架巡航画面">
          <span class="cockpit-static-status"><i></i>{_safe(scene_mode)} · <span id="dm-scene-speed-value">{_safe(context.state.speed)}</span> km/h</span>
          <div class="cockpit-static-caption">
            <strong>{_safe(scene_title)}</strong>
            <small>{_safe(scene_detail)}</small>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    render_cockpit_instruments(context)
