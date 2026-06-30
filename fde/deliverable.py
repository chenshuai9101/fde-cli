"""
FDE 交付物生成器

将各阶段的结构化数据渲染为人类可读的 Markdown 文档（.md），
未来可扩展为 .docx / .html / .pptx 格式。
"""
import os
import json
from datetime import datetime
from typing import List, Dict, Optional


def _ensure_output_dir(cfg) -> str:
    """确保输出目录存在"""
    os.makedirs(cfg.output_dir, exist_ok=True)
    return cfg.output_dir


PHASE0_GATE_FIELDS = [
    ("客户与角色", "客户是谁、所属行业、核心使用角色是谁？"),
    ("真实场景", "最近一次麻烦发生在什么时候、谁在做、从哪里开始、到哪里结束？"),
    ("频率与耗时", "每天/每周发生几次？单次耗时、等待或返工多久？"),
    ("业务影响", "慢、错、漏会造成什么成本、质量、合规、体验或收入影响？"),
    ("系统与数据", "涉及哪些系统、文件、账号、权限、API？数据能否访问？"),
    ("样本证据", "是否已拿到表格、工单、聊天、邮件、截图、SOP、录屏或日志？"),
    ("验收标准", "客户愿意接受的原型范围、上线约束和验收标准是什么？"),
]

PHASE0_FOLLOWUP_ROUNDS = [
    ("第一轮：追真实事件", "不要问“想做什么 AI”，追问最近一次具体麻烦：哪一天、哪个角色、哪个任务、卡在哪里。"),
    ("第二轮：追量化损失", "为每个场景补齐频率、单次耗时、涉及人数、错误/等待/返工影响。"),
    ("第三轮：追数据入口", "要求样本、系统入口、字段、权限、API 或 time-audit/Screenpipe 行为数据。"),
]

EVIDENCE_CARD_FIELDS = [
    "痛点名称",
    "真实场景",
    "涉及角色",
    "当前流程",
    "频率",
    "单次耗时",
    "错误/等待/返工影响",
    "数据来源",
    "系统入口",
    "样本是否已拿到",
    "适合 AI/agent 的原因",
    "不确定项",
    "下一步验证方式",
]

AI_FIT_RULES = [
    ("固定规则、固定字段、固定系统", "脚本 / RPA / API 自动化优先"),
    ("大量文本、语音、图片、非结构化信息", "AI 抽取、总结、分类、生成优先"),
    ("需要查多个系统并综合判断", "Agent 编排 / MCP 工具链优先"),
    ("审批、风控、医疗、财务等高风险动作", "人机协同，AI 给建议，人审核"),
    ("规则不清、数据拿不到、验收不可定义", "暂缓，先补数据或做审计"),
]

OBSERVATION_SOURCES = [
    ("行为时间审计", "time-audit / Screenpipe / 操作日志", "应用切换、网页停留、重复窗口、复制粘贴、导入导出"),
    ("文件与目录扫描", "最近修改文件、Excel/CSV/Word/PPT、下载目录", "重复报表、模板文档、多版本文件、批量导出"),
    ("邮件/聊天/工单样本", "脱敏邮件、IM 记录、客服工单、审批记录", "高频问题、重复回复、转派卡点、信息缺失"),
    ("业务系统日志/API", "CRM/ERP/HIS/OA/客服系统日志或 API", "慢流程、退回单据、空字段、排队任务、异常负载"),
    ("短时录屏观察", "30-60 分钟正常工作录屏或陪跑观察", "跨系统查找、人工判断文本、手工改格式、等待/返工"),
]

AUTODISCOVERY_SIGNALS = [
    ("高频重复动作", "同一应用/文件/页面/字段每天多次出现", "脚本、RPA、快捷流程、表单自动填充"),
    ("跨系统链路", "两个以上系统之间频繁切换、复制、查询、导出", "Agent 编排、MCP 工具链、API 集成"),
    ("非结构化处理", "大量邮件、聊天、语音、图片、PDF、长文本需要阅读判断", "LLM 分类、抽取、总结、生成建议"),
    ("报表/文件加工", "相似 Excel/CSV/PPT/Word 周期性生成或多版本修改", "数据清洗、报告生成、文件归档"),
    ("等待/返工/退回", "流程长时间停留、任务反复退回、字段经常补填", "流程再造、人机协同审核、规则校验"),
]

