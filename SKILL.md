# FDE Agent Skill — 前线部署工程执行引擎

## 你能用它做什么

FDE（Frontline Deployment Engineering）把"企业 AI / 自动化落地评估"拆成 5 阶段流水线，
每阶段产出一份结构化 `.md` 交付物。**真正的分析由 LLM 完成**——可以是你（调用方 Agent）背后的
模型，也可以是 FDE 自己配置的 ollama / OpenAI 端点。

> ⚠️ **诚实第一**：FDE 不再编造数据。没有客户输入、或没有配置可用 LLM 时，
> 对应字段会被明确标注 `待分析`，而不是填充看似合理的假痛点 / 假 ROI。
> 你看到 `待分析` 就知道：这里需要真实输入或模型，不能直接交给客户。

## 适用场景

- 客户说"帮我们诊所/公司做 AI 优化、搞自动化"
- 需要从零做：需求分析 → 机会评估 → 方案设计 → 原型计划 → 交付交接
- 需要**带文件的结构化交付包**，而不是口头建议

## 你作为 Agent 的标准动作

### Step 0 — 先把客户说清楚（关键，Phase 0）
FDE 的产出质量 = 你喂给它的客户信息质量。客户一开始说的通常是“想象中的方案”，
不是可落地痛点。**动手前先做三轮追问**：

1. **追真实事件**：不要问“你想做什么 AI”，问“最近一次觉得麻烦是哪一天、谁在做、做了多久、卡在哪里？”
2. **追量化损失**：为每个场景补齐每天/每周次数、单次耗时、涉及人数、错误/等待/返工影响。
3. **追数据入口**：要求样本、系统入口、字段、权限、API，或 time-audit/Screenpipe 行为数据。

把每个候选项目整理成证据卡后再创建项目：

```
痛点名称：
真实场景：
涉及角色：
当前流程：
频率：
单次耗时：
错误/等待/返工影响：
数据来源：
系统入口：
样本是否已拿到：
适合 AI/agent 的原因：
不确定项：
下一步验证方式：
```

证据卡缺少“频率、耗时、影响、数据来源、样本/系统入口”时，只能进入待验证机会，不能承诺 ROI。

### Step 0-A — 客户说不清痛点时，切换观察模式
如果客户无法描述痛点，不要继续逼问“哪里痛”。改用工作痕迹反推：

- 行为时间审计：time-audit / Screenpipe / 操作日志，找高频应用切换、复制粘贴、导入导出。
- 文件与目录扫描：最近修改的 Excel/CSV/Word/PPT、下载目录，找重复报表、模板文档、多版本文件。
- 邮件/聊天/工单样本：找高频问题、重复回复、转派卡点、信息缺失。
- 业务系统日志/API：找慢流程、退回单据、空字段、排队任务、异常负载。
- 短时录屏观察：让用户正常工作 30-60 分钟，观察跨系统查找、人工判断文本、手工改格式、等待/返工。

观察模式输出候选痛点卡，而不是直接下结论：

```
候选痛点：
发现依据：
频率/耗时线索：
可能影响：
建议验证：
需要用户确认：
```

然后让用户做确认题：哪些是真的、哪些不重要、哪些有权限/隐私限制、哪个愿意提供样本继续验证。

### Step 1 — 创建项目（带 LLM 配置）
```
fde_create_engagement({
  client_name: "某社区诊所",
  client_industry: "医疗",
  project_name: "病历录入AI优化",
  description: "15名医生，3个分院，日均73分钟花在病历模板填写...",
  llm_provider: "none",            // 默认诚实降级；或 "ollama" / "openai"
  llm_model: "qwen2.5:14b",        // openai 则如 "gpt-4o-mini"
  llm_endpoint: "",                 // 留空按 provider 取默认
  llm_api_key: ""                   // 留空回退环境变量
})
```
返回里会注明 LLM 是否可用；若不可用，输出会是 `待分析` 骨架。

### Step 2 — 执行（逐阶段更可控）

FDE 有**两种分析模式**，取决于你这个调用方 Agent 的能力：

