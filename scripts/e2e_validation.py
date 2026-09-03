# -*- coding: utf-8 -*-
"""Validate the reviewer fatigue scenario through the real application boundary.

Path under test:
HttpBackendClient -> Agent REST API -> decision pipeline -> cockpit simulator
-> simulator readback -> authenticated SQLite audit download.
"""
from __future__ import annotations

import json
import os
import secrets
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".artifacts" / "validation"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from start_demo import (  # noqa: E402
    _free_local_port,
    _wait_for_authenticated_health,
    _wait_for_backend_health,
)


JsonObject = Dict[str, Any]
LOCAL_ENGINE = "融合编排引擎（本地可审计）"
FATIGUE_MESSAGE = "开了三个多小时有点犯困，帮我处理"
SIMULATOR_TOOLS = {"set_climate", "set_seat", "play_media", "plan_route"}


def p95(values: Iterable[float]) -> Optional[float]:
    vals = sorted(values)
    if not vals:
        return None
    index = min(len(vals) - 1, max(0, int(round(0.95 * len(vals) + 0.5)) - 1))
    return round(vals[index], 2)


def latency_summary(values: List[float]) -> JsonObject:
    return {
        "samples": len(values),
        "avg": round(statistics.mean(values), 2) if values else None,
        "p95": p95(values),
        "min": round(min(values), 2) if values else None,
        "max": round(max(values), 2) if values else None,
    }


def owner_snapshot() -> JsonObject:
    return {
        "identity": {
            "mode": "OWNER_DRIVE",
            "user_id": "e2e_user",
            "auth_level": "vin_bound",
        },
        "vehicle_state": {
            "speed_kmh": 110,
            "soc_percent": 45,
            "range_km": 280,
            "driving_hours": 3.5,
            "child_seat_detected": False,
        },
        "order_state": {
            "status": "无订单",
            "vehicle_location": "高速",
            "passenger_coordinates": {"lat": 30.2741, "lng": 120.1551},
            "vehicle_coordinates": {"lat": 30.2741, "lng": 120.1551},
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
            "captured_at": "2026-09-03T07:00:00Z",
            "source": "e2e_simulated_sensor_bus",
            "simulated": True,
            "streams": [],
        },
    }


def passenger_snapshot(*, far: bool) -> JsonObject:
    return {
        "identity": {
            "mode": "ROBOTAXI_RIDE",
            "user_id": "e2e_pax",
            "auth_level": "order_token",
        },
        "vehicle_state": {
            "speed_kmh": 0,
            "soc_percent": 80,
            "range_km": 350,
            "driving_hours": 0,
            "child_seat_detected": False,
        },
        "order_state": {
            "status": "arriving",
            "vehicle_location": "接驾点",
            "passenger_coordinates": {"lat": 30.25874, "lng": 120.16452},
            "vehicle_coordinates": {
                "lat": 30.26012 if far else 30.25904,
                "lng": 120.16505 if far else 120.16452,
            },
        },
        "environment_state": {
            "weather": "晴",
            "traffic": "畅通",
            "time_of_day": "下午",
            "area_type": "城区",
            "parking_policy": "允许临停",
        },
        "sensor_state": {
            "schema_version": "1.0",
            "captured_at": "2026-09-03T07:00:00Z",
            "source": "e2e_simulated_sensor_bus",
            "simulated": True,
            "streams": [],
        },
    }


def find_call(
    result: JsonObject,
    tool: str,
    *,
    successful: Optional[bool] = None,
) -> Optional[JsonObject]:
    calls = [call for call in result.get("calls", []) if call.get("tool") == tool]
    if successful is not None:
        calls = [
            call
            for call in calls
            if (call.get("result") == "success") is successful
        ]
    return calls[-1] if calls else None


def raw_result(call: Optional[JsonObject]) -> JsonObject:
    value = call.get("raw_result") if call else None
    return value if isinstance(value, dict) else {}


