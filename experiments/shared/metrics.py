import os
import time
from collections import deque

class RuntimeMetrics:
    def __init__(self, window=120):
        self.started = time.perf_counter()
        self.last = self.started
        self.frames = 0
        self.intervals = deque(maxlen=window)
        self._process = None
        try:
            import psutil
            self._process = psutil.Process(os.getpid())
        except ImportError:
            pass

    def tick(self):
        now = time.perf_counter()
        dt = now - self.last
        self.last = now
        self.frames += 1
        if dt > 0:
            self.intervals.append(dt)
        fps = 1 / (sum(self.intervals) / len(self.intervals)) if self.intervals else 0.0
        cpu = self._process.cpu_percent(None) if self._process else None
        memory = self._process.memory_info().rss / 1024 / 1024 if self._process else None
        return {"fps": fps, "cpu_percent": cpu, "memory_mb": memory, "frames": self.frames}
