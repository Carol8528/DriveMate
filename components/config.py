# -*- coding: utf-8 -*-
"""运行配置：所有密钥/令牌仅从环境变量读取，禁止源码硬编码。"""
import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(1, value)


@dataclass(frozen=True)
class Settings:
    # 外接模型采用 OpenAI-compatible Chat Completions。默认指向百炼兼容模式，
    # 因此仅设置 API_KEY 即可启用；其他服务商可覆盖 LLM_BASE_URL / LLM_MODEL。
    llm_api_key: str = os.environ.get("API_KEY", "").strip()
    llm_base_url: str = os.environ.get(
        "LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    llm_model: str = os.environ.get("LLM_MODEL", "qwen-plus").strip() or "qwen-plus"
    llm_timeout_seconds: int = _int_env("LLM_TIMEOUT_SECONDS", 30)

    simulator_url: str = os.environ.get(
        "DRIVEMATE_SIMULATOR_URL", "http://127.0.0.1:8765"
    ).rstrip("/")
    simulator_token: str = os.environ.get("DRIVEMATE_SIMULATOR_TOKEN", "").strip()
    audit_db: str = os.environ.get(
        "DRIVEMATE_AUDIT_DB",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "audit.db"),
    )


SETTINGS = Settings()
