"""外部教材知识库（IMA）链路的离线测试。

用一个**假 MCP 服务**跑通全链路：
  客户端 initialize → tools/list → tools/call（JSON 与 SSE 两种响应都要能解析）
  → 适配层挑「检索类工具」→ 归一化片段 → 落库 kb_snippets → 本地检索 → prompt 注入

不需要真 IMA Token。跑法：
  python tests/ima_test.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORT = 9631
os.environ["STUDYBUDDY_IMA_URL"] = f"http://127.0.0.1:{PORT}/mcp"

pass_n = 0
fails: list[str] = []


def check(name, cond, extra=""):
    global pass_n
    if cond:
        pass_n += 1
        print(f"  [PASS] {name} {extra}")
    else:
        fails.append(name)
        print(f"  [FAIL] {name} {extra}")


# ---------------------------------------------------------------- 假 MCP 服务
TOOLS = [
    {
        "name": "ima_create_note",
        "description": "在 IMA 里新建笔记（写操作，不该被选中）",
        "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}},
    },
    {
        "name": "ima_search_knowledge",
        "description": "在 IMA 知识库中检索教材与资料",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
]

HIT = {
    "results": [
        {
            "title": "人教版 高中物理 必修第二册 · 第五章 抛体运动",
            "snippet": "平抛运动可分解为水平方向的匀速直线运动和竖直方向的自由落体运动，"
                       "两个方向的时间相同，落地时间只由高度决定：t=√(2h/g)。",
            "url": "https://ima.qq.com/kb/doc/abc123",
            "source_name": "高中数学物理教材库",
        }
    ]
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):   # 静音
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Mcp-Session-Id", "fake-session-1")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        method = req.get("method")
        rid = req.get("id")

        # 鉴权：没 token 就按真实的 IMA 那样返回 401
        if not (self.headers.get("Authorization") or "").startswith("Bearer "):
            self._send(401, json.dumps({"jsonrpc": "2.0", "error": {
                "code": -32001,
                "message": "type:business, code:110042, msg:empty access token"}, "id": None}))
            return

        if method == "initialize":
            self._send(200, json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "fake-ima", "version": "0.1"},
                "capabilities": {"tools": {}},
            }}))
            return
        if method == "notifications/initialized":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "tools/list":
            self._send(200, json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}))
            return
        if method == "tools/call":
            name = (req.get("params") or {}).get("name")
            args = (req.get("params") or {}).get("arguments") or {}
            payload = {
                "jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text",
                                        "text": json.dumps(HIT, ensure_ascii=False)}]},
            }
            if name != "ima_search_knowledge":
                payload["result"] = {"content": [{"type": "text", "text": "wrong tool"}],
                                     "isError": True}
            # 故意用 SSE 返回，逼客户端走 SSE 解析分支
            body = f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            self._send(200, body, ctype="text/event-stream")
            return

        self._send(400, json.dumps({"jsonrpc": "2.0", "error": {"code": -32601,
                                                                "message": f"no method {method}"}, "id": rid}))


def start_server():
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------- 测试主体
import asyncio  # noqa: E402

from backend.config import settings                    # noqa: E402
from backend.db import SessionLocal, init_db           # noqa: E402
from backend.services import ext_kb                    # noqa: E402
from backend.services.kp import hints_for              # noqa: E402
from backend.services.tutor import build_tutor_prompt  # noqa: E402

print("=" * 64)
print("IMA 教材知识库链路测试（假 MCP 服务）")

init_db()
srv = start_server()
print(f"假 MCP 服务： {ext_kb.IMA_URL}")

# 0) 没 token 时：明确报"未授权"，不崩
settings.set_ima_token("")
r = asyncio.run(ext_kb.probe())
check("没配 token 时 probe 明确说明", r.get("ok") is False and "Token" in (r.get("reason") or ""),
      r.get("reason"))
r = asyncio.run(ext_kb.search("平抛运动"))
check("没配 token 时 search 优雅失败", r.get("ok") is False and not r.get("items"),
      r.get("reason"))

# 1) 配上假 token
settings.set_ima_token("fake-token-abc123")
r = asyncio.run(ext_kb.probe())
check("能连上并列出工具", r.get("ok") is True, f"server={r.get('server')} tools={len(r.get('tools') or [])}")
check("自动挑中「检索类」工具（跳过写操作）", r.get("picked") == "ima_search_knowledge",
      str(r.get("picked")))
names = [t["name"] for t in r.get("tools") or []]
check("工具清单包含写操作但不选它", "ima_create_note" in names)
check("参数按 schema 生成", ext_kb.build_args(TOOLS[1], "平抛运动", 4) ==
      {"query": "平抛运动", "top_k": 4},
      str(ext_kb.build_args(TOOLS[1], "平抛运动", 4)))

# 2) 检索 + SSE 解析 + 归一化
res = asyncio.run(ext_kb.search("平抛运动怎么算落地时间"))
check("SSE 响应能解析", res.get("ok") is True, res.get("reason"))
items = res.get("items") or []
check("拿到片段", len(items) == 1, f"{len(items)} 条")
if items:
    it = items[0]
    check("标题/片段/出处都归一化", bool(it["title"]) and bool(it["snippet"]) and bool(it["url"]),
          it["title"][:26])
    check("片段里有关键结论", "t=√(2h/g)" in it["snippet"])

# 3) 落库 + 本地检索（幂等）
db = SessionLocal()
user_id = 1
before = len(ext_kb.local_search(db, user_id, "平抛运动", subject="physics"))
added = ext_kb.save_snippets(db, user_id, items, stage="senior", grade="senior_1",
                             subject="physics", query="平抛运动 教材")
db.commit()
check("片段落库", added >= 1, f"新增 {added} 条")
added2 = ext_kb.save_snippets(db, user_id, items, stage="senior", grade="senior_1",
                              subject="physics", query="平抛运动 教材")
db.commit()
check("重复同步不重复存", added2 == 0, f"第二次新增 {added2} 条")
hits = ext_kb.local_search(db, user_id, "平抛运动 落地时间", subject="physics")
check("本地检索能命中", len(hits) >= 1, (hits[0]["title"][:24] if hits else "无"))

# 4) 讲解 prompt 注入
ctx = {"stage": "senior", "grade": "senior_1", "grade_cn": "高一",
       "kp_hints": hints_for(db, ["physics.projectile"]),
       "ext_textbook": {"items": hits[:2], "origin": "local"}}
prompt = build_tutor_prompt(ctx, "physics")
check("prompt 有【教材摘录】段", "【教材摘录】" in prompt)
check("prompt 要求不照抄原文", "不要整段照抄" in prompt)
check("摘录内容真的进去了", "抛体运动" in prompt.split("【教材摘录】")[1][:400])

# 5) 清理：删掉测试片段与 token
from sqlalchemy import delete  # noqa: E402
from backend.models import KbSnippet  # noqa: E402
db.execute(delete(KbSnippet).where(KbSnippet.user_id == user_id))
db.commit()
db.close()
settings.set_ima_token("")
srv.shutdown()

print("=" * 64)
print(f"通过 {pass_n} 项，失败 {len(fails)} 项")
if fails:
    print("失败项:", fails)
    sys.exit(1)
print("全部通过")
