"""系统配置接口：供应商切换 / API Key 安全存取 / 连通性自检。

保密设计的四条硬约束（改代码时别破）：
  1. **Key 只进不出** —— 任何响应只返回掩码，绝不回传明文
  2. **Key 加密落盘** —— 走 SecretsStore（Windows DPAPI），不是明文 JSON
  3. **Key 不进前端存储** —— 前端不写 localStorage，输入框提交后立即清空
  4. **Key 不进日志/报错** —— 所有异常信息过 scrub() 抹掉 Key
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PROVIDERS, settings, save_settings
from ..db import get_db
from ..deps import current_user
from ..models import Memory, User
from ..services.llm import get_provider
from ..services.secrets_store import scrub

router = APIRouter(prefix="/api/system", tags=["system"])


class ConfigIn(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    # 只在提交的这一刻存在，写入后立刻丢弃
    api_key: str | None = None


class ClearKeyIn(BaseModel):
    provider: str | None = None


def _payload() -> dict:
    return {
        "provider": settings.provider,
        "providers": settings.providers_public(),
        "configured": settings.configured,
        "mode": "live" if settings.configured else "mock",
        "demo_model": "deepseek-flash",
        "secure_storage": settings.key_protected,
        "secure_note": (
            "API Key 已用 Windows DPAPI 加密，绑定当前 Windows 用户与本机；"
            "拷到别的机器或别的用户下解不开。"
            if settings.key_protected
            else "⚠️ 当前系统不支持 DPAPI，Key 以明文存储。建议设置文件目录权限。"
        ),
    }


@router.get("/config")
def read_config(user: User = Depends(current_user)):
    return _payload()


@router.post("/config")
def write_config(body: ConfigIn, user: User = Depends(current_user)):
    if body.provider and body.provider not in PROVIDERS:
        return {"ok": False, "message": f"未知供应商：{body.provider}"}

    target = body.provider or settings.provider

    # 1) 非敏感配置（显式传空串表示清空，回落到该供应商默认值）
    patch: dict = {"provider": body.provider, "providers": {}}
    slot = {}
    if body.base_url is not None:
        slot["base_url"] = body.base_url.strip()
    if body.model is not None:
        slot["model"] = body.model.strip()
    if slot:
        patch["providers"][target] = slot
    save_settings(patch)
    settings.reload()

    # 2) 敏感配置：写加密存储后立刻从内存变量丢弃
    if body.api_key is not None:
        key = body.api_key.strip()
        if key:
            settings.secrets.set(target, key)
        else:
            settings.secrets.clear(target)

    return _payload()


@router.post("/key/clear")
def clear_key(body: ClearKeyIn, user: User = Depends(current_user)):
    """删除已保存的 Key（比如换了账号、或者怀疑泄露）。"""
    target = body.provider or settings.provider
    if target not in PROVIDERS:
        return {"ok": False, "message": "未知供应商"}
    settings.secrets.clear(target)
    return {"ok": True, **_payload()}


def _build_provider(name: str):
    """按指定供应商构造实例（用于探测 / 测试，不影响当前选择）。"""
    from ..services.llm.openai_compat import DeepSeekProvider, MockProvider, TeleAIProvider

    key = settings.key_of(name)
    model = settings._slot(name).get("model") or PROVIDERS[name]["default_model"]
    if not key or not model:
        return MockProvider()
    base = settings._slot(name).get("base_url") or PROVIDERS[name]["base_url"]
    cls = DeepSeekProvider if name == "deepseek" else TeleAIProvider
    return cls(api_key=key, base_url=base, model=model)


@router.get("/models")
async def probe_models(provider: str | None = None, user: User = Depends(current_user)):
    """拉取可用模型列表。

    探测失败不代表配置错了 —— 有些网关不开放 /models。
    """
    name = provider or settings.provider
    if name not in PROVIDERS:
        return {"ok": False, "message": "未知供应商", "models": []}
    if not settings.key_of(name):
        return {"ok": False, "message": "还没填 API Key", "models": []}

    p = _build_provider(name)
    try:
        models = await p.list_models()
        if not models:
            return {"ok": False, "models": [],
                    "message": "接口通了但没有返回模型列表，请手动填写模型名。",
                    "fallback": True}
        return {"ok": True, "count": len(models), "models": models,
                "current": p.model}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "models": [],
            "message": scrub(str(exc), settings.key_of(name)),
            "fallback": True,
            "hint": "该网关不提供 /models。请到官方文档或控制台确认模型名后手动填入"
                    "（DeepSeek 可用：deepseek-flash / deepseek-v4-pro）。",
        }


@router.get("/health")
async def health(provider: str | None = None, user: User = Depends(current_user)):
    name = provider or settings.provider
    if name not in PROVIDERS:
        return {"ok": False, "message": "未知供应商"}
    p = _build_provider(name)
    info = await p.health()
    return {
        "provider": name,
        "provider_name": p.name,
        "configured": bool(settings.key_of(name)),
        "secure_storage": settings.key_protected,
        **info,
    }


@router.post("/test-chat")
async def test_chat(provider: str | None = None, user: User = Depends(current_user)):
    """最小连通性验证。一次真实调用，能验出 Key、base_url、model 三者是否都对。"""
    name = provider or settings.provider
    if name not in PROVIDERS:
        return {"ok": False, "message": "未知供应商"}
    p = _build_provider(name)
    try:
        text = await p.chat(
            [{"role": "user", "content": "只回复两个字：联通"}],
            temperature=0.1, max_tokens=64, scene="diagnose",
        )
        return {"ok": True, "provider": p.name, "model": getattr(p, "model", ""),
                "reply": text[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "provider": p.name,
                "message": scrub(str(exc), settings.key_of(name))}


@router.get("/memories")
def memories(subject: str | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    q = select(Memory).where(Memory.user_id == user.id)
    if subject:
        q = q.where(Memory.subject_key == subject)
    rows = db.scalars(q.order_by(Memory.weight.desc(), Memory.id.desc()).limit(100)).all()
    return [
        {
            "id": m.id,
            "type": m.mtype,
            "content": m.content,
            "subject": m.subject_key,
            "weight": round(m.weight, 3),
            "hits": m.hits,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]
