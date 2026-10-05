import hashlib
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOWNLOADS = [
    ("YuNet 2023mar", "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx", ROOT / "person_face/models/face_detection_yunet_2023mar.onnx"),
    ("SFace 2021dec", "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx", ROOT / "person_face/models/face_recognition_sface_2021dec.onnx"),
    ("YOLO11n", "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt", ROOT / "person_face/models/yolo11n.pt"),
    ("MediaPipe Hand Landmarker float16 v1", "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task", ROOT / "hands_gestures/models/hand_landmarker.task"),
    ("MediaPipe Pose Landmarker Lite float16 v1", "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task", ROOT / "hands_gestures/models/pose_landmarker_lite.task"),
    ("MediaPipe official hand sample", "https://storage.googleapis.com/mediapipe-tasks/hand_landmarker/woman_hands.jpg", ROOT / "shared/test_assets/woman_hands.jpg"),
    ("OpenCV official Lena sample", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/lena.jpg", ROOT / "shared/test_assets/lena.jpg"),
    ("Ultralytics official bus sample", "https://github.com/ultralytics/assets/raw/refs/heads/main/im/bus.jpg", ROOT / "shared/test_assets/bus.jpg"),
    ("Wikimedia closed fist test, CC BY-SA 4.0", "https://commons.wikimedia.org/wiki/Special:Redirect/file/Closed_fist.jpg", ROOT / "shared/test_assets/closed_fist.jpg"),
    ("Wikimedia pointing person test, public domain", "https://commons.wikimedia.org/wiki/Special:Redirect/file/Man_pointing_with_his_finger.jpg", ROOT / "shared/test_assets/pointing_person.jpg"),
]

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()

def download(name, url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size < 1024:
        temporary = target.with_suffix(target.suffix + ".part")
        print(f"Скачивание {name}: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "Automatic-Mafia-Experiments/1.0 (local model verification)"})
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output: shutil.copyfileobj(response, output)
        temporary.replace(target)
    return {"name": name, "url": url, "path": str(target.relative_to(ROOT)), "bytes": target.stat().st_size, "sha256": sha256(target)}

def main():
    records = [download(*item) for item in DOWNLOADS]
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "files": records}
    (ROOT / "MODEL_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Манифест: {ROOT / 'MODEL_MANIFEST.json'}")

if __name__ == "__main__": main()
