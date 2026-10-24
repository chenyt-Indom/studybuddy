# StudyBuddy · 智能学习助手

> 同样一个问题，不同的学生问，应该得到完全不同的回答。
> 这个能力叫**专精化（Specialization）**——不是回答「问题」，而是回答「你问这个问题的这个人」。

![状态](https://img.shields.io/badge/status-v0.1%20%E5%88%9D%E7%A8%BF-brightgreen)
![发布](https://img.shields.io/badge/release-v0.1.0--draft-orange)
![后端](https://img.shields.io/badge/FastAPI-0.162-009688)
![前端](https://img.shields.io/badge/%E5%89%8D%E7%AB%AF-%E6%97%A0%E6%9E%84%E5%BB%BA%E5%8D%95%E9%A1%B5-lightgrey)
![协议](https://img.shields.io/badge/license-MIT-blue)

> **当前版本：v0.1 初稿（`v0.1.0-draft`）**
> 这是按方案落地的**第一版可运行骨架**：三条主线（专精化 / 遗忘曲线 / 跨科目）已跑通，
> 但不是完成品。错题 OCR、教材配置、课表、周报尚未接入，记忆召回是降级实现。
> 完整的功能边界见 [「已实现」](#三已实现v01) 与 [「还没做」](#五还没做说清楚别误会) 两节。

基于**中国电信星辰大模型**、按《学习智能助手智能体开发方案（专精化版）》v3 实现的 PC 端学习助手。

---

## 一、星辰大模型 API（先说这个）

**接口地址（已实测连通）**

| 项 | 值 |
| --- | --- |
| 大陆节点 | `https://ai.ctaigw.cn` |
| 版本前缀 | `/v1` |
| **Base URL** | **`https://ai.ctaigw.cn/v1`** |
| 对话接口 | `POST https://ai.ctaigw.cn/v1/chat/completions` |
| 模型列表 | `GET https://ai.ctaigw.cn/v1/models` |
| 鉴权 | `Authorization: Bearer <AppKey>` |
| 协议 | OpenAI 兼容 ✅ |

实测：不带 Key 请求上面两个接口都返回

```json
{"error":{"message":"未携带Authorization请求头","type":"authentication_error",
          "code":"no_authentication_credential"}}
```

HTTP 401 —— 说明网关真实存在且是标准 OpenAI 兼容格式，可以直接用 OpenAI SDK 或任意
OpenAI 客户端对接。

> ⚠️ **两件必须自己确认的事**（官方文档明确提示）
> 1. **`model` 填什么** —— 去控制台「模型广场 → 模型详情 → 调用示例」查看。
>    本项目做了自动探测：设置页点「探测可用模型」，走 `GET /v1/models` 拉取列表，点一下填入。
> 2. **真实请求地址** —— 官方说明「不同区域、不同类型的模型，终端请求地址有所差异」。
>    如果 `ai.ctaigw.cn` 不通，去控制台「调用示例」看真实地址，填到设置页的 base_url 里。
>    不要去抄示例值。

**获取 AppKey**：平台 → 系统管理 → APP Key 管理。

---

## 二、快速开始（Windows PC）

### 方式一：双击

```bat
start.bat
```

首次运行会自动建虚拟环境、装依赖，然后打开 <http://127.0.0.1:8787>。

### 方式二：手动

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --port 8787
```

打开 <http://127.0.0.1:8787>，注册一个账号即可。

### 接入星辰模型

左下角「设置」→ 填 AppKey → 点「探测可用模型」→ 选中一个 model → 保存。
左下角状态会从 `离线演示模式` 变成 `星辰模型已接入`。

> **没 AppKey 也能跑**：学情看板、复习调度、错题归因、知识点掌握度、跨科关联
> 这些**不依赖大模型**的模块全部可用。只有对话和复习卡生成会落到「离线演示模式」，
> 输出会明确标注这是占位内容，不会假装是真模型。

---

## 三、已实现（v0.1）

按方案「三条主线 + 两条通路」落地：

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 星辰 API 适配器 | ✅ | `LLMProvider` 抽象 + `TeleAIProvider` + `MockProvider` 降级；httpx 直连，不依赖 openai SDK |
| 分场景温度 | ✅ | tutor 0.7 / 抽记忆 0.1 / 挖模式 0.2 / 出题 0.8 / 周报 0.6 |
| SSE 流式对话 | ✅ | 含 `X-Accel-Buffering: no`，前端边收边渲染 |
| **专精化引擎** | ✅ | 四维画像、认知风格推断（视觉/语言/动手/逻辑）、心理状态、讲解风格自适应 |
| **遗忘曲线引擎** | ✅ | SM-2 三参数（EF/interval/repetitions）、指数衰减记忆强度、三级优先级队列、复习卡生成 |
| **跨科目协调** | ✅ | 知识点关联图谱、跨科提示、协同建议、偏科预警 |
| 模式挖掘 | ✅ | P1 题型分层、P3 错误归因、P4 知识断层；带样本门槛（30 题 / 10 错题） |
| 长期记忆库 | ⚠️ | 提取/衰减/召回已实现，但召回用字符 bigram 而非向量检索（见「未完成」） |
| 错题本 | ⚠️ | 手动录入 + 自动知识点归因 + 错因六分类；OCR 未接 |
| 成绩与趋势 | ✅ | 逐题记录、百分制趋势、掌握度重算 |
| 对话不可删除 | ✅ | 不提供删除接口，`is_deletable` 恒为 0，前端无删除按钮 |
| 密钥不硬编码 | ✅ | 环境变量 > `data/settings.json`；`data/` 已在 .gitignore |

### 怎么验证「专精化」真的生效

学习档案页右上角有个「**看我的 Prompt 长什么样**」——点开会显示实际发给星辰的
system prompt。同一道题，视觉型 + 信心低 + 中档题弱的学生，和语言型 + 审题弱的
学生，拿到的 Prompt 完全不同。这是专精化最直接的证据，不是嘴上说说。

对话页右侧还有一个「本次回答的上下文」面板，实时显示这次注入了几条记忆、
几条洞察、有没有跨科关联。

---

## 四、目录结构

```text
studybuddy/
├── backend/
│   ├── main.py                 # FastAPI 入口 + 静态托管
│   ├── config.py               # 配置（密钥不硬编码）
│   ├── db.py  models.py        # SQLite + 全部 ORM（对齐方案第十三章）
│   ├── security.py  deps.py    # PBKDF2 口令 + JWT
│   ├── seeds.py                # 知识点/依赖/跨科关联预置数据
│   ├── prompts/                # 提示词集中管理（附录 A）
│   ├── api/                    # auth chat profile grade review mistake insight cross system
│   └── services/
│       ├── llm/                # 星辰适配器（base / teleai / mock）
│       ├── profile/            # 专精化引擎（style_infer / builder）
│       ├── pattern/            # 模式挖掘（analyzer / error_pattern / gap / miner）
│       ├── forgetting/         # 遗忘曲线（sm2 / strength / scheduler / card_gen）
│       ├── cross_subject/      # 跨科目（graph）
│       ├── memory/             # 记忆库（extractor / store / recall）
│       ├── tutor.py            # build_tutor_prompt —— 专精化的落地点
│       ├── chat_service.py     # 一次对话触发三个引擎
│       ├── mastery.py  kp.py   # 掌握度计算 / 知识点候选检索
│       └── util.py             # 模型 JSON 输出健壮解析
├── frontend/                   # 无构建单页（原生 JS + 手写 SVG 图表）
├── tests/
│   ├── smoke_test.py           # 后端端到端 27 项
│   └── dom_test.cjs            # 前端 DOM 冒烟 13 项
├── data/                       # 运行时数据（不入库）
└── start.bat
```

### 技术选型的两处主动偏离

1. **前端没用 Vue 3 + Element Plus + ECharts**，改成原生 JS + 手写 SVG。
   原因：PC 端先行验证阶段，`npm install` 在有代理问题的机器上经常装不下来，
   会让整套东西「跑不起来」。图表全部是手写 SVG，零 CDN、零构建，断网也能看。
   等三条主线验证完再迁 Vue，**后端接口一行都不用改**。

2. **记忆召回没用 ChromaDB**，改用 SQLite + 字符 bigram 重叠打分。
   原因：ChromaDB 会拉 onnxruntime 等一堆重依赖。召回层已经按 `recall()` 抽象好，
   换向量检索只改一个文件。这是明确的**降级实现，不是最终形态**。

---

## 五、还没做（说清楚，别误会）

| 项 | 方案章节 | 现在的状态 |
| --- | --- | --- |
| 错题拍照 → OCR | 第九章 | ❌ 表结构（`mistake_images` / `ocr_tasks`）已建好，链路未接。需要 PaddleOCR + OpenCV 预处理 |
| 教材版本适配 | 第十章 | ❌ 表结构已建（`user_region` / `user_textbook` / `textbook_kp`），高德定位与地区→教材映射未接 |
| 课表 | 7.x | ❌ 表已建，无接口无界面 |
| 学习周报 | 12.6 | ❌ 提示词已写好，未接 |
| 向量记忆检索 | 第八章 | ⚠️ 降级为 bigram |
| 前端 Vue 化 | 14.1 | ⚠️ 有意后置 |
| 专业选择库 | 11.x | ❌ 未开始 |

预置知识点目前是**数学 19 个 + 物理 12 个 + 化学 4 个 + 生物 2 个 + 语文 2 个 + 英语 2 个**
（按方案建议先跑通数学+物理）。要扩到小学/初中全学段，改 `backend/seeds.py` 即可。

---

## 六、测试

```bash
# 后端端到端（需要服务已启动）
.venv\Scripts\python tests\smoke_test.py

# 前端 DOM 冒烟（需要服务已启动 + jsdom）
npm i jsdom
node tests\dom_test.cjs
```

当前结果：**后端 27/27 通过，前端 13/13 通过**。

后端测试覆盖：注册登录 → 改画像 → 录 30 条逐题成绩 → 触发 P1/P4 洞察 →
复习队列 → SM-2 打分 → 遗忘曲线 → 错题自动归因 → 错因画像 → 跨科图谱 →
认知风格推断 → SSE 流式 → 对话不可删除 → 星辰配置。

---

## 七、设计原则

1. **不做替代思考的工具** —— AI 负责讲清楚和追问，答案要学生自己组织出来
2. **数据属于用户** —— 全本地 SQLite，不联网不上传，可导出
3. **宁可少而深** —— 三个引擎跑通，胜过十个功能半成品
4. **降级要诚实** —— 没有 Key 时明确标注「离线演示」，绝不假装是真模型的回答

---

## 八、版本记录

### v0.1 初稿 · `v0.1.0-draft`（2026-10-25）

**定位**：按方案 v3 落地的第一版可运行骨架。能跑、能验证三大引擎是真的在工作，但不是完成品。

已落地：

- 星辰大模型接入（`ai.ctaigw.cn/v1`，OpenAI 兼容，实测 401 可达）+ 无 Key 时的诚实降级
- 专精化引擎：四维画像 / 认知风格推断 / 心理状态 / 讲解风格自适应
- 遗忘曲线引擎：SM-2 三参数 / 指数衰减记忆强度 / 三级优先级队列 / 复习卡生成
- 跨科目协调：知识点图谱 / 跨科提示 / 协同建议 / 偏科预警
- 模式挖掘：P1 题型分层 / P3 错误归因 / P4 知识断层（含样本门槛）
- 记忆库：异步提取 / 半衰期衰减 / bigram 召回
- 错题本：手动录入 / 自动知识点归因 / 错因六分类
- 成绩与趋势：逐题记录 / 百分制趋势 / 掌握度重算
- PC 端 7 个页面：对话 / 看板 / 复习 / 错题 / 洞察 / 档案 / 设置

已知欠缺（下一版要补）：

- 错题拍照 OCR 链路（表已建，未接 PaddleOCR）
- 教材版本适配（表已建，未接高德定位与映射表）
- 课表、学习周报、专业选择库
- 记忆召回仍是 bigram，未换向量检索
- 前端仍是原生 JS，未迁 Vue

测试基线：后端 27/27、前端 13/13。

---

## 许可证

[MIT](LICENSE)
