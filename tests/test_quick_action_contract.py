import ast
from pathlib import Path
import unittest

from components.intent_graph import resolve_intent


ROOT = Path(__file__).resolve().parents[1]


def quick_actions():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {
                "OWNER_QUICK_ACTIONS",
                "TAXI_QUICK_ACTIONS",
            }:
                values[target.id] = ast.literal_eval(node.value)
    return values


def snapshot(mode):
    return {
        "identity": {
            "mode": "OWNER_DRIVE" if mode == "车主自驾" else "ROBOTAXI_RIDE",
            "user_id": "quick-action-test",
        },
        "vehicle_state": {
            "speed_kmh": 80,
            "soc_percent": 35,
            "range_km": 180,
            "driving_hours": 3.5,
            "child_seat_detected": True,
        },
        "order_state": {
            "status": "arriving（即将到达）",
            "destination": "上海外滩",
            "passenger_coordinates": {"lat": 31.1, "lng": 121.1},
            "vehicle_coordinates": {"lat": 31.1001, "lng": 121.1001},
        },
        "environment_state": {
            "time_of_day": "日间",
            "area_type": "城区",
            "parking_policy": "允许临停",
        },
    }


class QuickActionContractTests(unittest.TestCase):
    def test_all_frontend_quick_actions_resolve_to_backend_intents(self):
        actions = quick_actions()
        expectations = {
            "OWNER_QUICK_ACTIONS": {
                "我有点困": "fatigue",
                "调节车内温度": "climate",
                "规划沿途补能": "charging",
                "带孩子出行": "parent_child",
                "查看车辆状态": "vehicle_status",
                "开始路线导航": "route_plan",
            },
            "TAXI_QUICK_ACTIONS": {
                "我找不到车": "find_car",
                "修改上车点": "modify_pickup",
                "修改目的地": "reroute",
                "车内不舒服": "medical",
                "联系人工客服": "human_support",
                "查看行程状态": "trip_status",
            },
        }
        modes = {
            "OWNER_QUICK_ACTIONS": "车主自驾",
            "TAXI_QUICK_ACTIONS": "Robotaxi 乘客",
        }
        self.assertEqual(set(actions), set(expectations))
        for group, expected in expectations.items():
            mode = modes[group]
            actual_actions = dict(actions[group])
            self.assertEqual(set(actual_actions), set(expected))
            for label, expected_intent in expected.items():
                resolution = resolve_intent(
                    actual_actions[label], snapshot(mode), mode
                )
                self.assertFalse(
                    resolution["needs_clarification"],
                    f"{group} / {label}: {resolution}",
                )
                self.assertEqual(
                    resolution["selected"],
                    expected_intent,
                    f"{group} / {label}: {resolution}",
                )


if __name__ == "__main__":
    unittest.main()
