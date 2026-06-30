"""
FDE 五阶段核心逻辑（LLM 驱动 + Brief 模式）

两种分析路径，共用同一套 prompt 构造与结果归一逻辑（单一事实来源）：

  A. 内部 LLM 模式  run_xxx(..., llm)
     引擎用自己配置的 LLM（ollama/OpenAI）完成分析。适合人类 CLI、弱 Agent。

  B. Brief 模式     build_brief(phase, ctx, cfg) -> 分析任务包
                    normalize_result(phase, raw, ctx, cfg) -> 归一化产出
     引擎只产出"该分析什么"的任务包（prompt + 上下文 + schema），
     由调用方 Agent（通常比内置小模型更强）自己分析，再把结果回填。
     引擎负责它最擅长的：编排、校验、归一、渲染、持久化。

诚实第一：无输入 / 无 LLM 时返回标注 "待分析" 的骨架，绝不编造。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from fde.llm import LLMClient, LLMUnavailable, build_llm_client

PENDING = "待分析"
SOURCE_LLM = "llm"
SOURCE_AGENT = "agent"        # 经 Brief 模式由调用方 Agent 分析回填
SOURCE_TIME_AUDIT = "time-audit"

# 各阶段结构化产出在 result dict 中的键名
PHASE_OUTPUT_KEY = {1: "pain_points", 2: "opportunities",
                    3: "architecture", 4: "prototype", 5: "handoff"}


def _resolve_llm(cfg, llm: Optional[LLMClient]) -> LLMClient:
    return llm if llm is not None else build_llm_client(cfg)


# ═════════════════════════════════════════════════════════════════════
# 通用调度：Brief 模式入口
# ═════════════════════════════════════════════════════════════════════
def build_brief(phase: int, ctx: Dict, cfg) -> Dict:
    """产出某阶段的"分析任务包"，供调用方 Agent 自行分析。

    Returns:
        {
          "phase": int, "phase_name": str,
          "ready": bool,            # 上游是否就绪、是否需要 LLM 分析
          "reason": str,            # 不就绪时的说明
          "system": str, "user": str, "schema": str,   # 分析所需的完整 prompt
          "submit_with": "fde_submit_phase_result"      # 回填用的工具
        }
    """
    builders = {1: _discovery_brief, 2: _assessment_brief, 3: _architecture_brief,
                4: _prototype_brief, 5: _handoff_brief}
    if phase not in builders:
        raise ValueError(f"无效阶段: {phase}")
    brief = builders[phase](ctx, cfg)
    brief.setdefault("phase", phase)
    brief.setdefault("phase_name", {1: "现场发现", 2: "差距评估", 3: "架构设计",
                                    4: "原型构建", 5: "交付交接"}[phase])
    brief.setdefault("submit_with", "fde_submit_phase_result")
    return brief


def normalize_result(phase: int, raw, ctx: Dict, cfg, source: str = SOURCE_AGENT) -> Dict:
    """把调用方 Agent 提交的分析结果归一化为阶段的标准产出结构。

    与内部 LLM 模式走完全相同的归一逻辑，保证两条路径产出一致。
    """
    if phase == 1:
        return normalize_pain_points(raw, source)
    if phase == 2:
        return normalize_opportunities(raw, ctx, source)
    if phase == 3:
        return normalize_architecture(raw, ctx, cfg)
    if phase == 4:
        return normalize_prototype(raw, ctx, cfg)
    if phase == 5:
        return normalize_handoff(raw, ctx.get("state"), cfg)
    raise ValueError(f"无效阶段: {phase}")


def _brief_ready(system: str, user: str, schema: str) -> Dict:
    return {"ready": True, "reason": "", "system": system, "user": user, "schema": schema}


def _brief_blocked(reason: str) -> Dict:
    return {"ready": False, "reason": reason, "system": "", "user": "", "schema": ""}


# ═════════════════════════════════════════════════════════════════════
# Phase 1: 现场发现
# ═════════════════════════════════════════════════════════════════════
DISCOVERY_SCHEMA = (
    '[{"id": "P1", "category": "效率|数据|质量|合规|成本|其它", '
    '"description": "针对该客户的具体痛点（引用客户原话中的事实，不要泛泛而谈）", '
    '"frequency": 1-5 整数, "impact": 1-5 整数, '
    '"evidence": "支撑该评分的客户原话片段或推理依据"}]'
)


def _discovery_messages(client_input: str, cfg) -> Tuple[str, str]:
    system = (
        "你是企业 AI 落地的前线部署工程师（FDE）。"
        "你的任务是从客户的真实描述中，提取该客户**特有**的痛点，并按频率和影响打分。"
        "严禁套用通用模板；每条痛点必须能在客户原话中找到依据。"
    )
    user = (
        f"客户：{cfg.client_name or '未提供'}（行业：{cfg.client_industry or '未提供'}）\n"
        f"项目：{cfg.project_name or '未提供'}\n\n"
        f"客户原始描述：\n\"\"\"\n{client_input.strip()}\n\"\"\"\n\n"
        "请提取 3-6 条具体痛点。frequency=发生频率(1=极少,5=每天多次)，"
        "impact=影响程度(1=轻度不便,5=关键流程阻塞)。"
    )
    return system, user


def _discovery_brief(ctx: Dict, cfg) -> Dict:
    client_input = ctx.get("client_input", "") or ""
    if not client_input.strip():
        return _brief_blocked("缺少客户输入，无法提取痛点。请先补充客户的背景/痛点描述。")
    system, user = _discovery_messages(client_input, cfg)
    return _brief_ready(system, user, DISCOVERY_SCHEMA)


def normalize_pain_points(data, source: str = SOURCE_LLM) -> List[Dict]:
    items = data if isinstance(data, list) else \
        data.get("pain_points", []) if isinstance(data, dict) else []
    out = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        out.append({
            "id": raw.get("id") or f"P{i + 1}",
            "category": raw.get("category", "其它"),
            "description": (raw.get("description") or "").strip(),
            "frequency": _clamp(raw.get("frequency", 3)),
            "impact": _clamp(raw.get("impact", 3)),
            "evidence": raw.get("evidence", ""),
            "source": source,
        })
    return out or [_pending_pain_point("未返回有效痛点，请检查模型输出或补充客户描述。")]


def run_discovery(client_input: str, cfg, llm: Optional[LLMClient] = None) -> List[Dict]:
    """Phase 1（内部 LLM 模式）：从客户描述提取痛点矩阵。"""
    if not client_input or not client_input.strip():
        return [_pending_pain_point("缺少客户输入，无法提取痛点。请补充客户的背景/痛点描述。")]

    client = _resolve_llm(cfg, llm)
    if not client.available:
        return [_pending_pain_point(
            "未配置 LLM，无法从客户描述中提取痛点。"
            "请设置 llm_provider/llm_model 后重跑，或用 Brief 模式由调用方 Agent 分析。"
        )]

    system, user = _discovery_messages(client_input, cfg)
    try:
        data = client.complete_json(system, user, DISCOVERY_SCHEMA)
    except LLMUnavailable as e:
        return [_pending_pain_point(f"LLM 调用失败：{e}")]
    return normalize_pain_points(data, SOURCE_LLM)


def _pending_pain_point(reason: str) -> Dict:
    return {"id": "P0", "category": PENDING,
            "description": f"⚠️ {PENDING}：{reason}",
            "frequency": 0, "impact": 0, "evidence": "", "source": PENDING}


def _clamp(v, lo=1, hi=5) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return 3


# ═════════════════════════════════════════════════════════════════════
# Phase 2: 差距评估
# ═════════════════════════════════════════════════════════════════════
ASSESSMENT_SCHEMA = (
    '[{"id": "L-01", "layer": "point|line|surface", '
    '"description": "具体的自动化机会（对应哪个痛点、做什么）", '
    '"confidence": "high|med|low", "difficulty": "high|med|low", '
    '"estimated_weekly_savings_minutes": 数字或 null, '
    '"savings_basis": "估算依据；若无客户真实数据支撑必须写明假设，无法估算则填\\"需客户数据\\"", '
    '"suggestion": "建议的落地动作"}]'
)


def _assessment_messages(pain_points: List[Dict], cfg) -> Tuple[str, str]:
    system = (
        "你是 FDE 自动化评估专家。把客户痛点映射为可落地的自动化机会，分三层：\n"
        "point=单点小动作(alias/snippet)，line=跨系统固定流程(自动化Skill，核心价值)，"
        "surface=角色级工作模式(流程再造)。\n"
        "关于 ROI：只有在有明确依据时才给 estimated_weekly_savings_minutes 数字，"
        "并在 savings_basis 写清假设；没有依据就把数字设为 null 并写 \"需客户数据\"。禁止编造精确数字。"
    )
    pp_text = "\n".join(
        f"- [{p['id']}] {p['category']}：{p['description']}（频率{p['frequency']}/影响{p['impact']}）"
        for p in pain_points
    )
    user = (
        f"客户行业：{cfg.client_industry or '未提供'}\n\n"
        f"已识别痛点：\n{pp_text}\n\n请为每个痛点给出 1-2 个自动化机会。"
    )
    return system, user


def _assessment_brief(ctx: Dict, cfg) -> Dict:
    pain_points = ctx.get("pain_points", []) or []
    real = [p for p in pain_points if p.get("source") != PENDING]
    if not real:
        ta = ctx.get("time_audit_opportunities")
        if ta:
            return _brief_blocked(
                "无客户痛点需 LLM 分析，但存在 time-audit 真实机会。"
                "可直接以空数组 [] 提交，引擎会把 time-audit 机会归一为清单。")
        return _brief_blocked("上游无有效痛点（Phase 1 未完成或降级），无机会可评估。")
    system, user = _assessment_messages(real, cfg)
    return _brief_ready(system, user, ASSESSMENT_SCHEMA)


def normalize_opportunities(raw, ctx: Dict, source: str = SOURCE_AGENT) -> List[Dict]:
    """归一机会清单：融合 time-audit 真实机会 + 提交的分析结果，去重排序。"""
    opportunities: List[Dict] = []
    for opp in (ctx.get("time_audit_opportunities") or []):
        opportunities.append(_normalize_opportunity(opp, SOURCE_TIME_AUDIT))
    items = raw if isinstance(raw, list) else \
        raw.get("opportunities", []) if isinstance(raw, dict) else []
    for i, r in enumerate(items):
        if isinstance(r, dict):
            opportunities.append(_normalize_opportunity(r, source, i))
    if not opportunities:
        opportunities.append(_pending_opportunity("未产出任何机会。"))
    return _dedupe_and_rank(opportunities)


def run_assessment(pain_points, cfg, time_audit_opportunities=None,
                   llm: Optional[LLMClient] = None) -> List[Dict]:
    """Phase 2（内部 LLM 模式）：痛点 → 自动化机会。"""
    opportunities: List[Dict] = []
    for opp in (time_audit_opportunities or []):
        opportunities.append(_normalize_opportunity(opp, SOURCE_TIME_AUDIT))

    real = [p for p in pain_points if p.get("source") != PENDING]
    if real:
        client = _resolve_llm(cfg, llm)
        if client.available:
            system, user = _assessment_messages(real, cfg)
            try:
                data = client.complete_json(system, user, ASSESSMENT_SCHEMA)
                items = data if isinstance(data, list) else data.get("opportunities", [])
                for i, r in enumerate(items):
                    if isinstance(r, dict):
                        opportunities.append(_normalize_opportunity(r, SOURCE_LLM, i))
            except LLMUnavailable as e:
                opportunities.append(_pending_opportunity(f"LLM 调用失败：{e}"))
        else:
            opportunities.append(_pending_opportunity(
                "未配置 LLM，无法将痛点映射为机会（可用 Brief 模式由调用方 Agent 分析）。"))
    elif not opportunities:
        opportunities.append(_pending_opportunity("上游无有效痛点，无机会可评估。"))

    return _dedupe_and_rank(opportunities)


def _classify_roi(source: str, savings, basis: str) -> str:
    """把 ROI 数字的可信度分级，便于交付物透明展示、避免误导。

      time-audit        — 来自真实行为审计数据（最可信）
      needs-data        — 无数字 / 明确需客户数据（不可作为收益承诺）
      client-assumption — 客户口述假设
      <source>-assumption — 由 LLM / Agent 推测的假设
    """
    basis = basis or ""
    if source == SOURCE_TIME_AUDIT:
        return "time-audit"
    if savings is None or "需客户数据" in basis:
        return "needs-data"
    if "客户提供" in basis or basis.startswith("客户"):
        return "client-assumption"
    return f"{source}-assumption"


def _normalize_opportunity(raw: Dict, source: str, idx: int = 0) -> Dict:
    savings = raw.get("estimated_weekly_savings_minutes", raw.get("estimated_savings_minutes"))
    if isinstance(savings, str):
        try:
            savings = int(savings)
        except ValueError:
            savings = None
    basis = raw.get("savings_basis",
                    "来自时间审计真实数据" if source == SOURCE_TIME_AUDIT else "需客户数据")
    return {
        "id": raw.get("id") or f"{source[:1].upper()}-{idx + 1:02d}",
        "layer": raw.get("layer", "line"),
        "description": (raw.get("description") or raw.get("title") or "").strip(),
        "confidence": raw.get("confidence", "med"),
        "difficulty": raw.get("automation_difficulty", raw.get("difficulty", "med")),
        "estimated_weekly_savings_minutes": savings,
        "savings_basis": basis,
        "roi_source": _classify_roi(source, savings, basis),
        "suggestion": raw.get("suggestion", ""),
        "evidence": raw.get("evidence_sessions", raw.get("evidence", [])),
        "source": source,
    }


def _pending_opportunity(reason: str) -> Dict:
    return {"id": "L-0", "layer": PENDING, "description": f"⚠️ {PENDING}：{reason}",
            "confidence": "-", "difficulty": "-", "estimated_weekly_savings_minutes": None,
            "savings_basis": "-", "roi_source": "needs-data", "suggestion": "",
            "evidence": [], "source": PENDING}


def _dedupe_and_rank(opportunities: List[Dict]) -> List[Dict]:
    seen = set()
    uniq = []
    for opp in opportunities:
        key = (opp.get("description") or "")[:60]
        if key in seen:
            continue
        seen.add(key)
        conf_score = {"high": 3, "med": 2, "low": 1}.get(opp.get("confidence", "med"), 0)
        savings = opp.get("estimated_weekly_savings_minutes") or 0
        opp["_score"] = conf_score * (1 + savings / 60)
        uniq.append(opp)
    uniq.sort(key=lambda x: x["_score"], reverse=True)
    for opp in uniq:
        opp.pop("_score", None)
    return uniq


# ═════════════════════════════════════════════════════════════════════
# Phase 3: 架构设计
# ═════════════════════════════════════════════════════════════════════
ARCHITECTURE_SCHEMA = (
    '{"overview": "针对本项目的方案概览", '
    '"components": [{"name": "组件名", "tech": "技术选型", "description": "职责"}], '
    '"tech_stack": {"分类": ["技术1", "技术2"]}, '
    '"milestones": [{"phase": "阶段", "name": "名称", "duration": "周期", "deliverable": "交付物"}], '
    '"risks": [{"risk": "风险", "mitigation": "缓解方案"}]}'
)


def _architecture_messages(real_opps: List[Dict], cfg) -> Tuple[str, str]:
    system = (
        "你是 FDE 解决方案架构师。基于自动化机会清单，为本项目设计**针对性**技术方案。"
        "组件、技术栈、里程碑、风险都要贴合客户行业与具体机会，不要套用通用模板。"
    )
    opp_text = "\n".join(
        f"- [{o['id']}|{o['layer']}] {o['description']}（置信{o['confidence']}/难度{o['difficulty']}）"
        for o in real_opps
    )
    user = (
        f"客户行业：{cfg.client_industry or '未提供'}\n"
        f"LLM 推理后端：{cfg.llm_provider}/{cfg.llm_model}\n\n"
        f"自动化机会清单：\n{opp_text}\n\n"
        "请输出方案概览、3-5 个组件、技术栈、里程碑、3-5 条风险及缓解。"
    )
    return system, user


def _architecture_base(opportunities: List[Dict]) -> Tuple[Dict, List[Dict], List[Dict]]:
    real = [o for o in opportunities if o.get("source") != PENDING]
    top_lines = [o for o in real if o.get("layer") == "line"][:3]
    base = {
        "design_date": datetime.now().strftime("%Y-%m-%d"),
        "priority_lines": [
            {"id": o["id"], "description": o["description"],
             "weekly_savings": o.get("estimated_weekly_savings_minutes"),
             "savings_basis": o.get("savings_basis", ""),
             "difficulty": o.get("difficulty", "med")}
            for o in top_lines
        ],
        "architecture_mermaid": _generate_architecture_mermaid(top_lines),
    }
    return base, real, top_lines


def _architecture_brief(ctx: Dict, cfg) -> Dict:
    opportunities = ctx.get("opportunities", []) or []
    real = [o for o in opportunities if o.get("source") != PENDING]
    if not real:
        return _brief_blocked("上游无有效自动化机会（Phase 2 未完成或降级），无法设计架构。")
    system, user = _architecture_messages(real, cfg)
    return _brief_ready(system, user, ARCHITECTURE_SCHEMA)


def normalize_architecture(raw, ctx: Dict, cfg) -> Dict:
    base, real, _ = _architecture_base(ctx.get("opportunities", []) or [])
    data = raw if isinstance(raw, dict) else {}
    base.update({
        "overview": data.get("overview", ""),
        "components": data.get("components", []),
        "tech_stack": data.get("tech_stack", {}),
        "milestones": data.get("milestones", []),
        "risks": data.get("risks", []),
        "status": "completed",
    })
    return base


def run_architecture(opportunities, cfg, llm: Optional[LLMClient] = None) -> Dict:
    """Phase 3（内部 LLM 模式）：机会清单 → 技术方案。"""
    base, real, _ = _architecture_base(opportunities)

    def _pending(reason):
        base.update({"overview": f"⚠️ {PENDING}：{reason}", "components": [],
                     "tech_stack": {}, "milestones": [], "risks": [], "status": PENDING})
        return base

    if not real:
        return _pending("上游无有效自动化机会，无法设计架构。")
    client = _resolve_llm(cfg, llm)
    if not client.available:
        return _pending("未配置 LLM，无法生成针对性技术方案。已列出优先链路供人工/Agent 设计。")

    system, user = _architecture_messages(real, cfg)
    try:
        data = client.complete_json(system, user, ARCHITECTURE_SCHEMA)
    except LLMUnavailable as e:
        return _pending(f"LLM 调用失败：{e}")
    return normalize_architecture(data, {"opportunities": opportunities}, cfg)


def _generate_architecture_mermaid(top_lines: List[Dict]) -> str:
    lines = [
        "```mermaid", "graph TD",
        '    subgraph "🏢 客户现场"',
        "        A[现有系统] --> B[行为采集]",
        "        C[人工流程] --> B", "    end",
        '    subgraph "⚙️ FDE 引擎层"',
        "        B --> D[发现层<br>点/线/面分析]",
        "        D --> E[差距评估]", "        E --> F[方案架构]",
        "        F --> G[原型构建]", "    end",
        '    subgraph "📦 交付输出"',
        "        G --> H[自动化 Skill]", "        G --> I[交付证据包]", "    end",
        "    H --> A",
    ]
    for i, o in enumerate(top_lines):
        safe_id = str(o.get("id", f"L{i}")).replace("-", "_")
        desc = (o.get("description", "") or "")[:20]
        lines.append(f'        E -->|"{i + 1}. {desc}"| L{safe_id}[{o.get("id", "")}]')
        lines.append(f"        L{safe_id} --> F")
    lines.append("```")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# Phase 4: 原型构建
# ═════════════════════════════════════════════════════════════════════
PROTOTYPE_SCHEMA = (
    '{"core_workflow": [{"step": 1, "action": "动作", "tool": "工具"}], '
    '"files": [{"path": "相对路径", "purpose": "用途"}], '
    '"test_cases": [{"id": "T1", "description": "测试点", "expected": "预期"}], '
    '"setup_guide": "环境准备的 markdown 文本"}'
)


def _proto_dir(cfg) -> str:
    return os.path.expanduser(f"~/Desktop/fde-prototype-{cfg.engagement_id}/")


def _prototype_messages(architecture: Dict, cfg, proto_dir: str) -> Tuple[str, str]:
    system = (
        "你是 FDE 原型工程师。基于技术架构，给出**可直接动手**的最小原型计划："
        "核心工作流步骤、需要创建的文件清单（贴合本项目，不要套通用文件名）、测试用例、环境准备步骤。"
    )
    comp_text = "\n".join(
        f"- {c.get('name', '')}：{c.get('tech', '')} — {c.get('description', '')}"
        for c in architecture.get("components", [])
    )
    user = (
        f"项目：{cfg.project_name or cfg.engagement_id}\n"
        f"方案概览：{architecture.get('overview', '')}\n"
        f"组件：\n{comp_text}\n\n原型目录：{proto_dir}\n请给出原型计划。"
    )
    return system, user


def _prototype_brief(ctx: Dict, cfg) -> Dict:
    architecture = ctx.get("architecture", {}) or {}
    if architecture.get("status") == PENDING or not architecture.get("components"):
        return _brief_blocked("上游架构未完成（Phase 3 未完成或降级），无法生成原型计划。")
    system, user = _prototype_messages(architecture, cfg, _proto_dir(cfg))
    return _brief_ready(system, user, PROTOTYPE_SCHEMA)


def normalize_prototype(raw, ctx: Dict, cfg) -> Dict:
    data = raw if isinstance(raw, dict) else {}
    return {
        "prototype_dir": _proto_dir(cfg),
        "generated_at": datetime.now().isoformat(),
        "core_workflow": data.get("core_workflow", []),
        "files": data.get("files", []),
        "test_cases": data.get("test_cases", []),
        "setup_guide": data.get("setup_guide", ""),
        "status": "completed",
    }


def run_prototype(architecture, cfg, llm: Optional[LLMClient] = None) -> Dict:
    """Phase 4（内部 LLM 模式）：架构 → 最小原型计划。"""
    base = {"prototype_dir": _proto_dir(cfg), "generated_at": datetime.now().isoformat()}

    def _pending(reason):
        base.update({"core_workflow": [], "files": [], "test_cases": [],
                     "setup_guide": f"⚠️ {PENDING}：{reason}", "status": PENDING})
        return base

    if architecture.get("status") == PENDING or not architecture.get("components"):
        return _pending("上游架构未完成，无法生成原型计划。")
    client = _resolve_llm(cfg, llm)
    if not client.available:
        return _pending("未配置 LLM，无法生成原型计划（可用 Brief 模式由调用方 Agent 设计）。")

    system, user = _prototype_messages(architecture, cfg, _proto_dir(cfg))
    try:
        data = client.complete_json(system, user, PROTOTYPE_SCHEMA)
    except LLMUnavailable as e:
        return _pending(f"LLM 调用失败：{e}")
    return normalize_prototype(data, {"architecture": architecture}, cfg)


# ═════════════════════════════════════════════════════════════════════
# Phase 5: 交付交接
# ═════════════════════════════════════════════════════════════════════
HANDOFF_SCHEMA = (
    '{"summary": "项目执行摘要", '
    '"handoff_docs": [{"title": "文档标题", "content": "内容摘要"}], '
    '"next_steps": ["后续建议1", "后续建议2"]}'
)


def _handoff_messages(state, cfg) -> Tuple[str, str]:
    system = (
        "你是 FDE 交付负责人。基于项目阶段完成情况，撰写交付证据包的执行摘要、"
        "交接文档清单（系统架构/部署/运维/常见问题/关键决策记录等贴合本项目的内容）、后续建议。"
    )
    phase_text = "\n".join(f"- Phase {p.phase} {p.name}：{p.status}" for p in state.phases)
    user = (
        f"客户：{cfg.client_name}（{cfg.client_industry}）\n项目：{cfg.project_name}\n"
        f"阶段完成情况：\n{phase_text}\n\n请输出交付摘要、交接文档清单、后续建议。"
    )
    return system, user


def _handoff_brief(ctx: Dict, cfg) -> Dict:
    state = ctx.get("state")
    if state is None:
        return _brief_blocked("缺少项目状态，无法生成交接包。")
    system, user = _handoff_messages(state, cfg)
    return _brief_ready(system, user, HANDOFF_SCHEMA)


def _handoff_skeleton(state, cfg) -> Dict:
    return {
        "engagement_id": cfg.engagement_id,
        "client": f"{cfg.client_name} ({cfg.client_industry})",
        "project": cfg.project_name,
        "delivery_date": datetime.now().strftime("%Y-%m-%d"),
        "metrics": _build_metrics(state),
    }


def normalize_handoff(raw, state, cfg) -> Dict:
    pkg = _handoff_skeleton(state, cfg)
    data = raw if isinstance(raw, dict) else {}
    completed = pkg["metrics"]["completed_phases"]
    pkg.update({
        "summary": data.get("summary") or
        f"FDE 项目于 {state.created_at} 启动，{completed}/5 阶段完成。",
        "handoff_docs": data.get("handoff_docs", []),
        "next_steps": data.get("next_steps", []),
        "status": "completed",
    })
    return pkg


def run_handoff(state, cfg, llm: Optional[LLMClient] = None) -> Dict:
    """Phase 5（内部 LLM 模式）：汇总全阶段产出 → 交付证据包。"""
    pkg = _handoff_skeleton(state, cfg)
    completed = pkg["metrics"]["completed_phases"]
    fallback_summary = (
        f"FDE 项目于 {state.created_at} 启动，{completed}/5 阶段完成。交付包内含各阶段结构化文档。"
    )
    client = _resolve_llm(cfg, llm)

    if not client.available:
        pkg.update({
            "summary": fallback_summary + "（注：未配置 LLM，交接文档为通用占位，建议补充。）",
            "handoff_docs": [
                {"title": "系统架构", "content": f"⚠️ {PENDING}：参见 Phase 3 架构文档。"},
                {"title": "部署与运维", "content": f"⚠️ {PENDING}：需配置 LLM 或人工补充。"},
            ],
            "next_steps": [f"✅ {completed}/5 阶段已生成交付物",
                           "→ 配置 LLM 或用 Brief 模式由调用方 Agent 补充针对性交接文档",
                           "→ 建议 2 周后回访评估自动化采纳率"],
            "status": PENDING,
        })
        return pkg

    system, user = _handoff_messages(state, cfg)
    try:
        data = client.complete_json(system, user, HANDOFF_SCHEMA)
    except LLMUnavailable as e:
        pkg.update({"summary": fallback_summary + f"（LLM 调用失败：{e}）",
                    "handoff_docs": [{"title": "交接文档", "content": f"⚠️ {PENDING}：{e}"}],
                    "next_steps": [f"✅ {completed}/5 阶段已生成交付物"], "status": PENDING})
        return pkg
    return normalize_handoff(data, state, cfg)


def _build_metrics(state) -> Dict:
    completed_phases = [p for p in state.phases if p.status == "completed"]
    return {"total_phases": 5, "completed_phases": len(completed_phases),
            "deliverable_count": len([p for p in completed_phases if p.deliverable_path])}
