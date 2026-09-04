from __future__ import annotations

import math
import os
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, List

import streamlit as st

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DRIVEMATE_AVATAR = os.path.join(
    ROOT, "assets", "figma-hmi", "drivemate-logo.png"
)
USER_AVATAR = os.path.join(
    ROOT, "assets", "figma-hmi", "user-avatar-v4-transparent.png"
)

from api_client import BackendApiError, BackendClient, create_backend_client
from perception_fusion import (
    build_sensor_state,
)
from ui_chrome import render_header
from views.workspace import (
    WorkspaceContext,
    render_cockpit_context,
    render_command_workspace,
    render_drivemate_chat,
)
JsonObject = Dict[str, Any]

THEME_PALETTES: Dict[str, Dict[str, str]] = {
    "日间": {
        "bg": "#f2f8fc",
        "accent": "#4778f5",
        "text": "#203047",
        "muted": "#66768b",
        "wash_a": "rgba(253, 254, 255, 0.99)",
        "wash_b": "rgba(248, 252, 255, 0.84)",
        "wash_c": "rgba(238, 247, 253, 0.66)",
        "glass_panel": "rgba(255, 255, 255, 0.22)",
        "glass_card": "rgba(255, 255, 255, 0.15)",
        "glass_unit": "rgba(255, 255, 255, 0.09)",
        "edge_panel": "rgba(255, 255, 255, 0.48)",
        "edge_card": "rgba(255, 255, 255, 0.36)",
        "edge_unit": "rgba(255, 255, 255, 0.25)",
        "line": "rgba(69, 101, 137, 0.16)",
        "line_strong": "rgba(69, 101, 137, 0.26)",
        "chat_assistant_bg": "rgba(255, 255, 255, 0.86)",
        "chat_assistant_edge": "rgba(255, 255, 255, 0.7)",
        "shadow_panel": "0 18px 44px rgba(43, 76, 113, 0.13), inset 0 1px 0 rgba(255, 255, 255, 0.42)",
        "shadow_card": "0 8px 22px rgba(43, 76, 113, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.3)",
        "shadow_unit": "inset 0 1px 0 rgba(255, 255, 255, 0.28)",
    },
    "夜间": {
        "bg": "#101826",
        "accent": "#7fb2ff",
        "text": "#eef5ff",
        "muted": "#9aabc2",
        "wash_a": "rgba(13, 20, 34, 0.98)",
        "wash_b": "rgba(18, 31, 50, 0.9)",
        "wash_c": "rgba(7, 11, 19, 0.96)",
        "glass_panel": "rgba(14, 24, 40, 0.58)",
        "glass_card": "rgba(20, 34, 54, 0.5)",
        "glass_unit": "rgba(26, 44, 70, 0.52)",
        "edge_panel": "rgba(150, 185, 235, 0.24)",
        "edge_card": "rgba(150, 185, 235, 0.18)",
        "edge_unit": "rgba(150, 185, 235, 0.14)",
        "line": "rgba(155, 186, 226, 0.14)",
        "line_strong": "rgba(155, 186, 226, 0.24)",
        "chat_assistant_bg": "rgba(20, 34, 54, 0.78)",
        "chat_assistant_edge": "rgba(150, 185, 235, 0.22)",
        "shadow_panel": "0 20px 48px rgba(0, 0, 0, 0.34), inset 0 1px 0 rgba(255, 255, 255, 0.12)",
        "shadow_card": "0 10px 28px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.1)",
        "shadow_unit": "inset 0 1px 0 rgba(255, 255, 255, 0.1)",
    },
}

