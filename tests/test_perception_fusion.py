import unittest

from api_client import MockBackendClient
from perception_fusion import (
    build_sensor_state,
    fuse_perception,
    summarize_action_outcome,
)


def owner_snapshot():
    vehicle = {
        "speed_kmh": 80,
        "soc_percent": 80,
        "range_km": 450,
        "driving_hours": 3.5,
        "child_seat_detected": False,
    }
    order = {
        "status": "无订单",
        "destination": "上海外滩",
        "passenger_coordinates": {"lat": 31.1, "lng": 121.1},
        "vehicle_coordinates": {"lat": 31.1, "lng": 121.1},
    }
    environment = {
        "weather": "晴",
        "traffic": "畅通",
        "time_of_day": "夜间",
        "area_type": "高速",
        "parking_policy": "允许临停",
    }
    snapshot = {
        "identity": {"mode": "OWNER_DRIVE"},
        "vehicle_state": vehicle,
        "order_state": order,
        "environment_state": environment,
    }
    snapshot["sensor_state"] = build_sensor_state(
        "车主自驾",
        vehicle,
        environment,
        order,
        {
            "dms_fatigue": 78,
            "audio_fatigue": 71,
            "steering_stability": 69,
            "visibility": 90,
        },
    )
    return snapshot


class PerceptionFusionTests(unittest.TestCase):
    def test_fusion_exposes_cards_trace_and_evidence(self):
        fusion = fuse_perception(owner_snapshot(), "fatigue")
        self.assertEqual(fusion["focus"], "fatigue")
        self.assertEqual(len(fusion["modalities"]), 4)
        self.assertEqual(len(fusion["confidence_trace"]), 3)
        self.assertGreaterEqual(fusion["support_count"], 3)
        self.assertTrue(fusion["primary_finding"])

    def test_mock_run_returns_perception_and_action_outcome(self):
        result = MockBackendClient().run_agent(
            "我连续驾驶有些困倦，请先评估安全并给我建议",
            "车主自驾",
            "融合编排引擎（本地可审计）",
            owner_snapshot(),
        )
        self.assertEqual(result["phases"][0]["name"], "perceive")
        self.assertEqual(result["perception_fusion"]["focus"], "fatigue")
        self.assertEqual(result["action_outcome"]["status"], "waiting")

    def test_action_outcome_tracks_completion(self):
        result = {
            "steps": [{"title": "调节空调", "status": "done"}],
            "calls": [{"receipt_id": "R-1"}],
            "pending_tools": [],
            "state_diff": {"climate.temperature": {"before": 26, "after": 22}},
            "run_status": "completed",
        }
        outcome = summarize_action_outcome(result)
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(outcome["receipt_count"], 1)
        self.assertEqual(outcome["state_change_count"], 1)

    def test_mock_route_plan_preserves_destination_and_eta(self):
        snapshot = owner_snapshot()
        snapshot["order_state"]["destination"] = "上海迪士尼度假区"
        result = MockBackendClient().run_agent(
            "请规划前往上海迪士尼度假区的路线",
            "车主自驾",
            "融合编排引擎（本地可审计）",
            snapshot,
        )
        self.assertEqual(result["intent"], "route_plan")
        self.assertEqual(result["navigation"]["destination"], "上海迪士尼度假区")
        self.assertEqual(result["navigation"]["eta_minutes"], 58)
        self.assertEqual(
            result["state_diff"]["navigation.destination"]["after"],
            "上海迪士尼度假区",
        )


if __name__ == "__main__":
    unittest.main()
