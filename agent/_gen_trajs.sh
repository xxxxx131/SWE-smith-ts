#!/bin/bash
set -euo pipefail

# Resolve project root and load .env if present.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [ -z "${SWESMITH_ROOT:-}" ]; then
  if [ -d "${PROJECT_ROOT}/logs/agent_datasets" ]; then
    SWESMITH_ROOT="${PROJECT_ROOT}"
  elif [ -d "${PROJECT_ROOT}/../SWE-smith/logs/agent_datasets" ]; then
    SWESMITH_ROOT="$(cd "${PROJECT_ROOT}/../SWE-smith" && pwd)"
  else
    SWESMITH_ROOT="${PROJECT_ROOT}"
  fi
fi
cd "${PROJECT_ROOT}"
for env_file in "${PROJECT_ROOT}/.env" "${SWESMITH_ROOT}/.env"; do
  if [ -f "${env_file}" ]; then
    set -a
    # shellcheck disable=SC1091
    source "${env_file}"
    set +a
  fi
done

# Override with environment variables when needed.
INSTANCES_PATH="${INSTANCES_PATH:-${SWESMITH_ROOT}/logs/agent_datasets/colinhacks__zod.v3.23.8_final.json}"
RUN_USER="${USER:-$(id -un)}"
OUTPUT_DIR="${OUTPUT_DIR:-trajectories/${RUN_USER}/swesmith_gen__glm-4.6__t-0.00_p-1.00__c.2.00__colinhacks__zod.v3.23.8_final}"
NUM_WORKERS="${NUM_WORKERS:-20}"
MEMORY_LIMIT="${MEMORY_LIMIT:-10g}"
export OUTPUT_DIR