st.set_page_config(
    page_title="DriveMate",
    page_icon=DRIVEMATE_AVATAR,
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _load_theme() -> None:
    css_root = os.path.join(ROOT, "assets", "figma-hmi", "styles")
    css_paths = [
        os.path.join(css_root, filename)
        for filename in (
            "shared.css",
            "topbar.css",
            "cockpit.css",
            "command.css",
            "chat.css",
            "responsive.css",
        )
    ]
    cockpit_scene_path = os.path.join(
        ROOT, "assets", "figma-hmi", "cockpit-road-static-v1.png"
    )
    brand_path = os.path.join(
        ROOT, "assets", "figma-hmi", "drivemate-logo.png"
    )
    navigation_path = os.path.join(
        ROOT, "assets", "figma-hmi", "shanghai-route-map.svg"
    )
    import base64

    with open(brand_path, "rb") as image_file:
        brand_uri = "data:image/png;base64," + base64.b64encode(
            image_file.read()
        ).decode("ascii")
    with open(cockpit_scene_path, "rb") as image_file:
        cockpit_scene_uri = "data:image/png;base64," + base64.b64encode(
            image_file.read()
        ).decode("ascii")
    with open(navigation_path, "rb") as image_file:
        navigation_uri = "data:image/svg+xml;base64," + base64.b64encode(
            image_file.read()
        ).decode("ascii")
    if st.session_state.get("theme") not in THEME_PALETTES:
        st.session_state.theme = "日间"
    palette = THEME_PALETTES.get(
        st.session_state.get("theme", "日间"), THEME_PALETTES["日间"]
    )
    css_parts = []
    for css_path in css_paths:
        with open(css_path, encoding="utf-8") as css_file:
            css_parts.append(css_file.read())
    css = "\n".join(css_parts)
    css = (
        css.replace("__COCKPIT_SCENE__", cockpit_scene_uri)
        .replace("__BRAND_ICON__", brand_uri)
        .replace("__NAV_MAP__", navigation_uri)
    )
    css += f"""
    :root {{
      --bg: {palette["bg"]};
    --text: {palette["text"]};
    --muted: {palette["muted"]};
      --accent: {palette["accent"]};
      --cyan: {palette["accent"]};
    --glass-panel: {palette["glass_panel"]};
    --glass-card: {palette["glass_card"]};
    --glass-unit: {palette["glass_unit"]};
    --edge-panel: {palette["edge_panel"]};
    --edge-card: {palette["edge_card"]};
    --edge-unit: {palette["edge_unit"]};
    --line: {palette["line"]};
    --line-strong: {palette["line_strong"]};
    --chat-assistant-bg: {palette["chat_assistant_bg"]};
    --chat-assistant-edge: {palette["chat_assistant_edge"]};
    --shadow-panel: {palette["shadow_panel"]};
    --shadow-card: {palette["shadow_card"]};
    --shadow-unit: {palette["shadow_unit"]};
      --theme-wash-a: {palette["wash_a"]};
      --theme-wash-b: {palette["wash_b"]};
      --theme-wash-c: {palette["wash_c"]};
    }}
    """
    markup = f"<style>{css}</style>"
    if hasattr(st, "html"):
        st.html(markup)
    else:
        st.markdown(markup, unsafe_allow_html=True)


@st.cache_resource
def _get_client(
    api_mode: str,
    backend_url: str,
    api_token: str,
    timeout: str,
) -> BackendClient:
    try:
        timeout_seconds = float(timeout)
    except ValueError as exc:
        raise BackendApiError(
            "DRIVEMATE_API_TIMEOUT_SECONDS must be a number."
        ) from exc
    return create_backend_client(
        api_mode,
        backend_url,
        api_token,
        timeout_seconds,
    )


@st.cache_resource
def _get_agent_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=4, thread_name_prefix="drivemate-agent")


_load_theme()

API_MODE = os.environ.get("DRIVEMATE_API_MODE", "http").strip().lower()
BACKEND_URL = os.environ.get(
    "DRIVEMATE_BACKEND_URL", "http://127.0.0.1:8000"
).strip()
API_TOKEN = os.environ.get("DRIVEMATE_API_TOKEN", "").strip()
API_TIMEOUT = os.environ.get(
    "DRIVEMATE_API_TIMEOUT_SECONDS", "60"
).strip()

try:
    CLIENT = _get_client(API_MODE, BACKEND_URL, API_TOKEN, API_TIMEOUT)