def stop_process(process: Optional[subprocess.Popen]) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def main() -> int:
    simulator_token = "e2e-sim-" + secrets.token_urlsafe(24)
    api_token = "e2e-api-" + secrets.token_urlsafe(24)
    simulator_port = _free_local_port()
    backend_port = _free_local_port()
    while backend_port == simulator_port:
        backend_port = _free_local_port()
    simulator_url = f"http://127.0.0.1:{simulator_port}"
    backend_url = f"http://127.0.0.1:{backend_port}"
    audit_db = ARTIFACTS / "e2e_audit.db"
    simulator_db = ARTIFACTS / "e2e_simulator.db"
    for path in (audit_db, simulator_db):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    env = os.environ.copy()
    env.update(
        {
            "DRIVEMATE_SIMULATOR_TOKEN": simulator_token,
            "DRIVEMATE_SIMULATOR_URL": simulator_url,
            "DRIVEMATE_SIMULATOR_DB": str(simulator_db),
            "DRIVEMATE_AUDIT_DB": str(audit_db),
            "DRIVEMATE_API_TOKEN": api_token,
            "DRIVEMATE_BACKEND_URL": backend_url,
            "DRIVEMATE_API_MODE": "http",
        }
    )

    simulator: Optional[subprocess.Popen] = None
    backend: Optional[subprocess.Popen] = None
    try:
        simulator = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "simulator_server.py"),
                "--host",
                "127.0.0.1",
                "--port",
                str(simulator_port),
                f"--token={simulator_token}",
                f"--db={simulator_db}",
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for_authenticated_health(
            simulator_url, simulator_token, simulator, timeout_s=8
        )

        backend = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "backend_server.py"),
                "--host",
                "127.0.0.1",
                "--port",
                str(backend_port),
                f"--token={api_token}",
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for_backend_health(backend_url, api_token, backend, timeout_s=8)

        # Import after setting environment variables because backend settings are
        # immutable once imported.
        from api_client import HttpBackendClient

        client = HttpBackendClient(backend_url, api_token, timeout_seconds=30)
        health = client.health()
        metadata = client.meta()
        if health.get("status") not in {"ok", "degraded"}:
            raise RuntimeError(f"Agent API is not healthy: {health}")
        if LOCAL_ENGINE not in metadata.get("engines", []):
            raise RuntimeError("The auditable local Agent engine is unavailable.")

        scenario_results = []
        simulator_latencies: List[float] = []
        create_latencies: List[float] = []
        confirm_latencies: List[float] = []

        for index in range(10):
            snapshot = owner_snapshot()
            started = time.perf_counter()
            created = client.run_agent(
                FATIGUE_MESSAGE, "车主自驾", LOCAL_ENGINE, snapshot
            )
            create_latencies.append((time.perf_counter() - started) * 1000)

            pending_navigation = any(
                item.get("name") == "plan_route"
                for item in created.get("pending_tools", [])
            )
            started = time.perf_counter()
            confirmed = client.confirm_run(created["run_id"], snapshot)
            confirm_latencies.append((time.perf_counter() - started) * 1000)

            simulator_state = client.simulator_state()
            state_keys = set((simulator_state.get("state") or {}).keys())
            audit = client.audit_run(created["run_id"])

            for call in confirmed.get("calls", []):
                if (
                    call.get("tool") in SIMULATOR_TOOLS
                    and call.get("backend") == "simulator_http"
                    and isinstance(call.get("latency_ms"), (int, float))
                ):
                    simulator_latencies.append(float(call["latency_ms"]))

            fatigue = raw_result(find_call(created, "get_fatigue_status", successful=True))
            climate = find_call(created, "set_climate", successful=True)
            seat = find_call(created, "set_seat", successful=True)
            media = find_call(created, "play_media", successful=True)
            navigation = find_call(confirmed, "plan_route", successful=True)
            handoff = find_call(created, "transfer_to_human", successful=True)
            crm = find_call(created, "crm_agent", successful=True)
            critical = {
                "agent_intent_and_l3": (
                    created.get("intent") == "fatigue"
                    and created.get("risk_level") == "L3"
                ),
                "fatigue_detected": fatigue.get("fatigue_index", 0) >= 0.6,
                "climate_receipt": bool(climate and climate.get("receipt_id")),
                "seat_receipt": bool(seat and seat.get("receipt_id")),
                "media_receipt": bool(media and media.get("receipt_id")),
                "navigation_blocked_before_confirm": (
                    pending_navigation
                    and find_call(created, "plan_route", successful=True) is None
                ),
                "navigation_receipt_after_confirm": bool(
                    navigation and navigation.get("receipt_id")
                ),
                "state_verifiable": {
                    "climate",
                    "seat",
                    "media",
                    "navigation",
                }.issubset(state_keys),
                "handoff_rule_triggered": bool(handoff),
                "crm_agent_rule_triggered": bool(crm),
                "human_ticket_persisted": bool(audit.get("tickets")),
                "confirmation_persisted": any(
                    item.get("tool") == "plan_route"
                    and item.get("decision") == "confirmed"
                    for item in audit.get("confirmations", [])
                ),
                "decision_trace_persisted": len(audit.get("decision_events", [])) >= 3,
            }
            success = all(critical.values())
            scenario_results.append(
                {
                    "run": index + 1,
                    "success": success,
                    "checks": critical,
                    "run_id": created["run_id"],
                }
            )

        far_snapshot = passenger_snapshot(far=True)
        far_created = client.run_agent(
            "找不到接驾车辆，请帮我闪灯鸣笛",
            "Robotaxi 乘客",
            LOCAL_ENGINE,
            far_snapshot,
        )
        far_confirmed = client.confirm_run(far_created["run_id"], far_snapshot)
        far_call = find_call(far_confirmed, "contact_vehicle", successful=False)
        far_result = raw_result(far_call)

        near_snapshot = passenger_snapshot(far=False)
        near_created = client.run_agent(
            "找不到接驾车辆，请帮我闪灯鸣笛",
            "Robotaxi 乘客",
            LOCAL_ENGINE,
            near_snapshot,
        )
        near_confirmed = client.confirm_run(near_created["run_id"], near_snapshot)
        near_call = find_call(near_confirmed, "contact_vehicle", successful=True)
        near_result = raw_result(near_call)

        bad_api = requests.get(
            backend_url + "/health",
            headers={"Authorization": "Bearer invalid-token"},
            timeout=2,
        )
        bad_simulator = requests.get(
            simulator_url + "/health",
            headers={"Authorization": "Bearer invalid-token"},
            timeout=2,
        )

        successes = sum(item["success"] for item in scenario_results)
        security_checks = {
            "invalid_agent_api_token_rejected": bad_api.status_code == 401,
            "invalid_simulator_token_rejected": bad_simulator.status_code == 401,
            "far_contact_required_confirmation": any(
                item.get("name") == "contact_vehicle"
                for item in far_created.get("pending_tools", [])
            ),
            "far_contact_blocked": (
                far_call is not None
                and far_result.get("distance_verified") is True
                and float(far_result.get("distance_m", 0)) > 100
            ),
            "far_distance_m": far_result.get("distance_m"),
            "near_contact_required_confirmation": any(
                item.get("name") == "contact_vehicle"
                for item in near_created.get("pending_tools", [])
            ),
            "near_contact_executed": bool(
                near_call and near_call.get("receipt_id")
            ),
            "near_distance_m": (
                (near_result.get("verified_state") or {}).get("distance_m")
                or near_result.get("distance_m")
            ),
        }
        security_passed = all(
            security_checks[key]
            for key in (
                "invalid_agent_api_token_rejected",
                "invalid_simulator_token_rejected",
                "far_contact_required_confirmation",
                "far_contact_blocked",
                "near_contact_required_confirmation",
                "near_contact_executed",
            )
        )
        report = {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "environment": "localhost authenticated Agent API and independent HTTP cockpit simulator",
            "path": (
                "HttpBackendClient -> Agent REST API -> IntentGraph -> "
                "ConstraintShield -> DependencyPlanner -> ToolExecutor -> "
                "cockpit simulator/readback -> SQLite audit"
            ),
            "scenario": (
                "司机疲劳 → L3 风险 → 空调/按摩/音乐执行 → "
                "规则触发人工转接与 CRM 接管 → 导航强制确认 → 状态及审计回读"
            ),
            "runs": len(scenario_results),
            "successful_runs": successes,
            "task_success_rate_percent": round(
                100.0 * successes / len(scenario_results), 2
            ),
            "agent_api_create_latency_ms": latency_summary(create_latencies),
            "agent_api_confirm_latency_ms": latency_summary(confirm_latencies),
            "simulator_control_latency_ms": latency_summary(simulator_latencies),
            "security_checks": security_checks,
            "scenario_results": scenario_results,
        }
        (ARTIFACTS / "e2e_validation.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        markdown = """# Full-stack E2E Validation Report

- Generated: {generated}
- Environment: `{environment}`
- Path: `{path}`
- Scenario: {scenario}
- Runs: **{runs}**
- Successful runs: **{successes}**
- Task success rate: **{rate}%**
- Agent create latency: avg **{create_avg} ms**, p95 **{create_p95} ms**
- Agent confirmation latency: avg **{confirm_avg} ms**, p95 **{confirm_p95} ms**
- Simulator control latency: avg **{control_avg} ms**, p95 **{control_p95} ms** ({control_samples} samples)

## Security checks

- Invalid Agent API token rejected: **{bad_api}**
- Invalid simulator token rejected: **{bad_simulator}**
- `contact_vehicle` >100m blocked after confirmation: **{far_blocked}** ({far_distance} m)
- `contact_vehicle` <100m executed after confirmation: **{near_executed}** ({near_distance} m)

## What is actually verified

Every successful run starts with the same frontend HTTP client used by Streamlit.
It crosses the authenticated REST API and the real Agent decision pipeline. The
rule-generated plan must produce verifiable climate, seat, and media receipts,
persist a rule-triggered human handoff and CRM takeover, block navigation until
confirmation, execute it afterward, read simulator state back, and expose the
complete decoded SQLite audit chain.

> Measurements are from the localhost simulator, not a production vehicle.
""".format(
            generated=report["generated_at"],
            environment=report["environment"],
            path=report["path"],
            scenario=report["scenario"],
            runs=report["runs"],
            successes=report["successful_runs"],
            rate=report["task_success_rate_percent"],
            create_avg=report["agent_api_create_latency_ms"]["avg"],
            create_p95=report["agent_api_create_latency_ms"]["p95"],
            confirm_avg=report["agent_api_confirm_latency_ms"]["avg"],
            confirm_p95=report["agent_api_confirm_latency_ms"]["p95"],
            control_avg=report["simulator_control_latency_ms"]["avg"],
            control_p95=report["simulator_control_latency_ms"]["p95"],
            control_samples=report["simulator_control_latency_ms"]["samples"],
            bad_api=security_checks["invalid_agent_api_token_rejected"],
            bad_simulator=security_checks["invalid_simulator_token_rejected"],
            far_blocked=security_checks["far_contact_blocked"],
            far_distance=security_checks["far_distance_m"],
            near_executed=security_checks["near_contact_executed"],
            near_distance=security_checks["near_distance_m"],
        )
        (ARTIFACTS / "e2e_validation.md").write_text(markdown, encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if successes == len(scenario_results) and security_passed else 2
    finally:
        stop_process(backend)
        stop_process(simulator)


if __name__ == "__main__":
    raise SystemExit(main())
