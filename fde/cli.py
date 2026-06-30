"""
FDE CLI — 命令行入口

用法:
    fde new --client "客户名" --industry "行业" --project "项目名"
    fde status <engagement_id>
    fde list
    fde run <engagement_id> --phase 1
    fde run-all <engagement_id> --input "客户描述"
    fde deliverable <engagement_id> --phase 1
"""
import os
import sys
import json
import argparse
import glob
from datetime import datetime


def build_parser() -> argparse.ArgumentParser:
    """构建 FDE CLI 参数解析器"""
    p = argparse.ArgumentParser(
        prog="fde",
        description="FDE — Frontline Deployment Engineering (前线部署工程)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  fde new --client "某诊所" --industry "医疗" --project "病历AI"
  fde list
  fde run eng-20260101-120000 --phase 1
  fde run-all eng-20260101-120000 --input "医生每天花2小时录病历"
  fde deliverable eng-20260101-120000 --phase 3
        """,
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    # new
    new_p = sub.add_parser("new", help="创建新 FDE 项目")
    new_p.add_argument("--client", "-c", default="", help="客户名称")
    new_p.add_argument("--industry", "-i", default="", help="客户行业")
    new_p.add_argument("--project", "-p", default="", help="项目名称")
    new_p.add_argument("--input", "-d", default="", help="客户输入描述")
    new_p.add_argument("--output", "-o", default="", help="输出目录")
    new_p.add_argument("--llm-provider", default="none", help="LLM 供应商: none/ollama/openai")
    new_p.add_argument("--llm-model", default="qwen2.5:14b", help="模型名")
    new_p.add_argument("--llm-endpoint", default="", help="OpenAI 兼容端点(留空按 provider 取默认)")
    new_p.add_argument("--llm-api-key", default="", help="API Key(留空回退环境变量)")

    # list
    list_p = sub.add_parser("list", help="列出本地 FDE 项目")
    list_p.add_argument("--limit", "-l", type=int, default=10, help="最多列出几个")

    # status
    status_p = sub.add_parser("status", help="查看项目状态")
    status_p.add_argument("engagement_id", help="项目 ID")

    # run
    run_p = sub.add_parser("run", help="执行指定阶段")
    run_p.add_argument("engagement_id", help="项目 ID")
    run_p.add_argument("--phase", type=int, required=True, choices=range(1, 6), help="阶段 1-5")
    run_p.add_argument("--context", default="{}", help="阶段上下文 JSON")

    # run-all
    all_p = sub.add_parser("run-all", help="一键执行全流程")
    all_p.add_argument("engagement_id", help="项目 ID")
    all_p.add_argument("--input", default="", help="客户输入")

    # deliverable
    dlv_p = sub.add_parser("deliverable", aliases=["dlv"], help="查看阶段交付物")
    dlv_p.add_argument("engagement_id", help="项目 ID")
    dlv_p.add_argument("--phase", type=int, required=True, choices=range(1, 6), help="阶段 1-5")

    return p


def main():
    """FDE CLI 主入口"""
    parser = build_parser()
    args = parser.parse_args()

    from fde.engine import create_engagement, load_engagement, FDE_OUTPUT_BASE

    if args.cmd == "new":
        eng = create_engagement(
            client_name=args.client,
            client_industry=args.industry,
            project_name=args.project,
            output_dir=args.output if args.output else "",
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            llm_endpoint=args.llm_endpoint,
            llm_api_key=args.llm_api_key,
        )
        if args.input:
            ctx_path = os.path.join(eng.config.output_dir, ".client_input.txt")
            os.makedirs(eng.config.output_dir, exist_ok=True)
            with open(ctx_path, "w", encoding="utf-8") as f:
                f.write(args.input)

        print(f"✅ FDE 项目创建成功")
        print(f"   Engagement ID: {eng.config.engagement_id}")
        print(f"   输出目录: {eng.config.output_dir}")
        print(f"   状态: {eng.get_status_text()}")

    elif args.cmd == "list":
        pattern = os.path.join(FDE_OUTPUT_BASE, "*/fde_state.json")
        states = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

        if not states:
            print("📭 暂无 FDE 项目")
            return

        print(f"📋 本地 FDE 项目 ({len(states[:args.limit])}):")
        print(f"{'ID':26s} {'客户':26s} {'阶段':8s} {'更新于':20s}")
        print("-" * 80)
        for sp in states[:args.limit]:
            try:
                with open(sp, encoding="utf-8") as f:
                    data = json.load(f)
                cfg = data.get("config", {})
                phases = data.get("phases", [])
                completed = sum(1 for p in phases if p.get("status") == "completed")
                eid = cfg.get("engagement_id", os.path.basename(os.path.dirname(sp)))
                client = f"{cfg.get('client_name', '?')} ({cfg.get('client_industry', '?')})"
                updated = data.get("updated_at", "")[:16]
                print(f"{eid:26s} {client:26s} {completed}/5{'':4s} {updated:20s}")
            except Exception:
                continue

    elif args.cmd == "status":
        state_path = os.path.join(FDE_OUTPUT_BASE, args.engagement_id, "fde_state.json")
        if not os.path.exists(state_path):
            print(f"❌ 项目 '{args.engagement_id}' 不存在")
            return
        eng = load_engagement(state_path)
        print(eng.get_status_text())

    elif args.cmd == "run":
        state_path = os.path.join(FDE_OUTPUT_BASE, args.engagement_id, "fde_state.json")
        if not os.path.exists(state_path):
            print(f"❌ 项目 '{args.engagement_id}' 不存在")
            return
        eng = load_engagement(state_path)
        ctx = json.loads(args.context) if args.context.strip() else {}
        result = eng.run_phase(args.phase, ctx)
        print(f"✅ Phase {args.phase} 执行完成")
        print(f"   交付物: {result.get('deliverable_path', '—')}")

    elif args.cmd == "run-all":
        state_path = os.path.join(FDE_OUTPUT_BASE, args.engagement_id, "fde_state.json")
        if not os.path.exists(state_path):
            print(f"❌ 项目 '{args.engagement_id}' 不存在")
            return
        eng = load_engagement(state_path)
        context = {"phase_1": {"client_input": args.input}}
        results = eng.run_all(context)
        print(f"✅ FDE 全流程执行完成")
        print(f"   输出目录: {eng.config.output_dir}")
        for k, v in results.items():
            status = "✅" if v.get("deliverable_path") else "❌"
            print(f"   {status} {k}: {v.get('deliverable_path', '失败')}")

    elif args.cmd in ("deliverable", "dlv"):
        phase_docs = {1: "01", 2: "02", 3: "03", 4: "04", 5: "05"}
        prefix = phase_docs.get(args.phase, "01")
        pattern = os.path.join(FDE_OUTPUT_BASE, args.engagement_id, f"{prefix}*.md")
        files = glob.glob(pattern)
        if not files:
            print(f"❌ 项目 '{args.engagement_id}' Phase {args.phase} 交付物不存在")
            return
        with open(files[0], encoding="utf-8") as f:
            print(f.read())

    else:
        print(f"❌ 未知命令: {args.cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