except BackendApiError as exc:
    st.error(f"前端接口配置错误：{exc}")
    st.stop()

try:
    BACKEND_HEALTH = CLIENT.health()
    BACKEND_META = CLIENT.meta()
except BackendApiError as exc:
    BACKEND_HEALTH = {"ok": False, "summary": str(exc)}
    BACKEND_META = {"tool_count": 0}


DEFAULTS: JsonObject = {
    "mode": "车主自驾",
    "engine": "融合编排引擎（本地可审计）",
    "theme": "日间",
    "center_view": "导航",
    "center_view_control": "导航",
    "requested_center_view": None,
    "speed": 80,
    "soc": 80,
    "range_km": 450,
    "drive_hours": 3.5,
    "trip_km": 0.0,
    "_simulation_last_tick": None,
    "child_seat": False,
    "cabin_temp": 24.0,
    "fan_level": 2,
    "seat_angle": 105,
    "window_percent": 0,
    "ambient_light": 60,
    "media_status": "待机",
    "order_status": "无订单",
    "passenger_loc": "上海虹桥火车站 2F 出发层",
    "vehicle_loc": "上海虹桥火车站",
    "destination": "上海外滩",
    "passenger_lat": 31.19690,
    "passenger_lng": 121.32680,
    "vehicle_lat": 31.19700,
    "vehicle_lng": 121.32700,
    "weather": "晴",
    "traffic": "畅通",
    "time_of_day": "日间",
    "area_type": "高速",
    "parking_policy": "允许临停",
    "dms_fatigue": 72,
    "audio_fatigue": 68,
    "steering_stability": 74,
    "visibility": 92,
    "passenger_match": 88,
    "distress_probability": 18,
    "location_confidence": 96,
    "curb_risk": 24,
    "user_input": "",
    "current_run": None,
    "result": None,
    "last_snapshot": None,
    "last_run": None,
    "messages": [],
    "agent_session_id": None,
    "request_state": "idle",
    "request_error": "",
    "pending_request": None,
    "pending_future": None,
    "voice_state": "unavailable",
    "_critical_notice_run_id": None,
    "_clear_input": False,
}
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)

if st.session_state.requested_center_view:
    st.session_state.center_view = st.session_state.requested_center_view
    st.session_state.center_view_control = st.session_state.requested_center_view
    st.session_state.requested_center_view = None


OWNER_QUICK_ACTIONS = [
    ("我有点困", "我连续驾驶有些困倦，请先评估安全并给我建议"),
    ("调节车内温度", "车内有点热，请帮我把温度调得舒适一些"),
    ("规划沿途补能", "请根据当前电量规划沿途补能"),
    ("带孩子出行", "带孩子出行，请帮我检查并设置舒适安全的座舱环境"),
    ("查看车辆状态", "请告诉我当前车辆和行驶状态"),
    ("开始路线导航", "请根据当前目的地规划路线"),
]
TAXI_QUICK_ACTIONS = [
    ("我找不到车", "我找不到接驾车辆，请帮我定位"),
    ("修改上车点", "我需要修改上车点"),
    ("修改目的地", "我需要修改本次行程目的地"),
    ("车内不舒服", "我在车内感觉不舒服，需要帮助"),
    ("联系人工客服", "请帮我联系人工客服"),
    ("查看行程状态", "请查询当前 Robotaxi 订单状态与车辆位置"),
]
LOCAL_ENGINE = "融合编排引擎（本地可审计）"
BAILIAN_ENGINE = "百炼应用（App API）"
ALL_ENGINE_LABELS = {
    LOCAL_ENGINE: "融合编排",
    BAILIAN_ENGINE: "外接模型",
}
available_engines = BACKEND_META.get("engines")
AVAILABLE_ENGINES = (
    frozenset(str(name) for name in available_engines)
    if isinstance(available_engines, list)
    else frozenset({LOCAL_ENGINE})
)
ENGINE_LABELS = dict(ALL_ENGINE_LABELS)
BAILIAN_AVAILABLE = BAILIAN_ENGINE in AVAILABLE_ENGINES
BAILIAN_UNAVAILABLE_MESSAGE = (
    "外接模型未在当前后端启用。请配置DASHSCOPE_API_KEY，"
    "并通过 start_demo.py 重启完整服务。"
)
if st.session_state.engine not in ENGINE_LABELS:
    st.session_state.engine = LOCAL_ENGINE
