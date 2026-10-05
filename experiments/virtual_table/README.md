# virtual_table

Самостоятельный стенд схемы стола. `person_id`, `seat_id` и `player_number` разделены; схема сохраняется в `results/table_schema.json`, не в базе Automatic Mafia.

## Запуск

```bash
cd "/home/lost/Documents/Automatic Mafia/experiments/virtual_table"
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

По умолчанию стенд загружает `../person_face/results/participants.json`, если он существует. Можно выбрать другой файл кнопкой или параметром `--participants-file`; ручной список из `config.json` остаётся запасным.

Кликните стартового участника, затем соседей по желаемому обходу. Повторный клик по старту замыкает цикл. Кнопка «Подтвердить круг» проверяет единый цикл и только после этого выдаёт номера 1…N. Режим предложения использует геометрию расположения на схеме как подсказку, но не назначает порядок автоматически.
