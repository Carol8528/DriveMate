# -*- coding: utf-8 -*-
"""运行配置：所有密钥/令牌仅从环境变量读取，禁止源码硬编码。"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    bailian_base_url: str = os.environ.get("BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/api/v1/apps")
    bailian_app_id: str = os.environ.get("DRIVEMATE_APP_ID", "").strip()
    dashscope_api_key: str = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    simulator_url: str = os.environ.get("DRIVEMATE_SIMULATOR_URL", "http://127.0.0.1:8765").rstrip("/")
    simulator_token: str = os.environ.get("DRIVEMATE_SIMULATOR_TOKEN", "").strip()
    audit_db: str = os.environ.get("DRIVEMATE_AUDIT_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "audit.db"))


SETTINGS = Settings()
