# -*- coding: utf-8 -*-
"""决策账本与真实 Trace 构造。所有阶段耗时来自实际 perf_counter 计时。"""
from __future__ import annotations
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional


class TraceRecorder:
    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    @contextmanager
    def stage(self, name: str):
        t0 = time.perf_counter()
        box: Dict[str, Any] = {}
        try:
            yield box
        finally:
            self.events.append({"stage": name, "output": str(box.get("output", "")),
                                "duration_ms": round((time.perf_counter() - t0) * 1000, 3)})

    def add(self, stage: str, output: str, duration_ms: Optional[float] = None):
        self.events.append({"stage": stage, "output": output, "duration_ms": duration_ms})


def risk_contributions(intent_resolution: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for ev in intent_resolution.get("signals", []) + intent_resolution.get("negations", []):
        out.append({"factor": ev.get("label"), "value": ev.get("phrase"),
                    "contribution": ev.get("contribution"), "source": ev.get("source"),
                    "direction": "support" if float(ev.get("contribution") or 0) > 0 else "oppose"})
    return out


def build_ledger(intent_resolution: Dict[str, Any], shield: Dict[str, Any], execution: Dict[str, Any],
                 trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "algorithm": {"intent": f"{intent_resolution.get('algorithm')} {intent_resolution.get('version')}",
                      "planner": f"{shield.get('algorithm')} {shield.get('version')}",
                      "recovery": "RecoveryMesh 2.0"},
        "intent_resolution": intent_resolution,
        "risk_contributions": risk_contributions(intent_resolution),
        "constraint_shield": shield,
        "recovery": {"state": "degraded" if execution.get("replans") else "nominal",
                     "replans": execution.get("replans", []),
                     "invariants": ["失败工具不会标记成功", "降级工具仍经过 SchemaValidator + SafetyGuard",
                                    "非幂等工具不做自动故障重试", "上游失败自动阻断依赖分支"]},
        "topology": execution.get("topology", {}),
        "trace": trace,
    }
