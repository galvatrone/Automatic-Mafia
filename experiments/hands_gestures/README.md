# hands_gestures

Изолированный стенд жестов. Рабочий путь использует MediaPipe Hand Landmarker float16 и Pose Landmarker Lite; отсутствие веса показывает инструкцию и не затрагивает игру.

## Запуск

```bash
cd "/home/lost/Documents/Automatic Mafia/experiments/hands_gestures"
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py --source 0
.venv/bin/python app.py --source /path/video.mp4
```

Точная рекомендуемая установка — `../setup_experiments.sh --models`. Проверяются 21 точка кисти, ладонь, кулак, указательный жест, направление и плечо-локоть-запястье. Рука привязывается к `body-N` только при достаточной близости и отрыве от второго кандидата; иначе владелец остаётся неопределённым.

`sounddevice` удаляется из этого venv намеренно: он зависает на PortAudio данной машины и не нужен Vision API. RTMPose/MMPose остаётся следующим кандидатом после базового профилирования.
