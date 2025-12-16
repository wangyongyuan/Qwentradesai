#!/bin/bash

# GitHub 推送脚本
# 使用方法：./push_to_github.sh

cd "$(dirname "$0")"

echo "=========================================="
echo "推送代码到 GitHub"
echo "=========================================="
echo ""

# 检查是否已提交
if [ -z "$(git log --oneline -1 2>/dev/null)" ]; then
    echo "错误：没有提交记录，请先提交代码"
    exit 1
fi

echo "当前分支："
git branch --show-current
echo ""

echo "待推送的提交："
git log --oneline origin/main..HEAD 2>/dev/null || git log --oneline -5
echo ""

echo "=========================================="
echo "开始推送..."
echo "=========================================="
echo ""
echo "如果提示输入用户名和密码："
echo "  用户名：wangyongyuan"
echo "  密码：粘贴你的 GitHub Personal Access Token"
echo ""

# 推送代码
git push -u origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "✅ 推送成功！"
    echo "=========================================="
    echo ""
    echo "仓库地址：https://github.com/wangyongyuan/Qwentradesai"
else
    echo ""
    echo "=========================================="
    echo "❌ 推送失败"
    echo "=========================================="
    echo ""
    echo "可能的原因："
    echo "1. Token 权限不足（需要 repo 权限）"
    echo "2. Token 已过期或无效"
    echo "3. 仓库不存在或没有访问权限"
    echo ""
    echo "解决方法："
    echo "1. 检查 Token 权限：https://github.com/settings/tokens"
    echo "2. 重新生成 Token 并确保勾选 'repo' 权限"
    echo "3. 确认仓库地址正确：https://github.com/wangyongyuan/Qwentradesai"
fi

