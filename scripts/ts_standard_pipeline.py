#!/usr/bin/env python3
"""
TypeScript 标准任务实例生成流程 - 对齐 SWE-smith / SWE-bench

与原项目流程对齐 (参考 docs/guides/issue_gen.md):
1) Build Environments
2) Create Instances (procedural.generate)
3) Validate & Evaluate (harness.valid)
4) Gather (harness.gather)
5) Generate Issue Text (issue_gen)

Usage:
  uv run python scripts/ts_standard_pipeline.py \
    --profile ZodProfile \
    --max-bugs 20
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Optional

import yaml

# 添加项目根目录到路径
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from swesmith.constants import (
    LOG_DIR_BUG_GEN,
    LOG_DIR_RUN_VALIDATION,
    LOG_DIR_TASKS,
    LOG_DIR_ISSUE_GEN,
)


def _require_env(name: str) -> None:
    if not os.environ.get(name):
        raise RuntimeError(f"缺少环境变量: {name}")


def _require_any_env(names: list[str]) -> None:
    if not any(os.environ.get(n) for n in names):
        names_str = ", ".join(names)
        raise RuntimeError(f"缺少环境变量(至少需要一个): {names_str}")


def step1_build_environment(profile, *, skip_build: bool) -> None:
    """Step 1: 创建 GitHub mirror + 构建 Docker 镜像"""
    print("\n" + "=" * 60)
    print("Step 1: 创建 Mirror + 构建 Docker 镜像")
    print("=" * 60)

    # Mirror 创建需要 GitHub Token + SSH 能力
    _require_env("GITHUB_TOKEN")

    print(f"  创建/检查 mirror: {profile.mirror_name}")
    profile.create_mirror()

    if skip_build:
        print("  跳过镜像构建 (--skip-build)")
        return

    print(f"  构建镜像: {profile.image_name}")
    profile.build_image()
    print("  ✅ 镜像构建完成")


def step2_generate_bugs_procedural(
    profile,
    max_bugs: int,
    seed: int,
    interleave: bool,
    max_entities: int,
    max_candidates: int,
    timeout_seconds: Optional[int],
) -> Path:
    """Step 2a: 程序化生成 bugs (AST 修改)"""
    print("\n  [Procedural] 使用 AST 修改生成 bugs...")

    from swesmith.bug_gen.procedural.generate import main as gen_main

    gen_main(
        repo=profile.repo_name,
        max_bugs=max_bugs,
        seed=seed,
        interleave=interleave,
        max_entities=max_entities,
        max_candidates=max_candidates,
        timeout_seconds=timeout_seconds,
    )

    return Path(LOG_DIR_BUG_GEN) / profile.repo_name


def step2_generate_bugs_llm_modify(
    profile,
    max_bugs: int,
    model: str,
    config_file: Path,
    n_workers: int,
) -> Path:
    """Step 2b: LLM Modify 生成 bugs"""
    print(f"\n  [LLM-Modify] 使用 {model} 生成 bugs...")

    import subprocess
    cmd = [
        "uv", "run", "python", "-m", "swesmith.bug_gen.llm.modify",
        profile.repo_name,
        "--config_file", str(config_file),
        "--model", model,
        "--max_bugs", str(max_bugs),
        "--n_workers", str(n_workers),
    ]
    print(f"  执行: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    return Path(LOG_DIR_BUG_GEN) / profile.repo_name


def step2_generate_bugs_llm_rewrite(
    profile,
    max_bugs: int,
    model: str,
    config_file: Path,
    n_workers: int,
) -> Path:
    """Step 2c: LLM Rewrite 生成 bugs"""
    print(f"\n  [LLM-Rewrite] 使用 {model} 重写代码生成 bugs...")

    import subprocess
    # 使用 TypeScript rewrite 配置
    rewrite_config = Path("configs/bug_gen/ts_rewrite.yml")
    if not rewrite_config.exists():
        rewrite_config = Path("configs/bug_gen/lm_rewrite.yml")
    if not rewrite_config.exists():
        rewrite_config = config_file

    cmd = [
        "uv", "run", "python", "-m", "swesmith.bug_gen.llm.rewrite",
        profile.repo_name,
        "--config_file", str(rewrite_config),
        "--model", model,
        "--max_bugs", str(max_bugs),
        "--n_workers", str(n_workers),
    ]
    print(f"  执行: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    return Path(LOG_DIR_BUG_GEN) / profile.repo_name


def step2_generate_bugs(
    profile,
    method: str,
    max_bugs: int,
    seed: int,
    interleave: bool,
    max_entities: int,
    max_candidates: int,
    timeout_seconds: Optional[int],
    llm_model: str = "anthropic/claude-3-5-sonnet-20241022",
    llm_config: Path = Path("configs/bug_gen/ts_modify.yml"),
    llm_workers: int = 1,
) -> Path:
    """Step 2: 生成 bugs (支持多种方法)
    
    方法说明 (参考 https://swesmith.com/guides/):
    - procedural: AST 程序化修改 (快速、可靠)
    - llm-modify: LLM 修改现有代码 (更多样化)
    - llm-rewrite: LLM 重写代码 (最多样化，但较慢)
    - all: 使用所有方法
    """
    print("\n" + "=" * 60)
    print(f"Step 2: 生成 Bugs (方法: {method})")
    print("=" * 60)

    bug_gen_path = Path(LOG_DIR_BUG_GEN) / profile.repo_name

    if method in ["procedural", "all"]:
        step2_generate_bugs_procedural(
            profile=profile,
            max_bugs=max_bugs,
            seed=seed,
            interleave=interleave,
            max_entities=max_entities,
            max_candidates=max_candidates,
            timeout_seconds=timeout_seconds,
        )

    if method in ["llm-modify", "all"]:
        step2_generate_bugs_llm_modify(
            profile=profile,
            max_bugs=max_bugs,
            model=llm_model,
            config_file=llm_config,
            n_workers=llm_workers,
        )

    if method in ["llm-rewrite", "all"]:
        step2_generate_bugs_llm_rewrite(
            profile=profile,
            max_bugs=max_bugs,
            model=llm_model,
            config_file=llm_config,
            n_workers=llm_workers,
        )

    return bug_gen_path


def step3_collect_patches(bug_gen_path: Path, bug_type: str, num_bugs: int) -> Path:
    """Step 3: 收集 patches (swesmith.bug_gen.collect_patches)"""
    print("\n" + "=" * 60)
    print("Step 3: 收集 Patches")
    print("=" * 60)

    from swesmith.bug_gen.collect_patches import main as collect_main

    collect_main(bug_gen_path, bug_type=bug_type, num_bugs=num_bugs)

    patches_file = bug_gen_path.parent / f"{bug_gen_path.name}_{bug_type}_patches.json"
    if num_bugs != -1:
        patches_file = patches_file.with_name(
            patches_file.stem + f"_n{num_bugs}" + patches_file.suffix
        )

    if not patches_file.exists():
        raise FileNotFoundError(f"未找到 patches 文件: {patches_file}")

    print(f"  ✅ Patches 文件: {patches_file}")
    return patches_file


def step4_validate_f2p(patches_file: Path, workers: int, redo_existing: bool) -> Path:
    """Step 4: F2P 验证 (swesmith.harness.valid)"""
    print("\n" + "=" * 60)
    print("Step 4: F2P 验证")
    print("=" * 60)

    from swesmith.harness.valid import main as valid_main

    valid_main(str(patches_file), workers, redo_existing=redo_existing)

    # 从 patches 文件内容读取 repo 字段（与 valid.py 内部逻辑一致）
    # 这样无论 bug_type 或 num_bugs 参数如何，都能正确获取 repo_name
    with open(patches_file, "r") as f:
        bug_patches = json.load(f)
    if not bug_patches:
        raise ValueError(f"Patches 文件为空: {patches_file}")
    repo_name = bug_patches[0]["repo"]
    validation_dir = Path(LOG_DIR_RUN_VALIDATION) / repo_name
    return validation_dir


def step5_gather_instances(
    validation_dir: Path,
    override_branch: bool,
    debug_subprocess: bool,
    repush_image: bool,
    verbose: bool,
) -> Path:
    """Step 5: 收集任务实例 (swesmith.harness.gather)"""
    print("\n" + "=" * 60)
    print("Step 5: 收集任务实例")
    print("=" * 60)

    from swesmith.harness.gather import main as gather_main

    gather_main(
        validation_logs_path=str(validation_dir),
        override_branch=override_branch,
        debug_subprocess=debug_subprocess,
        repush_image=repush_image,
        verbose=verbose,
    )

    tasks_file = Path(LOG_DIR_TASKS) / f"{validation_dir.name}.json"
    if not tasks_file.exists():
        raise FileNotFoundError(f"未找到任务实例文件: {tasks_file}")

    print(f"  ✅ 任务实例文件: {tasks_file}")
    return tasks_file


def _pick_issue_text(issue_meta: dict, model: Optional[str]) -> Optional[str]:
    responses = issue_meta.get("responses")
    if not responses:
        return None

    if model and model in responses and responses[model]:
        return responses[model][0]

    # fallback: 取第一个可用模型的第一条
    for _, vals in responses.items():
        if vals:
            return vals[0]
    return None


def merge_issue_outputs(
    tasks_file: Path, config_file: Path, issue_exp_id: Optional[str] = None
) -> Path:
    """将 issue_gen 生成的文本合并回任务实例"""
    tasks = json.loads(tasks_file.read_text())
    config = yaml.safe_load(config_file.read_text())
    model = config.get("model")

    repo_name = tasks_file.stem
    issue_dir = Path(LOG_DIR_ISSUE_GEN) / repo_name
    issue_exp = issue_exp_id or config_file.stem

    out_path = Path(LOG_DIR_ISSUE_GEN) / f"{repo_name}__{issue_exp}_n1.json"

    missing = 0
    for inst in tasks:
        inst_id = inst.get("instance_id")
        meta_path = issue_dir / f"{inst_id}.json"
        if not meta_path.exists():
            missing += 1
            continue
        issue_meta = json.loads(meta_path.read_text())
        ps = _pick_issue_text(issue_meta, model)
        if ps:
            inst["problem_statement"] = ps
        else:
            missing += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False))

    print(f"  ✅ 合并完成: {out_path}")
    if missing:
        print(f"  ⚠️ 缺失 problem_statement: {missing}/{len(tasks)}")

    return out_path


def _normalize_issue_output(tasks_file: Path, suffix: str) -> Path:
    """Normalize issue output path to logs/issue_gen, with legacy fallback.

    Legacy issue generators (`get_static.py`, `get_from_pr.py`, `get_from_tests.py`)
    may write output next to `tasks_file` (e.g., `logs/task_insts`). The standard
    pipeline contract expects issue outputs in `logs/issue_gen`.
    """
    canonical = Path(LOG_DIR_ISSUE_GEN) / f"{tasks_file.stem}__{suffix}.json"
    legacy = tasks_file.parent / f"{tasks_file.stem}__{suffix}.json"

    if canonical.exists():
        return canonical

    if legacy.exists():
        canonical.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, canonical)
        print(f"  ℹ️ 检测到旧路径产物，已同步到标准路径: {canonical}")
        return canonical

    raise FileNotFoundError(
        f"未找到 issue 输出文件。标准路径: {canonical}；旧路径: {legacy}"
    )


def step6_generate_issue_text(
    tasks_file: Path,
    issue_mode: str,
    issue_config: Path,
    issue_workers: int,
    issue_redo_existing: bool,
    issue_exp_id: Optional[str],
    issue_tests_model: Optional[str],
) -> Optional[Path]:
    """Step 6: 生成问题描述"""
    print("\n" + "=" * 60)
    print("Step 6: 生成问题描述")
    print("=" * 60)

    if issue_mode == "skip":
        print("  跳过 Issue 生成")
        return None

    if issue_mode == "static":
        from swesmith.issue_gen.get_static import main as static_main

        static_main(str(tasks_file))
        out_path = _normalize_issue_output(tasks_file, "ig_static")
        print(f"  ✅ 生成静态问题描述: {out_path}")
        return out_path

    if issue_mode == "pr":
        from swesmith.issue_gen.get_from_pr import main as pr_main

        pr_main(str(tasks_file))
        out_path = _normalize_issue_output(tasks_file, "ig_orig")
        print(f"  ✅ 生成 PR 问题描述: {out_path}")
        return out_path

    if issue_mode == "tests":
        from swesmith.issue_gen.get_from_tests import main as tests_main

        if issue_tests_model is None:
            raise RuntimeError("--issue-tests-model 不能为空 (issue_mode=tests)")
        tests_main(
            dataset_path=str(tasks_file),
            config_file=str(issue_config),
            model=issue_tests_model,
            n_workers=issue_workers,
        )
        out_path = _normalize_issue_output(tasks_file, issue_config.stem)
        print(f"  ✅ 生成测试相关问题描述: {out_path}")
        return out_path

    # issue_mode == "llm"
    _require_any_env(["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])

    from swesmith.issue_gen.generate import IssueGen

    if not issue_config.exists():
        raise FileNotFoundError(f"Issue 配置不存在: {issue_config}")

    IssueGen(
        config_file=issue_config,
        workers=issue_workers,
        dataset_path=str(tasks_file),
        redo_existing=issue_redo_existing,
    ).run()

    # 合并生成的 issue 文本回任务实例
    return merge_issue_outputs(tasks_file, issue_config, issue_exp_id=issue_exp_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="TypeScript 标准任务实例生成流程")
    parser.add_argument("--profile", type=str, required=True, help="Profile 类名 (如 ZodProfile)")
    parser.add_argument("--org-gh", type=str, default=None, help="GitHub 组织/用户 (覆盖 SWESMITH_ORG_GH)")
    parser.add_argument("--org-dh", type=str, default=None, help="Docker 组织 (覆盖 SWESMITH_ORG_DH)")
    parser.add_argument(
        "--gh-owner-type",
        type=str,
        default="org",
        choices=["org", "user"],
        help="GitHub owner 类型: org 或 user (覆盖 SWESMITH_GH_OWNER_TYPE)",
    )
    parser.add_argument(
        "--force-mirror",
        action="store_true",
        help="强制更新已有 mirror (push --force)",
    )

    # bug 生成相关
    parser.add_argument(
        "--bug-gen-method",
        type=str,
        default="procedural",
        choices=["procedural", "llm-modify", "llm-rewrite", "all"],
        help="Bug 生成方法: procedural(AST), llm-modify, llm-rewrite, all",
    )
    parser.add_argument("--max-bugs", type=int, default=20, help="生成的 bugs 数量")
    parser.add_argument("--seed", type=int, default=24, help="随机种子")
    parser.add_argument("--interleave", action="store_true", help="随机交错 modifier")
    parser.add_argument("--max-entities", type=int, default=-1, help="实体采样上限")
    parser.add_argument("--max-candidates", type=int, default=-1, help="候选对上限")
    parser.add_argument("--timeout-seconds", type=int, default=None, help="生成超时(秒)")
    parser.add_argument(
        "--llm-model",
        type=str,
        default="anthropic/claude-3-5-sonnet-20241022",
        help="LLM bug 生成使用的模型",
    )
    parser.add_argument(
        "--llm-config",
        type=Path,
        default=Path("configs/bug_gen/ts_modify.yml"),
        help="LLM bug 生成的配置文件",
    )
    parser.add_argument("--llm-workers", type=int, default=1, help="LLM 生成并行数")

    # 收集 patches
    parser.add_argument("--bug-type", type=str, default="all", help="收集的 bug 类型")
    parser.add_argument("--collect-num-bugs", type=int, default=-1, help="收集 patches 数量")

    # F2P 验证
    parser.add_argument("--workers", type=int, default=2, help="验证并行数")
    parser.add_argument("--redo-existing", action="store_true", help="重新验证已存在结果")

    # gather
    parser.add_argument("--override-branch", action="store_true", help="覆盖已有分支")
    parser.add_argument("--debug-subprocess", action="store_true", help="输出 subprocess 调试信息")
    parser.add_argument("--repush-image", action="store_true", help="重新构建并推送镜像")
    parser.add_argument("--verbose", action="store_true", help="Verbose 输出")

    # issue 生成
    parser.add_argument(
        "--issue-mode",
        type=str,
        default="llm",
        choices=["llm", "static", "tests", "pr", "skip"],
        help="问题描述生成方式",
    )
    parser.add_argument(
        "--issue-config",
        type=Path,
        default=Path("configs/issue_gen/ig_v2.yaml"),
        help="Issue 生成配置文件",
    )
    parser.add_argument("--issue-workers", type=int, default=1, help="Issue 生成并行数")
    parser.add_argument("--issue-redo-existing", action="store_true", help="重做已有 issue")
    parser.add_argument("--issue-exp-id", type=str, default=None, help="Issue 输出标识")
    parser.add_argument("--issue-tests-model", type=str, default=None, help="tests 模式下的模型名")

    # 流程控制
    parser.add_argument("--skip-build", action="store_true", help="跳过镜像构建")
    parser.add_argument("--skip-validation", action="store_true", help="跳过 F2P 验证")

    args = parser.parse_args()

    # 运行时覆盖 GitHub/Docker 组织设置（支持方案 B）
    os.environ["SWESMITH_GH_OWNER_TYPE"] = args.gh_owner_type
    if args.gh_owner_type == "user":
        # 不设置 SWESMITH_GIT_HTTPS：clone 使用 SSH（快速、无需认证），
        # push 由 gather.py 自动设置 HTTPS + token
        pass
    if args.force_mirror:
        os.environ["SWESMITH_MIRROR_UPDATE"] = "1"
    if args.org_gh:
        os.environ["SWESMITH_ORG_GH"] = args.org_gh
    if args.org_dh:
        os.environ["SWESMITH_ORG_DH"] = args.org_dh

    # 获取 profile（支持内置 + auto_profile_ts 生成的 profiles/generated/*.py）
    from swesmith.profiles import registry, typescript

    available_ts_profiles: dict[str, type] = {}
    for cls in set(registry.data.values()):
        if (
            isinstance(cls, type)
            and issubclass(cls, typescript.TypeScriptProfile)
            and cls.__name__ != "TypeScriptProfile"
        ):
            available_ts_profiles[cls.__name__] = cls

    profile_cls = available_ts_profiles.get(args.profile)
    if profile_cls is None:
        print(f"❌ 未找到 Profile: {args.profile}")
        print("可用的 TypeScript Profiles:")
        for name in sorted(available_ts_profiles):
            print(f"  - {name}")
        raise SystemExit(1)

    profile = profile_cls()

    print("=" * 60)
    print("TypeScript 标准任务实例生成流程")
    print("=" * 60)
    print(f"Profile: {args.profile}")
    print(f"repo_name: {profile.repo_name}")
    print(f"mirror_name: {profile.mirror_name}")
    print(f"image_name: {profile.image_name}")
    print(f"gh_owner_type: {profile.gh_owner_type}")
    print(f"github_owner: {profile.org_gh}")
    print(f"docker_org: {profile.org_dh}")

    # Step 1
    step1_build_environment(profile, skip_build=args.skip_build)

    # Step 2
    bug_gen_path = step2_generate_bugs(
        profile,
        method=args.bug_gen_method,
        max_bugs=args.max_bugs,
        seed=args.seed,
        interleave=args.interleave,
        max_entities=args.max_entities,
        max_candidates=args.max_candidates,
        timeout_seconds=args.timeout_seconds,
        llm_model=args.llm_model,
        llm_config=args.llm_config,
        llm_workers=args.llm_workers,
    )

    # Step 3
    patches_file = step3_collect_patches(
        bug_gen_path, bug_type=args.bug_type, num_bugs=args.collect_num_bugs
    )

    # Step 4
    if args.skip_validation:
        print("\n⚠️ 跳过 F2P 验证")
        validation_dir = Path(LOG_DIR_RUN_VALIDATION) / profile.repo_name
    else:
        validation_dir = step4_validate_f2p(
            patches_file, workers=args.workers, redo_existing=args.redo_existing
        )

    # Step 5
    tasks_file = step5_gather_instances(
        validation_dir,
        override_branch=args.override_branch,
        debug_subprocess=args.debug_subprocess,
        repush_image=args.repush_image,
        verbose=args.verbose,
    )

    # Step 6
    issue_out = step6_generate_issue_text(
        tasks_file,
        issue_mode=args.issue_mode,
        issue_config=args.issue_config,
        issue_workers=args.issue_workers,
        issue_redo_existing=args.issue_redo_existing,
        issue_exp_id=args.issue_exp_id,
        issue_tests_model=args.issue_tests_model,
    )

    # Step 7: 输出最终数据集到 logs/agent_datasets/
    final_path = None
    if issue_out:
        final_path = Path("logs/agent_datasets") / f"{profile.repo_name}_final.json"
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(issue_out, final_path)

    print("\n" + "=" * 60)
    print("✅ 完成")
    print("=" * 60)
    print(f"任务实例: {tasks_file}")
    if final_path:
        print(f"最终数据集（可直接传给 Agent）: {final_path}")


if __name__ == "__main__":
    main()
