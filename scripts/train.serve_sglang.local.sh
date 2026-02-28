#!/bin/bash
set -euo pipefail

MODEL_PATH="${MODEL_PATH:?ERROR: set MODEL_PATH to your fine-tuned checkpoint directory}"
TOKENIZER_PATH="${TOKENIZER_PATH:?ERROR: set TOKENIZER_PATH to your base model directory}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-qwen2.5-coder-7b-sft-local}"
PORT="${PORT:-3000}"
HOST="${HOST:-0.0.0.0}"
TP_SIZE="${TP_SIZE:-1}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-32768}"
API_KEY="${API_KEY:-swesmith}"
PYTHON_BIN="${PYTHON_BIN:-python}"
SGLANG_EXTRA_ARGS="${SGLANG_EXTRA_ARGS:-}"

# Prefer a modern toolchain colocated with the selected Python env.
# This avoids nvcc host-compiler issues (e.g. missing C++20 <concepts>).
PYTHON_EXE="$PYTHON_BIN"
if [[ "$PYTHON_EXE" != /* ]]; then
  PYTHON_EXE="$(command -v "$PYTHON_BIN" || true)"
fi
if [ -n "$PYTHON_EXE" ]; then
  PYTHON_BIN_DIR="$(cd "$(dirname "$PYTHON_EXE")" && pwd)"
  if [ -x "$PYTHON_BIN_DIR/x86_64-conda-linux-gnu-g++" ]; then
    export CC="${CC:-$PYTHON_BIN_DIR/x86_64-conda-linux-gnu-gcc}"
    export CXX="${CXX:-$PYTHON_BIN_DIR/x86_64-conda-linux-gnu-g++}"
  fi
fi
if [ -n "${CXX:-}" ]; then
  export CUDAHOSTCXX="${CUDAHOSTCXX:-$CXX}"
  # nvcc may still fall back to system g++ unless -ccbin is explicit.
  if [[ " ${NVCC_PREPEND_FLAGS:-} " != *" -ccbin "* ]]; then
    export NVCC_PREPEND_FLAGS="-ccbin ${CUDAHOSTCXX}${NVCC_PREPEND_FLAGS:+ ${NVCC_PREPEND_FLAGS}}"
  fi
fi

# Keep build caches off root partition when /data is available.
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
export TVM_FFI_CACHE_DIR="${TVM_FFI_CACHE_DIR:-$XDG_CACHE_HOME/tvm-ffi}"
mkdir -p "$TVM_FFI_CACHE_DIR"

# Keep temporary build files off root partition.
export TMPDIR="${TMPDIR:-/tmp}"
mkdir -p "$TMPDIR"

if [ ! -d "$MODEL_PATH" ]; then
  echo "[serve_sglang_local] ERROR: model path not found: $MODEL_PATH" >&2
  exit 1
fi

if [ ! -d "$TOKENIZER_PATH" ]; then
  echo "[serve_sglang_local] ERROR: tokenizer path not found: $TOKENIZER_PATH" >&2
  exit 1
fi

if [ ! -f "$MODEL_PATH/config.json" ]; then
  if [ ! -f "$TOKENIZER_PATH/config.json" ]; then
    echo "[serve_sglang_local] ERROR: config.json not found in model/tokenizer path." >&2
    exit 1
  fi
  echo "[serve_sglang_local] Copying config.json from tokenizer to model path"
  cp "$TOKENIZER_PATH/config.json" "$MODEL_PATH/config.json"
fi

echo "[serve_sglang_local] MODEL_PATH=$MODEL_PATH"
echo "[serve_sglang_local] TOKENIZER_PATH=$TOKENIZER_PATH"
echo "[serve_sglang_local] HOST=$HOST PORT=$PORT TP_SIZE=$TP_SIZE CONTEXT_LENGTH=$CONTEXT_LENGTH"
echo "[serve_sglang_local] CC=${CC:-<unset>} CXX=${CXX:-<unset>} CUDAHOSTCXX=${CUDAHOSTCXX:-<unset>}"
echo "[serve_sglang_local] NVCC_PREPEND_FLAGS=${NVCC_PREPEND_FLAGS:-<unset>}"
echo "[serve_sglang_local] XDG_CACHE_HOME=$XDG_CACHE_HOME TVM_FFI_CACHE_DIR=$TVM_FFI_CACHE_DIR"
echo "[serve_sglang_local] TMPDIR=$TMPDIR"
if [ -n "$SGLANG_EXTRA_ARGS" ]; then
  echo "[serve_sglang_local] SGLANG_EXTRA_ARGS=$SGLANG_EXTRA_ARGS"
fi

cmd=(
  "$PYTHON_BIN" -m sglang.launch_server
  --model-path "$MODEL_PATH"
  --tokenizer-path "$TOKENIZER_PATH"
  --tp-size "$TP_SIZE"
  --port "$PORT"
  --host "$HOST"
  --served-model-name "$SERVED_MODEL_NAME"
  --context-length "$CONTEXT_LENGTH"
  --api-key "$API_KEY"
)

if [ -n "$SGLANG_EXTRA_ARGS" ]; then
  # shellcheck disable=SC2206
  extra_args=( $SGLANG_EXTRA_ARGS )
  cmd+=( "${extra_args[@]}" )
fi

"${cmd[@]}"
