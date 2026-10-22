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

## Прогон с моделями (22.10)

RTX 5070 Ti 16 ГБ, `ARCHONITY_LLAMA_ARGS="-ncmoe 7 -dev Vulkan1"`, ветка слита с `dev` (код M4 как в `dev`). Кеша для этих текстов не было: 405 ответов LLM от сервера (1 из кеша), векторов шагов докачано 72 (в `cache/emb` было 520, стало 592). Прогон 1103 с, из них сервер LLM 1063 с, пик видеопамяти 15.8 ГБ, ошибок и шагов без ответа нет, режим M1 `full`, все 103 шага выбраны моделью.

Команды (как в предыдущей редакции):

```powershell
$env:PYTHONUTF8=1; $env:ARCHONITY_LLAMA_ARGS="-ncmoe 7 -dev Vulkan1"
python run_eval.py --scenarios "eval/paraphrase/scenarios/*.json" --no-eval -o output/paraphrase/submission.json
python hackaton/tt-challenge/platform/evaluate_golden.py eval/paraphrase/gold.json output/paraphrase/submission.json
python -m engine.grounding.grounder eval/paraphrase/scenarios/S*.json --eval eval/m1_steps.json --embed-model
```

### Балл

| Сценарий | S0 | S1 | S2 | S3 | S4 | S5 | S6 | S7 | среднее |
|---|---|---|---|---|---|---|---|---|---|
| перефразированные | 1.000 | 0.852 | 0.973 | 0.852 | 0.880 | 0.965 | 0.827 | 0.840 | **0.899** |

По видам рёбер (среднее по сценариям): `executes` 0.908, `calls` 0.871, `remote` 0.872, `data` 0.944. Полнота везде 1.00 (S7 `calls` — 0.99): потери только в точности, то есть ошибка M1 даёт лишнее исполнение чужого обработчика, а не пропуск. Без моделей было 0.477, с моделями 0.899; исходные тексты дают 1.0.

### M1

Точность top-1 на шаге: 92/103 = 0.893; верный обработчик среди кандидатов: 82/103. Параметры шагов: 47/47 = 1.000. Ошибок 11, они повторяют три формулировки:

| Шаг | Что выбрала модель | Верный обработчик | Шагов |
|---|---|---|---|
| «Find GaoTie/DongChe (high-speed) trains from … to …» | `TravelPlanController#getByQuickest` | `TravelController#queryInfo` | S1.2, S3.2, S4.4, S6.8, S7.2 |
| «Reload my orders» | `OrderController#findAllOrder` (S2 — `OrderOtherController`) | `queryOrdersForRefresh` | S1.7, S2.7, S2.12, S7.5 |
| «Reload my orders, showing only those bought today» | `OrderController#queryOrders` | `queryOrdersForRefresh` | S7.14 |
| «Create a new passenger account …» | `AdminUserController#addUser` | `UserController#registerUser` | S4.1 |

Для всех, кроме S7.14, верного обработчика нет среди кандидатов M1: ни BM25, ни векторы его не находят (Reload — `queryOrdersForRefresh`, Find … trains — `queryInfo`). Чинить надо поиск кандидатов, а не выбор LLM. Совпадает с шагом «Reload my orders on high-speed GaoTie/DongChe trains» из замера 21.10 (`docs/run_on_a100.md`).

### Проверки

- Выдача S0–S7 оригиналов прежняя: `python run_eval.py --require-cache` даёт sha256 `94463c41a72c244fc548cbb52d009cff7c65f44ad5e682b7176a156cb66a5a08`.
- В `cache/` добавлены 405 файлов `cache/llm/*.json` (читаются, поле `key` на месте) и обновлён `cache/emb/qwen3-4b/vectors.npz` (592 вектора, NaN нет). Повтор M1 на перефразировках идёт целиком из кеша: grounder сообщил «кеш 406, вызовов 0».
