## 环境准备

```bash
source <SWESMITH_ROOT>/.venv/bin/activate
export SWESMITH_GH_OWNER_TYPE="user"                      # user 或 org
export SWESMITH_ORG_GH="<your_github_user_or_org>"
export SWESMITH_ORG_DH="<your_dockerhub_user_or_org>"
export GITHUB_TOKEN="<your_github_pat>"
```

## TypeScript 标准任务实例流水线

> 以 fp-ts 为例，Profile 应使用 `FpTsProfile`（不是 `ZodProfile`）。
>
> 完整链路说明见：`docs/guides/ts_pipeline_overview.md`
>
> 三段通用可执行手册见：`docs/guides/ts_three_pipelines.md`

```bash
uv run python scripts/ts_standard_pipeline.py \
  --profile FpTsProfile \
  --bug-gen-method all \
  --max-bugs 10 \
  --workers 4 \
  --issue-mode llm \
  --issue-config configs/issue_gen/ig_v2.yaml \
  --issue-workers 1
```

`--bug-gen-method` 支持 4 种模式：
- `procedural`
- `llm-modify`
- `llm-rewrite`
- `all`（三种都跑）

## 任务实例标准产物

- `logs/bug_gen/<repo_name>/`
- `logs/run_validation/<repo_name>/`
- `logs/task_insts/<repo_name>.json`
- `logs/issue_gen/<repo_name>__<exp>_n1.json`
- `logs/agent_datasets/<repo_name>_final.json`

## 轨迹与 SFT 产物链路

```bash
# 1) 在 SWE-agent 侧生成轨迹
./agent/_gen_trajs.sh

# 2) 评测轨迹（在 SWE-smith 侧）
python -m swesmith.harness.eval \
  --dataset_path logs/agent_datasets/<repo_name>_final.json \
  --predictions_path trajectories/<user>/<run_id>/preds.json \
  --run_id <run_id> \
  --workers 10

# 3) 轨迹转换为 SFT（本地脚本）
./scripts/train_prepare_sft_local.sh \
  trajectories/<user>/<run_id>/ \
  logs/run_evaluation/<run_id>/ \
  xml
```

SFT 数据默认输出到：
- `trajectories_sft/<run_id>.xml.jsonl`

## 手动分步（与 ts_standard_pipeline 等价）

```bash
repo_name="gcanti__fp-ts.master"

# Step 1: 创建 mirror + 构建镜像
python -m swesmith.build_repo.create_images -r fp-ts -y

# Step 2: 生成 bug（可替换为 llm.modify / llm.rewrite）
python -m swesmith.bug_gen.procedural.generate "$repo_name" --max_bugs 10

# Step 3: 收集 patch（路径需包含 commit 后缀）
python -m swesmith.bug_gen.collect_patches "logs/bug_gen/$repo_name"

# Step 4: F2P 验证
python -m swesmith.harness.valid "logs/bug_gen/${repo_name}_all_patches.json" -w 4

# Step 5: 收集有效实例（要求 >=1 FAIL_TO_PASS 且 >=1 PASS_TO_PASS）
python -m swesmith.harness.gather "logs/run_validation/$repo_name"

# Step 6: 生成 issue 文本（LLM）
python swesmith/issue_gen/generate.py \
  logs/task_insts/${repo_name}.json \
  --config_file configs/issue_gen/ig_v2.yaml \
  --n_workers 1
```

## 说明

- 已移除 `merge_issue_state_to_instance.py`，由 `ts_standard_pipeline.py` 内置合并逻辑替代。
- 若使用 `issue_mode=static/pr/tests`，流水线会自动把旧路径输出归一化到 `logs/issue_gen/`。