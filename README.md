# FDE — Frontline Deployment Engineering

> **前线部署工程** — 将企业 AI 落地需求从现场发现到交付交接的全生命周期流水线。

---

## 概述

FDE 是一套将 **企业 AI / 自动化落地** 咨询过程固化为可执行流水线的方法论引擎。

借鉴 Palantir Forward Deployed Engineer 的"蹲现场解决问题"理念，抽象为 **LLM 驱动分析、Agent 可编排、人类可操作** 的 5 阶段流水线。

> **设计底线：诚实优先。** FDE 的分析由真实 LLM 产生，不是写死的模板。
> 没有客户输入、或没有配置可用 LLM 时，对应内容会被明确标注 `待分析`，
> ROI 数字只在有依据时给出（否则标 `需客户数据`），**绝不编造**。

```
Phase 0               Phase 1               Phase 2               Phase 3               Phase 4               Phase 5
访谈补齐  ──→  现场发现  ──→  差距评估  ──→  架构设计  ──→  原型计划  ──→  交付交接
痛点矩阵          自动化机会清单        技术方案+架构图      可运行原型          交付证据包
   ▲                  ▲                    ▲                  ▲
   └──────────── 每个阶段由 LLM 针对本项目分析（可降级为「待分析」骨架）────────┘
```

## 核心能力

| 阶段 | 做什么 | 输出 |
|:---|:------|:----|
| **Phase 0 访谈/观察补齐** | 用三轮追问或行为观察，把客户表层需求还原为真实事件、量化损失、数据入口和候选项目证据卡 | 嵌入 `01-fde-discovery.md` |
| **Phase 1 现场发现** | LLM 从客户原话提取痛点矩阵（带依据，无输入则标待分析） | `01-fde-discovery.md` |
| **Phase 2 差距评估** | 痛点映射为自动化机会；可融合 time-audit 真实数据；ROI 标明真实审计/客户口述/LLM 假设/需数据 | `02-fde-assessment.md` |
| **Phase 3 架构设计** | 针对项目的技术方案、架构图、风险、里程碑 | `03-fde-architecture.md` |
| **Phase 4 原型计划** | 最小可验证原型的文件清单、核心工作流、测试用例、环境准备 | `04-fde-prototype.md` |
| **Phase 5 交付交接** | 汇总全阶段交付物，输出交付证据包（度量为真实数据） | `05-fde-handoff.md` + `README.md` |

## 安装

```bash
pip install fde-cli
```

或从源码安装：

```bash
git clone https://github.com/chenshuai9101/fde-cli.git
cd fde-cli
pip install -e .
```

## 快速开始

```bash
# 创建项目（带 LLM 配置；provider=none 则进入诚实降级模式）
fde new --client "某诊所" --industry "医疗" --project "病历AI优化" \
        --input "医生每天花2小时录病历，多系统切换" \
        --llm-provider none

# 如果已准备好本地模型，再显式启用 ollama：
fde new --client "某诊所" --industry "医疗" --project "病历AI优化" \
        --input "医生每天花2小时录病历，多系统切换" \
        --llm-provider ollama --llm-model qwen2.5:14b

# 用 OpenAI（或任何兼容端点）：
fde new --client "某诊所" --industry "医疗" --project "病历AI优化" \
        --llm-provider openai --llm-model gpt-4o-mini --llm-api-key sk-xxx

# 列出项目
fde list

# 查看状态
fde status eng-20260101-120000

# 执行阶段（逐阶段，便于审阅）
fde run eng-20260101-120000 --phase 1
fde run eng-20260101-120000 --phase 2

# 一键全流程
fde run-all eng-20260101-120000 --input "医生每天花2小时录病历"

# 查看交付物
fde deliverable eng-20260101-120000 --phase 3
```

## Phase 0：先发现真实痛点

创建项目前，Agent 应先把客户的“想做 AI”追问成证据卡：

1. **追真实事件**：最近一次麻烦发生在什么时候？谁在做？从哪里开始？卡在哪里？
2. **追量化损失**：每天/每周几次？单次多久？几个人参与？慢、错、漏造成什么影响？
3. **追数据入口**：样本、系统、字段、权限、API、录屏、日志或 time-audit 数据是否可获得？

证据卡必须覆盖：真实场景、涉及角色、当前流程、频率、单次耗时、错误/等待/返工影响、
数据来源、系统入口、样本是否已拿到、适合 AI/agent 的原因、不确定项、下一步验证方式。

