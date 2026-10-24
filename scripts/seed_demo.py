"""生成演示账号，让第一次打开就能看到效果。

用法（服务需已启动）：
    .venv\\Scripts\\python scripts\\seed_demo.py

账号：demo / demo123456
"""
from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8787"
USERNAME = "demo"
PASSWORD = "demo123456"

# q_no -> 知识点（15 题的卷子结构）
MATH_Q = {
    1: "math.set", 2: "math.function_basic", 3: "math.function_basic",
    4: "math.linear_function", 5: "math.inequality", 6: "math.factorization",
    7: "math.quadratic_function",
    8: "math.quadratic_function", 9: "math.quadratic_function", 10: "math.trigonometry",
    11: "math.sequence", 12: "math.logarithm",
    13: "math.derivative", 14: "math.analytic_geometry", 15: "math.derivative",
}
PHY_Q = {
    1: "physics.motion_basic", 2: "physics.motion_basic", 3: "physics.newton_law",
    4: "physics.newton_law", 5: "physics.force_composition", 6: "physics.work_energy",
    7: "physics.momentum", 8: "physics.projectile", 9: "physics.projectile",
    10: "physics.circuit", 11: "physics.circuit", 12: "physics.ohm_law",
    13: "physics.electric_field", 14: "physics.magnetic_field", 15: "physics.wave",
}


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=120)

    r = c.post("/api/auth/register", json={"username": USERNAME, "password": PASSWORD,
                                           "nickname": "陈同学"})
    if r.status_code == 400:
        r = c.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    if r.status_code >= 400:
        print("注册/登录失败:", r.text[:300])
        return 1
    tok = r.json()["token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    print("账号就绪：demo / demo123456")

    c.put("/api/profile", json={"stage": "senior", "grade": "senior_2",
                                "target_major": "人工智能技术应用", "target_score": 620,
                                "electives": ["物理", "化学"]})

    # ---- 数学：三场考试，基础稳、中档塌、压轴放弃 ----
    math_plan = [
        ("期中考试", 78, "2026-08-25", lambda q: q <= 6 or q == 8),
        ("9月月考", 84, "2026-09-22", lambda q: q <= 7 or q == 9),
        ("10月月考", 88, "2026-10-20", lambda q: q <= 7 or q == 10),
    ]
    for name, score, date, correct_fn in math_plan:
        qs = [{"q_no": q, "kp_code": MATH_Q[q], "is_correct": bool(correct_fn(q))}
              for q in range(1, 16)]
        r = c.post("/api/grades", json={"subject": "math", "exam_name": name,
                                        "score": score, "full_score": 150,
                                        "exam_date": date, "questions": qs})
        print(f"  数学 {name}: {r.json().get('insights_found')} 条洞察")

    # ---- 物理：整体偏弱，电路最差（制造跨科拖累）----
    phy_plan = [
        ("9月月考", 62, "2026-09-22", lambda q: q <= 4),
        ("10月月考", 58, "2026-10-20", lambda q: q <= 4 or q == 6),
    ]
    for name, score, date, correct_fn in phy_plan:
        qs = [{"q_no": q, "kp_code": PHY_Q[q], "is_correct": bool(correct_fn(q))}
              for q in range(1, 16)]
        r = c.post("/api/grades", json={"subject": "physics", "exam_name": name,
                                        "score": score, "full_score": 100,
                                        "exam_date": date, "questions": qs})
        print(f"  物理 {name}: {r.json().get('insights_found')} 条洞察")

    # ---- 错题：以「计算失误」为主，制造习惯类洞察 ----
    mistakes = [
        ("math", "二次函数顶点那题，配方到一半把符号写反了", "math.quadratic_function", "calculation", "medium"),
        ("math", "数列求通项，等比求和公式分母漏了 1-q", "math.sequence", "calculation", "medium"),
        ("math", "导数求单调区间，端点开闭判断错", "math.derivative", "careless", "hard"),
        ("math", "三角函数化简，把 sin2x 当成 2sinx", "math.trigonometry", "concept", "medium"),
        ("math", "解析几何联立方程算错，后面全崩", "math.analytic_geometry", "calculation", "hard"),
        ("math", "对数换底公式记混", "math.logarithm", "concept", "basic"),
        ("math", "不等式取等条件漏写", "math.inequality", "careless", "medium"),
        ("math", "压轴题看都没看，直接空着", "math.derivative", "timeout", "hard"),
        ("math", "韦达定理代错，根与系数关系搞反", "math.quadratic_function", "calculation", "medium"),
        ("math", "函数的定义域没考虑分母不为零", "math.function_basic", "careless", "basic"),
        ("math", "向量数量积算成叉积", "math.vector", "concept", "medium"),
        ("math", "最后 5 分钟匆忙涂卡，答案位移", "math.sequence", "timeout", "basic"),
        ("physics", "电路题没考虑电源内阻", "physics.circuit", "concept", "medium"),
        ("physics", "平抛运动分解时把水平竖直搞反", "physics.projectile", "method", "medium"),
        ("physics", "受力分析漏了摩擦力", "physics.newton_law", "careless", "basic"),
    ]
    for subj, content, kp, err, tier in mistakes:
        c.post("/api/mistakes", json={"subject": subj, "content": content, "kp_code": kp,
                                      "error_type": err, "tier": tier})
    print(f"  错题 {len(mistakes)} 道")

    # ---- 对话：真实走一遍 SSE，让认知风格/记忆库有原料 ----
    prompts = [
        ("math", "二次函数的顶点怎么求？我想看图理解，最好画个抛物线给我看"),
        ("math", "配方法我总是算错，有没有更直观的办法"),
        ("physics", "电路题为什么要考虑内阻？我画面想不出来"),
        ("physics", "平抛运动能不能画个示意图，我想看轨迹"),
    ]
    for subj, text in prompts:
        got = 0
        with c.stream("POST", "/api/chat/stream",
                      json={"subject": subj, "message": text}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    try:
                        evt = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    if evt.get("type") == "delta":
                        got += len(evt.get("text", ""))
        print(f"  对话[{subj}] {got} 字")

    # ---- 触发分析 + 重算画像 ----
    r = c.post("/api/insight/run")
    print("  模式挖掘:", r.json().get("found"), "条")
    r = c.post("/api/profile/refresh-style")
    st = r.json().get("style", {})
    print("  认知风格:", st.get("primary"), st.get("scores"))

    # ---- 挑几个知识点做一次复习，让曲线有历史 ----
    q = c.get("/api/review/queue").json().get("items", [])
    for i, item in enumerate(q[:4]):
        c.post(f"/api/review/{item['kp_code']}/grade", json={"quality": [5, 4, 3, 2][i]})
    print(f"  已复习 {min(4, len(q))} 个知识点")

    print("\n完成。打开 http://127.0.0.1:8787 ，用 demo / demo123456 登录。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
