#!/usr/bin/env bash
# Финальный запуск для организаторов (Linux x86_64, A100 40 ГБ) одной командой; подробности — docs/run_on_a100.md.
#
#   scripts/run_final.sh                                   # S0–S7 из hackaton/tt-challenge/scenarios
#   scripts/run_final.sh /path/S8.json /path/S9.json       # свои сценарии
#   OUT=out/submission.json scripts/run_final.sh ...       # куда писать выдачу (по умолчанию output/submission.json)
#
# 1. Модели: fetch_models.py докачивает в models/ недостающее и сверяет sha256 с models/manifest.json. llama.cpp —
#    релизная сборка манифеста, если не задан ARCHONITY_LLAMA_SERVER и llama-server нет в PATH.
# 2. run_eval.py: ответы из кеша; на промахе клиент сам поднимает llama-server и гасит его при выходе.
# 3. Итог: sha256 выдачи и режим M1 (m1_report.json рядом с выдачей).
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
echo "== 1/3 модели: $PY scripts/fetch_models.py ${FETCH[*]-}"
if ! "$PY" scripts/fetch_models.py ${FETCH[@]+"${FETCH[@]}"}; then
    echo "!! ВНИМАНИЕ: модели не прошли проверку — новые сценарии пойдут без LLM, качество ниже. Свяжитесь с командой Archonity." >&2
fi

ARGS=(-o "$OUT")
if (($#)); then
    ARGS+=(--scenarios "$@")
fi
echo "== 2/3 прогон: $PY run_eval.py ${ARGS[*]}"
"$PY" run_eval.py "${ARGS[@]}"
RC=$?

echo "== 3/3 итог"
if [[ ! -f "$OUT" ]]; then
    echo "!! выдача $OUT не создана (код $RC). Свяжитесь с командой Archonity." >&2
    exit "$RC"
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
if r["mode"] != "full":
    print(f"!! ВНИМАНИЕ: выдача построена не целиком моделью (режим {r['mode']}). Свяжитесь с командой Archonity.",
          file=sys.stderr)
EOF
exit "$RC"