缺少频率、耗时、影响、数据来源或样本时，FDE 只能把机会标为待验证，不能承诺 ROI。

如果客户无法描述痛点，切换 **Phase 0-A 无描述痛点发现模式**：

| 自动化发现方式 | 适合发现 |
|:--|:--|
| 行为时间审计（time-audit / Screenpipe / 操作日志） | 多系统切换、重复录入、复制粘贴、导入导出 |
| 文件与目录扫描 | 周报/月报、重复 Excel、模板文档、多版本文件、批量 CSV |
| 邮件/聊天/工单样本分析 | 高频问题、重复回复、转派卡点、审批来回沟通 |
| 系统日志/API 分析 | 慢流程、退回单据、空字段、排队任务、异常负载 |
| 30-60 分钟录屏观察 | 跨系统查找、人工判断、手工改格式、等待/返工 |

观察模式先生成候选痛点卡，再让用户确认“哪些是真的、哪些不重要、哪些受权限或隐私限制”。

## LLM 配置

FDE 通过 OpenAI 兼容接口调用模型，同一套代码覆盖本地与云端：

| 场景 | provider | endpoint（留空取默认） | model | api_key |
|:--|:--|:--|:--|:--|
| 本地 ollama | `ollama` | `http://localhost:11434`(自动补 `/v1`) | `qwen2.5:14b` | 可空 |
| OpenAI | `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` | `sk-...` |
| 兼容服务 | `openai` | 你的端点 | 你的模型 | 视情况 |
| **诚实降级（默认）** | `none` | — | — | — |

api_key 留空时回退环境变量 `FDE_LLM_API_KEY` / `OPENAI_API_KEY`。
`provider=none` 为默认值，只产出 `待分析` 骨架，不调用任何模型——适合先搭流程、后接模型。

## 给 Agent 用（MCP）

FDE 提供完整的 MCP 工具集，适配 Claude Desktop / Cursor / OpenClaw 等 MCP 客户端。

Agent 可直接调用以下工具：
- `fde_create_engagement` — 创建项目
- `fde_run_phase` — 执行阶段（引擎内部 LLM 分析）
- `fde_run_all` — 一键全流程（引擎内部 LLM 分析）
- `fde_get_deliverable` — 获取交付物
- `fde_get_engagement_status` — 查看状态
- `fde_list_engagements` — 列出项目
- `fde_get_phase_brief` — **Brief 模式**：取分析任务包，由调用方 Agent 自行分析
- `fde_submit_phase_result` — **Brief 模式**：回填分析结果，引擎归一/渲染/持久化

> **Brief 模式**：当调用方 Agent（如 Claude）比引擎内置模型更强时，
> 用 `get_phase_brief` 取走"该分析什么"的任务包（prompt + 上游上下文 + schema），
> 自己分析后用 `submit_phase_result` 回填。引擎只负责编排、校验、渲染、跨阶段持久化，
> 不和调用方抢分析。`llm_provider: "none"` 时 Brief 模式照常工作。

## 与 time-audit 集成

FDE 天然可与 [time-audit](https://github.com/chenshuai9101/time-audit) 集成:

```
客户行为数据 → time-audit 发现 → FDE Phase 2 差距评估
```

## 输出位置

所有交付物生成在 `~/Desktop/fde-engagements/<engagement_id>/`。

## 设计理念

1. **诚实 > 好看** — 没有依据的痛点 / ROI 一律标 `待分析` / `需客户数据`，绝不编造
2. **智能由 LLM 产生** — 每阶段针对本项目分析，而非套用写死模板
3. **数据驱动 > 主观判断** — Phase 2 优先使用 time-audit 真实行为数据
4. **ROI 分级透明** — ROI 来源分为真实审计数据、客户口述假设、LLM 待验证假设、需客户数据
5. **交付物是文件不是数据库** — 每阶段产出 `.md`，桌面即可阅读
6. **人类 ↔ Agent 双入口** — CLI + MCP tools，同一引擎
7. **可插拔 LLM** — 任意 OpenAI 兼容端点（本地 / 云端），可降级、可替换

## 捐赠支持

如果 FDE 对你有帮助，欢迎请作者喝杯咖啡 ☕

<img src="./assets/donate-qr.jpg" width="240" alt="捐赠收款码" />

---

## License

MIT
