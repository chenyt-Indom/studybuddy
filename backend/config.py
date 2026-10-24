"""全局配置：密钥不硬编码（方案约定 ①）。

分层：
  环境变量  >  data/secrets.bin（DPAPI 加密的 API Key）  >  data/settings.json（非敏感配置）

API Key 与普通配置分开存：Key 走 SecretsStore 加密，其余走 settings.json。
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from .services.secrets_store import SecretsStore

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "app.db"
DB_URL = f"sqlite:///{DB_PATH.as_posix()}"

SETTINGS_FILE = DATA_DIR / "settings.json"
SECRET_FILE = DATA_DIR / ".secret"

# ---------------------------------------------------------------- 供应商
# 都走 OpenAI 兼容协议，适配器同一套代码。
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "label": "DeepSeek（推荐 · 国内直连）",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "default_model": "deepseek-v4-flash",
        "env_key": "DEEPSEEK_API_KEY",
        "env_model": "DEEPSEEK_MODEL",
        "presets": [
            {"label": "官方 · OpenAI 格式", "value": "https://api.deepseek.com/v1"},
            {"label": "官方 · 无 /v1 前缀", "value": "https://api.deepseek.com"},
            {"label": "Anthropic 格式（本项目不用）", "value": "https://api.deepseek.com/anthropic"},
        ],
        "console": "https://platform.deepseek.com/api_keys",
        "doc": "https://api-docs.deepseek.com/zh-cn/",
        # 深度思考模式参数，仅 DeepSeek 支持
        "thinking_param": True,
    },
    "teleai": {
        "label": "中国电信星辰大模型",
        "base_url": "https://ai.ctaigw.cn/v1",
        "models": [],
        "default_model": "",
        "env_key": "TELEAI_APP_KEY",
        "env_model": "TELEAI_MODEL",
        "presets": [
            {"label": "大陆 · 普通推理", "value": "https://ai.ctaigw.cn/v1"},
            {"label": "大陆 · 编程 Token Plan", "value": "https://ai.ctaigw.cn/coding/v1"},
            {"label": "全球 · 美洲", "value": "https://ai.ctaigw.com/amer/v1"},
            {"label": "全球 · 欧洲", "value": "https://ai.ctaigw.com/eu/v1"},
            {"label": "全球 · 亚洲", "value": "https://ai.ctaigw.com/as/v1"},
        ],
        "console": "https://ctxirang.ctyun.cn/maas/home",
        "doc": "https://www.ctyun.cn/document/11061839/11062312",
        "thinking_param": False,
    },
}

DEFAULT_PROVIDER = "deepseek"

# 星空/星辰时代遗留常量，保留兼容
DEFAULT_BASE_URL = PROVIDERS["teleai"]["base_url"]
BASE_URL_PRESETS = PROVIDERS["teleai"]["presets"]
CONSOLE_URL = PROVIDERS["teleai"]["console"]
APPKEY_URL = "https://ctxirang.ctyun.cn/maas/service/serviceGroup"
MODEL_SQUARE_URL = "https://ctxirang.ctyun.cn/maas/inlineService"
DOC_URL = PROVIDERS["teleai"]["doc"]

# ---------------------------------------------------------------- 其他
# 分场景温度（方案 4.3）
TEMPERATURE_MAP = {
    "tutor": 0.7,
    "extract_memory": 0.1,
    "mine_pattern": 0.2,
    "diagnose": 0.2,
    "generate_quiz": 0.8,
    "report": 0.6,
}

# 分场景输出上限（tokens）。
# DeepSeek-V4.1-Flash 最大输出 384K，但给太高模型容易啰嗦，按场景给够就行。
# tutor 之前是 2048，长讲解必被截断 —— 这就是用户反馈"只输出一半"的原因。
MAX_TOKENS_MAP = {
    "tutor": 16384,
    "generate_quiz": 6144,
    "report": 4096,
    "extract_memory": 2048,
    "mine_pattern": 1536,
    "diagnose": 2048,
}

# ----------------  Web 搜索（DeepSeek 官方 Search 接口）----------------
# POST {base}/tools/search  —— 独立接口，按次计费：5 元 / 1000 次
# 只有 HTTP 200 且 results 非空才计费，失败/无结果不计费
WEB_SEARCH_COUNT = 6          # 返回条数（不影响单价）
WEB_SEARCH_NEED_CONTENT = False  # 用 summary（600~800字）足够，不拉正文更省
WEB_SEARCH_MAX_CONTEXT = 7000    # 注入 prompt 的最大字符数，防爆上下文
WEB_SEARCH_TIMEOUT = 25

# 时间感知用的时区
APP_TIMEZONE = "Asia/Shanghai"

# 需要「关掉思考模式」的场景。
# 原因：DeepSeek 思考模式下 temperature 不生效，而这些场景必须靠温度控制风格：
#   抽记忆/挖模式/诊断 → 要确定性（低温度，不能瞎编）
#   出题/周报        → 要多样性（高温度，避免每次出一样的题）
# 只有 tutor（讲解）保留思考模式，质量优先，接受 latency。
THINKING_OFF_SCENES = {
    "extract_memory",
    "mine_pattern",
    "diagnose",
    "generate_quiz",
    "report",
}

# 模式挖掘样本门槛（方案约定 ⑤）
MIN_SAMPLES_QUESTION = 30
MIN_SAMPLES_MISTAKE = 10

# 对话不可删除（方案约定 ②）
CONVERSATION_DELETABLE = False


# ---------------------------------------------------------------- 读写
def _load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(patch: dict) -> dict:
    """保存非敏感配置。结构：{provider, providers:{name:{base_url,model}}}"""
    data = _load_settings()

    # 迁移旧结构（扁平 app_key/model/base_url 时代）
    if "app_key" in data or "model" in data or "base_url" in data:
        legacy = {
            "base_url": data.pop("base_url", None) or PROVIDERS["teleai"]["base_url"],
            "model": data.pop("model", None) or "",
        }
        data.pop("app_key", None)  # 旧明文 key 不再使用，用户需重新填
        data.setdefault("providers", {}).setdefault("teleai", legacy)
        data.setdefault("provider", "teleai")

    providers = data.setdefault("providers", {})
    for name, cfg in (patch.get("providers") or {}).items():
        if name in PROVIDERS and isinstance(cfg, dict):
            slot = providers.setdefault(name, {})
            for k in ("base_url", "model"):
                if cfg.get(k) is not None:
                    slot[k] = cfg[k]
    if patch.get("provider") in PROVIDERS:
        data["provider"] = patch["provider"]
    if patch.get("search_enabled") is not None:
        data["search_enabled"] = bool(patch["search_enabled"])

    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


class Settings:
    """运行时配置。API Key 一律从 SecretsStore（加密）或环境变量取。"""

    def __init__(self) -> None:
        self._cache = _load_settings()
        self.secrets = SecretsStore(DATA_DIR)

    def reload(self) -> None:
        self._cache = _load_settings()

    # ---- 供应商 ----
    @property
    def provider(self) -> str:
        p = self._cache.get("provider") or DEFAULT_PROVIDER
        return p if p in PROVIDERS else DEFAULT_PROVIDER

    def set_provider(self, name: str) -> None:
        self._cache["provider"] = name
        SETTINGS_FILE.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @property
    def meta(self) -> dict:
        return PROVIDERS[self.provider]

    def _slot(self, name: str | None = None) -> dict:
        name = name or self.provider
        return (self._cache.get("providers") or {}).get(name) or {}

    # ---- Key（不落明文、不回传）----
    def key_of(self, name: str | None = None) -> str:
        name = name or self.provider
        env = os.getenv(PROVIDERS[name]["env_key"], "")
        if env:
            return env.strip()
        return self.secrets.get(name)

    @property
    def app_key(self) -> str:
        return self.key_of()

    # ---- 其余配置 ----
    @property
    def base_url(self) -> str:
        env = os.getenv("LLM_BASE_URL", "")
        if env:
            return env.rstrip("/")
        slot = self._slot()
        return (slot.get("base_url") or self.meta["base_url"]).rstrip("/")

    @property
    def model(self) -> str:
        env = os.getenv(self.meta["env_model"], "")
        if env:
            return env.strip()
        slot = self._slot()
        return slot.get("model") or self.meta["default_model"]

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.model)

    @property
    def key_protected(self) -> bool:
        """Key 是否加密存储（非 Windows 会降级为明文，前端要如实提示）。"""
        return self.secrets.protected

    # ---- 联网搜索 ----
    @property
    def search_enabled(self) -> bool:
        """是否允许联网搜索。默认开启（仅 DeepSeek 支持）。"""
        v = self._cache.get("search_enabled")
        return True if v is None else bool(v)

    def set_search_enabled(self, on: bool) -> None:
        self._cache["search_enabled"] = bool(on)
        SETTINGS_FILE.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @property
    def search_supported(self) -> bool:
        """只有 DeepSeek 有 /tools/search 这个接口。"""
        return self.provider == "deepseek"

    # ---- 列表（给前端，永不含 Key）----
    def providers_public(self) -> list[dict]:
        out = []
        for name, meta in PROVIDERS.items():
            slot = self._slot(name)
            key = self.key_of(name)
            out.append(
                {
                    "name": name,
                    "label": meta["label"],
                    "base_url": slot.get("base_url") or meta["base_url"],
                    "model": slot.get("model") or meta["default_model"],
                    "models": meta["models"],
                    "presets": meta["presets"],
                    "console": meta["console"],
                    "doc": meta["doc"],
                    "has_key": bool(key),
                    "key_masked": _mask_public(key),
                    "from_env": bool(os.getenv(meta["env_key"], "")),
                    "configured": bool(key and (slot.get("model") or meta["default_model"])),
                }
            )
        return out

    @property
    def jwt_secret(self) -> str:
        if not SECRET_FILE.exists():
            SECRET_FILE.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        return SECRET_FILE.read_text(encoding="utf-8").strip()


def _mask_public(key: str) -> str:
    from .services.secrets_store import mask

    return mask(key)


def now_context() -> dict:
    """当前时间上下文（时间感知）。每次都现算，不用缓存 —— 服务可能跑好几天。

    时区处理：Windows 上 zoneinfo 需要额外装 tzdata，装不上会直接抛
    ZoneInfoNotFoundError 把整个请求打挂。而中国自 1991 年起不实行夏令时，
    固定 UTC+8 与 Asia/Shanghai 完全等价，所以这里做降级而不是加依赖。
    """
    from datetime import datetime, timedelta, timezone as _tz

    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(APP_TIMEZONE)
    except Exception:
        tz = _tz(timedelta(hours=8), name="UTC+8")

    now = datetime.now(tz)
    wd = "一二三四五六日"[now.weekday()]
    return {
        "iso": now.isoformat(timespec="minutes"),
        "date": f"{now.year}年{now.month}月{now.day}日",
        "weekday": f"星期{wd}",
        "time": now.strftime("%H:%M"),
        "year": now.year,
        "month": now.month,
        "display": f"{now.year}年{now.month}月{now.day}日 星期{wd} {now.strftime('%H:%M')}",
    }


settings = Settings()
