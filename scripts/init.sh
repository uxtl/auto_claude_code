#!/bin/bash
# 一键初始化脚手架到目标项目
# 用法：bash init.sh /path/to/target/project

set -e

TARGET=${1:?"用法: bash init.sh /path/to/target/project"}

if [ ! -d "$TARGET" ]; then
    echo "错误：目标目录 $TARGET 不存在"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/../templates"

cp "$TEMPLATE_DIR/CLAUDE.md" "$TARGET/CLAUDE.md"
cp "$TEMPLATE_DIR/PROGRESS.md" "$TARGET/PROGRESS.md"
mkdir -p "$TARGET/tasks" "$TARGET/tasks/done"

echo "脚手架已初始化到 $TARGET"
echo "  - CLAUDE.md 已复制（请修改 {project_name}）"
echo "  - PROGRESS.md 已复制"
echo "  - tasks/ 目录已创建"
