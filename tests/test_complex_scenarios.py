# -*- coding: utf-8 -*-
"""复杂场景拆解能力测试：覆盖 复杂场景.md 中的四个场景。

1. 家庭长途出行：一句模糊需求拆成多目标 DAG（状态→续航→充电+用餐→儿童座舱→最终路线）。
2. 赶飞机行程：并存约束（时间/平稳/会议）进入同一条执行链。
3. 疲劳但要求继续：理解正确不等于允许执行（权限分离）。
4. Robotaxi 临时下车：停车/解锁分步授权 + 确认前状态重检 + 旧授权失效。
"""
import os
import subprocess
import sys
import tempfile
import unittest

_tmp = tempfile.mkdtemp(prefix="drivemate-complex-test-")
os.environ.setdefault("DRIVEMATE_AUDIT_DB", os.path.join(_tmp, "audit.db"))

from components.intent_graph import resolve_intent
from components.rule_engine import run_rule
from components.safety_guard import authorize_tool
from components.scenario_decomposer import decompose_scenario
from components.tool_executor import ToolExecutor
from components.tool_registry import load_tool_registry
from components.audit_store import create_session, start_run
from start_demo import _free_local_port, _wait_for_authenticated_health


def owner_trip_snapshot():
    return {
        "identity": {"mode": "OWNER_DRIVE", "user_id": "test", "auth_level": "vin_bound"},
        "vehicle_state": {"speed_kmh": 60, "soc_percent": 42, "range_km": 260,
                          "driving_hours": 1.2, "child_seat_detected": True},
        "order_state": {"status": "无订单", "destination": "",
                        "vehicle_coordinates": {"lat": 31.197, "lng": 121.327}},
        "environment_state": {"time_of_day": "下午", "area_type": "高速", "parking_policy": "允许临停"},
    }


def owner_fatigue_snapshot():
    return {
        "identity": {"mode": "OWNER_DRIVE", "user_id": "test", "auth_level": "vin_bound"},
        "vehicle_state": {"speed_kmh": 90, "soc_percent": 55, "range_km": 300, "driving_hours": 3.6},
        "order_state": {"status": "无订单", "vehicle_location": "沪杭高速嘉兴段"},
        "environment_state": {"time_of_day": "夜间", "area_type": "高速", "parking_policy": "允许临停"},
    }


def taxi_snapshot(speed=32, curb=24, parking="允许临停"):
    vehicle = {"speed_kmh": speed, "soc_percent": 76, "range_km": 310, "driving_hours": 0}
    if speed == 0:
        vehicle["gear"] = "P"
    return {
        "identity": {"mode": "ROBOTAXI_RIDE", "user_id": "test", "auth_level": "order_token"},
        "vehicle_state": vehicle,
        "order_state": {"status": "en_route", "vehicle_location": "城区主干道",
                        "destination": "市体育中心",
                        "passenger_coordinates": {"lat": 30.25874, "lng": 120.16452},
                        "vehicle_coordinates": {"lat": 30.2589, "lng": 120.1648}},
        "environment_state": {"time_of_day": "下午", "area_type": "城区", "parking_policy": parking},
        "perception_controls": {"curb_risk": curb},
    }


FAMILY_TEXT = "带孩子去上海，下午五点前到。孩子容易晕车，我不想中途没电，路上最好还能吃个饭。"
AIRPORT_TEXT = "我六点半的航班，现在去机场。路上我要开个会，尽量走平稳一点的路线，别让我迟到。"
FATIGUE_TEXT = "我很困，但我还能坚持，继续导航，帮我把空调调低一点让我清醒。"
DROPOFF_TEXT = "不用到目的地了，就这里停，我要下车。"


class ComplexScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta, _ = load_tool_registry()
        cls.owner_session = create_session("test", "车主自驾")
        cls.taxi_session = create_session("test", "Robotaxi 乘客")
        cls.root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.sim_dir = tempfile.TemporaryDirectory(
            prefix="drivemate-complex-sim-", ignore_cleanup_errors=True)
        cls.port = _free_local_port()
        cls.token = "complex-test-token"
        os.environ["DRIVEMATE_SIMULATOR_URL"] = f"http://127.0.0.1:{cls.port}"
        os.environ["DRIVEMATE_SIMULATOR_TOKEN"] = cls.token
        env = os.environ.copy()
        cls.sim_proc = subprocess.Popen(
            [sys.executable, os.path.join(cls.root, "simulator_server.py"),
             "--port", str(cls.port), "--token", cls.token,
             "--db", os.path.join(cls.sim_dir.name, "simulator.db")],
            cwd=cls.root, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _wait_for_authenticated_health(
            os.environ["DRIVEMATE_SIMULATOR_URL"], cls.token, cls.sim_proc, timeout_s=5.0)

    @classmethod
    def tearDownClass(cls):
        if cls.sim_proc.poll() is None:
            cls.sim_proc.terminate()
            try:
                cls.sim_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                cls.sim_proc.kill()
                cls.sim_proc.wait(timeout=2)
        cls.sim_dir.cleanup()

    def _new_run(self, session, text, snapshot):
        run_id = start_run(session, text, snapshot)
        return ToolExecutor(self.meta, run_id=run_id)

    @staticmethod
    def _grants(result):
        return {p["step_id"]: p["grant_id"] for p in result["pending_tools"]}

    # 场景 1：一句模糊需求 → 多目标 DAG
    def test_family_long_trip_decomposed_into_multi_goal_dag(self):
        snap = owner_trip_snapshot()
        ex = self._new_run(self.owner_session, FAMILY_TEXT, snap)
        first = run_rule(FAMILY_TEXT, "车主自驾", snap, ex, self.meta)

        self.assertEqual(first["intent"], "family_long_trip")
        decomp = first.get("scenario_decomposition")
        self.assertIsInstance(decomp, dict)
        self.assertGreaterEqual(len(decomp["goals"]), 4)
        self.assertEqual(decomp["constraints"]["destination"], "上海")
        self.assertEqual(decomp["constraints"]["arrive_by"], "17:00")

        tools = [s["tool"] for s in first["steps"]]
        # 依赖顺序：车况 → 续航估算 → 充电/用餐节点 → 最终路线
        self.assertLess(tools.index("get_vehicle_health"), tools.index("estimate_range_sufficiency"))
        self.assertLess(tools.index("estimate_range_sufficiency"), tools.index("find_charging_station"))
        self.assertLess(tools.index("find_charging_station"), tools.index("plan_route"))
        self.assertIn("detect_child_presence", tools)
        self.assertIn("find_rest_area", tools)

        pending = {p["name"]: p for p in first["pending_tools"]}
        self.assertEqual(set(pending), {"plan_route", "reserve_charging"})
        route_args = pending["plan_route"]["arguments"]
        self.assertEqual(route_args["destination"], "上海")
        self.assertEqual(route_args["arrive_by"], "17:00")
        self.assertEqual(route_args["waypoints"], ["cs_demo_01"])

        # 确认后：路线与预约真实执行
        second = run_rule(FAMILY_TEXT, "车主自驾", snap, ex, self.meta, confirmed=True,
                          previous_calls=first["calls"], confirmed_grants=self._grants(first))
        self.assertFalse(second["pending_tools"])
        self.assertTrue(any(c["tool"] == "plan_route" and c["result"] == "success" for c in second["calls"]))
        self.assertTrue(any(c["tool"] == "reserve_charging" and c["result"] == "success" for c in second["calls"]))

    # 场景 2：赶飞机并存约束进入同一执行链
    def test_airport_transfer_constraints_in_single_chain(self):
        snap = owner_trip_snapshot()
        ex = self._new_run(self.owner_session, AIRPORT_TEXT, snap)
        result = run_rule(AIRPORT_TEXT, "车主自驾", snap, ex, self.meta)

        self.assertEqual(result["intent"], "airport_transfer")
        decomp = result["scenario_decomposition"]
        self.assertEqual(decomp["constraints"]["destination"], "机场")
        self.assertEqual(decomp["constraints"]["arrive_by"], "06:30")
        goal_ids = {g["id"] for g in decomp["goals"]}
        self.assertIn("meeting_mode", goal_ids)
        self.assertIn("smooth_route", goal_ids)

        tools = [s["tool"] for s in result["steps"]]
        self.assertIn("estimate_range_sufficiency", tools)
        self.assertIn("set_ambient", tools)  # 会议氛围
        pending = {p["name"]: p for p in result["pending_tools"]}
        self.assertEqual(set(pending), {"plan_route"})
        self.assertEqual(pending["plan_route"]["arguments"]["preference"], "comfort")
        self.assertEqual(pending["plan_route"]["arguments"]["arrive_by"], "06:30")
        self.assertIn("平稳机场路线", pending["plan_route"]["title"])
        self.assertNotIn("休息点", pending["plan_route"]["title"])

    # 场景 3：疲劳但要求继续 → 理解权与执行权分离
    def test_fatigue_continue_request_is_permission_split(self):
        snap = owner_fatigue_snapshot()
        ex = self._new_run(self.owner_session, FATIGUE_TEXT, snap)
        result = run_rule(FATIGUE_TEXT, "车主自驾", snap, ex, self.meta)

        self.assertEqual(result["intent"], "fatigue")
        self.assertIn("理解正确不等于允许执行", result["reply"])
        self.assertIn("继续赶路", result["reply"])
        tools = [s["tool"] for s in result["steps"]]
        # 允许：可逆提神辅助；建议：导航至休息点（需确认）
        self.assertIn("set_climate", tools)
        self.assertIn("find_rest_area", tools)
        self.assertIn("plan_route", tools)
        # 约束盾：高疲劳下“便利优先直达”候选必须被硬约束拒绝
        direct = next(c for c in result["constraint_shield"]["candidates"] if c["id"] == "direct_action")
        self.assertFalse(direct["feasible"])
        self.assertTrue(direct["hard_violations"])
        # 休息点导航必须走确认，不能默认执行
        pending_names = {p["name"] for p in result["pending_tools"]}
        self.assertIn("plan_route", pending_names)

    # 场景 4：临时下车完整授权链 + 状态重检
    def test_robotaxi_dropoff_staged_grants_and_recheck(self):
        moving = taxi_snapshot(speed=32)
        stopped = taxi_snapshot(speed=0)
        ex = self._new_run(self.taxi_session, DROPOFF_TEXT, moving)

        first = run_rule(DROPOFF_TEXT, "Robotaxi 乘客", moving, ex, self.meta)
        self.assertEqual(first["intent"], "robotaxi_dropoff")
        by_tool = {s["tool"]: s for s in first["steps"]}
        self.assertEqual(by_tool["get_order_status"]["status_raw"], "done")
        self.assertEqual(by_tool["find_safe_stop_point"]["status_raw"], "done")
        self.assertEqual(by_tool["request_curbside_stop"]["status_raw"], "pending_confirm")
        self.assertEqual(by_tool["check_curbside_safety"]["status_raw"], "waiting_dependency")
        self.assertEqual(by_tool["unlock_door"]["status_raw"], "waiting_dependency")
        self.assertEqual([p["name"] for p in first["pending_tools"]], ["request_curbside_stop"])

        # 第一段确认：只授权靠边停车
        second = run_rule(DROPOFF_TEXT, "Robotaxi 乘客", moving, ex, self.meta, confirmed=True,
                          previous_calls=first["calls"], confirmed_grants=self._grants(first))
        self.assertTrue(any(c["tool"] == "request_curbside_stop" and c["result"] == "success"
                            for c in second["calls"]))
        # 车辆停稳后进入第二段：解锁需要单独确认
        self.assertEqual([p["name"] for p in second["pending_tools"]], ["unlock_door"])

        # 用停车后的最新快照确认：旧授权（基于行驶中快照）失效
        third = run_rule(DROPOFF_TEXT, "Robotaxi 乘客", stopped, ex, self.meta, confirmed=True,
                         previous_calls=second["calls"], confirmed_grants=self._grants(second))
        self.assertEqual([p["name"] for p in third["pending_tools"]], ["unlock_door"])
        self.assertTrue(third["pending_tools"][0].get("confirmation_invalidated"))
        # 已执行的停车步骤不能因再次确认被重放或重新挂起
        stop_steps = [s for s in third["steps"] if s["tool"] == "request_curbside_stop"]
        self.assertEqual(stop_steps[0]["status_raw"], "done")
        self.assertFalse(any(c["tool"] == "unlock_door" and c["result"] == "success"
                             for c in third["calls"]))

        # 基于一致的停稳快照再次确认：确定性条件满足，真实解锁
        fourth = run_rule(DROPOFF_TEXT, "Robotaxi 乘客", stopped, ex, self.meta, confirmed=True,
                          previous_calls=third["calls"], confirmed_grants=self._grants(third))
        self.assertTrue(any(c["tool"] == "unlock_door" and c["result"] == "success"
                            for c in fourth["calls"]))
        self.assertFalse(fourth["pending_tools"])

    # 场景 4 反转：确认瞬间自行车驶来 → 授权失效且全链重检
    def test_robotaxi_dropoff_bike_arrives_blocks_unlock(self):
        moving = taxi_snapshot(speed=32)
        stopped = taxi_snapshot(speed=0)
        bike = taxi_snapshot(speed=0, curb=85)
        ex = self._new_run(self.taxi_session, DROPOFF_TEXT, moving)

        first = run_rule(DROPOFF_TEXT, "Robotaxi 乘客", moving, ex, self.meta)
        second = run_rule(DROPOFF_TEXT, "Robotaxi 乘客", moving, ex, self.meta, confirmed=True,
                          previous_calls=first["calls"], confirmed_grants=self._grants(first))
        self.assertEqual([p["name"] for p in second["pending_tools"]], ["unlock_door"])

        # 先走到“已停稳、待确认解锁”的状态（与反转前夜一致）
        third = run_rule(DROPOFF_TEXT, "Robotaxi 乘客", stopped, ex, self.meta, confirmed=True,
                         previous_calls=second["calls"], confirmed_grants=self._grants(second))
        self.assertTrue(third["pending_tools"][0].get("confirmation_invalidated"))

        # 反转：用户按确认的同一秒自行车驶来，最新快照路缘风险 24 → 85。
        # 系统必须拒绝沿用旧授权执行开门。
        fourth = run_rule(DROPOFF_TEXT, "Robotaxi 乘客", bike, ex, self.meta, confirmed=True,
                          previous_calls=third["calls"], confirmed_grants=self._grants(third))
        self.assertFalse(any(c["tool"] == "unlock_door" and c["result"] == "success"
                             for c in fourth["calls"]))
        invalidated = [p for p in fourth["pending_tools"] if p.get("confirmation_invalidated")]
        self.assertTrue(invalidated, "状态实质变化后必须重新授权，而不是沿用旧确认")

        # 即使基于最新快照再次授权，SafetyGuard 仍按确定性条件硬阻断路缘风险下的解锁
        meta = dict(self.meta["unlock_door"])
        ok, reason, ctx = authorize_tool("unlock_door", meta, bike, True)
        self.assertFalse(ok)
        self.assertIn("路缘风险", reason)
        self.assertFalse(ctx["curb_side_safe"])

    # 解锁工具的确定性前置条件（单元级）
    def test_unlock_door_deterministic_preconditions(self):
        meta = dict(self.meta["unlock_door"])
        ok, _, ctx = authorize_tool("unlock_door", meta, taxi_snapshot(speed=0, curb=24), True)
        self.assertTrue(ok)
        self.assertTrue(ctx["curb_side_safe"])
        ok, reason, _ = authorize_tool("unlock_door", meta, taxi_snapshot(speed=32, curb=24), True)
        self.assertFalse(ok)
        self.assertIn("车速", reason)
        ok, reason, _ = authorize_tool("unlock_door", meta, taxi_snapshot(speed=0, curb=85), True)
        self.assertFalse(ok)
        self.assertIn("路缘风险", reason)
        ok, reason, _ = authorize_tool("unlock_door", meta,
                                       taxi_snapshot(speed=0, curb=24, parking="禁停区域"), True)
        self.assertFalse(ok)
        self.assertIn("禁止临停", reason)

    # 既有单意图行为不回归
    def test_single_intent_scenarios_stay_on_legacy_chain(self):
        snap = taxi_snapshot(speed=0)
        self.assertIsNone(decompose_scenario("就在路口停一下，我马上上车", snap, "Robotaxi 乘客"))
        r = resolve_intent("就在路口停一下，我马上上车", snap, "Robotaxi 乘客")
        self.assertEqual(r["selected"], "modify_pickup")
        self.assertIsNone(decompose_scenario("我需要修改上车点", snap, "Robotaxi 乘客"))
        owner = owner_trip_snapshot()
        self.assertIsNone(decompose_scenario("车内有点热，请帮我把温度调得舒适一些", owner, "车主自驾"))


if __name__ == "__main__":
    unittest.main()
