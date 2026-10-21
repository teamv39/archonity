# Запуск локальной LLM для M1 (заземление шагов) и судьи M4 на видеокарте 16 ГБ.
# Параметры и замер скорости — docs/researches/model_selection.md, раздел 2.
# llama.cpp — единый CLI: сервер запускается как `llama server`.
#
#   powershell -File scripts/start_llm.ps1
#   powershell -File scripts/start_llm.ps1 -Model D:\models\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf -Port 8080
#   powershell -File scripts/start_llm.ps1 -Ncmoe 11   # видеопамять частично занята: больше экспертов MoE в RAM
#
# Модель по умолчанию — из models/ (python scripts/fetch_models.py; уже скачанный файл: --from <путь к .gguf>).
# Клиент (engine/grounding/llm.py) ходит на ARCHONITY_LLM_URL, по умолчанию http://127.0.0.1:8080, и без этого
# скрипта сам поднимает сервер на промахе кеша; на 16 ГБ для автозапуска нужно ARCHONITY_LLAMA_ARGS="-ncmoe 7".
# Эмбеддер и LLM вместе в 16 ГБ VRAM не помещаются: эмбеддер рядом с сервером — ARCHONITY_EMBED_DEVICE=cpu.
param(
    [string]$Model = (Join-Path $PSScriptRoot "..\models\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"),
    [int]$Port = 8080,
    [int]$Ncmoe = 7
)

llama server -m $Model --fit off -ngl 999 -ncmoe $Ncmoe -fa 1 -ctk q8_0 -ctv q8_0 -c 32768 `
    -t 8 -tb 16 --prio 2 --poll 100 --port $Port
