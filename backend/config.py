"""全局配置：密钥不硬编码（方案约定 ①）。

优先级：环境变量 > data/settings.json（本地运行时配置）> 默认值
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "app.db"
DB_URL = f"sqlite:///{DB_PATH.as_posix()}"

SETTINGS_FILE = DATA_DIR / "settings.json"
SECRET_FILE = DATA_DIR / ".secret"

# 星辰大模型（第四章 4.1 / 附录 C1）
# 官方说明：不同区域、不同类型的模型，终端请求地址有差异，以控制台「调用示例」为准。
DEFAULT_BASE_URL = "https://ai.ctaigw.cn/v1"

# 官方文档核实的可用 base_url（https://www.ctyun.cn/document/11061839/11062312）
# 终端节点：大陆 ai.ctaigw.cn；全球 ai.ctaigw.com/{region}/，region ∈ amer/eu/as
BASE_URL_PRESETS = [
    {"label": "大陆 · 普通推理", "value": "https://ai.ctaigw.cn/v1"},
    {"label": "大陆 · 编程 Token Plan", "value": "https://ai.ctaigw.cn/coding/v1"},
    {"label": "全球 · 美洲", "value": "https://ai.ctaigw.com/amer/v1"},
    {"label": "全球 · 欧洲", "value": "https://ai.ctaigw.com/eu/v1"},
    {"label": "全球 · 亚洲", "value": "https://ai.ctaigw.com/as/v1"},
]

# 平台入口（这些才是浏览器能打开的网页；ai.ctaigw.cn 是 API，不是网页）
CONSOLE_URL = "https://ctxirang.ctyun.cn/maas/home"
APPKEY_URL = "https://ctxirang.ctyun.cn/maas/service/serviceGroup"
MODEL_SQUARE_URL = "https://ctxirang.ctyun.cn/maas/inlineService"
DOC_URL = "https://www.ctyun.cn/document/11061839/11062312"

# 分场景温度（方案 4.3）
TEMPERATURE_MAP = {
    "tutor": 0.7,
    "extract_memory": 0.1,
    "mine_pattern": 0.2,
    "diagnose": 0.2,
    "generate_quiz": 0.8,
    "report": 0.6,
}

# 模式挖掘样本门槛（方案约定 ⑤）
MIN_SAMPLES_QUESTION = 30
MIN_SAMPLES_MISTAKE = 10

# 对话不可删除（方案约定 ②）
CONVERSATION_DELETABLE = False


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_settings(patch: dict) -> dict:
    data = _load_settings()
    data.update({k: v for k, v in patch.items() if v is not None})
    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


class Settings:
    """运行时可变的配置（通过 /api/system/config 写入）。"""

    def __init__(self) -> None:
        self._cache = _load_settings()

    def reload(self) -> None:
        self._cache = _load_settings()

    def _get(self, env_key: str, json_key: str, default: str = "") -> str:
        v = os.getenv(env_key)
        if v:
            return v
        return str(self._cache.get(json_key) or default)

    @property
    def app_key(self) -> str:
        return self._get("TELEAI_APP_KEY", "app_key")

    @property
    def base_url(self) -> str:
        return self._get("TELEAI_BASE_URL", "base_url", DEFAULT_BASE_URL).rstrip("/")

    @property
    def model(self) -> str:
        return self._get("TELEAI_MODEL", "model")

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.model)

    @property
    def jwt_secret(self) -> str:
        if not SECRET_FILE.exists():
            SECRET_FILE.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        return SECRET_FILE.read_text(encoding="utf-8").strip()


settings = Settings()
