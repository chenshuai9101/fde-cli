"""
FDE 端到端集成测试
"""
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fde.engine import (
    FDEConfig, FDEState, FDEEngine,
    create_engagement, load_engagement,
)
from fde.phases import (
    run_discovery, run_assessment,
    run_architecture, run_prototype, run_handoff,
)
from fde.deliverable import (
    build_discovery_doc, build_assessment_doc,
    build_architecture_doc, build_prototype_doc,
    build_handoff_package,
)
from fde.llm import LLMClient, NullClient


class FakeLLM(LLMClient):
    """按调用顺序返回预设 JSON 的假 LLM。"""

    def __init__(self, responses):
        self.available = True
        self._responses = list(responses)

    def complete_json(self, system, user, schema_hint=None):
        return self._responses.pop(0)


class FDEIntegrationBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_root = tempfile.mkdtemp(prefix="fde_integration_")
        cls.cfg = FDEConfig(
            engagement_id="integration-test",
            client_name="集成测试客户",
            client_industry="测试行业",
            project_name="集成测试项目",
            output_dir=os.path.join(cls.test_root, "output"),
            llm_provider="none",
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_root, ignore_errors=True)


class TestFullEngineFlow(FDEIntegrationBase):
    def test_create_engagement(self):
        eng = create_engagement(
            client_name="某医院", client_industry="医疗",
            project_name="病历录入优化",
            output_dir=os.path.join(self.test_root, "eng-flow"),
        )
        self.assertEqual(eng.config.client_name, "某医院")
        self.assertEqual(len(eng.state.phases), 5)
        state_path = os.path.join(eng.config.output_dir, "fde_state.json")
        self.assertTrue(os.path.exists(state_path))

    def test_save_and_recover(self):
        eng = create_engagement(client_name="恢复测试",
                                output_dir=os.path.join(self.test_root, "eng-recover"))
        eng._set_phase_running(1)
        eng._set_phase_completed(1, "/tmp/test.md")
        state_path = os.path.join(eng.config.output_dir, "fde_state.json")
        eng2 = load_engagement(state_path)
        self.assertEqual(eng2.get_phase(1).status, "completed")


class TestPhaseEndToEnd(FDEIntegrationBase):
    def setUp(self):
        self.cfg = FDEConfig(
            engagement_id="e2e-test",
            client_name="E2E客户", client_industry="金融",
            project_name="风控自动化",
            output_dir=os.path.join(self.test_root, "e2e"),
            llm_provider="none",
        )

    def test_p1_to_p2_data_flow(self):
        # 无 LLM 时痛点降级为"待分析"，但 time-audit 真实机会仍应进入清单
        pain_points = run_discovery("手动录入风控数据", self.cfg, NullClient())
        ta_opps = [{"id": "L-01", "layer": "line",
                     "description": "风控数据录入", "confidence": "high",
                     "automation_difficulty": "low",
                     "estimated_weekly_savings_minutes": 420}]
        opportunities = run_assessment(pain_points, self.cfg, ta_opps, NullClient())
        self.assertGreaterEqual(len(opportunities), 1)
        self.assertTrue(any(o["id"] == "L-01" for o in opportunities))

    def test_all_five_docs_generated(self):
        # 注入 FakeLLM 走完整真实分析路径
        discovery_llm = FakeLLM([[
            {"id": "P1", "category": "效率", "description": "产线数据记录耗时",
             "frequency": 4, "impact": 4, "evidence": "每班次记录"},
        ]])
        pain_points = run_discovery("产线数据记录耗时", self.cfg, discovery_llm)
        d1 = build_discovery_doc(self.cfg, pain_points, {"client_input": "产线数据记录"})

        opps = run_assessment(pain_points, self.cfg, [{
            "id": "L-01", "layer": "line", "description": "数据记录自动化",
            "confidence": "high", "automation_difficulty": "low",
            "estimated_weekly_savings_minutes": 600,
        }], NullClient())  # 用 time-audit 真实机会，无需 LLM
        d2 = build_assessment_doc(self.cfg, opps, {})

        arch_llm = FakeLLM([{
            "overview": "产线数据自动化方案",
            "components": [{"name": "采集", "tech": "PLC适配器", "description": "采集产线数据"}],
            "tech_stack": {"后端": ["Python"]},
            "milestones": [{"phase": "P1", "name": "采集", "duration": "1周", "deliverable": "适配器"}],
            "risks": [{"risk": "停机", "mitigation": "灰度"}],
        }])
        arch = run_architecture(opps, self.cfg, arch_llm)
        d3 = build_architecture_doc(self.cfg, arch, {})

        proto_llm = FakeLLM([{
            "core_workflow": [{"step": 1, "action": "采集", "tool": "适配器"}],
            "files": [{"path": "agent.py", "purpose": "主入口"}],
            "test_cases": [{"id": "T1", "description": "采集", "expected": "成功"}],
            "setup_guide": "pip install ...",
        }])
        proto = run_prototype(arch, self.cfg, proto_llm)
        d4 = build_prototype_doc(self.cfg, proto, {})

        state = FDEState(config=self.cfg)
        for i in range(5):
            state.phases[i].status = "completed"
            state.phases[i].deliverable_path = [d1, d2, d3, d4, "/tmp/p"][i]
        pkg = run_handoff(state, self.cfg, NullClient())
        d5 = build_handoff_package(self.cfg, state, pkg)

        for i, doc in enumerate([d1, d2, d3, d4, d5], 1):
            self.assertTrue(os.path.exists(doc), f"Phase {i} not found")

        index_path = os.path.join(self.cfg.output_dir, "README.md")
        self.assertTrue(os.path.exists(index_path))

        contents = []
        for doc in [d1, d2, d3, d4, d5]:
            with open(doc, encoding="utf-8") as f:
                contents.append(f.read())
        self.assertIn("现场发现", contents[0])
        self.assertIn("差距评估", contents[1])
        self.assertIn("架构设计", contents[2])
        self.assertIn("原型计划", contents[3])
        self.assertIn("交付证据包", contents[4])


if __name__ == "__main__":
    unittest.main(verbosity=2)
