#!/bin/bash

# ============================================
# QwenTradeAI 项目打包脚本
# 用途：打包项目代码，排除不需要的文件
# 使用方法：./package.sh
# ============================================

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 项目信息
PROJECT_NAME="QwenTradeAI"
PACKAGE_NAME="${PROJECT_NAME}.tar.gz"

# 获取脚本所在目录（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}${PROJECT_NAME} 项目打包脚本${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 检查是否在项目根目录
if [ ! -f "requirements.txt" ] || [ ! -d "app" ]; then
    echo -e "${RED}错误：请在项目根目录运行此脚本${NC}"
    exit 1
fi

# 创建临时打包目录（不创建子目录，直接打包文件）
TEMP_DIR=$(mktemp -d)
PACKAGE_DIR="${TEMP_DIR}"

echo -e "${YELLOW}正在创建打包目录...${NC}"
echo "临时目录: $PACKAGE_DIR"
echo ""

# 需要打包的文件和目录
echo -e "${YELLOW}正在复制文件...${NC}"

# 1. 复制 app 目录（核心代码）
if [ -d "app" ]; then
    echo "  - 复制 app/ 目录"
    cp -r app "$PACKAGE_DIR/"
    # 清理 __pycache__ 和 .pyc 文件
    find "$PACKAGE_DIR/app" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$PACKAGE_DIR/app" -name "*.pyc" -delete 2>/dev/null || true
    find "$PACKAGE_DIR/app" -name "*.pyo" -delete 2>/dev/null || true
fi

# 2. 复制 database 目录（SQL文件）
if [ -d "database" ]; then
    echo "  - 复制 database/ 目录"
    cp -r database "$PACKAGE_DIR/"
fi

# 3. docs 目录不打包（文档文件，部署时不需要）
# if [ -d "docs" ]; then
#     echo "  - 复制 docs/ 目录"
#     cp -r docs "$PACKAGE_DIR/"
# fi

# 4. 复制 requirements.txt
if [ -f "requirements.txt" ]; then
    echo "  - 复制 requirements.txt"
    cp requirements.txt "$PACKAGE_DIR/"
fi

# 5. 复制 README.md（如果存在）
if [ -f "README.md" ]; then
    echo "  - 复制 README.md"
    cp README.md "$PACKAGE_DIR/"
fi

# 6. 不复制测试和文档文件
# test_cases.md - 测试用例文档，部署时不需要
# verify_database.py - 验证脚本，部署时不需要
# GIT_PUSH_GUIDE.md - Git推送指南，部署时不需要

# 7. 复制 .gitignore（用于参考）
if [ -f ".gitignore" ]; then
    echo "  - 复制 .gitignore"
    cp .gitignore "$PACKAGE_DIR/"
fi

# 排除的文件和目录（已在复制时排除）
echo ""
echo -e "${YELLOW}已排除的文件/目录：${NC}"
echo "  - venv/ (虚拟环境)"
echo "  - logs/ (日志文件)"
echo "  - .env (环境变量文件)"
echo "  - __pycache__/ (Python缓存)"
echo "  - *.pyc (编译文件)"
echo "  - .git/ (Git目录)"
echo "  - .DS_Store (系统文件)"
echo "  - tests/ (测试文件)"
echo "  - .cursor/ (IDE配置)"
echo "  - .btignore (宝塔配置)"
echo "  - docs/ (项目文档)"
echo "  - test_cases.md (测试用例文档)"
echo "  - verify_database.py (验证脚本)"
echo "  - GIT_PUSH_GUIDE.md (Git推送指南)"
echo ""

# 创建打包信息文件
echo -e "${YELLOW}正在创建打包信息...${NC}"
cat > "$PACKAGE_DIR/PACKAGE_INFO.txt" << EOF
项目名称: ${PROJECT_NAME}
打包时间: $(date '+%Y-%m-%d %H:%M:%S')
打包说明: 
  - 包含所有源代码和配置文件
  - 已排除虚拟环境、日志、缓存等文件
  - 部署时请先安装依赖: pip install -r requirements.txt
  - 请根据实际情况配置 .env 文件
EOF
echo "  - 创建 PACKAGE_INFO.txt"

# 打包（直接打包文件，不包含目录名）
echo ""
echo -e "${YELLOW}正在打包...${NC}"
cd "$TEMP_DIR"
tar -czf "${SCRIPT_DIR}/${PACKAGE_NAME}" .
cd "$SCRIPT_DIR"

# 计算文件大小
PACKAGE_SIZE=$(du -h "$PACKAGE_NAME" | cut -f1)

# 清理临时目录
echo ""
echo -e "${YELLOW}正在清理临时文件...${NC}"
rm -rf "$TEMP_DIR"

# 显示结果
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}打包完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "打包文件: ${PACKAGE_NAME}"
echo "文件大小: ${PACKAGE_SIZE}"
echo "文件位置: $(pwd)/${PACKAGE_NAME}"
echo ""
echo -e "${YELLOW}打包内容：${NC}"
echo "  ✓ app/ - 应用代码"
echo "  ✓ database/ - 数据库SQL文件"
echo "  ✓ requirements.txt - Python依赖"
echo "  ✓ README.md - 项目说明（如果存在）"
echo "  ✓ .gitignore - Git忽略规则"
echo "  ✓ PACKAGE_INFO.txt - 打包信息"
echo ""
echo -e "${YELLOW}已排除：${NC}"
echo "  ✗ docs/ - 项目文档（部署时不需要）"
echo "  ✗ test_cases.md - 测试用例文档（部署时不需要）"
echo "  ✗ verify_database.py - 验证脚本（部署时不需要）"
echo ""
echo -e "${YELLOW}部署说明：${NC}"
echo "  1. 解压: tar -xzf ${PACKAGE_NAME}"
echo "  2. 安装依赖: cd ${PROJECT_NAME} && pip install -r requirements.txt"
echo "  3. 配置环境: 创建 .env 文件并配置数据库连接等信息"
echo "  4. 初始化数据库: 执行 database/all_tables.sql"
echo "  5. 启动服务: python -m app.main 或 uvicorn app.main:app"
echo ""