STATUS_LABELS = {
    "pending": "等待执行",
    "active": "正在执行",
    "done": "已完成",
    "pending_confirm": "等待确认",
    "blocked": "已安全拦截",
    "failed": "执行失败",
    "degraded": "已切换备用方案",
    "cancelled": "已取消",
    "waiting_confirmation": "等待确认",
    "completed": "已完成",
    "confirming": "正在确认",
    "cancelling": "正在取消",
}
RISK_LABELS = {
    "L0": "低风险",
    "L1": "需要关注",
    "L2": "高风险",
    "L3": "紧急风险",
}
def reset_mode_context() -> None:
    future = st.session_state.get("pending_future")
    if isinstance(future, Future):
        future.cancel()
    st.session_state.current_run = None
    st.session_state.result = None
    st.session_state.last_snapshot = None
    st.session_state.last_run = None
    st.session_state.request_error = ""
    st.session_state.pending_request = None
    st.session_state.pending_future = None
    st.session_state.agent_session_id = None
    st.session_state._clear_input = True
    st.session_state.center_view = "导航"
    st.session_state.center_view_control = "导航"
    st.session_state.trip_km = 0.0
    st.session_state._simulation_last_tick = None
    if st.session_state.mode == "Robotaxi 乘客":
        st.session_state.order_status = "arriving（即将到达）"
        st.session_state.speed = 72
    else:
        st.session_state.order_status = "无订单"
        st.session_state.speed = 96


def switch_to_tools() -> None:
    st.session_state.center_view = "服务编排"


def sync_center_view() -> None:
    st.session_state.center_view = st.session_state.center_view_control


def sync_cabin_temp() -> None:
    st.session_state.cabin_temp = st.session_state.cabin_temp_control


def sync_seat_angle() -> None:
    st.session_state.seat_angle = st.session_state.seat_angle_control


def sync_window_percent() -> None:
    st.session_state.window_percent = st.session_state.window_percent_control


def sync_ambient_light() -> None:
    st.session_state.ambient_light = st.session_state.ambient_light_control


def apply_state_diff_to_preview(result: JsonObject) -> None:
    state_diff = result.get("state_diff")
    if not isinstance(state_diff, dict):
        return
    climate_change = state_diff.get("climate.temperature")
    if isinstance(climate_change, dict):
        updated_temperature = climate_change.get("after")
        if isinstance(updated_temperature, (int, float)):
            st.session_state.cabin_temp = float(updated_temperature)
            st.session_state.cabin_temp_control = float(updated_temperature)
    for path in ("climate.fan_level", "climate.fan"):
        fan_change = state_diff.get(path)
        if isinstance(fan_change, dict) and isinstance(
            fan_change.get("after"), (int, float)
        ):
            st.session_state.fan_level = int(fan_change["after"])
            break
    for path in (
        "seat.driver_backrest_angle",
        "seat.driver_angle",
        "seat.angle",
    ):
        seat_change = state_diff.get(path)
        if isinstance(seat_change, dict) and isinstance(
            seat_change.get("after"), (int, float)
        ):
            st.session_state.seat_angle = int(seat_change["after"])
            st.session_state.seat_angle_control = int(seat_change["after"])
            break
    window_change = state_diff.get("window.open_percent")
    if isinstance(window_change, dict) and isinstance(
        window_change.get("after"), (int, float)
    ):
        st.session_state.window_percent = int(window_change["after"])
        st.session_state.window_percent_control = int(window_change["after"])
    ambient_change = state_diff.get("ambient_light.brightness")
    if isinstance(ambient_change, dict) and isinstance(
        ambient_change.get("after"), (int, float)
    ):
        st.session_state.ambient_light = int(ambient_change["after"])
        st.session_state.ambient_light_control = int(ambient_change["after"])
    media_change = state_diff.get("media.playing")
    if isinstance(media_change, dict) and isinstance(media_change.get("after"), bool):
        st.session_state.media_status = (
            "播放中" if media_change["after"] else "已暂停"
        )
    navigation_change = state_diff.get("navigation.destination")
    if isinstance(navigation_change, dict):
        destination = navigation_change.get("after")
        if isinstance(destination, str) and destination.strip():
            st.session_state.destination = destination.strip()
    vehicle_location_change = state_diff.get("order.vehicle_location")
    if isinstance(vehicle_location_change, dict):
        vehicle_location = vehicle_location_change.get("after")
        if isinstance(vehicle_location, str) and vehicle_location.strip():
            st.session_state.vehicle_loc = vehicle_location.strip()


