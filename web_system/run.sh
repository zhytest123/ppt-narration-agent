#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
RUNTIME_DIR="$ROOT_DIR/runtime/ChatTTS-OpenVoice-Tools"

DEFAULT_CHATTTS_PYTHON="$(command -v python3 || command -v python)"
DEFAULT_CHATTTS_BIN="$(dirname "$DEFAULT_CHATTTS_PYTHON")"

export CHAT_TTS_PYTHON="${CHAT_TTS_PYTHON:-$DEFAULT_CHATTTS_PYTHON}"
export CHAT_TTS_DEVICE="${CHAT_TTS_DEVICE:-cpu}"
export CHAT_TTS_SOURCE_ROOT="${CHAT_TTS_SOURCE_ROOT:-$RUNTIME_DIR}"

if [[ -n "${CHAT_TTS_BIN:-}" ]]; then
  export PATH="$CHAT_TTS_BIN:$PATH"
elif [[ -n "$DEFAULT_CHATTTS_BIN" ]]; then
  export PATH="$DEFAULT_CHATTTS_BIN:$PATH"
fi

cd "$BACKEND_DIR"
if [[ "${DEV_RELOAD:-0}" == "1" ]]; then
  exec uvicorn app:app --reload --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
else
  exec uvicorn app:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
fi
