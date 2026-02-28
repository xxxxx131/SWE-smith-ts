# 训练 SWE-agent

下面进入关键部分：如何使用 SWE-smith 训练 SWE-agent。

本节重点介绍基于拒绝采样的监督微调（RSFT）流程。

!!! note "SWE-agent"

    本节文档基于 [SWE-agent](https://github.com/SWE-agent/SWE-agent) 的工作流。
    我们暂不显式支持非 SWE-agent 脚手架，但迁移通常不难，主要需要改动的是专家轨迹生成与评测预测文件的对接方式。

整体包含以下步骤：

1. 构建 SWE-smith 任务子集；
2. 为子集生成专家轨迹；
3. 用专家轨迹训练模型；
4. 在 SWE-bench（Lite/Verified/Multimodal）上评估模型。

如果你需要直接复用“任务实例 -> 轨迹/SFT -> 本地 SFT”的参数化命令模板，可先看：
`docs/guides/ts_three_pipelines.md`

## 构建 SWE-smith 子集

如果你直接使用完整的 [SWE-smith](https://huggingface.co/datasets/SWE-bench/SWE-smith) 数据集，规模会比较大。
通常建议先筛选出一个更可控的训练子集。示例逻辑如下：

```python
import json

from datasets import load_dataset
swesmith = load_dataset("SWE-bench/SWE-smith", split="train")

subset_name = "subset0"
def criteria(task_instance):
    return ".pr_" in task_instance["instance_id"] and \
        len(task_instance["FAIL_TO_PASS"]) <= 5 and \
        len(task_instance["FAIL_TO_PASS"]) >= 2
bugs = [x for x in swesmith if criteria(x)]
print(f"Found {len(bugs)} bugs that match criteria")
with open(f"logs/experiments/{subset_name}.json", "w") as f:
    json.dump(bugs, fp=f, indent=2)
```

## 生成专家轨迹

1. 克隆 [SWE-agent](https://github.com/SWE-agent/SWE-agent)，并按其官方安装文档完成环境配置。

2. 在 SWE-agent 仓库中创建到 `SWE-smith/agent/` 的软链接：
```bash
ln -s path/to/SWE-smith/agent/ .
```

3. 在 SWE-agent 中运行专家轨迹生成：
```bash
./agent/_gen_trajs.sh
```

请根据该脚本内容调整 `--instances.path`，指向你上一步生成的子集文件。

## 训练模型

上一步会在 `SWE-agent/trajectories/<username>/<run ID>/` 下生成每个任务实例的轨迹目录。

接下来我们要筛选出已解决（resolved）的轨迹，转换为 SFT 可用格式，再执行训练。

1.（在 SWE-smith 中）先对训练任务运行评测：
```bash
python -m swesmith.harness.eval \
    --dataset_path path/to/subset0.json \
    --predictions_path path/to/trajectories/<username>/<run ID>/preds.json \
    --run_id <run ID> \
    --workers 10 \
    --timeout 240
```

!!! tip "`preds.json`"
    如果没有 `preds.json`，可先执行：`sweagent merge-preds trajectories/<username>/<run ID>/`。

评测会生成 `logs/run_evaluation/<run ID>/`，其中 `report.json` 标记了哪些实例成功解决。

2.（在 SWE-smith 中）把轨迹转换为 SFT 格式：
```bash
python -m swesmith.train.traj_mgr.collect_trajs \
    --traj_dir path/to/trajectories/<username>/<run ID>/ \
    --eval_dir logs/run_evaluation/<run ID>/
```

该步骤会在 `trajectories_sft/` 下产出 `<run_id>.xml.jsonl`（文件名来自 `eval_dir` 目录名），可直接用于 SFT。

3.（原仓库云端流程）先上传到 Modal，再训练：
```bash
modal volume put <volume> trajectories_sft/<run_id>.xml.jsonl
```

然后修改 `configs/train/full_ft_qwen_7b.yml` 指向 Modal 上的数据文件，最后执行训练脚本：
```bash
./scripts/train_run_ft_torchtune.sh
```

## 评估

在 SWE-agent + SFT 后模型上运行 SWE-bench（Lite/Verified/Multimodal）评估。

1.（在 SWE-smith 中）修改 `scripts/train_serve_sglang.sh` 指向训练后模型并启动服务。

2.（在 SWE-agent 中）执行推理：
```bash
./agent/_infer_model.sh
```

请确认服务 URL 正确，并按需切换评测数据集。

3. 推理完成后，提交评测（可参考 [sb-cli](https://github.com/SWE-bench/sb-cli/tree/main)）：
```bash
sb-cli submit swe-bench_verified test \
    --predictions_path trajectories/<username>/<run ID>/preds.json \
    --run_id <run ID>
```

## 本地训练（不使用 Modal）

你可以在本机完整执行同样的 SFT 流程。仓库已提供 `Qwen2.5-Coder-7B-Instruct` 的本地脚本与配置。

### 1）将轨迹转换为 SFT jsonl

```bash
./scripts/train_prepare_sft_local.sh \
  /path/to/SWE-agent/trajectories/<user>/<run_id>/ \
  logs/run_evaluation/<run_id>/ \
  xml
```

该脚本会封装：
- `python -m swesmith.train.traj_mgr.collect_trajs ...`
- 可选长度统计校验（当你显式传入 `STATS_FILE` 时）：
  `python -m swesmith.train.traj_mgr.validate_len_stats ...`

默认行为：
- 输出目录：`trajectories_sft/`
- 若未设置 `STATS_FILE`，会跳过长度统计校验。

### 2）准备本地训练配置

使用 `configs/train/full_ft_qwen_7b_local.yml`。使用前需替换其中的占位符路径：
- `dataset.data_files`: 指向你的 resolved SFT JSONL 文件
- `output_dir`: 训练输出目录
- `<MODEL_DIR>`: 基础模型目录（如 `Qwen2.5-Coder-7B-Instruct`）

配置默认值：
- `max_seq_len: 32768`
- `packed: False`
- `conversation_style: openai`

### 3）执行本地 SFT

```bash
N_GPUS=1 CONFIG_PATH=configs/train/full_ft_qwen_7b_local.yml \
  ./scripts/train_run_ft_torchtune_local.sh
```

启动脚本会在训练前做两类校验：
- 配置中关键路径与权重分片是否存在；
- 若设置了 `LEN_STATS_FILE`，会对训练数据做长度统计一致性校验。

如需跳过长度统计校验，可显式设置：
```bash
LEN_STATS_FILE="" N_GPUS=1 CONFIG_PATH=configs/train/full_ft_qwen_7b_local.yml \
  ./scripts/train_run_ft_torchtune_local.sh
```

### 4）启动本地 checkpoint 服务（可选，用于 SWE-agent 评测）

```bash
MODEL_PATH=/path/to/outputs/<exp_name>/epoch_2 \
TOKENIZER_PATH=/path/to/Qwen2.5-Coder-7B-Instruct \
SERVED_MODEL_NAME=qwen2p5-coder-7b-sft-local \
TP_SIZE=1 \
./scripts/train_serve_sglang_local.sh
```

该脚本与原仓库行为保持一致：若 `MODEL_PATH` 下缺少 `config.json`，会自动从 `TOKENIZER_PATH` 复制。

兼容性说明：仓库仍保留旧命名（例如 `train.run_ft_torchtune.local.sh`）作为兼容入口；文档统一使用新的 `snake_case` 命名。

### 5）运行 SWE-agent 推理与评估

在 SWE-agent 中将 `_infer_model.sh` 指向本地 `sglang` 地址，推理完成后执行：

```bash
sb-cli submit swe-bench_verified test \
  --predictions_path /path/to/SWE-agent/trajectories/<user>/<run_id>/preds.json \
  --run_id <run_id>
```