def build_snapshot() -> JsonObject:
    snapshot = {
        "identity": {
            "mode": (
                "OWNER_DRIVE"
                if st.session_state.mode == "车主自驾"
                else "ROBOTAXI_RIDE"
            ),
            "user_id": "frontend_preview_user",
            "auth_level": (
                "vin_bound"
                if st.session_state.mode == "车主自驾"
                else "order_token"
            ),
        },
        "vehicle_state": {
            "speed_kmh": st.session_state.speed,
            "soc_percent": st.session_state.soc,
            "range_km": st.session_state.range_km,
            "driving_hours": st.session_state.drive_hours,
            "child_seat_detected": st.session_state.child_seat,
        },
        "order_state": {
            "status": st.session_state.order_status,
            "passenger_location": st.session_state.passenger_loc,
            "vehicle_location": st.session_state.vehicle_loc,
            "destination": st.session_state.destination,
            "passenger_coordinates": {
                "lat": st.session_state.passenger_lat,
                "lng": st.session_state.passenger_lng,
            },
            "vehicle_coordinates": {
                "lat": st.session_state.vehicle_lat,
                "lng": st.session_state.vehicle_lng,
            },
        },
        "environment_state": {
            "weather": st.session_state.weather,
            "traffic": st.session_state.traffic,
            "time_of_day": st.session_state.time_of_day,
            "area_type": st.session_state.area_type,
            "parking_policy": st.session_state.parking_policy,
        },
    }
    snapshot["sensor_state"] = build_sensor_state(
        st.session_state.mode,
        snapshot["vehicle_state"],
        snapshot["environment_state"],
        snapshot["order_state"],
        {
            "dms_fatigue": st.session_state.dms_fatigue,
            "audio_fatigue": st.session_state.audio_fatigue,
            "steering_stability": st.session_state.steering_stability,
            "visibility": st.session_state.visibility,
            "cabin_temperature_c": st.session_state.cabin_temp,
            "passenger_match": st.session_state.passenger_match,
            "distress_probability": st.session_state.distress_probability,
            "location_confidence": st.session_state.location_confidence,
            "curb_risk": st.session_state.curb_risk,
        },
        simulated=True,
        source="frontend_demo_bus",
    )
    return snapshot


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    delta_p = math.radians(lat2 - lat1)
    delta_l = math.radians(lng2 - lng1)
    value = (
        math.sin(delta_p / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(delta_l / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def enrich_result(result: JsonObject, snapshot: JsonObject, mode: str) -> JsonObject:
    enriched = dict(result)
    enriched["snapshot"] = snapshot
    enriched["mode"] = mode
    return enriched


def submit_message(message: str) -> None:
    message = message.strip()
    if not message:
        st.session_state.request_error = "请输入需求后再发送。"
        return
    if st.session_state.engine == BAILIAN_ENGINE and not BAILIAN_AVAILABLE:
        st.session_state.request_error = BAILIAN_UNAVAILABLE_MESSAGE
        return
    if st.session_state.pending_request:
        st.session_state.request_error = "上一条需求仍在处理中，请稍候。"
        return
    st.session_state.pending_request = {
        "message": message,
        "mode": st.session_state.mode,
        "engine": st.session_state.engine,
        "snapshot": build_snapshot(),
    }
    st.session_state.request_state = "queued"
    st.session_state.request_error = ""
    st.session_state.messages.append(
        {"role": "user", "content": message, "mode": st.session_state.mode}
    )
    st.session_state.center_view = "服务编排"
    st.session_state.requested_center_view = "服务编排"
    st.session_state._clear_input = True
    st.rerun()


def handle_engine_change() -> None:
    if st.session_state.engine == BAILIAN_ENGINE and not BAILIAN_AVAILABLE:
        st.session_state.request_error = BAILIAN_UNAVAILABLE_MESSAGE
    elif st.session_state.request_error == BAILIAN_UNAVAILABLE_MESSAGE:
        st.session_state.request_error = ""


def process_pending_request() -> None:
    pending = st.session_state.pending_request
    if not isinstance(pending, dict):
        return
    message = str(pending["message"])
    mode = str(pending["mode"])
    engine = str(pending["engine"])
    snapshot = pending["snapshot"]
    st.session_state.request_state = "waiting"
    future = st.session_state.get("pending_future")
    if not isinstance(future, Future):
        st.session_state.pending_future = _get_agent_executor().submit(
            CLIENT.run_agent,
            message,
            mode,
            engine,
            snapshot,
            st.session_state.agent_session_id,
        )
        return
    if not future.done():
        return
    try:
        result = future.result()
    except Exception as exc:
        st.session_state.pending_request = None
        st.session_state.pending_future = None
        st.session_state.request_state = "error"
        detail = str(exc) if isinstance(exc, BackendApiError) else "Agent 执行异常"
        st.session_state.request_error = f"请求失败：{detail}，请重试。"
        st.rerun()
        return
    enriched = enrich_result(result, snapshot, mode)
    apply_state_diff_to_preview(enriched)
    st.session_state.current_run = enriched
    st.session_state.agent_session_id = result.get("session_id")
    st.session_state.result = enriched
    st.session_state.last_snapshot = snapshot
    st.session_state.last_run = {
        "message": message,
        "mode": mode,
        "run_id": result["run_id"],
    }
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result["reply"],
            "mode": mode,
            "run_id": result["run_id"],
        }
    )
    st.session_state.pending_request = None
    st.session_state.pending_future = None
    st.session_state.center_view = "安全守护"
    st.session_state.requested_center_view = "安全守护"
    st.session_state.request_state = "idle"
    st.rerun()


def update_run(action: str) -> None:
    result = st.session_state.current_run
    if not result:
        return
    st.session_state.request_state = action
    st.session_state.request_error = ""
    st.session_state.center_view = "服务编排"
    st.session_state.requested_center_view = "服务编排"
    st.session_state.messages.append(
        {
            "role": "user",
            "content": "确认执行" if action == "confirming" else "取消操作",
            "mode": result["mode"],
        }
    )
    try:
        with st.spinner("正在提交确认…" if action == "confirming" else "正在取消操作…"):
            if action == "confirming":
                snapshot = build_snapshot()
                updated = CLIENT.confirm_run(result["run_id"], snapshot)
                enriched = enrich_result(updated, snapshot, result["mode"])
            else:
                updated = CLIENT.cancel_run(result["run_id"])
                enriched = enrich_result(updated, result["snapshot"], result["mode"])
    except BackendApiError as exc:
        verb = "确认" if action == "confirming" else "取消"
        st.session_state.request_state = "error"
        st.session_state.request_error = f"{verb}失败：{exc}"
        st.error(st.session_state.request_error)
        return
    st.session_state.current_run = enriched
    st.session_state.result = enriched
    apply_state_diff_to_preview(enriched)
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": updated["reply"],
            "mode": result["mode"],
            "run_id": result["run_id"],
        }
    )
    st.session_state.center_view = "安全守护"
    st.session_state.requested_center_view = "安全守护"
    st.session_state.request_state = "idle"
    st.rerun()


