# TypeScript 任务实例生成 - 快速启动指南

本文档详细讲解如何使用 SWE-smith 为 TypeScript 仓库生成可用于 Agent 训练的任务实例。

## 1. 环境要求

| 依赖 | 版本要求 | 检查命令 |
|------|---------|---------|
| Python | 3.10+ | `python --version` |
| Docker | 20+ | `docker --version` |
| uv | 最新 | `uv --version` |
| Git | 2.0+ | `git --version` |

## 2. 环境变量配置

运行前必须设置以下环境变量：

```bash
# GitHub Token（用于创建 mirror 仓库和推送分支）
export GITHUB_TOKEN="your_github_token"

# GitHub 用户名（mirror 仓库会创建在这个用户下）
export SWESMITH_ORG_GH="your_github_username"

# DockerHub 用户名（Docker 镜像名称前缀）
export SWESMITH_ORG_DH="your_dockerhub_username"

# LLM API（用于 LLM bug 生成和 issue 生成）
export ANTHROPIC_API_KEY="your_api_key"
# 如果使用中转站：
# export ANTHROPIC_BASE_URL="https://your-proxy.com"
```

## 3. 全流程概览

Pipeline 自动执行以下 7 个步骤，最终输出可直接传给 Agent 的标准数据集：

```
Step 1: Build Environment     →  创建 mirror 仓库 + 构建 Docker 镜像
Step 2: Generate Bugs         →  生成带 bug 的代码补丁
Step 3: Collect Patches       →  收集所有补丁为一个 JSON 文件
Step 4: F2P Validation        →  验证哪些 bug 能让测试失败
Step 5: Gather Instances      →  收集验证通过的实例，推送分支到 GitHub
Step 6: Generate Issue Text   →  LLM 为每个实例生成 GitHub Issue 描述
Step 7: Export Final Dataset   →  输出最终数据集到 logs/agent_datasets/
```

## 4. 一键运行（推荐）

使用 `ts_standard_pipeline.py` 自动执行全部步骤，最终输出到 `logs/agent_datasets/<repo>_final.json`：

```bash
uv run python scripts/ts_standard_pipeline.py \
    --profile ZodProfile \
    --bug-gen-method llm-modify \
    --max-bugs 10 \
    --llm-model "anthropic/claude-sonnet-4-20250514" \
    --skip-build \
    --gh-owner-type user
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--profile` | Profile 类名（必填） | - |
| `--bug-gen-method` | Bug 生成方法：`procedural` / `llm-modify` / `llm-rewrite` / `all` | `procedural` |
| `--max-bugs` | 每种方法生成的 bug 数量上限 | 20 |
| `--llm-model` | LLM 模型名称 | `anthropic/claude-3-5-sonnet-20241022` |
| `--skip-build` | 跳过 Docker 镜像构建（已构建过时使用） | 不跳过 |
| `--gh-owner-type` | GitHub owner 类型：`user` / `org` | `org` |
| `--issue-mode` | Issue 生成方式：`llm` / `static` / `skip` | `llm` |
| `--workers` | F2P 验证并行数 | 2 |

### 可用的 Profile

| Profile | 仓库 | 测试框架 |
|---------|------|---------|
| `ZodProfile` | colinhacks/zod | Jest |
| `ValibotProfile` | fabian-hiller/valibot | Vitest |
| `SuperstructProfile` | ianstormtaylor/superstruct | Vitest |
| `CheerioProfile` | cheeriojs/cheerio | Jest |
| `IoTsProfile` | gcanti/io-ts | Jest |
| `NeverthrowProfile` | supermacro/neverthrow | Vitest |
| `YupProfile` | jquense/yup | Jest |
| `FpTsProfile` | gcanti/fp-ts | Jest |

## 5. 分步手动运行

如果需要对每个步骤有更精细的控制，可以手动分步执行。以 Zod 为例：

### Step 1: 构建环境

首次使用某个仓库时，需要创建 mirror 和构建 Docker 镜像：

```bash
uv run python -c "
from swesmith.profiles.typescript import ZodProfile
p = ZodProfile()
p.create_mirror()  # 创建 GitHub mirror
p.build_image()    # 构建 Docker 镜像
"
```

### Step 2: 生成 Bugs

**LLM Modify**（让 LLM 在已有代码中引入 bug）：
```bash
uv run python -m swesmith.bug_gen.llm.modify \
    colinhacks__zod.v3.23.8 \
    -c configs/bug_gen/ts_modify.yml \
    --model anthropic/claude-sonnet-4-20250514 \
    --max_bugs 10
```

**LLM Rewrite**（让 LLM 重写函数引入 bug）：
```bash
uv run python -m swesmith.bug_gen.llm.rewrite \
    colinhacks__zod.v3.23.8 \
    -c configs/bug_gen/ts_rewrite.yml \
    --model anthropic/claude-sonnet-4-20250514 \
    --max_bugs 10
```

