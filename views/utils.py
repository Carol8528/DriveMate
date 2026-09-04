from __future__ import annotations

import html
import json
import math
from typing import Any, Dict, List

JsonObject = Dict[str, Any]


def safe(value: Any) -> str:
    return html.escape(str(value))


def script_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\u0026")
        .replace("<", "\u003c")
        .replace(">", "\u003e")
    )


def listify(value: Any) -> List[str]:
    if value is None or value == "":
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [
        json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)
        for item in values
        if item is not None and item != ""
    ]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    delta_p = math.radians(lat2 - lat1)
    delta_l = math.radians(lng2 - lng1)
    value = math.sin(delta_p / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(delta_l / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def pending_steps(result: JsonObject) -> List[JsonObject]:
    return [
        step
        for step in result.get("steps", [])
        if isinstance(step, dict) and step.get("status") == "pending_confirm"
    ]
