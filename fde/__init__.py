"""
FDE — Frontline Deployment Engineering (前线部署工程)

将企业 AI 落地需求拆解为 5 阶段全生命周期流水线：
  Phase 1: Field Discovery (现场发现)
  Phase 2: Gap Assessment (差距评估)
  Phase 3: Solution Architecture (架构设计)
  Phase 4: Prototype Plan (原型计划)
  Phase 5: Handoff (交付交接)

每个阶段输出结构化 Markdown 交付物，最终打包为交付证据包。

用法:
    fde new --client "客户名" --industry "行业" --project "项目名"
    fde run <engagement_id> --phase 1
    fde run-all <engagement_id> --input "客户描述"
    fde list
    fde status <engagement_id>
    fde deliverable <engagement_id> --phase 3

也可通过 MCP 工具被 Agent 调用（详见 docs/integration-guide.md）
"""

__version__ = "1.0.0"
__author__ = "Muyunye"
__license__ = "MIT"
