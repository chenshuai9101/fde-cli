"""
FDE 执行引擎

编排五阶段流水线，管理状态持久化，提供完整的 CLI 和 API 入口。
"""
import os
import json
import uuid
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict

from fde import phases
from fde.llm import build_llm_client
from fde.deliverable import (
    build_discovery_doc,
    build_assessment_doc,
    build_architecture_doc,
    build_prototype_doc,
    build_handoff_package,
)


# ── 常量 ─────────────────────────────────────────────────────────────
FDE_OUTPUT_BASE = os.path.expanduser("~/Desktop/fde-engagements/")


# ── 数据类型 ──────────────────────────────────────────────────────────
@dataclass
class FDEConfig:
    """FDE 项目配置"""
    engagement_id: str = ""
    client_name: str = ""
    client_industry: str = ""
    project_name: str = ""

    # LLM 配置（改造核心：智能由真实 LLM 产生）
    #   llm_provider="none" 时进入诚实降级模式，输出标注"待分析"而非假数据。
    llm_provider: str = "none"
    llm_model: str = "qwen2.5:14b"
    llm_endpoint: str = "http://localhost:11434"
    llm_api_key: str = ""

    # 输出
    output_dir: str = ""

    def __post_init__(self):
        if not self.engagement_id:
            self.engagement_id = datetime.now().strftime("eng-%Y%m%d-%H%M%S")
        if not self.output_dir:
            self.output_dir = os.path.join(FDE_OUTPUT_BASE, self.engagement_id)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FDEPhase:
    """单个阶段的执行状态"""
    phase: int              # 1-5
    name: str
    status: str = "pending"  # pending / running / completed / failed
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    deliverable_path: Optional[str] = None
    error: Optional[str] = None


