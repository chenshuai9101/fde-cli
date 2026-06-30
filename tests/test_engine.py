"""
FDE 引擎单元测试

测试核心数据类、状态管理、引擎编排。
"""
import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fde.engine import (
    FDEConfig,
    FDEState,
    FDEPhase,
    FDEEngine,
    create_engagement,
    load_engagement,
)


class TestFDEConfig(unittest.TestCase):
    def test_default_engagement_id(self):
        cfg = FDEConfig()
        self.assertTrue(cfg.engagement_id.startswith("eng-"))

    def test_custom_engagement_id(self):
        cfg = FDEConfig(engagement_id="my-test-001")
        self.assertEqual(cfg.engagement_id, "my-test-001")

    def test_default_output_dir(self):
        cfg = FDEConfig(engagement_id="test-001")
        expected = os.path.expanduser("~/Desktop/fde-engagements/test-001")
        self.assertEqual(cfg.output_dir, expected)

    def test_to_dict(self):
        cfg = FDEConfig(engagement_id="e-001", client_name="客户A")
        d = cfg.to_dict()
        self.assertEqual(d["client_name"], "客户A")


class TestFDEPhase(unittest.TestCase):
    def test_default_status(self):
        phase = FDEPhase(phase=1, name="测试")
        self.assertEqual(phase.status, "pending")

    def test_custom_status(self):
        phase = FDEPhase(phase=2, name="差距评估", status="completed",
                         deliverable_path="/tmp/r.md")
        self.assertEqual(phase.status, "completed")


class TestFDEState(unittest.TestCase):
    def setUp(self):
        self.config = FDEConfig(engagement_id="state-test", client_name="测试")
        self.state = FDEState(config=self.config)

    def test_initializes_5_phases(self):
        self.assertEqual(len(self.state.phases), 5)
        for i, p in enumerate(self.state.phases, 1):
            self.assertEqual(p.phase, i)
            self.assertEqual(p.status, "pending")

    def test_phase_names(self):
        expected = ["现场发现", "差距评估", "架构设计", "原型计划", "交付交接"]
        for i, name in enumerate(expected):
            self.assertEqual(self.state.phases[i].name, name)

    def test_save_and_load(self):
        self.state.phases[0].status = "completed"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
            self.state.save(path)
        loaded = FDEState.load(path)
        self.assertEqual(loaded.config.engagement_id, "state-test")
        self.assertEqual(loaded.phases[0].status, "completed")
        os.unlink(path)


class TestFDEEngine(unittest.TestCase):
    def setUp(self):
        self.config = FDEConfig(
            engagement_id="engine-test",
            client_name="测试",
            client_industry="医疗",
            project_name="FDE测试",
            output_dir=tempfile.mkdtemp(),
        )
        self.engine = FDEEngine(self.config)

    def test_engine_init(self):
        self.assertEqual(self.engine.config.engagement_id, "engine-test")
        self.assertEqual(len(self.engine.state.phases), 5)

    def test_get_phase(self):
        for i in range(1, 6):
            self.assertEqual(self.engine.get_phase(i).phase, i)

    def test_get_phase_out_of_range(self):
        with self.assertRaises(ValueError):
            self.engine.get_phase(0)
        with self.assertRaises(ValueError):
            self.engine.get_phase(6)

    def test_status_text(self):
        text = self.engine.get_status_text()
        self.assertIn("FDE测试", text)
        self.assertIn("pending", text)

    def test_phase_transition(self):
        self.engine._set_phase_running(1)
        self.assertEqual(self.engine.get_phase(1).status, "running")
        self.engine._set_phase_completed(1, "/tmp/d.md")
        self.assertEqual(self.engine.get_phase(1).status, "completed")
        self.engine._set_phase_failed(1, "err")
        self.assertEqual(self.engine.get_phase(1).status, "failed")


class TestCreateEngagement(unittest.TestCase):
    def test_create_basic(self):
        eng = create_engagement(client_name="客户B", client_industry="金融",
                                project_name="报表自动化")
        self.assertEqual(eng.config.client_name, "客户B")
        self.assertEqual(len(eng.state.phases), 5)


if __name__ == "__main__":
    unittest.main()
