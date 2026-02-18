#!/usr/bin/env bash
set -euo pipefail

export DATA_BACKEND="${DATA_BACKEND:-mongo}"
export MONGO_URI="${MONGO_URI:-mongodb://localhost:27017}"
export MONGO_DB_NAME="${MONGO_DB_NAME:-dailylens}"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

"$PYTHON_BIN" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
