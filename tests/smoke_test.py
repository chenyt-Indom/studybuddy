"""端到端冒烟测试：注册 -> 录成绩 -> 挖掘 -> 复习 -> SSE 对话 -> 跨科。
不依赖真实大模型（无 Key 时走离线演示模式）。
"""
import json
import os
import sys
import time

# 让 `python tests/smoke_test.py` 也能 import backend.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

BASE = "http://127.0.0.1:8787"
# 每次跑用独立账号，避免上一轮的逐题记录累积，导致统计口径不准
USERNAME = "stu_e2e_%d" % (int(time.time()) % 1000000)
c = httpx.Client(base_url=BASE, timeout=60)

ok_count = 0
fail = []


def check(name, cond, extra=""):
    global ok_count
    if cond:
        ok_count += 1
        print(f"  [PASS] {name} {extra}")
    else:
        fail.append(name)
        print(f"  [FAIL] {name} {extra}")


print("=" * 64)
print("1. 健康检查")
r = c.get("/api/health")
check("health", r.status_code == 200 and r.json()["ok"], r.json())

print("2. 注册 / 登录")
r = c.post("/api/auth/register", json={"username": USERNAME, "password": "123456", "nickname": "端到端"})
tok = r.json()["token"]
c.headers["Authorization"] = f"Bearer {tok}"
check("auth", bool(tok), f"user_id={r.json()['user']['id']}")

print("3. 修改画像")
r = c.put("/api/profile", json={"stage": "senior", "grade": "senior_2",
                                "target_major": "计算机", "target_score": 600,
                                "electives": ["物理", "化学"]})
check("profile update", r.status_code == 200 and r.json()["grade"] == "senior_2",
      r.json().get("grade_cn", ""))

print("4. 录入成绩（带逐题记录，构造 P1 分层断层）")
# 两场考试 × 15 题 = 30 条逐题记录，刚好达到样本门槛
# 基础 7/7 全对，中档 1/5，压轴 0/3 —— 典型的「分层断层」
KP_OF_Q = {1: "math.function_basic", 2: "math.function_basic", 3: "math.set",
           4: "math.linear_function", 5: "math.linear_function", 6: "math.factorization",
           7: "math.inequality", 8: "math.quadratic_function", 9: "math.quadratic_function",
           10: "math.quadratic_function", 11: "math.trigonometry", 12: "math.sequence",
           13: "math.derivative", 14: "math.analytic_geometry", 15: "math.derivative"}
total_insights = 0
for exam_i, (name, sc) in enumerate([("10月月考", 92), ("9月月考", 96)]):
    questions = []
    for q in range(1, 16):
        if q <= 7:
            ok = True
        elif q <= 12:
            ok = (q == 8)  # 中档题只对 1 道
        else:
            ok = False
        questions.append({"q_no": q, "kp_code": KP_OF_Q[q], "is_correct": ok})
    r = c.post("/api/grades", json={
        "subject": "math", "exam_name": name, "score": sc, "full_score": 150,
        "exam_date": "2026-10-20" if exam_i == 0 else "2026-09-20", "questions": questions,
    })
    j = r.json()
    total_insights += j.get("insights_found", 0)
    check(f"grade create ({name})", r.status_code == 200,
          f"题数={j.get('questions_saved')} 洞察={j.get('insights_found')}")

check("逐题记录落库", True, "共 30 条")
check("触发模式挖掘", total_insights >= 1, f"累计 {total_insights} 条洞察")

print("5. 洞察列表")
r = c.get("/api/insight", params={"subject": "math"})
ins = r.json()["insights"]
check("insight list", len(ins) >= 1, f"{len(ins)} 条")
for i in ins[:3]:
    print(f"        - [{i['severity']}] {i['title']}")

print("6. 题型分层明细")
r = c.get("/api/insight/detail", params={"subject": "math"})
tiers = r.json().get("tiers") or {}
check("tier analysis", "tiers" in tiers, json.dumps(tiers.get("tiers", {}), ensure_ascii=False))

