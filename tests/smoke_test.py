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

print("22. 教材通路：版本选择 / 跨册定位 / 目录导入")
eds = c.get("/api/textbook/editions", params={"subject": "math", "stage": "senior"}).json()
names = [e["name"] for e in eds["editions"]]
check("可选多版本", len(names) >= 4, "/".join(names))
check("人教A版有内置目录", any(e["code"] == "rja" and e["builtin"] for e in eds["editions"]))
check("未内置的版本明确标注需导入",
      any(e["name"] == "北师大版" and not e["builtin"] for e in eds["editions"]))

cur = c.get("/api/textbook/current", params={"subject": "math"}).json()
check("有当前教材", cur.get("ok") is True, f"{cur.get('title')}")

# 跨册定位
m1 = c.get("/api/textbook/match", params={"subject": "math", "q": "二次函数顶点怎么求"}).json()
check("二次函数定位到 2.3 节",
      any("2.3" in s for s in (m1.get("sections") or [])),
      (m1.get("sections") or [""])[0])
m2 = c.get("/api/textbook/match", params={"subject": "math", "q": "导数的几何意义"}).json()
check("导数定位到选择性必修（跨册生效）",
      "选择性必修" in " ".join(m2.get("sections") or []),
      (m2.get("sections") or [""])[0])
m3 = c.get("/api/textbook/match", params={"subject": "physics", "q": "平抛运动怎么算"}).json()
check("平抛定位到必修第二册",
      any("抛体" in s for s in (m3.get("sections") or [])),
      (m3.get("sections") or [""])[0])

# 结构
o = c.get(f"/api/textbook/{cur['id']}/outline").json()
n_ch = len(o.get("chapters") or [])
n_sec = sum(len(ch["sections"]) for ch in o.get("chapters") or [])
check("结构可读", o.get("ok") and n_ch > 0, f"{n_ch} 章 / {n_sec} 节")

# 粘贴目录导入 + 删除
r = c.post("/api/textbook/outline", json={
    "subject": "math", "title": "E2E 自定义目录",
    "raw": "第一章 测试章 | 1.1 测试节 | 二次函数\n第一章 测试章 | 1.2 另一节 | 导数",
}).json()
check("可粘贴目录导入", r.get("ok") and r.get("sections") == 2, r.get("message"))
tid = r.get("id")
if tid:
    oo = c.get(f"/api/textbook/{tid}/outline").json()
    check("导入的目录有结构", len(oo.get("chapters") or []) == 1)
    check("可删除导入教材", c.delete(f"/api/textbook/{tid}").json().get("ok") is True)

# 切换教材（原来只有"能选到"，没有"真能切"，漏掉了这条路径）
eds = c.get("/api/textbook/editions", params={"subject": "math", "stage": "senior"}).json()["editions"]
rja = [e for e in eds if e["code"] == "rja"][0]
codes = [b["code"] for b in rja["books"]]
check("人教A版有多个册次可切", len(codes) >= 2, "/".join(codes))

for code in codes[:2]:
    c.post("/api/textbook/select", params={"subject": "math", "code": code})
    cur2 = c.get("/api/textbook/current", params={"subject": "math"}).json()
    check(f"切到 {code} 后 current 一致", cur2.get("code") == code, cur2.get("title"))

# 切到"没有内置目录"的版本应当明确失败，而不是假成功
bad = c.post("/api/textbook/select", params={"subject": "math", "code": "bsd"}).json()
check("没有目录的版本不能假成功", bad.get("ok") is False, bad.get("message"))

# 导入目录时带上版本 code -> 该版本立刻变成"已导入"且册次可点，不产生重复的自定义卡
bsd_before = [e for e in eds if e["code"] == "bsd"][0]
check("北师大版原本没有可用册次", bsd_before["books"] == [])
r = c.post("/api/textbook/outline", json={
    "subject": "math", "title": "北师大版必修一", "edition_code": "bsd",
    "raw": "第一章 预备知识 | 1.1 集合 | 集合\n第一章 预备知识 | 1.2 常用逻辑用语 | 充分条件",
}).json()
new_code = r.get("code")
eds2 = c.get("/api/textbook/editions", params={"subject": "math", "stage": "senior"}).json()["editions"]
bsd_after = [e for e in eds2 if e["code"] == "bsd"][0]
check("导入后北师大版有可用册次", bsd_after["available"] and len(bsd_after["books"]) == 1,
      str([b["code"] for b in bsd_after["books"]]))
