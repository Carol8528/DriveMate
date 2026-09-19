# -*- coding: utf-8 -*-
"""External semantic LLM boundary tests.

The filename is retained for repository history, but the App API integration no longer exists.
"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend_service import AgentRunService, EXTERNAL_LLM_ENGINE
from components.semantic_understanding import (
    ExternalSemanticClient,
    merge_semantic_resolution,
    resolve_with_external_llm,
)
from components.intent_graph import resolve_intent
from components.rule_engine import _plan_for
from components.tool_registry import load_tool_registry


def owner_snapshot():
    return {
        "identity": {"mode": "OWNER_DRIVE", "user_id": "secret-user"},
        "vehicle_state": {
            "speed_kmh": 80,
            "soc_percent": 18,
            "range_km": 65,
            "driving_hours": 3.5,
        },
        "order_state": {
            "status": "无订单",
            "destination": "上海外滩",
            "passenger_coordinates": {"lat": 31.1, "lng": 121.1},
        },
        "environment_state": {"area_type": "高速", "time_of_day": "夜间"},
    }


def pax_snapshot():
    return {
        "identity": {"mode": "ROBOTAXI_RIDE", "user_id": "secret-user"},
        "vehicle_state": {"speed_kmh": 0, "soc_percent": 80, "range_km": 350},
        "order_state": {"status": "arriving", "vehicle_location": "路口附近"},
        "environment_state": {"area_type": "城区", "parking_policy": "禁停"},
    }


class _Response:
    status_code = 200
    text = ""

    @staticmethod
    def json():
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "intent": "route_plan",
                                "confidence": 0.94,
                                "needs_clarification": False,
                                "reason": "用户表达了前往地点的导航意图",
                                "slots": {"destination": "虹桥机场"},
                                "alternatives": [],
                                "negated_intents": [],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


class _FakeSemanticClient:
    model = "fake-semantic"

    def __init__(self, output):
        self.output = output

    def understand(self, *_args, **_kwargs):
        return dict(self.output)


class ExternalSemanticBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta, _ = load_tool_registry()

    def test_only_api_key_is_required_to_expose_external_engine(self):
        service = AgentRunService.__new__(AgentRunService)
        with patch(
            "backend_service.SETTINGS",
            SimpleNamespace(llm_api_key="configured"),
        ):
            self.assertIn(EXTERNAL_LLM_ENGINE, service.available_engines())

    def test_external_request_is_semantic_only_and_minimizes_state(self):
        captured = {}

        def fake_post(url, headers, json, timeout):
            captured.update({"url": url, "headers": headers, "body": json, "timeout": timeout})
            return _Response()

        client = ExternalSemanticClient(
            api_key="k-test",
            base_url="https://example.test/v1",
            model="semantic-model",
            timeout_seconds=7,
        )
        with patch("components.semantic_understanding.requests.post", side_effect=fake_post):
            result = client.understand(
                "带我去虹桥机场",
                mode="车主自驾",
                snapshot=owner_snapshot(),
                history=[{"user": "上一轮", "assistant": "上一轮回复"}],
            )

        self.assertEqual(result["intent"], "route_plan")
        self.assertEqual(result["slots"]["destination"], "虹桥机场")
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer k-test")
        self.assertNotIn("tools", captured["body"])
        self.assertNotIn("tool_choice", captured["body"])
        user_payload = json.loads(captured["body"]["messages"][1]["content"])
        serialized = json.dumps(user_payload, ensure_ascii=False)
        self.assertNotIn("secret-user", serialized)
        self.assertNotIn("passenger_coordinates", serialized)

    def test_external_semantics_can_resolve_local_ambiguity(self):
        message = "带我过去虹桥那边"
        local = resolve_intent(message, owner_snapshot(), "车主自驾")
        self.assertTrue(local["needs_clarification"])
        client = _FakeSemanticClient(
            {
                "intent": "route_plan",
                "confidence": 93,
                "needs_clarification": False,
                "reason": "表达了导航到虹桥的意图",
                "slots": {"destination": "虹桥"},
                "alternatives": [],
                "negated_intents": [],
                "provider": "test",
                "model": "fake-semantic",
            }
        )
        resolution = resolve_with_external_llm(
            message,
            snapshot=owner_snapshot(),
            mode="车主自驾",
            client=client,
        )
        self.assertEqual(resolution["selected"], "route_plan")
        self.assertEqual(resolution["semantic_source"], "external_llm")
        self.assertEqual(resolution["semantic_slots"]["destination"], "虹桥")

    def test_local_safety_override_beats_external_disagreement(self):
        message = "虽然有点困，但现在胸口闷得喘不上气。"
        local = resolve_intent(message, pax_snapshot(), "Robotaxi 乘客")
        self.assertEqual(local["selected"], "medical")
        self.assertTrue(local["safety_override"])
        fused = merge_semantic_resolution(
            local,
            {
                "intent": "trip_status",
                "confidence": 99,
                "needs_clarification": False,
                "reason": "wrong model result",
                "slots": {},
                "alternatives": [],
                "negated_intents": [],
                "provider": "test",
                "model": "fake-semantic",
            },
        )
        self.assertEqual(fused["selected"], "medical")
        self.assertEqual(fused["semantic_source"], "local_safety_override")

    def test_semantic_slots_feed_local_planner_not_external_execution(self):
        plan = _plan_for(
            "route_plan",
            "带我过去",
            "车主自驾",
            owner_snapshot(),
            self.meta,
            semantic_slots={"destination": "虹桥机场"},
        )
        self.assertFalse(plan.get("clarify"))
        self.assertEqual(plan["steps"][0]["tool"], "plan_route")
        self.assertEqual(plan["steps"][0]["arguments"]["destination"], "虹桥机场")

        climate = _plan_for(
            "climate",
            "调暖一点",
            "车主自驾",
            owner_snapshot(),
            self.meta,
            semantic_slots={"temperature_c": 24},
        )
        self.assertEqual(climate["steps"][0]["arguments"]["temperature"], 24)


if __name__ == "__main__":
    unittest.main()
