"""
FDE 阶段逻辑单元测试（LLM 驱动版）

改造后测试两类行为：
  1. 真实分析路径：注入 FakeLLM，验证阶段正确消费 LLM 的结构化输出。
  2. 诚实降级路径：无 LLM（NullClient）时，输出标注"待分析"且绝不编造数据。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fde.phases import (
    run_discovery,
    run_assessment,
    run_architecture,
    run_prototype,
    run_handoff,
    PENDING,
)
from fde.llm import LLMClient, NullClient
from fde.engine import FDEConfig, FDEState


def make_cfg(**kwargs):
    kwargs.setdefault("engagement_id", "test-phases")
    kwargs.setdefault("client_name", "测试客户")
    kwargs.setdefault("client_industry", "医疗")
    kwargs.setdefault("project_name", "测试项目")
    kwargs.setdefault("output_dir", "/tmp/fde-test-phases")
    kwargs.setdefault("llm_provider", "none")  # 默认诚实降级，避免网络
    return FDEConfig(**kwargs)


class FakeLLM(LLMClient):
    """可编程的假 LLM：按调用顺序返回预设的 JSON。"""

    def __init__(self, responses):
        self.available = True
        self._responses = list(responses)
        self.calls = []

    def complete_json(self, system, user, schema_hint=None):
        self.calls.append({"system": system, "user": user})
        return self._responses.pop(0)


# ════════════════════════════════════════════════════════════════════════
# Phase 1: 现场发现
# ════════════════════════════════════════════════════════════════════════
class TestRunDiscovery(unittest.TestCase):

    def test_empty_input_is_pending_not_fabricated(self):
        result = run_discovery("", make_cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], PENDING)

    def test_no_llm_is_pending(self):
        result = run_discovery("医生每天花2小时录病历", make_cfg(), NullClient())
        self.assertTrue(all(p["source"] == PENDING for p in result))

    def test_llm_extracts_real_pain_points(self):
        llm = FakeLLM([[
            {"id": "P1", "category": "效率", "description": "录病历耗时",
             "frequency": 5, "impact": 4, "evidence": "每天2小时"},
        ]])
        result = run_discovery("医生每天花2小时录病历", make_cfg(), llm)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "llm")
        self.assertEqual(result[0]["description"], "录病历耗时")
        self.assertEqual(result[0]["frequency"], 5)

    def test_llm_scores_are_clamped(self):
        llm = FakeLLM([[{"id": "P1", "category": "效率", "description": "x",
                         "frequency": 99, "impact": -3}]])
        result = run_discovery("一些描述", make_cfg(), llm)
        self.assertEqual(result[0]["frequency"], 5)
        self.assertEqual(result[0]["impact"], 1)


# ════════════════════════════════════════════════════════════════════════
# Phase 2: 差距评估
# ════════════════════════════════════════════════════════════════════════
class TestRunAssessment(unittest.TestCase):

    def test_time_audit_only_no_llm_needed(self):
        ta = [{"id": "L-01", "layer": "line", "description": "病历填写流程",
               "confidence": "high", "automation_difficulty": "low",
               "estimated_weekly_savings_minutes": 350}]
        result = run_assessment([], make_cfg(), ta, NullClient())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "L-01")
        self.assertEqual(result[0]["source"], "time-audit")
        self.assertEqual(result[0]["roi_source"], "time-audit")

    def test_pain_points_without_llm_is_pending(self):
        pain = [{"id": "P1", "category": "效率", "description": "x",
                 "frequency": 4, "impact": 4, "source": "llm"}]
        result = run_assessment(pain, make_cfg(), None, NullClient())
        self.assertTrue(any(o["source"] == PENDING for o in result))

    def test_llm_maps_pain_to_opportunities(self):
        pain = [{"id": "P1", "category": "效率", "description": "录病历耗时",
                 "frequency": 5, "impact": 4, "source": "llm"}]
        llm = FakeLLM([[
            {"id": "L-01", "layer": "line", "description": "病历模板自动填充",
             "confidence": "high", "difficulty": "med",
             "estimated_weekly_savings_minutes": 300,
             "savings_basis": "假设15名医生每天省20分钟", "suggestion": "构建模板引擎"},
        ]])
        result = run_assessment(pain, make_cfg(), None, llm)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "llm")
        self.assertEqual(result[0]["estimated_weekly_savings_minutes"], 300)
        self.assertIn("假设", result[0]["savings_basis"])
        self.assertEqual(result[0]["roi_source"], "llm-assumption")

    def test_client_assumption_roi_source_is_preserved(self):
        pain = [{"id": "P1", "category": "效率", "description": "录病历耗时",
                 "frequency": 5, "impact": 4, "source": "llm"}]
        llm = FakeLLM([[
            {"id": "L-01", "layer": "line", "description": "病历模板自动填充",
             "confidence": "high", "difficulty": "med",
             "estimated_weekly_savings_minutes": 300,
             "savings_basis": "客户提供：15名医生每天各省20分钟"},
        ]])
        result = run_assessment(pain, make_cfg(), None, llm)
        self.assertEqual(result[0]["roi_source"], "client-assumption")

    def test_savings_can_be_none_when_no_data(self):
        pain = [{"id": "P1", "category": "数据", "description": "数据分散",
                 "frequency": 3, "impact": 3, "source": "llm"}]
        llm = FakeLLM([[
            {"id": "L-01", "layer": "line", "description": "统一面板",
             "confidence": "med", "difficulty": "med",
             "estimated_weekly_savings_minutes": None, "savings_basis": "需客户数据"},
        ]])
        result = run_assessment(pain, make_cfg(), None, llm)
        self.assertIsNone(result[0]["estimated_weekly_savings_minutes"])
        self.assertEqual(result[0]["savings_basis"], "需客户数据")
        self.assertEqual(result[0]["roi_source"], "needs-data")

    def test_dedupe(self):
        ta = [
            {"id": "L-01", "layer": "line", "description": "重复流程", "confidence": "high"},
            {"id": "L-01", "layer": "line", "description": "重复流程", "confidence": "med"},
        ]
        result = run_assessment([], make_cfg(), ta, NullClient())
        self.assertEqual(len(result), 1)


# ════════════════════════════════════════════════════════════════════════
# Phase 3: 架构设计
# ════════════════════════════════════════════════════════════════════════
class TestRunArchitecture(unittest.TestCase):

    def test_no_opportunities_is_pending(self):
        arch = run_architecture([], make_cfg(), NullClient())
        self.assertEqual(arch["status"], PENDING)
        self.assertEqual(arch["components"], [])

    def test_no_llm_is_pending_but_keeps_priority_lines(self):
        opps = [{"id": "L-01", "layer": "line", "description": "自动化流程",
                 "confidence": "high", "difficulty": "low",
                 "estimated_weekly_savings_minutes": 300, "source": "time-audit"}]
        arch = run_architecture(opps, make_cfg(), NullClient())
        self.assertEqual(arch["status"], PENDING)
        self.assertEqual(len(arch["priority_lines"]), 1)
        self.assertTrue(arch["architecture_mermaid"].startswith("```mermaid"))

    def test_llm_generates_architecture(self):
        opps = [{"id": "L-01", "layer": "line", "description": "自动化流程",
                 "confidence": "high", "difficulty": "low",
                 "estimated_weekly_savings_minutes": 300, "source": "llm"}]
        llm = FakeLLM([{
            "overview": "针对医疗的方案",
            "components": [{"name": "采集层", "tech": "HIS适配器", "description": "采集病历"}],
            "tech_stack": {"后端": ["Python"]},
            "milestones": [{"phase": "P1", "name": "采集", "duration": "1周", "deliverable": "适配器"}],
            "risks": [{"risk": "隐私", "mitigation": "本地模型"}],
        }])
        arch = run_architecture(opps, make_cfg(), llm)
        self.assertEqual(arch["status"], "completed")
        self.assertEqual(arch["overview"], "针对医疗的方案")
        self.assertEqual(len(arch["components"]), 1)


# ════════════════════════════════════════════════════════════════════════
# Phase 4: 原型计划
# ════════════════════════════════════════════════════════════════════════
class TestRunPrototype(unittest.TestCase):

    def test_pending_architecture_yields_pending_prototype(self):
        arch = {"status": PENDING, "components": []}
        proto = run_prototype(arch, make_cfg(), NullClient())
        self.assertEqual(proto["status"], PENDING)
        self.assertIn("prototype_dir", proto)

    def test_llm_generates_prototype(self):
        arch = {"status": "completed",
                "overview": "方案", "components": [{"name": "x", "tech": "y", "description": "z"}]}
        llm = FakeLLM([{
            "core_workflow": [{"step": 1, "action": "采集", "tool": "适配器"}],
            "files": [{"path": "agent.py", "purpose": "主入口"}],
            "test_cases": [{"id": "T1", "description": "测试", "expected": "通过"}],
            "setup_guide": "pip install ...",
        }])
        proto = run_prototype(arch, make_cfg(), llm)
        self.assertEqual(proto["status"], "completed")
        self.assertEqual(len(proto["files"]), 1)


# ════════════════════════════════════════════════════════════════════════
# Phase 5: 交付交接
# ════════════════════════════════════════════════════════════════════════
class TestRunHandoff(unittest.TestCase):

    def test_metrics_are_always_real(self):
        cfg = make_cfg(engagement_id="test-handoff")
        state = FDEState(config=cfg)
        state.phases[0].status = "completed"
        state.phases[0].deliverable_path = "/tmp/d1.md"
        pkg = run_handoff(state, cfg, NullClient())
        self.assertEqual(pkg["metrics"]["completed_phases"], 1)
        self.assertEqual(pkg["metrics"]["deliverable_count"], 1)

    def test_no_llm_is_pending(self):
        cfg = make_cfg()
        state = FDEState(config=cfg)
        pkg = run_handoff(state, cfg, NullClient())
        self.assertEqual(pkg["status"], PENDING)

    def test_llm_generates_handoff(self):
        cfg = make_cfg()
        state = FDEState(config=cfg)
        llm = FakeLLM([{
            "summary": "项目顺利交付",
            "handoff_docs": [{"title": "架构", "content": "见文档"}],
            "next_steps": ["回访"],
        }])
        pkg = run_handoff(state, cfg, llm)
        self.assertEqual(pkg["status"], "completed")
        self.assertEqual(pkg["summary"], "项目顺利交付")


if __name__ == "__main__":
    unittest.main()