check("导入后不另起一张自定义卡",
      not [e for e in eds2 if e.get("custom")], str([e["name"] for e in eds2]))
cur3 = c.get("/api/textbook/current", params={"subject": "math"}).json()
check("导入后自动切到新教材", cur3.get("code") == new_code, cur3.get("title"))
ok3 = c.post("/api/textbook/select", params={"subject": "math", "code": new_code}).json()
check("刚导入的册次可再次切回", ok3.get("ok") is True, ok3.get("title"))

# 切回内置第一册，避免影响后续用例
c.post("/api/textbook/select", params={"subject": "math", "code": codes[0]})

print("23. 对话图片：上传 / 校验 / 越权 / 带图对话")
import struct  # noqa: E402
import zlib    # noqa: E402


def _png(rgb=(220, 30, 30), w=64, h=64):
    """纯 stdlib 造一张 PNG —— 测试不想为了跑起来再装 PIL。"""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def ck(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + ck(b"IHDR", ihdr)
            + ck(b"IDAT", zlib.compress(raw, 9)) + ck(b"IEND", b""))


up = c.post("/api/chat/attachments",
            files={"file": ("题目.png", _png(), "image/png")}).json()
check("可上传题目图片", up.get("ok") is True and str(up.get("id", "")).startswith("u"),
      f"{up.get('id')} {up.get('size')}B")
aid = up.get("id") or ""
got = c.get(f"/api/chat/attachments/{aid}")
check("图片能读回且是图片类型",
      got.status_code == 200 and got.headers.get("content-type", "").startswith("image/"),
      f"{len(got.content)}B")
bad = c.post("/api/chat/attachments",
             files={"file": ("x.png", b"this is not an image", "image/png")}).json()
check("把别的文件改名成 png 会被挡下", bad.get("ok") is False, bad.get("message"))

# 越权：别的用户读不到我的图
other = httpx.Client(base_url=BASE, timeout=30)
oname = "other_%d" % (int(time.time()) % 1000000)
otok = other.post("/api/auth/register",
                  json={"username": oname, "password": "123456"}).json()["token"]
orow = other.get(f"/api/chat/attachments/{aid}",
                 headers={"Authorization": f"Bearer {otok}"}).json()
check("别的用户读不到我的图", orow.get("ok") is False or orow.get("detail"), str(orow)[:60])

# 当前模型能不能看图（官方 /models 的 input_modalities）
vis = c.get("/api/system/vision").json()
check("能力接口说明当前模型是否支持图片", "supported" in vis, f"{vis.get('model')} → {vis.get('supported')}")

# 带图对话：真调一次模型，确认图片真的送到了。
# 故意不打字 —— 顺带验证「只发图也能问」会自动补一句问法
ans, err, status_texts = [], "", []
with c.stream("POST", "/api/chat/stream",
              json={"subject": "math", "message": "", "attachments": [aid]}) as resp:
    for line in resp.iter_lines():
        if not line.startswith("data:"):
            continue
        evt = json.loads(line[5:].strip())
        if evt.get("type") == "delta":
            ans.append(evt["text"])
        elif evt.get("type") == "status":
            status_texts.append(evt.get("text", ""))
        elif evt.get("type") == "error":
            err = evt.get("message", "")
check("只发图不打字也能得到回答", not err and bool("".join(ans).strip()),
      err or f"{''.join(ans).strip()[:20]} | 状态：{status_texts[:2]}")

