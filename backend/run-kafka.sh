#!/usr/bin/env bash
set -euo pipefail

export EVENT_PIPELINE_BACKEND="${EVENT_PIPELINE_BACKEND:-kafka}"
export KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:19092}"
export KAFKA_TOPIC="${KAFKA_TOPIC:-user-interactions}"
export KAFKA_GROUP_ID="${KAFKA_GROUP_ID:-dailylens-ranker}"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

"$PYTHON_BIN" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
