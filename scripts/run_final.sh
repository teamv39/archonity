#!/usr/bin/env bash
# Финальный запуск для организаторов (Linux x86_64, A100 40 ГБ) одной командой; подробности — docs/run_on_a100.md.
#
#   scripts/run_final.sh                                   # S0–S7 из hackaton/tt-challenge/scenarios
#   scripts/run_final.sh /path/S8.json /path/S9.json       # свои сценарии
#   OUT=out/submission.json scripts/run_final.sh ...       # куда писать выдачу (по умолчанию output/submission.json)
#   ARTIFACTS_DIR=artifacts/proj scripts/run_final.sh ...  # папка артефактов проекта (ir/, entity_ir.json), по умолчанию data/
#   PARSE_SOURCES=0 scripts/run_final.sh ...               # не пересобирать IR и entity_ir.json из исходников (взять готовые)
#
# 1. Модели: fetch_models.py докачивает в models/ недостающее и сверяет sha256 с models/manifest.json. llama.cpp —
#    релизная сборка манифеста, если не задан ARCHONITY_LLAMA_SERVER и llama-server нет в PATH.
# 2. Движок (ADR-008): ENGINE=rust (по умолчанию) — cargo build --release --locked в rust/ версией Rust из
#    rust/rust-toolchain.toml (нет cargo — ставится через rustup в ~/.cargo); ENGINE=python — весь конвейер в Python,
#    сборка не нужна. Rust не собрался или бинарник упал — run_eval.py делает тот же прогон на Python-исполнителе
#    (выдача та же, байт в байт) и пишет рамку ATTENTION (Р2).
#    При ENGINE=rust run_eval.py получает --parse-sources: IR тел методов (ir/) и entity_ir.json строит
#    archonity-parse (Rust, ADR-009) по исходникам и скелету в папку артефактов — каждый раз, около секунды, байт в байт
#    как закоммиченные в data/. Java-archparse в финальном запуске не участвует.
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
PARSE_SOURCES="${PARSE_SOURCES:-1}"
if [[ "$ENGINE" == rust ]]; then
    RUST_VERSION="$(sed -n 's/^channel = "\(.*\)"/\1/p' rust/rust-toolchain.toml)"
    echo "== 2/4 сборка Rust $RUST_VERSION: cargo build --release --locked"
    if ! command -v cargo >/dev/null 2>&1 && [[ -x "$HOME/.cargo/bin/cargo" ]]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    fi
    if ! command -v cargo >/dev/null 2>&1; then
        echo "cargo не найден: ставлю Rust $RUST_VERSION через rustup"
        if command -v curl >/dev/null 2>&1; then
            curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
                | sh -s -- -y --profile minimal --default-toolchain "$RUST_VERSION" || echo "!! rustup не установился" >&2
        else
            echo "!! нет curl для rustup" >&2
        fi
        export PATH="$HOME/.cargo/bin:$PATH"
    elif command -v rustup >/dev/null 2>&1; then
        # Версия из rust/rust-toolchain.toml; без rustup (cargo из пакетов ОС) собираем той, что есть
        rustup toolchain install "$RUST_VERSION" --profile minimal || echo "!! rustup не поставил $RUST_VERSION" >&2
    fi
    if ! command -v cc >/dev/null 2>&1 && ! command -v gcc >/dev/null 2>&1 && ! command -v clang >/dev/null 2>&1; then
        echo "!! нет компилятора C (cc, gcc или clang): он нужен tree-sitter, сборка Rust не пройдёт" >&2
    fi
    if ! (cd rust && cargo build --release --locked); then
        # Откат на Python делает run_eval.py: бинарника нет — тот же прогон на Python-исполнителе, рамка ATTENTION.
        # Старые бинарники собраны из другого кода, их не берём; IR и entity_ir.json — готовые из data/.
        echo "!! ВНИМАНИЕ: Rust не собрался — прогон пойдёт на Python, выдача та же. Свяжитесь с командой Archonity." >&2
        rm -f rust/target/release/archonity-exec rust/target/release/archonity-parse
        PARSE_SOURCES=0
    fi
fi

ARGS=(-o "$OUT" --engine "$ENGINE")
if [[ "$ENGINE" == rust && "$PARSE_SOURCES" != 0 ]]; then
    ARGS+=(--parse-sources)
fi
if [[ -n "${ARTIFACTS_DIR:-}" ]]; then
    ARGS+=(--artifacts-dir "$ARTIFACTS_DIR")
fi
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