OBSERVATION_CANDIDATE_FIELDS = [
    "候选痛点",
    "发现依据",
    "频率/耗时线索",
    "可能影响",
    "建议验证",
    "需要用户确认",
]


def _has_any(text: str, keywords: List[str]) -> bool:
    return any(k in text for k in keywords)


def _phase0_gate_rows(client_input: str) -> str:
    """Render a lightweight readiness gate from the available raw description."""
    text = client_input or ""
    checks = {
        "客户与角色": bool(text),
        "真实场景": _has_any(text, ["最近", "流程", "场景", "任务", "操作", "录入", "处理", "填写"]),
        "频率与耗时": _has_any(text, ["每天", "每日", "每周", "小时", "分钟", "次", "频率"]),
        "业务影响": _has_any(text, ["错误", "出错", "等待", "返工", "成本", "质量", "合规", "收入", "体验", "慢"]),
        "系统与数据": _has_any(text, ["系统", "Excel", "表格", "API", "文件", "数据库", "HIS", "CRM", "ERP"]),
        "样本证据": _has_any(text, ["样本", "截图", "录屏", "日志", "工单", "邮件", "聊天", "time-audit", "Screenpipe"]),
        "验收标准": _has_any(text, ["验收", "上线", "原型", "准确率", "成功率", "标准"]),
    }
    rows = []
    for field, question in PHASE0_GATE_FIELDS:
        status = "已提供线索" if checks.get(field) else "缺口"
        action = "进入证据卡整理" if checks.get(field) else "继续追问，不能用于 ROI 承诺"
        rows.append(f"| {field} | {status} | {question} | {action} |")
    return "\n".join(rows)


def _phase0_evidence_card_template() -> str:
    rows = []
    for field in EVIDENCE_CARD_FIELDS:
        rows.append(f"| {field} | 待补充 |")
    return "\n".join(rows)


def _observation_mode_hint(client_input: str) -> str:
    text = (client_input or "").strip()
    if not text:
        return "建议启用：客户没有提供痛点描述，应先采集工作痕迹生成候选痛点，再让客户确认。"
    if len(text) < 20 or _has_any(text, ["说不清", "不知道", "没有描述", "不清楚", "无法描述"]):
        return "建议启用：当前描述不足以定位真实痛点，应使用行为观察/样本分析反推候选痛点。"
    return "可选启用：若访谈仍停留在泛泛描述，可用观察模式校验客户主观判断。"


def _observation_candidate_template() -> str:
    return "\n".join(f"| {field} | 待观察/待验证 |" for field in OBSERVATION_CANDIDATE_FIELDS)