**Procedural**（AST 程序化修改，不需要 LLM）：
```bash
uv run python -m swesmith.bug_gen.procedural.generate \
    colinhacks__zod.v3.23.8 \
    --max_bugs 10
```

### Step 3: 收集 Patches

```bash
uv run python -m swesmith.bug_gen.collect_patches \
    logs/bug_gen/colinhacks__zod.v3.23.8 \
    --type all
```

### Step 4: F2P 验证

```bash
uv run python -m swesmith.harness.valid \
    logs/bug_gen/colinhacks__zod.v3.23.8_all_patches.json \
    --workers 4
```

### Step 5: Gather 实例

```bash
uv run python -m swesmith.harness.gather \
    logs/run_validation/colinhacks__zod.v3.23.8
```

### Step 6: 生成 Issue 文本

```bash
uv run python -m swesmith.issue_gen.generate \
    -d logs/task_insts/colinhacks__zod.v3.23.8.json \
    -c configs/issue_gen/ig_v2.yaml \
    -w 2
```

Pipeline 会自动完成 Step 7（将结果输出到 `logs/agent_datasets/`），手动运行时最终文件在 `logs/issue_gen/<repo>__ig_v2_n1.json`，格式与原仓库一致。

## 6. 输出文件说明

| 步骤 | 输出路径 | 说明 |
|------|---------|------|
| Bug 生成 | `logs/bug_gen/<repo>/` | 每个 bug 的 diff 和元数据 |
| Patches 收集 | `logs/bug_gen/<repo>_all_patches.json` | 所有 patches 合并 |
| F2P 验证 | `logs/run_validation/<repo>/` | 每个 patch 的验证报告 |
| Gather | `logs/task_insts/<repo>.json` | 任务实例（无 problem_statement） |
| Issue 生成 | `logs/issue_gen/<repo>__ig_v2_n1.json` | 带 problem_statement 的完整实例 |
| **最终数据集** | **`logs/agent_datasets/<repo>_final.json`** | **Pipeline 自动输出，可直接传给 Agent** |

### 最终数据集格式

与原仓库 SWE-smith 的 Python 任务实例格式完全一致（7 个字段）：

```json
{
  "instance_id": "colinhacks__zod.v3.23.8.ts_modify__3mpmd4za",
  "repo": "xxxxx131/colinhacks__zod.v3.23.8",
  "patch": "diff --git a/src/types.ts ...",
  "problem_statement": "Validation throws error when...",
  "FAIL_TO_PASS": ["test name 1", "test name 2"],
  "PASS_TO_PASS": ["test name 3", "..."],
  "image_name": "xxxxx131/swesmith.architecture.x86_64.colinhacks_1776_zod.v3.23.8"
}
```

Agent 使用方式：
```python
from swesmith.profiles import registry
import json

instances = json.load(open("logs/agent_datasets/colinhacks__zod.v3.23.8_final.json"))
task = instances[0]
rp = registry.get_from_inst(task)
container = rp.get_container(task)  # 获取初始化好的 Docker 容器
# Agent 在容器中读取 problem_statement、修复 bug、运行测试
```

## 7. 添加新的 TypeScript 仓库

在 `swesmith/profiles/typescript.py` 中添加新 Profile：

```python
@dataclass
class NewRepoProfile(TypeScriptProfile):
    owner: str = "owner-name"
    repo: str = "repo-name"
    commit: str = "v1.0.0"  # 使用稳定的 tag
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self) -> str:
        return f"""FROM node:20-bullseye
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN npm install
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)  # 或 parse_log_vitest / parse_log_mocha
```

然后运行：
```bash
uv run python scripts/ts_standard_pipeline.py \
    --profile NewRepoProfile \
    --bug-gen-method llm-modify \
    --max-bugs 10 \
    --gh-owner-type user
```

## 8. 常见问题

### Q: Docker 镜像找不到？
确保 `SWESMITH_ORG_DH` 与构建时一致。用 `docker images | grep swesmith` 查看已有镜像。

### Q: git clone 超时？
框架会自动先尝试 SSH clone，失败后 fallback 到 HTTPS。如果两种方式都超时，说明网络问题，请检查 GitHub 连通性。

### Q: git push 失败？
框架会自动使用 HTTPS + Token 推送（即使 clone 用了 SSH）。确保 `GITHUB_TOKEN` 有 repo 权限。

### Q: F2P 验证通过率太低？
这是正常的。原仓库 10-30% 的通过率是预期范围。增加 `--max-bugs` 可以生成更多候选。

### Q: 类型检查错误（tsc 失败）？
某些仓库因依赖版本漂移导致类型检查失败。在 Profile 中设置 `skip_type_check: bool = True` 即可自动跳过。

### Q: 测试名格式和 Python 不同？
Jest/Vitest 使用测试描述文本（如 `"should validate correctly"`）而非 pytest 的路径格式（如 `test_file.py::TestClass::test_method`）。这是正常的，不影响评估。
