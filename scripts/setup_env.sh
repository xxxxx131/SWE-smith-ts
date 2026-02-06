#!/bin/bash
#
# SWE-smith 环境配置脚本
# 
# 使用方法:
#   source scripts/setup_env.sh
#
# 这个脚本会帮助用户配置必要的环境变量
#

echo "=== SWE-smith 环境配置 ==="
echo ""

# 检查 GITHUB_TOKEN
if [ -z "$GITHUB_TOKEN" ]; then
    echo "⚠️  GITHUB_TOKEN 未设置"
    echo "   请设置: export GITHUB_TOKEN='your_github_pat'"
    echo ""
else
    echo "✅ GITHUB_TOKEN 已设置"
fi

# 配置 GitHub 组织/用户
if [ -z "$SWESMITH_ORG_GH" ]; then
    echo ""
    echo "请选择 GitHub 镜像仓库的位置:"
    echo "  1. 使用个人 GitHub 账户 (推荐)"
    echo "  2. 使用 GitHub 组织"
    echo "  3. 跳过 (仅本地运行)"
    read -p "请输入选项 [1/2/3]: " gh_choice
    
    case $gh_choice in
        1)
            read -p "请输入你的 GitHub 用户名: " gh_user
            export SWESMITH_ORG_GH="$gh_user"
            export SWESMITH_GH_OWNER_TYPE="user"
            echo "✅ 已配置: SWESMITH_ORG_GH=$gh_user (user)"
            ;;
        2)
            read -p "请输入你的 GitHub 组织名: " gh_org
            export SWESMITH_ORG_GH="$gh_org"
            export SWESMITH_GH_OWNER_TYPE="org"
            echo "✅ 已配置: SWESMITH_ORG_GH=$gh_org (org)"
            ;;
        3)
            echo "⏭️  跳过 GitHub 配置"
            ;;
    esac
else
    echo "✅ SWESMITH_ORG_GH 已设置: $SWESMITH_ORG_GH"
fi

# 配置 Docker Hub
if [ -z "$SWESMITH_ORG_DH" ]; then
    echo ""
    read -p "请输入 Docker Hub 用户名/组织名 (留空使用 GitHub 用户名): " dh_org
    if [ -z "$dh_org" ]; then
        export SWESMITH_ORG_DH="${SWESMITH_ORG_GH:-swebench}"
    else
        export SWESMITH_ORG_DH="$dh_org"
    fi
    echo "✅ 已配置: SWESMITH_ORG_DH=$SWESMITH_ORG_DH"
else
    echo "✅ SWESMITH_ORG_DH 已设置: $SWESMITH_ORG_DH"
fi

# 配置 HTTPS 克隆
export SWESMITH_GIT_HTTPS="1"
echo "✅ 已启用 HTTPS 克隆模式"

echo ""
echo "=== 配置完成 ==="
echo ""
echo "当前配置:"
echo "  GITHUB_TOKEN:          ${GITHUB_TOKEN:+(已设置)}"
echo "  SWESMITH_ORG_GH:       ${SWESMITH_ORG_GH:-未设置}"
echo "  SWESMITH_GH_OWNER_TYPE: ${SWESMITH_GH_OWNER_TYPE:-org}"
echo "  SWESMITH_ORG_DH:       ${SWESMITH_ORG_DH:-swebench}"
echo "  SWESMITH_GIT_HTTPS:    ${SWESMITH_GIT_HTTPS:-0}"
echo ""
echo "运行完整流程:"
echo "  uv run python scripts/ts_standard_pipeline.py --profile zod"
echo ""
