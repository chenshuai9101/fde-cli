"""
FDE Brief 模式测试

验证"引擎只给任务包、调用方 Agent 自己分析、再回填"的闭环：
  build_brief / normalize_result（phases 层）
  get_phase_brief / submit_phase_result（engine 层，含跨阶段持久化）
"""
import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fde import phases
from fde.phases import build_brief, normalize_result, PENDING, SOURCE_AGENT
from fde.engine import FDEConfig, FDEEngine, create_engagement, load_engagement


def make_cfg(**kwargs):
    kwargs.setdefault("client_name", "某诊所")
    kwargs.setdefault("client_industry", "医疗")
    kwargs.setdefault("project_name", "病历AI")
    kwargs.setdefault("llm_provider", "none")  # 关键：Brief 模式不应依赖引擎内 LLM
    return FDEConfig(**kwargs)


# ════════════════════════════════════════════════════════════════════════
# phases 层：build_brief / normalize_result
# ════════════════════════════════════════════════════════════════════════
class TestBuildBrief(unittest.TestCase):

    def test_discovery_brief_ready_with_input(self):
        brief = build_brief(1, {"client_input": "医生每天花2小时录病历"}, make_cfg())
        self.assertTrue(brief["ready"])
        self.assertIn("录病历", brief["user"])
        self.assertTrue(brief["schema"])
        self.assertEqual(brief["submit_with"], "fde_submit_phase_result")

    def test_discovery_brief_blocked_without_input(self):
        brief = build_brief(1, {"client_input": ""}, make_cfg())
        self.assertFalse(brief["ready"])
        self.assertIn("客户输入", brief["reason"])

    def test_assessment_brief_blocked_without_pain_points(self):
        brief = build_brief(2, {"pain_points": []}, make_cfg())
        self.assertFalse(brief["ready"])

    def test_architecture_brief_uses_opportunities(self):
        opps = [{"id": "L-01", "layer": "line", "description": "自动化流程",
                 "confidence": "high", "difficulty": "low", "source": "agent"}]
        brief = build_brief(3, {"opportunities": opps}, make_cfg())
        self.assertTrue(brief["ready"])
        self.assertIn("L-01", brief["user"])


class TestNormalizeResult(unittest.TestCase):

    def test_normalize_discovery_marks_agent_source(self):
        raw = [{"id": "P1", "category": "效率", "description": "录病历耗时",
                "frequency": 5, "impact": 4}]
        out = normalize_result(1, raw, {}, make_cfg())
        self.assertEqual(out[0]["source"], SOURCE_AGENT)
        self.assertEqual(out[0]["frequency"], 5)

    def test_normalize_assessment_merges_time_audit(self):
        agent_opps = [{"id": "L-02", "layer": "point", "description": "快捷输入",
                       "confidence": "med", "difficulty": "low",
                       "estimated_weekly_savings_minutes": None}]
        ctx = {"time_audit_opportunities": [
            {"id": "L-01", "layer": "line", "description": "病历填写",
             "confidence": "high", "estimated_weekly_savings_minutes": 350}]}
        out = normalize_result(2, agent_opps, ctx, make_cfg())
        ids = {o["id"] for o in out}
        self.assertEqual(ids, {"L-01", "L-02"})
        # time-audit 的 ROI 口径应被正确分级
        ta = next(o for o in out if o["id"] == "L-01")
        self.assertEqual(ta["roi_source"], "time-audit")