# Normalize proxy env for LiteLLM/httpx:
# - If ALL_PROXY is a SOCKS URL but socksio is unavailable, fall back to
#   HTTP(S)_PROXY (if present) instead of repeatedly failing LM calls.
PROXY_ALL="${ALL_PROXY:-${all_proxy:-}}"
PROXY_ALL_LC="$(printf '%s' "${PROXY_ALL}" | tr '[:upper:]' '[:lower:]')"
if [[ "${PROXY_ALL_LC}" == socks*://* ]]; then
  if python - <<'PY'
import importlib.util
import sys
sys.exit(0 if importlib.util.find_spec("socksio") else 1)
PY
  then
    echo "[proxy-normalize] SOCKS proxy detected; socksio is available."
  else
    if [ -n "${HTTP_PROXY:-${http_proxy:-}}" ] || [ -n "${HTTPS_PROXY:-${https_proxy:-}}" ]; then
      echo "[proxy-normalize] WARN ALL_PROXY is SOCKS but socksio is missing; unsetting ALL_PROXY/all_proxy and using HTTP(S)_PROXY."
      unset ALL_PROXY all_proxy
    else
      echo "[proxy-normalize] ERROR SOCKS proxy configured but socksio is missing and no HTTP(S)_PROXY fallback is set."
      echo "[proxy-normalize] Fix: install 'httpx[socks]' or set HTTP_PROXY/HTTPS_PROXY to a reachable HTTP proxy."
      exit 5
    fi
  fi
fi

if [ ! -f "${INSTANCES_PATH}" ]; then
  echo "ERROR: instances file not found: ${INSTANCES_PATH}"
  echo "Please set INSTANCES_PATH explicitly."
  exit 1
fi

# Preflight proxy checks to fail fast with actionable diagnostics.
# Set SKIP_PROXY_CHECK=1 to bypass.
if [ "${SKIP_PROXY_CHECK:-0}" != "1" ]; then
  python - <<'PY'
import json
import os
import socket
import subprocess
import sys
from urllib.parse import urlparse

proxy_keys = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]

raw_values = [(k, os.getenv(k, "").strip()) for k in proxy_keys if os.getenv(k, "").strip()]
if not raw_values:
    print("[proxy-check] no proxy configured; skip")
    raise SystemExit(0)

endpoints = []
for key, value in raw_values:
    parsed = urlparse(value if "://" in value else f"http://{value}")
    if not parsed.hostname or not parsed.port:
        print(f"[proxy-check] WARN {key} has no host/port, skip endpoint check: {value}")
        continue
    endpoints.append((key, value, parsed.hostname, int(parsed.port)))

if not endpoints:
    print("[proxy-check] proxy vars present but no parsable endpoints; continue")
    raise SystemExit(0)

def can_connect(host: str, port: int, timeout: float = 1.5) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()

failed = False
localhost_ports: set[int] = set()
checked: set[tuple[str, int]] = set()
for key, _, host, port in endpoints:
    if (host, port) in checked:
        continue
    checked.add((host, port))
    ok = can_connect(host, port)
    print(f"[proxy-check] {'OK' if ok else 'FAIL'} {host}:{port} ({key})")
    if not ok:
        failed = True
    if host in {"127.0.0.1", "localhost"}:
        localhost_ports.add(port)

if failed:
    print(
        "[proxy-check] ERROR: Some proxy endpoints are unreachable from host. "
        "Start your proxy first or unset broken proxy env vars."
    )
    raise SystemExit(2)

if localhost_ports:
    bridge_gateway = None
    try:
        inspect = subprocess.run(
            ["docker", "network", "inspect", "bridge"],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(inspect.stdout)
        bridge_gateway = data[0].get("IPAM", {}).get("Config", [{}])[0].get("Gateway")
    except Exception as e:
        print(f"[proxy-check] WARN cannot inspect docker bridge gateway: {e}")

    if bridge_gateway:
        for port in sorted(localhost_ports):
            ok = can_connect(str(bridge_gateway), port)
            print(
                f"[proxy-check] {'OK' if ok else 'FAIL'} bridge {bridge_gateway}:{port} "
                "(required when proxy host is localhost)"
            )
            if not ok:
                print(
                    "[proxy-check] ERROR: Container cannot reach localhost proxy via bridge gateway. "
                    "Bind proxy to 0.0.0.0 (or bridge IP), or use a reachable proxy host."
                )
                raise SystemExit(3)
PY
else
  echo "[proxy-check] skipped by SKIP_PROXY_CHECK=1"
fi

sweagent run-batch --num_workers "${NUM_WORKERS}" \
    --instances.deployment.docker_args=--memory="${MEMORY_LIMIT}" \
    --config agent/swesmith_gen_glm_ts.yaml \
    --instances.path "${INSTANCES_PATH}" \
    --output_dir "${OUTPUT_DIR}" \
    --random_delay_multiplier=1 \
    --agent.model.temperature 0.0

# Post-check: fail fast when generation produced no predictions.
python - <<'PY'
from pathlib import Path
import os
import sys
import json

out_dir = Path(os.environ["OUTPUT_DIR"])
preds = list(out_dir.rglob("*.pred"))
preds_json = out_dir / "preds.json"
if not preds:
    print(f"[traj-check] ERROR: no .pred files found under {out_dir}")
    print("[traj-check] Generation failed before agent submission (often env/proxy/repo reset).")
    status_file = out_dir / "run_batch_exit_statuses.yaml"
    if status_file.exists():
        print(f"[traj-check] Check status summary: {status_file}")
    sys.exit(4)
status_file = out_dir / "run_batch_exit_statuses.yaml"
if status_file.exists():
    try:
        from ruamel.yaml import YAML

        data = YAML(typ="safe").load(status_file.read_text()) or {}
        by_status = data.get("instances_by_exit_status", {}) or {}
        counts = {str(k): len(v or []) for k, v in by_status.items()}
        total = sum(counts.values())
        success = sum(
            c
            for k, c in counts.items()
            if any(tok in k.lower() for tok in ("submitted", "success", "solved"))
        )
        failure = sum(
            c
            for k, c in counts.items()
            if any(tok in k.lower() for tok in ("error", "exception", "runtimeerror", "fail"))
        )
        if total > 0 and success == 0 and failure == total:
            print(f"[traj-check] ERROR: all instances failed: {counts}")
            sys.exit(5)
    except Exception as e:
        print(f"[traj-check] WARN could not parse {status_file}: {e}")
if not preds_json.exists():
    print(f"[traj-check] WARN: {preds_json} not found yet. You can run:")
    print(f"  sweagent merge-preds {out_dir}")
else:
    try:
        parsed = json.loads(preds_json.read_text())
        if isinstance(parsed, dict):
            non_empty = sum(1 for v in parsed.values() if str(v.get("model_patch", "")).strip())
            print(f"[traj-check] non-empty model_patch count: {non_empty}/{len(parsed)}")
    except Exception as e:
        print(f"[traj-check] WARN failed to inspect preds.json: {e}")
print(f"[traj-check] OK: found {len(preds)} prediction files.")
PY

# Required before running:
# export ZAI_API_KEY="<your glm api key>"