# ═════════════════════════════════════════════════════════════════════
# Phase 1: 现场发现报告
# ═════════════════════════════════════════════════════════════════════
def build_discovery_doc(cfg, pain_points: List[Dict], ctx: Dict) -> str:
    """生成 FDE Phase 1 交付物"""
    output_dir = _ensure_output_dir(cfg)
    path = os.path.join(output_dir, "01-fde-discovery.md")
    client_input = ctx.get("client_input", "")

    def _stars(n):
        n = n or 0
        return "⭐" * n if n else "—"

    def _fire(n):
        n = n or 0
        return "🔥" * n if n else "—"

    pain_rows = "\n".join(
        f"| {p.get('id', '?')} | {p.get('category', '-')} | "
        f"{p.get('description', '-')} | "
        f"{_stars(p.get('frequency'))} | "
        f"{_fire(p.get('impact'))} | "
        f"{(p.get('evidence') or '')[:60]} |"
        for p in pain_points
    )

    is_pending = all(p.get("source") == "待分析" for p in pain_points) if pain_points else True
    source_note = (
        "⚠️ **待分析** — 本阶段未能产出真实痛点（见下方说明），不是分析结果。"
        if is_pending else
        "✅ 由 LLM 基于客户原始描述提取，每条痛点附依据。"
    )

    content = f"""# FDE 现场发现报告

> **项目**: {cfg.project_name or cfg.engagement_id}
> **客户**: {cfg.client_name} ({cfg.client_industry})
> **日期**: {datetime.now().strftime("%Y-%m-%d %H:%M")}
> **分析来源**: {source_note}

---

## 1. 客户概览

- **客户名称**: {cfg.client_name or '待确认'}
- **所属行业**: {cfg.client_industry or '待确认'}
- **项目名称**: {cfg.project_name or '待确认'}
- **FDE Engagement ID**: `{cfg.engagement_id}`

---

## 2. 客户输入

{"```" if client_input else ""}
{client_input if client_input else "（无输入 — 无法分析，请补充客户描述）"}
{"```" if client_input else ""}

---

## 3. Phase 0 痛点诊断准入门槛

> 客户表达的需求不等于真实痛点。进入 ROI 或方案承诺前，必须把抽象需求追到
> **具体场景 + 高频动作 + 可量化损失 + 可访问数据 + 可验证结果**。

| 维度 | 当前状态 | 必问问题 | Agent 动作 |
|:--|:--|:--|:--|
{_phase0_gate_rows(client_input)}

### 三轮追问协议

"""
    for title, prompt in PHASE0_FOLLOWUP_ROUNDS:
        content += f"- [ ] **{title}**：{prompt}\n"

    content += f"""

### 候选项目证据卡模板

> 每个候选 AI/agent 项目都要单独填一张证据卡。证据卡不完整时，只能进入“待验证机会”，不能进入收益承诺。

| 字段 | 内容 |
|:--|:--|
{_phase0_evidence_card_template()}

### Phase 0-A 无描述痛点发现模式

> 当客户说不清痛点时，不继续追问“你哪里痛”，改为采集真实工作痕迹，
> 由行为、文件、样本和系统日志反推候选痛点，再让客户确认或否定。

**启用建议**：{_observation_mode_hint(client_input)}

| 数据来源 | 可用工具/材料 | 自动发现信号 |
|:--|:--|:--|
"""
    for source, material, signal in OBSERVATION_SOURCES:
        content += f"| {source} | {material} | {signal} |\n"

    content += f"""

| 观察信号 | 判定依据 | 可能落地方向 |
|:--|:--|:--|
"""
    for signal, basis, direction in AUTODISCOVERY_SIGNALS:
        content += f"| {signal} | {basis} | {direction} |\n"

    content += f"""

#### 观察模式候选痛点卡

| 字段 | 内容 |
|:--|:--|
{_observation_candidate_template()}

#### 用户确认问题

- [ ] 这些候选痛点哪些是真的？
- [ ] 哪些虽然高频但不重要？
- [ ] 哪些涉及隐私、权限或合规限制？
- [ ] 哪个候选痛点愿意提供 3-5 个样本继续验证？

### AI/自动化适配判断

| 观察到的工作类型 | 优先落地方式 |
|:--|:--|
"""
    for pattern, fit in AI_FIT_RULES:
        content += f"| {pattern} | {fit} |\n"

    content += f"""
---

## 4. 痛点矩阵

| ID | 类别 | 描述 | 频率 | 影响 | 依据 |
|:--|:----|:----|:---:|:---:|:----|
{pain_rows if pain_rows else '| — | — | 无痛点数据 | — | — | — |'}

### 评分规则
- **频率**: ⭐1-5（1=极少，5=每天多次）
- **影响**: 🔥1-5（1=轻度不便，5=关键流程阻塞）

---

## 5. FDE 可行性判断

- [ ] 问题可以通过技术手段解决
- [ ] 客户有足够的配合意愿
- [ ] 数据/系统可访问
- [ ] 预计 ROI 为正

---

## 6. 下一步

→ 进入 **Phase 2: 差距评估**，基于以上痛点生成自动化机会清单。
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ═════════════════════════════════════════════════════════════════════
# Phase 2: 差距评估报告
# ═════════════════════════════════════════════════════════════════════
def build_assessment_doc(cfg, opportunities: List[Dict], ctx: Dict) -> str:
    """生成 FDE Phase 2 交付物"""
    output_dir = _ensure_output_dir(cfg)
    path = os.path.join(output_dir, "02-fde-assessment.md")

    def _savings(o):
        v = o.get("estimated_weekly_savings_minutes")
        return f"{v}分钟" if isinstance(v, (int, float)) else "需客户数据"

    def _roi_source(o):
        labels = {
            "time-audit": "真实审计数据",
            "client-assumption": "客户口述假设",
            "llm-assumption": "LLM待验证假设",
            "needs-data": "需客户数据",
        }
        return labels.get(o.get("roi_source"), o.get("roi_source", "需客户数据"))

    if not opportunities:
        opp_rows = "| — | — | — | — | — | — | — |"
    else:
        opp_rows = "\n".join(
            f"| {o.get('id', '?')} "
            f"| {o.get('layer', '?')} "
            f"| {o.get('description', '-')[:50]} "
            f"| {o.get('confidence', '?')} "
            f"| {o.get('difficulty', '?')} "
            f"| {_savings(o)} "
            f"| {o.get('source', '?')} / {_roi_source(o)} |"
            for o in opportunities
        )

    # 只对有真实数字的机会做 ROI 汇总，其余明确标注缺数据
    with_savings = [o for o in opportunities
                    if isinstance(o.get("estimated_weekly_savings_minutes"), (int, float))]
    without_savings = len(opportunities) - len(with_savings)
    total_savings = sum(o["estimated_weekly_savings_minutes"] for o in with_savings)
    pending = [o for o in opportunities if o.get("source") == "待分析"]

    # 假设与依据透明区块
    basis_rows = "\n".join(
        f"| {o.get('id', '?')} | {_savings(o)} | {_roi_source(o)} | {o.get('savings_basis', '-')} |"
        for o in opportunities if o.get("source") != "待分析"
    ) or "| — | — | — | — |"

    content = f"""# FDE 差距评估报告