def pending_steps(result: JsonObject) -> List[JsonObject]:
    return [
        step
        for step in result.get("steps", [])
        if step.get("status") == "pending_confirm"
    ]


def enforce_critical_safety_event() -> None:
    result = st.session_state.current_run
    if not isinstance(result, dict):
        return
    risk_level = str(result.get("risk_level") or "").strip().lower()
    if risk_level not in {"l3", "critical"}:
        return
    run_id = str(result.get("run_id") or "critical-event")
    if st.session_state._critical_notice_run_id == run_id:
        return
    st.session_state._critical_notice_run_id = run_id
    st.session_state.center_view = "安全守护"
    st.session_state.center_view_control = "安全守护"
    st.toast("检测到严重安全事件，已切换至安全守护。", icon="⚠️")


def _advance_local_simulation() -> None:
    now = time.monotonic()
    previous = st.session_state._simulation_last_tick
    st.session_state._simulation_last_tick = now
    if not isinstance(previous, (int, float)):
        return
    elapsed_seconds = min(max(now - previous, 0.0), 60.0)
    if elapsed_seconds <= 0:
        return
    target_speed = 72.0 if st.session_state.mode == "Robotaxi 乘客" else 96.0
    natural_variation = math.sin(now * 0.72) * 1.4
    blend = min(1.0, elapsed_seconds * 0.38)
    current_speed = float(st.session_state.speed)
    updated_speed = current_speed + (target_speed + natural_variation - current_speed) * blend
    distance_delta = max(updated_speed, 0.0) * elapsed_seconds / 3600
    st.session_state.speed = round(updated_speed, 1)
    st.session_state.trip_km = round(float(st.session_state.trip_km) + distance_delta, 3)
    st.session_state.drive_hours = round(
        float(st.session_state.drive_hours) + elapsed_seconds / 3600,
        4,
    )
    st.session_state.soc = round(
        max(0.0, float(st.session_state.soc) - elapsed_seconds * 0.00035),
        2,
    )
    st.session_state.range_km = round(
        max(0.0, float(st.session_state.range_km) - distance_delta * 0.16),
        2,
    )



