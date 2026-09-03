# -*- coding: utf-8 -*-
"""工具依赖编排器：真实 DAG 校验、拓扑排序、上游结果绑定、失败阻断与 RecoveryMesh 动态重规划。"""
from __future__ import annotations
from copy import deepcopy
from typing import Any, Dict, List, Optional

from components.recovery_mesh import recovery_decision, fallback_arguments
from components.confirmation_grant import make_grant


class DependencyError(ValueError):
    pass


def topological_sort(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {str(s["id"]): s for s in steps}
    indegree = {sid: 0 for sid in by_id}
    children = {sid: [] for sid in by_id}
    for sid, step in by_id.items():
        for dep in step.get("depends_on") or []:
            dep = str(dep)
            if dep not in by_id:
                raise DependencyError(f"步骤 {sid} 依赖不存在的步骤 {dep}")
            indegree[sid] += 1
            children[dep].append(sid)
    queue = [sid for sid, deg in indegree.items() if deg == 0]
    ordered = []
    while queue:
        sid = queue.pop(0)
        ordered.append(by_id[sid])
        for child in children[sid]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(ordered) != len(steps):
        raise DependencyError("工具依赖图存在环")
    return ordered


def _path_get(obj: Any, path: str):
    cur = obj
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            raise DependencyError(f"上游结果中不存在字段 {path}")
    return cur


def _resolve(value: Any, outputs: Dict[str, Dict[str, Any]]) -> Any:
    if isinstance(value, dict) and set(value.keys()) >= {"$from", "path"}:
        src = str(value["$from"])
        if src not in outputs:
            raise DependencyError(f"尚无上游步骤 {src} 的可用输出")
        return _path_get(outputs[src], str(value["path"]))
    if isinstance(value, dict):
        return {k: _resolve(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, outputs) for v in value]
    return value


def execute_plan(steps: List[Dict[str, Any]], executor, snapshot: Dict[str, Any], confirmed: bool,
                 tool_meta: Dict[str, Dict[str, Any]], previous_calls: Optional[List[dict]] = None,
                 confirmed_grants: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    ordered = topological_sort(steps)
    calls = list(previous_calls or []) if confirmed else []
    status_by_id: Dict[str, str] = {}
    outputs: Dict[str, Dict[str, Any]] = {}
    pending = []
    replans = []
    executed_steps: List[Dict[str, Any]] = []

    for original in ordered:
        step = deepcopy(original)
        sid, tool = str(step["id"]), step.get("tool", "")
        deps = [str(x) for x in (step.get("depends_on") or [])]
        blocked_deps = [d for d in deps if status_by_id.get(d) not in {"done", "degraded"}]
        if blocked_deps:
            step["status"] = "blocked_dependency"
            step["note"] = "上游步骤未成功：" + "、".join(blocked_deps)
            status_by_id[sid] = step["status"]
            executed_steps.append(step)
            continue

        try:
            resolved_args = _resolve(step.get("arguments") or {}, outputs)
        except DependencyError as e:
            step["status"] = "blocked_dependency"
            step["note"] = str(e)
            status_by_id[sid] = step["status"]
            executed_steps.append(step)
            continue
        step["arguments"] = resolved_args

        meta = tool_meta.get(tool, {})
        requires_confirm = bool(meta.get("confirm"))
        grant = make_grant(tool, resolved_args, snapshot) if requires_confirm else None
        if requires_confirm and not confirmed:
            step["status"] = "pending_confirm"
            step["confirmation_grant"] = grant
            pending.append({"name": tool, "arguments": resolved_args, "step_id": sid,
                            "depends_on": deps, "safety_level": meta.get("level", "L0"), **grant})
            status_by_id[sid] = step["status"]
            executed_steps.append(step)
            continue
        if requires_confirm and confirmed:
            expected = (confirmed_grants or {}).get(sid)
            if not expected or expected != grant["grant_id"]:
                step["status"] = "pending_confirm"
                step["note"] = "确认已失效：工具参数或实时状态版本发生变化，需要重新确认"
                step["confirmation_grant"] = grant
                pending.append({"name": tool, "arguments": resolved_args, "step_id": sid,
                                "depends_on": deps, "safety_level": meta.get("level", "L0"),
                                "confirmation_invalidated": True, **grant})
                status_by_id[sid] = step["status"]
                executed_steps.append(step)
                continue

        # 确认时：只对标记 refresh_on_confirm 的读取步骤重新读实时状态；其余已执行步骤沿用。
        if confirmed and not requires_confirm and not step.get("refresh_on_confirm"):
            step["status"] = "done"
            step["note"] = step.get("note") or "沿用确认前已验证的执行结果"
            status_by_id[sid] = "done"
            # 若后续绑定依赖该步骤，必须重新读；因此含 output_binding 的步骤应设置 refresh_on_confirm=True。
            executed_steps.append(step)
            continue

        result, call = executor.execute(tool, resolved_args, snapshot, confirmed=confirmed,
                                        force_refresh=bool(confirmed and step.get("refresh_on_confirm")))
        calls.append(call)
        if result.get("success"):
            step["status"] = "done"
            step["note"] = result.get("summary", "")
            status_by_id[sid] = "done"
            outputs[sid] = result
            executed_steps.append(step)
            continue
        if result.get("status") == "pending_user_confirmation":
            step["status"] = "pending_confirm"
            pending.append({"name": tool, "arguments": resolved_args, "step_id": sid,
                            "depends_on": deps, "safety_level": meta.get("level", "L0")})
            status_by_id[sid] = step["status"]
            executed_steps.append(step)
            continue

        step["status"] = "failed"
        step["note"] = result.get("summary", "执行失败")
        status_by_id[sid] = "failed"
        executed_steps.append(step)
        decision = recovery_decision(tool, result, bool(meta.get("idempotent")), retry_count=0)

        if decision["action"] == "retry":
            retry_result, retry_call = executor.execute(tool, resolved_args, snapshot, confirmed=confirmed,
                                                        is_retry=True, force_refresh=True)
            calls.append(retry_call)
            replans.append({"failed_tool": tool, "replacement_tool": tool, "fault_type": decision["failure_type"],
                            "policy_id": decision["policy_id"], "reason": decision["reason"], "action": "retry"})
            if retry_result.get("success"):
                retry_step = deepcopy(step)
                retry_step["id"] = sid + "-retry"
                retry_step["status"] = "degraded"
                retry_step["note"] = "幂等重试成功：" + retry_result.get("summary", "")
                retry_step["replaces"] = sid
                executed_steps.append(retry_step)
                status_by_id[sid] = "degraded"
                outputs[sid] = retry_result
                continue
            decision = recovery_decision(tool, retry_result, bool(meta.get("idempotent")), retry_count=1)
            result = retry_result

        if decision["action"] == "fallback":
            fb_tool = decision["tool"]
            fb_meta = tool_meta.get(fb_tool, {})
            fb_args = fallback_arguments(tool, fb_tool, snapshot, result)
            fb_id = sid + "-fallback"
            fb_step = {"id": fb_id, "seq": step.get("seq"), "title": "RecoveryMesh 降级：" + fb_tool,
                       "tool": fb_tool, "arguments": fb_args, "depends_on": [], "status": "degraded",
                       "safety_level": fb_meta.get("level", "L0"), "note": decision["reason"], "replaces": sid}
            if fb_meta.get("confirm") and not confirmed:
                fb_step["status"] = "pending_confirm"
                fb_grant = make_grant(fb_tool, fb_args, snapshot)
                fb_step["confirmation_grant"] = fb_grant
                pending.append({"name": fb_tool, "arguments": fb_args, "step_id": fb_id, "depends_on": [],
                                "safety_level": fb_meta.get("level", "L0"), **fb_grant})
                executed_steps.append(fb_step)
            else:
                fb_result, fb_call = executor.execute(fb_tool, fb_args, snapshot, confirmed=confirmed)
                calls.append(fb_call)
                fb_step["status"] = "degraded" if fb_result.get("success") else "failed"
                fb_step["note"] = (decision["reason"] + "；" + fb_result.get("summary", "")).strip("；")
                executed_steps.append(fb_step)
                if fb_result.get("success"):
                    status_by_id[sid] = "degraded"
                    outputs[sid] = fb_result
            replans.append({"failed_tool": tool, "replacement_tool": fb_tool, "fault_type": decision["failure_type"],
                            "policy_id": decision["policy_id"], "reason": decision["reason"], "action": "fallback"})

    return {"steps": executed_steps, "calls": calls, "pending_tools": pending,
            "replans": replans, "topology": {"nodes": len(steps), "cycles": 0, "order": [str(s["id"]) for s in ordered]}}