> **项目**: {cfg.project_name or cfg.engagement_id}
> **日期**: {datetime.now().strftime("%Y-%m-%d %H:%M")}
> **来源**: 现场发现报告 Phase 1 + 时间审计 MCP（如已集成）

{"> ⚠️ **本阶段含待分析项**：部分机会未能由 LLM 产出，见清单中 source=待分析 行。" if pending else ""}

---

## 1. 自动化机会清单

| ID | 层级 | 描述 | 置信度 | 难度 | 周节省 | 来源 / ROI 口径 |
|:--|:---|:----|:-----|:----|:-----|:----|
{opp_rows}

### 层级说明
- **点 (point)**：单次低效小动作，适合 alias/snippet
- **线 (line)**：跨系统固定流程，适合自动化 Skill ← **核心价值**
- **面 (surface)**：角色级工作模式，适合流程再造

---

## 2. ROI 汇总（仅统计有数据支撑的机会）

| 指标 | 值 |
|:---|:---|
| 总机会数 | {len(opportunities)} |
| 高置信度机会 | {sum(1 for o in opportunities if o.get('confidence') == 'high')} |
| 线级机会 | {sum(1 for o in opportunities if o.get('layer') == 'line')} |
| 有 ROI 数据的机会 | {len(with_savings)} |
| **缺 ROI 数据（需客户数据）** | **{without_savings}** |
| 已知周节省合计 | {total_savings} 分钟 |

> ⚠️ 上述周节省仅汇总了有明确依据的机会；标注"需客户数据"的项**未计入**，
> 避免用估算数字误导决策。

---

## 3. 估算依据与假设（透明区块）

| 机会 ID | 周节省 | ROI 口径 | 依据 / 假设 |
|:--|:--|:--|:----|
{basis_rows}

---

## 4. 数据源说明

- **时间审计**: {ctx.get('time_audit_report_id', '未集成')}
- **客户痛点**: Phase 1 产出

