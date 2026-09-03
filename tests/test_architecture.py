# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

_tmp = tempfile.mkdtemp(prefix="drivemate-test-")
os.environ.setdefault("DRIVEMATE_AUDIT_DB", os.path.join(_tmp, "audit.db"))

from components.intent_graph import resolve_intent
from components.constraint_shield import plan_candidates
from components.dependency_planner import topological_sort, DependencyError, execute_plan
from components.tool_registry import load_tool_registry
from components.tool_executor import ToolExecutor
from components.audit_store import create_session, start_run
from components.rule_engine import _plan_for, run_rule
from components.knowledge_retriever import retrieve_knowledge


def owner_snapshot():
    return {
        "identity": {"mode": "OWNER_DRIVE", "user_id": "test", "auth_level": "vin_bound"},
        "vehicle_state": {"speed_kmh": 80, "soc_percent": 18, "range_km": 65, "driving_hours": 3.5, "child_seat_detected": False},
        "order_state": {"status": "无订单", "passenger_coordinates": {"lat": 30.1, "lng": 120.1}, "vehicle_coordinates": {"lat": 30.1, "lng": 120.1}},
        "environment_state": {"time_of_day": "夜间", "area_type": "高速", "parking_policy": "允许临停"},
    }


def pax_snapshot(lat=30.26012):
    return {
        "identity": {"mode": "ROBOTAXI_RIDE", "user_id": "test", "auth_level": "order_token"},
        "vehicle_state": {"speed_kmh": 0, "soc_percent": 80, "range_km": 350, "driving_hours": 0},
        "order_state": {"status": "arriving", "vehicle_location": "路口附近",
                        "passenger_coordinates": {"lat": 30.25874, "lng": 120.16452},
                        "vehicle_coordinates": {"lat": lat, "lng": 120.16505}},
        "environment_state": {"time_of_day": "下午", "area_type": "城区", "parking_policy": "禁停"},
    }


class ArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta, _ = load_tool_registry()
        cls.session = create_session("test", "Robotaxi 乘客")

    def test_intent_negation_and_multi_intent(self):
        r = resolve_intent("我一点也不困，就是续航不够，找个充电站。", owner_snapshot(), "车主自驾")
        self.assertEqual(r["selected"], "charging")
        self.assertTrue(any(x["contribution"] < 0 for x in r["negations"]))
        r2 = resolve_intent("虽然有点困，但现在胸口闷得喘不上气。", pax_snapshot(), "Robotaxi 乘客")
        self.assertEqual(r2["selected"], "medical")
        self.assertTrue(r2["safety_override"])

    def test_low_confidence_clarifies(self):
        r = resolve_intent("帮我安排一下", owner_snapshot(), "车主自驾")
        self.assertIsNone(r["selected"])
        self.assertTrue(r["needs_clarification"])

    def test_constraint_shield_rejects_dangerous_direct_pickup(self):
        s = plan_candidates("modify_pickup", "就在路口停一下，我马上上车", pax_snapshot(), "Robotaxi 乘客")
        direct = next(c for c in s["candidates"] if c["id"] == "direct_action")
        self.assertFalse(direct["feasible"])
        self.assertTrue(direct["hard_violations"])
        self.assertEqual(s["selected_candidate"], "safe_closure")

    def test_schema_validator_is_execution_gate(self):
        run_id = start_run(self.session, "test invalid args", owner_snapshot())
        ex = ToolExecutor(self.meta, run_id=run_id)
        result, _ = ex.execute("suggest_safety_action", {"risk_type": "fatigue"}, owner_snapshot())
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "schema_invalid")

    def test_severe_fatigue_plan_triggers_real_handoff_chain(self):
        severe = _plan_for(
            "fatigue",
            "开了三个多小时有点犯困，帮我处理",
            "车主自驾",
            owner_snapshot(),
            self.meta,
        )
        tools = [step["tool"] for step in severe["steps"]]
        self.assertIn("set_climate", tools)
        self.assertLess(tools.index("transfer_to_human"), tools.index("crm_agent"))
        self.assertEqual(
            severe["steps"][tools.index("crm_agent")]["depends_on"],
            ["fatigue-human"],
        )

        moderate_snapshot = owner_snapshot()
        moderate_snapshot["vehicle_state"]["driving_hours"] = 3.0
        moderate = _plan_for(
            "fatigue",
            "我有点困",
            "车主自驾",
            moderate_snapshot,
            self.meta,
        )
        moderate_tools = [step["tool"] for step in moderate["steps"]]
        self.assertNotIn("transfer_to_human", moderate_tools)
        self.assertNotIn("crm_agent", moderate_tools)

    def test_every_human_handoff_uses_transfer_then_crm(self):
        for intent, text, mode, snapshot in (
            ("human_support", "请联系人工客服", "Robotaxi 乘客", pax_snapshot()),
            ("medical", "我胸口不舒服需要帮助", "Robotaxi 乘客", pax_snapshot()),
        ):
            plan = _plan_for(intent, text, mode, snapshot, self.meta)
            tools = [step["tool"] for step in plan["steps"]]
            self.assertLess(tools.index("transfer_to_human"), tools.index("crm_agent"))
            crm = plan["steps"][tools.index("crm_agent")]
            self.assertTrue(crm["depends_on"])
            self.assertEqual(crm["arguments"]["transfer_context"]["upstream_step_id"], crm["depends_on"][0])

    def test_local_knowledge_files_are_retrievable(self):
        refs = retrieve_knowledge("儿童安全座椅的 ISOFIX 怎么安装")
        self.assertTrue(refs)
        self.assertEqual(refs[0]["source"], "knowledge/children-ride-safety.md")

    def test_confirmation_grant_same_state_executes(self):
        snap = pax_snapshot()
        run_id = start_run(self.session, "就在路口停一下，我马上上车", snap)
        ex = ToolExecutor(self.meta, run_id=run_id)
        first = run_rule("就在路口停一下，我马上上车", "Robotaxi 乘客", snap, ex, self.meta)
        self.assertEqual(first["pending_tools"][0]["name"], "modify_pickup_point")
        grants = {p["step_id"]: p["grant_id"] for p in first["pending_tools"]}
        second = run_rule("就在路口停一下，我马上上车", "Robotaxi 乘客", snap, ex, self.meta,
                          confirmed=True, previous_calls=first["calls"], confirmed_grants=grants)
        self.assertFalse(second["pending_tools"])
        self.assertTrue(any(c["tool"] == "modify_pickup_point" and c["result"] == "success" for c in second["calls"]))

    def test_confirmation_grant_state_change_invalidates(self):
        snap = pax_snapshot()
        run_id = start_run(self.session, "就在路口停一下，我马上上车", snap)
        ex = ToolExecutor(self.meta, run_id=run_id)
        first = run_rule("就在路口停一下，我马上上车", "Robotaxi 乘客", snap, ex, self.meta)
        grants = {p["step_id"]: p["grant_id"] for p in first["pending_tools"]}
        changed = pax_snapshot(lat=30.25930)
        second = run_rule("就在路口停一下，我马上上车", "Robotaxi 乘客", changed, ex, self.meta,
                          confirmed=True, previous_calls=first["calls"], confirmed_grants=grants)
        self.assertTrue(second["pending_tools"])
        self.assertTrue(any(p.get("confirmation_invalidated") for p in second["pending_tools"]))
        self.assertFalse(any(c["tool"] == "modify_pickup_point" and c["result"] == "success" for c in second["calls"]))

    def test_same_run_side_effect_is_deduplicated(self):
        snap = pax_snapshot()
        run_id = start_run(self.session, "取消订单", snap)
        ex = ToolExecutor(self.meta, run_id=run_id)
        a, _ = ex.execute("cancel_order", {"reason": "passenger_initiated"}, snap, confirmed=True)
        b, call = ex.execute("cancel_order", {"reason": "passenger_initiated"}, snap, confirmed=True)
        self.assertTrue(a["success"] and b["success"])
        self.assertTrue(b.get("idempotency_replayed"))
        self.assertEqual(call["backend"], "idempotency_replay")

    def test_real_toposort_detects_cycle(self):
        with self.assertRaises(DependencyError):
            topological_sort([
                {"id": "a", "depends_on": ["b"]},
                {"id": "b", "depends_on": ["a"]},
            ])

    def test_recoverymesh_retries_only_idempotent(self):
        class Fake:
            run_id = None
            def __init__(self): self.n = 0
            def execute(self, tool, args, snapshot, confirmed=False, **kwargs):
                self.n += 1
                if self.n == 1:
                    r = {"success": False, "status": "backend_unreachable", "summary": "down", "backend": "fake"}
                else:
                    r = {"success": True, "status": "executed", "summary": "ok", "backend": "fake", "destination": "安全点"}
                return r, {"tool": tool, "result": "success" if r["success"] else r["status"], "summary": r["summary"], "level": "L0"}
        fake = Fake()
        meta = {"find_rest_area": {"level": "L0", "confirm": False, "idempotent": True}}
        out = execute_plan([{"id": "q", "seq": 1, "title": "q", "tool": "find_rest_area", "arguments": {}, "depends_on": []}], fake, owner_snapshot(), False, meta)
        self.assertEqual(fake.n, 2)
        self.assertEqual(out["replans"][0]["action"], "retry")
        self.assertTrue(any(s.get("status") == "degraded" for s in out["steps"]))


if __name__ == "__main__":
    unittest.main()
