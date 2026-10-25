"""对话图片附件：只落本机、按用户隔离、按需转 data URL 喂给多模态模型。

设计要点
- 图片是**用户上传的题目截图/手写照片**，属于隐私内容：只存本机 `data/uploads/chat/`，
  不上传到任何第三方（除了"发给模型本身"这一必要动作），不进 Git。
- 文件名带用户前缀 `u{user_id}_`，读取时严格校验前缀 + 白名单字符，
  **不靠路径判断**（`../` 之类的穿越在文件名层面就被拒绝）。
- 类型校验看**魔数**而不是扩展名：把 `a.txt` 改名成 `a.png` 上传要挡掉。
- 单张 8MB 上限：base64 后约 10.7MB，再大请求体容易超时，手机原图建议先裁。
"""
from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from ..config import UPLOAD_DIR

CHAT_DIR = UPLOAD_DIR / "chat"
CHAT_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_BYTES = 8 * 1024 * 1024   # 单张 8MB
MAX_IMAGES_PER_MSG = 4              # 一条消息最多 4 张

# 扩展名 -> MIME
MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)

_NAME_RE = re.compile(r"^u(\d+)_[0-9a-f]{12}\.(png|jpg|jpeg|webp|gif)$")


def _sniff_ext(data: bytes) -> str:
    """按文件头判断真实图片类型；判断不出来返回空串。"""
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""


def save_image(user_id: int, filename: str, data: bytes) -> dict:
    """保存图片。返回 {ok, id, url, name, size, message}。id 即文件名。"""
    if not data:
        return {"ok": False, "message": "图片为空"}
    if len(data) > MAX_IMAGE_BYTES:
        return {
            "ok": False,
            "message": f"图片 {len(data) / 1024 / 1024:.1f}MB，超过单张 8MB 上限，"
                       "请先裁剪或压缩（手机截图原图通常很大）",
        }
    ext = _sniff_ext(data)
    if not ext:
        return {
            "ok": False,
            "message": "不是有效的图片（只支持 PNG / JPG / WEBP / GIF），"
                       "把别的文件改后缀是没用的",
        }
    stored = f"u{user_id}_{uuid.uuid4().hex[:12]}{ext}"
    (CHAT_DIR / stored).write_bytes(data)
    return {
        "ok": True,
        "id": stored,
        "name": (filename or stored)[:120],
        "size": len(data),
        "url": f"/api/chat/attachments/{stored}",
    }


def resolve(user_id: int, name: str) -> Path | None:
    """把附件 id 解析成磁盘路径。只能拿到自己的图。"""
    m = _NAME_RE.match(name or "")
    if not m or int(m.group(1)) != int(user_id):
        return None
    p = CHAT_DIR / name
    return p if p.is_file() else None


def data_url(user_id: int, name: str) -> str | None:
    """转成 data URL，供 OpenAI 兼容协议里的 image_url 使用。"""
    p = resolve(user_id, name)
    if not p:
        return None
    mime = MIME.get(p.suffix.lower(), "image/png")
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def public(user_id: int, name: str) -> dict | None:
    """给前端展示用的元信息（不含图片内容）。"""
    p = resolve(user_id, name)
    if not p:
        return None
    return {
        "id": name,
        "url": f"/api/chat/attachments/{name}",
        "size": p.stat().st_size,
    }
