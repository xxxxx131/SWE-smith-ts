#!/bin/bash
set -euo pipefail

CONFIG_PATH="${CONFIG_PATH:-configs/train/full_ft_qwen_7b_local.yml}"
N_GPUS="${N_GPUS:-1}"
PYTHON_BIN="${PYTHON_BIN:-python}"
LEN_STATS_FILE="${LEN_STATS_FILE:-}"
MAX_SEQ_LEN="${MAX_SEQ_LEN:-32768}"

if ! command -v tune >/dev/null 2>&1; then
  echo "[local_ft] ERROR: 'tune' command not found in PATH." >&2
  echo "[local_ft] Install torchtune CLI in your current environment first." >&2
  exit 1
fi

if [ ! -f "$CONFIG_PATH" ]; then
  echo "[local_ft] ERROR: config file not found: $CONFIG_PATH" >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY' "$CONFIG_PATH"
import sys
from pathlib import Path
import yaml

cfg_path = Path(sys.argv[1])
cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

def must_exist(path_value: str, label: str) -> None:
    p = Path(path_value)
    if not p.exists():
        raise FileNotFoundError(f"[local_ft] Missing {label}: {p}")

must_exist(cfg["tokenizer"]["path"], "tokenizer.path")
must_exist(cfg["tokenizer"]["merges_file"], "tokenizer.merges_file")
must_exist(cfg["checkpointer"]["checkpoint_dir"], "checkpointer.checkpoint_dir")
must_exist(cfg["dataset"]["data_files"], "dataset.data_files")

for ckpt in cfg["checkpointer"]["checkpoint_files"]:
    must_exist(str(Path(cfg["checkpointer"]["checkpoint_dir"]) / ckpt), f"checkpoint_file[{ckpt}]")

print("[local_ft] Config path checks passed.")
PY

DATA_FILE="$("$PYTHON_BIN" - <<'PY' "$CONFIG_PATH"
import sys
from pathlib import Path
import yaml

cfg_path = Path(sys.argv[1])
cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
print(cfg["dataset"]["data_files"])
PY
)"

if [ -n "$LEN_STATS_FILE" ]; then
  if [ ! -f "$LEN_STATS_FILE" ]; then
    echo "[local_ft] ERROR: LEN_STATS_FILE not found: $LEN_STATS_FILE" >&2
    exit 1
  fi
  echo "[local_ft] Validating length stats before training"
  "$PYTHON_BIN" -m swesmith.train.traj_mgr.validate_len_stats \
    --data_file "$DATA_FILE" \
    --stats_file "$LEN_STATS_FILE" \
    --max_seq_len "$MAX_SEQ_LEN"
fi

echo "[local_ft] Running torchtune locally"
echo "[local_ft] CONFIG_PATH=$CONFIG_PATH"
echo "[local_ft] N_GPUS=$N_GPUS"
echo "[local_ft] CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-<unset>}"

tune run --nnodes 1 --nproc_per_node "$N_GPUS" full_finetune_distributed --config "$CONFIG_PATH"
