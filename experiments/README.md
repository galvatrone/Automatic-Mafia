# Automatic Mafia camera experiments

Три независимых стенда. Они не импортируют `automatic_mafia`, не читают и не изменяют рабочую базу лиц или сохранённые партии.

## Установка

Используется Python 3.11: MediaPipe и нативные ML-пакеты надёжнее поддерживают его, чем системный Python 3.14.

```bash
cd "/home/lost/Documents/Automatic Mafia/experiments"
./setup_experiments.sh --models
```

Скрипт создаёт собственные `.venv` во всех трёх папках, ставит CPU-only PyTorch, PySide6 Essentials и скачивает минимальный набор весов. Точные установленные версии находятся в `*/requirements.lock.txt`, URL и SHA-256 весов — в `MODEL_MANIFEST.json`, условия — в `MODEL_LICENSES.md`.

## Запуск

```bash
python3.11 launcher.py all --source 0
python3.11 launcher.py person-face --source shared/test_assets/common_test.mp4
python3.11 launcher.py hands-gestures --source shared/test_assets/common_test.mp4
python3.11 launcher.py virtual-table --participants-file person_face/results/participants.json
```

Источник может быть индексом USB-камеры, путём видео либо RTSP/HTTP URL.

## Проверка моделей

```bash
person_face/.venv/bin/python person_face/verify.py --video shared/test_assets/common_test.mp4 --max-frames 90
hands_gestures/.venv/bin/python hands_gestures/verify.py --video shared/test_assets/common_test.mp4 --max-frames 90
virtual_table/.venv/bin/python virtual_table/verify.py
```

Проверенный маршрут:

```text
YuNet face -> SFace embedding -> P001 stable identity
YOLO11n person -> ByteTrack track-N temporary identity
participants.json -> manual table cycle -> player numbers

Hand Landmarker -> 21 landmarks -> held gesture
Pose Landmarker -> body wrists -> owner only when unambiguous
```

`person_id`, `track_id`, `seat_id` и `player_number` остаются разными сущностями. Временный `track-N` не выдаётся за постоянную личность.

## Известные особенности

- CUDA не используется: установлен `torch +cpu`, `torch.cuda.is_available()` возвращает `False`.
- `sounddevice` намеренно удалён только из venv жестов: PortAudio зависает на этой машине, а MediaPipe Vision умеет работать без необязательного аудиомодуля.
- `pip check` сообщает об отсутствующих необязательных пакетах Ultralytics (`opencv-python`, platform/NVML) и MediaPipe (`sounddevice`). Фактически используются `opencv-contrib-python(-headless)`, CPU PyTorch и локальные веса; проверенный inference проходит.
- Без `/dev/video*` живая камера не проверена. Графические окна и настоящий video inference запускались в текущем Wayland/X11-сеансе.
- Общее видео составлено из трёх статичных официальных изображений. Это одинаковый нагрузочный smoke-тест, но не оценка точности, движения или разных ракурсов.