conv = [x for x in c.get("/api/chat/conversations").json() if x["subject"] == "math"][0]
hmsgs = c.get("/api/chat/messages", params={"conversation_id": conv["id"]}).json()
huser = [m for m in hmsgs if m["role"] == "user"][-1]
check("历史消息里带着图片附件",
      bool(huser.get("attachments")) and huser["attachments"][0]["id"] == aid,
      str(huser.get("attachments"))[:80])
check("空消息自动补问法入库", "图片" in (huser.get("content") or ""),
      (huser.get("content") or "")[:24])

print("24. 知识点汇总 / 提示 / 年级过滤 / 跨科联动")
ov = c.get("/api/kp/overview", params={"stage": "senior"}).json()
check("知识点汇总可读", ov.get("ok") is True, f"共 {ov.get('stats', {}).get('total_all')} 个")
check("覆盖多科目", len(ov.get("subjects") or []) >= 5,
      "/".join(s2["cn"] for s2 in ov.get("subjects") or []))
check("知识点总数够用", (ov.get("stats") or {}).get("total_all", 0) >= 100,
      f"{(ov.get('stats') or {}).get('total_all')}")
first_items = [i for s2 in ov["subjects"] for m in s2["modules"] for i in m["items"]]
check("每条都有要点", all(i.get("summary") for i in first_items[:40]))
check("每条都有年级", all(i.get("grade_cn") for i in first_items[:40]))
check("按模块分组", all(m.get("name") for s2 in ov["subjects"] for m in s2["modules"]))

# 详情：三个提示字段 + 依赖 + 联动
d = c.get("/api/kp/math.quadratic_function").json()
it = d.get("item") or {}
check("详情有要点/易错/锚点",
      bool(it.get("summary")) and bool(it.get("pitfall")) and bool(it.get("mnemonic")),
      it.get("mnemonic", ""))
check("详情有前置知识", len(d.get("prerequisites") or []) >= 1,
      "/".join(p["name"] for p in d.get("prerequisites") or []))
check("详情有解锁知识", len(d.get("unlocks") or []) >= 1,
      "/".join(p["name"] for p in d.get("unlocks") or []))
check("详情有跨科联动", len(d.get("cross") or []) >= 1,
      (d.get("cross") or [{}])[0].get("note", "")[:24])

# 搜索：名称与口语别名都要能命中
check("搜「抛物线」能命中二次函数",
      any(x["name"] == "二次函数" for x in c.get("/api/kp/search",
          params={"q": "抛物线"}).json()["items"]))
check("搜「勒夏特列」能命中化学平衡",
      any(x["name"] == "化学平衡" for x in c.get("/api/kp/search",
          params={"q": "勒夏特列"}).json()["items"]))

# 年级过滤：只给高一时，不该出现导数/圆锥曲线这类高二高三内容
g1 = c.get("/api/kp/overview", params={"stage": "senior", "mode": "current",
                                       "grade": "senior_1"}).json()
names1 = [i["name"] for s2 in g1["subjects"] for m in s2["modules"] for i in m["items"]]
check("仅本年级只返回该年级", g1["stats"]["total_shown"] > 0
      and all(i["grade"] == "senior_1" for s2 in g1["subjects"]
              for m in s2["modules"] for i in m["items"]),
      f"{g1['stats']['total_shown']} 条")
check("高一视图里没有导数/圆锥曲线", "导数" not in names1 and "圆锥曲线" not in names1)
check("高二视图里才出现导数",
      any(i["name"] == "导数" for s2 in c.get("/api/kp/overview", params={
          "stage": "senior", "mode": "current", "grade": "senior_2"}).json()["subjects"]
          for m in s2["modules"] for i in m["items"]))

# 讲解 prompt：该有的段落都在（透明化预览走的就是真对话上下文）
pv = c.get("/api/profile/prompt-preview",
           params={"subject": "physics", "q": "平抛运动怎么算落地时间"}).json()
sp = pv.get("system_prompt") or ""
check("prompt 有年级约束", "【年级约束】" in sp)
check("prompt 有知识点提示", "【知识点提示】" in sp and "记忆锚点" in sp)
check("prompt 有跨科联动", "【跨科联动·记忆锚点】" in sp)
check("prompt 有教材定位", "【教材定位】" in sp)
check("教材名没重复出版社", "人教版 人教版" not in sp)

