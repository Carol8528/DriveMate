from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

import streamlit as st


def _safe(value: Any) -> str:
    return html.escape(str(value))


def render_panel_header(
    marker: str,
    eyebrow: str,
    title: str,
    status: str,
    *,
    online: bool = False,
) -> None:
    status_class = " dm-status-online" if online else ""
    status_dot = "<i></i>" if online else ""
    st.markdown(
        f"""
        <span class="{_safe(marker)}"></span>
        <header class="dm-panel-header">
          <div><span>{_safe(eyebrow)}</span><h1>{_safe(title)}</h1></div>
          <small class="dm-status{status_class}">{status_dot}{_safe(status)}</small>
        </header>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(
    eyebrow: str,
    title: str,
    description: str,
    status: str,
    *,
    tone: str = "accent",
) -> None:
    st.markdown(
        f"""
        <header class="dm-page-header dm-card">
          <div>
            <span class="dm-eyebrow">{_safe(eyebrow)}</span>
            <h2>{_safe(title)}</h2>
            <p>{_safe(description)}</p>
          </div>
          <small class="dm-status dm-status-{_safe(tone)}">{_safe(status)}</small>
        </header>
        """,
        unsafe_allow_html=True,
    )


def render_header(
    *,
    backend_health: Mapping[str, Any],
    backend_meta: Mapping[str, Any],
    api_mode: str,
    theme_options: Sequence[str],
    reset_mode_context: Callable[[], None],
) -> None:
    connection_ok = bool(backend_health.get("ok"))
    connection_text = (
        "演示数据 · Mock API"
        if connection_ok and api_mode == "mock"
        else ("后端已连接" if connection_ok else "后端未连接")
    )
    connection_class = "online" if connection_ok else "offline"
    api_version = backend_meta.get("api_version", "—")
    tool_count = backend_meta.get("tool_count", 0)
    brand_col, mode_col, theme_col, status_col = st.columns(
        [1.0, 2.1, 0.24, 0.75], gap="small"
    )
    with brand_col:
        st.markdown(
            """
            <span class="topbar-marker"></span>
            <div class="dm-brand">
              <span class="brand-glyph" aria-hidden="true"></span>
              <span><strong>DriveMate</strong><small>智能出行服务管家</small></span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with mode_col:
        st.radio(
            "出行模式",
            ["车主自驾", "Robotaxi 乘客"],
            key="mode",
            horizontal=True,
            on_change=reset_mode_context,
            label_visibility="collapsed",
        )
    with theme_col:
        with st.container(key="theme_picker"):
            st.segmented_control(
                "选择界面主题",
                options=list(theme_options),
                key="theme",
                format_func=lambda value: "☀" if value == "日间" else "☾",
                label_visibility="collapsed",
            )
    with status_col:
        st.markdown(
            f"""
            <div class="dm-topbar-status">
              <span class="connection {connection_class}"><i></i>{_safe(connection_text)}</span>
              <small>API {_safe(api_version)} · {_safe(tool_count)} 工具 · {datetime.now().strftime("%H:%M")}</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
