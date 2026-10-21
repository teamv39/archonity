#!/usr/bin/env bash
# Ручной запуск llama-server под Linux (A100 40 ГБ): все слои на GPU, без -ncmoe.
# Обычно не нужен: клиент (engine/grounding/llm.py) сам поднимает сервер на первом промахе кеша и гасит при выходе.
# Скрипт — для ручной проверки и пересборки кеша. Параметры — как SERVER_ARGS в engine/grounding/llm.py.
#
#   scripts/start_llm.sh                       # модель из models/ (python scripts/fetch_models.py), порт 8080
#   PORT=8090 scripts/start_llm.sh -ncmoe 7    # аргументы скрипта и ARCHONITY_LLAMA_ARGS идут после умолчаний
#
# Бинарник: ARCHONITY_LLAMA_SERVER, models/llama.cpp/llama-server (fetch_models.py --llama-cpp), llama-server в PATH,
# единый CLI `llama server`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${MODEL:-$ROOT/models/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf}"
PORT="${PORT:-8080}"

if [[ -n "${ARCHONITY_LLAMA_SERVER:-}" ]]; then
    BIN="$ARCHONITY_LLAMA_SERVER"
elif [[ -x "$ROOT/models/llama.cpp/llama-server" ]]; then
    BIN="$ROOT/models/llama.cpp/llama-server"
elif command -v llama-server >/dev/null 2>&1; then
    BIN=llama-server
else
    BIN=llama
fi
CMD=("$BIN")
if [[ "$(basename "$BIN")" == llama ]]; then
    CMD+=(server)
fi

# shellcheck disable=SC2086  # ARCHONITY_LLAMA_ARGS — список аргументов через пробел
exec "${CMD[@]}" -m "$MODEL" --host 127.0.0.1 --port "$PORT" \
    --fit off -ngl 999 -fa 1 -ctk q8_0 -ctv q8_0 -c 32768 ${ARCHONITY_LLAMA_ARGS:-} "$@"
