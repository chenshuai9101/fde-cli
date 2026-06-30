FDE — Frontline Deployment Engineering 集成指南

## 集成架构

```
┌────────────────────────────────────────────┐
│              FDE Agent Skill                │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────┐  │
│  │Phase 0 │→│Phase 1 │→│Phase 2 │→│... │  │
│  │访谈补齐 │ │现场发现 │ │差距评估 │ │    │  │
│  └───┬────┘ └───┬────┘ └───┬────┘ └────┘  │
│      │          │          │               │
│      ▼          ▼          ▼               │
│  ┌──────────────────────────────┐          │
│  │      MCP 连接层               │          │
│  │  fde_create_engagement /     │          │
│  │  fde_run_phase / ...         │          │
│  └──────────────┬───────────────┘          │
│                 │                           │
└─────────────────┼───────────────────────────┘
                  │
         ┌────────▼────────┐
         │  time-audit 引擎 │ (可选)
         │  Screenpipe/Shell│
         └─────────────────┘
```

## 作为独立 CLI 使用

```bash
pip install fde-cli

fde new --client "某诊所" --industry "医疗" --project "病历自动化"
fde run-all eng-xxxx --input "..."
```

## 集成到 MCP Server

```python
from fde.mcp_tools import init_mcp_tools
mcp = FastMCP("my_mcp_server")
init_mcp_tools(mcp)
```

## 集成到 time-audit

将 fde 模块复制到 time-audit 项目中：

```bash
cp -r fde/ /path/to/time-audit/time_audit/fde/
```

然后在 `time_audit/main.py` 中添加 CLI 子命令，在 `mcp_server.py` 中注册 MCP 工具。

## 使用场景

### 场景 A：有时长审计数据

```bash
time-audit --days 14          # 先扫描
fde new --client "某公司"      # 建项目
fde run eng-xxxx --phase 2    # 融合数据评估
```

### 场景 B：新客户无数据

```bash
fde new --client "某药企" -i "医药" -p "销售培训AI"
fde run-all eng-xxxx --input "销售团队20人..."
```

### 场景 C：Agent 远程操作

```
用户 → Agent: "帮我评估一家诊所的AI落地需求"
Agent → MCP: fde_create_engagement(...) → fde_run_all(...)
Agent → 用户: "已完成，交付物在这里..."
```
