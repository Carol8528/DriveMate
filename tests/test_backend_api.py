from copy import deepcopy
import os
import subprocess
import sys
import tempfile
import unittest

import requests

from start_demo import (
    _free_local_port,
    _wait_for_authenticated_health,
    _wait_for_backend_health,
)


class BackendApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="drivemate-v8-api-")
        cls.simulator_port = _free_local_port()
        cls.backend_port = _free_local_port()
        cls.simulator_token = "test-simulator-token"
        cls.api_token = "test-agent-api-token"
        cls.simulator_url = f"http://127.0.0.1:{cls.simulator_port}"
        cls.backend_url = f"http://127.0.0.1:{cls.backend_port}"
        env = os.environ.copy()
        env.update(
            {
                "DRIVEMATE_SIMULATOR_TOKEN": cls.simulator_token,
                "DRIVEMATE_SIMULATOR_URL": cls.simulator_url,
                "DRIVEMATE_SIMULATOR_DB": os.path.join(
                    cls.temp_dir.name, "simulator.db"
                ),
                "DRIVEMATE_AUDIT_DB": os.path.join(
                    cls.temp_dir.name, "audit.db"
                ),
                "DRIVEMATE_API_TOKEN": cls.api_token,
            }
        )
        cls.simulator = subprocess.Popen(
            [
                sys.executable,
                os.path.join(cls.root, "simulator_server.py"),
                "--port",
                str(cls.simulator_port),
                "--token",
                cls.simulator_token,
                "--db",
                os.path.join(cls.temp_dir.name, "simulator.db"),
            ],
            cwd=cls.root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for_authenticated_health(
                cls.simulator_url,
                cls.simulator_token,
                cls.simulator,
                timeout_s=8,
            )
            cls.backend = subprocess.Popen(
                [
                    sys.executable,
                    os.path.join(cls.root, "backend_server.py"),
                    "--port",
                    str(cls.backend_port),
                    "--token",
                    cls.api_token,
                ],
                cwd=cls.root,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _wait_for_backend_health(
                cls.backend_url,
                cls.api_token,
                cls.backend,
                timeout_s=8,
            )
        except Exception:
            if cls.simulator.poll() is None:
                cls.simulator.terminate()
                cls.simulator.wait(timeout=3)
            cls.temp_dir.cleanup()
            raise
        cls.headers = {"Authorization": "Bearer " + cls.api_token}

    @classmethod
    def tearDownClass(cls):
        for process in (getattr(cls, "backend", None), cls.simulator):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        cls.temp_dir.cleanup()

    @staticmethod
    def snapshot():
        return {
            "identity": {
                "mode": "OWNER_DRIVE",
                "user_id": "api-test",
                "auth_level": "vin_bound",
            },
            "vehicle_state": {
                "speed_kmh": 80,
                "soc_percent": 18,
                "range_km": 65,
                "driving_hours": 3.5,
                "child_seat_detected": False,
            },
            "order_state": {
                "status": "无订单",
                "destination": "上海外滩",
                "passenger_coordinates": {"lat": 30.1, "lng": 120.1},
                "vehicle_coordinates": {"lat": 30.1, "lng": 120.1},
            },
            "environment_state": {
                "weather": "晴",
                "traffic": "畅通",
                "time_of_day": "夜间",
                "area_type": "高速",
                "parking_policy": "允许临停",
            },
            "sensor_state": {
                "schema_version": "1.0",
                "captured_at": "2026-09-03T01:00:00Z",
                "source": "frontend_demo_bus",
                "simulated": True,
                "streams": [],
            },
        }

    @classmethod
    def taxi_snapshot(cls):
        snapshot = cls.snapshot()
        snapshot["identity"].update(
            {"mode": "ROBOTAXI_RIDE", "auth_level": "order_token"}
        )
        snapshot["vehicle_state"].update(
            {"speed_kmh": 0, "driving_hours": 0}
        )
        snapshot["order_state"].update(
            {
                "status": "arriving（即将到达）",
                "passenger_location": "上海虹桥火车站 2F 出发层",
                "vehicle_location": "上海虹桥火车站",
            }
        )
        snapshot["environment_state"].update(
            {"area_type": "城区", "parking_policy": "允许临停"}
        )
        return snapshot

    def post(self, path, payload=None):
        return requests.post(
            self.backend_url + path,
            headers=self.headers,
            json=payload,
            timeout=15,
        )

    def test_authentication_and_sanitized_metadata(self):
        unauthorized = requests.get(
            self.backend_url + "/api/v1/meta", timeout=3
        )
        self.assertEqual(unauthorized.status_code, 401)
        response = requests.get(
            self.backend_url + "/api/v1/meta",
            headers=self.headers,
            timeout=3,
        )
        self.assertEqual(response.status_code, 200)
        metadata = response.json()
        self.assertGreater(metadata["tool_count"], 0)
        self.assertIn("融合编排引擎（本地可审计）", metadata["engines"])
        self.assertTrue(
            all("source_path" not in tool for tool in metadata["tools"])
        )

    def test_create_confirm_and_decoded_audit(self):
        snapshot = self.snapshot()
        response = self.post(
            "/api/v1/agent/runs",
            {
                "message": "开了三个多小时了，有点犯困，帮我看看怎么办",
                "mode": "车主自驾",
                "engine": "融合编排引擎（本地可审计）",
                "snapshot": snapshot,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        created = response.json()
        for field in (
            "run_id",
            "intent",
            "reply",
            "risk_level",
            "plan_summary",
            "steps",
            "safety_tip",
            "calls",
            "pending_tools",
            "perception_fusion",
            "action_outcome",
        ):
            self.assertIn(field, created)
        self.assertEqual(created["run_status"], "waiting_confirmation")
        self.assertTrue(created["pending_tools"])
        self.assertTrue(
            {
                "set_climate",
                "set_seat",
                "play_media",
                "transfer_to_human",
                "crm_agent",
            }.issubset(
                {
                    call.get("tool")
                    for call in created["calls"]
                    if call.get("result") == "success"
                }
            )
        )
        self.assertTrue(
            any(
                item.get("name") == "plan_route"
                for item in created["pending_tools"]
            )
        )
        self.assertFalse(
            any(
                call.get("tool") == "plan_route"
                and call.get("result") == "success"
                for call in created["calls"]
            )
        )

        refreshed = deepcopy(snapshot)
        refreshed["sensor_state"]["captured_at"] = "2026-09-03T01:00:01Z"
        confirmed_response = self.post(
            f"/api/v1/agent/runs/{created['run_id']}/confirm",
            {"snapshot": refreshed},
        )
        self.assertEqual(
            confirmed_response.status_code, 200, confirmed_response.text
        )
        confirmed = confirmed_response.json()
        self.assertFalse(confirmed["pending_tools"])
        self.assertIn(confirmed["run_status"], {"completed", "degraded"})
        self.assertGreaterEqual(confirmed["action_outcome"]["receipt_count"], 1)

        audit_response = requests.get(
            self.backend_url + f"/api/v1/audit/runs/{created['run_id']}",
            headers=self.headers,
            timeout=5,
        )
        self.assertEqual(audit_response.status_code, 200, audit_response.text)
        audit = audit_response.json()
        self.assertIsInstance(audit["run"]["snapshot"], dict)
        self.assertIsInstance(audit["run"]["result"], dict)
        self.assertTrue(audit["tool_calls"])
        self.assertIsInstance(audit["tool_calls"][0]["arguments"], dict)
        self.assertTrue(audit["tickets"])
        self.assertTrue(
            any(
                call.get("tool") == "crm_agent"
                and call.get("status") == "success"
                for call in audit["tool_calls"]
            )
        )

    def test_session_is_reused_and_history_is_consumed(self):
        first = self.post(
            "/api/v1/agent/runs",
            {
                "message": "请告诉我当前车辆状态",
                "mode": "车主自驾",
                "engine": "融合编排引擎（本地可审计）",
                "snapshot": self.snapshot(),
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        first_result = first.json()
        second = self.post(
            "/api/v1/agent/runs",
            {
                "message": "再看一下续航",
                "mode": "车主自驾",
                "engine": "融合编排引擎（本地可审计）",
                "snapshot": self.snapshot(),
                "session_id": first_result["session_id"],
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        second_result = second.json()
        self.assertEqual(second_result["session_id"], first_result["session_id"])
        self.assertEqual(second_result["session_context"]["history_turns_used"], 1)
        self.assertEqual(
            second_result["session_context"]["previous_run_ids"],
            [first_result["run_id"]],
        )

    def test_cancel_is_persisted_without_cancelling_order(self):
        response = self.post(
            "/api/v1/agent/runs",
            {
                "message": "请根据当前电量规划沿途补能",
                "mode": "车主自驾",
                "engine": "融合编排引擎（本地可审计）",
                "snapshot": self.snapshot(),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        created = response.json()
        self.assertTrue(created["pending_tools"])
        cancelled_response = self.post(
            f"/api/v1/agent/runs/{created['run_id']}/cancel"
        )
        self.assertEqual(
            cancelled_response.status_code, 200, cancelled_response.text
        )
        cancelled = cancelled_response.json()
        self.assertEqual(cancelled["run_status"], "cancelled")
        self.assertFalse(cancelled["pending_tools"])
        self.assertFalse(
            any(call.get("tool") == "cancel_order" for call in cancelled["calls"])
        )

        audit = requests.get(
            self.backend_url + f"/api/v1/audit/runs/{created['run_id']}",
            headers=self.headers,
            timeout=5,
        ).json()
        self.assertEqual(audit["run"]["result"]["run_status"], "cancelled")
        self.assertTrue(
            any(
                event.get("decision") == "cancelled"
                for event in audit["confirmations"]
            )
        )

    def test_all_frontend_quick_actions_execute_through_real_api(self):
        cases = [
            ("车主自驾", "我连续驾驶有些困倦，请先评估安全并给我建议", "fatigue"),
            ("车主自驾", "车内有点热，请帮我把温度调得舒适一些", "climate"),
            ("车主自驾", "请根据当前电量规划沿途补能", "charging"),
            ("车主自驾", "带孩子出行，请帮我检查并设置舒适安全的座舱环境", "parent_child"),
            ("车主自驾", "请告诉我当前车辆和行驶状态", "vehicle_status"),
            ("车主自驾", "请根据当前目的地规划路线", "route_plan"),
            ("Robotaxi 乘客", "我找不到接驾车辆，请帮我定位", "find_car"),
            ("Robotaxi 乘客", "我需要修改上车点", "modify_pickup"),
            ("Robotaxi 乘客", "我需要修改本次行程目的地", "reroute"),
            ("Robotaxi 乘客", "我在车内感觉不舒服，需要帮助", "medical"),
            ("Robotaxi 乘客", "请帮我联系人工客服", "human_support"),
            ("Robotaxi 乘客", "请查询当前 Robotaxi 订单状态与车辆位置", "trip_status"),
        ]
        required_fields = {
            "run_id",
            "intent",
            "reply",
            "risk_level",
            "steps",
            "calls",
            "pending_tools",
            "perception_fusion",
            "action_outcome",
        }
        for mode, message, expected_intent in cases:
            snapshot = (
                self.snapshot()
                if mode == "车主自驾"
                else self.taxi_snapshot()
            )
            response = self.post(
                "/api/v1/agent/runs",
                {
                    "message": message,
                    "mode": mode,
                    "engine": "融合编排引擎（本地可审计）",
                    "snapshot": snapshot,
                },
            )
            self.assertEqual(
                response.status_code,
                200,
                f"{mode} / {message}: {response.text}",
            )
            result = response.json()
            self.assertEqual(
                expected_intent,
                result["intent"],
                f"{mode} / {message}: {result}",
            )
            self.assertTrue(required_fields.issubset(result))
            self.assertNotEqual(result["intent"], "backend_error")


if __name__ == "__main__":
    unittest.main()
