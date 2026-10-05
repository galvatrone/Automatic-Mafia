# person_face

Изолированный стенд обнаружения лиц/людей и трекинга. Он не импортирует `automatic_mafia` и не читает базу лиц основной игры. Рабочий путь: YuNet -> SFace 128D embedding -> экспериментальная gallery; YOLO11n -> ByteTrack.

## Запуск

```bash
cd "/home/lost/Documents/Automatic Mafia/experiments/person_face"
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py --source 0
# или видео/RTSP: .venv/bin/python app.py --source /path/video.mp4
```

Для полной установки используйте `../setup_experiments.sh --models`: он ставит официальный CPU-only PyTorch и Ultralytics без CUDA-пакетов. YuNet без SFace не считается рабочим identity-путём: приложение требует оба веса и формирует 128D embedding.

`results/participants.json` — экспериментальный обмен с `virtual_table`. Он содержит постоянные SFace-теги `P001` и временные ByteTrack-теги `track-N`, фотографии-кропы и timestamp, но не роли или игровые номера.

`results/` предназначен для CSV/скриншотов измерений и не содержит рабочие данные игры.
