"""
FDE 交付物生成器测试
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fde.deliverable import (
    build_discovery_doc,
    build_assessment_doc,
    build_architecture_doc,
    build_prototype_doc,
    build_handoff_package,
    _ensure_output_dir,
)
from fde.engine import FDEConfig, FDEState
from fde.phases import (
    run_discovery,
    run_assessment,
    run_architecture,
    run_prototype,
    run_handoff,
)


def make_cfg(**kwargs):
    kwargs.setdefault("engagement_id", "deliverable-test")
    kwargs.setdefault("client_name", "某诊所")
    kwargs.setdefault("client_industry", "医疗")
    kwargs.setdefault("project_name", "病历AI测试")
    kwargs.setdefault("output_dir", tempfile.mkdtemp())
    kwargs.setdefault("llm_provider", "none")  # 诚实降级，避免网络
    return FDEConfig(**kwargs)


class TestBuildDiscoveryDoc(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        self.pain_points = [
            {"id": "P1", "category": "效率", "description": "病历重复填写",
             "frequency": 5, "impact": 4, "details": "每天3-5次"},
        ]

    def test_file_created(self):
        path = build_discovery_doc(self.cfg, self.pain_points, {})
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith("01-fde-discovery.md"))

    def test_content_contains_project_name(self):
        path = build_discovery_doc(self.cfg, self.pain_points, {})
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("病历AI测试", content)
        self.assertIn("某诊所", content)

    def test_client_input_included(self):
        path = build_discovery_doc(self.cfg, self.pain_points,
                                   {"client_input": "客户描述文本"})
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("客户描述文本", content)

    def test_phase0_diagnostic_sections_rendered(self):
        path = build_discovery_doc(self.cfg, self.pain_points,
                                   {"client_input": "客户说想做AI客服"})
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Phase 0 痛点诊断准入门槛", content)
        self.assertIn("三轮追问协议", content)
        self.assertIn("候选项目证据卡模板", content)
        self.assertIn("Phase 0-A 无描述痛点发现模式", content)
        self.assertIn("AI/自动化适配判断", content)
        self.assertIn("缺口", content)

    def test_phase0a_observation_mode_for_missing_description(self):
        path = build_discovery_doc(self.cfg, self.pain_points, {"client_input": ""})
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("建议启用：客户没有提供痛点描述", content)
        self.assertIn("行为时间审计", content)
        self.assertIn("文件与目录扫描", content)
        self.assertIn("观察模式候选痛点卡", content)
        self.assertIn("需要用户确认", content)

    def test_phase0a_observation_mode_for_unclear_description(self):
        path = build_discovery_doc(self.cfg, self.pain_points,
                                   {"client_input": "客户说不清具体痛点"})
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("建议启用：当前描述不足以定位真实痛点", content)

    def test_phase0_marks_quantified_input_as_signal(self):
        path = build_discovery_doc(
            self.cfg,
            self.pain_points,
            {"client_input": "医生每天录入系统3次，每次20分钟，容易出错，有HIS截图样本，验收标准是准确率95%"},
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("| 频率与耗时 | 已提供线索 |", content)
        self.assertIn("| 系统与数据 | 已提供线索 |", content)
        self.assertIn("| 样本证据 | 已提供线索 |", content)

    def test_empty_pain_points(self):
        path = build_discovery_doc(self.cfg, [], {})
        self.assertTrue(os.path.exists(path))


class TestBuildAssessmentDoc(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        self.opportunities = [
            {"id": "L-01", "layer": "line", "description": "病历模板填写",
             "confidence": "high", "difficulty": "low",
             "estimated_weekly_savings_minutes": 350, "source": "time-audit"},
        ]

    def test_file_created(self):
        path = build_assessment_doc(self.cfg, self.opportunities, {})
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith("02-fde-assessment.md"))

    def test_content_has_opportunities(self):
        path = build_assessment_doc(self.cfg, self.opportunities, {})
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("L-01", content)
        self.assertIn("350分钟", content)

    def test_empty_opportunities(self):
        path = build_assessment_doc(self.cfg, [], {})
        self.assertTrue(os.path.exists(path))


class TestBuildArchitectureDoc(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        self.arch = run_architecture([], self.cfg)

    def test_file_created(self):
        path = build_architecture_doc(self.cfg, self.arch, {})
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith("03-fde-architecture.md"))

    def test_content_has_mermaid(self):
        path = build_architecture_doc(self.cfg, self.arch, {})
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("mermaid", content)


class TestBuildPrototypeDoc(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        # 直接构造一个已完成的原型字典（模拟 LLM 产出），验证渲染
        self.proto = {
            "prototype_dir": "/tmp/fde-proto-test/",
            "status": "completed",
            "core_workflow": [{"step": 1, "action": "采集", "tool": "适配器"}],
            "files": [{"path": "agent.py", "purpose": "主入口"}],
            "test_cases": [
                {"id": "T1", "description": "输入提取", "expected": "≥3 痛点"},
                {"id": "T2", "description": "机会映射", "expected": "每条映射"},
                {"id": "T3", "description": "文档生成", "expected": "完整可读"},
            ],
            "setup_guide": "pip install fde-cli",
        }

    def test_file_created(self):
        path = build_prototype_doc(self.cfg, self.proto, {})
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith("04-fde-prototype.md"))

    def test_content_has_test_cases(self):
        path = build_prototype_doc(self.cfg, self.proto, {})
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("T1", content)
        self.assertIn("T2", content)
        self.assertIn("T3", content)


class TestBuildHandoffPackage(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        self.state = FDEState(config=self.cfg)
        for i in range(3):
            self.state.phases[i].status = "completed"
            self.state.phases[i].deliverable_path = f"/tmp/phase-{i+1}.md"
        self.package = run_handoff(self.state, self.cfg)

    def test_file_created(self):
        path = build_handoff_package(self.cfg, self.state, self.package)
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith("05-fde-handoff.md"))

    def test_index_file_created(self):
        path = build_handoff_package(self.cfg, self.state, self.package)
        index_path = os.path.join(os.path.dirname(path), "README.md")
        self.assertTrue(os.path.exists(index_path))
        with open(index_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("FDE 交付项目", content)


if __name__ == "__main__":
    unittest.main()
