# -*- coding: utf-8 -*-
"""工具 Schema 注册表。tools/**/*.json 是唯一事实源。"""
import glob
import json
import os


def load_tool_registry(project_root=None):
    meta, schemas = {}, []
    root = project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = os.path.join(root, "tools")
    for path in sorted(glob.glob(os.path.join(base, "**", "*.json"), recursive=True)):
        try:
            with open(path, encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        name = spec.get("name")
        if not name:
            continue
        dom = spec.get("domain", "")
        mode = "both" if dom == "human_emergency" else ("robotaxi" if dom == "robotaxi_order" else "owner")
        level = spec.get("safety_level", "L0")
        confirm = bool(spec.get("requires_confirmation", False)) or level == "L2"
        meta[name] = {
            "domain": mode,
            "level": level,
            "confirm": confirm,
            "idempotent": bool(spec.get("idempotent", False)),
            "description": spec.get("description", ""),
            "constraints": spec.get("constraints", ""),
            "parameters": spec.get("parameters", {"type": "object", "properties": {}}),
            "source_path": path,
        }
        desc = "%s（安全等级 %s%s" % (spec.get("description", ""), level, "，需用户确认后执行）" if confirm else "）")
        schemas.append({
            "type": "function",
            "function": {"name": name, "description": desc,
                         "parameters": spec.get("parameters", {"type": "object", "properties": {}})},
        })
    return meta, schemas
