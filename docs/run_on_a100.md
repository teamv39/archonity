# Запуск на A100 40 ГБ

Инструкция для финального запуска у организаторов: Linux x86_64, одна A100 40 ГБ. Версии моделей и `llama.cpp` закреплены в [`models/manifest.json`](../models/manifest.json), версии Python-пакетов — в `uv.lock`.

## Одна команда

```bash
uv sync --locked && source .venv/bin/activate      # или: pip install -r requirements.txt (Python 3.11+)
scripts/run_final.sh <файлы сценариев>              # без аргументов — S0–S7
```

`scripts/run_final.sh` делает три шага:

1. `scripts/fetch_models.py` докачивает в `models/` недостающие файлы и сверяет sha256 каждого с манифестом. Уже лежащие файлы не перекачиваются. `llama.cpp` качается, если не задан `ARCHONITY_LLAMA_SERVER` и `llama-server` нет в `PATH`.
2. `run_eval.py --scenarios <файлы> -o output/submission.json`. Перед ним скрипт удаляет выдачу, `m1_report.json` и `ATTENTION.txt` прошлого прогона в той же папке: если `run_eval.py` упадёт, итог не покажет старые. Выдачи нет — код выхода не 0. Ответы берутся из кеша. На первом промахе клиент сам поднимает `llama-server`, ждёт `/health` и гасит сервер при выходе.
3. Итог: sha256 выдачи, режим M1 из `m1_report.json` и последней — рамка из `ATTENTION.txt`, если он есть.

Выдача строится всегда, код выхода 0 (roadmap, Р2):

- исключение на шаге — шаг без рёбер, остальные шаги идут дальше; исключение в сценарии — пустой блок `{"edges": []}`;
- конвейер не собрался — повтор без LLM и эмбеддера, не собрался и так — `submission.json` с пустыми блоками всех сценариев;
- LLM не ответила — шаг берёт первый кандидат поиска (режим M1 `partial` или `emergency`).

Если хоть что-то из этого случилось, рядом с выдачей появляется `ATTENTION.txt`: что сломалось, на каких шагах, контакт команды. Тот же текст в рамке — последние строки stdout и stderr; список сбоев ещё в `m1_report.json`, поле `failures`. Чистый прогон `ATTENTION.txt` не оставляет. Путь выдачи меняет переменная `OUT`, интерпретатор — `PYTHON`.

Пакет организаторов (скелет, исходники Train Ticket, сценарии) ожидается в `hackaton/tt-challenge/`. Другие пути задаются флагами `run_eval.py`: `--skeleton`, `--targets`, `--scenarios`.

## Требования

