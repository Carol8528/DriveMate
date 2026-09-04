import unittest
from unittest.mock import patch

from backend_service import AgentRunService
from components.tool_registry import load_tool_registry


class _Response:
    status_code = 200
    text = ""

    @staticmethod
    def json():
        return {"output": {"text": "建议尽快进入服务区休息。", "thoughts": []}}


class _Executor:
    run_id = None

    def __init__(self, tool_meta):
        self.tool_meta = tool_meta

    def execute(self, name, arguments, snapshot, confirmed=False, **_kwargs):
        result = {
            "success": True,
            "status": "success",
            "summary": f"{name} completed",
            "destination": "最近服务区",
        }
        call = {
            "tool": name,
            "level": self.tool_meta[name].get("level", "L0"),
            "result": "success",
            "summary": result["summary"],
            "arguments": arguments,
            "receipt_id": f"receipt-{name}",
        }
        return result, call


class BailianSafetyTests(unittest.TestCase):
    def test_high_risk_text_only_response_falls_back_to_local_confirmation(self):
        service = AgentRunService.__new__(AgentRunService)
        service.tool_meta, service.tool_schemas = load_tool_registry()
        snapshot = {
            "identity": {"mode": "OWNER_DRIVE", "user_id": "test"},
            "vehicle_state": {"speed_kmh": 80, "driving_hours": 3.5},
            "order_state": {"vehicle_location": "高速公路"},
            "environment_state": {"area_type": "高速"},
        }

        with patch("backend_service.requests.post", return_value=_Response()):
            result = service._run_bailian(
                "我连续驾驶有些困倦，请先评估安全并给我建议",
                "车主自驾",
                snapshot,
                _Executor(service.tool_meta),
            )

        self.assertEqual(result["intent"], "fatigue")
        self.assertTrue(result["pending_tools"])
        self.assertEqual(result["pending_tools"][0]["name"], "plan_route")
        self.assertTrue(
            any(step.get("status_raw") == "pending_confirm" for step in result["steps"])
        )


if __name__ == "__main__":
    unittest.main()
