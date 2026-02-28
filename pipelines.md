# SWE-smith pipeline

## 0. 全局前置条件

### 0.1 必要环境变量

```bash
export SWESMITH_GH_OWNER_TYPE="user"              # user 或 org
export SWESMITH_ORG_GH="<your_github_user_or_org>"
export SWESMITH_ORG_DH="<your_dockerhub_user_or_org>"
export GITHUB_TOKEN="<your_github_pat>"
```

使用 `--issue-mode llm`：

```bash
export ANTHROPIC_API_KEY="<your_anthropic_key>"
export ANTHROPIC_AUTH_TOKEN="<your_anthropic_token>"
```

---

## Phase 1) 对TS仓库生成任务实例

主入口：`scripts/ts_standard_pipeline.py`

### 1.1 通用参数

```bash
PROFILE="ZodProfile"                               # 替换为任意其它TS profile
BUG_GEN_METHOD="all"                               # procedural / llm-modify / llm-rewrite / all
MAX_BUGS=20
VALIDATION_WORKERS=4
ISSUE_MODE="llm"                                   # llm / static / tests / pr / skip
ISSUE_CONFIG="configs/issue_gen/ig_v2.yaml"
ISSUE_WORKERS=1

uv run python scripts/ts_standard_pipeline.py \
  --profile "${PROFILE}" \
  --gh-owner-type "${SWESMITH_GH_OWNER_TYPE}" \
  --org-gh "${SWESMITH_ORG_GH}" \
  --org-dh "${SWESMITH_ORG_DH}" \
  --bug-gen-method "${BUG_GEN_METHOD}" \
  --max-bugs "${MAX_BUGS}" \
  --workers "${VALIDATION_WORKERS}" \
  --issue-mode "${ISSUE_MODE}" \
  --issue-config "${ISSUE_CONFIG}" \
  --issue-workers "${ISSUE_WORKERS}"
```

LLM bug 生成参数：

```bash
  --llm-model "anthropic/claude-3-5-sonnet-20241022" \
  --llm-config "configs/bug_gen/ts_modify.yml" \
  --llm-workers 1
```


---

## 2) phase 2：对任务实例生成完整修复轨迹，并转为SFT格式

### 2.0 网络代理（socat 转发）

SWE-agent 在 Docker 容器内运行，容器需要通过宿主机代理访问 GitHub 等外部服务。
确保宿主机已运行 socat 转发（监听 `172.17.0.1:10819`），然后在启动轨迹生成前设置：

```bash
export HTTP_PROXY=http://172.17.0.1:10819
export HTTPS_PROXY=http://172.17.0.1:10819
export ALL_PROXY=http://172.17.0.1:10819
export http_proxy=http://172.17.0.1:10819
export https_proxy=http://172.17.0.1:10819
export all_proxy=http://172.17.0.1:10819
export NO_PROXY=127.0.0.1
export no_proxy=127.0.0.1
```

> `172.17.0.1` 是 Docker 默认网桥的宿主机地址。socat 负责将容器的 HTTP 请求转发到宿主机的实际代理端口。

## 2.1 使用SWE-agent生成轨迹

使用 `SWE-smith/agent/_gen_trajs.sh`

```bash
export SWESMITH_ROOT="/abs/path/to/SWE-smith"
export INSTANCES_PATH="${SWESMITH_ROOT}/logs/agent_datasets/<repo_name>_final.json"
export OUTPUT_DIR="trajectories/${USER}/<run_id>"
export NUM_WORKERS=20
export MEMORY_LIMIT="10g"

./agent/_gen_trajs.sh
```

> `_gen_trajs.sh` 会使用 `agent/swesmith_gen_glm_ts.yaml` 运行 `sweagent run-batch`

若缺失 `preds.json`，执行：

```bash
sweagent merge-preds "${OUTPUT_DIR}"
```

## 2.2  评测轨迹

```bash
RUN_ID="<run_id>"                                  # 与 OUTPUT_DIR 末级目录保持一致
DATASET_PATH="logs/agent_datasets/<repo_name>_final.json"
PREDS_PATH="/abs/path/to/SWE-agent/${OUTPUT_DIR}/preds.json"

uv run python -m swesmith.harness.eval \
  --dataset_path "${DATASET_PATH}" \
  --predictions_path "${PREDS_PATH}" \
  --run_id "${RUN_ID}" \
  --workers 10
```

产物：`logs/run_evaluation/<run_id>/report.json`

## 2.3 转换为 SFT JSONL

```bash
TRAJ_DIR="/abs/path/to/SWE-agent/${OUTPUT_DIR}"
EVAL_DIR="logs/run_evaluation/${RUN_ID}"
OUT_DIR="/abs/path/to/SWE-smith/trajectories_sft"

OUT_DIR="${OUT_DIR}" ./scripts/train.prepare_sft_local.sh \
  "${TRAJ_DIR}" "${EVAL_DIR}" xml
```

产物：`trajectories_sft/<run_id>.xml.jsonl`

## 2.4 Resolved-only 过滤

从 `report.json` 读取 `ids_resolved`，只保留已解决的轨迹作为 SFT 训练数据。

```bash
RUN_ID="<run_id>"
SFT_FILE="trajectories_sft/${RUN_ID}.xml.jsonl"
REPORT_FILE="logs/run_evaluation/${RUN_ID}/report.json"
OUT_FILE="trajectories_sft/${RUN_ID}.resolved_only.xml.jsonl"

uv run python - <<'PY' "${SFT_FILE}" "${REPORT_FILE}" "${OUT_FILE}"
import json, sys
from pathlib import Path

sft_file = Path(sys.argv[1])
report_file = Path(sys.argv[2])
out_file = Path(sys.argv[3])

rows = [json.loads(x) for x in sft_file.read_text(encoding="utf-8").splitlines() if x.strip()]
report = json.loads(report_file.read_text(encoding="utf-8"))
resolved_ids = set(report.get("ids_resolved", []))
if not resolved_ids:
    raise ValueError(f"ids_resolved is empty in {report_file}")

resolved_rows = [r for r in rows if r.get("instance_id") in resolved_ids]
if not resolved_rows:
    raise ValueError("No resolved rows found in SFT file")

out_file.parent.mkdir(parents=True, exist_ok=True)
with out_file.open("w", encoding="utf-8") as f:
    for row in resolved_rows:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

print(f"Filtered: {len(resolved_rows)}/{len(rows)} resolved trajectories -> {out_file}")
PY
```

产物：`trajectories_sft/<run_id>.resolved_only.xml.jsonl`


## 3) 使用SFT 数据进行本地SFT训练

核心脚本：`scripts/train_run_ft_torchtune_local.sh`

## 3.1 准备训练配置

可以直接使用现有配置 `configs/train/full_ft_qwen_7b_local.yml`：

1. `dataset.data_files`：指向 2.4 产出的 resolved SFT JSONL；
2. `checkpointer.checkpoint_dir`：基础模型目录；
3. `tokenizer.path` + `tokenizer.merges_file`：对应 tokenizer；
4. `output_dir`：训练输出目录。