- Linux x86_64, NVIDIA A100 40 ГБ, драйвер 570+ (CUDA 12.8).
- Python 3.11+ (кеши и рекорд построены на 3.13) или [`uv`](https://docs.astral.sh/uv/): он сам поставит нужный Python.
- Около 27 ГБ на диске под `models/` и доступ к Hugging Face и GitHub на время `fetch_models.py`.
- Прогону S0–S7 из кеша видеокарта и модели не нужны.

## Версии

| Что | Версия | Размер |
|---|---|---|
| LLM | `unsloth/Qwen3.6-35B-A3B-GGUF`, файл `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf`, ревизия `a483e9e6cbd5` | 17.7 ГБ |
| Эмбеддер | `Qwen/Qwen3-Embedding-4B`, ревизия `5cf2132abc99` | 8.1 ГБ |
| llama.cpp | сборка `b11671`, commit `ba3c05f71da8`: релизные архивы `ubuntu-cuda-12.8-x64` и CUDA runtime | 0.8 ГБ |
| torch | `2.11.0+cu128` с `download.pytorch.org` | — |

sha256 каждого файла и URL архивов — в манифесте. `python scripts/fetch_models.py --check` проверяет `models/` без скачивания.

## llama.cpp

- По умолчанию берётся релизная сборка манифеста: `fetch_models.py --llama-cpp` распаковывает её в `models/llama.cpp`, и клиент находит её сам.
- Свой бинарник: `export ARCHONITY_LLAMA_SERVER=<путь>/llama-server`.
- Docker-образа ровно этой сборки нет: `ghcr.io/ggml-org/llama.cpp:server-cuda-*` собираются по ночам из других коммитов.
- Для A100 (sm80) в релизной сборке есть только PTX. Ядра CUDA компилирует драйвер при первом запуске, поэтому первые запросы идут дольше. Без этого шага — сборка из исходников того же коммита:

  ```bash
  git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp && git checkout ba3c05f71da85cd0439e84ba42b0478b24d5db16
  cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=80 && cmake --build build -j --target llama-server
  export ARCHONITY_LLAMA_SERVER=$PWD/build/bin/llama-server
  ```

## Что из кеша, что заново

- S0–S7 целиком из кеша (`cache/llm/`, `cache/emb/`). Сервер не поднимается, выдача совпадает с рекордом байт в байт.
- На новом сценарии из кеша берутся профиль проекта (ответ LLM) и векторы обработчиков.
- Заново считаются векторы шагов нового сценария (эмбеддер) и ответы LLM на его шаги. Новые ответы дописываются в `cache/llm/`, повторный прогон идёт из кеша.
- Лог сервера — `output/llama-server.log`.

## Память и параметры сервера

- LLM около 20 ГБ (веса 17.7 ГБ, KV `q8_0` на 32k токенов), эмбеддер около 8 ГБ (bf16), оба на GPU. Для A100 это оценка. Замеры на 16 ГБ — в последнем разделе.
- Сервер по умолчанию: `--fit off -ngl 999 -fa 1 -ctk q8_0 -ctv q8_0 -c 32768` — все слои на GPU, без `-ncmoe`. Вручную тот же сервер запускает `scripts/start_llm.sh`.
- Уже запущенный сервер на `ARCHONITY_LLM_URL` клиент использует как есть.

| Переменная | Что делает |
|---|---|
| `ARCHONITY_LLAMA_SERVER` | путь к `llama-server` или к единому `llama`; `off` — без автозапуска |
| `ARCHONITY_LLAMA_ARGS` | аргументы сервера после умолчаний, перекрывают их |
| `ARCHONITY_LLAMA_START_TIMEOUT` | сколько ждать `/health`, с (по умолчанию 1800) |
| `ARCHONITY_LLM_URL` | адрес сервера, по умолчанию `http://127.0.0.1:8080`; автозапуск — только для loopback |
| `ARCHONITY_EMBED_DEVICE` | устройство эмбеддера: `cuda` или `cpu`; по умолчанию GPU, если он есть |

## Видеокарта 16 ГБ (машина команды)

LLM и эмбеддер вместе в 16 ГБ не помещаются:

- `ARCHONITY_LLAMA_ARGS="-ncmoe 7"` — часть экспертов MoE в RAM;
- `ARCHONITY_EMBED_DEVICE=cpu` — эмбеддер на процессоре.

Замер 21.10 на RTX 5070 Ti 16 ГБ, S0 с пустым кешем LLM. Автозапуск `llama server` с `-ncmoe 7`: загрузка модели с диска заняла 284 с, весь прогон — 340 с (11 ответов сервера, IoU S0 = 1.0). Пик видеопамяти — 15.4 ГБ, после выхода — 0. Эмбеддер на `cuda`: загрузка из `models/` 155 с, пик 7.7 ГиБ. Векторы совпали с `cache/emb`, косинус 0.998–1.007 — разница в округлении bf16.

Сервер вручную — `scripts/start_llm.ps1`. Уже скачанную модель кладёт в `models/` команда `python scripts/fetch_models.py --from <путь>/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf`: она проверяет sha256 и ставит жёсткую ссылку или копию. Для эмбеддера `--only embedder --from <кеш HF>/snapshots/<ревизия>`.
