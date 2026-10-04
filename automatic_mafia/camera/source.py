import platform
from typing import List

import cv2

from automatic_mafia.config import CAPTURE_FPS, CAPTURE_HEIGHT, CAPTURE_WIDTH


def open_camera(index: int):
    system = platform.system().lower()
    backends = [None]
    if system == "windows":
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, None]
    elif hasattr(cv2, "CAP_V4L2"):
        backends = [cv2.CAP_V4L2, None]
    for backend in backends:
        cap = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, CAPTURE_FPS)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap
        cap.release()
    return None


def detect_cameras(limit: int = 4) -> List[int]:
    found = []
    for index in range(limit):
        cap = open_camera(index)
        if cap is not None:
            found.append(index)
            cap.release()
    return found or [0]
