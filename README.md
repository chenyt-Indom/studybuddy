# StudyBuddy · 智能学习助手

> 同样一个问题，不同的学生问，应该得到完全不同的回答。
>   
> 这个能力叫**专精化（Specialization）**——不是回答「问题」，而是回答「你问这个问题的这个人」。

![状态](https://img.shields.io/badge/status-v0.1.2%20%E5%88%9D%E7%A8%BF-brightgreen)

![发布](https://img.shields.io/badge/release-v0.1.0--draft-orange)

![模型](https://img.shields.io/badge/model-deepseek--flash-4d6bfe)



![后端](https://img.shields.io/badge/FastAPI-0.162-009688)

![前端](https://img.shields.io/badge/%E5%89%8D%E7%AB%AF-%E6%97%A0%E6%9E%84%E5%BB%BA%E5%8D%95%E9%A1%B5-lightgrey)

![协议](https://img.shields.io/badge/license-MIT-blue)

> **当前版本：v0.1.2 初稿**（GitHub Release 仍为 `v0.1.0-draft`）
>   
> 这是按方案落地的**第一版可运行骨架**：三条主线（专精化 / 遗忘曲线 / 跨科目）已跑通，
>   
> 但不是完成品。错题 OCR、教材配置、课表、周报尚未接入，记忆召回是降级实现。
>   
> 完整的功能边界见 [「已实现」](#五已实现v01) 与 [「还没做」](#七还没做说清楚别误会) 两节。

按《学习智能助手智能体开发方案（专精化版）》v3 实现的 PC 端学习助手。
  
大模型可切换 **DeepSeek（默认）** 或 **中国电信星辰**。

---

## 一、大模型接入（当前默认 DeepSeek）

同时支持 **DeepSeek** 与 **中国电信星辰**，都走 OpenAI 兼容协议，适配器同一套代码。
  
在设置页切换即可，不用改代码。

### DeepSeek 参数（已核对官方文档）

| 项                       | 值                                                   |
| ----------------------- | --------------------------------------------------- |
| **Base URL（OpenAI 格式）** | **`https://api.deepseek.com/v1`**                   |
| 对话接口                    | `POST https://api.deepseek.com/v1/chat/completions` |
| 模型列表                    | `GET https://api.deepseek.com/v1/models`            |
| 鉴权                      | `Authorization: Bearer <API Key>`                   |
| **推荐模型**                | **`deepseek-flash`**（= DeepSeek-V4.1-Flash-1017）    |
| 更强但更贵                   | `deepseek-v4-pro`                                   |
| 上下文 / 最大输出              | 1M / 384K                                           |
| 拿 Key                   | <https://platform.deepseek.com/api_keys>            |
| 官方文档                    | <https://api-docs.deepseek.com/zh-cn/>              |

**模型名的坑（很重要）**

- ✅ 用 `deepseek-flash` —— 这就是 V4.1 Flash
- ⚠️ `deepseek-v4-flash` 是**已下线**的旧名，仍可调用但会兼容路由到 V4.1 Flash
- ❌ `deepseek-v4.1-flash` 这个名字**不存在**，写了会报错
- ❌ `deepseek-chat` / `deepseek-reasoner` 已在 **2026-07-24 弃用**

**思考模式（默认开启，会影响温度）**

```json
{"model": "deepseek-flash", "messages": [...],
 "thinking": {"type": "enabled"}, "reasoning_effort": "low"}
```

- 参数放在请求体根层：`{"thinking": {"type": "enabled" | "disabled"}}`
- 强度：`{"reasoning_effort": "low" | "high" | "max"}`
- ⚠️ **思考模式下 `temperature` / `presence_penalty` / `frequency_penalty` 不生效**
    
  （设置不报错，但被忽略）。所以「要温度」的场景必须显式关掉思考。
- 流式返回里思维链在 `reasoning_content`，与 `content` 同级

本项目按场景自动分配（`backend/config.py` 的 `THINKING_OFF_SCENES`）：

| 场景                   | 思考模式            | temperature | 原因          |
| -------------------- | --------------- | ----------- | ----------- |
| `tutor` 讲解           | ✅ 开（effort=low） | 不传          | 讲课质量优先，接受延迟 |
| `extract_memory` 抽记忆 | ❌ 关             | 0.1         | 要确定，不能瞎编    |
| `mine_pattern` 挖模式   | ❌ 关             | 0.2         | 要严谨推断       |
| `diagnose` 诊断        | ❌ 关             | 0.2         | 要客观         |
| `generate_quiz` 出题   | ❌ 关             | 0.8         | 要多样性，避免重复出题 |
| `report` 周报          | ❌ 关             | 0.6         | 自然但客观       |

### 中国电信星辰（备选）

**`https://ai.ctaigw.cn/v1` 是 API 端点，不是网页** —— 浏览器打开只会得到 401 或空白，
  
这是正常的。要在浏览器里操作请打开控制台：

| 用途        | 链接                                                    |
| --------- | ----------------------------------------------------- |
| 星辰控制台     | <https://ctxirang.ctyun.cn/maas/home>                 |
| 申请 AppKey | <https://ctxirang.ctyun.cn/maas/service/serviceGroup> |
| 模型广场      | <https://ctxirang.ctyun.cn/maas/inlineService>        |
| 官方文档      | <https://www.ctyun.cn/document/11061839/11062312>     |

- 大陆：`https://ai.ctaigw.cn/v1`；编程 Token Plan：`/coding/v1`；全球：`ai.ctaigw.com/{amer|eu|as}/v1`
- `model` 名必须自己填（控制台 → 模型广场 → 模型详情 → 调用示例）

---

## 二、API Key 怎么保密

你说的是「能在前端直接输入 API，并且保密」。这两件事同时成立的关键在于：

> **「前端输入」不等于「前端持有」。**
>   
> Key 提交一次就离开浏览器，之后所有调用都在后端完成。

### 数据流

```text
浏览器（输入框）
   │  只提交一次，走 127.0.0.1 回环，不出网卡
   ▼
FastAPI 后端
   │  Windows DPAPI 加密（CryptProtectData）
   ▼
data/secrets.bin   ← 密文，与「当前 Windows 用户 + 本机」绑定
   │
   └─► 调 DeepSeek 时在后端解密使用，明文永不回传浏览器
```

### 七条硬约束（改代码时别破）

1. **Key 只进不出** —— 所有接口只返回掩码 `sk-a1b2****9f8e`，绝不回传明文
2. **加密落盘** —— DPAPI 加密，拷到别的机器 / 别的 Windows 用户下解不开
3. **前端无痕** —— 不写 localStorage、不写 cookie，输入框提交后立即清空
4. **浏览器不直连大模型** —— 所有请求由后端代理，F12 的 Network 里翻不到 Key
5. **报错擦除** —— 异常信息统一过 `scrub()`，即便网关回显了 Key 也会被替换成掩码
6. **不硬编码** —— `data/` 已在 `.gitignore`，不会随仓库推上 GitHub
7. **可一键删除** —— 设置页有「删除已保存的 Key」

### 这层保护防什么、不防什么（如实说）

- ✅ 防：Key 出现在浏览器开发者工具、前端源码、localStorage、Git 提交历史、日志里
- ✅ 防：拷走 `data/` 目录到别的电脑后直接读出 Key
- ⚠️ 不防：**已经在你这台电脑上、以你的 Windows 账号运行的恶意程序**。
    
  DPAPI 是按用户隔离的，同账号的进程理论上能调用解密。要做到那一步得靠系统层面的隔离。

### 环境变量（可选，优先级更高）

临时覆盖或 CI 场景可以不落盘：

```bash
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-flash
```

环境变量存在时，设置页会显示「环境变量已配置」，本机存储那份不生效。

---

## 三、时间感知 · 联网搜索 · 深度思考

这三件事是「教学要跟得上时代」的基础设施，缺一个模型就只能凭训练记忆瞎答。

### 3.1 时间感知

每次对话都会把当前时间注入 system prompt 的**开头**（模型对开头最敏感）：

```
【当前时间】现在是 2026年10月25日 星期日 01:16（北京时间）。
当用户问「最新/今年/现在」这类问题时，以此时间为准；
如需超出你知识截止时间的信息，应说明需要联网检索或提示用户开启联网搜索。
```

实现位置：`backend/config.py` 的 `now_context()` + `backend/services/websearch.py` 的 `today_line()`。

> ⚠️ **一个 Windows 坑**：`zoneinfo.ZoneInfo("Asia/Shanghai")` 在 Windows 上需要额外装
> `tzdata` 包，没装会直接抛 `ZoneInfoNotFoundError` 把整个请求打挂（本项目踩过）。
> 中国自 1991 年起不实行夏令时，**固定 UTC+8 与 Asia/Shanghai 完全等价**，
> 所以这里做的是「优先 zoneinfo，失败降级固定 +8」，不加依赖。

### 3.2 联网搜索（DeepSeek 官方 Search 接口）

**这是独立接口，不是 chat 的参数**——这点很容易搞错：

| 项 | 值 |
| --- | --- |
| 搜索 | `POST https://api.deepseek.com/v1/tools/search` |
| 抓正文 | `POST https://api.deepseek.com/v1/tools/fetch` |
| 鉴权 | 同一个 `Authorization: Bearer <API Key>` |
| 计费 | **5 元 / 1000 次**，只有 HTTP 200 且 `results` 非空才计费 |
| 限速 | Search 100 QPS（账号级） |

请求体：

```json
{"query": "2026 广东高考数学 最新变化", "count": 6,
 "ori_question": "用户原始问题（帮助理解意图）", "need_content": false}
```

本项目用 `need_content: false`：返回的 `summary` 有 600~800 字，够模型读，比拉正文省时省钱。

**触发策略**（三种模式，前端有下拉框）：

| 模式 | 行为 |
| --- | --- |
| 自动（默认） | 命中时效线索词才查：最新/今年/政策/大纲/分数线/考试时间/报名/趋势/20\d\d … |
| 强制开启 | 每条都查 |
| 关闭 | 一条都不查 |

纯公式推导、纯定义类问题走「自动」时不会触发搜索 —— 一次搜索 0.005 元，
但更重要的是别让简单问题多等 1~2 秒。

**结果怎么用**：搜到的摘要按「权威性 + 相关度」排序后注入 system prompt，
并要求模型**用 [1] [2] 编号标注来源**；前端会在回答下方列出可点击的来源卡片。

预算是可控的：`backend/config.py` 里的 `WEB_SEARCH_COUNT`（条数）、
`WEB_SEARCH_MAX_CONTEXT`（注入上限 7000 字符）。

### 3.3 深度思考（思维链可见、可展开）

DeepSeek 思考模式的思维链在流式响应里是 `delta.reasoning_content`，与 `content` 同级。

本项目把它**单独一路推到前端**，渲染成可折叠块：

- 流式过程中实时更新「深度思考过程 · N 字」
- 点标题**展开/收起**，展开后自动滚到最新一行
- 思考中正文区只显示「深度思考中…」，不干扰阅读
- **思维链会存库**（`messages.reasoning` 字段），回翻历史时还能再展开看

### 3.4 长输出（解决「只输出一半」）

之前 `max_tokens` 固定 2048，长讲解必然被砍。现在按场景分级：

| 场景 | max_tokens |
| --- | --- |
| **tutor 讲解** | **16384** |
| 生成复习卡 | 6144 |
| 学习周报 | 4096 |
| 抽记忆 / 诊断 | 2048 |
| 挖模式 | 1536 |

DeepSeek-V4.1-Flash 的理论上限是 384K 输出，所以 16384 远没到顶。
没直接拉满的原因：给太高模型容易啰嗦，按场景给「够用就行」更稳。

改 `backend/config.py` 的 `MAX_TOKENS_MAP` 即可调整。

## 四、快速开始（Windows PC）

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
>   
> 这些**不依赖大模型**的模块全部可用。只有对话和复习卡生成会落到「离线演示模式」，
>   
> 输出会明确标注这是占位内容，不会假装是真模型。

---

## 五、已实现（v0.1）

按方案「三条主线 + 两条通路」落地：

| 模块             | 状态 | 说明                                                                                          |
| -------------- | -- | ------------------------------------------------------------------------------------------- |
| 大模型适配器         | ✅  | `LLMProvider` 抽象 + DeepSeek / 星辰（共用 OpenAI 兼容逻辑）+ `MockProvider` 降级；httpx 直连，不依赖 openai SDK |
| 分场景温度 + 思考模式   | ✅  | 讲解开思考（effort=low）；抽记忆 0.1 / 挖模式 0.2 / 出题 0.8 / 周报 0.6 且关思考，保证温度生效                           |
| **时间感知** | ✅ | 每轮把北京时间注入 Prompt 开头；Windows 缺 tzdata 时降级固定 UTC+8 |
| **联网搜索** | ✅ | DeepSeek `/v1/tools/search`，自动/强制/关闭三档；带 [1][2] 引用 + 前端来源卡片 |
| **思维链可展开** | ✅ | `reasoning_content` 单独推流，折叠块实时更新、可展开收起，存库可回翻 |
| **长输出** | ✅ | tutor 上限 2048 → 16384，按场景分级（这是长讲解被截断的根因） |
| SSE 流式对话       | ✅  | 含 `X-Accel-Buffering: no`；思维链 `reasoning_content` 单独推前端做「深度思考中」提示                           |
| **API Key 保密** | ✅  | 前端输入一次 → DPAPI 加密落盘 → 接口只回掩码 → 浏览器不直连模型；8 项安全验收覆盖                                           |
| **专精化引擎**      | ✅  | 四维画像、认知风格推断（视觉/语言/动手/逻辑）、心理状态、讲解风格自适应                                                       |
| **遗忘曲线引擎**     | ✅  | SM-2 三参数（EF/interval/repetitions）、指数衰减记忆强度、三级优先级队列、复习卡生成                                    |
| **跨科目协调**      | ✅  | 知识点关联图谱、跨科提示、协同建议、偏科预警                                                                      |
| 模式挖掘           | ✅  | P1 题型分层、P3 错误归因、P4 知识断层；带样本门槛（30 题 / 10 错题）                                                 |
| 长期记忆库          | ⚠️ | 提取/衰减/召回已实现，但召回用字符 bigram 而非向量检索（见「未完成」）                                                    |
| 错题本            | ⚠️ | 手动录入 + 自动知识点归因 + 错因六分类；OCR 未接                                                               |
| 成绩与趋势          | ✅  | 逐题记录、百分制趋势、掌握度重算                                                                            |
| 对话不可删除         | ✅  | 不提供删除接口，`is_deletable` 恒为 0，前端无删除按钮                                                         |
| 密钥不硬编码         | ✅  | 环境变量 > DPAPI 加密的 `data/secrets.bin` > `data/settings.json`；`data/` 已在 .gitignore            |

### 怎么验证「专精化」真的生效

学习档案页右上角有个「**看我的 Prompt 长什么样**」——点开会显示实际发给大模型的
  
system prompt。同一道题，视觉型 + 信心低 + 中档题弱的学生，和语言型 + 审题弱的
  
学生，拿到的 Prompt 完全不同。这是专精化最直接的证据，不是嘴上说说。

对话页右侧还有一个「本次回答的上下文」面板，实时显示这次注入了几条记忆、
  
几条洞察、有没有跨科关联。

---

## 六、目录结构

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
│       ├── llm/                # 大模型适配（base / openai_compat / teleai 垫片）
│       ├── profile/            # 专精化引擎（style_infer / builder）
│       ├── pattern/            # 模式挖掘（analyzer / error_pattern / gap / miner）
│       ├── forgetting/         # 遗忘曲线（sm2 / strength / scheduler / card_gen）
│       ├── cross_subject/      # 跨科目（graph）
│       ├── memory/             # 记忆库（extractor / store / recall）
│       ├── secrets_store.py    # API Key 加密存储（DPAPI）+ 掩码/擦除
│       ├── websearch.py        # DeepSeek Search 接口 + 时效判定 + 上下文拼装
│       ├── tutor.py            # build_tutor_prompt —— 专精化的落地点
│       ├── chat_service.py     # 一次对话触发三个引擎
│       ├── mastery.py  kp.py   # 掌握度计算 / 知识点候选检索
│       └── util.py             # 模型 JSON 输出健壮解析
├── frontend/                   # 无构建单页（原生 JS + 手写 SVG 图表）
├── tests/
│   ├── smoke_test.py           # 后端端到端 55 项
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

## 七、还没做（说清楚，别误会）

| 项          | 方案章节 | 现在的状态                                                                   |
| ---------- | ---- | ----------------------------------------------------------------------- |
| 错题拍照 → OCR | 第九章  | ❌ 表结构（`mistake_images` / `ocr_tasks`）已建好，链路未接。需要 PaddleOCR + OpenCV 预处理 |
| 教材版本适配     | 第十章  | ❌ 表结构已建（`user_region` / `user_textbook` / `textbook_kp`），高德定位与地区→教材映射未接 |
| 课表         | 7.x  | ❌ 表已建，无接口无界面                                                            |
| 学习周报       | 12.6 | ❌ 提示词已写好，未接                                                             |
| 向量记忆检索     | 第八章  | ⚠️ 降级为 bigram                                                           |
| 前端 Vue 化   | 14.1 | ⚠️ 有意后置                                                                 |
| 专业选择库      | 11.x | ❌ 未开始                                                                   |

预置知识点目前是**数学 19 个 + 物理 12 个 + 化学 4 个 + 生物 2 个 + 语文 2 个 + 英语 2 个**
  
（按方案建议先跑通数学+物理）。要扩到小学/初中全学段，改 `backend/seeds.py` 即可。

---

## 八、测试

```bash
# 后端端到端（需要服务已启动）
.venv\Scripts\python tests\smoke_test.py

# 前端 DOM 冒烟（需要服务已启动 + jsdom）
npm i jsdom
node tests\dom_test.cjs
```

当前结果：**后端 55/55 通过，前端 17/17 通过**
（含 10 项 API Key 保密性验收、时间感知/联网/思维链/长输出验收）。

后端测试覆盖：注册登录 → 改画像 → 录 30 条逐题成绩 → 触发 P1/P4 洞察 →
  
复习队列 → SM-2 打分 → 遗忘曲线 → 错题自动归因 → 错因画像 → 跨科图谱 →
  
认知风格推断 → SSE 流式 → 对话不可删除 → **API Key 保密性（10 项）** →
**时间感知 / 联网检索 / 思维链 / 长输出（12 项）**。

---

## 九、设计原则

1. **不做替代思考的工具** —— AI 负责讲清楚和追问，答案要学生自己组织出来
2. **数据属于用户** —— 全本地 SQLite，不联网不上传，可导出
3. **宁可少而深** —— 三个引擎跑通，胜过十个功能半成品
4. **降级要诚实** —— 没有 Key 时明确标注「离线演示」，绝不假装是真模型的回答

---

## 十、版本记录

### v0.1.2 · 时间感知 + 联网搜索 + 思维链 + 长输出（2026-10-25）

按用户反馈修三件事：

1. **思维链只能看字数** → 现在实时推原文，折叠块可展开/收起，且存库
2. **长回答被截断** → `max_tokens` 按场景分级，tutor 从 2048 提到 16384
3. **没有时间感知和联网** → 注入北京时间 + 接入 DeepSeek `/v1/tools/search`

顺手修的 bug：

- Windows 上 `zoneinfo` 缺 tzdata 直接把请求打挂（降级固定 UTC+8）
- `loadHistory()` 异步返回会覆盖 `innerHTML`，用户手快先发消息会被历史抹掉
- 测试脚本缺项目根路径，无法 import backend

测试：后端 55/55、前端 17/17

### v0.1.1 · 接入 DeepSeek + API Key 保密（2026-10-25）

**定位**：按用户要求把主用模型从星辰换成 DeepSeek，并把「前端输入 Key 且保密」真正做扎实。

- 新增 `DeepSeekProvider`，与星辰共用 `OpenAICompatProvider`（同一套 OpenAI 兼容逻辑）
- 默认模型 `deepseek-flash`（= V4.1-Flash-1017），base_url `https://api.deepseek.com/v1`
- 处理 DeepSeek 思考模式：讲解开思考，其余场景关思考以保证 temperature 生效
- 新增 `secrets_store.py`：Windows DPAPI 加密存储 Key，掩码输出，报错擦除
- 设置页重写：供应商切换 / Key 输入（提交即清空）/ 掩码状态 / 一键删除 / 拉取模型列表
- 前端对话新增「深度思考中…已想 N 字」提示，思维链不混进正文
- 安全验收 8 项：响应无明文、只回掩码、磁盘无明文、可清除等
- 测试：后端 38/38、前端 13/13

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