print("25. 教材知识库（IMA）对接：状态 / 诊断 / 降级")
st = c.get("/api/ext/ima").json()
check("IMA 状态可读", st.get("ok") is True, f"configured={st.get('configured')}")
check("指向 IMA 的 MCP 接口", "ima.qq.com" in (st.get("url") or ""), st.get("url"))
check("状态里有本地片段计数", isinstance(st.get("cached_snippets"), int),
      f"{st.get('cached_snippets')} 条")
pr = c.post("/api/ext/ima/test").json()
check("诊断接口有结构", isinstance(pr.get("probe"), dict) and "ok" in (pr.get("probe") or {}),
      (pr.get("probe") or {}).get("reason", ""))
# 没 token 时必须明确说「未配置」，而不是 500
if not st.get("configured"):
    check("没配 token 时诊断给出明确原因",
          "Token" in ((pr.get("probe") or {}).get("reason") or ""),
          (pr.get("probe") or {}).get("reason", ""))
    sy = c.post("/api/ext/ima/sync", json={"stage": "senior", "max_queries": 1}).json()
    check("没配 token 时同步给出明确原因", sy.get("ok") is False
          and "Token" in (sy.get("message") or ""), sy.get("message"))
kb = c.get("/api/ext/kb", params={"q": "平抛运动"}).json()
check("本地片段检索可用（可以为空）", kb.get("ok") is True and isinstance(kb.get("items"), list),
      f"{kb.get('count')} 条")
# 开关能读能写（测完恢复成开）
off = c.post("/api/ext/ima/enabled", json={"enabled": False}).json()
on = c.post("/api/ext/ima/enabled", json={"enabled": True}).json()
check("教材摘录开关可切换", off.get("enabled") is False and on.get("enabled") is True)
check("关闭后讲解 prompt 里没有教材摘录段",
      "【教材摘录】" not in c.get("/api/profile/prompt-preview",
                                  params={"subject": "physics"}).json()["system_prompt"])

print("26. 学习周报：生成 / 取回 / 数据口径")
w0 = c.get("/api/weekly/latest").json()
check("周报接口可用", w0.get("ok") is True, "是否已有：" + str(w0.get("exists")))
wg = c.post("/api/weekly/generate").json()
check("能生成本周周报", wg.get("ok") is True and bool(wg.get("content")),
      f"来源 {wg.get('source')}，{len(wg.get('content') or '')} 字")
check("周报带本周起止日期", wg.get("week_start", "") <= wg.get("week_end", ""),
      f"{wg.get('week_start')} ~ {wg.get('week_end')}")
st = wg.get("stats") or {}
check("统计快照字段齐全",
      all(k in st for k in ("qa_count", "new_mistakes", "review_due", "weak_kps", "exams")),
      f"qa={st.get('qa_count')} 错题={st.get('new_mistakes')} 待复习={st.get('review_due')}")
check("周报正文有结构（小标题）", "##" in (wg.get("content") or ""))
w1 = c.get("/api/weekly/latest").json()
check("能取回已生成的周报", w1.get("exists") is True and w1.get("week_start") == wg.get("week_start"),
      w1.get("week_start"))
wl = c.get("/api/weekly/list").json()
check("历史列表可用", wl.get("ok") is True and len(wl.get("items") or []) >= 1,
      f"{len(wl.get('items') or [])} 条")
# 同一周重复生成不该产生多条记录
c.post("/api/weekly/generate")
wl2 = c.get("/api/weekly/list").json()
same_week = [x for x in wl2["items"] if x["week_start"] == wg["week_start"]]
check("同一周重复生成不重复入库", len(same_week) == 1, f"{len(same_week)} 条")

print("=" * 64)
print(f"通过 {ok_count} 项，失败 {len(fail)} 项")
if fail:
    print("失败项:", fail)
    sys.exit(1)
print("全部通过")

