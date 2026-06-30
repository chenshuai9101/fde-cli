#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
# FDE CLI — 测试运行器
# ──────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════════════╗"
echo "║        FDE CLI — 测试套件                      ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "目录: $SCRIPT_DIR"
echo "Python: $(python3 --version)"
echo ""

# 确保必要依赖
MISSING=0
for mod in json tempfile unittest pydantic; do
    python3 -c "import $mod" 2>/dev/null || { echo "❌ 缺少模块: $mod"; MISSING=1; }
done
if [ "$MISSING" -eq 1 ]; then exit 1; fi

echo "所有依赖检查通过 ✅"
echo ""

HAS_PYTEST=0
python3 -c "import pytest" 2>/dev/null && HAS_PYTEST=1

echo "═══════════════════════════════════════════════════"
echo "  执行测试"
echo "═══════════════════════════════════════════════════"

TEST_EXIT=0
if [ "$HAS_PYTEST" -eq 1 ]; then
    python3 -m pytest tests/ -v --tb=short 2>&1
    TEST_EXIT=$?
else
    python3 -m unittest discover -s tests -p "test_*.py" -v 2>&1
    TEST_EXIT=$?
fi

echo ""
if [ "$TEST_EXIT" -eq 0 ]; then
    echo "🎉 全部测试通过！"
else
    echo "⚠️  有测试失败 (exit code: $TEST_EXIT)"
fi

exit $TEST_EXIT
