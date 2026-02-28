#!/usr/bin/env python3
"""
TypeScript 仓库自动 Profile 生成器

自动检测仓库的：
- 包管理器 (npm/yarn/pnpm)
- 测试框架 (Jest/Vitest/Mocha)
- 测试命令
- 依赖安装方式

Usage:
  uv run python scripts/auto_profile_ts.py colinhacks/zod --commit v3.23.8

  # 或者自动检测最新 release
  uv run python scripts/auto_profile_ts.py colinhacks/zod

  # 生成后直接运行流程
  uv run python scripts/auto_profile_ts.py colinhacks/zod --run
"""

import argparse
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RepoConfig:
    """自动检测到的仓库配置"""
    owner: str
    repo: str
    commit: str
    package_manager: str  # npm, yarn, pnpm
    test_framework: str   # jest, vitest, mocha, ava
    test_cmd: str
    install_cmd: str
    node_version: str = "20"


def clone_repo(owner: str, repo: str, commit: Optional[str], temp_dir: str) -> str:
    """克隆仓库到临时目录"""
    repo_url = f"https://github.com/{owner}/{repo}.git"
    repo_path = os.path.join(temp_dir, repo)
    
    print(f"  正在克隆 {owner}/{repo}...")
    subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, repo_path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    
    if commit:
        # Fetch the specific commit/tag
        subprocess.run(
            ["git", "-C", repo_path, "fetch", "--depth", "1", "origin", commit],
            check=False,  # May fail for tags
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "-C", repo_path, "checkout", commit],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    
    return repo_path


def detect_package_manager(repo_path: str) -> str:
    """检测包管理器"""
    if os.path.exists(os.path.join(repo_path, "pnpm-lock.yaml")):
        return "pnpm"
    elif os.path.exists(os.path.join(repo_path, "yarn.lock")):
        return "yarn"
    elif os.path.exists(os.path.join(repo_path, "bun.lockb")):
        return "bun"
    else:
        return "npm"


def detect_test_framework(package_json: dict, package_manager: str) -> tuple[str, str]:
    """检测测试框架，返回 (框架名, 安全的测试命令)
    
    命令选择策略（与原始 JS profiles 主流模式对齐）：
    
    优先级 1: `<pm> run <specific-test-script>` (29/81 原始 JS profiles)
      找到 package.json 中直接调用测试运行器的具体脚本（不含 && 链），
      通过 `npm run <脚本名>` 调用。安全、可预测、不会静默下载。
      例: npm run test:vitest -- --reporter verbose
      例: yarn run test:ts-jest --verbose
    
    优先级 2: `./node_modules/.bin/<runner>` (4/81 原始 JS profiles)
      直接调用本地安装的二进制。如果没安装会立即报错（fail fast），
      不会像 npx 那样静默从 npm 下载可能不兼容的版本。
      例: ./node_modules/.bin/vitest run --reporter verbose
    
    避免使用:
      - `npm test` -- 几乎总是链式命令（lint && type-check && test && docs）
      - `npx <tool>` -- 会静默下载不存在的包，可能版本不兼容
    """
    scripts = package_json.get("scripts", {})
    dev_deps = package_json.get("devDependencies", {})
    deps = package_json.get("dependencies", {})
    all_deps = {**deps, **dev_deps}
    pm = package_manager  # npm, yarn, or pnpm
    
    # Step 1: 收集所有"纯测试"脚本（不含 && 链式命令）
    pure_test_scripts = {}
    for name, cmd in scripts.items():
        if "&&" in cmd:
            continue
        pure_test_scripts[name] = cmd
    
    # Step 2: 检测 Vitest
    if "vitest" in all_deps or any("vitest" in v for v in scripts.values()):
        # 优先找调用 vitest 的纯脚本
        for name, cmd in pure_test_scripts.items():
            if "vitest" in cmd:
                # 使用 npm run <script> 模式（原始 JS profiles 主流模式）
                return "vitest", f"{pm} run {name} -- --reporter verbose"
        # 没有纯脚本时用 ./node_modules/.bin/ 模式（避免 npx 下载）
        return "vitest", "./node_modules/.bin/vitest run --reporter verbose"
    
    # Step 3: 检测 Jest
    if "jest" in all_deps or "ts-jest" in all_deps or any("jest" in v for v in scripts.values()):
        # 优先找调用 jest 的纯脚本
        for name, cmd in pure_test_scripts.items():
            if "jest" in cmd and "test" in name:
                return "jest", f"{pm} run {name} --verbose"
        # 没有纯脚本时用 ./node_modules/.bin/ 模式
        return "jest", "./node_modules/.bin/jest --verbose --no-color"
    
    # Step 4: 检测 Mocha
    if "mocha" in all_deps or any("mocha" in v for v in scripts.values()):
        for name, cmd in pure_test_scripts.items():
            if "mocha" in cmd:
                return "mocha", f"{pm} run {name} -- --reporter spec"
        return "mocha", "./node_modules/.bin/mocha --reporter spec"
    
    # Step 5: 检测 node --test (Node.js 内置测试运行器)
    if any("node --test" in v or "node:test" in v for v in scripts.values()):
        return "node_test", "node --test"
    
    # Step 6: 检测 Ava
    if "ava" in all_deps:
        return "ava", "./node_modules/.bin/ava --verbose"
    
    # Step 7: 兜底 -- 找最合适的纯测试脚本
    for name, cmd in pure_test_scripts.items():
        if "test" in name:
            return "unknown", f"{pm} run {name} --verbose"
    
    # 最终兜底：./node_modules/.bin/jest（大多数 TS 仓库用 jest）
    return "jest", "./node_modules/.bin/jest --verbose --no-color"