# ════════════════════════════════════════════════════════════════════════
# engine 层：完整 Brief 闭环 + 跨阶段持久化（全程 provider=none）
# ════════════════════════════════════════════════════════════════════════
class TestBriefModeEngine(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="fde_brief_")
        self.cfg = make_cfg(engagement_id="brief-e2e",
                            output_dir=os.path.join(self.root, "out"))
        self.eng = FDEEngine(self.cfg)
        self.eng.save_state()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_engine_has_no_llm(self):
        # Brief 模式的前提：即便引擎自身无可用 LLM，也能跑完整流程
        self.assertFalse(self.eng.llm.available)

    def test_full_brief_flow_without_engine_llm(self):
        # Phase 1：取 brief（需要客户输入）
        with open(os.path.join(self.cfg.output_dir, ".client_input.txt"), "w",
                  encoding="utf-8") as f:
            f.write("医生每天花2小时录病历，多系统切换")
        b1 = self.eng.get_phase_brief(1)
        self.assertTrue(b1["ready"])
        # 调用方 Agent“分析”后回填
        r1 = self.eng.submit_phase_result(1, [
            {"id": "P1", "category": "效率", "description": "录病历耗时",
             "frequency": 5, "impact": 4, "evidence": "每天2小时"}])
        self.assertTrue(os.path.exists(r1["deliverable_path"]))
        self.assertEqual(self.eng.get_phase(1).status, "completed")

        # Phase 2：brief 应自动读取 Phase 1 持久化的痛点（无需手动传）
        b2 = self.eng.get_phase_brief(2)
        self.assertTrue(b2["ready"])
        self.assertIn("录病历耗时", b2["user"])
        r2 = self.eng.submit_phase_result(2, [
            {"id": "L-01", "layer": "line", "description": "病历模板自动填充",
             "confidence": "high", "difficulty": "med",
             "estimated_weekly_savings_minutes": 300,
             "savings_basis": "假设每天省20分钟"}])
        self.assertTrue(os.path.exists(r2["deliverable_path"]))

        # Phase 3：brief 自动读取 Phase 2 机会
        b3 = self.eng.get_phase_brief(3)
        self.assertTrue(b3["ready"])
        self.assertIn("病历模板自动填充", b3["user"])
        r3 = self.eng.submit_phase_result(3, {
            "overview": "病历自动化方案",
            "components": [{"name": "模板引擎", "tech": "Python", "description": "填充"}],
            "tech_stack": {"后端": ["Python"]},
            "milestones": [{"phase": "P1", "name": "引擎", "duration": "1周", "deliverable": "原型"}],
            "risks": [{"risk": "隐私", "mitigation": "本地化"}]})
        self.assertTrue(os.path.exists(r3["deliverable_path"]))

        # Phase 4：brief 自动读取 Phase 3 架构
        b4 = self.eng.get_phase_brief(4)
        self.assertTrue(b4["ready"])
        r4 = self.eng.submit_phase_result(4, {
            "core_workflow": [{"step": 1, "action": "填充", "tool": "引擎"}],
            "files": [{"path": "engine.py", "purpose": "模板引擎"}],
            "test_cases": [{"id": "T1", "description": "填充", "expected": "成功"}],
            "setup_guide": "pip install ..."})
        self.assertTrue(os.path.exists(r4["deliverable_path"]))

        # Phase 5：交接
        r5 = self.eng.submit_phase_result(5, {
            "summary": "项目交付完成",
            "handoff_docs": [{"title": "架构", "content": "见文档"}],
            "next_steps": ["回访"]})
        self.assertTrue(os.path.exists(r5["deliverable_path"]))

        # 五阶段全部完成，且交付物索引存在
        self.assertEqual(sum(1 for p in self.eng.state.phases if p.status == "completed"), 5)
        self.assertTrue(os.path.exists(os.path.join(self.cfg.output_dir, "README.md")))

    def test_brief_persists_across_reload(self):
        # Phase 1 回填后，重新 load_engagement 仍能拿到 Phase 2 brief 的上游上下文
        with open(os.path.join(self.cfg.output_dir, ".client_input.txt"), "w",
                  encoding="utf-8") as f:
            f.write("重复手工录入")
        self.eng.submit_phase_result(1, [
            {"id": "P1", "category": "效率", "description": "手工录入耗时",
             "frequency": 4, "impact": 4}])
        state_path = os.path.join(self.cfg.output_dir, "fde_state.json")
        eng2 = load_engagement(state_path)
        b2 = eng2.get_phase_brief(2)
        self.assertTrue(b2["ready"])
        self.assertIn("手工录入耗时", b2["user"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
