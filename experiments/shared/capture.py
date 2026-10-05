import time
from collections import deque
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from .metrics import RuntimeMetrics
from .observations import FramePacket

def parse_source(value: str):
    value = str(value).strip()
    return int(value) if value.isdigit() else value

class CaptureThread(QThread):
    packet_ready = Signal(object)
    status = Signal(str)

    def __init__(self, source: str = "0", camera_id: str = "camera-0", processor=None, parent=None):
        super().__init__(parent)
        self.source = source
        self.camera_id = camera_id
        self.processor = processor
        self._running = False

    def stop(self):
        self._running = False
        self.wait(1500)

    def run(self):
        try:
            import cv2
        except ImportError:
            self.status.emit("OpenCV не установлен")
            return
        capture = cv2.VideoCapture(parse_source(self.source))
        if not capture.isOpened():
            self.status.emit(f"Источник недоступен: {self.source}")
            return
        self.status.emit(f"Источник открыт: {self.source}")
        self._running = True
        frame_id = 0
        metrics = RuntimeMetrics()
        processing_ms = deque(maxlen=240)
        try:
            while self._running:
                ok, frame = capture.read()
                if not ok:
                    self.status.emit("Источник завершён или кадр не прочитан")
                    break
                frame_id += 1
                packet = FramePacket(self.camera_id, frame_id, time.time_ns(), frame)
                packet.metrics = metrics.tick()
                if self.processor:
                    try:
                        inference_started = time.perf_counter()
                        packet = self.processor(packet)
                        processing_ms.append((time.perf_counter() - inference_started) * 1000)
                        ordered = sorted(processing_ms)
                        packet.metrics["inference_median_ms"] = ordered[len(ordered) // 2]
                        packet.metrics["inference_p95_ms"] = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
                    except Exception as exc:  # adapter failures stay visible in the UI
                        self.status.emit(f"Адаптер: {exc}")
                self.packet_ready.emit(packet)
                self.msleep(1)
        finally:
            capture.release()
            self.status.emit("Источник остановлен")