enforce_critical_safety_event()
WORKSPACE = WorkspaceContext(
    state=st.session_state,
    api_mode=API_MODE,
    client=CLIENT,
    drivemate_avatar=DRIVEMATE_AVATAR,
    user_avatar=USER_AVATAR,
    owner_quick_actions=OWNER_QUICK_ACTIONS,
    taxi_quick_actions=TAXI_QUICK_ACTIONS,
    engine_labels=ENGINE_LABELS,
    status_labels=STATUS_LABELS,
    risk_labels=RISK_LABELS,
    submit_message=submit_message,
    handle_engine_change=handle_engine_change,
    update_run=update_run,
    sync_cabin_temp=sync_cabin_temp,
    sync_seat_angle=sync_seat_angle,
    sync_window_percent=sync_window_percent,
    sync_ambient_light=sync_ambient_light,
    sync_center_view=sync_center_view,
    build_snapshot=build_snapshot,
    pending_steps=pending_steps,
    advance_simulation=_advance_local_simulation,
)
render_header(
    backend_health=BACKEND_HEALTH,
    backend_meta=BACKEND_META,
    api_mode=API_MODE,
    theme_options=tuple(THEME_PALETTES),
    reset_mode_context=reset_mode_context,
)

if not BACKEND_HEALTH.get("ok") and BACKEND_HEALTH.get("summary"):
    st.error(
        f"后端未连接：{BACKEND_HEALTH['summary']}。你仍可编辑输入和查看已有历史。"
    )

cockpit_column, command_column, chat_column = st.columns(
    [30, 45, 25], gap="small"
)
with cockpit_column:
    render_cockpit_context(WORKSPACE)
with command_column:
    render_command_workspace(WORKSPACE)
with chat_column:
    render_drivemate_chat(WORKSPACE)

@st.fragment(run_every=0.5)
def poll_pending_request() -> None:
    process_pending_request()


poll_pending_request()
