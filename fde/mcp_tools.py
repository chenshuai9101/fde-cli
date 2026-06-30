"""
FDE MCP 工具扩展

定义 FDE 专属的 MCP 工具，供 Agent（Claude Desktop / Cursor / OpenClaw）直连调用。
作为 MCP Server 的热插拔扩展。

工具清单：

  fde_create_engagement     → 创建 FDE 项目
  fde_list_engagements      → 列出本地 FDE 项目
  fde_get_engagement_status → 查看项目状态
  fde_run_phase             → 执行指定阶段（引擎内部 LLM 分析）
  fde_run_all               → 一键跑全流程（引擎内部 LLM 分析）
  fde_get_deliverable       → 获取阶段交付物内容
  fde_get_phase_brief       → 【Brief 模式】取分析任务包，由调用方 Agent 自行分析
  fde_submit_phase_result   → 【Brief 模式】回填分析结果，生成交付物
"""
import os
import json
import glob
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

# 延迟导入（避免运行时依赖）
_FDE_ENGINE = None


def _get_engine():
    global _FDE_ENGINE
    if _FDE_ENGINE is None:
        from fde.engine import create_engagement, load_engagement
        _FDE_ENGINE = {"create": create_engagement, "load": load_engagement}
    return _FDE_ENGINE


FDE_STATE_DIR = os.path.expanduser("~/Desktop/fde-engagements/")


# ── 入参模型 ─────────────────────────────────────────────────────────
class CreateEngagementInput(BaseModel):
    """create_engagement 入参"""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    client_name: str = Field(default="", description="客户名称")
    client_industry: str = Field(default="", description="客户所属行业")
    project_name: str = Field(default="", description="项目名称")
    description: str = Field(default="", description="项目描述/客户输入的背景")
    # LLM 配置（决定智能由谁产生；none=诚实降级，输出标注"待分析"而非假数据）
    llm_provider: str = Field(default="none", description="LLM 供应商：none / ollama / openai")
    llm_model: str = Field(default="qwen2.5:14b", description="模型名，如 qwen2.5:14b / gpt-4o-mini")
    llm_endpoint: str = Field(default="", description="OpenAI 兼容端点；留空按 provider 取默认")
    llm_api_key: str = Field(default="", description="API Key；留空回退环境变量 FDE_LLM_API_KEY/OPENAI_API_KEY")


class ListEngagementsInput(BaseModel):
    """list_engagements 入参"""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    limit: int = Field(default=10, description="最多返回几个项目", ge=1, le=50)


class RunPhaseInput(BaseModel):
    """run_phase 入参"""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    engagement_id: str = Field(description="FDE 项目 ID (目录名)")
    phase: int = Field(description="阶段号 1-5", ge=1, le=5)
    context: str = Field(default="{}", description="阶段上下文 JSON 字符串")


class RunAllInput(BaseModel):
    """run_all 入参"""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    engagement_id: str = Field(description="FDE 项目 ID (目录名)")
    client_input: str = Field(default="", description="客户输入（Phase 1 用）")


class GetStatusInput(BaseModel):
    """get_engagement_status 入参"""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    engagement_id: str = Field(description="FDE 项目 ID (目录名)")


class GetDeliverableInput(BaseModel):
    """get_deliverable 入参"""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    engagement_id: str = Field(description="FDE 项目 ID")
    phase: int = Field(description="阶段号 1-5", ge=1, le=5)


class GetPhaseBriefInput(BaseModel):
    """get_phase_brief 入参"""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    engagement_id: str = Field(description="FDE 项目 ID")
    phase: int = Field(description="阶段号 1-5", ge=1, le=5)
    context: str = Field(default="{}", description="可选上下文 JSON，如 time_audit_opportunities")


class SubmitPhaseResultInput(BaseModel):
    """submit_phase_result 入参"""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    engagement_id: str = Field(description="FDE 项目 ID")
    phase: int = Field(description="阶段号 1-5", ge=1, le=5)
    result: str = Field(description="调用方 Agent 按 brief.schema 产出的分析结果 JSON 字符串")
    context: str = Field(default="{}", description="可选上下文 JSON，如 time_audit_opportunities")


