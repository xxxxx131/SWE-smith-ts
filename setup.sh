set -euo pipefail

PROJECT_DIR="/data/k8s/yrx/SWE-smith"

# Install UV into project-local location if you haven't already
export UV_INSTALL_DIR="${PROJECT_DIR}/.local"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="${UV_INSTALL_DIR}/bin:${PATH}"

# Create and activate virtual environment in the project directory
VENV_DIR="${PROJECT_DIR}/.venv"
uv venv --python 3.12 "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"
uv sync