**① Brief 模式（强 Agent 推荐）—— 你自己分析，引擎只编排/校验/渲染**
你（如 Claude）通常比引擎内置的本地小模型更强、且掌握与客户的完整对话。
让引擎把"分析"还给你，质量最高（`llm_provider` 设 `none` 即可，无需引擎 LLM）：
```
// ① 取分析任务包：引擎不调用任何模型，只给 prompt + 上游上下文 + 期望 schema
fde_get_phase_brief({ engagement_id: "eng-xxxx", phase: 1 })
//   返回 { ready, system, user, schema, ... }；ready=false 时按 reason 补数据

// ② 你按 brief 的 system/user/schema 亲自分析，产出 JSON

// ③ 回填：引擎归一化你的结果、融合 time-audit、渲染交付物、持久化供下一阶段
fde_submit_phase_result({ engagement_id: "eng-xxxx", phase: 1, result: "<你的JSON>" })
```
依次走 phase 1→5。**每个阶段的 brief 会自动加载上一阶段你回填的产出**，无需手动传递。
传 `context: {"time_audit_opportunities": [...]}` 可并入真实审计机会。

**② 内部 LLM 模式 —— 引擎用自己配置的 LLM 分析（适合弱 Agent / 图省事）**
```
fde_run_phase({ engagement_id: "eng-xxxx", phase: 1 })   // 现场发现：提取痛点
fde_run_phase({ engagement_id: "eng-xxxx", phase: 2 })   // 差距评估：痛点→机会
fde_run_phase({ engagement_id: "eng-xxxx", phase: 3 })   // 架构设计
fde_run_phase({ engagement_id: "eng-xxxx", phase: 4 })   // 原型计划
fde_run_phase({ engagement_id: "eng-xxxx", phase: 5 })   // 交付交接
```
或一键：`fde_run_all({ engagement_id, client_input })`

> **为什么有 Brief 模式**：引擎最擅长流程编排、结构校验、交付物渲染、跨阶段持久化——
> 不该和你抢"分析"这件你更擅长的事。Brief 模式让强 Agent 真正发挥价值，
> 而不是把分析转包给可能更弱的内置模型。

### Step 3 — 审阅每阶段产出（不要盲目往下走）
```
fde_get_deliverable({ engagement_id: "eng-xxxx", phase: 1 })
```
**读一遍**痛点是否贴合客户原话、是否出现 `待分析`。
- 出现 `待分析` → 补客户输入或配置 LLM 后重跑该阶段。
- Phase 0 准入门槛出现“缺口” → 先补访谈或样本，不要继续包装方案。
- 客户无法描述痛点 → 启用 Phase 0-A 观察模式，先生成候选痛点再让客户确认。
- 痛点不准 → 调整 `description` 重跑 Phase 1，再继续。
确认无误后再进入下一阶段。

### Step 4 — 交付给客户
把各阶段 `.md` 内容发给客户。注意向客户说明：
标注"需客户数据"的 ROI 项是**待验证假设**，不是承诺数字。

## 关键设计（你需要知道的约束）

- **ROI 诚实**：周节省分钟数必须带 `roi_source`，只允许分为
  `time-audit`（真实审计数据）、`client-assumption`（客户口述假设）、
  `llm-assumption`（LLM 待验证假设）、`needs-data`（需客户数据）。
  ROI 汇总**只统计有数字的项**，但交付时必须说明其口径。绝不要把假设数字当成既定收益讲给客户。
- **time-audit 优先**：若客户能提供真实行为数据，Phase 2 传入 `time_audit_opportunities`，
  其可信度高于任何 LLM 推测。
- **Phase 0 强制证据卡**：客户表达的需求 ≠ 真实痛点。真实痛点必须落到具体场景、高频动作、
  可量化损失、可访问数据、可验证结果。
- **Phase 0-A 观察优先**：客户无法描述痛点时，使用行为审计、文件扫描、样本分析、系统日志或录屏观察反推候选痛点。
- **降级可识别**：`source: "待分析"` / `status: "待分析"` 是显式信号，遇到就回到上一步补数据。

## 私有知识

- 输出目录：`~/Desktop/fde-engagements/<engagement_id>/`
- 状态文件：`<id>/fde_state.json`；客户输入持久化在 `<id>/.client_input.txt`
- 交付物为 `.md`，可直接读取发送
- LLM 后端：任意 OpenAI 兼容端点（ollama 本地 / OpenAI / vLLM / DeepSeek 等）
- `llm_provider: "none"` = 默认诚实降级模式（只出骨架，不调模型）
- MCP 工具统一以 `fde_` 前缀命名
