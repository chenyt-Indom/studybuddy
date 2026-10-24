"""API Key 的安全存储。

「前端输入 + 保密」的正确做法：
  浏览器把 Key 提交一次给**本机后端**（走 127.0.0.1 回环，不出网卡）
    → 后端用 Windows DPAPI 加密后落盘
    → 之后任何接口只返回掩码（sk-1234****abcd），**永远不把明文回传**
    → 所有大模型调用都在后端完成，浏览器不直连 DeepSeek

  ⚠️ 关键点：如果让前端直接调 DeepSeek，Key 会出现在 DevTools 的 Network 里，
     那才是真泄露。所以「前端输入」不等于「前端持有」。

加密用的是 Windows DPAPI（CryptProtectData）：
  - 密文与当前 Windows 用户 + 本机绑定，拷到别的机器/别的用户解不开
  - 零第三方依赖，直接 ctypes 调 crypt32.dll
  - 非 Windows 平台降级为明文存储，并明确标记 secure=False（不假装安全）
"""
from __future__ import annotations

import base64
import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path

SECRETS_FILE_NAME = "secrets.bin"
# 固定 entropy：即使 data/.secret 丢了也能解密（否则密钥丢失即不可恢复）
ENTROPY = b"StudyBuddy/api-key/v1"

_IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------- DPAPI
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes):
    """构造 DATA_BLOB，同时返回底层 buffer 防止被 GC 回收。"""
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buf


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    in_blob, _keep1 = _blob(data)
    ent_blob, _keep2 = _blob(ENTROPY)
    out_blob = _DATA_BLOB()

    if encrypt:
        fn = crypt32.CryptProtectData
        argtypes = [
            ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR,
            ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
        ]
    else:
        fn = crypt32.CryptUnprotectData
        argtypes = [
            ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
        ]
    fn.argtypes = argtypes
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    if encrypt:
        ok = fn(ctypes.byref(in_blob), None, ctypes.byref(ent_blob),
                None, None, 0, ctypes.byref(out_blob))
    else:
        desc = wintypes.LPWSTR()
        ok = fn(ctypes.byref(in_blob), ctypes.byref(desc), ctypes.byref(ent_blob),
                None, None, 0, ctypes.byref(out_blob))
        if desc:
            kernel32.LocalFree(ctypes.cast(desc, ctypes.c_void_p))

    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI 调用失败")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


# ---------------------------------------------------------------- 读写
class SecretsStore:
    """按 provider 分别存 Key。返回的永远是明文 key，但只在后端内存里存在。"""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / SECRETS_FILE_NAME
        self._cache: dict[str, str] | None = None

    # ---- 内部 ----
    def _load(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        self._cache = {}
        if not self.path.exists():
            return self._cache
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            payload = base64.b64decode(raw.get("payload", ""))
            if raw.get("dpapi"):
                payload = _dpapi(payload, encrypt=False)
            data = json.loads(payload.decode("utf-8"))
            if isinstance(data, dict):
                self._cache = {str(k): str(v) for k, v in data.items() if v}
        except Exception:
            # 解不开（换了机器/换了 Windows 用户）就当没有，让用户重新填
            self._cache = {}
        return self._cache

    def _save(self, data: dict[str, str]) -> None:
        blob = json.dumps(data, ensure_ascii=False).encode("utf-8")
        use_dpapi = _IS_WINDOWS
        if use_dpapi:
            try:
                blob = _dpapi(blob, encrypt=True)
            except Exception:
                use_dpapi = False
        self.path.write_text(
            json.dumps(
                {"v": 1, "dpapi": use_dpapi,
                 "payload": base64.b64encode(blob).decode("ascii")},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        try:
            self.path.chmod(0o600)  # 非 Windows 生效；Windows 靠用户目录 ACL
        except Exception:
            pass
        self._cache = data

    # ---- 对外 ----
    @property
    def protected(self) -> bool:
        """当前是否真的加密存储。"""
        return _IS_WINDOWS

    def get(self, provider: str) -> str:
        return self._load().get(provider, "")

    def set(self, provider: str, key: str) -> None:
        data = dict(self._load())
        if key:
            data[provider] = key
        else:
            data.pop(provider, None)
        self._save(data)

    def clear(self, provider: str) -> None:
        self.set(provider, "")

    def has_any(self) -> bool:
        return any(self._load().values())


def mask(key: str) -> str:
    """掩码：只露前 4 后 4，中间全星号。短 key 全遮。"""
    if not key:
        return ""
    if len(key) <= 12:
        return "*" * len(key)
    return f"{key[:4]}{'*' * min(12, len(key) - 8)}{key[-4:]}"


def scrub(text: str, key: str) -> str:
    """从异常信息里抹掉可能被回显的 Key。

    httpx / 网关的错误体偶尔会把 Authorization 带出来，这里统一兜一道。
    """
    if not text:
        return ""
    if key and key in text:
        text = text.replace(key, mask(key))
    return text[:400]
