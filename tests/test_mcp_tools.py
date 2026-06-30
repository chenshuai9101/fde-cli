"""
FDE MCP 工具测试

测试 MCP 工具入参模型和工具定义结构。
"""
import os
import sys
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fde.mcp_tools import (
    CreateEngagementInput,
    ListEngagementsInput,
    RunPhaseInput,
    RunAllInput,
    GetStatusInput,
    GetDeliverableInput,
)
from pydantic import ValidationError


class TestCreateEngagementInput(unittest.TestCase):
    def test_all_fields_optional(self):
        params = CreateEngagementInput()
        self.assertEqual(params.client_name, "")
        self.assertEqual(params.description, "")
        self.assertEqual(params.llm_provider, "none")

    def test_with_values(self):
        params = CreateEngagementInput(client_name="测试客户",
                                        client_industry="金融",
                                        project_name="风控系统",
                                        description="客户需要AI风控")
        self.assertEqual(params.client_name, "测试客户")

    def test_extra_fields_rejected(self):
        with self.assertRaises(ValidationError):
            CreateEngagementInput(client_name="测试", unknown_field="x")


class TestListEngagementsInput(unittest.TestCase):
    def test_default_limit(self):
        params = ListEngagementsInput()
        self.assertEqual(params.limit, 10)

    def test_limit_range(self):
        with self.assertRaises(ValidationError):
            ListEngagementsInput(limit=0)
        with self.assertRaises(ValidationError):
            ListEngagementsInput(limit=51)


class TestRunPhaseInput(unittest.TestCase):
    def test_required_fields(self):
        with self.assertRaises(ValidationError):
            RunPhaseInput()

    def test_valid_input(self):
        params = RunPhaseInput(engagement_id="test-001", phase=3)
        self.assertEqual(params.engagement_id, "test-001")
        self.assertEqual(params.phase, 3)

    def test_phase_range(self):
        with self.assertRaises(ValidationError):
            RunPhaseInput(engagement_id="test", phase=0)
        with self.assertRaises(ValidationError):
            RunPhaseInput(engagement_id="test", phase=6)


class TestRunAllInput(unittest.TestCase):
    def test_engagement_id_required(self):
        with self.assertRaises(ValidationError):
            RunAllInput()

    def test_valid(self):
        params = RunAllInput(engagement_id="test-all", client_input="描述")
        self.assertEqual(params.client_input, "描述")


class TestGetStatusInput(unittest.TestCase):
    def test_engagement_id_required(self):
        with self.assertRaises(ValidationError):
            GetStatusInput()


class TestGetDeliverableInput(unittest.TestCase):
    def test_valid(self):
        params = GetDeliverableInput(engagement_id="test", phase=3)
        self.assertEqual(params.phase, 3)

    def test_phase_range(self):
        with self.assertRaises(ValidationError):
            GetDeliverableInput(engagement_id="test", phase=0)


if __name__ == "__main__":
    unittest.main()