# ── 工具定义 ─────────────────────────────────────────────────────────
def init_mcp_tools(mcp):
    """注册所有 FDE 工具到 MCP server 实例。

    用法：
        from fde.mcp_tools import init_mcp_tools
        init_mcp_tools(mcp)   # 在你的 MCP server 创建后调用
    """

    @mcp.tool(
        name="fde_create_engagement",
        annotations={
            "title": "创建 FDE 项目",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
        },
    )
    def create_engagement(params: CreateEngagementInput) -> str:
        """创建新的 FDE（Forward Deployed Engineering）项目。

        FDE 项目将客户的企业 AI 落地需求拆解为 5 阶段：
          1. 现场发现 → 2. 差距评估 → 3. 架构设计 → 4. 原型计划 → 5. 交付交接

        Args:
            params (CreateEngagementInput):
                - client_name (str): 客户名称
                - client_industry (str): 客户行业（如"医疗/制造/金融"）
                - project_name (str): 项目名称
                - description (str): 客户输入的背景/需求/痛点

        Returns:
            str: 创建成功的项目概要（JSON 格式）
        """
        try:
            eng = _get_engine()["create"](
                client_name=params.client_name,
                client_industry=params.client_industry,
                project_name=params.project_name,
                llm_provider=params.llm_provider,
                llm_model=params.llm_model,
                llm_endpoint=params.llm_endpoint,
                llm_api_key=params.llm_api_key,
            )
            if params.description:
                ctx_path = os.path.join(eng.config.output_dir, ".client_input.txt")
                os.makedirs(eng.config.output_dir, exist_ok=True)
                with open(ctx_path, "w", encoding="utf-8") as f:
                    f.write(params.description)

            return json.dumps({
                "engagement_id": eng.config.engagement_id,
                "output_dir": eng.config.output_dir,
                "status": "created",
                "llm": f"{eng.config.llm_provider}/{eng.config.llm_model}"
                       + ("" if eng.llm.available else "（不可用→诚实降级，输出将标注待分析）"),
                "phases": [f"Phase {p.phase}: {p.name}" for p in eng.state.phases],
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Error: 创建失败 — {e}"

    @mcp.tool(
        name="fde_list_engagements",
        annotations={
            "title": "列出 FDE 项目",
            "readOnlyHint": True,
            "destructiveHint": False,
        },
    )
    def list_engagements(params: ListEngagementsInput) -> str:
        """列出本机已有的 FDE 项目。

        Returns:
            str: 项目列表（按最后修改时间倒序）
        """
        engagements = []
        pattern = os.path.join(FDE_STATE_DIR, "*/fde_state.json")
        for state_path in sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True):
            try:
                with open(state_path, encoding="utf-8") as f:
                    data = json.load(f)
                cfg = data.get("config", {})
                phases = data.get("phases", [])
                completed = sum(1 for p in phases if p.get("status") == "completed")
                engagements.append({
                    "id": cfg.get("engagement_id", os.path.basename(os.path.dirname(state_path))),
                    "client": f"{cfg.get('client_name', '?')} ({cfg.get('client_industry', '?')})",
                    "project": cfg.get("project_name", "未命名"),
                    "phases": f"{completed}/5",
                    "updated": data.get("updated_at", ""),
                })
            except Exception:
                continue

        return json.dumps({
            "count": len(engagements[:params.limit]),
            "engagements": engagements[:params.limit],
        }, ensure_ascii=False, indent=2)

    @mcp.tool(
        name="fde_get_engagement_status",
        annotations={
            "title": "查看 FDE 项目状态",
            "readOnlyHint": True,
        },
    )
    def get_engagement_status(params: GetStatusInput) -> str:
        """查看指定 FDE 项目的当前状态。

        Args:
            params (GetStatusInput):
                - engagement_id (str): FDE 项目 ID

        Returns:
            str: 项目当前状态概览
        """
        try:
            state_path = os.path.join(FDE_STATE_DIR, params.engagement_id, "fde_state.json")
            if not os.path.exists(state_path):
                return f"Error: 项目 '{params.engagement_id}' 不存在"
            from fde.engine import load_engagement
            eng = load_engagement(state_path)
            return eng.get_status_text()
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool(
        name="fde_run_phase",
        annotations={
            "title": "执行 FDE 阶段",
            "readOnlyHint": False,
            "destructiveHint": False,
        },
    )
    def run_phase(params: RunPhaseInput) -> str:
        """执行 FDE 项目的指定阶段。

        Args:
            params (RunPhaseInput):
                - engagement_id (str): FDE 项目 ID
                - phase (int): 阶段号 1(现场发现) / 2(差距评估) / 3(架构设计) / 4(原型计划) / 5(交付交接)
                - context (str, optional): 阶段上下文的 JSON 字符串

        Returns:
            str: 执行结果
        """
        try:
            state_path = os.path.join(FDE_STATE_DIR, params.engagement_id, "fde_state.json")
            if not os.path.exists(state_path):
                return f"Error: 项目 '{params.engagement_id}' 不存在"
            from fde.engine import load_engagement
            eng = load_engagement(state_path)

            ctx = json.loads(params.context) if params.context.strip() else {}
            result = eng.run_phase(params.phase, ctx)
            return json.dumps(result, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            return f"Error: Phase {params.phase} 执行失败 — {e}"

    @mcp.tool(
        name="fde_run_all",
        annotations={
            "title": "一键执行全流程",
            "readOnlyHint": False,
            "destructiveHint": False,
        },
    )
    def run_all(params: RunAllInput) -> str:
        """一键执行 FDE 全流程（Phase 1-5 顺序执行）。

        Args:
            params (RunAllInput):
                - engagement_id (str): FDE 项目 ID
                - client_input (str, optional): 客户输入描述

        Returns:
            str: 全流程执行结果摘要
        """
        try:
            state_path = os.path.join(FDE_STATE_DIR, params.engagement_id, "fde_state.json")
            if not os.path.exists(state_path):
                return f"Error: 项目 '{params.engagement_id}' 不存在"
            from fde.engine import load_engagement
            eng = load_engagement(state_path)

            context = {
                "phase_1": {"client_input": params.client_input},
            }
            results = eng.run_all(context)
            return json.dumps({
                "status": "completed",
                "output_dir": eng.config.output_dir,
                "phases": {
                    k: {
                        "status": "completed" if v.get("deliverable_path") else "failed",
                        "deliverable": v.get("deliverable_path", ""),
                    }
                    for k, v in results.items()
                },
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Error: 全流程执行失败 — {e}"

    @mcp.tool(
        name="fde_get_deliverable",
        annotations={
            "title": "获取 FDE 阶段交付物",
            "readOnlyHint": True,
        },
    )
    def get_deliverable(params: GetDeliverableInput) -> str:
        """读取 FDE 项目某阶段的交付物内容。

        Args:
            params (GetDeliverableInput):
                - engagement_id (str): FDE 项目 ID
                - phase (int): 阶段号 1-5

        Returns:
            str: 交付物 Markdown 内容
        """
        try:
            phase_docs = {1: "01", 2: "02", 3: "03", 4: "04", 5: "05"}
            prefix = phase_docs.get(params.phase, "01")
            pattern = os.path.join(FDE_STATE_DIR, params.engagement_id, f"{prefix}*.md")
            files = glob.glob(pattern)
            if not files:
                return f"Error: 项目 '{params.engagement_id}' Phase {params.phase} 交付物不存在"

            with open(files[0], encoding="utf-8") as f:
                content = f.read()
            return content[:5000] + ("\n\n...（内容较长，已截断）" if len(content) > 5000 else "")
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool(
        name="fde_get_phase_brief",
        annotations={
            "title": "获取 FDE 阶段分析任务包（Brief 模式）",
            "readOnlyHint": True,
        },
    )
    def get_phase_brief(params: GetPhaseBriefInput) -> str:
        """【Brief 模式①】获取某阶段的"分析任务包"，由你（调用方 Agent）亲自分析。

        与 fde_run_phase 的区别：
          - fde_run_phase：引擎用它**内部配置的 LLM**（可能是本地小模型）做分析。
          - 本工具：引擎只返回 prompt + 上游上下文 + 期望 JSON schema，**不调用任何 LLM**。
            你（通常比内置模型更强、且掌握与客户的完整对话）据此自行分析，
            再用 fde_submit_phase_result 回填。引擎负责编排、校验、渲染、持久化。

        返回字段：
          - ready (bool): 上游是否就绪。false 时看 reason。
          - system / user / schema: 你做分析所需的完整提示与期望输出结构。
          - submit_with: 回填用的工具名。

        Returns:
            str: 分析任务包（JSON）
        """
        try:
            state_path = os.path.join(FDE_STATE_DIR, params.engagement_id, "fde_state.json")
            if not os.path.exists(state_path):
                return f"Error: 项目 '{params.engagement_id}' 不存在"
            from fde.engine import load_engagement
            eng = load_engagement(state_path)
            ctx = json.loads(params.context) if params.context.strip() else {}
            brief = eng.get_phase_brief(params.phase, ctx)
            return json.dumps(brief, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            return f"Error: 获取 Phase {params.phase} 任务包失败 — {e}"

    @mcp.tool(
        name="fde_submit_phase_result",
        annotations={
            "title": "回填 FDE 阶段分析结果（Brief 模式）",
            "readOnlyHint": False,
            "destructiveHint": False,
        },
    )
    def submit_phase_result(params: SubmitPhaseResultInput) -> str:
        """【Brief 模式②】把你的分析结果回填给引擎，生成交付物并推进状态。

        result 必须是符合 fde_get_phase_brief 返回的 schema 的 JSON 字符串。
        引擎会归一化你的结果（与内部 LLM 模式同一套逻辑）、融合 time-audit 真实机会、
        渲染 .md 交付物、持久化阶段产出供下一阶段使用。

        Args:
            params (SubmitPhaseResultInput):
                - engagement_id, phase
                - result (str): 你的分析结果 JSON
                - context (str): 可选，如 time_audit_opportunities

        Returns:
            str: 归一后的阶段产出 + 交付物路径（JSON）
        """
        try:
            state_path = os.path.join(FDE_STATE_DIR, params.engagement_id, "fde_state.json")
            if not os.path.exists(state_path):
                return f"Error: 项目 '{params.engagement_id}' 不存在"
            from fde.engine import load_engagement
            eng = load_engagement(state_path)
            try:
                result = json.loads(params.result) if params.result.strip() else []
            except json.JSONDecodeError as e:
                return f"Error: result 不是合法 JSON — {e}"
            ctx = json.loads(params.context) if params.context.strip() else {}
            out = eng.submit_phase_result(params.phase, result, ctx)
            return json.dumps(out, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            return f"Error: 回填 Phase {params.phase} 失败 — {e}"

    return mcp