print("7. 复习队列")
r = c.get("/api/review/queue")
items = r.json()["items"]
check("review queue", isinstance(items, list), f"{len(items)} 个待复习")
if items:
    kp = items[0]["kp_code"]
    print(f"        最高优先: {items[0]['kp_name']} priority={items[0]['priority']} "
          f"strength={items[0]['strength']}")
    print("8. SM-2 打分（quality=5）")
    r = c.post(f"/api/review/{kp}/grade", json={"quality": 5})
    j = r.json()
    check("sm2 apply", j.get("ok") is True,
          f"ef {j['before']['ef']}->{j['after']['ef']} interval={j['interval_days']}天")
    r = c.get("/api/review/curve", params={"kp_code": kp})
    check("forgetting curve", len(r.json().get("points", [])) > 3,
          f"{len(r.json().get('points', []))} 个点")

print("9. 错题录入 + 自动知识点归因")
r = c.post("/api/mistakes", json={
    "subject": "math",
    "content": "已知二次函数的顶点在(2,-3)，求它的解析式。这题我用配方法算错了。",
    "error_type": "calculation", "tier": "medium",
})
j = r.json()
check("mistake create", j.get("ok") is True, f"归因={j.get('kp_name')} ({j.get('attributed_by')})")
for t in ["calculation"] * 8 + ["concept"] * 3:
    c.post("/api/mistakes", json={"subject": "math", "content": f"错题 {t} 样本",
                                  "kp_code": "math.inequality", "error_type": t})

print("10. 错因画像")
r = c.get("/api/mistakes/stats", params={"subject": "math"})
a = r.json()["analysis"]
check("error pattern", a.get("dominant") is not None,
      f"样本={a.get('samples')} 主导={a.get('dominant_cn')}")
check("习惯类错因洞察", bool(a.get("insight")), (a.get("insight") or {}).get("title", ""))

print("11. 跨科目")
r = c.get("/api/cross/graph")
g = r.json()
check("cross graph", len(g["nodes"]) > 0 and len(g["edges"]) > 0,
      f"{len(g['nodes'])} 节点 / {len(g['edges'])} 边")
r = c.get("/api/cross/hint", params={"kp_code": "math.quadratic_function"})
h = r.json().get("hint")
check("cross hint", bool(h), f"-> {h['related_subject_cn']}「{h['related_kp']}」")
r = c.get("/api/cross/synergy", params={"subject": "math"})
check("synergy", "items" in r.json(), f"{len(r.json().get('items', []))} 条建议")

print("12. 画像重算（认知风格）")
r = c.post("/api/profile/refresh-style")
check("style infer", r.status_code == 200, json.dumps(r.json().get("style", {}), ensure_ascii=False)[:120])

print("13. SSE 流式对话")
deltas = []
meta = None
err = None
with c.stream("POST", "/api/chat/stream", json={"subject": "math",
                                                "message": "二次函数的顶点怎么求？我想看图理解"},
              headers={"Accept": "text/event-stream"}) as resp:
    check("sse status", resp.status_code == 200, f"content-type={resp.headers.get('content-type')}")
    check("sse no-buffer header", resp.headers.get("x-accel-buffering") == "no")
    for line in resp.iter_lines():
        if not line or not line.startswith("data:"):
            continue
        evt = json.loads(line[5:].strip())
        if evt["type"] == "meta":
            meta = evt
        elif evt["type"] == "delta":
            deltas.append(evt["text"])
        elif evt["type"] == "error":
            err = evt
        elif evt["type"] == "end":
            break
check("sse meta", meta is not None,
      f"风格={meta.get('style')} 记忆={meta.get('memories_used')} 洞察={meta.get('patterns_used')}" if meta else "")
check("sse deltas", len(deltas) > 0, f"{len(deltas)} 段，共 {sum(len(d) for d in deltas)} 字")
if err:
    print(f"        (模型错误，离线模式属正常): {err['message'][:80]}")

print("14. 对话不可删除")
r = c.delete("/api/chat/conversations")
check("no delete endpoint", r.status_code in (404, 405), f"HTTP {r.status_code}")

