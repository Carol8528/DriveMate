from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import fmean, pstdev
from typing import Any, Dict, List, Optional, Tuple


JsonObject = Dict[str, Any]

INTENT_ALIASES = {
    "charging_plan": "charging",
    "climate_comfort": "climate",
    "family_trip": "parent_child",
    "modify_trip": "reroute",
}

INTENT_LABELS = {
    "charging": "补能规划",
    "climate": "座舱舒适",
    "context": "环境态势",
    "fatigue": "疲劳驾驶",
    "find_car": "人车会合",
    "medical": "紧急求助",
    "modify_pickup": "上车点安全",
    "parent_child": "儿童安全",
    "passenger_comfort": "乘客舒适",
    "reroute": "行程变更",
    "vehicle_status": "车辆状态",
    "route_plan": "路线导航",
    "human_support": "人工客服",
    "trip_status": "行程状态",
}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _number(value)))


def _ratio_percent(value: Any) -> float:
    numeric = _number(value)
    return _clamp(numeric * 100 if 0 <= numeric <= 1 else numeric)


def _distance_m(order_state: JsonObject) -> Optional[float]:
    passenger = order_state.get("passenger_coordinates")
    vehicle = order_state.get("vehicle_coordinates")
    if not isinstance(passenger, dict) or not isinstance(vehicle, dict):
        return None
    try:
        lat1, lng1 = float(passenger["lat"]), float(passenger["lng"])
        lat2, lng2 = float(vehicle["lat"]), float(vehicle["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    radius_m = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    delta_p = math.radians(lat2 - lat1)
    delta_l = math.radians(lng2 - lng1)
    value = (
        math.sin(delta_p / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(delta_l / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def build_sensor_state(
    mode: str,
    vehicle_state: JsonObject,
    environment_state: JsonObject,
    order_state: JsonObject,
    controls: Optional[JsonObject] = None,
    *,
    simulated: bool = True,
    source: str = "demo_sensor_bus",
) -> JsonObject:
    controls = controls or {}
    captured_at = datetime.now(timezone.utc).isoformat()
    weather = str(environment_state.get("weather") or "未知")
    time_of_day = str(environment_state.get("time_of_day") or "未知")
    visibility = _clamp(controls.get("visibility", 92))
    cabin_temperature = _number(controls.get("cabin_temperature_c"), 24)

    if mode == "Robotaxi 乘客":
        passenger_match = _clamp(controls.get("passenger_match", 88))
        distress = _clamp(controls.get("distress_probability", 18))
        location_confidence = _clamp(controls.get("location_confidence", 96))
        parking_policy = str(environment_state.get("parking_policy") or "未知")
        curb_risk = 84 if any(
            term in parking_policy for term in ("禁停", "禁止", "不允许")
        ) else _clamp(controls.get("curb_risk", 24))
        streams = [
            {
                "id": "surround_camera",
                "modality": "video",
                "label": "环视视觉",
                "source": "AVM-04",
                "status": "online",
                "confidence": 94,
                "latency_ms": 36,
                "readings": {
                    "passenger_match_probability": passenger_match / 100,
                    "pedestrian_zone_clear": curb_risk < 60,
                },
            },
            {
                "id": "passenger_audio",
                "modality": "audio",
                "label": "座舱音频",
                "source": "MIC-ARRAY",
                "status": "online",
                "confidence": 86,
                "latency_ms": 52,
                "readings": {
                    "distress_probability": distress / 100,
                    "discomfort_probability": max(12, distress - 6) / 100,
                },
            },
            {
                "id": "gnss_order",
                "modality": "position",
                "label": "GNSS / 订单",
                "source": "TSP-GNSS",
                "status": "online",
                "confidence": 98,
                "latency_ms": 18,
                "readings": {
                    "location_confidence": location_confidence / 100,
                    "distance_m": _distance_m(order_state),
                    "order_status": order_state.get("status"),
                },
            },
            {
                "id": "road_context",
                "modality": "environment",
                "label": "道路语义",
                "source": "MAP-CAM",
                "status": "online",
                "confidence": 92,
                "latency_ms": 64,
                "readings": {
                    "curb_risk": curb_risk / 100,
                    "visibility": visibility / 100,
                    "weather": weather,
                    "parking_policy": parking_policy,
                },
            },
        ]
    else:
        fatigue = _clamp(controls.get("dms_fatigue", 72))
        audio_fatigue = _clamp(controls.get("audio_fatigue", 68))
        steering_stability = _clamp(controls.get("steering_stability", 74))
        streams = [
            {
                "id": "dms_camera",
                "modality": "video",
                "label": "DMS监测",
                "source": "DMS-01",
                "status": "online",
                "confidence": 96,
                "latency_ms": 32,
                "readings": {
                    "fatigue_probability": fatigue / 100,
                    "eye_closure_ratio": min(0.48, 0.08 + fatigue * 0.0042),
                    "blink_rate_per_min": round(12 + fatigue * 0.12),
                },
            },
            {
                "id": "cabin_audio",
                "modality": "audio",
                "label": "座舱音频",
                "source": "MIC-ARRAY",
                "status": "online",
                "confidence": 89,
                "latency_ms": 48,
                "readings": {
                    "yawn_probability": audio_fatigue / 100,
                    "speech_fatigue_probability": max(0, audio_fatigue - 8) / 100,
                    "distress_probability": max(0, audio_fatigue - 52) / 200,
                },
            },
            {
                "id": "vehicle_telemetry",
                "modality": "telemetry",
                "label": "CAN 车辆遥测",
                "source": "CAN-GW",
                "status": "online",
                "confidence": 99,
                "latency_ms": 12,
                "readings": {
                    "driving_hours": _number(vehicle_state.get("driving_hours")),
                    "speed_kmh": _number(vehicle_state.get("speed_kmh")),
                    "soc_percent": _number(vehicle_state.get("soc_percent"), 100),
                    "range_km": _number(vehicle_state.get("range_km"), 999),
                    "steering_stability": steering_stability / 100,
                },
            },
            {
                "id": "environment_sensor",
                "modality": "environment",
                "label": "环境感知",
                "source": "ENV-GNSS",
                "status": "online",
                "confidence": 94,
                "latency_ms": 61,
                "readings": {
                    "visibility": visibility / 100,
                    "weather": weather,
                    "time_of_day": time_of_day,
                    "cabin_temperature_c": cabin_temperature,
                },
            },
        ]

    return {
        "schema_version": "1.0",
        "captured_at": captured_at,
        "source": source,
        "simulated": simulated,
        "streams": streams,
    }


def _stream_hypotheses(stream: JsonObject) -> JsonObject:
    stream_id = str(stream.get("id") or "")
    readings = stream.get("readings")
    readings = readings if isinstance(readings, dict) else {}
    hypotheses: JsonObject = {}

    if stream_id == "dms_camera":
        hypotheses["fatigue"] = _ratio_percent(readings.get("fatigue_probability"))
    elif stream_id == "cabin_audio":
        hypotheses["fatigue"] = max(
            _ratio_percent(readings.get("yawn_probability")),
            _ratio_percent(readings.get("speech_fatigue_probability")),
        )
        hypotheses["medical"] = _ratio_percent(readings.get("distress_probability"))
    elif stream_id == "vehicle_telemetry":
        hours = _number(readings.get("driving_hours"))
        stability_risk = 100 - _ratio_percent(readings.get("steering_stability"))
        hypotheses["fatigue"] = _clamp(max(hours / 4 * 82, stability_risk * 1.1))
        soc = _number(readings.get("soc_percent"), 100)
        range_km = _number(readings.get("range_km"), 999)
        hypotheses["charging"] = _clamp(
            max((35 - soc) / 35 * 100, (120 - range_km) / 120 * 100)
        )
        hypotheses["vehicle_status"] = 96
    elif stream_id == "environment_sensor":
        visibility_risk = 100 - _ratio_percent(readings.get("visibility"))
        night_bonus = 28 if readings.get("time_of_day") == "夜间" else 8
        hypotheses["fatigue"] = _clamp(max(visibility_risk, night_bonus))
        temperature = _number(readings.get("cabin_temperature_c"), 22)
        hypotheses["climate"] = _clamp(abs(temperature - 22) * 18)
    elif stream_id == "surround_camera":
        hypotheses["find_car"] = _ratio_percent(
            readings.get("passenger_match_probability")
        )
    elif stream_id == "passenger_audio":
        hypotheses["medical"] = _ratio_percent(readings.get("distress_probability"))
        hypotheses["passenger_comfort"] = _ratio_percent(
            readings.get("discomfort_probability")
        )
    elif stream_id == "gnss_order":
        hypotheses["find_car"] = _ratio_percent(
            readings.get("location_confidence")
        )
        hypotheses["reroute"] = 48
    elif stream_id == "road_context":
        hypotheses["modify_pickup"] = _ratio_percent(readings.get("curb_risk"))
        hypotheses["find_car"] = _ratio_percent(readings.get("visibility")) * 0.72

    return {key: round(_clamp(value), 1) for key, value in hypotheses.items()}


def _signal_and_value(stream_id: str, readings: JsonObject) -> Tuple[str, str]:
    if stream_id == "dms_camera":
        fatigue = round(_ratio_percent(readings.get("fatigue_probability")))
        closure = round(_ratio_percent(readings.get("eye_closure_ratio")))
        return f"疲劳特征 {fatigue}% · 闭眼占比 {closure}%", f"{fatigue}%"
    if stream_id == "cabin_audio":
        yawn = round(_ratio_percent(readings.get("yawn_probability")))
        return f"哈欠声纹 {yawn}% · 语音疲劳线索", f"{yawn}%"
    if stream_id == "vehicle_telemetry":
        hours = _number(readings.get("driving_hours"))
        stability = round(_ratio_percent(readings.get("steering_stability")))
        return f"连续驾驶 {hours:g} h · 操稳 {stability}%", f"{hours:g} h"
    if stream_id == "environment_sensor":
        visibility = round(_ratio_percent(readings.get("visibility")))
        return (
            f"{readings.get('weather', '未知')} · {readings.get('time_of_day', '未知')} · 可见度 {visibility}%",
            f"{visibility}%",
        )
    if stream_id == "surround_camera":
        match = round(
            _ratio_percent(readings.get("passenger_match_probability"))
        )
        return f"候车人视觉匹配 {match}%", f"{match}%"
    if stream_id == "passenger_audio":
        distress = round(_ratio_percent(readings.get("distress_probability")))
        return f"求助声学线索 {distress}%", f"{distress}%"
    if stream_id == "gnss_order":
        confidence = round(_ratio_percent(readings.get("location_confidence")))
        distance = readings.get("distance_m")
        distance_text = f"{_number(distance):.0f} m" if distance is not None else "待定位"
        return f"位置可信 {confidence}% · 人车 {distance_text}", distance_text
    if stream_id == "road_context":
        curb_risk = round(_ratio_percent(readings.get("curb_risk")))
        return f"{readings.get('parking_policy', '未知')} · 路缘风险 {curb_risk}%", f"{curb_risk}%"
    return "等待有效读数", "—"


def fuse_perception(
    snapshot: JsonObject,
    intent: Optional[str] = None,
) -> JsonObject:
    sensor_state = snapshot.get("sensor_state")
    if not isinstance(sensor_state, dict):
        identity = snapshot.get("identity")
        identity = identity if isinstance(identity, dict) else {}
        mode = (
            "Robotaxi 乘客"
            if identity.get("mode") == "ROBOTAXI_RIDE"
            else "车主自驾"
        )
        sensor_state = build_sensor_state(
            mode,
            snapshot.get("vehicle_state")
            if isinstance(snapshot.get("vehicle_state"), dict)
            else {},
            snapshot.get("environment_state")
            if isinstance(snapshot.get("environment_state"), dict)
            else {},
            snapshot.get("order_state")
            if isinstance(snapshot.get("order_state"), dict)
            else {},
            source="snapshot_adapter",
        )

    raw_streams = sensor_state.get("streams")
    raw_streams = raw_streams if isinstance(raw_streams, list) else []
    modalities: List[JsonObject] = []
    hypothesis_values: Dict[str, List[Tuple[float, float]]] = {}

    for raw_stream in raw_streams:
        if not isinstance(raw_stream, dict):
            continue
        confidence = round(_clamp(raw_stream.get("confidence")))
        status = str(raw_stream.get("status") or "offline")
        readings = raw_stream.get("readings")
        readings = readings if isinstance(readings, dict) else {}
        hypotheses = _stream_hypotheses(raw_stream)
        signal, value = _signal_and_value(str(raw_stream.get("id") or ""), readings)
        modality = {
            "id": str(raw_stream.get("id") or "unknown"),
            "modality": str(raw_stream.get("modality") or "sensor"),
            "label": str(raw_stream.get("label") or "未命名传感器"),
            "source": str(raw_stream.get("source") or "unknown"),
            "status": status,
            "confidence": confidence,
            "latency_ms": round(_clamp(raw_stream.get("latency_ms"), 0, 10_000)),
            "signal": signal,
            "value": value,
            "hypotheses": hypotheses,
        }
        modalities.append(modality)
        if status == "online":
            for hypothesis, score in hypotheses.items():
                hypothesis_values.setdefault(hypothesis, []).append(
                    (_number(score), confidence)
                )

    aggregate: JsonObject = {}
    for hypothesis, values in hypothesis_values.items():
        weight = sum(confidence for _, confidence in values)
        aggregate[hypothesis] = round(
            sum(score * confidence for score, confidence in values) / weight
            if weight
            else 0,
            1,
        )

    canonical_intent = INTENT_ALIASES.get(str(intent or ""), str(intent or ""))
    if canonical_intent and (
        canonical_intent in aggregate or canonical_intent in INTENT_LABELS
    ):
        focus = canonical_intent
    elif aggregate:
        support_counts = {
            key: sum(score >= 20 for score, _ in hypothesis_values.get(key, []))
            for key in aggregate
        }
        focus = max(
            aggregate,
            key=lambda key: aggregate[key] * min(1.0, support_counts[key] / 2),
        )
    else:
        focus = "context"

    online = [item for item in modalities if item["status"] == "online"]
    relevant_scores = [
        _number(item["hypotheses"].get(focus))
        for item in online
        if _number(item["hypotheses"].get(focus)) >= 20
    ]
    supporting = len(relevant_scores)
    source_confidence = round(
        fmean(item["confidence"] for item in online) if online else 0
    )
    max_latency = max((item["latency_ms"] for item in online), default=0)
    temporal_alignment = round(
        _clamp(source_confidence + 3 - min(12, max_latency / 16))
    )
    agreement = round(
        _clamp(
            100 - (pstdev(relevant_scores) * 0.9)
            if len(relevant_scores) > 1
            else 74 if relevant_scores else 55
        )
    )
    coverage = len(online) / len(modalities) if modalities else 0
    corroboration = min(100, supporting / 3 * 100)
    fusion_confidence = round(
        _clamp(
            source_confidence * 0.45
            + temporal_alignment * 0.15
            + agreement * 0.2
            + corroboration * 0.2
        )
    )
    if coverage < 1:
        fusion_confidence = round(fusion_confidence * coverage)

    weighted_relevance = [
        _number(item["hypotheses"].get(focus)) * _number(item["confidence"])
        for item in modalities
    ]
    relevance_total = sum(weighted_relevance)
    for item, relevance in zip(modalities, weighted_relevance):
        item["contribution"] = (
            round(relevance / relevance_total * 100) if relevance_total else 0
        )
        item["relevance"] = round(
            _number(item["hypotheses"].get(focus)), 1
        )

    evidence_sources = sorted(
        modalities,
        key=lambda item: (item["relevance"], item["confidence"]),
        reverse=True,
    )
    evidence = [
        f"{item['label']}：{item['signal']}（输入置信度 {item['confidence']}%）"
        for item in evidence_sources
        if item["relevance"] >= 20
    ][:4]
    if not evidence:
        evidence = [
            f"{item['label']}：{item['signal']}（输入置信度 {item['confidence']}%）"
            for item in evidence_sources[:3]
        ]

    source_names = [item["label"] for item in evidence_sources if item["relevance"] >= 20][:3]
    if source_names:
        primary_finding = (
            "、".join(source_names)
            + f"共同支持“{INTENT_LABELS.get(focus, focus)}”判断"
        )
    else:
        primary_finding = "多路感知已完成时空对齐，等待任务提供决策焦点"

    return {
        "schema_version": "1.0",
        "status": "fused" if online else "unavailable",
        "source": sensor_state.get("source") or "unknown",
        "simulated": bool(sensor_state.get("simulated", False)),
        "captured_at": sensor_state.get("captured_at"),
        "focus": focus,
        "focus_label": INTENT_LABELS.get(focus, focus),
        "modalities": modalities,
        "online_count": len(online),
        "total_count": len(modalities),
        "support_count": supporting,
        "fusion_confidence": fusion_confidence,
        "risk_score": aggregate.get(focus, 0),
        "hypotheses": aggregate,
        "confidence_trace": [
            {"stage": "单模态解析", "confidence": source_confidence},
            {"stage": "时空对齐", "confidence": temporal_alignment},
            {"stage": "交叉验证", "confidence": fusion_confidence},
        ],
        "latency_ms": max_latency,
        "primary_finding": primary_finding,
        "evidence": evidence,
    }


def summarize_action_outcome(result: JsonObject) -> JsonObject:
    steps = result.get("steps")
    steps = steps if isinstance(steps, list) else []
    calls = result.get("calls")
    calls = calls if isinstance(calls, list) else []
    pending_tools = result.get("pending_tools")
    pending_tools = pending_tools if isinstance(pending_tools, list) else []
    state_diff = result.get("state_diff")
    state_diff = state_diff if isinstance(state_diff, dict) else {}

    done = [
        str(step.get("title"))
        for step in steps
        if isinstance(step, dict)
        and step.get("title")
        and step.get("status") in {"done", "degraded"}
    ]
    waiting = [
        str(step.get("title"))
        for step in steps
        if isinstance(step, dict)
        and step.get("title")
        and step.get("status") in {"pending_confirm", "waiting"}
    ]
    blocked = [
        str(step.get("title"))
        for step in steps
        if isinstance(step, dict)
        and step.get("title")
        and step.get("status") in {"blocked", "failed"}
    ]
    run_status = str(result.get("run_status") or result.get("status") or "")

    if run_status == "cancelled":
        status, status_label = "cancelled", "已取消"
        title = "待确认动作已取消"
    elif blocked:
        status, status_label = "blocked", "安全拦截"
        title = f"{len(blocked)} 项动作已被安全策略拦截"
    elif waiting or pending_tools:
        status, status_label = "waiting", "等待确认"
        title = f"已完成 {len(done)} 项，下一动作等待确认"
    elif done:
        status, status_label = "completed", "闭环完成"
        title = f"{len(done)} 项动作已完成并回读"
    else:
        status, status_label = "advisory", "仅建议"
        title = "已形成判断，未触发车辆动作"

    detail = " · ".join(done[-3:]) if done else str(
        result.get("plan_summary") or "等待执行计划"
    )
    next_action = waiting[0] if waiting else (
        str(pending_tools[0].get("name"))
        if pending_tools and isinstance(pending_tools[0], dict)
        else "无需额外确认"
    )
    receipt_count = sum(
        bool(call.get("receipt_id"))
        for call in calls
        if isinstance(call, dict)
    )
    return {
        "status": status,
        "status_label": status_label,
        "title": title,
        "detail": detail,
        "next_action": next_action,
        "completed_actions": done,
        "pending_actions": waiting,
        "receipt_count": receipt_count,
        "state_change_count": len(state_diff),
    }
