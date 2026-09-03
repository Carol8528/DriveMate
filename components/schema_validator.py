# -*- coding: utf-8 -*-
"""工具参数 SchemaValidator：对 tools/*.json 的常用 JSON Schema 子集做统一硬校验。"""
from __future__ import annotations
import re
from typing import Any, Dict, List


def _typename(value: Any) -> str:
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, dict): return "object"
    if isinstance(value, list): return "array"
    if isinstance(value, str): return "string"
    if isinstance(value, int): return "integer"
    if isinstance(value, float): return "number"
    return type(value).__name__


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object": return isinstance(value, dict)
    if expected == "array": return isinstance(value, list)
    if expected == "string": return isinstance(value, str)
    if expected == "boolean": return isinstance(value, bool)
    if expected == "integer": return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number": return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _validate(value: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    expected = schema.get("type")
    if expected and not _type_ok(value, expected):
        errors.append(f"{path}: 期望 {expected}，实际 {_typename(value)}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 值 {value!r} 不在允许集合 {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]: errors.append(f"{path}: 小于最小值 {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]: errors.append(f"{path}: 大于最大值 {schema['maximum']}")
    if isinstance(value, str) and schema.get("pattern"):
        if not re.search(schema["pattern"], value): errors.append(f"{path}: 不满足格式 {schema['pattern']}")
    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in value or value[key] is None:
                errors.append(f"{path}.{key}: 缺少必填参数")
        props = schema.get("properties") or {}
        for key, child in value.items():
            if key in props:
                _validate(child, props[key], f"{path}.{key}", errors)
    if isinstance(value, list) and schema.get("items"):
        for idx, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{idx}]", errors)


def validate_arguments(arguments: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    if not isinstance(arguments, dict):
        return {"valid": False, "errors": ["arguments: 必须为 object"]}
    _validate(arguments, schema or {"type": "object"}, "arguments", errors)
    return {"valid": not errors, "errors": errors}