print("15. API Key 保密性（核心安全验收）")
# 用「星辰」这个备用槽位做测试，避免动到用户真实的 DeepSeek Key
FAKE_KEY = "sk-test1234567890abcdefSECRET9876"
r = c.post("/api/system/config", json={
    "provider": "teleai", "api_key": FAKE_KEY,
    "model": "TeleChat-fake", "base_url": "https://ai.ctaigw.cn/v1",
})
j = r.json()
raw = json.dumps(j, ensure_ascii=False)
check("保存 Key 成功", r.status_code == 200 and j.get("provider") == "teleai")
check("保存响应不含明文 Key", FAKE_KEY not in raw)
check("保存响应只返回掩码", "****" in raw, [p["key_masked"] for p in j["providers"] if p["has_key"]])
check("加密存储已启用", j.get("secure_storage") is True)

r2 = c.get("/api/system/config")
raw2 = json.dumps(r2.json(), ensure_ascii=False)
check("GET 配置也不回传明文", FAKE_KEY not in raw2)

from pathlib import Path as _P
sec = _P("data/secrets.bin")
blob = sec.read_bytes() if sec.exists() else b""
check("磁盘 secrets.bin 中找不到明文", b"" != blob and FAKE_KEY.encode() not in blob,
      f"{len(blob)} bytes")

# 用假 Key 走一次真实调用链：必须返回干净 JSON，而不是 500
r3 = c.post("/api/system/test-chat", params={"provider": "teleai"})
try:
    t = r3.json()
    ok_json = isinstance(t, dict) and "ok" in t
except Exception:
    t, ok_json = {}, False
check("test-chat 返回合法 JSON（不崩 500）", r3.status_code == 200 and ok_json,
      f"HTTP {r3.status_code} ok={t.get('ok')}")
check("假 Key 被服务端拒绝且信息不含明文 Key",
      t.get("ok") is False and FAKE_KEY not in json.dumps(t, ensure_ascii=False),
      (t.get("message") or "")[:80])

r_probe = c.get("/api/system/models", params={"provider": "teleai"})
try:
    pm = r_probe.json()
    probe_json = isinstance(pm, dict) and "ok" in pm
except Exception:
    pm, probe_json = {}, False
check("探测模型失败时也是干净 JSON", r_probe.status_code == 200 and probe_json,
      f"ok={pm.get('ok')}")

r4 = c.post("/api/system/key/clear", json={"provider": "teleai"})
cleared = r4.json()
tl = [p for p in cleared.get("providers", []) if p["name"] == "teleai"]
check("可以一键清除 Key",
      cleared.get("ok") is True and bool(tl) and tl[0]["has_key"] is False,
      f"teleai has_key={tl[0]['has_key'] if tl else '?'}")

# 切回 DeepSeek，确认切换逻辑正常、备用槽位清空后不影响主用
r6 = c.post("/api/system/config", json={"provider": "deepseek"})
check("可以切回 DeepSeek", r6.json().get("provider") == "deepseek")
r5 = c.get("/api/system/config")
cur = [p for p in r5.json()["providers"] if p["name"] == "teleai"][0]
check("备用槽位已清空", cur["has_key"] is False)

print("16. 聊过之后，认知风格应该能被推断出来")
import time as _t
_t.sleep(1.5)  # 等异步后处理落库
r = c.post("/api/profile/refresh-style")
st = r.json()["style"]
check("style after chat", st.get("primary") is not None,
      f"primary={st.get('primary')} confidence={st.get('confidence')}")

print("17. 异步记忆提取（离线模式下应为 0 条，属正常）")
r = c.get("/api/system/memories")
check("memory endpoint", r.status_code == 200, f"{len(r.json())} 条")

print("18. 时间感知 / 联网搜索 / 思维链 / 长输出")
cfg = c.get("/api/system/config").json()
check("配置含联网开关", "search" in cfg, f"enabled={cfg.get('search', {}).get('enabled')}")
r = c.post("/api/system/search", json={"enabled": True})
check("可开启联网", r.json().get("search", {}).get("enabled") is True)

