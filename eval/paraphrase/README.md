# Перефразированные S0–S7

Тексты S0–S7 другими словами: тот же сценарий, те же факты, другие формулировки. Закрытые сценарии организаторов будут написаны не нашими словами, а эталона для них у нас нет. Здесь эталон есть, поэтому это единственный замер всего конвейера на незнакомом тексте с настоящими рёбрами (roadmap, П2, «Перефразированные шаги S1–S7»).

## Файлы

- `scenarios/S0.json` … `S7.json` — формат `hackaton/tt-challenge/scenarios/`, ID те же, что у оригиналов: так подходят `eval/m1_steps.json` и сравнение с рекордом. Ни один текст шага не совпадает с оригиналом дословно, переписаны и `title`, и `description`.
- `gold.json` — эталон в формате `platform/evaluate_golden.py`: S0 — `gold/S0.json` организаторов, S1–S7 — рекорд `eval/records/submission_p27_1.00000.json` (1.00000 на платформе при точности 1e-5, то есть совпадает с эталоном ребро в ребро). Без ключа `ids`: формат ID оценщик не проверяет. Проверка: рекорд против `gold.json` — 1.000.

## Как переписано

- Сохранено всё, от чего зависит выбор обработчика и параметры: города, дата, тип поезда (`GaoTie/DongChe`, `'Other'`), класс места, еда (на борту или со станции), страховка, вес багажа, статусы фильтров, даты, ожидаемый отказ, числа шагов администратора, имена `Ning Bo`, `GaoTieSix`, `G9101`.
- Заменены глаголы и обороты: Book → Reserve, Refresh the list of orders → Reload my orders, Search → Find / Look for, Open the details → Show the details, Collect the ticket → Pick up the ticket, Enter the station → Go through the station entrance, Check the price → See how much the order costs, internal account balance → internal account balance / the money on the internal account, Ask how much would be refunded → Find out how much money would come back, regular → ordinary, food → meal.
- Это стресс-тест: организаторы, скорее всего, пишут своим словарём (Book, Refresh, Collect), так что балл здесь — нижняя оценка для закрытых сценариев по формулировкам. Новых обработчиков он не проверяет, это делают `eval/own/`.

## Замер без моделей (22.10)

| | M1 BM25: top-1 | верный среди кандидатов | итог без LLM и эмбеддера |
|---|---|---|---|
| исходные S0–S7 | 61/103 | 92/103 | 0.623 |
| перефразированные | 37/103 | 62/103 | 0.477 |

BM25 не знает синонимов: Reserve не находит `preserve`, Reload — `queryOrdersForRefresh`, Find … trains — `queryInfo`. Сколько из этого закрывают векторы и LLM — вопрос прогона на GPU.

## Прогон на GPU (Миша)

Ответов LLM и векторов этих шагов в `cache/` нет. Сервер поднимается сам на первом промахе, эмбеддер выгружается до первого вызова LLM ([run_on_a100.md](../../docs/run_on_a100.md), «Видеокарта 16 ГБ»):

```powershell
$env:PYTHONUTF8=1; $env:ARCHONITY_LLAMA_ARGS="-ncmoe 7"
python run_eval.py --scenarios "eval/paraphrase/scenarios/*.json" --no-eval -o output/paraphrase/submission.json
python hackaton/tt-challenge/platform/evaluate_golden.py eval/paraphrase/gold.json output/paraphrase/submission.json
python -m engine.grounding.grounder eval/paraphrase/scenarios/S*.json --eval eval/m1_steps.json --embed-model
```

Первая команда — весь конвейер и новые записи кеша, вторая — балл по сценариям и видам рёбер, третья — точность M1 по шагам (из кеша, после первой). Нужно в `cache/` закоммитить новые `cache/llm/*.json` и `cache/emb/qwen3-4b/vectors.npz`, проверить, что выдача S0–S7 оригиналов прежняя (`python run_eval.py --require-cache`, sha256 `94463c41…`), и записать в этот README итог, балл по сценариям и ошибки M1.
