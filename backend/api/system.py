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

    # 1) 非敏感配置
    patch: dict = {"provider": body.provider, "providers": {}}
    slot = {}
    if body.base_url is not None and body.base_url.strip():
        slot["base_url"] = body.base_url.strip()
    if body.model is not None and body.model.strip():
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


@router.get("/models")
async def probe_models(provider: str | None = None, user: User = Depends(current_user)):
    """拉取可用模型列表。

    DeepSeek 的 `/models` 是可用接口；星辰文档里没列，可能 404 —— 失败不代表配置错了。
    """
    name = provider or settings.provider
    if name not in PROVIDERS:
        return {"ok": False, "message": "未知供应商", "models": []}
    if not settings.key_of(name):
        return {"ok": False, "message": "还没填 API Key", "models": []}

    p = get_provider(name) if name == settings.provider else _probe_instance(name)
    if p is None:
        return {"ok": False, "message": "该供应商还没配置模型名", "models": []}
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


def _probe_instance(name: str):
    """为「非当前供应商」临时构造一个实例来探测。"""
    from ..services.llm.openai_compat import DeepSeekProvider, TeleAIProvider

    model = settings._slot(name).get("model") or PROVIDERS[name]["default_model"]
    if not model:
        return None
    base = settings._slot(name).get("base_url") or PROVIDERS[name]["base_url"]
    cls = DeepSeekProvider if name == "deepseek" else TeleAIProvider
    return cls(api_key=settings.key_of(name), base_url=base, model=model)


@router.get("/health")
async def health(user: User = Depends(current_user)):
    p = get_provider()
    info = await p.health()
    return {
        "provider": settings.provider,
        "provider_name": p.name,
        "configured": settings.configured,
        "secure_storage": settings.key_protected,
        **info,
    }


@router.post("/test-chat")
async def test_chat(user: User = Depends(current_user)):
    """最小连通性验证。一次真实调用，能验出 Key、base_url、model 三者是否都对。"""
    p = get_provider()
    try:
        text = await p.chat(
            [{"role": "user", "content": "只回复两个字：联通"}],
            temperature=0.1, max_tokens=64, scene="diagnose",
        )
        return {"ok": True, "provider": p.name, "model": p.model, "reply": text[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "provider": p.name,
                "message": scrub(str(exc), settings.api_key)}


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
