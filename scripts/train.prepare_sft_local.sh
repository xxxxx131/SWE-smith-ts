#!/bin/bash
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: $0 <traj_dir> <eval_dir> [style]" >&2
  echo "Example: $0 /path/to/trajectories/user/run_id logs/run_evaluation/run_id xml" >&2
  exit 1
fi

TRAJ_DIR="$1"
EVAL_DIR="$2"
STYLE="${3:-xml}"

OUT_DIR="${OUT_DIR:-trajectories_sft}"
STATS_FILE="${STATS_FILE:-}"
MAX_SEQ_LEN="${MAX_SEQ_LEN:-32768}"
PYTHON_BIN="${PYTHON_BIN:-python}"

mkdir -p "$OUT_DIR"

echo "[prepare_sft_local] Collecting trajectories"
"$PYTHON_BIN" -m swesmith.train.traj_mgr.collect_trajs \
  --traj_dir "$TRAJ_DIR" \
  --eval_dir "$EVAL_DIR" \
  --style "$STYLE" \
  --out_dir "$OUT_DIR"

DATA_FILE="$OUT_DIR/$(basename "$EVAL_DIR").$STYLE.jsonl"
if [ ! -f "$DATA_FILE" ]; then
  echo "[prepare_sft_local] ERROR: expected output not found: $DATA_FILE" >&2
  exit 1
fi

if [ -n "$STATS_FILE" ]; then
  if [ ! -f "$STATS_FILE" ]; then
    echo "[prepare_sft_local] ERROR: stats file not found: $STATS_FILE" >&2
    exit 1
  fi
  echo "[prepare_sft_local] Validating length stats"
  "$PYTHON_BIN" -m swesmith.train.traj_mgr.validate_len_stats \
    --data_file "$DATA_FILE" \
    --stats_file "$STATS_FILE" \
    --max_seq_len "$MAX_SEQ_LEN"
else
  echo "[prepare_sft_local] WARN: STATS_FILE unset, skip validation"
fi

echo "[prepare_sft_local] Done: $DATA_FILE"
