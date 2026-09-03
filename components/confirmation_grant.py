# -*- coding: utf-8 -*-
"""ConfirmationGrant：把用户确认绑定到工具、解析后参数和 StateSnapshot 版本。"""
import hashlib
import json
from typing import Any, Dict


def _hash(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stable_snapshot(value: Any, path=()) -> Any:
    """Remove observation metadata that changes without changing safety state."""
    if isinstance(value, dict):
        stable = {}
        for key, item in value.items():
            child_path = path + (key,)
            # sensor_state is a derived observation view. It contains values
            # changed by already-authorized cabin actions, so binding it would
            # invalidate a later navigation confirmation because of the
            # system's own execution. Canonical identity, vehicle, order, and
            # environment state remain bound below.
            if not path and key == "sensor_state":
                continue
            if path and path[0] == "sensor_state" and key == "captured_at":
                continue
            stable[key] = _stable_snapshot(item, child_path)
        return stable
    if isinstance(value, list):
        return [_stable_snapshot(item, path) for item in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        telemetry_buckets = {
            ("vehicle_state", "speed_kmh"): 10.0,
            ("vehicle_state", "soc_percent"): 2.0,
            ("vehicle_state", "range_km"): 5.0,
            ("vehicle_state", "driving_hours"): 0.1,
        }
        bucket = telemetry_buckets.get(path)
        if path and path[0] == "sensor_state":
            bucket = {
                "speed_kmh": 10.0,
                "soc_percent": 2.0,
                "range_km": 5.0,
                "driving_hours": 0.1,
            }.get(str(path[-1]), bucket)
        if bucket:
            return round(float(value) / bucket)
    return value


def _grant_snapshot(tool: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    grant_snapshot = dict(snapshot)
    if tool == "plan_route":
        vehicle_state = dict(snapshot.get("vehicle_state") or {})
        # Natural speed variation must not cancel an already reviewed
        # destination; route execution still receives the fresh snapshot.
        vehicle_state.pop("speed_kmh", None)
        grant_snapshot["vehicle_state"] = vehicle_state
    return grant_snapshot


def state_version(snapshot: Dict[str, Any], tool: str = "") -> str:
    source = _grant_snapshot(tool, snapshot) if tool else snapshot
    return _hash(_stable_snapshot(source))[:16]


def grant_id(tool: str, arguments: Dict[str, Any], snapshot: Dict[str, Any]) -> str:
    return _hash({"tool": tool, "arguments": arguments or {}, "state_version": state_version(snapshot, tool)})[:24]


def make_grant(tool: str, arguments: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, str]:
    return {"grant_id": grant_id(tool, arguments, snapshot), "state_version": state_version(snapshot, tool)}
