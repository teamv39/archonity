# Рекорды платформы

Лучшая посылка NSUTS — эталон для сравнения перед каждой новой посылкой ([agent_lessons.md](../../docs/agent_lessons.md), раздел 4):

```powershell
$env:PYTHONUTF8=1; python scripts/compare_submissions.py eval/records/submission_p27_1.00000.json <ваш>/submission.json --show 20
```

Не изменилось ни одного ребра — посылка ничего не проверит.

## Текущий рекорд

`submission_p27_1.00000.json` — **1.00000**, 19.10. Это выдача кода (`python run_eval.py --executor ir --m4-unresolved-calls emit --no-server`, ветка `feature/82-unbound-path-variable`); по множествам рёбер она совпадает с посылкой 27 (ручной зонд, итог 1.00000). Отправка самой выдачи — посылка 28.

- По сценариям: все 1.000.
- sha256 `94463c41a72c244fc548cbb52d009cff7c65f44ad5e682b7176a156cb66a5a08` — эталон воспроизводимости.
- Путь: [code_record_drift.md](../../docs/researches/code_record_drift.md), [reaching_1_0.md](../../docs/researches/reaching_1_0.md).

| Сценарий | Всего | executes | calls | remote | data |
|---|---|---|---|---|---|
| S0 | 65 | 34 | 24 | 0 | 7 |
| S1 | 426 | 167 | 184 | 36 | 39 |
| S2 | 442 | 163 | 207 | 38 | 34 |
| S3 | 386 | 152 | 169 | 30 | 35 |
| S4 | 447 | 173 | 195 | 38 | 41 |
| S5 | 544 | 188 | 268 | 51 | 37 |
| S6 | 413 | 163 | 178 | 36 | 36 |
| S7 | 392 | 156 | 174 | 31 | 31 |

Прежние рекорды в истории git: посылка 17 (0.99457, ручная, `submission_p17_0.99457.json`), посылка 20 (0.99457, выдача кода, sha256 `3c329a55…4151`).

## Как обновлять

Новый рекорд — новый файл `submission_p<номер посылки>_<балл>.json` и строка здесь. Старый файл удалить: он остаётся в истории git. Таблица посылок — в [roadmap.md](../../docs/roadmap.md).