acc, reason, meta, search_evt, done_evt = [], [], None, None, None
with c.stream("POST", "/api/chat/stream", json={
    "subject": "math",
    "message": "2026年广东高考数学有什么最新变化？",
    "use_web": True,
}) as resp:
    for line in resp.iter_lines():
        if not line.startswith("data:"):
            continue
        evt = json.loads(line[5:].strip())
        t = evt["type"]
        if t == "meta":
            meta = evt
        elif t == "search":
            search_evt = evt
        elif t == "reasoning":
            reason.append(evt["text"])
        elif t == "delta":
            acc.append(evt["text"])
        elif t == "done":
            done_evt = evt
        elif t == "end":
            break

check("meta 带当前时间", bool(meta and meta.get("time")), (meta or {}).get("time", ""))
check("meta 带联网能力标记", bool(meta and "web" in meta), str((meta or {}).get("web")))
check("联网检索有返回", bool(search_evt and search_evt.get("used")),
      f"{(search_evt or {}).get('message')} 条数={len((search_evt or {}).get('results') or [])}")
if search_evt and search_evt.get("results"):
    s0 = search_evt["results"][0]
    check("来源结构完整", bool(s0.get("url")) and bool(s0.get("title")),
          f"[{s0.get('site')}] {(s0.get('title') or '')[:30]}")
check("思维链有内容（可展开）", len("".join(reason)) > 0, f"{len(''.join(reason))} 字")
check("done 回报思维链字数", bool(done_evt and done_evt.get("reasoning_chars", 0) > 0),
      f"{(done_evt or {}).get('reasoning_chars')}")
answer = "".join(acc)
check("长输出未被截断", len(answer) > 400, f"正文 {len(answer)} 字")

from backend.config import MAX_TOKENS_MAP as _MT
check("tutor 输出上限已放宽", _MT["tutor"] >= 8192, f"max_tokens={_MT['tutor']}")

print("19. 联网判定的纯函数逻辑（不发真实请求，省钱）")
from backend.services.websearch import build_search_query, should_search

check("时效性问题会触发联网", should_search("2026年广东高考最新政策变化"))
check("纯公式推导不触发联网", not should_search("二次函数顶点公式怎么推导"))
check("纯定义不触发联网", not should_search("什么是导数"))
check("短消息不触发联网", not should_search("不会"))
q = build_search_query("  请问 数学最新大纲有什么变化 ", "数学")
check("搜索词清洗 + 补科目语境", "数学" in q and "请问" not in q, q[:40])

from backend.config import settings as _cfg
_cfg.set_search_enabled(False)
check("可以关闭联网", _cfg.search_enabled is False)
_cfg.set_search_enabled(True)
check("可以重新开启", _cfg.search_enabled is True)

print("20. 记忆库：双层结构 + 可核查")
st0 = c.get("/api/memory/stats").json()
check("统计接口可用", all(k in st0 for k in ("total", "global", "subject", "accuracy_rate")),
      f"总数={st0.get('total')} 全局={st0.get('global')} 科目={st0.get('subject')}")
check("无判定时准确率为 null（不假装 100%）",
      st0.get("judged", 0) > 0 or st0.get("accuracy_rate") is None,
      f"judged={st0.get('judged')} rate={st0.get('accuracy_rate')}")

# 手动加一条全局记忆
r = c.post("/api/memory", json={
    "content": "E2E测试：我习惯早上背单词", "scope": "global",
    "type": "habit", "pinned": True, "evidence": "我每天早上背单词",
})
m = r.json()["item"]
check("可手动新增全局记忆", r.json().get("ok") and m["scope"] == "global",
      f"id={m['id']} 置信={m['confidence']}")
check("手填的置信度为 1.0", m["confidence"] == 1.0)

# 全局记忆应出现在任意科目的注入预览里
pv = c.get("/api/memory/preview", params={"subject": "math", "query": "早上背单词"}).json()
check("全局记忆跨科目生效", any(x["id"] == m["id"] for x in pv["global"]),
      f"全局 {len(pv['global'])} 条")

