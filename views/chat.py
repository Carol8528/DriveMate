from __future__ import annotations

import json
from typing import Any, Dict, List

import streamlit as st
import streamlit.components.v1 as components

from views.context import WorkspaceContext
from views.utils import safe as _safe, script_json as _script_json

JsonObject = Dict[str, Any]

def render_confirmation(context: WorkspaceContext, result: JsonObject, key_prefix: str) -> None:
    steps = context.pending_steps(result)
    tools = result.get("pending_tools", [])
    if not steps and not tools:
        return
    names = [
        step.get("title") or step.get("tool") or "待确认动作" for step in steps
    ] or [tool.get("name", "待确认动作") for tool in tools]
    arguments = [
        tool.get("arguments", {}) for tool in tools if tool.get("arguments")
    ]
    st.markdown(
        f"""
        <section class="confirm-card">
          <div><strong>是否继续执行？</strong><span>{_safe("、".join(names))}</span></div>
          <p>这一步可能影响车辆或行程。请告诉我确认还是取消；确认接口成功前不会标记完成。</p>
          <small>判断依据：{_safe(result.get("safety_tip", "高影响操作需要明确授权"))}</small>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if arguments:
        st.caption(
            "关键参数："
            + "；".join(json.dumps(item, ensure_ascii=False) for item in arguments)
        )
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button(
        "确认执行",
        key=f"{key_prefix}_confirm",
        type="primary",
        use_container_width=True,
    ):
        context.update_run("confirming")
    if cancel_col.button(
        "取消待确认操作",
        key=f"{key_prefix}_cancel",
        use_container_width=True,
    ):
        context.update_run("cancelling")


STATE_DIFF_LABELS = {
    "climate.temperature": "空调温度",
    "climate.fan_level": "空调风量",
    "climate.fan": "空调风量",
    "seat.driver_backrest_angle": "主驾座椅靠背",
    "seat.driver_angle": "主驾座椅靠背",
    "seat.angle": "主驾座椅靠背",
    "window.open_percent": "车窗开启比例",
    "ambient_light.brightness": "氛围灯亮度",
    "media.playing": "提神音乐",
    "media.source": "播放内容",
    "navigation.destination": "导航目的地",
    "order.vehicle_location": "车辆位置",
}


def _format_feedback_value(path: str, value: Any) -> str:
    if value is None:
        return "—"
    if path == "media.playing" and isinstance(value, bool):
        return "播放中" if value else "未播放"
    if isinstance(value, bool):
        return "已开启" if value else "已关闭"
    if path == "climate.temperature" and isinstance(value, (int, float)):
        return f"{value:g}℃"
    if path in {"climate.fan_level", "climate.fan"} and isinstance(
        value, (int, float)
    ):
        return f"{value:g} 档"
    if path.startswith("seat.") and isinstance(value, (int, float)):
        return f"{value:g}°"
    if path in {"window.open_percent", "ambient_light.brightness"} and isinstance(
        value, (int, float)
    ):
        return f"{value:g}%"
    return str(value)


def execution_feedback(result: JsonObject) -> List[str]:
    feedback = []
    state_diff = result.get("state_diff")
    if isinstance(state_diff, dict):
        for path, change in state_diff.items():
            if not isinstance(change, dict):
                continue
            label = STATE_DIFF_LABELS.get(str(path), str(path))
            before = _format_feedback_value(str(path), change.get("before"))
            after = _format_feedback_value(str(path), change.get("after"))
            feedback.append(f"{label}：{before} → {after}")
    if feedback:
        return feedback[:6]
    for step in result.get("steps", []):
        if isinstance(step, dict) and step.get("status") == "done":
            feedback.append(f"{step.get('title', '动作')}：已完成")
    return feedback[:4]


def render_current_reply(context: WorkspaceContext, result: JsonObject) -> None:
    reply = str(result["reply"])
    st.markdown(reply)
    safety_tip = result.get("safety_tip")
    if safety_tip and safety_tip != "无" and str(safety_tip) not in reply:
        st.markdown(
            f"<div class='assistant-safety-note'>安全提醒：{_safe(safety_tip)}</div>",
            unsafe_allow_html=True,
        )


VOICE_BRIDGE_HTML = """
<!doctype html>
<html lang="zh-CN">
<body>
<script>
(() => {
  "use strict";
  const reply = __REPLY__;
  try {
    const hostWindow = window.parent;
    const hostDocument = hostWindow.document;
    const Recognition = hostWindow.SpeechRecognition || hostWindow.webkitSpeechRecognition;
    const setInputValue = (value) => {
      const input = hostDocument.querySelector('input[placeholder="输入出行需求…"]');
      if (!input) return;
      const setter = Object.getOwnPropertyDescriptor(
        hostWindow.HTMLInputElement.prototype,
        "value"
      ).set;
      setter.call(input, value);
      input.dispatchEvent(new hostWindow.InputEvent("input", { bubbles: true, data: value }));
      input.dispatchEvent(new hostWindow.Event("change", { bubbles: true }));
      input.focus();
    };

        const bindVoiceButton = (remainingTries = 40) => {
            const button = hostDocument.getElementById("drivemate-voice-trigger");
            if (!button) {
                if (remainingTries > 0) hostWindow.setTimeout(() => bindVoiceButton(remainingTries - 1), 100);
                return;
            }
            if (Recognition) {
                button.disabled = false;
                button.classList.remove("is-unavailable");
                button.classList.add("is-supported");
                button.title = "也可呼唤“小D小D”：点击开始中文语音识别";
                button.onclick = () => {
        const recognition = new Recognition();
        recognition.lang = "zh-CN";
        recognition.interimResults = false;
        recognition.continuous = false;
        button.classList.add("is-listening");
                button.title = "正在聆听…";
        recognition.onresult = (event) => {
          const transcript = Array.from(event.results)
            .map((item) => item[0] && item[0].transcript ? item[0].transcript : "")
            .join("")
            .trim();
          if (transcript) setInputValue(transcript);
                    button.title = transcript ? "已识别，请确认后发送" : "未识别到内容，请重试";
        };
        recognition.onerror = () => {
                    button.title = "语音识别不可用，请使用文字输入";
        };
        recognition.onend = () => button.classList.remove("is-listening");
        recognition.start();
                };
            } else {
                button.disabled = true;
                button.classList.add("is-unavailable");
                button.title = "当前浏览器不支持语音识别，请使用文字输入";
            }
        };
        bindVoiceButton();

    if (reply && "speechSynthesis" in hostWindow && "SpeechSynthesisUtterance" in hostWindow) {
      const storageKey = "drivemate-last-spoken-reply";
      if (hostWindow.sessionStorage.getItem(storageKey) !== reply) {
        hostWindow.sessionStorage.setItem(storageKey, reply);
        const utterance = new hostWindow.SpeechSynthesisUtterance(reply);
        utterance.lang = "zh-CN";
        utterance.rate = 1;
        hostWindow.speechSynthesis.cancel();
        hostWindow.speechSynthesis.speak(utterance);
      }
    }
  } catch (error) {
    console.warn("DriveMate voice bridge unavailable", error);
  }
})();
</script>
</body>
</html>
"""


def render_voice_bridge(reply: str) -> None:
    components.html(
        VOICE_BRIDGE_HTML.replace("__REPLY__", _script_json(reply)),
        height=0,
        scrolling=False,
    )


def render_drivemate_chat(context: WorkspaceContext) -> None:
    if context.state.pop("_clear_input", False):
        context.state.user_input = ""
    with st.container(key="chat_header"):
        title_col, online_col = st.columns([1.7, 0.55], gap="small")
        with title_col:
            st.markdown(
                """
                <span class="right-pane-marker"></span>
                <header class="dm-chat-title"><span>AI COPILOT</span><h1>DriveMate</h1></header>
                """,
                unsafe_allow_html=True,
            )
        with online_col:
            st.markdown(
                '<small class="dm-status dm-status-online"><i></i>在线</small>',
                unsafe_allow_html=True,
            )
    quick_actions = (
        context.owner_quick_actions
        if context.state.mode == "车主自驾"
        else context.taxi_quick_actions
    )
    st.markdown(
        "<div class='quick-heading'><span>常用场景</span><small>安全评估后执行</small></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<span class='quick-grid-anchor'></span>", unsafe_allow_html=True)
    quick_columns = st.columns(3, gap="small")
    selected = None
    for index, (label, message) in enumerate(quick_actions):
        column = quick_columns[index % len(quick_columns)]
        if column.button(
            label,
            key=f"quick_{context.state.mode}_{label}",
            use_container_width=True,
        ):
            selected = message
    if selected:
        context.submit_message(selected)

    messages = [
        message
        for message in context.state.messages
        if message.get("mode") == context.state.mode
    ]
    result = context.state.current_run
    is_processing = context.state.request_state in {"queued", "waiting"}
    visible_messages = (
        messages[:-1]
        if (
            result
            and not is_processing
            and messages
            and messages[-1].get("role") == "assistant"
        )
        else messages
    )
    with st.container(key="chat_thread", border=False):
        if visible_messages:
            for message in visible_messages[-6:]:
                avatar = (
                    context.drivemate_avatar
                    if message["role"] == "assistant"
                    else context.user_avatar
                )
                with st.chat_message(message["role"], avatar=avatar):
                    st.markdown(message["content"])
        if is_processing:
            with st.chat_message("assistant", avatar=context.drivemate_avatar):
                st.markdown("需求已收到，正在调用 DriveMate Agent。中控已切换到服务编排页。")
        elif context.state.request_error:
            with st.chat_message("assistant", avatar=context.drivemate_avatar):
                st.error(context.state.request_error)
        elif result:
            with st.chat_message("assistant", avatar=context.drivemate_avatar):
                render_current_reply(context, result)
                feedback_items = execution_feedback(result)
                if feedback_items:
                    feedback_markup = "".join(
                        f"<span class='execution-action-tag'>{_safe(feedback)}</span>"
                        for feedback in feedback_items
                    )
                    st.markdown(
                        "<div class='execution-feedback-panel'>"
                        "<strong>执行结果已同步</strong>"
                        f"<div class='execution-action-tags'>{feedback_markup}</div>"
                        "</div>",
                        unsafe_allow_html=True,
                    )
            if context.pending_steps(result) or result.get("pending_tools"):
                with st.chat_message("assistant", avatar=context.drivemate_avatar):
                    render_confirmation(context, result, "chat")
        else:
            with st.chat_message("assistant", avatar=context.drivemate_avatar):
                st.markdown(
                    "你好，我是小D。疲劳、舒适、补能或 Robotaxi 行程问题，"
                    "都可以直接告诉我。"
                )
    placeholder = "输入出行需求…"
    render_voice_bridge(str(result.get("reply") or "") if result else "")
    with st.container(key="agent_composer", border=False):
        st.markdown("<span class='composer-marker'></span>", unsafe_allow_html=True)
        st.text_input(
            "告诉 DriveMate 你的需求",
            key="user_input",
            placeholder=placeholder,
            label_visibility="collapsed",
        )
        st.markdown(
            """
            <button id="drivemate-voice-trigger" type="button" class="voice-ready is-unavailable" disabled title="正在检测浏览器语音能力" aria-label="语音输入">
              <i aria-hidden="true"></i>
            </button>
            """,
            unsafe_allow_html=True,
        )
        model_col, send_col = st.columns([1.05, 1.0], gap="small")
        with model_col:
            with st.container(key="chat_model_picker"):
                st.segmented_control(
                    "选择智能体模型",
                    options=list(context.engine_labels),
                    key="engine",
                    format_func=context.engine_labels.get,
                    on_change=context.handle_engine_change,
                    label_visibility="collapsed",
                )
        with send_col:
            send = st.button(
                "发送需求", type="primary", use_container_width=True
            )
    if send:
        context.submit_message(context.state.user_input)