@dataclass
class FDEState:
    """FDE 项目完整状态"""
    config: FDEConfig
    phases: List[FDEPhase] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        if not self.phases:
            self.phases = [
                FDEPhase(phase=1, name="现场发现", status="pending"),
                FDEPhase(phase=2, name="差距评估", status="pending"),
                FDEPhase(phase=3, name="架构设计", status="pending"),
                FDEPhase(phase=4, name="原型计划", status="pending"),
                FDEPhase(phase=5, name="交付交接", status="pending"),
            ]

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "phases": [asdict(p) for p in self.phases],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def save(self, path: str = None) -> str:
        """持久化状态到 JSON"""
        path = path or os.path.join(self.config.output_dir, "fde_state.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load(cls, path: str) -> "FDEState":
        """从 JSON 恢复状态"""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        config = FDEConfig(**data["config"])
        state = cls(config=config)
        state.phases = [FDEPhase(**p) for p in data["phases"]]
        state.created_at = data["created_at"]
        state.updated_at = data["updated_at"]
        return state


# ── 引擎 ──────────────────────────────────────────────────────────────
class FDEEngine:
    """FDE 执行引擎 — 编排五阶段流水线"""

    def __init__(self, config: FDEConfig, llm=None):
        self.config = config
        self.state = FDEState(config=config)
        # 注入 LLM 客户端；未配置时为 NullClient（诚实降级）
        self.llm = llm if llm is not None else build_llm_client(config)

    # ── 状态管理 ───────────────────────────────────────────────────
    def get_phase(self, phase: int) -> FDEPhase:
        if phase < 1 or phase > 5:
            raise ValueError(f"阶段号必须为 1-5，收到: {phase}")
        return self.state.phases[phase - 1]

    def _set_phase_running(self, phase: int):
        p = self.get_phase(phase)
        p.status = "running"
        p.started_at = datetime.now().isoformat()
        self.state.updated_at = datetime.now().isoformat()
        self._save_state()

    def _set_phase_completed(self, phase: int, deliverable_path: str = ""):
        p = self.get_phase(phase)
        p.status = "completed"
        p.completed_at = datetime.now().isoformat()
        if deliverable_path:
            p.deliverable_path = deliverable_path
        self.state.updated_at = datetime.now().isoformat()
        self._save_state()

    def _set_phase_failed(self, phase: int, error: str):
        p = self.get_phase(phase)
        p.status = "failed"
        p.error = error
        self.state.updated_at = datetime.now().isoformat()
        self._save_state()

    def _save_state(self):
        self.config = self.state.config
        os.makedirs(self.config.output_dir, exist_ok=True)
        self.state.save()

    def save_state(self):
        """公开保存接口"""
        self._save_state()

    # ── 公开 API ──────────────────────────────────────────────────
    def get_status_text(self) -> str:
        """返回人类可读的状态概览"""
        lines = [
            f"📋 FDE 项目: {self.config.project_name or self.config.engagement_id}",
            f"   客户: {self.config.client_name} ({self.config.client_industry})",
            f"   输出目录: {self.config.output_dir}",
            "",
            "阶段状态:",
        ]
        for p in self.state.phases:
            icon = {"pending": "⏳", "running": "🔄", "completed": "✅", "failed": "❌"}
            line = f"  {icon.get(p.status, '❓')} Phase {p.phase}: {p.name} — {p.status}"
            if p.deliverable_path:
                line += f"\n     📄 {p.deliverable_path}"
            if p.error:
                line += f"\n     ⚠️  {p.error}"
            lines.append(line)
        return "\n".join(lines)

    def run_phase(self, phase: int, context: dict = None) -> dict:
        """执行指定阶段（内部 LLM 模式）。

        引擎用自己配置的 LLM 完成分析。适合人类 CLI / 弱 Agent。
        强 Agent 想自己分析时，改用 get_phase_brief + submit_phase_result。
        """
        ctx = self._collect_context(phase, context or {})
        self._set_phase_running(phase)
        try:
            output = self._analyze(phase, ctx)
            doc_path = self._render(phase, output, ctx)
            self._persist_phase_output(phase, output)
            self._set_phase_completed(phase, doc_path)
            return {phases.PHASE_OUTPUT_KEY[phase]: output, "deliverable_path": doc_path}
        except Exception as e:
            self._set_phase_failed(phase, str(e))
            raise

    def get_phase_brief(self, phase: int, context: dict = None) -> dict:
        """Brief 模式①：返回该阶段的"分析任务包"，供调用方 Agent 自行分析。

        引擎只给出 prompt + 上游上下文 + 期望 schema，不调用任何 LLM。
        调用方 Agent（通常比内置小模型更强）据此分析后，调 submit_phase_result 回填。
        """
        if phase < 1 or phase > 5:
            raise ValueError(f"无效阶段: {phase}，仅支持 1-5")
        ctx = self._collect_context(phase, context or {})
        brief = phases.build_brief(phase, ctx, self.config)
        brief["engagement_id"] = self.config.engagement_id
        return brief

    def submit_phase_result(self, phase: int, result, context: dict = None) -> dict:
        """Brief 模式②：接收调用方 Agent 的分析结果，归一、渲染、持久化。

        Args:
            phase: 1-5
            result: 调用方 Agent 按 brief.schema 产出的 JSON（list 或 dict）
        """
        if phase < 1 or phase > 5:
            raise ValueError(f"无效阶段: {phase}，仅支持 1-5")
        ctx = self._collect_context(phase, context or {})
        self._set_phase_running(phase)
        try:
            output = phases.normalize_result(
                phase, result, ctx, self.config, source=phases.SOURCE_AGENT
            )
            doc_path = self._render(phase, output, ctx)
            self._persist_phase_output(phase, output)
            self._set_phase_completed(phase, doc_path)
            return {phases.PHASE_OUTPUT_KEY[phase]: output, "deliverable_path": doc_path}
        except Exception as e:
            self._set_phase_failed(phase, str(e))
            raise

    def run_all(self, context: dict = None) -> dict:
        """顺序执行全部五阶段（内部 LLM 模式），自动将上阶段产出注入下阶段。"""
        context = context or {}
        results = {}
        for i in range(1, 6):
            user_ctx = dict(context.get(f"phase_{i}", {}))
            results[f"phase_{i}"] = self.run_phase(i, user_ctx)
        return results

    # ── 分析 / 渲染分派 ─────────────────────────────────────────────
    def _analyze(self, phase: int, ctx: dict):
        """内部 LLM 模式下，按阶段调用对应分析函数。"""
        if phase == 1:
            return phases.run_discovery(ctx.get("client_input", ""), self.config, self.llm)
        if phase == 2:
            return phases.run_assessment(
                ctx.get("pain_points", []), self.config,
                ctx.get("time_audit_opportunities"), self.llm)
        if phase == 3:
            return phases.run_architecture(ctx.get("opportunities", []), self.config, self.llm)
        if phase == 4:
            return phases.run_prototype(ctx.get("architecture", {}), self.config, self.llm)
        if phase == 5:
            return phases.run_handoff(self.state, self.config, self.llm)
        raise ValueError(f"无效阶段: {phase}")

    def _render(self, phase: int, output, ctx: dict) -> str:
        """把阶段产出渲染为 .md 交付物，返回路径。"""
        if phase == 1:
            return build_discovery_doc(self.config, output, ctx)
        if phase == 2:
            return build_assessment_doc(self.config, output, ctx)
        if phase == 3:
            return build_architecture_doc(self.config, output, ctx)
        if phase == 4:
            return build_prototype_doc(self.config, output, ctx)
        if phase == 5:
            return build_handoff_package(self.config, self.state, output)
        raise ValueError(f"无效阶段: {phase}")

    # ── 上下文收集与产出持久化 ───────────────────────────────────────
    def _collect_context(self, phase: int, context: dict) -> dict:
        """汇集该阶段所需上下文：用户传入优先，缺失项从持久化的上游产出补齐。"""
        ctx = dict(context)
        if phase == 1:
            ctx.setdefault("client_input", self._load_client_input())
        elif phase == 2:
            ctx.setdefault("pain_points", self._load_phase_output(1).get("pain_points", []))
        elif phase == 3:
            ctx.setdefault("opportunities", self._load_phase_output(2).get("opportunities", []))
        elif phase == 4:
            ctx.setdefault("architecture", self._load_phase_output(3).get("architecture", {}))
        elif phase == 5:
            ctx["state"] = self.state
        return ctx

    def _phase_output_path(self, phase: int) -> str:
        return os.path.join(self.config.output_dir, f".phase_{phase}_output.json")

    def _persist_phase_output(self, phase: int, output):
        """把阶段结构化产出落盘，供后续阶段的 brief / 分析读取。"""
        os.makedirs(self.config.output_dir, exist_ok=True)
        with open(self._phase_output_path(phase), "w", encoding="utf-8") as f:
            json.dump({phases.PHASE_OUTPUT_KEY[phase]: output}, f, ensure_ascii=False, indent=2)

    def _load_phase_output(self, phase: int) -> dict:
        path = self._phase_output_path(phase)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _load_client_input(self) -> str:
        """读取创建项目时持久化的客户输入（.client_input.txt）。"""
        path = os.path.join(self.config.output_dir, ".client_input.txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
        return ""


# ── 快捷入口 ──────────────────────────────────────────────────────────
def create_engagement(
    client_name: str = "",
    client_industry: str = "",
    project_name: str = "",
    **kwargs,
) -> FDEEngine:
    """快速创建 FDE 项目引擎，自动持久化状态"""
    config = FDEConfig(
        client_name=client_name,
        client_industry=client_industry,
        project_name=project_name,
        **kwargs,
    )
    eng = FDEEngine(config)
    eng._save_state()  # 创建时即持久化
    return eng


def load_engagement(path: str) -> FDEEngine:
    """从状态文件恢复 FDE 项目"""
    state = FDEState.load(path)
    engine = FDEEngine(state.config)
    engine.state = state
    return engine
