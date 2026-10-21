#!/usr/bin/env bash
# Финальный запуск для организаторов (Linux x86_64, A100 40 ГБ) одной командой; подробности — docs/run_on_a100.md.
#
#   scripts/run_final.sh                                   # S0–S7 из hackaton/tt-challenge/scenarios
#   scripts/run_final.sh /path/S8.json /path/S9.json       # свои сценарии
#   OUT=out/submission.json scripts/run_final.sh ...       # куда писать выдачу (по умолчанию output/submission.json)
#
# 1. Модели: fetch_models.py докачивает в models/ недостающее и сверяет sha256 с models/manifest.json. llama.cpp —
#    релизная сборка манифеста, если не задан ARCHONITY_LLAMA_SERVER и llama-server нет в PATH.
# 2. Движок (ADR-008): ENGINE=rust (по умолчанию) — cargo build --release --locked в rust/, при отсутствии cargo
#    ставится stable через rustup в ~/.cargo; ENGINE=python — весь конвейер в Python, сборка не нужна. Сбой сборки
#    Rust не переключает на Python: run_eval.py пишет пустую выдачу с рамкой ATTENTION (Р2).
# 3. run_eval.py: ответы из кеша; на промахе клиент сам поднимает llama-server и гасит его при выходе.
# 4. Итог: sha256 выдачи, режим M1 (m1_report.json рядом с выдачей) и последней — рамка ATTENTION.txt, если она есть.
# Сбой моделей прогон не останавливает: выдача строится всегда (roadmap, Р2), но с заметным предупреждением.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONUTF8=1
OUT="${OUT:-output/submission.json}"
if [[ -n "${PYTHON:-}" ]]; then
    PY="$PYTHON"
elif [[ -x .venv/bin/python ]]; then
    PY=.venv/bin/python
else
    PY=python3
fi

FETCH=()
if [[ -z "${ARCHONITY_LLAMA_SERVER:-}" ]] && ! command -v llama-server >/dev/null 2>&1; then
    FETCH+=(--llama-cpp)
fi
echo "== 1/4 модели: $PY scripts/fetch_models.py ${FETCH[*]-}"
if ! "$PY" scripts/fetch_models.py ${FETCH[@]+"${FETCH[@]}"}; then
    echo "!! ВНИМАНИЕ: модели не прошли проверку — новые сценарии пойдут без LLM, качество ниже. Свяжитесь с командой Archonity." >&2
fi

ENGINE="${ENGINE:-rust}"
if [[ "$ENGINE" == rust ]]; then
    echo "== 2/4 сборка Rust: cargo build --release --locked"
    if ! command -v cargo >/dev/null 2>&1 && [[ -x "$HOME/.cargo/bin/cargo" ]]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    fi
    if ! command -v cargo >/dev/null 2>&1; then
        echo "cargo не найден: ставлю stable через rustup"
        if command -v curl >/dev/null 2>&1; then
            curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable \
                || echo "!! rustup не установился" >&2
        else
            echo "!! нет curl для rustup" >&2
        fi
        export PATH="$HOME/.cargo/bin:$PATH"
    fi
    if ! (cd rust && cargo build --release --locked); then
        echo "!! ВНИМАНИЕ: Rust не собрался — выдача будет пустой с рамкой ATTENTION. Свяжитесь с командой Archonity." >&2
    fi
fi

ARGS=(-o "$OUT" --engine "$ENGINE")
if (($#)); then
    ARGS+=(--scenarios "$@")
fi
echo "== 3/4 прогон: $PY run_eval.py ${ARGS[*]}"
# Выдача, отчёт M1 и рамка прошлого прогона в той же папке не должны выдать себя за этот, если run_eval.py упадёт
rm -f "$OUT" "$(dirname "$OUT")/m1_report.json" "$(dirname "$OUT")/ATTENTION.txt"
"$PY" run_eval.py "${ARGS[@]}"
RC=$?

echo "== 4/4 итог"
if [[ ! -f "$OUT" ]]; then
    echo "!! выдача $OUT не создана (код $RC). Свяжитесь с командой Archonity." >&2
    exit $((RC ? RC : 1))
fi
sha256sum "$OUT"
"$PY" - "$(dirname "$OUT")/m1_report.json" <<'EOF'
import json
import sys

try:
    r = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError):
    sys.exit(0)
llm = r["llm"]
print(f"M1: режим {r['mode']}, шагов {r['steps']}, выбрано моделью {r['steps_by_llm']}; ответы LLM: из кеша "
      f"{llm['from_cache']}, от сервера {llm['from_server']}, без ответа {llm['missing']}, ошибок {llm['errors']}")
EOF
# Рамка ошибки (Р2) — последней: run_eval.py пишет ATTENTION.txt, если M1 не в режиме full или были сбои
ATT="$(dirname "$OUT")/ATTENTION.txt"
if [[ -f "$ATT" ]]; then
    cat "$ATT" >&2
    cat "$ATT"
fi
exit "$RC"