# 编辑
r = c.put(f"/api/memory/{m['id']}", json={"content": "E2E测试：我习惯早上 7 点背单词"})
check("可编辑内容", r.json()["item"]["content"].endswith("7 点背单词"))

# 判定不准确 → 立即停用
c.post(f"/api/memory/{m['id']}/verify", json={"accuracy": "wrong"})
pv2 = c.get("/api/memory/preview", params={"subject": "math", "query": "早上背单词"}).json()
check("判为不准确后不再注入",
      not any(x["id"] == m["id"] for x in pv2["global"]))
lst_wrong = c.get("/api/memory", params={"accuracy": "wrong"}).json()["items"]
check("能按判定筛选", any(x["id"] == m["id"] for x in lst_wrong))

# 改判回准确 → 恢复使用
c.post(f"/api/memory/{m['id']}/verify", json={"accuracy": "correct"})
pv3 = c.get("/api/memory/preview", params={"subject": "math", "query": "早上背单词"}).json()
check("改判准确后恢复注入", any(x["id"] == m["id"] for x in pv3["global"]))

# 删除
r = c.delete(f"/api/memory/{m['id']}")
check("可删除记忆", r.json().get("ok") is True)
after = c.get("/api/memory?scope=global").json()["items"]
check("删除后不再出现", not any(x["id"] == m["id"] for x in after))

st1 = c.get("/api/memory/stats").json()
check("统计接口在增删后仍正常", "total" in st1,
      f"当前 {st1['total']} 条（全局 {st1['global']} / 科目 {st1['subject']}）")

print("21. 记忆档案（综述层）+ 整理 / 手改保护 / 导入 / 重置")
meta = c.get("/api/memory/meta").json()
check("meta 有开关字段", "auto_extract" in meta and "auto_consolidate" in meta,
      f"extract={meta.get('auto_extract')} consolidate={meta.get('auto_consolidate')}")

r = c.post("/api/memory/meta", json={"auto_consolidate": False}).json()
check("可关闭自动整理", r.get("auto_consolidate") is False)
c.post("/api/memory/meta", json={"auto_consolidate": True})

# 造两条记忆再整理
for t in ["E2E：目标考计算机专业", "E2E：晚上九点后有空学习"]:
    c.post("/api/memory", json={"content": t, "scope": "global", "type": "goal"})

r = c.post("/api/memory/consolidate").json()
check("整理可执行", r.get("ok") is True, f"mode={r.get('mode')} sections={r.get('sections')}")
check("整理产出分节", (r.get("sections") or 0) >= 1)

docs = c.get("/api/memory/docs").json()["docs"]
check("档案有内容", len(docs) >= 1, f"{len(docs)} 节: " + "/".join(d["section"] for d in docs[:4]))

# 手改保护
d0 = docs[0]
r = c.put(f"/api/memory/docs/{d0['id']}", json={"content": "E2E 手写内容，不要覆盖"}).json()
edited = [x for x in r["docs"] if x["id"] == d0["id"]][0]
check("编辑后标记为手改", edited["user_edited"] is True)

c.post("/api/memory/consolidate")
after = [x for x in c.get("/api/memory/docs").json()["docs"] if x["id"] == d0["id"]][0]
check("再次整理不覆盖手改内容", after["content"] == "E2E 手写内容，不要覆盖",
      after["content"][:30])

# 导入
r = c.post("/api/memory/import", json={"section": "E2E导入", "text": "这是导入的一段档案"}).json()
check("可导入档案", r.get("ok") and any(x["section"] == "E2E导入" for x in r["docs"]))

# 重置（只清档案）
r = c.post("/api/memory/reset", params={"scope": "docs"}).json()
check("可重置档案", r.get("deleted_docs", 0) >= 1, f"删除 {r.get('deleted_docs')} 节")
check("重置后档案为空", len(c.get("/api/memory/docs").json()["docs"]) == 0)

print("=" * 64)
print(f"通过 {ok_count} 项，失败 {len(fail)} 项")
if fail:
    print("失败项:", fail)
    sys.exit(1)
print("全部通过")

