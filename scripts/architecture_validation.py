# -*- coding: utf-8 -*-
"""融合架构验证：在独立 HTTP 座舱模拟器上验证 IntentGraph → DAG → ConfirmationGrant → ToolExecutor。"""
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".artifacts" / "validation"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def wait(url, token):
    for _ in range(50):
        try:
            if requests.get(url + "/health", headers={"Authorization": "Bearer " + token}, timeout=.3).ok:
                return True
        except Exception:
            pass
        time.sleep(.1)
    return False


def owner_snapshot():
    return {"identity": {"mode": "OWNER_DRIVE", "user_id": "arch", "auth_level": "vin_bound"},
            "vehicle_state": {"speed_kmh": 110, "soc_percent": 45, "range_km": 280, "driving_hours": 3.5, "child_seat_detected": False},
            "order_state": {"status": "无订单", "vehicle_location": "高速", "passenger_coordinates": {"lat": 30.1, "lng": 120.1}, "vehicle_coordinates": {"lat": 30.1, "lng": 120.1}},
            "environment_state": {"weather": "晴", "traffic": "畅通", "time_of_day": "夜间", "area_type": "高速", "parking_policy": "允许临停"}}


def pax_snapshot(lat=30.26012):
    return {"identity": {"mode": "ROBOTAXI_RIDE", "user_id": "arch", "auth_level": "order_token"},
            "vehicle_state": {"speed_kmh": 0, "soc_percent": 80, "range_km": 350, "driving_hours": 0, "child_seat_detected": False},
            "order_state": {"status": "arriving", "vehicle_location": "路口", "passenger_coordinates": {"lat": 30.25874, "lng": 120.16452}, "vehicle_coordinates": {"lat": lat, "lng": 120.16505}},
            "environment_state": {"weather": "晴", "traffic": "畅通", "time_of_day": "下午", "area_type": "城区", "parking_policy": "禁停"}}


def main():
    token = secrets.token_urlsafe(24)
    port = 18766
    url = f"http://127.0.0.1:{port}"
    audit = ARTIFACTS / "architecture_validation_audit.db"
    simdb = ARTIFACTS / "architecture_validation_simulator.db"
    for p in (audit, simdb):
        try: p.unlink()
        except FileNotFoundError: pass
    env = os.environ.copy()
    env.update({"DRIVEMATE_SIMULATOR_TOKEN": token, "DRIVEMATE_SIMULATOR_URL": url, "DRIVEMATE_AUDIT_DB": str(audit), "DRIVEMATE_SIMULATOR_DB": str(simdb)})
    os.environ.update(env)
    proc = subprocess.Popen([sys.executable, str(ROOT / "simulator_server.py"), "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        if not wait(url, token): raise RuntimeError("simulator not ready")
        from components.tool_registry import load_tool_registry
        from components.tool_executor import ToolExecutor
        from components.audit_store import create_session, start_run, get_run_trace
        from components.rule_engine import run_rule
        from components.intent_graph import resolve_intent

        meta, _ = load_tool_registry()
        sid = create_session("arch", "mixed")
        checks = {}

        # 1. 否定作用域
        r = resolve_intent("我一点也不困，就是续航不够，找个充电站。", owner_snapshot(), "车主自驾")
        checks["negation_scope"] = r.get("selected") == "charging" and bool(r.get("negations"))

        # 2. 疲劳真实 DAG + 确认后导航
        snap = owner_snapshot(); rid = start_run(sid, "开了三个多小时有点犯困", snap); ex = ToolExecutor(meta, rid)
        first = run_rule("开了三个多小时有点犯困", "车主自驾", snap, ex, meta)
        grants = {p["step_id"]: p["grant_id"] for p in first.get("pending_tools", [])}
        second = run_rule("开了三个多小时有点犯困", "车主自驾", snap, ex, meta, True, first.get("calls"), confirmed_grants=grants)
        checks["dag_topology_real"] = first.get("topology", {}).get("cycles") == 0 and "fatigue-route" in first.get("topology", {}).get("order", [])
        checks["confirmation_executes_navigation"] = any(c.get("tool") == "plan_route" and c.get("receipt_id") for c in second.get("calls", []))

        # 3. 危险上车点：安全候选来自上游结果并绑定确认
        ps = pax_snapshot(); prid = start_run(sid, "就在路口停一下，我马上上车", ps); pex = ToolExecutor(meta, prid)
        pfirst = run_rule("就在路口停一下，我马上上车", "Robotaxi 乘客", ps, pex, meta)
        pending = pfirst.get("pending_tools", [])
        checks["upstream_binding"] = bool(pending and pending[0]["arguments"].get("new_location", {}).get("address"))
        checks["dangerous_direct_filtered"] = any(c.get("id") == "direct_action" and not c.get("feasible") for c in pfirst.get("constraint_shield", {}).get("candidates", []))

        # 4. 状态变化使旧 ConfirmationGrant 失效
        pgrants = {p["step_id"]: p["grant_id"] for p in pending}
        changed = pax_snapshot(lat=30.25930)
        psecond = run_rule("就在路口停一下，我马上上车", "Robotaxi 乘客", changed, pex, meta, True, pfirst.get("calls"), confirmed_grants=pgrants)
        checks["confirmation_invalidated_on_state_change"] = any(p.get("confirmation_invalidated") for p in psecond.get("pending_tools", []))

        trace = get_run_trace(rid)
        checks["decision_trace_persisted"] = len(trace.get("decision_events", [])) >= 3
        report = {"checks": checks, "passed": sum(bool(v) for v in checks.values()), "total": len(checks), "all_passed": all(checks.values())}
        (ARTIFACTS / "architecture_validation.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["all_passed"] else 2
    finally:
        proc.terminate()
        try: proc.wait(2)
        except Exception: proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
