# Инструменты слепой разметки

Скрипты для ручной разметки сценария по [заданию](../../docs/researches/blind_annotation_task.md). Пайплайн, `output/`, `cache/`, `data/` и `engine/` они не читают, поэтому слепоту не нарушают. Запуск — с `PYTHONUTF8=1` (см. [environment_guide.md](../../docs/environment_guide.md)).

```bash
SK=hackaton/tt-challenge/skeleton/trainticket.json.gz

# методы по подстроке ID; call_site метода с целями рёбер; входящие рёбра
python scripts/blind/sk.py $SK m  "OrderServiceImpl#create"
python scripts/blind/sk.py $SK cs "order.service.OrderServiceImpl#create("
python scripts/blind/sk.py $SK in "order.service.OrderServiceImpl#create("

# строки таблицы дампа (дамп распаковать: zcat context/db-after-warmup.sql.gz > dump.sql)
python scripts/blind/dump.py dump.sql ts_order.orders 4d2a46c7

# собрать ответ из компактного списка рёбер (формат — в docstring build.py)
python scripts/blind/build.py $SK S2 edges.txt eval/blind/S2.json

# сверка: рёбра скелета от исполненных методов, которых нет в ответе
python scripts/blind/crosscheck.py $SK eval/blind/S2.json S2
```

Что важно (опыт S3, [notes.md](../../eval/blind/notes.md)):

- Сборщик принимает подстроку ID, только если она однозначна. Неоднозначность — ошибка, ID в ответе всегда из `nodes`.
- `crosscheck.py` запускать после каждой разметки. В S3 так нашлись шесть пропущенных рёбер к `StringUtils#String2Lower`: их вызывают рукописные геттеры ts-common.
- Скелет не разрешает цепочки с неизвестным приёмником (`x.getTripId().toString()`, `SeatClass.FIRSTCLASS.getCode()`). `sk.py cs` показывает их с типом `None`, их нужно разрешать вручную.