> 💡 集成 [time-audit](https://github.com/chenshuai9101/time-audit)（运行 `time-audit --days 14`）
> 可获得基于真实行为数据的自动化机会，比主观描述更可靠，并能为 ROI 提供真实依据。

---

## 5. 下一步

→ 进入 **Phase 3: 架构设计**，为高优先级机会设计技术方案。
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ═════════════════════════════════════════════════════════════════════
# Phase 3: 架构设计报告
# ═════════════════════════════════════════════════════════════════════
def build_architecture_doc(cfg, architecture: Dict, ctx: Dict) -> str:
    """生成 FDE Phase 3 交付物"""
    output_dir = _ensure_output_dir(cfg)
    path = os.path.join(output_dir, "03-fde-architecture.md")

    comp_rows = "\n".join(
        f"| {c.get('name', '?')} | {c.get('tech', '?')} | {c.get('description', '?')} |"
        for c in architecture.get("components", [])
    )

    mile_rows = "\n".join(
        f"| {m.get('phase', '?')} | {m.get('name', '?')} | {m.get('duration', '?')} | {m.get('deliverable', '?')} |"
        for m in architecture.get("milestones", [])
    )

    risk_rows = "\n".join(
        f"| {r.get('risk', '?')} | {r.get('mitigation', '?')} |"
        for r in architecture.get("risks", [])
    )

    content = f"""# FDE 架构设计报告

> **项目**: {cfg.project_name or cfg.engagement_id}
> **日期**: {architecture.get('design_date', datetime.now().strftime('%Y-%m-%d'))}
> **依据**: 差距评估 Phase 2 产出的自动化机会清单

---

## 1. 方案概览

{architecture.get('overview', '—')}

---

## 2. 优先自动化链路

| ID | 描述 | 周节省 | 难度 |
|:--|:----|:-----|:----|
"""
    for pl in architecture.get("priority_lines", []):
        ws = pl.get("weekly_savings")
        ws_str = f"{ws}分钟" if isinstance(ws, (int, float)) else "需客户数据"
        content += f"| {pl['id']} | {pl['description'][:50]} | {ws_str} | {pl['difficulty']} |\n"

    content += f"""
---

## 3. 组件架构

| 组件 | 技术选型 | 职责 |
|:---|:--------|:----|
{comp_rows}

---

## 4. 架构图

{architecture.get('architecture_mermaid', '*未生成*')}

---

## 5. 技术栈

"""
    for category, techs in architecture.get("tech_stack", {}).items():
        content += f"- **{category}**: {', '.join(techs)}\n"

    content += f"""
---

## 6. 里程碑规划

| 阶段 | 名称 | 周期 | 交付物 |
|:---|:----|:---:|:-----|
{mile_rows}

---

## 7. 风险评估

| 风险 | 缓解方案 |
|:---|:--------|
{risk_rows}

---

## 8. 下一步

→ 进入 **Phase 4: 原型计划**，定义优先级最高自动化链路的最小可验证原型。
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ═════════════════════════════════════════════════════════════════════
# Phase 4: 原型计划报告
# ═════════════════════════════════════════════════════════════════════
def build_prototype_doc(cfg, prototype: Dict, ctx: Dict) -> str:
    """生成 FDE Phase 4 交付物"""
    output_dir = _ensure_output_dir(cfg)
    path = os.path.join(output_dir, "04-fde-prototype.md")

    file_rows = "\n".join(
        f"| {f.get('path', '?')} | {f.get('purpose', '?')} |"
        for f in prototype.get("files", [])
    )

    test_rows = "\n".join(
        f"| {t.get('id', '?')} | {t.get('description', '?')} | {t.get('expected', '?')} |"
        for t in prototype.get("test_cases", [])
    )

    content = f"""# FDE 原型计划报告

> **项目**: {cfg.project_name or cfg.engagement_id}
> **日期**: {datetime.now().strftime("%Y-%m-%d %H:%M")}
> **依据**: 架构设计 Phase 3

---

## 1. 原型目录

**位置**: `{prototype.get('prototype_dir', '?')}`

| 文件 | 用途 |
|:---|:----|
{file_rows}

---

## 2. 核心工作流

| 步骤 | 操作 | 使用工具 |
|:---:|:----|:--------|
"""
    for wf in prototype.get("core_workflow", []):
        content += f"| {wf.get('step', '?')} | {wf.get('action', '?')} | {wf.get('tool', '?')} |\n"

    content += f"""
---

## 3. 测试用例

| ID | 描述 | 预期结果 |
|:--|:----|:--------|
{test_rows}

---

## 4. 环境准备

{prototype.get('setup_guide', '*未生成*')}

---

## 5. 下一步

→ 进入 **Phase 5: 交付交接**，打包交付证据包并完成知识转移。
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ═════════════════════════════════════════════════════════════════════
# Phase 5: 交付交接包
# ═════════════════════════════════════════════════════════════════════
def build_handoff_package(cfg, state, package: Dict) -> str:
    """生成 FDE Phase 5 交付物——最终交付证据包"""
    output_dir = _ensure_output_dir(cfg)
    path = os.path.join(output_dir, "05-fde-handoff.md")

    doc_rows = "\n".join(
        f"| {d.get('title', '?')} | {d.get('content', '?')} |"
        for d in package.get("handoff_docs", [])
    )

    metrics = package.get("metrics", {})

    content = f"""# FDE 交付证据包

> **项目**: {package.get('project', cfg.project_name or cfg.engagement_id)}
> **客户**: {package.get('client', cfg.client_name)}
> **交付日期**: {package.get('delivery_date', datetime.now().strftime('%Y-%m-%d'))}
> **FDE Engagement ID**: `{package.get('engagement_id', cfg.engagement_id)}`

---

## 1. 执行摘要

{package.get('summary', '—')}

---

## 2. 项目度量

| 指标 | 值 |
|:---|:---|
| 计划阶段数 | {metrics.get('total_phases', 5)} |
| 完成阶段数 | {metrics.get('completed_phases', '—')} |
| 交付物数量 | {metrics.get('deliverable_count', '—')} |

---

## 3. 交付物清单

| 文件 | 说明 |
|:---|:----|
"""
    for p in state.phases:
        if p.deliverable_path and os.path.exists(p.deliverable_path):
            content += f"| `{p.deliverable_path}` | Phase {p.phase}: {p.name} |\n"

    content += f"""
---

## 4. 交接文档清单

| 文档 | 内容摘要 |
|:---|:--------|
{doc_rows if doc_rows else '| — | — |'}

---

## 5. 后续建议

"""
    for step in package.get("next_steps", []):
        content += f"{step}\n"

    content += f"""

---

## 6. 阶段详情

"""
    for p in state.phases:
        icon = {"pending": "⏳", "running": "🔄", "completed": "✅", "failed": "❌"}
        content += f"- {icon.get(p.status, '❓')} **Phase {p.phase}: {p.name}** — *{p.status}*\n"
        if p.started_at:
            content += f"  - 开始: {p.started_at}\n"
        if p.completed_at:
            content += f"  - 完成: {p.completed_at}\n"

    content += """

---

> 📋 本交付证据包由 **fde-cli v1.0** 自动生成
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    _build_index(cfg, state)
    return path


def _build_index(cfg, state):
    """生成 FDE 项目索引文件"""
    output_dir = _ensure_output_dir(cfg)
    path = os.path.join(output_dir, "README.md")

    lines = [
        f"# FDE 交付项目: {cfg.project_name or cfg.engagement_id}",
        "",
        f"**客户**: {cfg.client_name} ({cfg.client_industry})",
        f"**Engagement ID**: `{cfg.engagement_id}`",
        f"**创建时间**: {state.created_at}",
        f"**最后更新**: {state.updated_at}",
        "",
        "## 交付物索引",
        "",
    ]

    phase_docs = {
        1: ("01-fde-discovery.md", "现场发现报告"),
        2: ("02-fde-assessment.md", "差距评估报告"),
        3: ("03-fde-architecture.md", "架构设计报告"),
        4: ("04-fde-prototype.md", "原型计划报告"),
        5: ("05-fde-handoff.md", "交付交接包"),
    }

    for phase_num, (filename, desc) in phase_docs.items():
        p = state.phases[phase_num - 1]
        icon = {"completed": "✅", "pending": "⏳", "running": "🔄", "failed": "❌"}
        full_path = os.path.join(output_dir, filename)
        if os.path.exists(full_path):
            lines.append(f"- {icon.get(p.status, '❓')} `{filename}` — {desc}")
        else:
            lines.append(f"- {icon.get(p.status, '⏳')} `{filename}` — {desc} *（未生成）*")

    lines.extend([
        "",
        "---",
        f"由 fde-cli v1.0 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ])

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