def detect_config(owner: str, repo: str, commit: Optional[str]) -> RepoConfig:
    """自动检测仓库配置"""
    print(f"\n🔍 正在分析仓库: {owner}/{repo}")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = clone_repo(owner, repo, commit, temp_dir)
        
        # 读取 package.json
        package_json_path = os.path.join(repo_path, "package.json")
        if not os.path.exists(package_json_path):
            raise ValueError(f"找不到 package.json: {package_json_path}")
        
        with open(package_json_path) as f:
            package_json = json.load(f)
        
        # 检测包管理器
        pm = detect_package_manager(repo_path)
        print(f"  📦 包管理器: {pm}")
        
        # 检测测试框架
        framework, test_cmd = detect_test_framework(package_json, pm)
        print(f"  🧪 测试框架: {framework}")
        
        # 确定安装命令
        install_cmd = f"{pm} install"
        
        # test_cmd 已由 detect_test_framework 完整生成（包含包管理器前缀）
        print(f"  ▶️  测试命令: {test_cmd}")
        
        # 获取实际 commit
        if not commit:
            result = subprocess.run(
                ["git", "-C", repo_path, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            )
            commit = result.stdout.strip()[:8]
        
        return RepoConfig(
            owner=owner,
            repo=repo,
            commit=commit,
            package_manager=pm,
            test_framework=framework,
            test_cmd=test_cmd,
            install_cmd=install_cmd,
        )


def generate_profile_code(config: RepoConfig) -> str:
    """生成 Profile 类代码"""
    
    # 选择正确的 log_parser
    parser_map = {
        "jest": "parse_log_jest",
        "vitest": "parse_log_vitest",
        "mocha": "parse_log_mocha",
    }
    parser = parser_map.get(config.test_framework, "parse_log_jest")
    
    # 生成类名
    class_name = f"{''.join(word.capitalize() for word in config.repo.replace('-', '_').split('_'))}Profile"
    
    code = f'''
@dataclass
class {class_name}(TypeScriptProfile):
    """
    Auto-generated profile for {config.owner}/{config.repo}
    
    Detected:
    - Package Manager: {config.package_manager}
    - Test Framework: {config.test_framework}
    """
    owner: str = "{config.owner}"
    repo: str = "{config.repo}"
    commit: str = "{config.commit}"
    test_cmd: str = "{config.test_cmd}"

    @property
    def dockerfile(self) -> str:
        return f"""FROM node:{config.node_version}-bullseye
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{{self.mirror_name}} /{{ENV_NAME}}
WORKDIR /{{ENV_NAME}}
RUN git checkout {{self.commit}}
RUN {config.install_cmd}
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return {parser}(log)


# Register the profile
registry.register_profile({class_name})
'''
    return code


def save_profile(config: RepoConfig, code: str) -> Path:
    """保存生成的 Profile 到文件"""
    output_dir = Path(__file__).parent.parent / "swesmith" / "profiles" / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Ensure generated/ is a regular package for reliable imports.
    init_file = output_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text(
            '"""Auto-generated profiles for SWE-smith."""\n',
            encoding="utf-8",
        )
    
    filename = f"{config.owner}__{config.repo}.py".replace("-", "_")
    output_path = output_dir / filename
    
    header = '''"""
Auto-generated TypeScript Profile

Generated by: scripts/auto_profile_ts.py
"""

from dataclasses import dataclass
from swesmith.constants import ENV_NAME
from swesmith.profiles.base import registry
from swesmith.profiles.typescript import TypeScriptProfile
from swesmith.profiles.javascript import parse_log_jest, parse_log_vitest, parse_log_mocha
'''
    
    output_path.write_text(header + code)
    print(f"\n✅ Profile 已保存到: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="自动生成 TypeScript 仓库的 Profile"
    )
    parser.add_argument(
        "repo",
        help="仓库名称 (格式: owner/repo)"
    )
    parser.add_argument(
        "--commit",
        help="指定 commit/tag (默认: 最新)"
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="生成后直接运行完整流程"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示生成的代码，不保存"
    )
    
    args = parser.parse_args()
    
    # 解析仓库名
    if "/" not in args.repo:
        print(f"❌ 错误: 仓库名格式应为 owner/repo，收到: {args.repo}")
        return 1
    
    owner, repo = args.repo.split("/", 1)
    
    try:
        # 检测配置
        config = detect_config(owner, repo, args.commit)
        
        # 生成代码
        code = generate_profile_code(config)
        
        print("\n📝 生成的 Profile 代码:")
        print("-" * 60)
        print(code)
        print("-" * 60)
        
        if args.dry_run:
            print("\n(--dry-run 模式，未保存)")
            return 0
        
        # 保存 Profile
        profile_path = save_profile(config, code)
        class_name = f"{''.join(word.capitalize() for word in config.repo.replace('-', '_').split('_'))}Profile"
        
        if args.run:
            print("\n🚀 开始运行完整流程...")
            subprocess.run([
                "uv", "run", "python", "scripts/ts_standard_pipeline.py",
                "--profile", class_name
            ])
        else:
            print("\n💡 下一步:")
            print(f"  1. 检查生成的 Profile 是否正确")
            print(f"  2. 运行: uv run python scripts/ts_standard_pipeline.py --profile {class_name}")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
